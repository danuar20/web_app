from flask import Blueprint, render_template, request, session, jsonify, send_file, make_response, Response, stream_with_context
from app import csrf
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, viewer_blocked, db_query
import logging
import time
import io
import csv
import psycopg2.extras
import datetime
import os
import uuid
import tempfile
import threading

logger = logging.getLogger(__name__)

sow = Blueprint("sow", __name__)

# Async import progress tracking
_ONX_IMPORT_JOBS = {}
_ONX_IMPORT_JOBS_LOCK = threading.Lock()
_FB_IMPORT_JOBS = {}
_FB_IMPORT_JOBS_LOCK = threading.Lock()

# In-memory caches for fast responses
_LOCATIONS_CACHE = {}
_KAB_REGIONS_CACHE = {"data": None, "timestamp": 0}
_YEARWEEKS_CACHE = {"data": None, "timestamp": 0}
_SUMMARY_YEARS_CACHE = {"data": None, "timestamp": 0}
_CACHE_TTL = 1800  # 30 minutes


def clear_sow_caches():
    """Clear memory caches after data updates/imports."""
    global _LOCATIONS_CACHE, _KAB_REGIONS_CACHE, _YEARWEEKS_CACHE, _SUMMARY_YEARS_CACHE
    _LOCATIONS_CACHE.clear()
    _KAB_REGIONS_CACHE = {"data": None, "timestamp": 0}
    _YEARWEEKS_CACHE = {"data": None, "timestamp": 0}
    _SUMMARY_YEARS_CACHE = {"data": None, "timestamp": 0}
    _FB_YEARWEEKS_CACHE["data"] = None
    _FB_YEARWEEKS_CACHE["timestamp"] = 0
    _FB_CITY_MASTER_CACHE["data"] = None
    _FB_CITY_MASTER_CACHE["timestamp"] = 0


def get_cached_kab_regions():
    """Retrieve distinct Region values for level='Kabupaten'."""
    now = time.time()
    if _KAB_REGIONS_CACHE["data"] and (now - _KAB_REGIONS_CACHE["timestamp"] < _CACHE_TTL):
        return _KAB_REGIONS_CACHE["data"]
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(
                """
                SELECT DISTINCT "Region"
                FROM sow.onx_rank_score
                WHERE level = 'Kabupaten' AND "Region" IS NOT NULL AND "Region" != '' AND "Region" != '-'
                ORDER BY "Region" ASC
                """
            )
            regions = [r[0] for r in cur.fetchall() if r[0]]
            _KAB_REGIONS_CACHE["data"] = regions
            _KAB_REGIONS_CACHE["timestamp"] = now
            return regions
    except Exception as e:
        logger.exception("Error loading Kabupaten regions: %s", e)
        return []


def get_cached_locations(level, region=None):
    """Retrieve distinct locations for a level (and optional Region for Kabupaten)."""
    cache_key = f"{level}:{region or ''}"
    if cache_key in _LOCATIONS_CACHE:
        return _LOCATIONS_CACHE[cache_key]
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            if level == "Kabupaten" and region:
                cur.execute(
                    """
                    SELECT DISTINCT location 
                    FROM sow.onx_rank_score 
                    WHERE level = %s AND "Region" = %s
                    ORDER BY location ASC
                    """,
                    (level, region)
                )
            else:
                cur.execute(
                    """
                    SELECT DISTINCT location 
                    FROM sow.onx_rank_score 
                    WHERE level = %s 
                    ORDER BY location ASC
                    """,
                    (level,)
                )
            locs = [r[0] for r in cur.fetchall() if r[0] is not None]
            _LOCATIONS_CACHE[cache_key] = locs
            return locs
    except Exception as e:
        logger.exception("Error loading locations for level %s, region %s: %s", level, region, e)
        return []


def get_cached_yearweeks():
    """Retrieve all distinct yearweeks sorted descending, with auto-invalidation if DB max week changed."""
    now = time.time()
    
    # 1. Query current max yearweek from DB (fast: uses index-only scan)
    db_max = 0
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT MAX(yearweek) FROM sow.onx_rank_score")
            row = cur.fetchone()
            if row and row[0]:
                db_max = int(row[0])
    except Exception:
        pass

    # 2. Check cache: if DB max week differs from cached max, we're stale
    if _YEARWEEKS_CACHE["data"] and (now - _YEARWEEKS_CACHE["timestamp"] < _CACHE_TTL):
        val = _YEARWEEKS_CACHE["data"]
        cached_max = val[0] if val else 0
        # Return cached data ONLY if the DB max matches what we cached
        if db_max == cached_max and db_max > 0:
            return val

    # 3. Cache miss, expired, or mismatched - refresh from DB
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT DISTINCT yearweek FROM sow.onx_rank_score WHERE yearweek IS NOT NULL ORDER BY yearweek DESC")
            yws = [int(r[0]) for r in cur.fetchall()]
            _YEARWEEKS_CACHE["data"] = yws
            _YEARWEEKS_CACHE["timestamp"] = now
            return yws
    except Exception as e:
        logger.exception("Error loading yearweeks: %s", e)
        return []


# Standard 16 metrics in order
ORDERED_16_METRICS = [
    # Col 1: Overall experience & timeon
    "videoexperience_overall",
    "gamesexperience_overall",
    "voiceexperience_overall",
    "timeon_overall",
    # Col 2: Overall speed & quality
    "download_overall",
    "upload_overall",
    "reliability_overall",
    "consistentquality_overall",
    # Col 3: 5G experience & timeon
    "videoexperience_5g",
    "gamesexperience_5g",
    "voiceexperience_5g",
    "timeon_5g",
    # Col 4: 5G speed & coverage
    "download_5g",
    "upload_5g",
    "onxcoveragesim_5g",
    "onxcoveragesim_overall"
]

METRIC_TITLES = {
    "consistentquality_overall": "Consistent Quality Overall",
    "download_5g": "Download Speed 5G",
    "download_overall": "Download Speed Overall",
    "gamesexperience_5g": "Games Experience 5G",
    "gamesexperience_overall": "Games Experience Overall",
    "onxcoveragesim_5g": "Coverage Experience 5G",
    "onxcoveragesim_overall": "Coverage Experience Overall",
    "reliability_overall": "Reliability Experience",
    "timeon_5g": "Time on 5G",
    "timeon_overall": "Time on Overall",
    "upload_5g": "Upload Speed 5G",
    "upload_overall": "Upload Speed Overall",
    "videoexperience_5g": "Video Experience 5G",
    "videoexperience_overall": "Video Experience Overall",
    "voiceexperience_5g": "Voice Experience 5G",
    "voiceexperience_overall": "Voice Experience Overall",
}



@sow.route('/api/sow/crowdsource_onx-csv-export', methods=['GET'])
@login_required
def api_sow_crowdsource_onx_csv_export():
    """
    Export ONX rank score data to CSV, filtered by week or week range.
    Accepts 'week' (single ISO YYYYWW) or 'start_week' & 'end_week'.
    """
    try:
        week = request.args.get("week")
        start_week = request.args.get("start_week")
        end_week = request.args.get("end_week")

        if week:
            start_yw = int(week)
            end_yw = int(week)
        elif start_week and end_week:
            start_yw = int(start_week)
            end_yw = int(end_week)
            if start_yw > end_yw:
                start_yw, end_yw = end_yw, start_yw
        else:
            return jsonify({"status": "error", "message": "Must provide 'week' or 'start_week'/'end_week'"}), 400

    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid yearweek format"}), 400

    return _stream_table_csv(
        "onx_rank_score", "yearweek", start_yw, end_yw,
        f"ONX_Crowdsource_Export_{start_yw}-{end_yw}.csv",
    )

@sow.route('/api/sow/crowdsource_fb-csv-export', methods=['GET'])
@login_required
def api_sow_crowdsource_fb_csv_export():
    """
    Export FB Share data to CSV, filtered by week or week range.
    Accepts 'week' (single ISO YYYYWW) or 'start_week'/'end_week'.
    """
    try:
        week = request.args.get("week")
        start_week = request.args.get("start_week")
        end_week = request.args.get("end_week")

        if week:
            start_yw = int(week)
            end_yw = int(week)
        elif start_week and end_week:
            start_yw = int(start_week)
            end_yw = int(end_week)
            if start_yw > end_yw:
                start_yw, end_yw = end_yw, start_yw
        else:
            return jsonify({"status": "error", "message": "Must provide 'week' or 'start_week'/'end_week'"}), 400

    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid yearweek format"}), 400

    return _stream_table_csv(
        "fb_share", "yearweek", start_yw, end_yw,
        f"FB_Share_Crowdsource_Export_{start_yw}-{end_yw}.csv",
    )


_FB_YEARWEEKS_CACHE = {"data": None, "timestamp": 0}
FB_PROVIDERS = ("tsel", "ioh", "xls")  # tsel=telkomsel, ioh=isat3, xls=xl+smartfren


def get_cached_fb_yearweeks():
    """Distinct yearweeks available in sow.fb_share (descending), with auto-invalidation if DB max week changed."""
    now = time.time()
    
    # 1. Query current max yearweek from DB (fast: uses index-only scan)
    db_max = 0
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT MAX(yearweek) FROM sow.fb_share")
            row = cur.fetchone()
            if row and row[0]:
                db_max = int(row[0])
    except Exception:
        pass

    # 2. Check cache: if DB max week differs from cached max, we're stale
    if _FB_YEARWEEKS_CACHE["data"] and (now - _FB_YEARWEEKS_CACHE["timestamp"] < _CACHE_TTL):
        val = _FB_YEARWEEKS_CACHE["data"]
        cached_max = val[0] if val else 0
        # Return cached data ONLY if the DB max matches what we cached
        if db_max == cached_max and db_max > 0:
            return val

    # 3. Cache miss, expired, or mismatched - refresh from DB
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT DISTINCT yearweek FROM sow.fb_share WHERE yearweek IS NOT NULL ORDER BY yearweek DESC")
            yws = [int(r[0]) for r in cur.fetchall()]
            _FB_YEARWEEKS_CACHE["data"] = yws
            _FB_YEARWEEKS_CACHE["timestamp"] = now
            return yws
    except Exception as e:
        logger.exception("Error loading fb_share yearweeks: %s", e)
        return []


def _shift_yearweek(yw, weeks):
    """Shift an ISO yearweek (YYYYWW) back by N weeks. Returns None if invalid."""
    try:
        y, w = divmod(int(yw), 100)
        d = datetime.date.fromisocalendar(y, w, 1) - datetime.timedelta(weeks=weeks)
        iy, iw, _ = d.isocalendar()
        return iy * 100 + iw
    except (ValueError, TypeError):
        return None


def _fb_values(telkomsel, isat3, xl, smartfren):
    """Map raw columns to (tsel, ioh, xls) where XLS = XL + Smartfren."""
    tsel = float(telkomsel or 0)
    ioh = float(isat3 or 0)
    xls = float(xl or 0) + float(smartfren or 0)
    return tsel, ioh, xls


def _avg_nonzero(values):
    """Average of values excluding 0/None (Excel AVERAGEIFS(..., "<>0")). Unrounded."""
    nz = [v for v in values if v]
    return (sum(nz) / len(nz)) if nz else None


def _r2(v):
    return round(v, 2) if v is not None else None


def _delta(cur_v, prev_v):
    if cur_v is None or prev_v is None:
        return None
    return round(cur_v - prev_v, 2)


def _fb_is_zero(tsel, ioh, xls):
    return not tsel and not ioh and not xls


def _fb_status(tsel, ioh, xls, win_lose):
    """DB win_lose has priority (a 0-value city flagged WIN is counted as WIN).
    Fallback when win_lose is empty: '-' for all-zero, else computed."""
    wl = (win_lose or "").strip().upper()
    if wl in ("WIN", "LOSE"):
        return wl
    if _fb_is_zero(tsel, ioh, xls):
        return "-"
    return "WIN" if tsel > max(ioh, xls) else "LOSE"


def _fb_olo(ioh, xls):
    """Strongest competitor (other licensed operator)."""
    return "XLS" if xls > ioh else "IOH"


FB_CITY_MASTER_START_YW = 202401
_FB_CITY_MASTER_CACHE = {"data": None, "timestamp": 0}


def get_cached_fb_city_master():
    """Distinct cities in sow.fb_share since 202401 with their latest branch: [(branch, city), ...]."""
    now = time.time()
    if _FB_CITY_MASTER_CACHE["data"] and (now - _FB_CITY_MASTER_CACHE["timestamp"] < _CACHE_TTL):
        return _FB_CITY_MASTER_CACHE["data"]
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(
                """
                SELECT branch, kabupaten FROM (
                    SELECT DISTINCT ON (kabupaten) kabupaten, branch
                    FROM sow.fb_share
                    WHERE yearweek >= %s AND kabupaten IS NOT NULL AND kabupaten <> ''
                    ORDER BY kabupaten, yearweek DESC
                ) t
                ORDER BY branch, kabupaten
                """,
                (FB_CITY_MASTER_START_YW,)
            )
            data = [(r[0], r[1]) for r in cur.fetchall()]
            _FB_CITY_MASTER_CACHE["data"] = data
            _FB_CITY_MASTER_CACHE["timestamp"] = now
            return data
    except Exception as e:
        logger.exception("Error loading fb_share city master: %s", e)
        return []


@sow.route("/api/sow/fb-share/trend", methods=["POST"])
@csrf.exempt
@login_required
def api_fb_share_trend():
    """FB Share trends: win-city achievement, regional/branch averages (non-zero) and city series."""
    req = request.get_json(silent=True) or {}
    try:
        start_yw = int(req.get("start_yearweek", 202501))
        end_yw = int(req.get("end_yearweek", 202652))
        if start_yw > end_yw:
            start_yw, end_yw = end_yw, start_yw
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid yearweek range"}), 400

    query = """
        SELECT yearweek, region, branch, kabupaten, telkomsel, isat3, xl, smartfren, win_lose
        FROM sow.fb_share
        WHERE yearweek >= %s AND yearweek <= %s
        ORDER BY yearweek ASC, branch ASC, kabupaten ASC
    """
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(query, (start_yw, end_yw))
            rows = cur.fetchall()

        weeks = sorted({int(r[0]) for r in rows})
        w_idx = {w: i for i, w in enumerate(weeks)}
        n = len(weeks)

        regions = sorted({r[1] for r in rows if r[1]})
        master = get_cached_fb_city_master()
        branches = sorted({r[2] for r in rows if r[2]} | {b for b, _ in master if b})

        # Buckets for averaging: bucket[key][provider][week_idx] -> list of values
        def new_bucket():
            return {p: [[] for _ in range(n)] for p in FB_PROVIDERS}

        reg_bucket = new_bucket()
        br_buckets = {b: new_bucket() for b in branches}
        # City list seeded from master (distinct cities since 202401)
        city_map = {
            kab: {"city": kab, "branch": b, "tsel": [None] * n, "ioh": [None] * n, "xls": [None] * n}
            for b, kab in master
        }

        win_cnt = [0] * n
        zero_cnt = [0] * n
        total_cnt = [0] * n

        for r in rows:
            yw, _region, branch, kab = int(r[0]), r[1], r[2], r[3]
            i = w_idx[yw]
            tsel, ioh, xls = _fb_values(r[4], r[5], r[6], r[7])
            status = _fb_status(tsel, ioh, xls, r[8])

            total_cnt[i] += 1
            if _fb_is_zero(tsel, ioh, xls):
                zero_cnt[i] += 1
            # DB status has priority: 0-value city flagged WIN still counts as #win city
            if status == "WIN":
                win_cnt[i] += 1

            for p, v in zip(FB_PROVIDERS, (tsel, ioh, xls)):
                reg_bucket[p][i].append(v)
                if branch in br_buckets:
                    br_buckets[branch][p][i].append(v)

            if kab:
                c = city_map.get(kab)
                if c is None:
                    c = {"city": kab, "branch": branch, "tsel": [None] * n, "ioh": [None] * n, "xls": [None] * n}
                    city_map[kab] = c
                # 0 means no data -> keep as gap (None) in trend lines
                c["tsel"][i] = round(tsel, 2) if tsel else None
                c["ioh"][i] = round(ioh, 2) if ioh else None
                c["xls"][i] = round(xls, 2) if xls else None

        def finalize(bucket):
            return {p: [_r2(_avg_nonzero(vals)) for vals in bucket[p]] for p in FB_PROVIDERS}

        win_pct = [round(win_cnt[i] / total_cnt[i] * 100, 2) if total_cnt[i] else None for i in range(n)]

        cities = sorted(city_map.values(), key=lambda c: ((c["branch"] or ""), c["city"]))

        return jsonify({
            "status": "success",
            "start_yearweek": start_yw,
            "end_yearweek": end_yw,
            "weeks": [str(w) for w in weeks],
            "region_label": " / ".join(regions) if regions else "Regional",
            "branches": branches,
            "achievement": {
                "win": win_cnt,
                "zero": zero_cnt,
                "total": total_cnt,
                "win_pct": win_pct,
            },
            "regional": finalize(reg_bucket),
            "branch_series": {b: finalize(br_buckets[b]) for b in branches},
            "cities": cities,
        })
    except Exception as e:
        logger.exception("Error loading FB share trend: %s", e)
        return jsonify({"status": "error", "message": "Failed to fetch FB share trend"}), 500


@sow.route("/api/sow/fb-share/compare", methods=["POST"])
@csrf.exempt
@login_required
def api_fb_share_compare():
    """FB Share comparison tables for a reference week vs WoW (-1w), MoM (-4w), YoY (-1y)."""
    req = request.get_json(silent=True) or {}
    try:
        ref_yw = int(req.get("yearweek"))
    except (ValueError, TypeError):
        yws = get_cached_fb_yearweeks()
        ref_yw = yws[0] if yws else None
    if not ref_yw:
        return jsonify({"status": "error", "message": "No yearweek available"}), 400

    try:
        threshold = float(req.get("threshold", 95))
    except (ValueError, TypeError):
        threshold = 95.0

    cmp_weeks = {
        "wow": _shift_yearweek(ref_yw, 1),
        "mom": _shift_yearweek(ref_yw, 4),
        "yoy": ref_yw - 100,
    }
    all_weeks = [ref_yw] + [w for w in cmp_weeks.values() if w]

    query = """
        SELECT yearweek, region, branch, kabupaten, telkomsel, isat3, xl, smartfren, win_lose
        FROM sow.fb_share
        WHERE yearweek = ANY(%s)
    """
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(query, (all_weeks,))
            rows = cur.fetchall()

        # data[yw][kab] = dict(...)
        data = {}
        regions = set()
        for r in rows:
            yw = int(r[0])
            tsel, ioh, xls = _fb_values(r[4], r[5], r[6], r[7])
            if r[1]:
                regions.add(r[1])
            data.setdefault(yw, {})[r[3]] = {
                "branch": r[2], "tsel": tsel, "ioh": ioh, "xls": xls, "win_lose": r[8]
            }

        ref_data = data.get(ref_yw, {})
        if not ref_data:
            return jsonify({"status": "error", "message": f"No FB share data for week {ref_yw}"}), 404

        available = {k: (w if w in data else None) for k, w in cmp_weeks.items()}

        # ── Branch / Regional comparison (AVERAGEIFS <> 0) ──
        def group_avg(yw, branch=None):
            d = data.get(yw)
            if not d:
                return {p: None for p in FB_PROVIDERS}
            items = [v for v in d.values() if branch is None or v["branch"] == branch]
            return {p: _avg_nonzero([it[p] for it in items]) for p in FB_PROVIDERS}

        branches = sorted({v["branch"] for v in ref_data.values() if v["branch"]})
        region_label = " / ".join(sorted(regions)) if regions else "Regional"

        branch_rows = []
        for b in branches + [None]:
            cur_avg = group_avg(ref_yw, b)
            row = {
                "name": b if b else region_label,
                "is_regional": b is None,
                "share": {p: _r2(cur_avg[p]) for p in FB_PROVIDERS},
            }
            for k, w in available.items():
                prev = group_avg(w, b) if w else {p: None for p in FB_PROVIDERS}
                row[k] = {p: _delta(cur_avg[p], prev[p]) for p in FB_PROVIDERS}
            branch_rows.append(row)

        # ── City level table (city list = master since 202401 ∪ ref week) ──
        master = get_cached_fb_city_master()
        city_branch = {kab: b for b, kab in master}
        for kab, v in ref_data.items():
            city_branch.setdefault(kab, v["branch"])

        city_rows = []
        for kab, master_branch in city_branch.items():
            v = ref_data.get(kab)
            if v is None:
                # City exists in master list but has no record in the selected week
                row = {
                    "branch": master_branch, "city": kab,
                    "tsel": None, "ioh": None, "xls": None,
                    "status": "N/A", "olo": None, "zero": False, "missing": True,
                }
                for k in available:
                    row[k] = {p: None for p in FB_PROVIDERS}
                city_rows.append(row)
                continue
            status = _fb_status(v["tsel"], v["ioh"], v["xls"], v["win_lose"])
            row = {
                "branch": v["branch"] or master_branch,
                "city": kab,
                "tsel": round(v["tsel"], 2),
                "ioh": round(v["ioh"], 2),
                "xls": round(v["xls"], 2),
                "status": status,
                "olo": _fb_olo(v["ioh"], v["xls"]),
                "zero": _fb_is_zero(v["tsel"], v["ioh"], v["xls"]),
                "missing": False,
            }
            for k, w in available.items():
                prev = data.get(w, {}).get(kab) if w else None
                row[k] = {p: (_delta(v[p], prev[p]) if prev else None) for p in FB_PROVIDERS}
            city_rows.append(row)
        city_rows.sort(key=lambda c: ((c["branch"] or ""), c["city"]))

        # ── Summary ──
        regional = branch_rows[-1]
        reported = [c for c in city_rows if not c["missing"]]
        wins = [c for c in reported if c["status"] == "WIN"]  # includes 0-value cities flagged WIN
        loses = [c for c in reported if c["status"] == "LOSE"]
        zero = [c for c in reported if c["zero"]]
        below = [c for c in reported if c["tsel"] and c["tsel"] < threshold]
        lowest_city = min((c for c in reported if c["tsel"]), key=lambda c: c["tsel"], default=None)
        branch_only = [b for b in branch_rows if not b["is_regional"] and b["share"]["tsel"] is not None]
        best_branch = max(branch_only, key=lambda b: b["share"]["tsel"], default=None)
        low_branch = min(branch_only, key=lambda b: b["share"]["tsel"], default=None)
        r_share = regional["share"]
        olo_max = max([x for x in (r_share["ioh"], r_share["xls"]) if x is not None], default=None)

        summary = {
            "regional_tsel": r_share["tsel"],
            "regional_ioh": r_share["ioh"],
            "regional_xls": r_share["xls"],
            "regional_wow": regional["wow"]["tsel"],
            "regional_mom": regional["mom"]["tsel"],
            "regional_yoy": regional["yoy"]["tsel"],
            "gap_vs_olo": _delta(r_share["tsel"], olo_max),
            "win_city": len(wins),
            "lose_city": len(loses),
            "reported_city": len(reported),
            "master_city": len(city_rows),
            "missing_city": len(city_rows) - len(reported),
            "zero_city": len(zero),
            "win_rate": round(len(wins) / len(reported) * 100, 2) if reported else None,
            "below_threshold": len(below),
            "threshold": threshold,
            "lowest_city": {"city": lowest_city["city"], "branch": lowest_city["branch"], "tsel": lowest_city["tsel"]} if lowest_city else None,
            "best_branch": {"name": best_branch["name"], "tsel": best_branch["share"]["tsel"]} if best_branch else None,
            "low_branch": {"name": low_branch["name"], "tsel": low_branch["share"]["tsel"]} if low_branch else None,
        }

        return jsonify({
            "status": "success",
            "yearweek": ref_yw,
            "compare_weeks": cmp_weeks,
            "compare_available": {k: bool(w) for k, w in available.items()},
            "region_label": region_label,
            "branch_table": branch_rows,
            "city_table": city_rows,
            "summary": summary,
        })
    except Exception as e:
        logger.exception("Error loading FB share comparison: %s", e)
        return jsonify({"status": "error", "message": "Failed to fetch FB share comparison"}), 500



@sow.route("/api/sow/summary-availability", methods=["GET"])
@login_required
def api_sow_summary_availability():
    """Returns comprehensive SOW summary, availability, WoW movement, and insights."""
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            # 1. Targets from sow.sow_target
            cur.execute("""
                SELECT "SOW", "Year", "Q1", "Q2", "Q3", "Q4"
                FROM sow.sow_target;
            """)
            targets = {}
            for r in cur.fetchall():
                k = (r[0] or "").strip().lower()
                if not k:
                    continue
                try:
                    yr = int(r[1])
                except (TypeError, ValueError):
                    continue
                entry = targets.setdefault(k, {"raw_key": r[0], "years": {}})
                entry["years"][yr] = {
                    1: float(r[2]) if r[2] is not None else None,
                    2: float(r[3]) if r[3] is not None else None,
                    3: float(r[4]) if r[4] is not None else None,
                    4: float(r[5]) if r[5] is not None else None,
                }

            # 2. Latest two weeks + their aggregate for all five sources, in ONE
            #    round-trip.
            #
            #    This replaces ten statements: five `SELECT DISTINCT week ...
            #    ORDER BY week DESC LIMIT 2` probes, each followed by a second
            #    query aggregating those weeks. The link to the database costs
            #    ~80ms per round-trip (measured), so ten serialised trips cost
            #    ~0.8s no matter how fast the SQL itself runs. Each UNION branch
            #    below expresses the same "group by week, newest two" as one
            #    statement.
            #
            #    n1/n2/n3 per branch:
            #      RHI      total, GOOD cells, FAIL cells
            #      CEI      total, Good_cell, Bad_cell
            #      Redcov   total_geohash7, "RED OPTIM", unused
            #      RCI      total, rci optimization, unbalanced_p1
            #      ONX      Telkomsel rank-1 wins, Telkomsel row count
            cur.execute("""
                SELECT * FROM (
                    SELECT 'RHI' AS src, weeknum AS wk,
                           count(*)::numeric AS n1,
                           count(*) FILTER (WHERE upper(trim(remark_week)) = 'GOOD')::numeric AS n2,
                           count(*) FILTER (WHERE upper(trim(remark_week)) = 'FAIL')::numeric AS n3
                    FROM sow.rhi_score GROUP BY weeknum ORDER BY weeknum DESC LIMIT 2
                ) t
                UNION ALL
                SELECT * FROM (
                    SELECT 'CEI', weeknum, count(*)::numeric,
                           count(*) FILTER (WHERE remark_cell = 'Good_cell')::numeric,
                           count(*) FILTER (WHERE remark_cell = 'Bad_cell')::numeric
                    FROM sow.cei_score GROUP BY weeknum ORDER BY weeknum DESC LIMIT 2
                ) t
                UNION ALL
                SELECT * FROM (
                    SELECT 'Redcov', yearweek, sum(total_geohash7)::numeric,
                           sum("RED OPTIM")::numeric, 0::numeric
                    FROM sow.red_cov WHERE region = 'MALUKU DAN PAPUA'
                    GROUP BY yearweek ORDER BY yearweek DESC LIMIT 2
                ) t
                UNION ALL
                SELECT * FROM (
                    SELECT 'RCI', week, count(*)::numeric,
                           count(*) FILTER (WHERE grouping_rci = 'optimization')::numeric,
                           count(*) FILTER (WHERE unbalanced_3method = 'unbalanced_p1')::numeric
                    FROM sow.rci_redsector GROUP BY week ORDER BY week DESC LIMIT 2
                ) t
                UNION ALL
                SELECT * FROM (
                    SELECT 'ONX', yearweek,
                           sum(CASE WHEN provider = 'Telkomsel' AND rank = 1 THEN 1 ELSE 0 END)::numeric,
                           count(*) FILTER (WHERE provider = 'Telkomsel')::numeric,
                           0::numeric
                    FROM sow.onx_rank_score
                    WHERE level = 'Region' AND location = 'MALUKU DAN PAPUA'
                    GROUP BY yearweek ORDER BY yearweek DESC LIMIT 2
                ) t
            """)
            wk_rows = {}
            for src, wk, n1, n2, n3 in cur.fetchall():
                wk_rows.setdefault(src, []).append((wk, n1, n2, n3))

            def _latest_two(src):
                rows = wk_rows.get(src) or []
                return (rows[0] if rows else None), (rows[1] if len(rows) > 1 else None)

            def _pct(num, den):
                return round(float(num) * 100.0 / float(den), 2) if den else 0.0

            live = {}

            # RHI
            lw_r, pw_r = _latest_two("RHI")
            rhi_w = [r[0] for r in (wk_rows.get("RHI") or [])]
            if lw_r:
                live["RHI"] = {
                    "lw": lw_r[0], "pw": pw_r[0] if pw_r else None,
                    "lval": _pct(lw_r[2], lw_r[1]),
                    "pval": _pct(pw_r[2], pw_r[1]) if pw_r else None,
                    "total": int(lw_r[1]), "good": int(lw_r[2]), "fail": int(lw_r[3]),
                }

            # CEI
            lw_c, pw_c = _latest_two("CEI")
            cei_w = [r[0] for r in (wk_rows.get("CEI") or [])]
            if lw_c:
                live["CEI"] = {
                    "lw": lw_c[0], "pw": pw_c[0] if pw_c else None,
                    "lval": _pct(lw_c[2], lw_c[1]),
                    "pval": _pct(pw_c[2], pw_c[1]) if pw_c else None,
                    "total": int(lw_c[1]), "good": int(lw_c[2]), "bad": int(lw_c[3]),
                }

            # Redcov (PUMA only)
            lw_d, pw_d = _latest_two("Redcov")
            red_w = [r[0] for r in (wk_rows.get("Redcov") or [])]
            if lw_d:
                live["Redcov"] = {
                    "lw": lw_d[0], "pw": pw_d[0] if pw_d else None,
                    "lval": _pct(lw_d[2], lw_d[1]),
                    "pval": _pct(pw_d[2], pw_d[1]) if pw_d else None,
                    "total": int(lw_d[1]), "red": int(lw_d[2]),
                }

            # RCI & Unbalance share the same week rows
            lw_i, pw_i = _latest_two("RCI")
            rci_w = [r[0] for r in (wk_rows.get("RCI") or [])]
            if lw_i:
                live["RCI"] = {
                    "lw": lw_i[0], "pw": pw_i[0] if pw_i else None,
                    "lval": _pct(lw_i[2], lw_i[1]),
                    "pval": _pct(pw_i[2], pw_i[1]) if pw_i else None,
                    "total": int(lw_i[1]), "optim": int(lw_i[2]),
                }
                live["Unbalance"] = {
                    "lw": lw_i[0], "pw": pw_i[0] if pw_i else None,
                    "lval": _pct(lw_i[3], lw_i[1]),
                    "pval": _pct(pw_i[3], pw_i[1]) if pw_i else None,
                    "total": int(lw_i[1]), "p1": int(lw_i[3]),
                }

            # ONX — n2 counts Telkomsel rows, so a week carrying no Telkomsel
            # data yields None rather than a misleading 0.
            lw_o, pw_o = _latest_two("ONX")
            onx_w = [r[0] for r in (wk_rows.get("ONX") or [])]
            if lw_o:
                live["ONX"] = {
                    "lw": lw_o[0], "pw": pw_o[0] if pw_o else None,
                    "lval": int(lw_o[1]) if lw_o[2] else None,
                    "pval": (int(pw_o[1]) if pw_o[2] else None) if pw_o else None,
                }

            # 3. Breakdown drivers: the five "top 3 by count" lists in ONE
            #    round-trip (previously five separate statements).
            cur.execute("""
                SELECT * FROM (
                    SELECT 'RHI' AS src, kabupaten AS name, count(*)::numeric AS n1
                    FROM sow.rhi_score
                    WHERE weeknum = %s AND upper(trim(remark_week)) = 'FAIL'
                    GROUP BY kabupaten ORDER BY n1 DESC LIMIT 3
                ) t
                UNION ALL
                SELECT * FROM (
                    SELECT 'CEI', kabupaten, count(*)::numeric
                    FROM sow.cei_score
                    WHERE weeknum = %s AND remark_cell = 'Bad_cell'
                    GROUP BY kabupaten ORDER BY 3 DESC LIMIT 3
                ) t
                UNION ALL
                SELECT * FROM (
                    SELECT 'Redcov', kabupaten, sum("RED OPTIM")::numeric
                    FROM sow.red_cov
                    WHERE region = 'MALUKU DAN PAPUA' AND yearweek = %s
                    GROUP BY kabupaten ORDER BY 3 DESC LIMIT 3
                ) t
                UNION ALL
                SELECT * FROM (
                    SELECT 'RCI', kabupaten, count(*)::numeric
                    FROM sow.rci_redsector
                    WHERE week = %s AND grouping_rci = 'optimization'
                    GROUP BY kabupaten ORDER BY 3 DESC LIMIT 3
                ) t
                UNION ALL
                SELECT * FROM (
                    SELECT 'Unbalance', kabupaten, count(*)::numeric
                    FROM sow.rci_redsector
                    WHERE week = %s AND unbalanced_3method = 'unbalanced_p1'
                    GROUP BY kabupaten ORDER BY 3 DESC LIMIT 3
                ) t
            """, (
                rhi_w[0] if rhi_w else None,
                cei_w[0] if cei_w else None,
                red_w[0] if red_w else None,
                rci_w[0] if rci_w else None,
                rci_w[0] if rci_w else None,
            ))
            tops = {}
            for src, name, n1 in cur.fetchall():
                tops.setdefault(src, []).append((name, n1))
            for src in tops:
                # UNION ALL does not guarantee branch order across the append
                # nodes, so impose the ordering the SQL asked for.
                tops[src].sort(key=lambda x: (-float(x[1]), x[0] or ""))

            rhi_top_str = ", ".join(
                f"{n.title()} ({int(v):,} cells)" for n, v in tops.get("RHI", []))
            cei_top_str = ", ".join(
                f"{n.title()} ({int(v):,} cells)" for n, v in tops.get("CEI", []))
            red_top_str = ", ".join(
                f"{n.title()} ({int(v):,} grids)" for n, v in tops.get("Redcov", []))
            rci_top_str = ", ".join(
                f"{n.title()} ({int(v)} sectors)" for n, v in tops.get("RCI", []))
            unb_top_str = ", ".join(
                f"{n.title()} ({int(v)} sectors)" for n, v in tops.get("Unbalance", []))

            # 4. ONX metrics where the rank is not 1
            onx_trailing_str = ""
            if onx_w:
                cur.execute("""
                    SELECT metric, rank, "mean or percentage"
                    FROM sow.onx_rank_score
                    WHERE level = 'Region' AND location = 'MALUKU DAN PAPUA' AND provider = 'Telkomsel'
                      AND yearweek = %s AND rank > 1
                    ORDER BY metric;
                """, (onx_w[0],))
                onx_trailing_str = ", ".join(
                    [f"{r[0].replace('_', ' ').title()} (Rank {r[1]}, {r[2]})" for r in cur.fetchall()])

        # 3. Assemble the 6 KPIs. Every number comes from the database: when a
        #    metric has no data, or sow.sow_target carries no usable target for
        #    the latest week's year/quarter, the field is emitted as null so the
        #    UI renders "—" instead of a plausible-looking invented figure.
        def _quarter_of(yearweek):
            """ISO yearweek -> (year, quarter 1-4); (None, None) if unusable."""
            try:
                yw = int(yearweek)
            except (TypeError, ValueError):
                return None, None
            return yw // 100, min(4, max(1, ((yw % 100) - 1) // 13 + 1))

        def _target_for(sow_key, latest_week, is_count=False):
            """Quarter target for the latest data week's year/quarter, else None.

            sow.sow_target holds one row per (SOW, Year) with Q1..Q4 columns, so
            the quarter is resolved from the data week rather than assumed.
            Fractional targets (0.9355) are normalised to percent (93.55).
            """
            entry = targets.get((sow_key or "").lower())
            if not entry or not entry["years"]:
                return None
            year, quarter = _quarter_of(latest_week)
            year_map = entry["years"]
            if year is None:
                year = max(year_map)
            elif year not in year_map:
                year = min(year_map, key=lambda y: (abs(y - year), y))
            raw = (year_map.get(year) or {}).get(quarter)
            if raw is None:
                return None
            if is_count:
                return int(round(float(raw)))
            v = float(raw)
            return round(v * 100, 2) if 0 < v < 1.0 else round(v, 2)

        def _wow(latest, prev):
            if latest is None or prev is None:
                return None
            return round(latest - prev, 2)

        def _movement(wow, higher_better, deadband=0.0, force=None):
            """improved / degraded / maintained / None when WoW is unknown."""
            if wow is None:
                return None
            if force is not None:
                return force
            if abs(wow) <= deadband:
                return "maintained"
            good = (wow > 0) if higher_better else (wow < 0)
            return "improved" if good else "degraded"

        def _fmt(v, is_count=False):
            if v is None:
                return "n/a"
            return f"{int(round(v)):,}" if is_count else f"{v:.2f}%"

        def _pack(mid, name, category, icon, color, unit, is_count, sow_key, live_key,
                  higher_better, link, link_title, deadband=0.0, force_movement=None,
                  drivers="", drivers_label="Top contributors", detail=None):
            """Build one metric dict using only values that actually exist."""
            l = live.get(live_key) or {}
            latest = l.get("lval")
            prev = l.get("pval")
            tgt = _target_for(sow_key, l.get("lw"), is_count)
            wow = _wow(latest, prev)
            gap = None if (latest is None or tgt is None) else round(latest - tgt, 2)
            if latest is None or tgt is None:
                ach = None
            else:
                ach = (latest >= tgt) if higher_better else (latest <= tgt)
            status = "NO DATA" if ach is None else ("ACH" if ach else "NY ACH")

            if latest is None:
                insight = f"No {name} data available in the database."
            else:
                parts = []
                if wow is None:
                    parts.append("WoW n/a (no previous week)")
                else:
                    parts.append(f"{wow:+.2f}{'' if is_count else ' pp'} WoW "
                                 f"({_fmt(latest, is_count)} vs {_fmt(prev, is_count)})")
                if tgt is None:
                    parts.append(f"no target in sow.sow_target for week {l.get('lw')}")
                else:
                    parts.append(f"Target {_fmt(tgt, is_count)} — {status}")
                if detail:
                    parts.append(detail)
                if drivers:
                    parts.append(f"{drivers_label}: {drivers}")
                insight = ". ".join(parts) + "."

            year, qtr = _quarter_of(l.get("lw"))
            q_label = f"Q{qtr}" if qtr else None

            return {
                "id": mid, "name": name, "category": category, "icon": icon,
                "color": color, "unit": unit, "is_count": is_count,
                "target": tgt, "target_quarter": q_label,
                "prev_val": prev, "latest_val": latest,
                "prev_week": l.get("pw"), "latest_week": l.get("lw"),
                "wow": wow, "gap": gap, "ach": ach, "status": status,
                "higher_better": higher_better,
                "movement": _movement(wow, higher_better, deadband, force_movement),
                "link": link, "link_title": link_title, "insight": insight,
            }

        rhi_l = live.get("RHI") or {}
        cei_l = live.get("CEI") or {}
        red_l = live.get("Redcov") or {}
        onx_l = live.get("ONX") or {}
        unb_l = live.get("Unbalance") or {}
        rci_l = live.get("RCI") or {}

        metrics = [
            # (1) RHI — higher is better
            _pack("RHI", "RHI", "Radio Health & Quality", "fas fa-heartbeat", "#10b981",
                  "%", False, "rhi", "RHI", True, "/okr/rhi", "RHI Dashboard",
                  deadband=0.1, drivers=rhi_top_str, drivers_label="Top fail contributors",
                  detail=(f"{rhi_l.get('total', 0):,} cells monitored, "
                          f"{rhi_l.get('fail', 0):,} fail" if rhi_l else None)),

            # (2) CEI — higher is better
            _pack("CEI", "CEI", "Customer Experience", "fas fa-smile", "#06b6d4",
                  "%", False, "cei", "CEI", True, "/okr/cei", "CEI Dashboard",
                  drivers=cei_top_str,
                  detail=(f"{cei_l.get('bad', 0):,} bad cells out of "
                          f"{cei_l.get('total', 0):,} evaluated" if cei_l else None)),

            # (3) Red Coverage Optim — lower is better
            _pack("Redcov", "Red Coverage Optim", "Bad Spot Optimization",
                  "fas fa-satellite-dish", "#f59e0b", "%", False, "redcov", "Redcov",
                  False, "/okr/redcov", "Redcov Dashboard",
                  drivers=red_top_str,
                  detail=(f"{red_l.get('red', 0):,} RED OPTIM grids across "
                          f"{red_l.get('total', 0):,} geohash7 grids in Region Maluku & Papua"
                          if red_l else None)),

            # (4) ONX Mobile — win count (movement tracked as maintained)
            _pack("ONX", "ONX Mobile", "Benchmark / Crowdsource", "fas fa-trophy", "#3b82f6",
                  "wins", True, "onx", "ONX", True, "/okr/crowdsource?tab=onx",
                  "Crowdsource (ONX)", force_movement="maintained",
                  drivers=onx_trailing_str, drivers_label="Categories not at rank 1"),

            # (5) Unbalance Sector — lower is better
            _pack("Unbalance", "Unbalance Sector", "PRB Balance & Capacity",
                  "fas fa-balance-scale", "#8b5cf6", "%", False, "unbalance", "Unbalance",
                  False, "/okr/ran_capacity?mode=unbalance", "RAN Capacity (Unbalance)",
                  drivers=unb_top_str,
                  detail=(f"{unb_l.get('p1', 0):,} Unbalanced P1 sectors out of "
                          f"{unb_l.get('total', 0):,} sectors" if unb_l else None)),

            # (6) Direct Optim (RCI) — lower is better
            _pack("RCI", "Direct Optim (RCI)", "Interference & Optimization",
                  "fas fa-sliders-h", "#f43f5e", "%", False, "rci", "RCI", False,
                  "/okr/ran_capacity?mode=rci", "RAN Capacity (RCI)",
                  drivers=rci_top_str,
                  detail=(f"{rci_l.get('optim', 0)} optimization sectors out of "
                          f"{rci_l.get('total', 0):,} sectors" if rci_l else None)),
        ]

        all_lws = [l.get("lw") for l in live.values() if l.get("lw")]
        overall_latest_week = max(all_lws) if all_lws else None
        all_pws = [l.get("pw") for l in live.values() if l.get("pw")]
        overall_prev_week = max(all_pws) if all_pws else None

        active_year, active_quarter = _quarter_of(overall_latest_week)

        return jsonify({
            "status": "success",
            "metrics": metrics,
            "latest_week": overall_latest_week,
            "active_quarter": active_quarter,
            "active_quarter_label": f"Q{active_quarter}" if active_quarter else None,
            "prev_week": overall_prev_week,
            "total_metrics": len(metrics),
            "ach_count": sum(1 for m in metrics if m["ach"] is True),
            "ny_ach_count": sum(1 for m in metrics if m["ach"] is False),
            "no_data_count": sum(1 for m in metrics if m["ach"] is None),
        })

    except Exception as e:
        logger.exception("Error loading OKR summary availability: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


SUMMARY_SOW_TITLES = {
    "redcov": "Red Coverage",
    "unbalance": "Unbalance PRB",
    "rci": "RCI",
    "4g_good_thp": "4G Good Throughput",
    "5g_good_thp": "5G Good Throughput",
    "Payload": "Payload",
    "ONX": "ONX",
    "Ookla": "Ookla",
    "RHI": "RHI",
    "CEI": "CEI",
}

# SOW metrics whose quarterly targets are counts (not percentages)
SUMMARY_COUNT_METRICS = {"ONX", "Ookla"}


def _summary_title(key):
    return SUMMARY_SOW_TITLES.get(key, key)


def get_cached_summary_years():
    """Distinct years available in sow.sow_target, descending."""
    now = time.time()
    if _SUMMARY_YEARS_CACHE["data"] is not None and (now - _SUMMARY_YEARS_CACHE["timestamp"] < _CACHE_TTL):
        return _SUMMARY_YEARS_CACHE["data"]
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(
                'SELECT DISTINCT "Year" FROM sow.sow_target WHERE "Year" IS NOT NULL ORDER BY "Year" DESC'
            )
            years = [int(r[0]) for r in cur.fetchall()]
            _SUMMARY_YEARS_CACHE["data"] = years
            _SUMMARY_YEARS_CACHE["timestamp"] = now
            return years
    except Exception as e:
        logger.exception("Error loading sow_target years: %s", e)
        return []


@sow.route("/sow/summary")
@sow.route("/okr/summary")
@login_required
def summary_page():
    """Render the OKR Summary page: quarterly targets per OKR metric for a chosen year."""
    years = get_cached_summary_years()
    default_year = years[0] if years else 2026

    return render_template(
        "sow_summary.html",
        username=session.get("username", "User"),
        years=years,
        default_year=default_year,
    )


@sow.route("/api/sow/targets", methods=["GET"])
@login_required
def api_sow_targets():
    """Return sow.sow_target rows (Baseline + Q1..Q4) filtered by year and optional Region."""
    try:
        year = int(request.args.get("year", 0))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid year"}), 400

    if not year:
        years = get_cached_summary_years()
        year = years[0] if years else None
    if not year:
        return jsonify({"status": "error", "message": "No year available in sow.sow_target"}), 400

    region = (request.args.get("region") or "").strip() or None

    query = """
        SELECT "SOW", "Baseline", "Q1", "Q2", "Q3", "Q4"
        FROM sow.sow_target
        WHERE "Year" = %s
    """
    params = [year]
    if region:
        query += ' AND "Region" = %s'
        params.append(region)

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

        items = []
        for r in rows:
            key = r[0]
            vals = [r[i] for i in range(1, 6)]
            is_count = key in SUMMARY_COUNT_METRICS

            def _fmt_target(v):
                if v is None:
                    return "—"
                num = float(v)
                if is_count:
                    return str(int(round(num)))
                if abs(num) <= 1.0 and num != 0:
                    return f"{num * 100:.2f}%"
                return f"{num:.2f}%"

            items.append({
                "sow": key,
                "title": _summary_title(key),
                "is_count": is_count,
                "baseline": vals[0],
                "q1": vals[1],
                "q2": vals[2],
                "q3": vals[3],
                "q4": vals[4],
                "formatted": {
                    "baseline": _fmt_target(vals[0]),
                    "q1": _fmt_target(vals[1]),
                    "q2": _fmt_target(vals[2]),
                    "q3": _fmt_target(vals[3]),
                    "q4": _fmt_target(vals[4]),
                }
            })
        items.sort(key=lambda x: x["title"].lower())

        return jsonify({
            "status": "success",
            "year": year,
            "region": region,
            "count": len(items),
            "targets": items,
        })
    except Exception as e:
        logger.exception("Error loading sow targets: %s", e)
        return jsonify({"status": "error", "message": "Failed to fetch SOW targets"}), 500


@sow.route("/sow/crowdsource")
@sow.route("/okr/crowdsource")
@login_required
def crowdsource_page():
    """Render the Crowdsource OKR page with multiple tabs."""
    yearweeks = get_cached_yearweeks()
    levels = ["Nation", "Area", "Region", "Kabupaten"]
    providers = ["Telkomsel", "Indosat", "XL", "Smartfren", "3"]
    kab_regions = get_cached_kab_regions()

    default_level = "Region"
    locations = get_cached_locations(default_level)
    default_location = "MALUKU DAN PAPUA" if "MALUKU DAN PAPUA" in locations else (locations[0] if locations else "")
    default_provider = "Telkomsel"

    default_start_yw = 202601 if 202601 in yearweeks else (yearweeks[-1] if yearweeks else 202601)
    default_end_yw = yearweeks[0] if yearweeks else 202638

    # FB Share tab defaults (independent week list from sow.fb_share)
    fb_yearweeks = get_cached_fb_yearweeks()
    fb_default_end_yw = fb_yearweeks[0] if fb_yearweeks else default_end_yw
    fb_default_start_yw = _shift_yearweek(fb_default_end_yw, 52) if fb_yearweeks else default_start_yw
    if fb_yearweeks and fb_default_start_yw not in fb_yearweeks:
        older = [y for y in fb_yearweeks if y <= (fb_default_start_yw or 0)]
        fb_default_start_yw = older[0] if older else fb_yearweeks[-1]

    return render_template(
        "sow_crowdsource.html",
        username=session.get("username", "User"),
        levels=levels,
        default_level=default_level,
        locations=locations,
        default_location=default_location,
        providers=providers,
        default_provider=default_provider,
        yearweeks=yearweeks,
        default_start_yw=default_start_yw,
        default_end_yw=default_end_yw,
        kab_regions=kab_regions,
        ordered_metrics=ORDERED_16_METRICS,
        metric_titles=METRIC_TITLES,
        fb_yearweeks=fb_yearweeks,
        fb_default_start_yw=fb_default_start_yw,
        fb_default_end_yw=fb_default_end_yw
    )


@sow.route("/api/sow/regions", methods=["GET"])
@login_required
def api_sow_regions():
    """Return distinct Region list for level='Kabupaten'."""
    regions = get_cached_kab_regions()
    return jsonify({"regions": regions})


@sow.route("/api/sow/locations", methods=["GET"])
@login_required
def api_sow_locations():
    """Return distinct locations for the given level and optional region."""
    level = request.args.get("level", "Region")
    region = request.args.get("region")
    locs = get_cached_locations(level, region)
    return jsonify({"level": level, "region": region, "locations": locs})


@sow.route("/api/sow/chart-data", methods=["POST"])
@csrf.exempt
@login_required
def api_sow_chart_data():
    """Return stacked bar chart data (#win and #lose) with quarterly custom targets supporting multi-year."""
    req = request.get_json(silent=True) or {}
    level = req.get("level", "Region")
    location = req.get("location", "MALUKU DAN PAPUA")
    provider = req.get("provider", "Telkomsel")

    try:
        start_yw = int(req.get("start_yearweek", 202601))
        end_yw = int(req.get("end_yearweek", 202638))
        if start_yw > end_yw:
            start_yw, end_yw = end_yw, start_yw
    except (ValueError, TypeError):
        start_yw = 202601
        end_yw = 202638

    # Quarterly targets from sow.sow_target (SOW = 'ONX'); fallback to 14.
    # Keyed by year so multi-year trends resolve the correct quarter.
    targets_by_year = {}
    target_q1 = 14
    target_q2 = 14
    target_q3 = 14
    target_q4 = 14
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute('SELECT "Year", "Q1", "Q2", "Q3", "Q4" FROM sow.sow_target WHERE "SOW" = %s', ("ONX",))
            for yr_, *qs in cur.fetchall():
                if yr_ is None:
                    continue
                vals = [int(q) if q is not None else 14 for q in qs]
                targets_by_year[int(yr_)] = dict(zip((1, 2, 3, 4), vals))
            if targets_by_year:
                latest = targets_by_year[max(targets_by_year)]
                target_q1, target_q2, target_q3, target_q4 = (latest[1], latest[2], latest[3], latest[4])
    except Exception as e:
        logger.exception("Error loading ONX targets from sow_target: %s", e)

    fallback_map = {1: target_q1, 2: target_q2, 3: target_q3, 4: target_q4}

    def _target_for(year, quarter):
        """Resolve ONX quarterly target for a year, falling back to the nearest
        year present in sow.sow_target (the table only carries certain years)."""
        year_map = targets_by_year.get(year)
        if not year_map and targets_by_year:
            nearest = min(targets_by_year, key=lambda y: (abs(y - year), y))
            year_map = targets_by_year[nearest]
        if year_map:
            return year_map.get(quarter, 14)
        return fallback_map.get(quarter, 14)


    query = """
        SELECT yearweek,
               SUM(CASE WHEN rank = 1 THEN 1 ELSE 0 END)::integer AS win_count,
               (16 - SUM(CASE WHEN rank = 1 THEN 1 ELSE 0 END))::integer AS lose_count
        FROM sow.onx_rank_score
        WHERE level = %s
          AND location = %s
          AND provider = %s
          AND yearweek >= %s
          AND yearweek <= %s
        GROUP BY yearweek
        ORDER BY yearweek ASC
    """

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(query, (level, location, provider, start_yw, end_yw))
            rows = cur.fetchall()

        labels = []
        win_data = []
        lose_data = []
        target_series = []

        target_met_count = 0
        total_wins = 0

        best_week = None
        max_win = -1
        lowest_week = None
        min_win = 999

        for r in rows:
            yw = int(r[0])
            w = int(r[1])
            l = int(r[2])
            if l < 0:
                l = 0

            # Determine target for this week's year and quarter (from sow.sow_target)
            yr = yw // 100
            week_num = yw % 100
            q = min(4, max(1, (week_num - 1) // 13 + 1))

            curr_target = _target_for(yr, q)

            labels.append(str(yw))
            win_data.append(w)
            lose_data.append(l)
            target_series.append(curr_target)

            total_wins += w
            if w >= curr_target:
                target_met_count += 1

            if w > max_win:
                max_win = w
                best_week = {"yearweek": yw, "win": w, "lose": l}
            if w < min_win:
                min_win = w
                lowest_week = {"yearweek": yw, "win": w, "lose": l}

        total_weeks = len(rows)
        latest_yw = rows[-1][0] if rows else None
        latest_win = rows[-1][1] if rows else 0
        latest_lose = rows[-1][2] if rows else 0
        latest_target = target_series[-1] if target_series else target_q1
        latest_rate = round((latest_win / 16.0) * 100, 1) if latest_win else 0.0

        latest_q = "Q2"
        if latest_yw:
            lyw = int(latest_yw)
            l_wk = lyw % 100
            latest_q = f"Q{min(4, max(1, (l_wk - 1) // 13 + 1))}"

        avg_win = round(total_wins / total_weeks, 1) if total_weeks > 0 else 0.0
        avg_rate = round((avg_win / 16.0) * 100, 1) if total_weeks > 0 else 0.0
        target_met_pct = round((target_met_count / total_weeks) * 100, 1) if total_weeks > 0 else 0.0

        prev_yw = None
        lose_metrics = []
        win_metrics = []
        moved_to_win = []
        moved_to_lose = []
        maintained_win = []
        maintained_lose = []

        if rows:
            latest_yw = rows[-1][0]
            prev_yw = rows[-2][0] if len(rows) >= 2 else None
            target_yws = [latest_yw]

            with db_query(get_postgres_connection) as (conn_m, cur_m):
                if not prev_yw:
                    cur_m.execute("""
                        SELECT MAX(yearweek) FROM sow.onx_rank_score
                        WHERE level = %s AND location = %s AND provider = %s AND yearweek < %s
                    """, (level, location, provider, latest_yw))
                    p_row = cur_m.fetchone()
                    if p_row and p_row[0]:
                        prev_yw = p_row[0]

                if prev_yw:
                    target_yws.append(prev_yw)

                cur_m.execute("""
                    SELECT yearweek, metric, rank, "mean or percentage"
                    FROM sow.onx_rank_score
                    WHERE level = %s AND location = %s AND provider = %s
                      AND yearweek = ANY(%s)
                    ORDER BY yearweek DESC, metric;
                """, (level, location, provider, target_yws))
                m_rows = cur_m.fetchall()

            curr_m = {}
            prev_m = {}
            for r in m_rows:
                yw_val = int(r[0])
                metric_name = r[1]
                title = METRIC_TITLES.get(metric_name, metric_name.replace("_", " ").title())
                rank_val = r[2]
                score_val = round(r[3], 2) if r[3] is not None else None
                entry = {"metric": metric_name, "title": title, "rank": rank_val, "score": score_val}
                if yw_val == int(latest_yw):
                    curr_m[metric_name] = entry
                elif prev_yw and yw_val == int(prev_yw):
                    prev_m[metric_name] = entry

            for m_key, entry in curr_m.items():
                if entry["rank"] == 1:
                    win_metrics.append(entry)
                    if prev_m:
                        if m_key in prev_m and prev_m[m_key]["rank"] and prev_m[m_key]["rank"] > 1:
                            moved_to_win.append(entry)
                        elif m_key in prev_m and prev_m[m_key]["rank"] == 1:
                            maintained_win.append(entry)
                elif entry["rank"] and entry["rank"] > 1:
                    lose_metrics.append(entry)
                    if prev_m:
                        if m_key in prev_m and prev_m[m_key]["rank"] == 1:
                            moved_to_lose.append(entry)
                        elif m_key in prev_m and prev_m[m_key]["rank"] > 1:
                            maintained_lose.append(entry)

        summary = {
            "total_weeks": total_weeks,
            "latest_yearweek": latest_yw,
            "latest_quarter": latest_q,
            "latest_win": latest_win,
            "latest_lose": latest_lose,
            "latest_target": latest_target,
            "latest_rate": latest_rate,
            "target_q1": target_q1,
            "target_q2": target_q2,
            "target_q3": target_q3,
            "target_q4": target_q4,
            "target_met_count": target_met_count,
            "target_met_pct": target_met_pct,
            "avg_win": avg_win,
            "avg_rate": avg_rate,
            "best_week": best_week,
            "lowest_week": lowest_week,
            "prev_yearweek": prev_yw,
            "lose_metrics": lose_metrics,
            "win_metrics": win_metrics,
            "moved_to_win": moved_to_win,
            "moved_to_lose": moved_to_lose,
            "maintained_win_count": len(maintained_win),
            "maintained_lose": maintained_lose,
        }

        return jsonify({
            "status": "success",
            "level": level,
            "location": location,
            "provider": provider,
            "start_yearweek": start_yw,
            "end_yearweek": end_yw,
            "labels": labels,
            "win": win_data,
            "lose": lose_data,
            "targets": target_series,
            "summary": summary
        })

    except Exception as e:
        logger.exception("Error executing chart query for SOW Crowdsource: %s", e)
        return jsonify({"status": "error", "message": "Failed to fetch chart data"}), 500


@sow.route("/api/sow/trend-metrics", methods=["POST"])
@csrf.exempt
@login_required
def api_sow_trend_metrics():
    """Return trend line scores and status rank winners for 16 metrics across multiple providers."""
    req = request.get_json(silent=True) or {}
    level = req.get("level", "Region")
    location = req.get("location", "MALUKU DAN PAPUA")
    providers = req.get("providers", ["Indosat", "Telkomsel", "XL"])
    if not isinstance(providers, list) or len(providers) == 0:
        providers = ["Indosat", "Telkomsel", "XL"]

    try:
        start_yw = int(req.get("start_yearweek", 202602))
        end_yw = int(req.get("end_yearweek", 202638))
        if start_yw > end_yw:
            start_yw, end_yw = end_yw, start_yw
    except (ValueError, TypeError):
        start_yw = 202602
        end_yw = 202638

    # Query 1: Metric data for the requested providers
    data_query = """
        SELECT yearweek, metric, provider, "mean or percentage" AS score, rank
        FROM sow.onx_rank_score
        WHERE level = %s
          AND location = %s
          AND provider = ANY(%s)
          AND yearweek >= %s
          AND yearweek <= %s
        ORDER BY yearweek ASC, metric ASC, provider ASC
    """

    # Query 2: Winners (rank = 1) across ALL providers in that location
    winners_query = """
        SELECT yearweek, metric, provider
        FROM sow.onx_rank_score
        WHERE level = %s
          AND location = %s
          AND rank = 1
          AND yearweek >= %s
          AND yearweek <= %s
        ORDER BY yearweek ASC, metric ASC, provider ASC
    """

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(data_query, (level, location, providers, start_yw, end_yw))
            rows = cur.fetchall()

            cur.execute(winners_query, (level, location, start_yw, end_yw))
            winner_rows = cur.fetchall()

        # Build list of weeks
        weeks_set = set()
        # Structure: metrics_data[metric][provider][yearweek] = {score, rank}
        metrics_data = {m: {p: {} for p in providers} for m in ORDERED_16_METRICS}

        for r in rows:
            yw = int(r[0])
            m = r[1]
            p = r[2]
            score = round(r[3], 2) if r[3] is not None else None
            rnk = r[4]

            weeks_set.add(yw)
            if m in metrics_data and p in metrics_data[m]:
                metrics_data[m][p][yw] = {"score": score, "rank": rnk}

        weeks_sorted = sorted(list(weeks_set))
        weeks_labels = [str(w) for w in weeks_sorted]

        # Winners structure: winners[metric][yearweek] = [providers with rank 1]
        winners_map = {m: {str(w): [] for w in weeks_sorted} for m in ORDERED_16_METRICS}
        for wr in winner_rows:
            yw_str = str(wr[0])
            m = wr[1]
            p = wr[2]
            if m in winners_map and yw_str in winners_map[m]:
                winners_map[m][yw_str].append(p)

        # Format metrics series aligned with weeks_sorted
        formatted_metrics = {}
        for m in ORDERED_16_METRICS:
            formatted_metrics[m] = {
                "title": METRIC_TITLES.get(m, m.replace("_", " ").title()),
                "providers": {}
            }
            for p in providers:
                score_series = []
                rank_series = []
                for w in weeks_sorted:
                    item = metrics_data[m][p].get(w)
                    if item:
                        score_series.append(item["score"])
                        rank_series.append(item["rank"])
                    else:
                        score_series.append(None)
                        rank_series.append(None)
                formatted_metrics[m]["providers"][p] = {
                    "scores": score_series,
                    "ranks": rank_series
                }

        return jsonify({
            "status": "success",
            "level": level,
            "location": location,
            "providers": providers,
            "weeks": weeks_labels,
            "ordered_metrics": ORDERED_16_METRICS,
            "metrics": formatted_metrics,
            "winners": winners_map
        })

    except Exception as e:
        logger.exception("Error loading trend metrics: %s", e)
        return jsonify({"status": "error", "message": "Failed to fetch trend metrics"}), 500


@sow.route("/api/sow/metrics-detail", methods=["GET"])
@login_required
def api_sow_metrics_detail():
    """Return the 16 individual metrics and their rank/status for a single week."""
    level = request.args.get("level", "Region")
    location = request.args.get("location", "MALUKU DAN PAPUA")
    provider = request.args.get("provider", "Telkomsel")
    try:
        yearweek = int(request.args.get("yearweek", 202638))
    except (ValueError, TypeError):
        yearweek = 202638

    query = """
        SELECT metric,
               rank,
               "mean or percentage" AS score,
               lci,
               uci,
               CASE 
                   WHEN rank IS NULL THEN 'no rank'
                   WHEN rank = 1 THEN 'win'
                   ELSE 'lose'
               END AS status,
               snapshot_date,
               week_date
        FROM sow.onx_rank_score
        WHERE level = %s
          AND location = %s
          AND provider = %s
          AND yearweek = %s
        ORDER BY 
          CASE WHEN rank = 1 THEN 1 WHEN rank IS NOT NULL THEN 2 ELSE 3 END,
          metric ASC
    """

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(query, (level, location, provider, yearweek))
            rows = cur.fetchall()

        metrics_list = []
        win_count = 0
        lose_count = 0
        no_rank_count = 0

        for r in rows:
            raw_metric = r[0]
            rank_val = r[1]
            score_val = round(r[2], 2) if r[2] is not None else None
            lci_val = round(r[3], 2) if r[3] is not None else None
            uci_val = round(r[4], 2) if r[4] is not None else None
            status_val = r[5]

            if status_val == "win":
                win_count += 1
            elif status_val == "lose":
                lose_count += 1
            else:
                no_rank_count += 1

            metrics_list.append({
                "metric": raw_metric,
                "metric_title": METRIC_TITLES.get(raw_metric, raw_metric.replace("_", " ").title()),
                "rank": rank_val,
                "score": score_val,
                "lci": lci_val,
                "uci": uci_val,
                "status": status_val
            })

        prev_yearweek = None
        moved_to_win = []
        moved_to_lose = []
        maintained_win = []
        maintained_lose = []
        lose_metrics = []

        try:
            with db_query(get_postgres_connection) as (conn_pw, cur_pw):
                cur_pw.execute("""
                    SELECT MAX(yearweek) FROM sow.onx_rank_score
                    WHERE level = %s AND location = %s AND provider = %s AND yearweek < %s
                """, (level, location, provider, yearweek))
                p_row = cur_pw.fetchone()
                if p_row and p_row[0]:
                    prev_yearweek = p_row[0]
                    cur_pw.execute("""
                        SELECT metric, rank, "mean or percentage"
                        FROM sow.onx_rank_score
                        WHERE level = %s AND location = %s AND provider = %s AND yearweek = %s
                    """, (level, location, provider, prev_yearweek))
                    p_rows = cur_pw.fetchall()
                else:
                    p_rows = []

            prev_map = {r[0]: {"rank": r[1], "score": round(r[2], 2) if r[2] is not None else None} for r in p_rows}
            for m in metrics_list:
                m_key = m["metric"]
                p_entry = prev_map.get(m_key)
                if m["status"] == "win":
                    if p_entry:
                        if p_entry["rank"] and p_entry["rank"] > 1:
                            moved_to_win.append(m)
                        elif p_entry["rank"] == 1:
                            maintained_win.append(m)
                elif m["status"] == "lose":
                    lose_metrics.append(m)
                    if p_entry:
                        if p_entry["rank"] == 1:
                            moved_to_lose.append(m)
                        elif p_entry["rank"] and p_entry["rank"] > 1:
                            maintained_lose.append(m)
        except Exception as e_wow:
            logger.warning("Could not calculate WoW metrics detail: %s", e_wow)

        yw_num = int(yearweek)
        wk_num = yw_num % 100
        quarter_label = f"Q{min(4, max(1, (wk_num - 1) // 13 + 1))}"

        return jsonify({
            "status": "success",
            "yearweek": yearweek,
            "quarter_label": quarter_label,
            "level": level,
            "location": location,
            "provider": provider,
            "total_metrics": len(metrics_list),
            "win_count": win_count,
            "lose_count": lose_count,
            "no_rank_count": no_rank_count,
            "prev_yearweek": prev_yearweek,
            "moved_to_win": moved_to_win,
            "moved_to_lose": moved_to_lose,
            "maintained_win_count": len(maintained_win),
            "maintained_lose": maintained_lose,
            "lose_metrics": lose_metrics,
            "metrics": metrics_list
        })
    except Exception as e:
        logger.exception("Error fetching metrics detail: %s", e)
        return jsonify({"status": "error", "message": "Failed to fetch metrics detail"}), 500


@sow.route("/api/sow/kabupaten-comparison", methods=["POST"])
@csrf.exempt
@login_required
def api_sow_kabupaten_comparison():
    """Return performance comparison table of all Kabupatens for a chosen Region and Yearweek."""
    req = request.get_json(silent=True) or {}
    region = req.get("region", "MALUKU DAN PAPUA")
    provider = req.get("provider", "Telkomsel")
    try:
        yearweek = int(req.get("yearweek", 202638))
    except (ValueError, TypeError):
        yearweek = 202638

    yw_val = int(yearweek)
    yr = yw_val // 100
    wk = yw_val % 100
    q = min(4, max(1, (wk - 1) // 13 + 1))
    quarter_label = f"Q{q}"

    target = 14
    try:
        with db_query(get_postgres_connection) as (conn_t, cur_t):
            cur_t.execute("""
                SELECT "Q1", "Q2", "Q3", "Q4" 
                FROM sow.sow_target 
                WHERE "SOW" = 'ONX' AND "Year" = %s
            """, (yr,))
            t_row = cur_t.fetchone()
            if not t_row:
                cur_t.execute("""
                    SELECT "Q1", "Q2", "Q3", "Q4" 
                    FROM sow.sow_target 
                    WHERE "SOW" = 'ONX' 
                    ORDER BY "Year" DESC LIMIT 1
                """)
                t_row = cur_t.fetchone()
            if t_row:
                q_map = {"Q1": int(t_row[0]), "Q2": int(t_row[1]), "Q3": int(t_row[2]), "Q4": int(t_row[3])}
                target = q_map.get(quarter_label, 14)
    except Exception as e_tgt:
        logger.warning("Could not resolve dynamic quarterly target for ONX comparison: %s", e_tgt)

    query = """
        SELECT location,
               SUM(CASE WHEN rank = 1 THEN 1 ELSE 0 END)::integer AS win_count,
               (16 - SUM(CASE WHEN rank = 1 THEN 1 ELSE 0 END))::integer AS lose_count,
               ROUND((SUM(CASE WHEN rank = 1 THEN 1 ELSE 0 END)::numeric / 16.0) * 100, 1) AS win_rate
        FROM sow.onx_rank_score
        WHERE level = 'Kabupaten'
          AND provider = %s
          AND yearweek = %s
          AND "Region" = %s
        GROUP BY location
        ORDER BY win_count DESC, location ASC;
    """

    prev_query = """
        SELECT location,
               SUM(CASE WHEN rank = 1 THEN 1 ELSE 0 END)::integer AS win_count
        FROM sow.onx_rank_score
        WHERE level = 'Kabupaten'
          AND provider = %s
          AND yearweek = %s
          AND "Region" = %s
        GROUP BY location;
    """

    try:
        prev_yearweek = _shift_yearweek(yearweek, 1)
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(query, (provider, yearweek, region))
            rows = cur.fetchall()

            prev_map = {}
            if prev_yearweek:
                cur.execute(prev_query, (provider, prev_yearweek, region))
                for pr in cur.fetchall():
                    prev_map[pr[0]] = pr[1]

        kab_list = []
        for r in rows:
            loc = r[0]
            win = r[1]
            lose = r[2]
            rate = float(r[3])
            prev_win = prev_map.get(loc)
            wow = (win - prev_win) if prev_win is not None else None
            kab_list.append({
                "location": loc,
                "win": win,
                "lose": lose,
                "rate": rate,
                "prev_win": prev_win,
                "wow": wow,
                "target_met": (win >= target)
            })

        total = len(kab_list)
        achieved_count = sum(1 for k in kab_list if k["target_met"])
        breaching_count = total - achieved_count
        achieved_pct = round((achieved_count / total) * 100, 1) if total else 0.0
        breaching_pct = round((breaching_count / total) * 100, 1) if total else 0.0

        total_wins = sum(k["win"] for k in kab_list)
        avg_win = round(total_wins / total, 1) if total else 0.0
        avg_rate = round((avg_win / 16.0) * 100, 1) if total else 0.0
        gap_to_target = round(avg_win - target, 1)

        top_performer = {"location": kab_list[0]["location"], "win": kab_list[0]["win"], "rate": kab_list[0]["rate"]} if kab_list else None
        lowest_sorted = sorted(kab_list, key=lambda x: (x["win"], x["rate"]))
        lowest_performer = {"location": lowest_sorted[0]["location"], "win": lowest_sorted[0]["win"], "rate": lowest_sorted[0]["rate"]} if lowest_sorted else None

        improved_count = sum(1 for k in kab_list if k["wow"] is not None and k["wow"] > 0)
        declined_count = sum(1 for k in kab_list if k["wow"] is not None and k["wow"] < 0)
        maintained_count = sum(1 for k in kab_list if k["wow"] is not None and k["wow"] == 0)

        summary = {
            "target": target,
            "quarter_label": quarter_label,
            "total_kabupaten": total,
            "achieved_count": achieved_count,
            "achieved_pct": achieved_pct,
            "breaching_count": breaching_count,
            "breaching_pct": breaching_pct,
            "avg_win": avg_win,
            "avg_rate": avg_rate,
            "gap_to_target": gap_to_target,
            "top_performer": top_performer,
            "lowest_performer": lowest_performer,
            "improved_count": improved_count,
            "declined_count": declined_count,
            "maintained_count": maintained_count
        }

        return jsonify({
            "status": "success",
            "region": region,
            "provider": provider,
            "yearweek": yearweek,
            "prev_yearweek": prev_yearweek,
            "target": target,
            "quarter_label": quarter_label,
            "summary": summary,
            "total_kabupaten": len(kab_list),
            "kabupatens": kab_list
        })
    except Exception as e:
        logger.exception("Error fetching Kabupaten comparison: %s", e)
        return jsonify({"status": "error", "message": "Failed to fetch Kabupaten comparison"}), 500


@sow.route("/api/sow/sample-template", methods=["GET"])
@login_required
def api_sow_sample_template():
    """Download sample CSV or XLSX template for editing and importing into sow.onx_rank_score."""
    file_format = request.args.get("format", "xlsx").lower()

    fieldnames = [
        "Region", "level", "location", "provider", "yearweek", "metric",
        "rank", "mean or percentage", "lci", "uci", "snapshot_date", "week_date"
    ]
    sample_rows = []
    for m in ORDERED_16_METRICS:
        sample_rows.append([
            "MALUKU DAN PAPUA", "Region", "MALUKU DAN PAPUA", "Telkomsel",
            202639, m, 1, 50.0, 48.5, 51.5,
            "2026-09-28 00:00:00", "2026-09-28 00:00:00"
        ])

    if file_format == "csv":
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(fieldnames)
        writer.writerows(sample_rows)
        output = make_response(csv_buffer.getvalue())
        output.headers["Content-Disposition"] = "attachment; filename=OKR_ONX_Import_Sample.csv"
        output.headers["Content-type"] = "text/csv; charset=utf-8"
        return output
    else:
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "onx_rank_score"
            ws.append(fieldnames)
            for row in sample_rows:
                ws.append(row)

            excel_buffer = io.BytesIO()
            wb.save(excel_buffer)
            excel_buffer.seek(0)
            return send_file(
                excel_buffer,
                download_name="OKR_ONX_Import_Sample.xlsx",
                as_attachment=True,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            logger.exception("Error generating Excel template: %s", e)
            return jsonify({"status": "error", "message": "Failed to generate Excel template"}), 500


@sow.route("/api/sow/import/progress/<job_id>", methods=["GET"])
@login_required
def api_sow_import_progress(job_id):
    with _ONX_IMPORT_JOBS_LOCK:
        job = _ONX_IMPORT_JOBS.get(job_id)
        if job is None:
            return jsonify({"status": "error", "message": "Job not found"}), 404
        return jsonify(job)


@sow.route("/api/sow/fb-import/progress/<job_id>", methods=["GET"])
@login_required
def api_sow_fb_import_progress(job_id):
    with _FB_IMPORT_JOBS_LOCK:
        job = _FB_IMPORT_JOBS.get(job_id)
        if job is None:
            return jsonify({"status": "error", "message": "Job not found"}), 404
        return jsonify(job)


def _bg_onx_import(job_id, tmp_path, filename):
    try:
        with _ONX_IMPORT_JOBS_LOCK:
            _ONX_IMPORT_JOBS[job_id] = {"status": "processing", "pct": 15, "message": "Parsing file...", "stage": "parse"}

        raw_dicts = []
        if filename.endswith(".csv"):
            with open(tmp_path, "r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f)
                raw_dicts = list(reader)
        else:
            import openpyxl
            wb = openpyxl.load_workbook(tmp_path, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if rows and len(rows) >= 2:
                headers = [str(c).strip() if c is not None else "" for c in rows[0]]
                for r in rows[1:]:
                    if any(v is not None for v in r):
                        row_dict = {headers[i]: r[i] for i in range(min(len(headers), len(r)))}
                        raw_dicts.append(row_dict)
            wb.close()

        if not raw_dicts:
            with _ONX_IMPORT_JOBS_LOCK:
                _ONX_IMPORT_JOBS[job_id] = {"status": "error", "message": "No data rows found in uploaded file"}
            return

        with _ONX_IMPORT_JOBS_LOCK:
            _ONX_IMPORT_JOBS[job_id] = {"status": "processing", "pct": 35, "message": f"Validating {len(raw_dicts):,} rows...", "stage": "validate", "total_rows": len(raw_dicts)}

        cleaned_rows = [{str(k).strip(): v for k, v in r.items() if k is not None} for r in raw_dicts]
        first_row = cleaned_rows[0]
        required_cols = ["level", "location", "provider", "yearweek", "metric"]
        missing = [c for c in required_cols if c not in first_row]
        if missing:
            with _ONX_IMPORT_JOBS_LOCK:
                _ONX_IMPORT_JOBS[job_id] = {"status": "error", "message": f"Missing required columns: {', '.join(missing)}"}
            return

        score_col = None
        for cand in ["mean or percentage", "score", "value", "mean_or_percentage"]:
            if cand in first_row:
                score_col = cand
                break
        if not score_col:
            with _ONX_IMPORT_JOBS_LOCK:
                _ONX_IMPORT_JOBS[job_id] = {"status": "error", "message": "Missing 'mean or percentage' score column"}
            return

        records = []
        for row in cleaned_rows:
            region = str(row.get("Region") or "").strip()
            if not region or region in ("None", "nan"):
                region = "-"
            lvl = str(row.get("level") or "").strip()
            loc = str(row.get("location") or "").strip()
            prv = str(row.get("provider") or "").strip()
            try:
                yw = int(float(str(row.get("yearweek")).strip()))
            except (ValueError, TypeError):
                continue
            metric = str(row.get("metric") or "").strip()
            rank_val = None
            raw_rank = row.get("rank")
            if raw_rank is not None and str(raw_rank).strip() not in ("", "None", "nan"):
                try:
                    rank_val = int(float(str(raw_rank).strip()))
                except (ValueError, TypeError):
                    rank_val = None
            score_val = None
            raw_score = row.get(score_col)
            if raw_score is not None and str(raw_score).strip() not in ("", "None", "nan"):
                try:
                    score_val = float(str(raw_score).strip())
                except (ValueError, TypeError):
                    score_val = None
            lci_val = None
            raw_lci = row.get("lci")
            if raw_lci is not None and str(raw_lci).strip() not in ("", "None", "nan"):
                try:
                    lci_val = float(str(raw_lci).strip())
                except (ValueError, TypeError):
                    lci_val = None
            uci_val = None
            raw_uci = row.get("uci")
            if raw_uci is not None and str(raw_uci).strip() not in ("", "None", "nan"):
                try:
                    uci_val = float(str(raw_uci).strip())
                except (ValueError, TypeError):
                    uci_val = None
            snap_val = str(row.get("snapshot_date") or "").strip() or None
            week_date_val = str(row.get("week_date") or "").strip() or None
            records.append((
                region, lvl, loc, prv, yw, metric,
                rank_val, score_val, lci_val, uci_val,
                snap_val, week_date_val
            ))

        if not records:
            with _ONX_IMPORT_JOBS_LOCK:
                _ONX_IMPORT_JOBS[job_id] = {"status": "error", "message": "No valid data rows found in file"}
            return

        with _ONX_IMPORT_JOBS_LOCK:
            _ONX_IMPORT_JOBS[job_id] = {
                "status": "processing", "pct": 50,
                "message": f"Prepared {len(records):,} records. Inserting into database...",
                "stage": "insert", "total_rows": len(records), "processed": 0
            }

        batch_size = 250
        upsert_query = """
            INSERT INTO sow.onx_rank_score (
                "Region", level, location, provider, yearweek, metric,
                rank, "mean or percentage", lci, uci, snapshot_date, week_date
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP), COALESCE(%s, CURRENT_TIMESTAMP)
            )
            ON CONFLICT (yearweek, metric, level, location, provider)
            DO UPDATE SET
                rank = EXCLUDED.rank,
                "mean or percentage" = EXCLUDED."mean or percentage",
                lci = COALESCE(EXCLUDED.lci, sow.onx_rank_score.lci),
                uci = COALESCE(EXCLUDED.uci, sow.onx_rank_score.uci),
                "Region" = COALESCE(EXCLUDED."Region", sow.onx_rank_score."Region"),
                snapshot_date = COALESCE(EXCLUDED.snapshot_date, sow.onx_rank_score.snapshot_date, CURRENT_TIMESTAMP),
                week_date = COALESCE(EXCLUDED.week_date, sow.onx_rank_score.week_date, CURRENT_TIMESTAMP)
        """
        with db_query(get_postgres_connection) as (conn, cur):
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                psycopg2.extras.execute_batch(cur, upsert_query, batch, page_size=len(batch))
                conn.commit()
                done = min(i + len(batch), len(records))
                pct = 50 + int(48 * (done / max(len(records), 1)))
                with _ONX_IMPORT_JOBS_LOCK:
                    _ONX_IMPORT_JOBS[job_id] = {
                        "status": "processing", "pct": pct,
                        "message": f"Upserting records... {done:,} / {len(records):,}",
                        "stage": "insert", "total_rows": len(records), "processed": done
                    }

        clear_sow_caches()
        with _ONX_IMPORT_JOBS_LOCK:
            _ONX_IMPORT_JOBS[job_id] = {
                "status": "success", "pct": 100,
                "message": f"Successfully imported and updated {len(records):,} benchmark records.",
                "rows_processed": len(records), "total_rows": len(records)
            }
    except Exception as e:
        logger.exception("Background ONX import failed: %s", e)
        with _ONX_IMPORT_JOBS_LOCK:
            _ONX_IMPORT_JOBS[job_id] = {"status": "error", "message": f"Database error during import: {str(e)}"}
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _bg_fb_import(job_id, tmp_path, filename):
    try:
        with _FB_IMPORT_JOBS_LOCK:
            _FB_IMPORT_JOBS[job_id] = {"status": "processing", "pct": 15, "message": "Parsing file...", "stage": "parse"}

        raw_dicts = []
        if filename.endswith(".csv"):
            with open(tmp_path, "r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f)
                raw_dicts = list(reader)
        else:
            import openpyxl
            wb = openpyxl.load_workbook(tmp_path, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if rows and len(rows) >= 2:
                headers = [str(c).strip() if c is not None else "" for c in rows[0]]
                for r in rows[1:]:
                    if any(v is not None for v in r):
                        row_dict = {headers[i]: r[i] for i in range(min(len(headers), len(r)))}
                        raw_dicts.append(row_dict)
            wb.close()

        if not raw_dicts:
            with _FB_IMPORT_JOBS_LOCK:
                _FB_IMPORT_JOBS[job_id] = {"status": "error", "message": "No data rows found in uploaded file"}
            return

        with _FB_IMPORT_JOBS_LOCK:
            _FB_IMPORT_JOBS[job_id] = {"status": "processing", "pct": 35, "message": f"Validating {len(raw_dicts):,} rows...", "stage": "validate", "total_rows": len(raw_dicts)}

        cleaned_rows = [{str(k).strip(): v for k, v in r.items() if k is not None} for r in raw_dicts]
        first_row = cleaned_rows[0]
        required_cols = ["yearweek", "branch", "kabupaten"]
        missing = [c for c in required_cols if c not in first_row]
        if missing:
            with _FB_IMPORT_JOBS_LOCK:
                _FB_IMPORT_JOBS[job_id] = {"status": "error", "message": f"Missing required columns: {', '.join(missing)}"}
            return

        def _num(v):
            if v is None or str(v).strip() in ("", "None", "nan"):
                return None
            try:
                return float(str(v).strip().replace(",", "."))
            except (ValueError, TypeError):
                return None

        records = []
        for row in cleaned_rows:
            try:
                yw = int(float(str(row.get("yearweek")).strip()))
            except (ValueError, TypeError):
                continue
            branch = str(row.get("branch") or "").strip()
            kabupaten = str(row.get("kabupaten") or "").strip()
            if not branch or not kabupaten:
                continue
            region = str(row.get("region") or "").strip() or None
            archetype = str(row.get("archetype") or "").strip() or None
            win_lose = str(row.get("win_lose") or "").strip() or None
            records.append((
                yw, region, branch, kabupaten, archetype,
                _num(row.get("telkomsel")), _num(row.get("isat3")),
                _num(row.get("xl")), _num(row.get("smartfren")),
                _num(row.get("gap")), _num(row.get("wow")), _num(row.get("mom")),
                _num(row.get("wow_cc")), _num(row.get("mom_cc")), win_lose,
            ))

        if not records:
            with _FB_IMPORT_JOBS_LOCK:
                _FB_IMPORT_JOBS[job_id] = {"status": "error", "message": "No valid data rows found in uploaded file"}
            return

        with _FB_IMPORT_JOBS_LOCK:
            _FB_IMPORT_JOBS[job_id] = {
                "status": "processing", "pct": 50,
                "message": f"Prepared {len(records):,} records. Inserting into database...",
                "stage": "insert", "total_rows": len(records), "processed": 0
            }

        upsert_query = """
            INSERT INTO sow.fb_share (
                yearweek, region, branch, kabupaten, archetype,
                telkomsel, isat3, xl, smartfren,
                gap, wow, mom, wow_cc, mom_cc, win_lose
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (yearweek, branch, kabupaten)
            DO UPDATE SET
                region = COALESCE(EXCLUDED.region, sow.fb_share.region),
                archetype = COALESCE(EXCLUDED.archetype, sow.fb_share.archetype),
                telkomsel = EXCLUDED.telkomsel,
                isat3 = EXCLUDED.isat3,
                xl = EXCLUDED.xl,
                smartfren = EXCLUDED.smartfren,
                gap = EXCLUDED.gap,
                wow = EXCLUDED.wow,
                mom = EXCLUDED.mom,
                wow_cc = EXCLUDED.wow_cc,
                mom_cc = EXCLUDED.mom_cc,
                win_lose = COALESCE(EXCLUDED.win_lose, sow.fb_share.win_lose)
        """
        batch_size = 250
        with db_query(get_postgres_connection) as (conn, cur):
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                psycopg2.extras.execute_batch(cur, upsert_query, batch, page_size=len(batch))
                conn.commit()
                done = min(i + len(batch), len(records))
                pct = 50 + int(48 * (done / max(len(records), 1)))
                with _FB_IMPORT_JOBS_LOCK:
                    _FB_IMPORT_JOBS[job_id] = {
                        "status": "processing", "pct": pct,
                        "message": f"Upserting records... {done:,} / {len(records):,}",
                        "stage": "insert", "total_rows": len(records), "processed": done
                    }

        clear_sow_caches()
        with _FB_IMPORT_JOBS_LOCK:
            _FB_IMPORT_JOBS[job_id] = {
                "status": "success", "pct": 100,
                "message": f"Successfully imported and updated {len(records):,} FB Share records.",
                "rows_processed": len(records), "total_rows": len(records)
            }
    except Exception as e:
        logger.exception("Background FB import failed: %s", e)
        with _FB_IMPORT_JOBS_LOCK:
            _FB_IMPORT_JOBS[job_id] = {"status": "error", "message": f"Database error during import: {str(e)}"}
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@sow.route("/api/sow/import", methods=["POST"])
@csrf.exempt
@login_required
def api_sow_import():
    """Import and upsert records into sow.onx_rank_score from uploaded CSV or Excel file."""
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    uploaded_file = request.files["file"]
    if not uploaded_file.filename:
        return jsonify({"status": "error", "message": "Empty file name"}), 400

    filename = uploaded_file.filename.lower()
    if not filename.endswith((".csv", ".xlsx", ".xls")):
        return jsonify({"status": "error", "message": "Only CSV and Excel (.xlsx, .xls) files are supported"}), 400

    is_async = request.args.get("async") == "1" or request.headers.get("X-Async-Import") == "1"
    if is_async:
        job_id = uuid.uuid4().hex
        fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(filename)[1])
        with os.fdopen(fd, "wb") as f:
            uploaded_file.seek(0)
            f.write(uploaded_file.read())
        with _ONX_IMPORT_JOBS_LOCK:
            _ONX_IMPORT_JOBS[job_id] = {
                "status": "processing", "pct": 5,
                "message": "File received. Queued for processing...", "stage": "queue"
            }
        threading.Thread(target=_bg_onx_import, args=(job_id, tmp_path, filename), daemon=True).start()
        return jsonify({"status": "queued", "job_id": job_id}), 202
    raw_dicts = []

    try:
        if filename.endswith(".csv"):
            file_bytes = uploaded_file.read()
            text = file_bytes.decode("utf-8-sig", errors="replace")
            stream = io.StringIO(text)
            reader = csv.DictReader(stream)
            raw_dicts = list(reader)
        elif filename.endswith((".xlsx", ".xls")):
            import openpyxl
            wb = openpyxl.load_workbook(uploaded_file.stream, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows or len(rows) < 2:
                return jsonify({"status": "error", "message": "Uploaded Excel sheet is empty"}), 400
            headers = [str(c).strip() if c is not None else "" for c in rows[0]]
            for r in rows[1:]:
                if any(v is not None for v in r):
                    row_dict = {headers[i]: r[i] for i in range(min(len(headers), len(r)))}
                    raw_dicts.append(row_dict)
        else:
            return jsonify({"status": "error", "message": "Only CSV and Excel (.xlsx, .xls) files are supported"}), 400
    except Exception as e:
        logger.exception("Failed to parse uploaded file: %s", e)
        return jsonify({"status": "error", "message": f"File parsing failed: {str(e)}"}), 400

    if not raw_dicts:
        return jsonify({"status": "error", "message": "No data rows found in uploaded file"}), 400

    # Clean headers in row dictionaries
    cleaned_rows = []
    for r in raw_dicts:
        cleaned_rows.append({str(k).strip(): v for k, v in r.items() if k is not None})

    first_row = cleaned_rows[0]
    required_cols = ["level", "location", "provider", "yearweek", "metric"]
    missing = [c for c in required_cols if c not in first_row]
    if missing:
        return jsonify({
            "status": "error",
            "message": f"Missing required columns in file: {', '.join(missing)}"
        }), 400

    # Detect score column
    score_col = None
    for cand in ["mean or percentage", "score", "value", "mean_or_percentage"]:
        if cand in first_row:
            score_col = cand
            break

    if not score_col:
        return jsonify({
            "status": "error",
            "message": "Missing 'mean or percentage' score column in uploaded file"
        }), 400

    upsert_query = """
        INSERT INTO sow.onx_rank_score (
            "Region", level, location, provider, yearweek, metric,
            rank, "mean or percentage", lci, uci, snapshot_date, week_date
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP), COALESCE(%s, CURRENT_TIMESTAMP)
        )
        ON CONFLICT (yearweek, metric, level, location, provider)
        DO UPDATE SET
            rank = EXCLUDED.rank,
            "mean or percentage" = EXCLUDED."mean or percentage",
            lci = COALESCE(EXCLUDED.lci, sow.onx_rank_score.lci),
            uci = COALESCE(EXCLUDED.uci, sow.onx_rank_score.uci),
            "Region" = COALESCE(EXCLUDED."Region", sow.onx_rank_score."Region"),
            snapshot_date = COALESCE(EXCLUDED.snapshot_date, sow.onx_rank_score.snapshot_date, CURRENT_TIMESTAMP),
            week_date = COALESCE(EXCLUDED.week_date, sow.onx_rank_score.week_date, CURRENT_TIMESTAMP)
    """

    records = []
    for row in cleaned_rows:
        region = str(row.get("Region") or "").strip()
        if not region or region in ("None", "nan"):
            region = "-"

        lvl = str(row.get("level") or "").strip()
        loc = str(row.get("location") or "").strip()
        prv = str(row.get("provider") or "").strip()

        try:
            yw = int(float(str(row.get("yearweek")).strip()))
        except (ValueError, TypeError):
            continue

        metric = str(row.get("metric") or "").strip()

        # Rank
        rank_val = None
        raw_rank = row.get("rank")
        if raw_rank is not None and str(raw_rank).strip() not in ("", "None", "nan"):
            try:
                rank_val = int(float(str(raw_rank).strip()))
            except (ValueError, TypeError):
                rank_val = None

        # Score
        score_val = None
        raw_score = row.get(score_col)
        if raw_score is not None and str(raw_score).strip() not in ("", "None", "nan"):
            try:
                score_val = float(str(raw_score).strip())
            except (ValueError, TypeError):
                score_val = None

        # LCI & UCI
        lci_val = None
        raw_lci = row.get("lci")
        if raw_lci is not None and str(raw_lci).strip() not in ("", "None", "nan"):
            try:
                lci_val = float(str(raw_lci).strip())
            except (ValueError, TypeError):
                lci_val = None

        uci_val = None
        raw_uci = row.get("uci")
        if raw_uci is not None and str(raw_uci).strip() not in ("", "None", "nan"):
            try:
                uci_val = float(str(raw_uci).strip())
            except (ValueError, TypeError):
                uci_val = None

        # snapshot_date & week_date
        snap_val = None
        raw_snap = row.get("snapshot_date")
        if raw_snap is not None and str(raw_snap).strip() not in ("", "None", "nan"):
            snap_val = str(raw_snap).strip()

        week_date_val = None
        raw_wk = row.get("week_date")
        if raw_wk is not None and str(raw_wk).strip() not in ("", "None", "nan"):
            week_date_val = str(raw_wk).strip()

        records.append((
            region, lvl, loc, prv, yw, metric,
            rank_val, score_val, lci_val, uci_val,
            snap_val, week_date_val
        ))

    if not records:
        return jsonify({"status": "error", "message": "No valid data rows found in uploaded file"}), 400

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            psycopg2.extras.execute_batch(cur, upsert_query, records, page_size=200)
            conn.commit()

        clear_sow_caches()

        return jsonify({
            "status": "success",
            "rows_processed": len(records),
            "message": f"Successfully imported and updated {len(records)} benchmark records."
        })
    except Exception as e:
        logger.exception("Database error while upserting SOW records: %s", e)
        return jsonify({"status": "error", "message": f"Database error during import: {str(e)}"}), 500


# ══════════════════════════════════════════════════════════════════════
# FB SHARE import / sample template (sow.fb_share)
# ══════════════════════════════════════════════════════════════════════
FB_SHARE_FIELDS = [
    "yearweek", "region", "branch", "kabupaten", "archetype",
    "telkomsel", "isat3", "xl", "smartfren",
    "gap", "wow", "mom", "wow_cc", "mom_cc", "win_lose",
]


def _fb_share_sample_row(region="MALUKU DAN PAPUA", branch="AMBON", city="KOTA AMBON", yw=202639):
    return [
        yw, region, branch, city, "Super Fortress",
        91.5, 6.4, 0.8, 0.2,
        85.1, 0.3, 1.2, 0.1, 0.9, "WIN",
    ]


@sow.route("/api/sow/fb-sample-template", methods=["GET"])
@login_required
def api_sow_fb_sample_template():
    """Download sample CSV or XLSX template for importing into sow.fb_share."""
    file_format = request.args.get("format", "xlsx").lower()
    fieldnames = FB_SHARE_FIELDS
    sample_rows = [
        _fb_share_sample_row("MALUKU DAN PAPUA", "AMBON", "KOTA AMBON", 202639),
        _fb_share_sample_row("MALUKU DAN PAPUA", "JAYAPURA", "KOTA JAYAPURA", 202639),
        _fb_share_sample_row("MALUKU DAN PAPUA", "SORONG", "KOTA SORONG", 202639),
    ]

    if file_format == "csv":
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(fieldnames)
        writer.writerows(sample_rows)
        output = make_response(csv_buffer.getvalue())
        output.headers["Content-Disposition"] = "attachment; filename=OKR_FBShare_Import_Sample.csv"
        output.headers["Content-type"] = "text/csv; charset=utf-8"
        return output
    else:
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "fb_share"
            ws.append(fieldnames)
            for row in sample_rows:
                ws.append(row)
            excel_buffer = io.BytesIO()
            wb.save(excel_buffer)
            excel_buffer.seek(0)
            return send_file(
                excel_buffer,
                download_name="OKR_FBShare_Import_Sample.xlsx",
                as_attachment=True,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            logger.exception("Error generating FB Share Excel template: %s", e)
            return jsonify({"status": "error", "message": "Failed to generate Excel template"}), 500


@sow.route("/api/sow/fb-import", methods=["POST"])
@csrf.exempt
@login_required
def api_sow_fb_import():
    """Import and upsert records into sow.fb_share from uploaded CSV or Excel file."""
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    uploaded_file = request.files["file"]
    if not uploaded_file.filename:
        return jsonify({"status": "error", "message": "Empty file name"}), 400

    filename = uploaded_file.filename.lower()
    if not filename.endswith((".csv", ".xlsx", ".xls")):
        return jsonify({"status": "error", "message": "Only CSV and Excel (.xlsx, .xls) files are supported"}), 400

    is_async = request.args.get("async") == "1" or request.headers.get("X-Async-Import") == "1"
    if is_async:
        job_id = uuid.uuid4().hex
        fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(filename)[1])
        with os.fdopen(fd, "wb") as f:
            uploaded_file.seek(0)
            f.write(uploaded_file.read())
        with _FB_IMPORT_JOBS_LOCK:
            _FB_IMPORT_JOBS[job_id] = {
                "status": "processing", "pct": 5,
                "message": "File received. Queued for processing...", "stage": "queue"
            }
        threading.Thread(target=_bg_fb_import, args=(job_id, tmp_path, filename), daemon=True).start()
        return jsonify({"status": "queued", "job_id": job_id}), 202

    raw_dicts = []

    try:
        if filename.endswith(".csv"):
            file_bytes = uploaded_file.read()
            text = file_bytes.decode("utf-8-sig", errors="replace")
            stream = io.StringIO(text)
            reader = csv.DictReader(stream)
            raw_dicts = list(reader)
        elif filename.endswith((".xlsx", ".xls")):
            import openpyxl
            wb = openpyxl.load_workbook(uploaded_file.stream, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows or len(rows) < 2:
                return jsonify({"status": "error", "message": "Uploaded Excel sheet is empty"}), 400
            headers = [str(c).strip() if c is not None else "" for c in rows[0]]
            for r in rows[1:]:
                if any(v is not None for v in r):
                    row_dict = {headers[i]: r[i] for i in range(min(len(headers), len(r)))}
                    raw_dicts.append(row_dict)
        else:
            return jsonify({"status": "error", "message": "Only CSV and Excel (.xlsx, .xls) files are supported"}), 400
    except Exception as e:
        logger.exception("Failed to parse uploaded file: %s", e)
        return jsonify({"status": "error", "message": f"File parsing failed: {str(e)}"}), 400

    if not raw_dicts:
        return jsonify({"status": "error", "message": "No data rows found in uploaded file"}), 400

    cleaned_rows = [{str(k).strip(): v for k, v in r.items() if k is not None} for r in raw_dicts]

    first_row = cleaned_rows[0]
    required_cols = ["yearweek", "branch", "kabupaten"]
    missing = [c for c in required_cols if c not in first_row]
    if missing:
        return jsonify({"status": "error", "message": f"Missing required columns in file: {', '.join(missing)}"}), 400

    def _num(v):
        if v is None or str(v).strip() in ("", "None", "nan"):
            return None
        try:
            return float(str(v).strip().replace(",", "."))
        except (ValueError, TypeError):
            return None

    records = []
    for row in cleaned_rows:
        try:
            yw = int(float(str(row.get("yearweek")).strip()))
        except (ValueError, TypeError):
            continue
        branch = str(row.get("branch") or "").strip()
        kabupaten = str(row.get("kabupaten") or "").strip()
        if not branch or not kabupaten:
            continue
        region = str(row.get("region") or "").strip() or None
        archetype = str(row.get("archetype") or "").strip() or None
        win_lose = str(row.get("win_lose") or "").strip() or None
        records.append((
            yw, region, branch, kabupaten, archetype,
            _num(row.get("telkomsel")), _num(row.get("isat3")),
            _num(row.get("xl")), _num(row.get("smartfren")),
            _num(row.get("gap")), _num(row.get("wow")), _num(row.get("mom")),
            _num(row.get("wow_cc")), _num(row.get("mom_cc")), win_lose,
        ))

    if not records:
        return jsonify({"status": "error", "message": "No valid data rows found in uploaded file"}), 400

    upsert_query = """
        INSERT INTO sow.fb_share (
            yearweek, region, branch, kabupaten, archetype,
            telkomsel, isat3, xl, smartfren,
            gap, wow, mom, wow_cc, mom_cc, win_lose
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (yearweek, branch, kabupaten)
        DO UPDATE SET
            region = COALESCE(EXCLUDED.region, sow.fb_share.region),
            archetype = COALESCE(EXCLUDED.archetype, sow.fb_share.archetype),
            telkomsel = EXCLUDED.telkomsel,
            isat3 = EXCLUDED.isat3,
            xl = EXCLUDED.xl,
            smartfren = EXCLUDED.smartfren,
            gap = EXCLUDED.gap,
            wow = EXCLUDED.wow,
            mom = EXCLUDED.mom,
            wow_cc = EXCLUDED.wow_cc,
            mom_cc = EXCLUDED.mom_cc,
            win_lose = COALESCE(EXCLUDED.win_lose, sow.fb_share.win_lose)
    """

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            psycopg2.extras.execute_batch(cur, upsert_query, records, page_size=200)
            conn.commit()

        clear_sow_caches()

        return jsonify({
            "status": "success",
            "rows_processed": len(records),
            "message": f"Successfully imported and updated {len(records)} FB Share records."
        })
    except Exception as e:
            logger.exception("Database error while upserting FB Share records: %s", e)
            return jsonify({"status": "error", "message": f"Database error during import: {str(e)}"}), 500

# ══════════════════════════════════════════════════════════════════════
# CSV Export endpoints — faithful dumps of the source tables
#
# Every export mirrors its table exactly: ALL columns, in the table's own
# order, with the database's own column names as the CSV header. The header
# is read from the live cursor description rather than a hardcoded list, so
# an export can never drift from the schema again.
#
#   cei             -> sow.cei_score      (weeknum)
#   rhi             -> sow.rhi_score      (weeknum)
#   redcov          -> sow.red_cov        (yearweek)
#   ran_capacity    -> sow.rci_redsector  (week)
#   crowdsource_onx -> sow.onx_rank_score (yearweek)
#   crowdsource_fb  -> sow.fb_share       (yearweek)
# ══════════════════════════════════════════════════════════════════════

EXPORT_TABLES = {
    "cei":             ("cei_score",      "weeknum"),
    "rhi":             ("rhi_score",      "weeknum"),
    "redcov":          ("red_cov",        "yearweek"),
    "ran_capacity":    ("rci_redsector",  "week"),
    "crowdsource_onx": ("onx_rank_score", "yearweek"),
    "crowdsource_fb":  ("fb_share",       "yearweek"),
}


def _parse_export_week_range():
    """Return (start_yw, end_yw) for the requested period, ordered ascending.

    Accepts 'week' (single ISO YYYYWW) or 'start_week' + 'end_week'.
    Raises ValueError when the period is missing or not numeric.
    """
    week = request.args.get("week")
    start_week = request.args.get("start_week")
    end_week = request.args.get("end_week")

    if week:
        a = b = int(week)
    elif start_week and end_week:
        a, b = int(start_week), int(end_week)
    else:
        raise ValueError("Must provide 'week' or 'start_week'/'end_week'")

    return (b, a) if a > b else (a, b)


def _table_columns(table):
    """Column names of sow.<table> in the database's own ordinal order."""
    with db_query(get_postgres_connection) as (conn, cur):
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'sow' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [r[0] for r in cur.fetchall()]


def _stream_table_csv(table, week_col, start_yw, end_yw, filename):
    """Stream an exact CSV mirror of sow.<table> over the given week range.

    A server-side (named) cursor is used so a wide table (sow.rhi_score carries
    164 columns) is never materialised in memory. Both the SELECT list and the
    CSV header come from the live catalog, so the names and their order always
    equal the database's own and can never drift from it.
    """
    cols = _table_columns(table)
    if not cols:
        raise ValueError(f"Table sow.{table} does not exist")

    col_sql = ", ".join('"' + c.replace('"', '""') + '"' for c in cols)
    select_sql = (
        f"SELECT {col_sql} FROM sow.\"{table}\" "
        f"WHERE \"{week_col}\" >= %s AND \"{week_col}\" <= %s "
        f"ORDER BY \"{week_col}\""
    )

    def generate():
        conn = get_postgres_connection()
        try:
            cur = conn.cursor(name=f"exp_{table}")
            cur.itersize = 5000
            cur.execute(select_sql, (start_yw, end_yw))

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(cols)  # exact DB column names, in DB order
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

            for row in cur:
                writer.writerow(row)
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)

            cur.close()
        finally:
            try:
                conn.close()  # pooled wrapper: returns the connection, rolls back
            except Exception:
                pass

    return Response(
        stream_with_context(generate()),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _table_csv_export(key, label):
    """Shared body for the OKR table export endpoints."""
    table, week_col = EXPORT_TABLES[key]

    if not (request.args.get("week")
            or (request.args.get("start_week") and request.args.get("end_week"))):
        return jsonify({"status": "error", "message": "Must provide 'week' or 'start_week'/'end_week'"}), 400

    try:
        start_yw, end_yw = _parse_export_week_range()
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid yearweek format"}), 400

    try:
        return _stream_table_csv(
            table, week_col, start_yw, end_yw,
            f"{label}_Export_{start_yw}-{end_yw}.csv",
        )
    except Exception as e:
        logger.exception("Error generating %s CSV export: %s", label, e)
        return jsonify({"status": "error", "message": "Failed to generate CSV export"}), 500


@sow.route('/api/sow/cei-csv-export', methods=['GET'])
@login_required
def api_sow_cei_csv_export():
    """Export sow.cei_score — every column, filtered by week or week range."""
    return _table_csv_export("cei", "CEI_OKR")


@sow.route("/api/sow/rhi-csv-export", methods=["GET"])
@login_required
def api_sow_rhi_csv_export():
    """Export sow.rhi_score — every column, filtered by week or week range."""
    return _table_csv_export("rhi", "RHI_OKR")


@sow.route("/api/sow/redcov-csv-export", methods=["GET"])
@login_required
def api_sow_redcov_csv_export():
    """Export sow.red_cov — every column, filtered by week or week range."""
    return _table_csv_export("redcov", "Redcov_OKR")


@sow.route('/api/sow/ran_capacity-csv-export', methods=['GET'])
@login_required
def api_sow_ran_capacity_csv_export():
    """Export sow.rci_redsector — every column, filtered by week or week range."""
    return _table_csv_export("ran_capacity", "RAN_Capacity_OKR")
