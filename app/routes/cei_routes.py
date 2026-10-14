"""CEI Dashboard Routes — /sow/cei

Crowdsource Experience Index (CEI) dashboard based on sow.cei_score.
Replicates the 3-section layout:
  1. Top KPI Summary & Regional Benchmark Gauge
  2. 7 KQI Hit Rate Cards with Mini Sparklines & WoW Delta
  3. Weekly Trend Combination Chart (Stacked Bar KQIs + % Good Cell Line + Target)
"""
import csv
import io
import logging
import os
import tempfile
import threading
import time
import uuid
from collections import defaultdict
import psycopg2.extras
from flask import Blueprint, render_template, request, session, jsonify, make_response, send_file
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
    """Get list of weeknums, with auto-invalidation if DB max week changed."""
    now = time.time()
    
    # 1. Query current max week from DB (fast: uses index-only scan)
    db_max = 0
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT MAX(weeknum) FROM sow.cei_score")
            row = cur.fetchone()
            if row and row[0]:
                db_max = int(row[0])
    except Exception:
        pass

    # 2. Check cache and compare max week
    if "_yearweeks" in _CEI_CACHE:
        val, exp = _CEI_CACHE["_yearweeks"]
        if now < exp:
            cached_max = val[0] if val else 0
            # If DB max differs from cached max (higher OR lower after manual delete), cache is stale
            if db_max == cached_max and db_max > 0:
                return val  # Cache is still valid

    # 3. Cache miss, expired, or mismatched - refresh from DB
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT DISTINCT weeknum FROM sow.cei_score ORDER BY weeknum DESC")
            yws = [int(r[0]) for r in cur.fetchall() if r[0] is not None]
            _CEI_CACHE["_yearweeks"] = (yws, now + 1800)
            return yws
    except Exception as e:
        logger.exception("Error loading CEI yearweeks: %s", e)
        return []


def _quarter_for_week(yearweek):
    week = int(str(yearweek)[4:])
    if week <= 13:
        return "Q1"
    if week <= 26:
        return "Q2"
    if week <= 39:
        return "Q3"
    return "Q4"


def _get_all_targets():
    """All CEI targets from sow.sow_target, keyed by Year -> {'Baseline': pct, 'Q1': pct, ...}."""
    now = time.time()
    cached = _CEI_CACHE.get("_all_targets")
    if cached and now < cached[1]:
        return cached[0]
    targets = {}
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(
                'SELECT "Year", "Baseline", "Q1", "Q2", "Q3", "Q4" '
                'FROM sow.sow_target WHERE UPPER(TRIM("SOW")) = \'CEI\''
            )
            for year, baseline, *qs in cur.fetchall():
                q_map = {}
                if baseline is not None:
                    v = float(baseline)
                    if v <= 1.0:
                        v *= 100.0
                    q_map["Baseline"] = round(v, 2)
                for name, raw in zip(("Q1", "Q2", "Q3", "Q4"), qs):
                    if raw is None:
                        q_map[name] = None
                        continue
                    v = float(raw)
                    if v <= 1.0:
                        v *= 100.0
                    q_map[name] = round(v, 2)
                targets[int(year)] = q_map
    except Exception as e:
        logger.warning("Error fetching CEI targets: %s", e)
    _CEI_CACHE["_all_targets"] = (targets, now + 3600)
    return targets


def _get_target_for_week(yearweek):
    year = int(str(yearweek)[:4])
    q_col = _quarter_for_week(yearweek)
    val = _get_all_targets().get(year, {}).get(q_col)
    if val is None:
        return 93.95, f"Target {q_col}"
    return val, f"Target {q_col}"


@cei.route("/sow/cei")
@cei.route("/okr/cei")
@login_required
def cei_dashboard_page():
    yearweeks = _get_yearweeks()
    yearweeks_asc = list(reversed(yearweeks)) if yearweeks else []
    default_yw = yearweeks[0] if yearweeks else 202637
    default_start_yw = 202611 if 202611 in yearweeks else (yearweeks[-1] if yearweeks else 202611)
    default_gauge_yw = yearweeks[0] if yearweeks else 202637
    latest_week_label = f"W{str(default_yw)[4:]} ({default_yw})" if default_yw else "-"

    return render_template(
        "sow_cei.html",
        username=session.get("username", "User"),
        yearweeks=yearweeks,
        yearweeks_asc=yearweeks_asc,
        latest_week=latest_week_label,
        default_yw=default_yw,
        default_start_yw=default_start_yw,
        default_gauge_yw=default_gauge_yw,
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
                    "total": tot,
                    "good": gd,
                    "bad": tot - gd,
                    "fail": tot - gd,
                })

        yw_str = str(target_yw)
        label_week = f"W{yw_str[4:]} {yw_str[:4]}"
        prev_label = f"W{str(prev_yw)[4:]}" if prev_yw else "-"

        # Get CEI baseline for current year
        all_targets = _get_all_targets()
        year = int(str(target_yw)[:4])
        baseline = all_targets.get(year, {}).get("Baseline", 92.51) # Fallback to 92.51

        res_data = {
            "status": "success",
            "yearweeks": yearweeks,
            "weeknum": target_yw,
            "label_week": label_week,
            "prev_weeknum": prev_yw,
            "prev_label": prev_label,
            "good_cell_pct": good_pct,
            "is_above_target": good_pct >= target_val,
            "target": target_val,
            "baseline": baseline,
            "target_label": target_label,
            "quarter": _quarter_for_week(target_yw),
            "diff_target_pp": diff_target_pp,
            "needed_recover": needed_recover,
            "total_cells": total_cells,
            "good_cells": good_cells,
            "bad_cells": bad_cells,
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

    # yearweeks is DESC: take selected week + 7 earlier, reverse to ASC
    spark_yws = list(reversed(yearweeks[curr_idx:curr_idx + 8]))

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
                "avg_hit_days": curr_avg,
                "delta": delta,
                "delta_pct": delta_pct,
                "is_better": is_better,
                "total_hit_days": curr_sum,
                "hit_cells": curr_hits,
                "affected_cells": curr_hits,
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
        kqi_series_list = []
        for i, k in enumerate(KQIS):
            vals = []
            for yw in weeks_list:
                row_vals = kqi_rows.get(yw)
                vals.append(row_vals[i] or 0 if row_vals else 0)
            kqi_series[k["id"]] = vals
            kqi_series_list.append({
                "id": k["id"],
                "title": k["title"],
                "color": k.get("color", "#64748B"),
                "data": vals,
            })

        # Dynamic target per week (Q1..Q4 differ), from sow.sow_target SOW='CEI'
        all_targets = _get_all_targets()
        target_series = []
        for yw in weeks_list:
            t = all_targets.get(int(str(yw)[:4]), {}).get(_quarter_for_week(yw))
            target_series.append(t if t is not None else target_val)

        res_data = {
            "status": "success",
            "weeks": weeks_list,
            "labels": weeks_labels,
            "good_pct_series": good_pct_series,
            "target": target_val,
            "target_series": target_series,
            "kqi_series": kqi_series,
            "kqi_series_list": kqi_series_list,
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


def clear_cei_caches():
    """Clear all in-memory CEI caches."""
    _CEI_CACHE.clear()


CEI_COLUMNS = [
    "weeknum", "sai_cgi_ecgi",
    "latest_week_only_web_browsing_client_side_round_trip_time_ms_hi",
    "latest_week_only_web_browsing_ul_retransmitted_packet_rate_hit_",
    "latest_week_only_streaming_video_streaming_xkb_start_delay_s_hi",
    "latest_week_only_voip_udp_uplink_jitter_ms_hit_count",
    "latest_week_only_voip_udp_downlink_jitter_ms_hit_count",
    "latest_week_only_gamemax_client_side_round_trip_time_ms_hit_cou",
    "latest_week_only_gamemax_udp_uplink_jitter_ms_hit_count",
    "rule_1_days_hit_w_2", "rule_1_days_hit_w_1", "rule_1_days_hit_w_0", "rule_1_hit_at_week",
    "rule_2_friday", "rule_2_saturday", "rule_2_sunday", "rule_2_monday",
    "rule_2_tuesday", "rule_2_wednesday", "rule_2_thursday", "rule_2_hit_at_week",
    "remark_cell", "cgisai", "site_id", "cell_name", "cell_name_clean",
    "access_type", "longitude", "latitude", "id_desa", "desa",
    "id_kec", "kecamatan", "id_kab", "kabupaten", "id_region",
    "region", "id_area", "area", "state", "lac_dec",
    "ci_dec", "band", "site_type", "remark", "date",
    "CATEGORY", "MAIN ISSUE", "ROOT CAUSE", "ACTION CATEGORY", "DETAIL ACTION"
]

CEI_INT_COLS = {
    "weeknum",
    "latest_week_only_web_browsing_client_side_round_trip_time_ms_hi",
    "latest_week_only_web_browsing_ul_retransmitted_packet_rate_hit_",
    "latest_week_only_streaming_video_streaming_xkb_start_delay_s_hi",
    "latest_week_only_voip_udp_uplink_jitter_ms_hit_count",
    "latest_week_only_voip_udp_downlink_jitter_ms_hit_count",
    "latest_week_only_gamemax_client_side_round_trip_time_ms_hit_cou",
    "latest_week_only_gamemax_udp_uplink_jitter_ms_hit_count",
    "rule_1_days_hit_w_2", "rule_1_days_hit_w_1", "rule_1_days_hit_w_0", "rule_1_hit_at_week",
    "rule_2_friday", "rule_2_saturday", "rule_2_sunday", "rule_2_monday",
    "rule_2_tuesday", "rule_2_wednesday", "rule_2_thursday", "rule_2_hit_at_week",
    "id_region", "id_area"
}

CEI_FLOAT_COLS = {
    "longitude", "latitude", "id_desa", "id_kec", "id_kab", "lac_dec", "ci_dec"
}


def _safe_int(val, default=0):
    if val is None:
        return default
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null", ""):
        return default
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=None):
    if val is None:
        return default
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null", ""):
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def _safe_str(val, default=None):
    if val is None:
        return default
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return default
    return s


def _get_cei_sample_rows():
    return [
        [
            202638, "510107C85F1F", 2, 4, 0, 1, 1, 0, 1,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            "Good_cell", "510107C85F1F", "COK047", "E_COK047ML1_CombatIaasBioIntiAgrindo2_ML03",
            "COK047ML1_CombatIaasBioIntiAgrindo2_ML03", "4G", 140.91265, -7.102583,
            9401052010.0, "KANDRAKAI", 9401052.0, "ULILIN", 9401.0, "MERAUKE",
            11, "PUMA", 4, "PAMASUKA", "PAPUA", 510047.0, 31.0, "FDD LTE1800",
            "MACRO", "sample_import.csv", "00:00:00", "", "", "", "", ""
        ],
        [
            202638, "51010622610E", 1, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            "Good_cell", "51010622610E", "FFK017", "E_FFK017ME1_Wagom-TBG_ME01",
            "FFK017ME1_Wagom-TBG_ME01", "4G", 132.295711, -2.930681,
            9101062007.0, "KEL. WAGOM", 9101062.0, "PARIWARI", 9101.0, "FAKFAK",
            11, "PUMA", 4, "PAMASUKA", "PAPUA BARAT", 402017.0, 14.0, "TDD LTE2300",
            "MACRO", "sample_import.csv", "00:00:00", "", "", "", "", ""
        ],
        [
            202638, "5101091234AB", 5, 6, 2, 3, 2, 4, 3,
            1, 2, 3, 1, 1, 0, 1, 1, 0, 1, 1, 1,
            "Bad_cell", "5101091234AB", "AMB001", "E_AMB001ML1_KotaAmbonCenter_ML01",
            "AMB001ML1_KotaAmbonCenter_ML01", "4G", 128.18123, -3.69541,
            8171010001.0, "BATU MEJA", 8171010.0, "SIRIMAU", 8171.0, "KOTA AMBON",
            11, "PUMA", 4, "PAMASUKA", "MALUKU", 510012.0, 11.0, "FDD LTE1800",
            "MACRO", "sample_import.csv", "00:00:00", "High Retransmission", "Overload", "Congestion", "Expansion", "Add Carrier"
        ]
    ]


@cei.route("/api/sow/cei/sample", methods=["GET"])
@cei.route("/api/sow/cei/sample-template", methods=["GET"])
@login_required
def api_sow_cei_sample_template():
    """Download sample CSV or XLSX template for importing into sow.cei_score."""
    file_format = request.args.get("format", "xlsx").lower()
    headers = CEI_COLUMNS
    sample_rows = _get_cei_sample_rows()

    if file_format == "csv":
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(headers)
        writer.writerows(sample_rows)
        output = make_response(csv_buffer.getvalue())
        output.headers["Content-Disposition"] = "attachment; filename=OKR_CEI_Import_Sample.csv"
        output.headers["Content-type"] = "text/csv; charset=utf-8"
        return output
    else:
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "cei_score"
            ws.append(headers)
            for row in sample_rows:
                ws.append(row)
            excel_buffer = io.BytesIO()
            wb.save(excel_buffer)
            excel_buffer.seek(0)
            return send_file(
                excel_buffer,
                download_name="OKR_CEI_Import_Sample.xlsx",
                as_attachment=True,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            logger.exception("Error generating CEI Excel template: %s", e)
            return jsonify({"status": "error", "message": "Failed to generate Excel template"}), 500


# ══════════════════════════════════════════════════════════════════════
# CEI Import — async background worker + COPY FROM STDIN + live progress
# ══════════════════════════════════════════════════════════════════════
_CEI_IMPORT_JOBS = {}
_CEI_IMPORT_JOBS_LOCK = threading.Lock()


class _CeiCountingReader:
    def __init__(self, fh, total_bytes, job_id):
        self._fh = fh
        self._total = max(1, int(total_bytes or 0))
        self._job_id = job_id

    def read(self, size=-1):
        chunk = self._fh.read(size)
        self._update(len(chunk))
        return chunk

    def _update(self, n):
        if n <= 0: return
        with _CEI_IMPORT_JOBS_LOCK:
            job = _CEI_IMPORT_JOBS.get(self._job_id)
            if not job: return
            job["_read"] = job.get("_read", 0) + n
            read_bytes = job["_read"]
        pct = 10 + int(70 * min(1.0, read_bytes / float(self._total)))
        _cei_set_job(self._job_id, status="processing", pct=pct,
                     message="Uploading to database... %.1f/%.1f MB" % (
                         read_bytes / 1048576.0, self._total / 1048576.0))

    def readable(self): return True
    def writable(self): return False


def _cei_set_job(job_id, **kw):
    with _CEI_IMPORT_JOBS_LOCK:
        job = _CEI_IMPORT_JOBS.get(job_id)
        if job: job.update(kw)


@cei.route("/api/sow/cei/import", methods=["POST"])
@csrf.exempt
@login_required
def api_sow_cei_import():
    if "file" not in request.files: return jsonify({"status": "error", "message": "No file uploaded"}), 400
    uploaded_file = request.files["file"]
    filename = (uploaded_file.filename or "").lower()
    if not filename.endswith((".csv", ".xlsx", ".xls")):
        return jsonify({"status": "error", "message": "Only CSV and Excel (.xlsx, .xls) files are supported"}), 400

    job_id = uuid.uuid4().hex
    tmp_path = os.path.join(tempfile.gettempdir(), "cei_%s%s" % (job_id, os.path.splitext(filename)[1]))
    uploaded_file.save(tmp_path)
    with _CEI_IMPORT_JOBS_LOCK:
        _CEI_IMPORT_JOBS[job_id] = {"status": "processing", "pct": 2, "message": "Queued...", "created": time.time(), "_read": 0}
    threading.Thread(target=_bg_cei_import, args=(job_id, tmp_path, filename), daemon=True).start()
    return jsonify({"status": "queued", "job_id": job_id}), 202


@cei.route("/api/sow/cei/import/progress/<job_id>", methods=["GET"])
@login_required
def api_sow_cei_import_progress(job_id):
    with _CEI_IMPORT_JOBS_LOCK:
        job = _CEI_IMPORT_JOBS.get(job_id)
        if job is None: return jsonify({"status": "error", "message": "Job not found"}), 404
        snapshot = {k: v for k, v in job.items() if not k.startswith("_")}
    return jsonify(snapshot)


def _bg_cei_import(job_id, tmp_path, filename):
    try:
        _cei_set_job(job_id, status="processing", pct=5, message="Parsing file...")
        raw_rows = []
        if filename.endswith(".csv"):
            with open(tmp_path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
                reader = csv.reader(fh)
                headers = next(reader)
                idx = {str(h).strip().lower(): i for i, h in enumerate(headers)}
                for r in reader:
                    if any(r): raw_rows.append([r[idx.get(c, -1)] if idx.get(c, -1) != -1 else "" for c in CEI_COLUMNS])
        else:
            from python_calamine import CalamineWorkbook
            wb = CalamineWorkbook.from_path(tmp_path)
            rows = list(wb.get_sheet_by_index(0).to_python())
            idx = {str(h).strip().lower(): i for i, h in enumerate(rows[0])}
            for r in rows[1:]:
                raw_rows.append([r[idx.get(c, -1)] if idx.get(c, -1) != -1 else "" for c in CEI_COLUMNS])

        converted = []
        weeknums = set()
        week_idx = CEI_COLUMNS.index("weeknum")
        int_idx = {CEI_COLUMNS.index(c) for c in CEI_INT_COLS}
        float_idx = {CEI_COLUMNS.index(c) for c in CEI_FLOAT_COLS}

        for r in raw_rows:
            yw = _safe_int(r[week_idx], 0)
            if yw <= 0: continue
            weeknums.add(yw)
            out = []
            for i, val in enumerate(r):
                if i == week_idx: out.append(str(yw))
                elif i in int_idx: out.append(str(_safe_int(val, 0)))
                elif i in float_idx: out.append("" if (fv := _safe_float(val)) is None else str(fv))
                else: out.append(_safe_str(val, ""))
            converted.append(out)

        _cei_set_job(job_id, status="processing", pct=15, message="Uploading...")
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerows(converted)
        payload = buf.getvalue().encode("utf-8")
        
        with get_postgres_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM sow.cei_score WHERE weeknum IN (%s)" % ",".join(["%s"]*len(weeknums)), tuple(weeknums))
            cur.copy_expert("COPY sow.cei_score (%s) FROM STDIN WITH (FORMAT CSV, NULL '')" % 
                            ",".join(['"%s"' % c for c in CEI_COLUMNS]), _CeiCountingReader(io.BytesIO(payload), len(payload), job_id))
            conn.commit()
            cur.close()
            conn.close()

        clear_cei_caches()
        _cei_set_job(job_id, status="success", pct=100, message="Import complete.")
    except Exception as e:
        _cei_set_job(job_id, status="error", pct=0, message=str(e))
    finally:
        if os.path.exists(tmp_path): os.remove(tmp_path)


# ══════════════════════════════════════════════════════════════════════
# CEI Achievement Chart — stacked Good/Bad counts + % Good Cell + Target
# (matches reference "CEI Trend Achievement" combo chart)
# ══════════════════════════════════════════════════════════════════════
@cei.route("/api/sow/cei/achievement", methods=["GET"])
@login_required
def api_cei_achievement():
    yearweeks = _get_yearweeks()
    if not yearweeks:
        return jsonify({"status": "error", "message": "No data"}), 404
    try:
        start_yw = request.args.get("start_yw", type=int) or (202601 if 202601 in yearweeks else yearweeks[-1])
        end_yw = request.args.get("end_yw", type=int) or yearweeks[0]
    except Exception:
        start_yw, end_yw = yearweeks[-1], yearweeks[0]

    cache_key = f"achievement:{start_yw}:{end_yw}"
    now = time.time()
    if cache_key in _CEI_CACHE:
        val, exp = _CEI_CACHE[cache_key]
        if now < exp:
            return jsonify(val)
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("""
                SELECT weeknum,
                       COUNT(*) AS total_cells,
                       COUNT(*) FILTER (WHERE remark_cell = 'Good_cell') AS good_cells,
                       COUNT(*) FILTER (WHERE remark_cell = 'Bad_cell') AS bad_cells
                FROM sow.cei_score
                WHERE weeknum >= %s AND weeknum <= %s
                GROUP BY weeknum
                ORDER BY weeknum ASC
            """, (start_yw, end_yw))
            rows = cur.fetchall()
        weeks, labels, good_counts, bad_counts, total_counts, good_pct = [], [], [], [], [], []
        for yw, total, good, bad in rows:
            weeks.append(yw)
            yw_s = str(yw)
            labels.append(f"W{yw_s[4:]}")
            good_counts.append(good or 0)
            bad_counts.append(bad or 0)
            total_counts.append(total or 0)
            good_pct.append(round(good * 100.0 / total, 2) if total else 0.0)
        all_targets = _get_all_targets()
        target_series = []
        for yw in weeks:
            t = all_targets.get(int(str(yw)[:4]), {}).get(_quarter_for_week(yw))
            target_series.append(t if t is not None else 93.95)
        target_val, _ = _get_target_for_week(end_yw if weeks else (yearweeks[0]))
        res_data = {
            "status": "success", "weeks": weeks, "labels": labels,
            "good_counts": good_counts, "bad_counts": bad_counts,
            "total_counts": total_counts, "good_pct_series": good_pct,
            "target_series": target_series, "target": target_val,
        }
        _CEI_CACHE[cache_key] = (res_data, now + _CEI_CACHE_TTL)
        return jsonify(res_data)
    except Exception as e:
        logger.exception("Error calculating CEI achievement: %s", e)
        return jsonify({"status": "error", "message": "Failed to compute achievement"}), 500


# ══════════════════════════════════════════════════════════════════════
# CEI Geo filters + 7-KQI geo trend (filter by kabupaten/kecamatan)
# ══════════════════════════════════════════════════════════════════════
@cei.route("/api/sow/cei/geo-options", methods=["GET"])
@login_required
def api_cei_geo_options():
    cache_key = "geo_options"
    now = time.time()
    if cache_key in _CEI_CACHE:
        val, exp = _CEI_CACHE[cache_key]
        if now < exp:
            return jsonify(val)
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("""
                SELECT DISTINCT TRIM(kabupaten) FROM sow.cei_score
                WHERE kabupaten IS NOT NULL AND TRIM(kabupaten) <> ''
                ORDER BY 1
            """)
            kabs = [r[0] for r in cur.fetchall()]
            cur.execute("""
                SELECT TRIM(kabupaten), TRIM(kecamatan) FROM sow.cei_score
                WHERE kabupaten IS NOT NULL AND kecamatan IS NOT NULL
                GROUP BY TRIM(kabupaten), TRIM(kecamatan) ORDER BY 1, 2
            """)
            kec_map = {}
            for kab, kec in cur.fetchall():
                kec_map.setdefault(kab, []).append(kec)
        res_data = {"status": "success", "kabupaten": kabs, "kecamatan_map": kec_map}
        _CEI_CACHE[cache_key] = (res_data, now + 86400)
        return jsonify(res_data)
    except Exception as e:
        logger.exception("Error loading CEI geo options: %s", e)
        return jsonify({"status": "error", "message": "Failed to load geo options"}), 500


@cei.route("/api/sow/cei/geo-trend", methods=["GET"])
@login_required
def api_cei_geo_trend():
    kabupaten = (request.args.get("kabupaten") or "").strip()
    kecamatan = (request.args.get("kecamatan") or "").strip()
    cell_filter = request.args.get("cell_filter", "bad").lower()
    metric_type = request.args.get("metric_type", "avg").lower()  # avg | total_days | cell_count
    where_parts, params = [], []
    if kabupaten:
        where_parts.append("UPPER(TRIM(kabupaten)) = UPPER(TRIM(%s))")
        params.append(kabupaten)
    if kecamatan:
        where_parts.append("UPPER(TRIM(kecamatan)) = UPPER(TRIM(%s))")
        params.append(kecamatan)
    cell_clause = ""
    if cell_filter == "bad":
        cell_clause = "AND remark_cell = 'Bad_cell'"
    elif cell_filter == "good":
        cell_clause = "AND remark_cell = 'Good_cell'"
    geo_where = (" AND ".join(where_parts))
    geo_where = f"AND {geo_where}" if geo_where else ""
    cache_key = f"geo_trend:{kabupaten}:{kecamatan}:{cell_filter}:{metric_type}"
    now = time.time()
    if cache_key in _CEI_CACHE:
        val, exp = _CEI_CACHE[cache_key]
        if now < exp:
            return jsonify(val)
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            q_pct = f"""
                SELECT weeknum, COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE remark_cell = 'Good_cell') AS good
                FROM sow.cei_score WHERE 1=1 {geo_where}
                GROUP BY weeknum ORDER BY weeknum ASC
            """
            cur.execute(q_pct, tuple(params))
            pct_rows = cur.fetchall()
            if metric_type == "cell_count":
                kqi_exprs = ", ".join([f'COUNT(*) FILTER (WHERE "{k["col"]}" > 0) AS val_{k["id"]}' for k in KQIS])
            elif metric_type == "total_days":
                kqi_exprs = ", ".join([f'SUM("{k["col"]}") AS val_{k["id"]}' for k in KQIS])
            else:
                kqi_exprs = ", ".join(
                    [f'ROUND(SUM("{k["col"]}") * 1.0 / NULLIF(COUNT(*),0), 2) AS val_{k["id"]}' for k in KQIS])
            q_kqi = f"""
                SELECT weeknum, COUNT(*) AS n, {kqi_exprs}
                FROM sow.cei_score WHERE 1=1 {geo_where} {cell_clause}
                GROUP BY weeknum ORDER BY weeknum ASC
            """
            cur.execute(q_kqi, tuple(params))
            kqi_rows = {r[0]: r[2:] for r in cur.fetchall()}
            # summary on latest week with geo filter
            q_sum = f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE remark_cell = 'Good_cell') AS good,
                       COUNT(*) FILTER (WHERE remark_cell = 'Bad_cell') AS bad
                FROM sow.cei_score WHERE weeknum = (SELECT MAX(weeknum) FROM sow.cei_score WHERE 1=1 {geo_where})
                {geo_where}
            """
            cur.execute(q_sum, tuple(params + params))
            srow = cur.fetchone()
        weeks, labels, good_pct = [], [], []
        for yw, total, good in pct_rows:
            weeks.append(yw)
            weeks_labels_yw = str(yw)
            labels.append(f"W{weeks_labels_yw[4:]}")
            good_pct.append(round(good * 100.0 / total, 2) if total else 0.0)
        kqi_series = {}
        for i, k in enumerate(KQIS):
            vals = []
            for yw in weeks:
                rv = kqi_rows.get(yw)
                vals.append(float(rv[i] or 0) if rv else 0)
            kqi_series[k["id"]] = vals
        all_targets = _get_all_targets()
        target_series = []
        for yw in weeks:
            t = all_targets.get(int(str(yw)[:4]), {}).get(_quarter_for_week(yw))
            target_series.append(t if t is not None else 93.95)
        latest_yw = weeks[-1] if weeks else None
        prev_yw = weeks[-2] if len(weeks) >= 2 else None
        tgt_latest, _ = _get_target_for_week(latest_yw) if latest_yw else (93.95, "")
        tot, gd, bd = (srow[0] or 0, srow[1] or 0, srow[2] or 0) if srow else (0, 0, 0)
        pct_latest = round(gd * 100.0 / tot, 2) if tot else 0.0
        pct_prev = good_pct[-2] if len(good_pct) >= 2 else None
        diff_wow = round(pct_latest - pct_prev, 2) if pct_prev is not None else 0.0
        diff_target = round(pct_latest - tgt_latest, 2) if tgt_latest else 0.0

        res_data = {
            "status": "success", "weeks": weeks, "labels": labels,
            "good_pct_series": good_pct, "target_series": target_series,
            "kqi_series": kqi_series, "kqi_defs": KQIS,
            "summary": {
                "weeknum": latest_yw, "total": tot, "good": gd, "bad": bd,
                "pct": pct_latest, "target": tgt_latest,
                "prev_weeknum": prev_yw, "prev_pct": pct_prev,
                "diff_wow": diff_wow, "diff_target": diff_target,
                "quarter": _quarter_for_week(latest_yw) if latest_yw else "Q",
                "is_above": pct_latest >= tgt_latest,
                "kabupaten": kabupaten or "All", "kecamatan": kecamatan or "All",
            },
        }
        _CEI_CACHE[cache_key] = (res_data, now + _CEI_CACHE_TTL)
        return jsonify(res_data)
    except Exception as e:
        logger.exception("Error calculating CEI geo trend: %s", e)
        return jsonify({"status": "error", "message": "Failed to compute geo trend"}), 500


# ══════════════════════════════════════════════════════════════════════
# CEI Comparison — NOP (branch via fb_share lookup) WoW + 7-KQI WoW
# ══════════════════════════════════════════════════════════════════════
@cei.route("/api/sow/cei/comparison", methods=["GET"])
@login_required
def api_cei_comparison():
    yearweeks = _get_yearweeks()
    if len(yearweeks) < 1:
        return jsonify({"status": "error", "message": "No data"}), 404
    try:
        req_yw = request.args.get("weeknum", type=int)
        curr_yw = req_yw if req_yw and req_yw in yearweeks else yearweeks[0]
    except Exception:
        curr_yw = yearweeks[0]
    curr_idx = yearweeks.index(curr_yw) if curr_yw in yearweeks else 0
    prev_yw = yearweeks[curr_idx + 1] if curr_idx + 1 < len(yearweeks) else None
    if prev_yw is None:
        return jsonify({"status": "error", "message": "Need at least 2 weeks for WoW comparison"}), 400
    target_val, _ = _get_target_for_week(curr_yw)

    req_branch = (request.args.get("branch") or "").strip().upper()
    req_kab = (request.args.get("kabupaten") or "").strip().upper()
    req_kec = (request.args.get("kecamatan") or "").strip().upper()

    cache_key = f"comparison:{curr_yw}:{prev_yw}:{req_branch}:{req_kab}:{req_kec}"
    now = time.time()
    if cache_key in _CEI_CACHE:
        val, exp = _CEI_CACHE[cache_key]
        if now < exp:
            return jsonify(val)
    try:
        branch_map = _get_branch_map()

        filter_parts = []
        filter_params = []
        if req_kec:
            filter_parts.append("UPPER(TRIM(kecamatan)) = %s")
            filter_params.append(req_kec)
        if req_kab:
            filter_parts.append("UPPER(TRIM(kabupaten)) = %s")
            filter_params.append(req_kab)
        elif req_branch and req_branch != "ALL":
            kabs_in_branch = [k for k, b in branch_map.items() if b == req_branch]
            if kabs_in_branch:
                filter_parts.append("UPPER(TRIM(kabupaten)) = ANY(%s)")
                filter_params.append(kabs_in_branch)

        kqi_where = f"AND {' AND '.join(filter_parts)}" if filter_parts else ""

        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("""
                SELECT UPPER(TRIM(kabupaten)), weeknum,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE remark_cell = 'Good_cell') AS good,
                       COUNT(*) FILTER (WHERE remark_cell = 'Bad_cell') AS bad
                FROM sow.cei_score
                WHERE weeknum = ANY(%s) AND kabupaten IS NOT NULL
                GROUP BY UPPER(TRIM(kabupaten)), weeknum
            """, ([curr_yw, prev_yw],))
            kab_rows = cur.fetchall()

            sum_exprs = ", ".join([f'SUM("{k["col"]}") AS s_{k["id"]}' for k in KQIS])
            q_kqi = f"""
                SELECT weeknum, {sum_exprs}
                FROM sow.cei_score WHERE weeknum = ANY(%s) {kqi_where}
                GROUP BY weeknum
            """
            cur.execute(q_kqi, ([curr_yw, prev_yw], *filter_params))
            kqi_totals = {r[0]: list(r[1:]) for r in cur.fetchall()}
        # aggregate kabupaten -> branch
        branches = ["AMBON", "JAYAPURA", "SORONG", "TIMIKA"]
        agg = {b: {curr_yw: [0, 0, 0], prev_yw: [0, 0, 0]} for b in branches}
        puma = {curr_yw: [0, 0, 0], prev_yw: [0, 0, 0]}
        for kab, yw, total, good, bad in kab_rows:
            b = branch_map.get(kab, "OTHER")
            puma[yw][0] += total or 0
            puma[yw][1] += good or 0
            puma[yw][2] += bad or 0
            if b in agg:
                agg[b][yw][0] += total or 0
                agg[b][yw][1] += good or 0
                agg[b][yw][2] += bad or 0

        def _row(nop, d_curr, d_prev):
            tot_c, gd_c, bd_c = d_curr
            tot_p, gd_p, bd_p = d_prev
            ach_c = round(gd_c * 100.0 / tot_c, 2) if tot_c else 0.0
            ach_p = round(gd_p * 100.0 / tot_p, 2) if tot_p else 0.0
            d_tgt = round(ach_c - target_val, 2)
            wow = round(ach_c - ach_p, 2)
            return {
                "nop": nop, "target": target_val,
                "prev_total": tot_p, "prev_good": gd_p, "prev_bad": bd_p, "prev_ach": ach_p,
                "curr_total": tot_c, "curr_good": gd_c, "curr_bad": bd_c, "curr_ach": ach_c,
                "delta_target": d_tgt, "delta_wow": wow, "ach_wow": wow,
                "st_target": "Pass" if ach_c >= target_val else "Not Pass",
                "st_wow": "Improved" if wow > 0 else ("Stable" if wow == 0 else "Degraded"),
            }

        rows = [_row(b, agg[b][curr_yw], agg[b][prev_yw]) for b in branches]
        rows.append(_row("PUMA", puma[curr_yw], puma[prev_yw]))
        # 7-KQI WoW
        kqi_wow = []
        for i, k in enumerate(KQIS):
            before = (kqi_totals.get(prev_yw, [0] * len(KQIS))[i]) or 0
            after = (kqi_totals.get(curr_yw, [0] * len(KQIS))[i]) or 0
            delta = after - before
            delta_pct = round(delta * 100.0 / before, 2) if before else (0.0 if after == 0 else 100.0)
            kqi_wow.append({
                "id": k["id"], "title": k["title"],
                "before": before, "after": after, "delta": delta,
                "delta_pct": delta_pct,
                "remark": "Improve" if delta < 0 else ("Stable" if delta == 0 else "Degrade"),
            })
        res_data = {
            "status": "success", "curr_week": curr_yw, "prev_week": prev_yw,
            "target": target_val, "rows": rows, "kqi_wow": kqi_wow,
            "filter": {"branch": req_branch or "ALL", "kabupaten": req_kab, "kecamatan": req_kec},
        }
        _CEI_CACHE[cache_key] = (res_data, now + _CEI_CACHE_TTL)
        return jsonify(res_data)
    except Exception as e:
        logger.exception("Error calculating CEI comparison: %s", e)
        return jsonify({"status": "error", "message": "Failed to compute comparison"}), 500


# ══════════════════════════════════════════════════════════════════════
# CEI Comparison — Kabupaten Level WoW + 7-KQI Breakdown
# ══════════════════════════════════════════════════════════════════════
@cei.route("/api/sow/cei/comparison-kabupaten", methods=["GET"])
@login_required
def api_cei_comparison_kabupaten():
    yearweeks = _get_yearweeks()
    if len(yearweeks) < 1:
        return jsonify({"status": "error", "message": "No data"}), 404
    try:
        req_yw = request.args.get("weeknum", type=int)
        curr_yw = req_yw if req_yw and req_yw in yearweeks else yearweeks[0]
    except Exception:
        curr_yw = yearweeks[0]
    curr_idx = yearweeks.index(curr_yw) if curr_yw in yearweeks else 0
    prev_yw = yearweeks[curr_idx + 1] if curr_idx + 1 < len(yearweeks) else None
    if prev_yw is None:
        return jsonify({"status": "error", "message": "Need at least 2 weeks for WoW comparison"}), 400

    target_val, _ = _get_target_for_week(curr_yw)
    branch_filter = (request.args.get("branch") or "").strip().upper()
    kqi_filter = (request.args.get("kqi") or "").strip()

    cache_key = f"comparison_kab:{curr_yw}:{prev_yw}:{branch_filter}:{kqi_filter}"
    now = time.time()
    if cache_key in _CEI_CACHE:
        val, exp = _CEI_CACHE[cache_key]
        if now < exp:
            return jsonify(val)

    try:
        branch_map = _get_branch_map()
        sum_exprs = ", ".join([f'SUM("{k["col"]}") AS s_{k["id"]}' for k in KQIS])
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(f"""
                SELECT UPPER(TRIM(kabupaten)), weeknum,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE remark_cell = 'Good_cell') AS good,
                       COUNT(*) FILTER (WHERE remark_cell = 'Bad_cell') AS bad,
                       {sum_exprs}
                FROM sow.cei_score
                WHERE weeknum = ANY(%s) AND kabupaten IS NOT NULL
                GROUP BY UPPER(TRIM(kabupaten)), weeknum
                ORDER BY 1, 2
            """, ([curr_yw, prev_yw],))
            raw_rows = cur.fetchall()

        # Organize by kabupaten -> {curr_yw: {...}, prev_yw: {...}}
        kab_dict = defaultdict(dict)
        for r in raw_rows:
            kab = r[0]
            yw = r[1]
            tot = r[2] or 0
            gd = r[3] or 0
            bd = r[4] or 0
            kqis_data = {KQIS[i]["id"]: (r[5 + i] or 0) for i in range(len(KQIS))}
            kab_dict[kab][yw] = {
                "total": tot,
                "good": gd,
                "bad": bd,
                "ach": round(gd * 100.0 / tot, 2) if tot else 0.0,
                "kqis": kqis_data,
            }

        kab_rows = []
        for kab, yws in sorted(kab_dict.items()):
            b_name = branch_map.get(kab, "OTHER")
            if branch_filter and branch_filter != "ALL" and b_name != branch_filter:
                continue

            c_data = yws.get(curr_yw, {"total": 0, "good": 0, "bad": 0, "ach": 0.0, "kqis": {}})
            p_data = yws.get(prev_yw, {"total": 0, "good": 0, "bad": 0, "ach": 0.0, "kqis": {}})

            d_tgt = round(c_data["ach"] - target_val, 2)
            wow = round(c_data["ach"] - p_data["ach"], 2)

            kqi_breakdown = {}
            for k in KQIS:
                kid = k["id"]
                b_val = p_data["kqis"].get(kid, 0)
                a_val = c_data["kqis"].get(kid, 0)
                d_val = a_val - b_val
                d_pct = round(d_val * 100.0 / b_val, 2) if b_val else (0.0 if a_val == 0 else 100.0)
                kqi_breakdown[kid] = {
                    "before": b_val,
                    "after": a_val,
                    "delta": d_val,
                    "delta_pct": d_pct,
                    "remark": "Improve" if d_val < 0 else ("Stable" if d_val == 0 else "Degrade"),
                }

            kab_rows.append({
                "kabupaten": kab,
                "branch": b_name,
                "target": target_val,
                "prev_total": p_data["total"],
                "prev_good": p_data["good"],
                "prev_bad": p_data["bad"],
                "prev_ach": p_data["ach"],
                "curr_total": c_data["total"],
                "curr_good": c_data["good"],
                "curr_bad": c_data["bad"],
                "curr_ach": c_data["ach"],
                "delta_target": d_tgt,
                "ach_wow": wow,
                "st_target": "Pass" if c_data["ach"] >= target_val else "Not Pass",
                "st_wow": "Improved" if wow > 0 else ("Stable" if wow == 0 else "Degraded"),
                "kqis": kqi_breakdown,
            })

        res_data = {
            "status": "success",
            "curr_week": curr_yw,
            "prev_week": prev_yw,
            "target": target_val,
            "branches": ["AMBON", "JAYAPURA", "SORONG", "TIMIKA"],
            "kqi_defs": KQIS,
            "rows": kab_rows,
        }
        _CEI_CACHE[cache_key] = (res_data, now + _CEI_CACHE_TTL)
        return jsonify(res_data)
    except Exception as e:
        logger.exception("Error calculating CEI Kabupaten comparison: %s", e)
        return jsonify({"status": "error", "message": "Failed to compute Kabupaten comparison"}), 500

