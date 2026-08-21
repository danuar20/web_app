from flask import Blueprint, render_template, request, session, jsonify, make_response
from app import csrf
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, _no_cache, db_query, viewer_blocked
import psycopg2
import logging

logger = logging.getLogger(__name__)

unbalance_prb = Blueprint("unbalance_prb", __name__)


@unbalance_prb.route("/unbalance_prb")
@login_required
@viewer_blocked
def unbalance_prb_page():
    from datetime import date, timedelta
    import re

    weeks = []
    week_dates = {}
    try:
        with db_query() as (conn, cur):
            cur.execute('''
                SELECT DISTINCT week FROM "unbalance_prb_weekly"
                ORDER BY week DESC
            ''')
            weeks = [r[0] for r in cur.fetchall()]

        for w in weeks:
            m = re.match(r"^(\d{4})-W(\d{2})$", w)
            if m:
                year, week_num = int(m.group(1)), int(m.group(2))
                mon = date.fromisocalendar(year, week_num, 1)
                fri = mon + timedelta(days=4)
                thu = fri + timedelta(days=6)
                week_dates[w] = {
                    "start_date": fri.strftime("%Y-%m-%d"),
                    "end_date": thu.strftime("%Y-%m-%d")
                }
    except Exception as e:
        logger.warning("Could not pre-fetch weeks for unbalance_prb_page: %s", e)

    return render_template(
        "unbalance_prb.html",
        username=session.get("username", "User"),
        initial_weeks=weeks,
        initial_week_dates=week_dates
    )


@unbalance_prb.route("/api/unbalance_prb/weeks", methods=["GET"])
@login_required
def api_unbalance_prb_weeks():
    """Return list of available weeks from unbalance_prb_weekly table with instant start/end date calculation."""
    from datetime import date, timedelta
    import re

    try:
        with db_query() as (conn, cur):
            cur.execute('''
                SELECT DISTINCT week FROM "unbalance_prb_weekly"
                ORDER BY week DESC
            ''')
            weeks = [r[0] for r in cur.fetchall()]

        week_dates = {}
        for w in weeks:
            m = re.match(r"^(\d{4})-W(\d{2})$", w)
            if m:
                year, week_num = int(m.group(1)), int(m.group(2))
                mon = date.fromisocalendar(year, week_num, 1)
                fri = mon + timedelta(days=4)
                thu = fri + timedelta(days=6)
                week_dates[w] = {
                    "start_date": fri.strftime("%Y-%m-%d"),
                    "end_date": thu.strftime("%Y-%m-%d")
                }

        return jsonify({"weeks": weeks, "week_dates": week_dates})
    except Exception as e:
        logger.exception("Error fetching unbalance_prb weeks: %s", e)
        return jsonify({"error": str(e)}), 500


@unbalance_prb.route("/api/unbalance_prb/data", methods=["POST"])
@csrf.exempt
@login_required
def api_unbalance_prb_data():
    """Return unbalance PRB weekly data for a selected week range in high-speed compact format."""
    req = request.get_json()
    if not req:
        return jsonify({"error": "Missing request body"}), 400

    # Support both single-week and range parameters
    sel_a = req.get("start_week") or req.get("week")
    sel_b = req.get("end_week") or req.get("week")

    if not sel_a or not sel_b:
        return jsonify({"error": "Missing week range parameters"}), 400

    start_week = sel_a if sel_a <= sel_b else sel_b
    end_week = sel_b if sel_a <= sel_b else sel_a

    try:
        with db_query() as (conn, cur):
            cur.execute('''
                SELECT
                    week,
                    COALESCE(site_id, '') AS site_id,
                    COALESCE(site_id_v2, '') AS site_id_v2,
                    COALESCE(sector, '') AS sector,
                    COALESCE(type, '') AS type,
                    COALESCE(num_band, 0) AS num_band,
                    "dl_L900",
                    "dl_L1800",
                    "dl_L2100",
                    "dl_L2300_1",
                    "dl_L2300_2",
                    "dl_L2300_3",
                    "dl_L700",
                    avg_dl_prb,
                    max_dl_prb,
                    COALESCE(max_dl_band, '') AS max_dl_band,
                    COALESCE(min_dl_band, '') AS min_dl_band,
                    "ul_L900",
                    "ul_L1800",
                    "ul_L2100",
                    "ul_L2300_1",
                    "ul_L2300_2",
                    "ul_L2300_3",
                    "ul_L700",
                    avg_ul_prb,
                    max_ul_prb,
                    COALESCE(max_ul_band, '') AS max_ul_band,
                    COALESCE(min_ul_band, '') AS min_ul_band
                FROM "unbalance_prb_weekly"
                WHERE week >= %s AND week <= %s
                ORDER BY week, site_id, sector
            ''', [start_week, end_week])

            columns = [
                "week", "site_id", "site_id_v2", "sector", "type", "num_band",
                "dl_L900", "dl_L1800", "dl_L2100", "dl_L2300_1", "dl_L2300_2", "dl_L2300_3", "dl_L700",
                "avg_dl_prb", "max_dl_prb", "max_dl_band", "min_dl_band",
                "ul_L900", "ul_L1800", "ul_L2100", "ul_L2300_1", "ul_L2300_2", "ul_L2300_3", "ul_L700",
                "avg_ul_prb", "max_ul_prb", "max_ul_band", "min_ul_band"
            ]
            raw_rows = cur.fetchall()

        return jsonify({
            "columns": columns,
            "rows": raw_rows,
            "start_week": start_week,
            "end_week": end_week,
            "count": len(raw_rows),
            "source": "unbalance_prb_weekly"
        })

    except Exception as e:
        logger.exception("Error fetching unbalance_prb data: %s", e)
        return jsonify({"error": str(e)}), 500


@unbalance_prb.route("/api/unbalance_prb/export", methods=["POST"])
@csrf.exempt
@login_required
def api_unbalance_prb_export():
    """Generate and stream a professionally styled Excel file using fast xlsxwriter."""
    import io
    import xlsxwriter
    from flask import send_file

    if request.is_json:
        req = request.get_json() or {}
    else:
        req = request.form.to_dict() if request.form else {}
        if "bands" in req and isinstance(req["bands"], str):
            import json
            try:
                req["bands"] = json.loads(req["bands"])
            except Exception:
                req["bands"] = [b.strip() for b in req["bands"].split(",") if b.strip()]

    start_week = req.get("start_week")
    end_week = req.get("end_week")
    week_filter = req.get("week_filter", "all")
    type_filter = (req.get("type_filter") or "all").lower()
    search = (req.get("search") or "").strip().lower()
    status_filter = req.get("status_filter", "all")
    bands_input = req.get("bands")
    if isinstance(bands_input, list):
        active_bands = set(bands_input)
    else:
        active_bands = {'L900', 'L1800', 'L2100', 'L2300_1', 'L2300_2', 'L2300_3', 'L700'}
    view_mode = req.get("view_mode", "all")
    low_thresh = float(req.get("low_util", 50))
    high_thresh = float(req.get("high_util", 85))
    gap_thresh = float(req.get("gap_thresh", 30))

    if not start_week or not end_week:
        return jsonify({"error": "Missing week range"}), 400

    min_week = start_week if start_week <= end_week else end_week
    max_week = end_week if start_week <= end_week else start_week

    where_clauses = ["week >= %s", "week <= %s"]
    params = [min_week, max_week]

    if week_filter != "all":
        where_clauses.append("week = %s")
        params.append(week_filter)

    if type_filter != "all":
        where_clauses.append("LOWER(type) = %s")
        params.append(type_filter)

    if search:
        where_clauses.append("(LOWER(site_id) LIKE %s OR LOWER(site_id_v2) LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    sql = f'''
        SELECT
            week,
            COALESCE(site_id, '') AS site_id,
            COALESCE(site_id_v2, '') AS site_id_v2,
            COALESCE(sector, '') AS sector,
            COALESCE(type, '') AS type,
            COALESCE(num_band, 0) AS num_band,
            "dl_L900", "dl_L1800", "dl_L2100", "dl_L2300_1", "dl_L2300_2", "dl_L2300_3", "dl_L700",
            avg_dl_prb, max_dl_prb,
            COALESCE(max_dl_band, '') AS max_dl_band,
            COALESCE(min_dl_band, '') AS min_dl_band,
            "ul_L900", "ul_L1800", "ul_L2100", "ul_L2300_1", "ul_L2300_2", "ul_L2300_3", "ul_L700",
            avg_ul_prb, max_ul_prb,
            COALESCE(max_ul_band, '') AS max_ul_band,
            COALESCE(min_ul_band, '') AS min_ul_band
        FROM "unbalance_prb_weekly"
        WHERE {" AND ".join(where_clauses)}
        ORDER BY week DESC, site_id, sector
    '''

    try:
        with db_query() as (conn, cur):
            cur.execute(sql, params)
            raw_rows = cur.fetchall()

        all_col_defs = [
            ("week", "week", "base", None),
            ("site_id", "site_id", "base", None),
            ("site_id_v2", "site_id_v2", "base", None),
            ("sector", "sector", "base", None),
            ("type", "type", "base", None),
            ("num_band", "num_band", "base", None),

            ("dl_L900", "dl_L900", "dl", "L900"),
            ("dl_L1800", "dl_L1800", "dl", "L1800"),
            ("dl_L2100", "dl_L2100", "dl", "L2100"),
            ("dl_L2300_1", "dl_L2300_1", "dl", "L2300_1"),
            ("dl_L2300_2", "dl_L2300_2", "dl", "L2300_2"),
            ("dl_L2300_3", "dl_L2300_3", "dl", "L2300_3"),
            ("dl_L700", "dl_L700", "dl", "L700"),
            ("avg_dl_prb", "avg_dl_prb", "dl", None),
            ("max_dl_prb", "max_dl_prb", "dl", None),
            ("cat_dl_prb", "Cat DL PRB", "dl", None),
            ("dl_prb_status", "DL PRB Status", "dl", None),
            ("dl_fdd", "dl_fdd", "dl", None),
            ("dl_tdd", "dl_tdd", "dl", None),
            ("max_dl_band", "max_dl_band", "dl", None),
            ("min_dl_band", "min_dl_band", "dl", None),

            ("ul_L900", "ul_L900", "ul", "L900"),
            ("ul_L1800", "ul_L1800", "ul", "L1800"),
            ("ul_L2100", "ul_L2100", "ul", "L2100"),
            ("ul_L2300_1", "ul_L2300_1", "ul", "L2300_1"),
            ("ul_L2300_2", "ul_L2300_2", "ul", "L2300_2"),
            ("ul_L2300_3", "ul_L2300_3", "ul", "L2300_3"),
            ("ul_L700", "ul_L700", "ul", "L700"),
            ("avg_ul_prb", "avg_ul_prb", "ul", None),
            ("max_ul_prb", "max_ul_prb", "ul", None),
            ("cat_ul_prb", "Cat UL PRB", "ul", None),
            ("ul_prb_status", "UL PRB Status", "ul", None),
            ("ul_fdd", "ul_fdd", "ul", None),
            ("ul_tdd", "ul_tdd", "ul", None),
            ("max_ul_band", "max_ul_band", "ul", None),
            ("min_ul_band", "min_ul_band", "ul", None),
        ]

        active_cols = []
        for key, label, group, band in all_col_defs:
            if band and band not in active_bands:
                continue
            if view_mode == "dl" and group not in ("base", "dl"):
                continue
            if view_mode == "ul" and group not in ("base", "ul"):
                continue
            active_cols.append((key, label))

        def to_num(v):
            if v is None or v == "": return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        # Pre-compute column index accessors
        dl_band_map = [('L900', 6), ('L1800', 7), ('L2100', 8), ('L2300_1', 9), ('L2300_2', 10), ('L2300_3', 11), ('L700', 12)]
        ul_band_map = [('L900', 17), ('L1800', 18), ('L2100', 19), ('L2300_1', 20), ('L2300_2', 21), ('L2300_3', 22), ('L700', 23)]

        active_dl_indices = [idx for band, idx in dl_band_map if band in active_bands]
        active_ul_indices = [idx for band, idx in ul_band_map if band in active_bands]

        fdd_dl_indices = [idx for band, idx in dl_band_map if band in active_bands and band in ('L700', 'L900', 'L1800', 'L2100')]
        tdd_dl_indices = [idx for band, idx in dl_band_map if band in active_bands and band in ('L2300_1', 'L2300_2', 'L2300_3')]

        fdd_ul_indices = [idx for band, idx in ul_band_map if band in active_bands and band in ('L700', 'L900', 'L1800', 'L2100')]
        tdd_ul_indices = [idx for band, idx in ul_band_map if band in active_bands and band in ('L2300_1', 'L2300_2', 'L2300_3')]

        def get_cat(val):
            if val is None: return ""
            if val <= low_thresh: return "Low Util"
            if val <= high_thresh: return "Medium Util"
            return "High Util"

        def fast_eval_stat(row, indices):
            pos = []
            for i in indices:
                v = to_num(row[i])
                if v is not None and v > 0:
                    pos.append(v)
            if not pos: return "N/A"
            if len(pos) == 1: return "Balance"
            return "Unbalance" if (max(pos) - min(pos) >= gap_thresh) else "Balance"

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'constant_memory': True, 'in_memory': True})
        ws = wb.add_worksheet("Unbalance_PRB_Weekly")

        fmt_hdr = wb.add_format({'bold': True, 'bg_color': '#F3EFE8', 'font_color': '#8A7D6B', 'border': 1, 'border_color': '#E2D9CC'})
        fmt_def = wb.add_format({'font_name': 'Calibri', 'font_size': 10, 'border': 1, 'border_color': '#D0D0D0'})
        fmt_center = wb.add_format({'font_name': 'Calibri', 'font_size': 10, 'align': 'center', 'border': 1, 'border_color': '#D0D0D0'})
        fmt_pct = wb.add_format({'font_name': 'Calibri', 'font_size': 10, 'num_format': '0.00"%"', 'border': 1, 'border_color': '#D0D0D0'})
        fmt_cat_low = wb.add_format({'font_name': 'Calibri', 'font_size': 10, 'bold': True, 'font_color': '#137333', 'bg_color': '#E6F4EA', 'border': 1, 'border_color': '#D0D0D0'})
        fmt_cat_med = wb.add_format({'font_name': 'Calibri', 'font_size': 10, 'bold': True, 'font_color': '#B06000', 'bg_color': '#FEF7E0', 'border': 1, 'border_color': '#D0D0D0'})
        fmt_cat_high = wb.add_format({'font_name': 'Calibri', 'font_size': 10, 'bold': True, 'font_color': '#C5221F', 'bg_color': '#FCE8E6', 'border': 1, 'border_color': '#D0D0D0'})
        fmt_bal = wb.add_format({'font_name': 'Calibri', 'font_size': 10, 'bold': True, 'align': 'center', 'bg_color': '#C6E0B4', 'border': 1, 'border_color': '#D0D0D0'})
        fmt_unbal = wb.add_format({'font_name': 'Calibri', 'font_size': 10, 'bold': True, 'align': 'center', 'bg_color': '#FCE4D6', 'border': 1, 'border_color': '#D0D0D0'})

        for c, (_, label) in enumerate(active_cols):
            ws.write(0, c, label.upper(), fmt_hdr)

        row_idx = 1
        for r in raw_rows:
            # DL & UL status
            dl_status = fast_eval_stat(r, active_dl_indices)
            ul_status = fast_eval_stat(r, active_ul_indices)

            if status_filter == "dl_unbalance" and dl_status != "Unbalance": continue
            if status_filter == "ul_unbalance" and ul_status != "Unbalance": continue
            if status_filter == "both_unbalance" and (dl_status != "Unbalance" or ul_status != "Unbalance"): continue

            # Dynamic Averages
            dl_active_vals = []
            for i in active_dl_indices:
                v = to_num(r[i])
                if v is not None:
                    dl_active_vals.append(v)

            ul_active_vals = []
            for i in active_ul_indices:
                v = to_num(r[i])
                if v is not None:
                    ul_active_vals.append(v)

            dl_avg = round(sum(dl_active_vals) / len(dl_active_vals), 2) if dl_active_vals else to_num(r[13])
            ul_avg = round(sum(ul_active_vals) / len(ul_active_vals), 2) if ul_active_vals else to_num(r[24])

            cat_dl = get_cat(dl_avg)
            cat_ul = get_cat(ul_avg)

            dl_fdd = fast_eval_stat(r, fdd_dl_indices)
            dl_tdd = fast_eval_stat(r, tdd_dl_indices)
            ul_fdd = fast_eval_stat(r, fdd_ul_indices)
            ul_tdd = fast_eval_stat(r, tdd_ul_indices)

            # Map key values directly
            val_map = {
                "week": r[0], "site_id": r[1], "site_id_v2": r[2], "sector": r[3], "type": r[4], "num_band": r[5],
                "dl_L900": to_num(r[6]), "dl_L1800": to_num(r[7]), "dl_L2100": to_num(r[8]),
                "dl_L2300_1": to_num(r[9]), "dl_L2300_2": to_num(r[10]), "dl_L2300_3": to_num(r[11]), "dl_L700": to_num(r[12]),
                "avg_dl_prb": dl_avg, "max_dl_prb": to_num(r[14]), "max_dl_band": r[15], "min_dl_band": r[16],
                "cat_dl_prb": cat_dl, "dl_prb_status": dl_status, "dl_fdd": dl_fdd, "dl_tdd": dl_tdd,
                "ul_L900": to_num(r[17]), "ul_L1800": to_num(r[18]), "ul_L2100": to_num(r[19]),
                "ul_L2300_1": to_num(r[20]), "ul_L2300_2": to_num(r[21]), "ul_L2300_3": to_num(r[22]), "ul_L700": to_num(r[23]),
                "avg_ul_prb": ul_avg, "max_ul_prb": to_num(r[25]), "max_ul_band": r[26], "min_ul_band": r[27],
                "cat_ul_prb": cat_ul, "ul_prb_status": ul_status, "ul_fdd": ul_fdd, "ul_tdd": ul_tdd
            }

            for ci, (k, _) in enumerate(active_cols):
                val = val_map.get(k)
                if k in ("cat_dl_prb", "cat_ul_prb"):
                    num_v = dl_avg if k == "cat_dl_prb" else ul_avg
                    fmt = fmt_cat_low if num_v is not None and num_v <= low_thresh else (fmt_cat_med if num_v is not None and num_v <= high_thresh else (fmt_cat_high if num_v is not None else fmt_def))
                    ws.write(row_idx, ci, val or "-", fmt)
                elif k in ("dl_prb_status", "ul_prb_status", "dl_fdd", "dl_tdd", "ul_fdd", "ul_tdd"):
                    fmt = fmt_bal if val == "Balance" else (fmt_unbal if val == "Unbalance" else fmt_center)
                    ws.write(row_idx, ci, val or "-", fmt)
                elif k.startswith("dl_L") or k.startswith("ul_L") or k in ("avg_dl_prb", "avg_ul_prb", "max_dl_prb", "max_ul_prb"):
                    num_val = to_num(val)
                    if num_val is not None:
                        ws.write_number(row_idx, ci, num_val, fmt_pct)
                    else:
                        ws.write(row_idx, ci, "-", fmt_center)
                elif k in ("num_band", "sector", "week"):
                    ws.write(row_idx, ci, val if val is not None else "-", fmt_center)
                else:
                    ws.write(row_idx, ci, str(val) if val is not None else "-", fmt_def)

            row_idx += 1

        wb.close()
        output.seek(0)
        file_bytes = output.getvalue()
        output.close()

        if week_filter and week_filter != "all":
            filename = f"Unbalance_PRB_Weekly_{week_filter}.xlsx"
        else:
            filename = f"Unbalance_PRB_Weekly_{min_week}.xlsx" if min_week == max_week else f"Unbalance_PRB_Weekly_{min_week}_to_{max_week}.xlsx"

        response = make_response(file_bytes)
        response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        logger.exception("Error exporting unbalance_prb data: %s", e)
        return jsonify({"error": str(e)}), 500
