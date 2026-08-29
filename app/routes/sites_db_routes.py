"""
Enhanced Routes for Sites DB page & dynamic CRUD, CSV import/upsert, and map performance APIs
"""

from flask import Blueprint, render_template, request, jsonify, session, make_response, flash, redirect, url_for, Response
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, viewer_blocked, json_response, csv_response, db_query, _no_cache
import psycopg2
import psycopg2.extras
import psycopg2.errors
import logging
import csv
import io

logger = logging.getLogger(__name__)

sites_db_bp = Blueprint("sites_db", __name__)

TABLE_NAME = "sites_db"


def _get_table_schema(cur):
    """Retrieve dynamic column metadata from information_schema for sites_db."""
    cur.execute("""
        SELECT 
            c.column_name,
            c.data_type,
            c.is_nullable,
            c.column_default,
            c.character_maximum_length
        FROM information_schema.columns c
        WHERE c.table_name = %s
        ORDER BY c.ordinal_position
    """, (TABLE_NAME,))
    
    columns = cur.fetchall()
    
    # Check for primary key / unique constraint
    cur.execute("""
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
          AND tc.table_name = %s
    """, (TABLE_NAME,))
    pk_rows = cur.fetchall()
    pk_cols = [r[0] for r in pk_rows]

    col_names = [c[0] for c in columns]
    if not pk_cols or "SiteID_v2" not in pk_cols:
        if "SiteID_v2" in col_names:
            pk_cols = ["SiteID_v2"]
        elif "SiteID" in col_names:
            pk_cols = ["SiteID"]
        elif col_names:
            pk_cols = [col_names[0]]

    schema_info = []
    for col in columns:
        c_name, d_type, is_null, default_val, max_len = col
        schema_info.append({
            "name": c_name,
            "type": d_type,
            "nullable": is_null == "YES",
            "default": default_val,
            "max_length": max_len,
            "is_pk": c_name in pk_cols
        })
        
    return schema_info, pk_cols


@sites_db_bp.route("/database/sites_db")
@login_required
@viewer_blocked
def sites_db_page():
    response = make_response(render_template(
        "sites_db.html",
        username=session.get("username"),
        role=session.get("role", "viewer")
    ))
    return _no_cache(response)


@sites_db_bp.route("/api/sites_db/schema")
@login_required
@viewer_blocked
def api_sites_db_schema():
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            return json_response({
                "status": "success",
                "table": TABLE_NAME,
                "columns": schema,
                "primary_keys": pk_cols
            })
    except Exception as e:
        logger.exception("Error getting sites_db schema")
        return json_response({"status": "error", "message": str(e)}, 500)


@sites_db_bp.route("/api/sites_db/data")
@login_required
@viewer_blocked
def api_sites_db_data():
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(250, max(5, int(request.args.get("limit", 25))))
        search = request.args.get("search", "").strip()
        sort_by = request.args.get("sort_by", "").strip()
        sort_order = "DESC" if request.args.get("sort_order", "asc").lower() == "desc" else "ASC"

        offset = (page - 1) * limit

        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            valid_cols = [c["name"] for c in schema]

            where_clauses = []
            params = []

            if search:
                text_like_cols = [
                    c["name"] for c in schema 
                    if c["type"] in ("character varying", "text", "character", "integer")
                ]
                search_terms = []
                for col in text_like_cols:
                    search_terms.append(f'"{col}"::text ILIKE %s')
                    params.append(f"%{search}%")
                if search_terms:
                    where_clauses.append("(" + " OR ".join(search_terms) + ")")

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # Count total matching rows
            count_query = f'SELECT COUNT(*) FROM "{TABLE_NAME}"{where_sql}'
            cur.execute(count_query, params)
            total_records = cur.fetchone()[0]

            # Sorting
            if sort_by and sort_by in valid_cols:
                order_sql = f'ORDER BY "{sort_by}" {sort_order} NULLS LAST'
            elif pk_cols:
                order_sql = f'ORDER BY "{pk_cols[0]}" {sort_order}'
            else:
                order_sql = f'ORDER BY 1 {sort_order}'

            # Data query
            select_cols = ", ".join([f'"{c}"' for c in valid_cols])
            data_query = f'SELECT {select_cols} FROM "{TABLE_NAME}"{where_sql} {order_sql} LIMIT %s OFFSET %s'
            cur.execute(data_query, params + [limit, offset])

            rows = cur.fetchall()

            # Format rows as list of dicts
            data = []
            for row in rows:
                row_dict = {}
                for idx, col in enumerate(valid_cols):
                    row_dict[col] = row[idx]
                data.append(row_dict)

            total_pages = (total_records + limit - 1) // limit if total_records > 0 else 1

            return json_response({
                "status": "success",
                "data": data,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total_records": total_records,
                    "total_pages": total_pages
                }
            })
    except Exception as e:
        logger.exception("Error querying sites_db data")
        return json_response({"status": "error", "message": str(e)}, 500)


@sites_db_bp.route("/api/sites_db/map")
@login_required
@viewer_blocked
def api_sites_db_map():
    """Optimized lightweight map API returning only coordinates, SiteID_v2, and provider."""
    try:
        search = request.args.get("search", "").strip()

        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            valid_cols = [c["name"] for c in schema]

            lat_col = next((c for c in valid_cols if c.lower() == "latitude"), "latitude")
            lng_col = next((c for c in valid_cols if c.lower() == "longitude"), "longitude")
            id_col = "SiteID_v2" if "SiteID_v2" in valid_cols else ("SiteID" if "SiteID" in valid_cols else valid_cols[0])
            provider_col = next((c for c in valid_cols if c.lower() == "provider"), None)

            cur.execute(f'SELECT COUNT(*) FROM "{TABLE_NAME}"')
            total_count = cur.fetchone()[0]

            where_clause = f"""
                WHERE "{lat_col}" IS NOT NULL 
                  AND "{lng_col}" IS NOT NULL 
                  AND "{lat_col}" BETWEEN -90 AND 90
                  AND "{lng_col}" BETWEEN -180 AND 180
            """
            params = []
            if search:
                where_clause += f' AND "{id_col}"::text ILIKE %s'
                params.append(f"%{search}%")

            if provider_col:
                query = f'SELECT "{id_col}", "{lat_col}", "{lng_col}", COALESCE("{provider_col}", \'Telkomsel\') FROM "{TABLE_NAME}" {where_clause}'
                cur.execute(query, params)
                rows = cur.fetchall()
                sites = [
                    {"id": r[0], "lat": r[1], "lng": r[2], "provider": str(r[3]).strip() if r[3] else "Telkomsel"}
                    for r in rows
                ]
            else:
                query = f'SELECT "{id_col}", "{lat_col}", "{lng_col}" FROM "{TABLE_NAME}" {where_clause}'
                cur.execute(query, params)
                rows = cur.fetchall()
                sites = [
                    {"id": r[0], "lat": r[1], "lng": r[2], "provider": "Telkomsel"}
                    for r in rows
                ]

            valid_count = len(sites)
            invalid_count = max(0, total_count - valid_count)

            providers_set = set()
            for s in sites:
                if s.get("provider"):
                    providers_set.add(s["provider"])
            if not providers_set:
                providers_set.add("Telkomsel")

            providers = sorted(list(providers_set), key=lambda x: (x.lower() != "telkomsel", x.lower()))

            return json_response({
                "status": "success",
                "sites": sites,
                "providers": providers,
                "total_count": total_count,
                "valid_count": valid_count,
                "invalid_count": invalid_count
            })
    except Exception as e:
        logger.exception("Error getting sites map data")
        return json_response({"status": "error", "message": str(e)}, 500)


@sites_db_bp.route("/api/sites_db/detail/<path:site_id>")
@login_required
@viewer_blocked
def api_sites_db_detail(site_id):
    """Fetch complete site metadata for map popup on-demand."""
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            valid_cols = [c["name"] for c in schema]
            id_col = "SiteID_v2" if "SiteID_v2" in valid_cols else ("SiteID" if "SiteID" in valid_cols else valid_cols[0])

            select_cols = ", ".join([f'"{c}"' for c in valid_cols])
            query = f'SELECT {select_cols} FROM "{TABLE_NAME}" WHERE "{id_col}"::text = %s LIMIT 1'
            cur.execute(query, [site_id])
            row = cur.fetchone()

            if not row:
                return json_response({"status": "error", "message": "Site not found"}, 404)

            site_detail = {valid_cols[i]: row[i] for i in range(len(valid_cols))}
            return json_response({"status": "success", "detail": site_detail})
    except Exception as e:
        logger.exception("Error fetching site detail")
        return json_response({"status": "error", "message": str(e)}, 500)


@sites_db_bp.route("/api/sites_db/autocomplete")
@login_required
@viewer_blocked
def api_sites_db_autocomplete():
    """Autocomplete suggestions for SiteID_v2 (max 10 prefix matches)."""
    try:
        q = request.args.get("q", "").strip()
        if not q or len(q) < 1:
            return json_response({"status": "success", "suggestions": []})

        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            valid_cols = [c["name"] for c in schema]
            id_col = "SiteID_v2" if "SiteID_v2" in valid_cols else ("SiteID" if "SiteID" in valid_cols else valid_cols[0])

            query = f"""
                SELECT DISTINCT "{id_col}"
                FROM "{TABLE_NAME}"
                WHERE "{id_col}"::text ILIKE %s
                ORDER BY "{id_col}" ASC
                LIMIT 10
            """
            cur.execute(query, [f"{q}%"])
            rows = cur.fetchall()
            suggestions = [r[0] for r in rows if r[0]]

            return json_response({"status": "success", "suggestions": suggestions})
    except Exception as e:
        logger.exception("Error fetching autocomplete suggestions")
        return json_response({"status": "error", "message": str(e)}, 500)


from datetime import datetime


def _normalize_val(val, d_type):
    """
    Normalize value for semantic comparison.
    - None, '', and 'null' (case-insensitive) are normalized to None.
    - Numeric floats are converted to float and rounded to 6 decimal places.
    - Integers are converted to int.
    - Strings are stripped of leading/trailing whitespace.
    """
    if val is None:
        return None
    
    if isinstance(val, (int, float)):
        d_type_lower = (d_type or "").lower()
        if "int" in d_type_lower:
            return int(val)
        return round(float(val), 6)
    
    val_str = str(val).strip()
    if val_str == "" or val_str.lower() == "null":
        return None
    
    d_type_lower = (d_type or "").lower()
    if "int" in d_type_lower:
        try:
            return int(float(val_str))
        except (ValueError, TypeError):
            return val_str
    elif any(t in d_type_lower for t in ("float", "double", "numeric", "real", "decimal")):
        try:
            return round(float(val_str), 6)
        except (ValueError, TypeError):
            return val_str
            
    return val_str


def _format_display_val(val):
    if val is None:
        return "NULL"
    return str(val)


@sites_db_bp.route("/api/sites_db/export_csv")
@login_required
@viewer_blocked
def api_sites_db_export_csv():
    """Export complete sites_db data dynamically to CSV with UTF-8 encoding."""
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            valid_cols = [c["name"] for c in schema]
            id_col = pk_cols[0] if pk_cols else "SiteID_v2"
            
            select_cols = ", ".join([f'"{c}"' for c in valid_cols])
            cur.execute(f'SELECT {select_cols} FROM "{TABLE_NAME}" ORDER BY "{id_col}" ASC')
            rows = cur.fetchall()
            
            output = io.StringIO()
            output.write('\ufeff')  # UTF-8 BOM for seamless Excel compatibility
            writer = csv.writer(output)
            writer.writerow(valid_cols)
            
            for row in rows:
                clean_row = []
                for val in row:
                    clean_row.append("" if val is None else str(val))
                writer.writerow(clean_row)
                
            today_str = datetime.now().strftime("%Y-%m-%d")
            filename = f"sites_db_{today_str}.csv"
            
            resp = make_response(output.getvalue())
            resp.headers["Content-Type"] = "text/csv; charset=utf-8"
            resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
            return resp
    except Exception as e:
        logger.exception("Error exporting sites_db to CSV")
        return json_response({"status": "error", "message": str(e)}, 500)


@sites_db_bp.route("/api/sites_db/csv_template")
@login_required
@viewer_blocked
def api_sites_db_csv_template():
    """Download dynamic CSV header template matching sites_db schema."""
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            headers = [c["name"] for c in schema]
            
            # Example sample row
            sample_row = []
            for col in schema:
                cname = col["name"]
                if cname == "SiteID" or cname == "SiteID_v2":
                    sample_row.append("DEMO001")
                elif cname.lower() == "latitude":
                    sample_row.append("-6.2088")
                elif cname.lower() == "longitude":
                    sample_row.append("106.8451")
                elif cname.lower() == "tac":
                    sample_row.append("10001")
                elif cname.lower() == "nop":
                    sample_row.append("JAKARTA")
                elif cname.lower() == "rtpo":
                    sample_row.append("TO JAKARTA")
                elif cname.lower() == "kabupaten":
                    sample_row.append("JAKARTA PUSAT")
                elif cname.lower() == "provider":
                    sample_row.append("Telkomsel")
                else:
                    sample_row.append("SAMPLE")

            return csv_response([sample_row], headers, "sites_db_template.csv")
    except Exception as e:
        logger.exception("Error generating CSV template")
        return json_response({"status": "error", "message": str(e)}, 500)


@sites_db_bp.route("/api/sites_db/csv_compare", methods=["POST"])
@login_required
@viewer_blocked
def api_sites_db_csv_compare():
    """
    Parse CSV and compare against existing sites_db records without modifying database.
    Performs semantic normalization, detects duplicates, identifies unchanged/changed/new records.
    """
    try:
        if "file" not in request.files:
            return json_response({"status": "error", "message": "No CSV file provided"}, 400)

        file = request.files["file"]
        if not file.filename.lower().endswith(".csv"):
            return json_response({"status": "error", "message": "Invalid file format. Please upload a .csv file"}, 400)

        stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
        reader = csv.DictReader(stream)

        if not reader.fieldnames:
            return json_response({"status": "error", "message": "CSV file is empty or missing headers"}, 400)

        csv_headers = [h.strip() for h in reader.fieldnames if h]

        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            valid_cols = [c["name"] for c in schema]
            col_type_map = {c["name"]: c["type"] for c in schema}
            id_col = "SiteID_v2" if "SiteID_v2" in valid_cols else ("SiteID" if "SiteID" in valid_cols else valid_cols[0])

            if id_col not in csv_headers:
                return json_response({
                    "status": "error",
                    "message": f"Mandatory column '{id_col}' is missing from CSV headers"
                }, 400)

            unknown_cols = [h for h in csv_headers if h not in valid_cols]

            # Fetch all existing records from DB in a single efficient query
            select_cols = ", ".join([f'"{c}"' for c in valid_cols])
            cur.execute(f'SELECT {select_cols} FROM "{TABLE_NAME}" WHERE "{id_col}" IS NOT NULL')
            db_rows = cur.fetchall()

            # In-memory lookup map: site_id -> { col: val }
            db_map = {}
            for r in db_rows:
                row_dict = {valid_cols[i]: r[i] for i in range(len(valid_cols))}
                site_key = str(row_dict.get(id_col, "")).strip()
                if site_key:
                    db_map[site_key] = row_dict

            total_csv_rows = 0
            invalid_rows = []
            seen_site_counts = {}
            csv_rows_ordered = []

            for idx, row in enumerate(reader, start=2):
                total_csv_rows += 1
                raw_id = row.get(id_col)
                site_id_val = str(raw_id).strip() if raw_id is not None else ""

                if not site_id_val:
                    invalid_rows.append({
                        "row": idx,
                        "site_id": "",
                        "reason": f"Missing or empty {id_col}"
                    })
                    continue

                if site_id_val not in seen_site_counts:
                    seen_site_counts[site_id_val] = []
                seen_site_counts[site_id_val].append(idx)

                # Clean and extract valid fields from CSV row
                clean_row = {}
                for col in csv_headers:
                    if col in valid_cols:
                        v = row.get(col)
                        clean_row[col] = v.strip() if v is not None else None

                csv_rows_ordered.append((idx, site_id_val, clean_row))

            # Identify duplicates
            duplicate_records = []
            for s_id, row_idxs in seen_site_counts.items():
                if len(row_idxs) > 1:
                    duplicate_records.append({
                        "site_id": s_id,
                        "count": len(row_idxs),
                        "rows": row_idxs
                    })

            # Deduplicate deterministically (last occurrence wins)
            valid_map = {}
            for idx, site_id_val, clean_row in csv_rows_ordered:
                valid_map[site_id_val] = (idx, clean_row)

            # Compare each valid CSV row against database
            unchanged_sites = []
            changed_sites = []
            new_sites = []

            for site_id, (row_num, csv_row) in valid_map.items():
                if site_id not in db_map:
                    # New record to be inserted
                    new_sites.append({
                        "row_num": row_num,
                        "site_id": site_id,
                        "data": csv_row
                    })
                else:
                    db_row = db_map[site_id]
                    field_changes = []

                    # Check each column present in CSV that exists in DB
                    for col in csv_headers:
                        if col not in valid_cols:
                            continue
                        col_type = col_type_map.get(col, "text")
                        csv_norm = _normalize_val(csv_row.get(col), col_type)
                        db_norm = _normalize_val(db_row.get(col), col_type)

                        if csv_norm != db_norm:
                            field_changes.append({
                                "field": col,
                                "old_val": db_row.get(col),
                                "new_val": csv_row.get(col),
                                "old_display": _format_display_val(db_row.get(col)),
                                "new_display": _format_display_val(csv_row.get(col))
                            })

                    if field_changes:
                        changed_sites.append({
                            "row_num": row_num,
                            "site_id": site_id,
                            "changes": field_changes,
                            "changes_count": len(field_changes),
                            "new_data": csv_row,
                            "old_data": db_row
                        })
                    else:
                        unchanged_sites.append({
                            "row_num": row_num,
                            "site_id": site_id,
                            "data": db_row
                        })

            return json_response({
                "status": "success",
                "filename": file.filename,
                "summary": {
                    "total_csv_records": total_csv_rows,
                    "unique_sites": len(valid_map),
                    "unchanged_count": len(unchanged_sites),
                    "changed_count": len(changed_sites),
                    "new_count": len(new_sites),
                    "duplicate_count": len(duplicate_records),
                    "duplicate_rows_count": sum(d["count"] - 1 for d in duplicate_records),
                    "error_count": len(invalid_rows)
                },
                "unknown_columns": unknown_cols,
                "changed_sites": changed_sites,
                "new_sites": new_sites,
                "unchanged_sites": unchanged_sites,
                "duplicates": duplicate_records,
                "errors": invalid_rows,
                "columns": valid_cols,
                "id_column": id_col
            })
    except Exception as e:
        logger.exception("Error executing CSV comparison")
        return json_response({"status": "error", "message": f"CSV comparison failed: {str(e)}"}, 500)


@sites_db_bp.route("/api/sites_db/csv_confirm_import", methods=["POST"])
@login_required
@viewer_blocked
def api_sites_db_csv_confirm_import():
    """
    Execute transactional batch import of confirmed changed and new site records.
    Updates only changed records, inserts only new records, leaves unchanged records untouched.
    """
    try:
        payload = request.get_json() or {}
        changed_records = payload.get("changed_records", [])
        new_records = payload.get("new_records", [])

        if not changed_records and not new_records:
            return json_response({
                "status": "error",
                "message": "No new or updated records provided for import"
            }, 400)

        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            valid_cols = [c["name"] for c in schema]
            col_type_map = {c["name"]: c["type"] for c in schema}
            id_col = "SiteID_v2" if "SiteID_v2" in valid_cols else ("SiteID" if "SiteID" in valid_cols else valid_cols[0])

            updated_count = 0
            inserted_count = 0

            # 1. Process UPDATES for changed records
            for item in changed_records:
                site_id = item.get("site_id")
                new_data = item.get("new_data") or {}
                if not site_id or not new_data:
                    continue

                set_clauses = []
                update_vals = []

                for col in valid_cols:
                    if col in new_data and col != id_col:
                        val = new_data[col]
                        norm_val = _normalize_val(val, col_type_map.get(col, "text"))
                        set_clauses.append(f'"{col}" = %s')
                        update_vals.append(norm_val)

                if set_clauses:
                    update_vals.append(site_id)
                    update_sql = f'UPDATE "{TABLE_NAME}" SET {", ".join(set_clauses)} WHERE "{id_col}"::text = %s'
                    cur.execute(update_sql, update_vals)
                    updated_count += cur.rowcount

            # 2. Process INSERTS for new records
            if new_records:
                insert_cols = valid_cols
                cols_sql = ", ".join([f'"{c}"' for c in insert_cols])
                placeholders = ", ".join(["%s"] * len(insert_cols))
                insert_sql = f'INSERT INTO "{TABLE_NAME}" ({cols_sql}) VALUES ({placeholders})'

                insert_batch = []
                for item in new_records:
                    data = item.get("data") if "data" in item else item
                    if not data:
                        continue
                    row_vals = []
                    for col in insert_cols:
                        raw_v = data.get(col)
                        norm_v = _normalize_val(raw_v, col_type_map.get(col, "text"))
                        row_vals.append(norm_v)
                    insert_batch.append(tuple(row_vals))

                if insert_batch:
                    psycopg2.extras.execute_batch(cur, insert_sql, insert_batch, page_size=250)
                    inserted_count = len(insert_batch)

            # Transaction commit
            conn.commit()

            return json_response({
                "status": "success",
                "message": f"Successfully imported {updated_count + inserted_count} site changes ({inserted_count} inserted, {updated_count} updated).",
                "summary": {
                    "updated": updated_count,
                    "inserted": inserted_count,
                    "total_imported": updated_count + inserted_count
                }
            })
    except psycopg2.errors.UniqueViolation as ue:
        logger.exception("Unique constraint violation during CSV import")
        return json_response({
            "status": "error",
            "message": f"Import aborted due to duplicate key: {str(ue)}"
        }, 400)
    except Exception as e:
        logger.exception("Error executing confirmed CSV import")
        return json_response({"status": "error", "message": f"Import failed: {str(e)}"}, 500)


@sites_db_bp.route("/api/sites_db/csv_preview", methods=["POST"])
@login_required
@viewer_blocked
def api_sites_db_csv_preview():
    """Parse CSV, validate schema & headers, detect internal duplicates, check existing DB records."""
    return api_sites_db_csv_compare()


@sites_db_bp.route("/api/sites_db/csv_import", methods=["POST"])
@login_required
@viewer_blocked
def api_sites_db_csv_import():
    """Batch UPSERT CSV records into sites_db using INSERT ... ON CONFLICT DO UPDATE."""
    try:
        if "file" not in request.files:
            return json_response({"status": "error", "message": "No CSV file provided"}, 400)

        file = request.files["file"]
        stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
        reader = csv.DictReader(stream)

        if not reader.fieldnames:
            return json_response({"status": "error", "message": "CSV file is empty or missing headers"}, 400)

        csv_headers = [h.strip() for h in reader.fieldnames if h]

        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            valid_cols = [c["name"] for c in schema]
            id_col = "SiteID_v2" if "SiteID_v2" in valid_cols else ("SiteID" if "SiteID" in valid_cols else valid_cols[0])

            if id_col not in csv_headers:
                return json_response({"status": "error", "message": f"Mandatory column '{id_col}' is missing"}, 400)

            # Read existing site IDs from DB to track Inserts vs Updates accurately
            cur.execute(f'SELECT "{id_col}" FROM "{TABLE_NAME}" WHERE "{id_col}" IS NOT NULL')
            existing_site_ids = set(r[0] for r in cur.fetchall())

            # Parse & deduplicate deterministically (last occurrence wins)
            valid_map = {}
            total_csv_rows = 0
            skipped_count = 0
            errors = []

            for idx, row in enumerate(reader, start=2):
                total_csv_rows += 1
                site_id_val = row.get(id_col, "").strip() if row.get(id_col) else ""

                if not site_id_val:
                    skipped_count += 1
                    errors.append({"row": idx, "reason": f"Empty {id_col}"})
                    continue

                clean_row = {}
                for col in csv_headers:
                    if col in valid_cols:
                        val = row.get(col, "").strip() if row.get(col) else None
                        if val is not None:
                            # Type casting
                            d_type = next((c["type"].lower() for c in schema if c["name"] == col), "text")
                            try:
                                if "int" in d_type:
                                    val = int(val)
                                elif "float" in d_type or "double" in d_type or "numeric" in d_type:
                                    val = float(val)
                            except ValueError:
                                pass
                        clean_row[col] = val

                valid_map[site_id_val] = clean_row

            if not valid_map:
                return json_response({"status": "error", "message": "No valid site records found in CSV"}, 400)

            # Determine column list present in CSV that are valid DB columns
            import_cols = [c for c in valid_cols if c in csv_headers]
            if id_col not in import_cols:
                import_cols.append(id_col)

            # Prepare SQL statement for UPSERT
            cols_sql = ", ".join([f'"{c}"' for c in import_cols])
            placeholders = ", ".join(["%s"] * len(import_cols))

            update_assignments = [f'"{c}" = EXCLUDED."{c}"' for c in import_cols if c != id_col]
            if update_assignments:
                update_sql = f'ON CONFLICT ("{id_col}") DO UPDATE SET ' + ", ".join(update_assignments)
            else:
                update_sql = f'ON CONFLICT ("{id_col}") DO NOTHING'

            upsert_sql = f'INSERT INTO "{TABLE_NAME}" ({cols_sql}) VALUES ({placeholders}) {update_sql}'

            # Calculate counts
            inserted_count = sum(1 for s in valid_map if s not in existing_site_ids)
            updated_count = sum(1 for s in valid_map if s in existing_site_ids)

            # Execute batch UPSERT
            batch_data = []
            for site_id, row in valid_map.items():
                row_tuple = tuple(row.get(c) for c in import_cols)
                batch_data.append(row_tuple)

            psycopg2.extras.execute_batch(cur, upsert_sql, batch_data, page_size=250)
            conn.commit()

            return json_response({
                "status": "success",
                "message": f"Successfully imported {len(valid_map)} sites ({inserted_count} inserted, {updated_count} updated).",
                "summary": {
                    "total_csv_rows": total_csv_rows,
                    "processed": len(valid_map),
                    "inserted": inserted_count,
                    "updated": updated_count,
                    "skipped": skipped_count,
                    "errors_count": len(errors),
                    "errors": errors[:20]
                }
            })
    except Exception as e:
        logger.exception("Error executing CSV import")
        return json_response({"status": "error", "message": f"Import failed: {str(e)}"}, 500)


@sites_db_bp.route("/api/sites_db/record", methods=["POST"])
@login_required
@viewer_blocked
def api_sites_db_add():
    """Add a new site record with uniqueness check."""
    try:
        data = request.get_json() or {}

        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            valid_cols = [c["name"] for c in schema]
            id_col = "SiteID_v2" if "SiteID_v2" in valid_cols else ("SiteID" if "SiteID" in valid_cols else valid_cols[0])

            site_id_val = data.get(id_col, "").strip() if data.get(id_col) else ""
            if not site_id_val:
                return json_response({"status": "error", "message": f"Field '{id_col}' is required"}, 400)

            # Check if SiteID_v2 already exists
            cur.execute(f'SELECT 1 FROM "{TABLE_NAME}" WHERE "{id_col}"::text = %s', [site_id_val])
            if cur.fetchone():
                return json_response({
                    "status": "error",
                    "message": f'{id_col} "{site_id_val}" already exists. Please use Edit instead.'
                }, 400)

            insert_cols = []
            insert_vals = []
            placeholders = []

            for col in schema:
                c_name = col["name"]
                if c_name in data:
                    val = data[c_name]
                    if val == "" or val is None:
                        val = None
                    else:
                        d_type = col["type"].lower()
                        if "int" in d_type:
                            val = int(val)
                        elif "float" in d_type or "double" in d_type or "numeric" in d_type:
                            val = float(val)

                    insert_cols.append(f'"{c_name}"')
                    insert_vals.append(val)
                    placeholders.append("%s")

            if not insert_cols:
                return json_response({"status": "error", "message": "No valid data fields provided"}, 400)

            sql = f'INSERT INTO "{TABLE_NAME}" ({", ".join(insert_cols)}) VALUES ({", ".join(placeholders)})'
            cur.execute(sql, insert_vals)
            conn.commit()

            return json_response({"status": "success", "message": f"Site record '{site_id_val}' added successfully"})
    except psycopg2.errors.UniqueViolation:
        return json_response({"status": "error", "message": f'SiteID_v2 already exists. Please use Edit instead.'}, 400)
    except Exception as e:
        logger.exception("Error adding site record")
        return json_response({"status": "error", "message": str(e)}, 500)


@sites_db_bp.route("/api/sites_db/record/<path:pk_val>", methods=["PUT"])
@login_required
@viewer_blocked
def api_sites_db_update(pk_val):
    """Update an existing site record in sites_db."""
    try:
        data = request.get_json() or {}

        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            pk_col = pk_cols[0] if pk_cols else "SiteID_v2"

            set_clauses = []
            update_vals = []

            for col in schema:
                c_name = col["name"]
                if c_name in data and c_name != pk_col:
                    val = data[c_name]
                    if val == "" or val is None:
                        val = None
                    else:
                        d_type = col["type"].lower()
                        if "int" in d_type:
                            val = int(val)
                        elif "float" in d_type or "double" in d_type or "numeric" in d_type:
                            val = float(val)

                    set_clauses.append(f'"{c_name}" = %s')
                    update_vals.append(val)

            if not set_clauses:
                return json_response({"status": "error", "message": "No updated fields provided"}, 400)

            update_vals.append(pk_val)
            sql = f'UPDATE "{TABLE_NAME}" SET {", ".join(set_clauses)} WHERE "{pk_col}"::text = %s'
            cur.execute(sql, update_vals)
            conn.commit()

            if cur.rowcount == 0:
                return json_response({"status": "error", "message": f"Record with {pk_col} = '{pk_val}' not found"}, 404)

            return json_response({"status": "success", "message": "Site record updated successfully"})
    except psycopg2.errors.UniqueViolation:
        return json_response({"status": "error", "message": "Unique constraint violation: SiteID_v2 already exists"}, 400)
    except Exception as e:
        logger.exception("Error updating site record")
        return json_response({"status": "error", "message": str(e)}, 500)


@sites_db_bp.route("/api/sites_db/record/<path:pk_val>", methods=["DELETE"])
@login_required
@viewer_blocked
def api_sites_db_delete(pk_val):
    """Delete a site record from sites_db."""
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            pk_col = pk_cols[0] if pk_cols else "SiteID_v2"

            sql = f'DELETE FROM "{TABLE_NAME}" WHERE "{pk_col}"::text = %s'
            cur.execute(sql, [pk_val])
            conn.commit()

            if cur.rowcount == 0:
                return json_response({"status": "error", "message": f"Record with {pk_col} = '{pk_val}' not found"}, 404)

            return json_response({"status": "success", "message": "Site record deleted successfully"})
    except Exception as e:
        logger.exception("Error deleting site record")
        return json_response({"status": "error", "message": str(e)}, 500)
