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
    """Optimized lightweight map API returning only coordinates & SiteID_v2."""
    try:
        search = request.args.get("search", "").strip()

        with db_query(get_postgres_connection) as (conn, cur):
            schema, pk_cols = _get_table_schema(cur)
            valid_cols = [c["name"] for c in schema]

            lat_col = next((c for c in valid_cols if c.lower() == "latitude"), "latitude")
            lng_col = next((c for c in valid_cols if c.lower() == "longitude"), "longitude")
            id_col = "SiteID_v2" if "SiteID_v2" in valid_cols else ("SiteID" if "SiteID" in valid_cols else valid_cols[0])

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

            # Return lightweight tuple (SiteID_v2, lat, lng)
            query = f'SELECT "{id_col}", "{lat_col}", "{lng_col}" FROM "{TABLE_NAME}" {where_clause}'
            cur.execute(query, params)
            rows = cur.fetchall()

            sites = [
                {"id": r[0], "lat": r[1], "lng": r[2]}
                for r in rows
            ]

            valid_count = len(sites)
            invalid_count = max(0, total_count - valid_count)

            return json_response({
                "status": "success",
                "sites": sites,
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
                else:
                    sample_row.append("SAMPLE")

            return csv_response([sample_row], headers, "sites_db_template.csv")
    except Exception as e:
        logger.exception("Error generating CSV template")
        return json_response({"status": "error", "message": str(e)}, 500)


@sites_db_bp.route("/api/sites_db/csv_preview", methods=["POST"])
@login_required
@viewer_blocked
def api_sites_db_csv_preview():
    """Parse CSV, validate schema & headers, detect internal duplicates, check existing DB records."""
    try:
        if "file" not in request.files:
            return json_response({"status": "error", "message": "No CSV file provided"}, 400)

        file = request.files["file"]
        if not file.filename.endswith(".csv"):
            return json_response({"status": "error", "message": "Invalid file format. Please upload a .csv file"}, 400)

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
                return json_response({
                    "status": "error",
                    "message": f"Mandatory column '{id_col}' is missing from CSV headers"
                }, 400)

            # Check unknown columns
            unknown_cols = [h for h in csv_headers if h not in valid_cols]

            # Read existing site IDs from DB for comparison
            cur.execute(f'SELECT "{id_col}" FROM "{TABLE_NAME}" WHERE "{id_col}" IS NOT NULL')
            existing_site_ids = set(r[0] for r in cur.fetchall())

            total_csv_rows = 0
            invalid_rows = []
            valid_map = {} # site_id -> (row_num, row_data)  -- deterministic last occurrence!
            internal_duplicate_count = 0

            for idx, row in enumerate(reader, start=2): # line 2 is first data row
                total_csv_rows += 1
                site_id_val = row.get(id_col, "").strip() if row.get(id_col) else ""

                if not site_id_val:
                    invalid_rows.append({"row": idx, "reason": f"Empty {id_col}"})
                    continue

                if site_id_val in valid_map:
                    internal_duplicate_count += 1

                # Clean row values
                clean_row = {}
                for col in csv_headers:
                    if col in valid_cols:
                        v = row.get(col, "").strip() if row.get(col) else None
                        clean_row[col] = v

                valid_map[site_id_val] = (idx, clean_row)

            # Calculate INSERT vs UPDATE
            new_sites = []
            update_sites = []

            for site_id, (row_num, clean_row) in valid_map.items():
                if site_id in existing_site_ids:
                    update_sites.append(clean_row)
                else:
                    new_sites.append(clean_row)

            preview_records = (new_sites[:5] + update_sites[:5])

            return json_response({
                "status": "success",
                "total_csv_rows": total_csv_rows,
                "unique_csv_rows": len(valid_map),
                "new_count": len(new_sites),
                "update_count": len(update_sites),
                "internal_duplicate_count": internal_duplicate_count,
                "invalid_count": len(invalid_rows),
                "invalid_rows": invalid_rows[:10],
                "unknown_columns": unknown_cols,
                "preview_records": preview_records,
                "id_column": id_col
            })
    except Exception as e:
        logger.exception("Error previewing CSV import")
        return json_response({"status": "error", "message": f"CSV parse error: {str(e)}"}, 500)


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
