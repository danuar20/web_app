"""CEI Dashboard Routes — /sow/cei

Crowdsource Experience Index (CEI) dashboard based on sow.cei_score.
Replicates the 3-section layout:
  1. Top KPI Summary & Regional Benchmark Gauge
  2. 7 KQI Hit Rate Cards with Mini Sparklines & WoW Delta
  3. Weekly Trend Combination Chart (Stacked Bar KQIs + % Good Cell Line + Target)
"""
import logging
import time
from collections import defaultdict
from flask import Blueprint, render_template, request, session, jsonify, make_response
from app import csrf
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, viewer_blocked, db_query, csv_response

logger = logging.getLogger(__name__)

cei = Blueprint("cei", __name__)

_CEI_CACHE = {}
_CEI_CACHE_TTL = 900  # 15 minutes

KQIS = [
    {
        "id": "web_rtt",
        "title": "Web browsing RTT",
        "col": "latest_week_only_web_browsing_client_side_round_trip_time_ms_hi",
        "color": "#145DA0",
    },
    {
        "id": "web_ul_retrans",
        "title": "Web UL retransmission",
        "col": "latest_week_only_web_browsing_ul_retransmitted_packet_rate_hit_",
        "color": "#0C2D48",
    },
    {
        "id": "video_vxb",
        "title": "Video start delay",
        "col": "latest_week_only_streaming_video_streaming_xkb_start_delay_s_hi",
        "color": "#569BB8",
    },
    {
        "id": "voip_ul",
        "title": "VoIP UL jitter",
        "col": "latest_week_only_voip_udp_uplink_jitter_ms_hit_count",
        "color": "#9DB4C0",
    },
    {
        "id": "voip_dl",
        "title": "VoIP DL jitter",
        "col": "latest_week_only_voip_udp_downlink_jitter_ms_hit_count",
        "color": "#C2D4DD",
    },
    {
        "id": "game_rtt",
        "title": "Gaming RTT",
        "col": "latest_week_only_gamemax_client_side_round_trip_time_ms_hit_cou",
        "color": "#2E8BC0",
    },
    {
        "id": "game_jitter",
        "title": "Gaming UL jitter",
        "col": "latest_week_only_gamemax_udp_uplink_jitter_ms_hit_count",
        "color": "#83A6C4",
    },
]


def _get_branch_map():
    now = time.time()
    if "_branch_map" in _CEI_CACHE:
        val, exp = _CEI_CACHE["_branch_map"]
        if now < exp:
            return val
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(
                "SELECT DISTINCT branch, UPPER(TRIM(kabupaten)) "
                "FROM sow.fb_share WHERE branch IS NOT NULL AND kabupaten IS NOT NULL"
            )
            mapping = {}
            for b, k in cur.fetchall():
                if k not in mapping:
                    mapping[k] = b
            _CEI_CACHE["_branch_map"] = (mapping, now + 86400)
            return mapping
    except Exception as e:
        logger.exception("Error loading branch map: %s", e)
        return {}


def _get_yearweeks():
    now = time.time()
    if "_yearweeks" in _CEI_CACHE:
        val, exp = _CEI_CACHE["_yearweeks"]
        if now < exp:
            return val
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT DISTINCT weeknum FROM sow.cei_score ORDER BY weeknum DESC")
            yws = [int(r[0]) for r in cur.fetchall() if r[0] is not None]
            _CEI_CACHE["_yearweeks"] = (yws, now + 1800)
            return yws
    except Exception as e:
        logger.exception("Error loading CEI yearweeks: %s", e)
        return []


def _get_target_for_week(yearweek):
    try:
        yw_str = str(yearweek)
        year = int(yw_str[:4])
        week = int(yw_str[4:])
        if week <= 13:
            q_col = "Q1"
        elif week <= 26:
            q_col = "Q2"
        elif week <= 39:
            q_col = "Q3"
        else:
            q_col = "Q4"

        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(
                f'SELECT "{q_col}" FROM sow.sow_target WHERE "SOW" = \'CEI\' AND "Year" = %s LIMIT 1',
                (year,)
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                val = float(row[0])
                if val < 1.0:
                    val *= 100.0
                return round(val, 2), f"Target {q_col}"
    except Exception as e:
        logger.warning("Error fetching target: %s", e)
    return 93.95, "Target Q3"


@cei.route("/sow/cei")
@login_required
@viewer_blocked
def cei_dashboard_page():
    yearweeks = _get_yearweeks()
    default_yw = yearweeks[0] if yearweeks else 202637
    default_start_yw = 202611 if 202611 in yearweeks else (yearweeks[-1] if yearweeks else 202611)

    return render_template(
        "sow_cei.html",
        username=session.get("username", "User"),
        yearweeks=yearweeks,
        default_yw=default_yw,
        default_start_yw=default_start_yw,
        kqis=KQIS,
    )


@cei.route("/api/sow/cei/summary", methods=["GET"])
@login_required
def api_cei_summary():
    yearweeks = _get_yearweeks()
    if not yearweeks:
        return jsonify({"status": "error", "message": "No data available in sow.cei_score"}), 404

    try:
        req_yw = request.args.get("weeknum", type=int)
        target_yw = req_yw if req_yw and req_yw in yearweeks else yearweeks[0]
    except Exception:
        target_yw = yearweeks[0]

    cache_key = f"summary:{target_yw}"
    now = time.time()
    if cache_key in _CEI_CACHE:
        val, exp = _CEI_CACHE[cache_key]
        if now < exp:
            return jsonify(val)

    curr_idx = yearweeks.index(target_yw)
    prev_yw = yearweeks[curr_idx + 1] if curr_idx + 1 < len(yearweeks) else None

    branch_map = _get_branch_map()
    target_val, target_label = _get_target_for_week(target_yw)

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            weeks_to_query = [target_yw] + ([prev_yw] if prev_yw else [])

            cur.execute(
                """
                SELECT weeknum,
                       COUNT(*) AS total_cells,
                       COUNT(*) FILTER (WHERE remark_cell = 'Good_cell') AS good_cells,
                       COUNT(*) FILTER (WHERE remark_cell = 'Bad_cell')  AS bad_cells
                FROM sow.cei_score
                WHERE weeknum = ANY(%s)
                GROUP BY weeknum
                """,
                (weeks_to_query,)
            )
            cell_counts = {r[0]: {"total": r[1], "good": r[2], "bad": r[3]} for r in cur.fetchall()}

            cur.execute(
                """
                SELECT UPPER(TRIM(kabupaten)),
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE remark_cell = 'Good_cell') AS good
                FROM sow.cei_score
                WHERE weeknum = %s AND kabupaten IS NOT NULL
                GROUP BY UPPER(TRIM(kabupaten))
                """,
                (target_yw,)
            )
            kab_counts = cur.fetchall()

        curr_stats = cell_counts.get(target_yw, {"total": 0, "good": 0, "bad": 0})
        prev_stats = cell_counts.get(prev_yw, {"total": 0, "good": 0, "bad": 0}) if prev_yw else None

        total_cells = curr_stats["total"]
        good_cells = curr_stats["good"]
        bad_cells = curr_stats["bad"]

        good_pct = round(good_cells * 100.0 / total_cells, 2) if total_cells else 0.0

        diff_target_pp = round(good_pct - target_val, 2)

        needed_recover = 0
        if good_pct < target_val and total_cells:
            needed_good = int((target_val / 100.0) * total_cells) + 1
            needed_recover = max(0, needed_good - good_cells)

        diff_prev_pp = None
        if prev_stats and prev_stats["total"]:
            prev_pct = round(prev_stats["good"] * 100.0 / prev_stats["total"], 2)
            diff_prev_pp = round(good_pct - prev_pct, 2)

        branch_totals = defaultdict(lambda: [0, 0])
        for kab, total, good in kab_counts:
            b = branch_map.get(kab, "OTHER")
            branch_totals[b][0] += total
            branch_totals[b][1] += good

        regional_gauge = []
        for b_name in ["TIMIKA", "JAYAPURA", "AMBON", "SORONG"]:
            if b_name in branch_totals:
                tot, gd = branch_totals[b_name]
                pct = round(gd * 100.0 / tot, 2) if tot else 0.0
                regional_gauge.append({
                    "name": b_name,
                    "value": pct,
                    "is_above": pct >= target_val,
                })

        yw_str = str(target_yw)
        label_week = f"W{yw_str[4:]} {yw_str[:4]}"
        prev_label = f"W{str(prev_yw)[4:]}" if prev_yw else "-"

        res_data = {
            "status": "success",
            "weeknum": target_yw,
            "label_week": label_week,
            "prev_weeknum": prev_yw,
            "prev_label": prev_label,
            "good_cell_pct": good_pct,
            "is_above_target": good_pct >= target_val,
            "target": target_val,
            "target_label": target_label,
            "diff_target_pp": diff_target_pp,
            "needed_recover": needed_recover,
            "bad_cells": bad_cells,
            "total_cells": total_cells,
            "diff_prev_pp": diff_prev_pp,
            "regional_gauge": regional_gauge,
        }

        _CEI_CACHE[cache_key] = (res_data, now + _CEI_CACHE_TTL)
        return jsonify(res_data)

    except Exception as e:
        logger.exception("Error calculating CEI summary: %s", e)
        return jsonify({"status": "error", "message": "Failed to compute summary"}), 500


@cei.route("/api/sow/cei/kqi-cards", methods=["GET"])
@login_required
def api_cei_kqi_cards():
    yearweeks = _get_yearweeks()
    if not yearweeks:
        return jsonify({"status": "error", "message": "No data"}), 404

    target_yw = request.args.get("weeknum", type=int) or yearweeks[0]
    cell_filter = request.args.get("cell_filter", "bad").lower()

    where_clause = ""
    if cell_filter == "bad":
        where_clause = "AND remark_cell = 'Bad_cell'"
    elif cell_filter == "good":
        where_clause = "AND remark_cell = 'Good_cell'"

    cache_key = f"kqi_cards:{target_yw}:{cell_filter}"
    now = time.time()
    if cache_key in _CEI_CACHE:
        val, exp = _CEI_CACHE[cache_key]
        if now < exp:
            return jsonify(val)

    curr_idx = yearweeks.index(target_yw) if target_yw in yearweeks else 0
    prev_yw = yearweeks[curr_idx + 1] if curr_idx + 1 < len(yearweeks) else None

    # For sparklines, fetch up to 8 prior weeks
    spark_yws = list(reversed(yearweeks[max(0, curr_idx - 7):curr_idx + 1]))

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            sum_exprs = ", ".join([f'SUM("{k["col"]}") AS sum_{k["id"]}' for k in KQIS])
            hit_exprs = ", ".join([f'COUNT(*) FILTER (WHERE "{k["col"]}" > 0) AS hit_{k["id"]}' for k in KQIS])

            q = f"""
                SELECT weeknum,
                       COUNT(*) AS cell_count,
                       {sum_exprs},
                       {hit_exprs}
                FROM sow.cei_score
                WHERE weeknum = ANY(%s) {where_clause}
                GROUP BY weeknum
            """
            cur.execute(q, ([target_yw, prev_yw] if prev_yw else [target_yw],))
            rows = {r[0]: r for r in cur.fetchall()}

            # Query sparkline trends
            cur.execute(f"""
                SELECT weeknum,
                       COUNT(*) AS cell_count,
                       {sum_exprs}
                FROM sow.cei_score
                WHERE weeknum = ANY(%s) {where_clause}
                GROUP BY weeknum
                ORDER BY weeknum ASC
            """, (spark_yws,))
            spark_rows = {r[0]: r for r in cur.fetchall()}

        curr_row = rows.get(target_yw)
        prev_row = rows.get(prev_yw) if prev_yw else None

        cards = []
        n_kqi = len(KQIS)

        curr_denom = curr_row[1] if curr_row and curr_row[1] else 1
        prev_denom = prev_row[1] if prev_row and prev_row[1] else 1

        for i, k in enumerate(KQIS):
            sum_idx = 2 + i
            hit_idx = 2 + n_kqi + i

            curr_sum = curr_row[sum_idx] or 0 if curr_row else 0
            curr_hits = curr_row[hit_idx] or 0 if curr_row else 0
            curr_avg = round(curr_sum / curr_denom, 2)

            prev_sum = prev_row[sum_idx] or 0 if prev_row else 0
            prev_avg = round(prev_sum / prev_denom, 2) if prev_row else None

            delta = None
            delta_pct = None
            is_better = None
            if prev_avg is not None:
                delta = round(curr_avg - prev_avg, 2)
                delta_pct = round((delta / prev_avg * 100.0), 1) if prev_avg > 0 else 0.0
                # Hit rate: lower is better! Negative delta means improvement (green)
                is_better = delta < 0

            # Build sparkline points
            sparkline = []
            for y in spark_yws:
                sr = spark_rows.get(y)
                if sr and sr[1]:
                    s_avg = round((sr[2 + i] or 0) / sr[1], 2)
                    sparkline.append(s_avg)
                else:
                    sparkline.append(0.0)

            cards.append({
                "id": k["id"],
                "title": k["title"],
                "value": curr_avg,
                "delta": delta,
                "delta_pct": delta_pct,
                "is_better": is_better,
                "total_hit_days": curr_sum,
                "hit_cells": curr_hits,
                "sparkline": sparkline,
            })

        yw_str = str(target_yw)
        meta = {
            "week_label": f"W{yw_str[4:]} {yw_str[:4]}",
            "cell_count": curr_denom,
            "filter": cell_filter,
        }

        res_data = {"status": "success", "cards": cards, "meta": meta}
        _CEI_CACHE[cache_key] = (res_data, now + _CEI_CACHE_TTL)
        return jsonify(res_data)

    except Exception as e:
        logger.exception("Error calculating CEI KQI cards: %s", e)
        return jsonify({"status": "error", "message": "Failed to compute KQI cards"}), 500


@cei.route("/api/sow/cei/trend", methods=["GET"])
@login_required
def api_cei_trend():
    yearweeks = _get_yearweeks()
    if not yearweeks:
        return jsonify({"status": "error", "message": "No data"}), 404

    try:
        start_yw = request.args.get("start_yw", type=int) or (202611 if 202611 in yearweeks else yearweeks[-1])
        end_yw = request.args.get("end_yw", type=int) or yearweeks[0]
    except Exception:
        start_yw = 202611
        end_yw = yearweeks[0]

    metric_type = request.args.get("metric_type", "total_days").lower()
    cell_filter = request.args.get("cell_filter", "bad").lower()

    cache_key = f"trend:{start_yw}:{end_yw}:{metric_type}:{cell_filter}"
    now = time.time()
    if cache_key in _CEI_CACHE:
        val, exp = _CEI_CACHE[cache_key]
        if now < exp:
            return jsonify(val)

    where_filter = ""
    if cell_filter == "bad":
        where_filter = "AND remark_cell = 'Bad_cell'"
    elif cell_filter == "good":
        where_filter = "AND remark_cell = 'Good_cell'"

    target_val, _ = _get_target_for_week(end_yw)

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            # 1. Overall % good cell per week
            cur.execute("""
                SELECT weeknum,
                       COUNT(*) AS total_cells,
                       COUNT(*) FILTER (WHERE remark_cell = 'Good_cell') AS good_cells
                FROM sow.cei_score
                WHERE weeknum >= %s AND weeknum <= %s
                GROUP BY weeknum
                ORDER BY weeknum ASC
            """, (start_yw, end_yw))
            pct_rows = cur.fetchall()

            # 2. KQIs breakdown per week
            if metric_type == "total_days":
                kqi_exprs = ", ".join([f'SUM("{k["col"]}") AS val_{k["id"]}' for k in KQIS])
            else:
                kqi_exprs = ", ".join([f'COUNT(*) FILTER (WHERE "{k["col"]}" > 0) AS val_{k["id"]}' for k in KQIS])

            q_kqi = f"""
                SELECT weeknum, {kqi_exprs}
                FROM sow.cei_score
                WHERE weeknum >= %s AND weeknum <= %s {where_filter}
                GROUP BY weeknum
                ORDER BY weeknum ASC
            """
            cur.execute(q_kqi, (start_yw, end_yw))
            kqi_rows = {r[0]: r[1:] for r in cur.fetchall()}

        weeks_list = []
        weeks_labels = []
        good_pct_series = []

        for yw, total, good in pct_rows:
            weeks_list.append(yw)
            yw_s = str(yw)
            weeks_labels.append(f"W{yw_s[4:]}")
            pct = round(good * 100.0 / total, 2) if total else 0.0
            good_pct_series.append(pct)

        # Build series per KQI in exact stacking order
        kqi_series = {}
        for i, k in enumerate(KQIS):
            vals = []
            for yw in weeks_list:
                row_vals = kqi_rows.get(yw)
                vals.append(row_vals[i] or 0 if row_vals else 0)
            kqi_series[k["id"]] = vals

        res_data = {
            "status": "success",
            "weeks": weeks_list,
            "labels": weeks_labels,
            "good_pct_series": good_pct_series,
            "target": target_val,
            "kqi_series": kqi_series,
            "kqi_defs": KQIS,
        }

        _CEI_CACHE[cache_key] = (res_data, now + _CEI_CACHE_TTL)
        return jsonify(res_data)

    except Exception as e:
        logger.exception("Error calculating CEI trend: %s", e)
        return jsonify({"status": "error", "message": "Failed to compute trend"}), 500


@cei.route("/api/sow/cei/export", methods=["GET"])
@login_required
def api_cei_export():
    fmt = request.args.get("format", "csv").lower()
    start_yw = request.args.get("start_yw", type=int) or 202611
    end_yw = request.args.get("end_yw", type=int) or 202639
    cell_filter = request.args.get("cell_filter", "bad").lower()

    where_filter = ""
    if cell_filter == "bad":
        where_filter = "AND remark_cell = 'Bad_cell'"
    elif cell_filter == "good":
        where_filter = "AND remark_cell = 'Good_cell'"

    sum_cols = ", ".join([f'SUM("{k["col"]}")' for k in KQIS])
    hit_cols = ", ".join([f'COUNT(*) FILTER (WHERE "{k["col"]}" > 0)' for k in KQIS])

    headers = [
        "Weeknum", "Week Label", "Total Cells", "Good Cells", "% Good Cell", "Bad Cells"
    ] + [f"{k['title']} (Hit Days)" for k in KQIS] + [f"{k['title']} (Hit Cells)" for k in KQIS]

    with db_query(get_postgres_connection) as (conn, cur):
        cur.execute(f"""
            SELECT weeknum,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE remark_cell = 'Good_cell') AS good,
                   COUNT(*) FILTER (WHERE remark_cell = 'Bad_cell') AS bad,
                   {sum_cols},
                   {hit_cols}
            FROM sow.cei_score
            WHERE weeknum >= %s AND weeknum <= %s {where_filter}
            GROUP BY weeknum
            ORDER BY weeknum ASC
        """, (start_yw, end_yw))
        db_rows = cur.fetchall()

    export_rows = []
    for r in db_rows:
        yw = r[0]
        yw_s = str(yw)
        label = f"W{yw_s[4:]} {yw_s[:4]}"
        tot, gd, bd = r[1], r[2], r[3]
        pct = round(gd * 100.0 / tot, 2) if tot else 0.0
        export_rows.append([yw, label, tot, gd, pct, bd] + list(r[4:]))

    filename = f"cei_summary_{start_yw}_{end_yw}.csv"
    return csv_response(export_rows, headers, filename)
