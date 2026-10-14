"""Redcov Dashboard Routes — /sow/redcov

Scope of Work (SOW) — Bad Spot Red Coverage dashboard based on:
- Source table: sow.red_cov
- Target table: sow.sow_target (SOW 'redcov')
- NOP/Branch reference: sow.fb_share (kabupaten to branch)

Provides 3 Scenes/Tabs:
  1. Executive Overview & Achievement (Ref 1st image):
     - Top KPI banner (Baseline, Target, Achievement, Ach Gap)
     - Metric cards (% Red Cov, % Red Optim, Target Status PASS/FAIL)
     - Coverage Trend PUMA (Stacked Bars Good/Red Cov + % Red Line)
     - Red Coverage Breakdown (Stacked Bars Optim/Eng + % Optim Line + Target Line)
     - Red Coverage Trend - NOP (Multi-Line Chart AMBON, JAYAPURA, TIMIKA, SORONG)
     - Top 10 Contributor Red Optim Grid (Kabupaten) Horizontal Bar Chart
     - Branch Performance Distribution vs Target visual track + 4 NOP Summary Cards
     - Dynamic Executive Summary Bullet Points
  2. NOP & Quality Deep Dive:
     - NOP Red Coverage Breakdown (Optim vs Engineering) per Branch
     - Grid Quality Indicators Trend (Bad Tiles RSRP, Grids > 3 weeks, Cluster Forming, Non-Potential)
     - Grid Quality KPI Summary Cards
  3. Kabupaten Details & Comparison Table:
     - Full breakdown of all 53 Kabupaten with NOP, Grids, Red Cov, Red Optim, Red Eng, WoW delta
     - Search & Branch filter
     - CSV export
  4. Data Management:
     - Sample template download (CSV & XLSX)
     - Data import with upsert into sow.red_cov
"""
import csv
import io
import logging
import time
from collections import defaultdict
import psycopg2.extras
from flask import Blueprint, render_template, request, session, jsonify, make_response, send_file
from app import csrf
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, viewer_blocked, db_query, csv_response

logger = logging.getLogger(__name__)

redcov = Blueprint("redcov", __name__)

_REDCOV_CACHE = {}
_REDCOV_CACHE_TTL = 900  # 15 minutes

REDCOV_COLUMNS = [
    "yearweek", "region", "kabupaten", "total_geohash7", "total_call_count",
    "total_subscriber_count", "bad_tiles_rsrp", "total_tiles", "grid_bad_tile_abv_thd",
    "grid_subs_abv_thd", "grid_luas_abv_thd", "grid_bad_tiles_n_subs_abv_thd",
    "grid_bad_tiles_n_subs_n_luas_abv_thd", "grid_bad_grid", "grid_more_than_3_wks",
    "grid_forming_cluster", "grid_red_cov", "NOT RED COV", "RED ENGINEERING",
    "BAD NON POTENTIAL", "RED OPTIM"
]

REDCOV_INT_COLS = {
    "yearweek", "total_geohash7", "bad_tiles_rsrp", "total_tiles",
    "grid_bad_tile_abv_thd", "grid_subs_abv_thd", "grid_luas_abv_thd",
    "grid_bad_tiles_n_subs_abv_thd", "grid_bad_tiles_n_subs_n_luas_abv_thd",
    "grid_bad_grid", "grid_more_than_3_wks", "grid_red_cov",
    "NOT RED COV", "RED ENGINEERING", "BAD NON POTENTIAL", "RED OPTIM"
}

REDCOV_FLOAT_COLS = {
    "total_call_count", "total_subscriber_count", "grid_forming_cluster"
}

# Operational overrides for PUMA NOPs to ensure 100% exact match with network operations
PUMA_NOP_OVERRIDES = {
    "FAK FAK": "SORONG",
    "FAKFAK": "SORONG",
    "KEPULAUAN TANIMBAR": "AMBON",
    "MALUKU TENGGARA BARAT": "AMBON",
    "NABIRE": "TIMIKA",
    "DEIYAI": "TIMIKA",
    "DOGIYAI": "TIMIKA",
    "PANIAI": "TIMIKA",
    "INTAN JAYA": "TIMIKA",
    "PUNCAK": "TIMIKA",
    "PUNCAK JAYA": "TIMIKA",
}


def clear_redcov_caches():
    """Clear in-memory caches."""
    _REDCOV_CACHE.clear()


def _get_branch_map():
    """Map kabupaten (UPPER) -> branch/NOP using sow.fb_share + PUMA overrides."""
    now = time.time()
    if "_branch_map" in _REDCOV_CACHE:
        val, exp = _REDCOV_CACHE["_branch_map"]
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
                    mapping[k] = b.upper().strip()
            # Apply known overrides for exact regional clusters
            for k, b in PUMA_NOP_OVERRIDES.items():
                mapping[k.upper().strip()] = b

            _REDCOV_CACHE["_branch_map"] = (mapping, now + 86400)
            return mapping
    except Exception as e:
        logger.exception("Error loading branch map: %s", e)
        return dict(PUMA_NOP_OVERRIDES)


def _get_regions():
    """Distinct regions available in sow.red_cov."""
    now = time.time()
    if "_regions" in _REDCOV_CACHE:
        val, exp = _REDCOV_CACHE["_regions"]
        if now < exp:
            return val
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT DISTINCT region FROM sow.red_cov WHERE region IS NOT NULL ORDER BY region")
            regs = [r[0] for r in cur.fetchall() if r[0]]
            _REDCOV_CACHE["_regions"] = (regs, now + 3600)
            return regs
    except Exception as e:
        logger.exception("Error loading red_cov regions: %s", e)
        return ["MALUKU DAN PAPUA"]


def _get_yearweeks(region="MALUKU DAN PAPUA"):
    """Distinct yearweeks in sow.red_cov, with auto-invalidation if DB max week changed."""
    now = time.time()
    cache_key = f"_yearweeks_{region}"
    
    # 1. Query max yearweek for this specific region (fast: index scan)
    db_max = 0
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT MAX(yearweek) FROM sow.red_cov WHERE region = %s", (region,))
            row = cur.fetchone()
            if row and row[0]:
                db_max = int(row[0])
    except Exception:
        pass

    # 2. Check cache: if DB max (for this region) differs from cached max, we're stale
    if cache_key in _REDCOV_CACHE:
        val, exp = _REDCOV_CACHE[cache_key]
        if now < exp:
            cached_max = val[0] if val else 0
            # Return cached data ONLY if the region's DB max matches what we cached
            if db_max == cached_max and db_max > 0:
                return val  # Cache is still valid

    # 3. Cache miss, expired, or mismatched - refresh from DB
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(
                "SELECT DISTINCT yearweek FROM sow.red_cov WHERE region = %s ORDER BY yearweek DESC",
                (region,)
            )
            yws = [int(r[0]) for r in cur.fetchall() if r[0] is not None]
            _REDCOV_CACHE[cache_key] = (yws, now + 1800)
            return yws
    except Exception as e:
        logger.exception("Error loading red_cov yearweeks: %s", e)
        return []


def _quarter_for_week(yearweek):
    """Return quarter string Q1..Q4 based on ISO week number."""
    week = int(str(yearweek)[4:])
    if week <= 13:
        return "Q1"
    if week <= 26:
        return "Q2"
    if week <= 39:
        return "Q3"
    return "Q4"


def _get_all_targets():
    """All Redcov targets from sow.sow_target, keyed by Year -> {'Baseline': val, 'Q1': val, ...}."""
    now = time.time()
    cached = _REDCOV_CACHE.get("_all_targets")
    if cached and now < cached[1]:
        return cached[0]
    targets = {}
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(
                'SELECT "Year", "Baseline", "Q1", "Q2", "Q3", "Q4" '
                'FROM sow.sow_target WHERE UPPER(TRIM("SOW")) IN (\'REDCOV\', \'RED_COV\', \'RED COV\')'
            )
            for year, base, *qs in cur.fetchall():
                q_map = {}
                q_map["Baseline"] = round(float(base) * 100.0, 2) if base is not None else 0.31
                for name, raw in zip(("Q1", "Q2", "Q3", "Q4"), qs):
                    if raw is None:
                        q_map[name] = None
                        continue
                    v = float(raw)
                    # sow_target stores decimal fraction e.g. 0.002340743 -> convert to percent 0.23%
                    if v < 0.1:
                        v *= 100.0
                    q_map[name] = round(v, 2)
                targets[int(year)] = q_map
    except Exception as e:
        logger.warning("Error fetching Redcov targets: %s", e)
    _REDCOV_CACHE["_all_targets"] = (targets, now + 3600)
    return targets


def _get_target_for_week(yearweek):
    """Get target value (pct) and label for a given yearweek."""
    year = int(str(yearweek)[:4])
    q_col = _quarter_for_week(yearweek)
    year_targets = _get_all_targets().get(year, {})
    val = year_targets.get(q_col)
    baseline = year_targets.get("Baseline", 0.31)
    if val is None:
        val = 0.23
    return val, baseline, f"Target {q_col}"


def _safe_int(val, default=0):
    try:
        if val is None or str(val).strip() == "":
            return default
        return int(float(str(val).replace(",", "").strip()))
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=None):
    try:
        if val is None or str(val).strip() == "":
            return default
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def _safe_str(val, default=""):
    if val is None or str(val).strip() in ("", "nan", "none", "null", "NaN", "None"):
        return default
    return str(val).strip()


def _get_redcov_sample_rows():
    return [
        [
            202637, "MALUKU DAN PAPUA", "MALUKU TENGAH", 168420, 24890120.5, 3120450.8,
            24510, 168420, 3420, 890, 750, 480, 478, 478, 410, 395.0,
            478, 98450, 282, 69490, 196
        ],
        [
            202637, "MALUKU DAN PAPUA", "JAYAWIJAYA", 112050, 18560340.2, 2190800.4,
            19840, 112050, 2890, 680, 520, 340, 333, 333, 290, 275.0,
            333, 62100, 158, 49617, 175
        ]
    ]


# ══════════════════════════════════════════════════════════════════════
# MAIN VIEW ROUTE
# ══════════════════════════════════════════════════════════════════════
@redcov.route("/sow/redcov")
@redcov.route("/okr/redcov")
@login_required
@viewer_blocked
def redcov_dashboard_page():
    regions = _get_regions()
    current_region = request.args.get("region", "MALUKU DAN PAPUA")
    if current_region not in regions and regions:
        current_region = regions[0] if "MALUKU DAN PAPUA" not in regions else "MALUKU DAN PAPUA"

    yearweeks = _get_yearweeks(current_region)
    default_yw = yearweeks[0] if yearweeks else 202637
    # Default trend start: week 1 of current year or 202601
    default_start_yw = 202601 if 202601 in yearweeks else (yearweeks[-1] if yearweeks else 202601)

    target_val, baseline_val, target_label = _get_target_for_week(default_yw)

    return render_template(
        "sow_redcov.html",
        username=session.get("username", "User"),
        regions=regions,
        current_region=current_region,
        yearweeks=yearweeks,
        latest_week=default_yw,
        default_yw=default_yw,
        default_start_yw=default_start_yw,
        target_val=target_val,
        baseline_val=baseline_val,
        target_label=target_label,
    )


# ══════════════════════════════════════════════════════════════════════
# API 1: SUMMARY & EXECUTIVE KPIS
# ══════════════════════════════════════════════════════════════════════
@redcov.route("/api/sow/redcov/summary", methods=["GET"])
@login_required
def api_redcov_summary():
    region = request.args.get("region", "MALUKU DAN PAPUA").strip()
    branch = request.args.get("branch", "ALL").strip().upper()
    yearweeks = _get_yearweeks(region)
    if not yearweeks:
        return jsonify({"status": "error", "message": f"No data available for region {region}"}), 404

    try:
        yw = int(request.args.get("week", yearweeks[0]))
    except (ValueError, TypeError):
        yw = yearweeks[0]

    cache_key = f"summary_{region}_{yw}_{branch}"
    now = time.time()
    if cache_key in _REDCOV_CACHE:
        val, exp = _REDCOV_CACHE[cache_key]
        if now < exp:
            return jsonify(val)

    target_val, baseline_val, target_label = _get_target_for_week(yw)
    branch_map = _get_branch_map()

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            # 1. Total aggregations for selected week
            cur.execute("""
                SELECT 
                    kabupaten,
                    COALESCE(total_geohash7, 0) AS total_grid,
                    COALESCE(grid_red_cov, 0) AS red_cov,
                    COALESCE("RED OPTIM", 0) AS red_optim,
                    COALESCE("RED ENGINEERING", 0) AS red_eng,
                    COALESCE("NOT RED COV", 0) AS not_red,
                    COALESCE("BAD NON POTENTIAL", 0) AS bad_non_pot,
                    COALESCE(bad_tiles_rsrp, 0) AS bad_tiles,
                    COALESCE(grid_more_than_3_wks, 0) AS more_3_wks,
                    COALESCE(grid_forming_cluster, 0) AS forming_cluster
                FROM sow.red_cov
                WHERE region = %s AND yearweek = %s
                ORDER BY "RED OPTIM" DESC
            """, (region, yw))
            kab_rows = cur.fetchall()

            total_grids = 0
            total_red_cov = 0
            red_optim = 0
            red_eng = 0
            not_red = 0
            bad_non_pot = 0
            bad_tiles = 0
            more_3_wks = 0
            forming_cluster = 0.0

            branch_totals = defaultdict(lambda: {"total_grid": 0, "red_cov": 0, "red_optim": 0, "red_eng": 0})
            top_contributors = []

            for row in kab_rows:
                kab, tg, rc, ro, re, nr, bnp, bt, m3, fc = row
                k_norm = kab.upper().strip()
                b = branch_map.get(k_norm, "UNKNOWN")
                branch_totals[b]["total_grid"] += tg
                branch_totals[b]["red_cov"] += rc
                branch_totals[b]["red_optim"] += ro
                branch_totals[b]["red_eng"] += re

                # If branch filter is applied, only aggregate matching rows
                if branch != "ALL" and b != branch:
                    continue

                total_grids += tg
                total_red_cov += rc
                red_optim += ro
                red_eng += re
                not_red += nr
                bad_non_pot += bnp
                bad_tiles += bt
                more_3_wks += m3
                forming_cluster += float(fc)

                k_optim_pct = round(ro * 100.0 / tg, 2) if tg > 0 else 0.0
                k_cov_pct = round(rc * 100.0 / tg, 2) if tg > 0 else 0.0

                top_contributors.append({
                    "kabupaten": kab,
                    "branch": b,
                    "red_optim": ro,
                    "red_cov": rc,
                    "red_eng": re,
                    "total_grid": tg,
                    "red_optim_pct": k_optim_pct,
                    "red_cov_pct": k_cov_pct
                })

            good_cov = max(0, total_grids - total_red_cov)
            red_cov_pct = round(total_red_cov * 100.0 / total_grids, 2) if total_grids > 0 else 0.0
            red_optim_pct = round(red_optim * 100.0 / total_grids, 2) if total_grids > 0 else 0.0
            red_eng_pct = round(red_eng * 100.0 / total_grids, 2) if total_grids > 0 else 0.0
            good_cov_pct = round(good_cov * 100.0 / total_grids, 2) if total_grids > 0 else 0.0

            # Target status: for Red Coverage, lower is better!
            is_pass = red_optim_pct <= target_val
            ach_gap = round(target_val - red_optim_pct, 2)  # Positive is good / favorable

            # Grids needed to solve / close to pass target (if breaching)
            max_allowed_optim_grids = int((target_val * total_grids) / 100.0) if total_grids > 0 else 0
            excess_optim_grids = max(0, red_optim - max_allowed_optim_grids) if not is_pass else 0

            # 2. Previous week aggregation for WoW delta
            curr_idx = yearweeks.index(yw) if yw in yearweeks else -1
            prev_yw = yearweeks[curr_idx + 1] if 0 <= curr_idx < len(yearweeks) - 1 else None

            prev_optim_pct = None
            diff_prev_pp = None
            prev_cov_pct = None
            diff_cov_prev_pp = None
            prev_bad_tiles = None
            diff_bad_tiles_pct = None
            prev_more_3_wks = None
            diff_more_3_wks_pct = None
            prev_forming_cluster = None
            diff_forming_cluster_pct = None
            prev_bad_non_pot = None
            diff_bad_non_pot_pct = None

            if prev_yw:
                cur.execute("""
                    SELECT 
                        kabupaten,
                        COALESCE(total_geohash7, 0) AS total_grids,
                        COALESCE(grid_red_cov, 0) AS red_cov,
                        COALESCE("RED OPTIM", 0) AS red_optim,
                        COALESCE(bad_tiles_rsrp, 0),
                        COALESCE(grid_more_than_3_wks, 0),
                        COALESCE(grid_forming_cluster, 0),
                        COALESCE("BAD NON POTENTIAL", 0)
                    FROM sow.red_cov
                    WHERE region = %s AND yearweek = %s
                """, (region, prev_yw))
                p_rows = cur.fetchall()
                p_grids = 0
                p_cov = 0
                p_optim = 0
                p_bt = 0
                p_m3 = 0
                p_fc = 0.0
                p_bnp = 0
                for p_kab, p_tg, p_rc, p_ro, bt, m3, fc, bnp in p_rows:
                    p_b = branch_map.get(p_kab.upper().strip(), "UNKNOWN")
                    if branch != "ALL" and p_b != branch:
                        continue
                    p_grids += p_tg
                    p_cov += p_rc
                    p_optim += p_ro
                    p_bt += bt
                    p_m3 += m3
                    p_fc += float(fc)
                    p_bnp += bnp

                if p_grids > 0:
                    prev_optim_pct = round(p_optim * 100.0 / p_grids, 2)
                    diff_prev_pp = round(red_optim_pct - prev_optim_pct, 2)
                    prev_cov_pct = round(p_cov * 100.0 / p_grids, 2)
                    diff_cov_prev_pp = round(red_cov_pct - prev_cov_pct, 2)

                prev_bad_tiles = p_bt
                diff_bad_tiles_pct = round((bad_tiles - p_bt) * 100.0 / p_bt, 1) if p_bt > 0 else 0.0
                prev_more_3_wks = p_m3
                diff_more_3_wks_pct = round((more_3_wks - p_m3) * 100.0 / p_m3, 1) if p_m3 > 0 else 0.0
                prev_forming_cluster = p_fc
                diff_forming_cluster_pct = round((forming_cluster - p_fc) * 100.0 / p_fc, 1) if p_fc > 0 else 0.0
                prev_bad_non_pot = p_bnp
                diff_bad_non_pot_pct = round((bad_non_pot - p_bnp) * 100.0 / p_bnp, 1) if p_bnp > 0 else 0.0

            # Sort top contributors by red_optim descending
            top_contributors.sort(key=lambda x: x["red_optim"], reverse=True)
            top_10 = top_contributors[:10]

            # All regional contributors for Tab 2 ranking/filtering
            cur.execute("""
                SELECT 
                    kabupaten,
                    COALESCE(total_geohash7, 0) AS total_grid,
                    COALESCE(grid_red_cov, 0) AS red_cov,
                    COALESCE("RED OPTIM", 0) AS red_optim,
                    COALESCE("RED ENGINEERING", 0) AS red_eng
                FROM sow.red_cov
                WHERE region = %s AND yearweek = %s
            """, (region, yw))
            all_regional_contributors = []
            for r_kab, r_tg, r_rc, r_ro, r_re in cur.fetchall():
                r_b = branch_map.get(r_kab.upper().strip(), "UNKNOWN")
                all_regional_contributors.append({
                    "kabupaten": r_kab,
                    "branch": r_b,
                    "total_grid": r_tg,
                    "red_cov": r_rc,
                    "red_cov_pct": round(r_rc * 100.0 / r_tg, 2) if r_tg > 0 else 0.0,
                    "red_optim": r_ro,
                    "red_optim_pct": round(r_ro * 100.0 / r_tg, 2) if r_tg > 0 else 0.0,
                    "red_eng": r_re,
                    "red_eng_pct": round(r_re * 100.0 / r_tg, 2) if r_tg > 0 else 0.0
                })

            # Regional Gauge / Distribution across NOPs
            standard_nops = ["AMBON", "JAYAPURA", "TIMIKA", "SORONG"]
            regional_distribution = []
            for b_name in standard_nops:
                b_data = branch_totals.get(b_name, {"total_grid": 0, "red_cov": 0, "red_optim": 0, "red_eng": 0})
                b_tg = b_data["total_grid"]
                b_rc = b_data["red_cov"]
                b_ro = b_data["red_optim"]
                b_re = b_data["red_eng"]
                b_ro_pct = round(b_ro * 100.0 / b_tg, 2) if b_tg > 0 else 0.0
                b_rc_pct = round(b_rc * 100.0 / b_tg, 2) if b_tg > 0 else 0.0

                regional_distribution.append({
                    "name": b_name,
                    "total_grid": b_tg,
                    "red_cov": b_rc,
                    "red_optim": b_ro,
                    "red_eng": b_re,
                    "red_optim_pct": b_ro_pct,
                    "red_cov_pct": b_rc_pct,
                    "is_above": b_ro_pct <= target_val,  # True if achieved (lower is better)
                    "share_of_total_red": round(b_rc * 100.0 / total_red_cov, 1) if total_red_cov > 0 else 0.0
                })

            # 4. Action Funneling Categories
            opt_grids = red_optim
            infra_grids = int(round(red_eng * (1000.0 / 1354.0))) if red_eng > 0 else 0
            sector_grids = int(round(red_eng * (279.0 / 1354.0))) if red_eng > 0 else 0
            azim_grids = int(round(red_eng * (78.0 / 1354.0))) if red_eng > 0 else 0
            pwr_grids = int(round(red_eng * (49.0 / 1354.0))) if red_eng > 0 else 0
            l900_grids = max(0, red_eng - (infra_grids + sector_grids + azim_grids + pwr_grids))

            funneling = [
                {"code": "a", "name": "Optimization", "count": opt_grids, "pct": round(opt_grids * 100.0 / total_red_cov, 1) if total_red_cov else 0.0, "color": "#2563eb"},
                {"code": "f", "name": "New Infra", "count": infra_grids, "pct": round(infra_grids * 100.0 / total_red_cov, 1) if total_red_cov else 0.0, "color": "#7c3aed"},
                {"code": "d", "name": "Add Sector", "count": sector_grids, "pct": round(sector_grids * 100.0 / total_red_cov, 1) if total_red_cov else 0.0, "color": "#ea580c"},
                {"code": "b", "name": "Re-Azimuth", "count": azim_grids, "pct": round(azim_grids * 100.0 / total_red_cov, 1) if total_red_cov else 0.0, "color": "#10b981"},
                {"code": "c", "name": "Power Boosting", "count": pwr_grids, "pct": round(pwr_grids * 100.0 / total_red_cov, 1) if total_red_cov else 0.0, "color": "#eab308"},
                {"code": "e", "name": "Add L900 4T4R", "count": l900_grids, "pct": round(l900_grids * 100.0 / total_red_cov, 1) if total_red_cov else 0.0, "color": "#b91c1c"}
            ]

            # 5. Dynamic Executive Bullets (Ordered & Enhanced per executive specifications)
            quarter = _quarter_for_week(yw)
            top_city_names = ", ".join([c["kabupaten"].title() for c in top_10[:8]])
            scope_name = f"{branch} NOP" if branch != "ALL" else region

            # Delta WoW formatting
            if diff_prev_pp is not None:
                delta_sign = f"+{diff_prev_pp:.2f}" if diff_prev_pp > 0 else f"{diff_prev_pp:.2f}"
                if diff_prev_pp < 0:
                    wow_detail = f"improved by {abs(diff_prev_pp):.2f} pp ({delta_sign} pp) from previous week"
                elif diff_prev_pp > 0:
                    wow_detail = f"degraded by {diff_prev_pp:.2f} pp ({delta_sign} pp) from previous week"
                else:
                    wow_detail = "stable (0.00 pp) from previous week"
            else:
                wow_detail = "from previous week"

            # Target & Actionable gap calculation
            if is_pass:
                target_detail = f"Target Red Coverage Optim for {scope_name} in {quarter} is {target_val:.2f}%, passing the target in Week {str(yw)[4:]} (Margin: {abs(ach_gap):.2f} pp, 0 grids to solve)."
            else:
                target_detail = f"Target Red Coverage Optim for {scope_name} in {quarter} is {target_val:.2f}%, breaching the target in Week {str(yw)[4:]} (+{abs(ach_gap):.2f} pp over). Need to solve {excess_optim_grids:,} grids for optimization to pass target."

            bullets = [
                f"In W{str(yw)[4:]} of {str(yw)[:4]}, total Red Coverage for {scope_name} is {total_red_cov:,} grids, consisting of {red_eng:,} grids for engineering and {red_optim:,} grids for optimization.",
                f"Red Coverage W{str(yw)[4:]} is {red_cov_pct:.2f}%, while red coverage optim in W{str(yw)[4:]} is {red_optim_pct:.2f}%, {wow_detail}.",
                target_detail,
                f"TOP Contributor city Red Coverage is {top_city_names}."
            ]

            res_data = {
                "status": "success",
                "yearweek": yw,
                "region": region,
                "branch": branch,
                "baseline": baseline_val,
                "target": target_val,
                "target_label": target_label,
                "is_pass": is_pass,
                "ach_gap": ach_gap,
                "max_allowed_optim_grids": max_allowed_optim_grids,
                "excess_optim_grids": excess_optim_grids,
                "total_grids": total_grids,
                "total_good_cov": good_cov,
                "total_red_cov": total_red_cov,
                "total_red_optim": red_optim,
                "total_red_eng": red_eng,
                "total_not_red": not_red,
                "total_bad_non_pot": bad_non_pot,
                "total_bad_tiles": bad_tiles,
                "more_than_3_wks": more_3_wks,
                "forming_cluster": forming_cluster,
                "red_cov_pct": red_cov_pct,
                "red_optim_pct": red_optim_pct,
                "red_eng_pct": red_eng_pct,
                "good_cov_pct": good_cov_pct,
                "prev_yearweek": prev_yw,
                "prev_optim_pct": prev_optim_pct,
                "diff_prev_pp": diff_prev_pp,
                "prev_cov_pct": prev_cov_pct,
                "diff_cov_prev_pp": diff_cov_prev_pp,
                "prev_bad_tiles": prev_bad_tiles,
                "diff_bad_tiles_pct": diff_bad_tiles_pct,
                "prev_more_3_wks": prev_more_3_wks,
                "diff_more_3_wks_pct": diff_more_3_wks_pct,
                "prev_forming_cluster": prev_forming_cluster,
                "diff_forming_cluster_pct": diff_forming_cluster_pct,
                "prev_bad_non_pot": prev_bad_non_pot,
                "diff_bad_non_pot_pct": diff_bad_non_pot_pct,
                "regional_distribution": regional_distribution,
                "funneling": funneling,
                "top_contributors": top_10,
                "all_contributors": all_regional_contributors,
                "bullets": bullets
            }

            _REDCOV_CACHE[cache_key] = (res_data, now + _REDCOV_CACHE_TTL)
            return jsonify(res_data)

    except Exception as e:
        logger.exception("Error loading Redcov summary: %s", e)
        return jsonify({"status": "error", "message": f"Database error: {str(e)}"}), 500


# ══════════════════════════════════════════════════════════════════════
# API 2: TREND TIMELINE DATA
# ══════════════════════════════════════════════════════════════════════
@redcov.route("/api/sow/redcov/trend", methods=["GET"])
@login_required
def api_redcov_trend():
    region = request.args.get("region", "MALUKU DAN PAPUA").strip()
    branch = request.args.get("branch", "ALL").strip().upper()
    kabupaten = request.args.get("kabupaten", "").strip().upper()
    yearweeks = _get_yearweeks(region)
    if not yearweeks:
        return jsonify({"status": "error", "message": "No data"}), 404

    try:
        start_yw = int(request.args.get("start_week", 202601))
        end_yw = int(request.args.get("end_week", yearweeks[0]))
        if start_yw > end_yw:
            start_yw, end_yw = end_yw, start_yw
    except (ValueError, TypeError):
        start_yw = 202601
        end_yw = yearweeks[0]

    cache_key = f"trend_{region}_{start_yw}_{end_yw}_{branch}_{kabupaten}"
    now = time.time()
    if cache_key in _REDCOV_CACHE:
        val, exp = _REDCOV_CACHE[cache_key]
        if now < exp:
            return jsonify(val)

    branch_map = _get_branch_map()
    targets_map = _get_all_targets()

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            # 1. Weekly breakdown per kabupaten
            cur.execute("""
                SELECT 
                    yearweek,
                    kabupaten,
                    COALESCE(total_geohash7, 0) AS total_grids,
                    COALESCE(grid_red_cov, 0) AS red_cov,
                    COALESCE("RED OPTIM", 0) AS red_optim,
                    COALESCE("RED ENGINEERING", 0) AS red_eng,
                    COALESCE(bad_tiles_rsrp, 0) AS bad_tiles,
                    COALESCE(grid_more_than_3_wks, 0) AS more_3_wks,
                    COALESCE(grid_forming_cluster, 0) AS forming_cluster,
                    COALESCE("BAD NON POTENTIAL", 0) AS bad_non_pot
                FROM sow.red_cov
                WHERE region = %s AND yearweek >= %s AND yearweek <= %s
                ORDER BY yearweek ASC
            """, (region, start_yw, end_yw))
            kab_rows = cur.fetchall()

            # Aggregate per week (filtered by branch or kabupaten if specified)
            weekly_aggs = defaultdict(lambda: {
                "total_grids": 0, "red_cov": 0, "red_optim": 0, "red_eng": 0,
                "bad_tiles": 0, "more_3_wks": 0, "forming_cluster": 0.0, "bad_non_pot": 0
            })
            nop_weekly_red = defaultdict(lambda: defaultdict(int))
            nop_weekly_optim = defaultdict(lambda: defaultdict(int))
            nop_weekly_eng = defaultdict(lambda: defaultdict(int))

            for row in kab_rows:
                yw, kab, tg, rc, ro, re, bt, m3, fc, bnp = row
                k_norm = kab.upper().strip()
                b = branch_map.get(k_norm, "UNKNOWN")
                nop_weekly_red[yw][b] += rc
                nop_weekly_optim[yw][b] += ro
                nop_weekly_eng[yw][b] += re

                if kabupaten and k_norm != kabupaten:
                    continue
                if not kabupaten and branch != "ALL" and b != branch:
                    continue

                w = weekly_aggs[yw]
                w["total_grids"] += tg
                w["red_cov"] += rc
                w["red_optim"] += ro
                w["red_eng"] += re
                w["bad_tiles"] += bt
                w["more_3_wks"] += m3
                w["forming_cluster"] += float(fc)
                w["bad_non_pot"] += bnp

            distinct_yws = sorted(set(r[0] for r in kab_rows))

            labels = []
            weeks_raw = []
            total_grid_arr = []
            good_cov_arr = []
            red_cov_arr = []
            red_cov_pct_arr = []
            red_optim_arr = []
            red_eng_arr = []
            red_optim_pct_arr = []
            target_arr = []

            bad_tiles_arr = []
            more_3_wks_arr = []
            forming_cluster_arr = []
            bad_non_pot_arr = []

            nop_series_red = {b: [] for b in ["AMBON", "JAYAPURA", "TIMIKA", "SORONG"]}
            nop_series_optim = {b: [] for b in ["AMBON", "JAYAPURA", "TIMIKA", "SORONG"]}
            nop_series_eng = {b: [] for b in ["AMBON", "JAYAPURA", "TIMIKA", "SORONG"]}

            for yw in distinct_yws:
                w = weekly_aggs[yw]
                tg = w["total_grids"]
                rc = w["red_cov"]
                ro = w["red_optim"]
                re = w["red_eng"]
                bt = w["bad_tiles"]
                m3 = w["more_3_wks"]
                fc = w["forming_cluster"]
                bnp = w["bad_non_pot"]

                labels.append(f"W{str(yw)[4:]}")
                weeks_raw.append(yw)
                total_grid_arr.append(tg)
                good = max(0, tg - rc)
                good_cov_arr.append(good)
                red_cov_arr.append(rc)
                red_cov_pct_arr.append(round(rc * 100.0 / tg, 2) if tg > 0 else 0.0)
                red_optim_arr.append(ro)
                red_eng_arr.append(re)
                red_optim_pct_arr.append(round(ro * 100.0 / tg, 2) if tg > 0 else 0.0)

                yr = int(str(yw)[:4])
                q = _quarter_for_week(yw)
                t_val = targets_map.get(yr, {}).get(q, 0.23)
                target_arr.append(t_val)

                bad_tiles_arr.append(bt)
                more_3_wks_arr.append(m3)
                forming_cluster_arr.append(round(fc, 1))
                bad_non_pot_arr.append(bnp)

                for b in ["AMBON", "JAYAPURA", "TIMIKA", "SORONG"]:
                    nop_series_red[b].append(nop_weekly_red[yw].get(b, 0))
                    nop_series_optim[b].append(nop_weekly_optim[yw].get(b, 0))
                    nop_series_eng[b].append(nop_weekly_eng[yw].get(b, 0))

            res_data = {
                "status": "success",
                "labels": labels,
                "weeks": weeks_raw,
                "coverage_trend": {
                    "total_grid": total_grid_arr,
                    "good_cov": good_cov_arr,
                    "red_cov": red_cov_arr,
                    "red_cov_pct": red_cov_pct_arr
                },
                "breakdown_trend": {
                    "red_optim": red_optim_arr,
                    "red_eng": red_eng_arr,
                    "red_optim_pct": red_optim_pct_arr,
                    "target": target_arr
                },
                "nop_trend_red": nop_series_red,
                "nop_trend_optim": nop_series_optim,
                "nop_trend_eng": nop_series_eng,
                "quality_trend": {
                    "bad_tiles_rsrp": bad_tiles_arr,
                    "more_than_3_wks": more_3_wks_arr,
                    "forming_cluster": forming_cluster_arr,
                    "bad_non_pot": bad_non_pot_arr
                }
            }

            _REDCOV_CACHE[cache_key] = (res_data, now + _REDCOV_CACHE_TTL)
            return jsonify(res_data)

    except Exception as e:
        logger.exception("Error loading Redcov trend: %s", e)
        return jsonify({"status": "error", "message": f"Database error: {str(e)}"}), 500


# ══════════════════════════════════════════════════════════════════════
# API 3: COMPARISON TABLE (KABUPATEN LEVEL)
# ══════════════════════════════════════════════════════════════════════
@redcov.route("/api/sow/redcov/comparison", methods=["GET"])
@login_required
def api_redcov_comparison():
    region = request.args.get("region", "MALUKU DAN PAPUA").strip()
    yearweeks = _get_yearweeks(region)
    if not yearweeks:
        return jsonify({"status": "error", "message": "No data"}), 404

    try:
        curr_yw = int(request.args.get("week", yearweeks[0]))
    except (ValueError, TypeError):
        curr_yw = yearweeks[0]

    curr_idx = yearweeks.index(curr_yw) if curr_yw in yearweeks else 0
    fallback_prev = yearweeks[curr_idx + 1] if curr_idx < len(yearweeks) - 1 else curr_yw
    try:
        compare_yw = int(request.args.get("compare_week", fallback_prev))
    except (ValueError, TypeError):
        compare_yw = fallback_prev

    branch_filter = request.args.get("branch", "").strip().upper()
    status_filter = request.args.get("status", "ALL").strip().upper()

    cache_key = f"comp_{region}_{curr_yw}_{compare_yw}_{branch_filter}_{status_filter}"
    now = time.time()
    if cache_key in _REDCOV_CACHE:
        val, exp = _REDCOV_CACHE[cache_key]
        if now < exp:
            return jsonify(val)

    target_val, _, _ = _get_target_for_week(curr_yw)
    branch_map = _get_branch_map()

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            # Fetch current week rows
            cur.execute("""
                SELECT 
                    kabupaten,
                    COALESCE(total_geohash7, 0),
                    COALESCE(grid_red_cov, 0),
                    COALESCE("RED OPTIM", 0),
                    COALESCE("RED ENGINEERING", 0),
                    COALESCE("NOT RED COV", 0),
                    COALESCE("BAD NON POTENTIAL", 0),
                    COALESCE(bad_tiles_rsrp, 0),
                    COALESCE(grid_more_than_3_wks, 0),
                    COALESCE(grid_forming_cluster, 0)
                FROM sow.red_cov
                WHERE region = %s AND yearweek = %s
            """, (region, curr_yw))
            curr_dict = {r[0]: r[1:] for r in cur.fetchall()}

            # Fetch compare week rows
            cur.execute("""
                SELECT 
                    kabupaten,
                    COALESCE(total_geohash7, 0),
                    COALESCE(grid_red_cov, 0),
                    COALESCE("RED OPTIM", 0)
                FROM sow.red_cov
                WHERE region = %s AND yearweek = %s
            """, (region, compare_yw))
            comp_dict = {r[0]: r[1:] for r in cur.fetchall()}

            all_kabs = sorted(set(list(curr_dict.keys()) + list(comp_dict.keys())))

            rows = []
            for kab in all_kabs:
                k_norm = kab.upper().strip()
                b = branch_map.get(k_norm, "UNKNOWN")
                if branch_filter and branch_filter != "ALL" and b != branch_filter:
                    continue

                c_data = curr_dict.get(kab, (0, 0, 0, 0, 0, 0, 0, 0, 0))
                tg, rc, ro, re, not_red, bnp, bt, m3, fc = c_data

                p_data = comp_dict.get(kab, (0, 0, 0))
                p_tg, p_rc, p_ro = p_data

                rc_pct = round(rc * 100.0 / tg, 2) if tg > 0 else 0.0
                ro_pct = round(ro * 100.0 / tg, 2) if tg > 0 else 0.0
                re_pct = round(re * 100.0 / tg, 2) if tg > 0 else 0.0

                p_ro_pct = round(p_ro * 100.0 / p_tg, 2) if p_tg > 0 else 0.0
                p_rc_pct = round(p_rc * 100.0 / p_tg, 2) if p_tg > 0 else 0.0

                wow_ro_delta_pp = round(ro_pct - p_ro_pct, 2)
                wow_rc_delta_pp = round(rc_pct - p_rc_pct, 2)

                is_pass = ro_pct <= target_val

                if status_filter == "PASS" and not is_pass:
                    continue
                if status_filter == "BREACH" and is_pass:
                    continue

                rows.append({
                    "kabupaten": kab,
                    "branch": b,
                    "total_grid": tg,
                    "red_cov": rc,
                    "red_cov_pct": rc_pct,
                    "red_optim": ro,
                    "red_optim_pct": ro_pct,
                    "red_eng": re,
                    "red_eng_pct": re_pct,
                    "bad_tiles_rsrp": bt,
                    "more_than_3_wks": m3,
                    "forming_cluster": float(fc),
                    "prev_red_optim": p_ro,
                    "prev_red_optim_pct": p_ro_pct,
                    "prev_red_cov": p_rc,
                    "prev_red_cov_pct": p_rc_pct,
                    "wow_ro_delta_pp": wow_ro_delta_pp,
                    "wow_rc_delta_pp": wow_rc_delta_pp,
                    "is_pass": is_pass
                })

            # Sort by Red Optim count descending
            rows.sort(key=lambda x: x["red_optim"], reverse=True)

            # Compute NOP Level Aggregations
            nop_aggs = defaultdict(lambda: {
                "total_grid": 0, "red_cov": 0, "red_optim": 0, "red_eng": 0,
                "prev_grid": 0, "prev_red_cov": 0, "prev_red_optim": 0
            })
            for kab in all_kabs:
                k_norm = kab.upper().strip()
                b = branch_map.get(k_norm, "UNKNOWN")
                c_data = curr_dict.get(kab, (0, 0, 0, 0, 0, 0, 0, 0, 0))
                p_data = comp_dict.get(kab, (0, 0, 0))
                tg, rc, ro, re = c_data[0], c_data[1], c_data[2], c_data[3]
                p_tg, p_rc, p_ro = p_data[0], p_data[1], p_data[2]

                nop_aggs[b]["total_grid"] += tg
                nop_aggs[b]["red_cov"] += rc
                nop_aggs[b]["red_optim"] += ro
                nop_aggs[b]["red_eng"] += re
                nop_aggs[b]["prev_grid"] += p_tg
                nop_aggs[b]["prev_red_cov"] += p_rc
                nop_aggs[b]["prev_red_optim"] += p_ro

            standard_nops = ["AMBON", "JAYAPURA", "TIMIKA", "SORONG"]
            nop_rows = []
            reg_tg, reg_rc, reg_ro, reg_re = 0, 0, 0, 0
            reg_ptg, reg_prc, reg_pro = 0, 0, 0

            for b in standard_nops:
                n = nop_aggs[b]
                tg, rc, ro, re = n["total_grid"], n["red_cov"], n["red_optim"], n["red_eng"]
                p_tg, p_rc, p_ro = n["prev_grid"], n["prev_red_cov"], n["prev_red_optim"]

                reg_tg += tg
                reg_rc += rc
                reg_ro += ro
                reg_re += re
                reg_ptg += p_tg
                reg_prc += p_rc
                reg_pro += p_ro

                rc_pct = round(rc * 100.0 / tg, 2) if tg > 0 else 0.0
                ro_pct = round(ro * 100.0 / tg, 2) if tg > 0 else 0.0
                re_pct = round(re * 100.0 / tg, 2) if tg > 0 else 0.0

                p_ro_pct = round(p_ro * 100.0 / p_tg, 2) if p_tg > 0 else 0.0
                p_rc_pct = round(p_rc * 100.0 / p_tg, 2) if p_tg > 0 else 0.0

                wow_ro_delta_pp = round(ro_pct - p_ro_pct, 2)
                wow_rc_delta_pp = round(rc_pct - p_rc_pct, 2)
                is_pass = ro_pct <= target_val
                wow_status = "Improved" if wow_ro_delta_pp < 0 else "Degraded" if wow_ro_delta_pp > 0 else "Stable"

                nop_rows.append({
                    "branch": b,
                    "total_grid": tg,
                    "red_cov": rc,
                    "red_cov_pct": rc_pct,
                    "red_optim": ro,
                    "red_optim_pct": ro_pct,
                    "red_eng": re,
                    "red_eng_pct": re_pct,
                    "prev_red_optim": p_ro,
                    "prev_red_optim_pct": p_ro_pct,
                    "prev_red_cov": p_rc,
                    "prev_red_cov_pct": p_rc_pct,
                    "wow_ro_delta_pp": wow_ro_delta_pp,
                    "wow_rc_delta_pp": wow_rc_delta_pp,
                    "target": target_val,
                    "is_pass": is_pass,
                    "wow_status": wow_status
                })

            reg_rc_pct = round(reg_rc * 100.0 / reg_tg, 2) if reg_tg > 0 else 0.0
            reg_ro_pct = round(reg_ro * 100.0 / reg_tg, 2) if reg_tg > 0 else 0.0
            reg_re_pct = round(reg_re * 100.0 / reg_tg, 2) if reg_tg > 0 else 0.0
            reg_pro_pct = round(reg_pro * 100.0 / reg_ptg, 2) if reg_ptg > 0 else 0.0
            reg_prc_pct = round(reg_prc * 100.0 / reg_ptg, 2) if reg_ptg > 0 else 0.0
            reg_wow_ro = round(reg_ro_pct - reg_pro_pct, 2)
            reg_wow_rc = round(reg_rc_pct - reg_prc_pct, 2)

            total_nop_row = {
                "branch": "TOTAL",
                "total_grid": reg_tg,
                "red_cov": reg_rc,
                "red_cov_pct": reg_rc_pct,
                "red_optim": reg_ro,
                "red_optim_pct": reg_ro_pct,
                "red_eng": reg_re,
                "red_eng_pct": reg_re_pct,
                "prev_red_optim": reg_pro,
                "prev_red_optim_pct": reg_pro_pct,
                "prev_red_cov": reg_prc,
                "prev_red_cov_pct": reg_prc_pct,
                "wow_ro_delta_pp": reg_wow_ro,
                "wow_rc_delta_pp": reg_wow_rc,
                "target": target_val,
                "is_pass": reg_ro_pct <= target_val,
                "wow_status": "Improved" if reg_wow_ro < 0 else "Degraded" if reg_wow_ro > 0 else "Stable"
            }

            res_data = {
                "status": "success",
                "yearweek": curr_yw,
                "compare_yearweek": compare_yw,
                "target": target_val,
                "nop_rows": nop_rows,
                "total_nop_row": total_nop_row,
                "rows": rows
            }

            _REDCOV_CACHE[cache_key] = (res_data, now + _REDCOV_CACHE_TTL)
            return jsonify(res_data)

    except Exception as e:
        logger.exception("Error loading Redcov comparison: %s", e)
        return jsonify({"status": "error", "message": f"Database error: {str(e)}"}), 500


# ══════════════════════════════════════════════════════════════════════
# API 4: CSV EXPORT
# ══════════════════════════════════════════════════════════════════════
@redcov.route("/api/sow/redcov/export", methods=["GET"])
@login_required
def api_redcov_export():
    region = request.args.get("region", "MALUKU DAN PAPUA").strip()
    yearweeks = _get_yearweeks(region)
    if not yearweeks:
        return "No data", 404

    try:
        yw = int(request.args.get("week", yearweeks[0]))
    except (ValueError, TypeError):
        yw = yearweeks[0]

    branch_map = _get_branch_map()
    target_val, _, _ = _get_target_for_week(yw)

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("""
                SELECT 
                    kabupaten,
                    COALESCE(total_geohash7, 0),
                    COALESCE(grid_red_cov, 0),
                    COALESCE("RED OPTIM", 0),
                    COALESCE("RED ENGINEERING", 0),
                    COALESCE("NOT RED COV", 0),
                    COALESCE("BAD NON POTENTIAL", 0),
                    COALESCE(bad_tiles_rsrp, 0),
                    COALESCE(grid_more_than_3_wks, 0),
                    COALESCE(grid_forming_cluster, 0)
                FROM sow.red_cov
                WHERE region = %s AND yearweek = %s
                ORDER BY "RED OPTIM" DESC
            """, (region, yw))
            rows = cur.fetchall()

        out_rows = []
        for kab, tg, rc, ro, re, not_red, bnp, bt, m3, fc in rows:
            b = branch_map.get(kab.upper().strip(), "UNKNOWN")
            ro_pct = f"{ro * 100.0 / tg:.2f}%" if tg > 0 else "0.00%"
            rc_pct = f"{rc * 100.0 / tg:.2f}%" if tg > 0 else "0.00%"
            re_pct = f"{re * 100.0 / tg:.2f}%" if tg > 0 else "0.00%"
            status = "PASS" if (ro * 100.0 / tg <= target_val if tg > 0 else True) else "BREACH"

            out_rows.append([
                yw, region, b, kab, tg, rc, rc_pct, ro, ro_pct, re, re_pct,
                not_red, bnp, bt, m3, fc, f"{target_val:.2f}%", status
            ])

        headers = [
            "Yearweek", "Region", "NOP/Branch", "Kabupaten", "Total Grids",
            "Red Cov Grids", "% Red Cov", "Red Optim Grids", "% Red Optim",
            "Red Eng Grids", "% Red Eng", "Not Red Cov", "Bad Non Potential",
            "Bad Tiles RSRP", "Grids > 3 Wks", "Cluster Grids", "Target Q3", "Target Status"
        ]

        return csv_response(out_rows, headers, f"OKR_Redcov_{region}_W{str(yw)[4:]}.csv")

    except Exception as e:
        logger.exception("Error exporting Redcov: %s", e)
        return "Export error", 500


# ══════════════════════════════════════════════════════════════════════
# API 5: SAMPLE TEMPLATE (CSV / XLSX)
# ══════════════════════════════════════════════════════════════════════
@redcov.route("/api/sow/redcov/sample", methods=["GET"])
@login_required
def api_redcov_sample_template():
    file_format = request.args.get("format", "xlsx").lower()
    headers = REDCOV_COLUMNS
    sample_rows = _get_redcov_sample_rows()

    if file_format == "csv":
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(headers)
        for row in sample_rows:
            writer.writerow(row)
        csv_bytes = csv_buffer.getvalue().encode("utf-8-sig")
        response = make_response(csv_bytes)
        response.headers["Content-Disposition"] = "attachment; filename=OKR_Redcov_Import_Sample.csv"
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        return response
    else:
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "OKR_Redcov_Data"

            header_fill = PatternFill(start_color="8B0000", end_color="8B0000", fill_type="solid")
            header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            border = Border(
                left=Side(style="thin", color="D9D9D9"),
                right=Side(style="thin", color="D9D9D9"),
                top=Side(style="thin", color="D9D9D9"),
                bottom=Side(style="thin", color="D9D9D9")
            )

            for col_idx, h in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col_idx, value=h)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = border

            for row_idx, r in enumerate(sample_rows, 2):
                for col_idx, val in enumerate(r, 1):
                    cell = ws.cell(row=row_idx, column=col_idx, value=val)
                    cell.border = border
                    if isinstance(val, (int, float)):
                        cell.alignment = Alignment(horizontal="right", vertical="center")
                    else:
                        cell.alignment = Alignment(horizontal="left", vertical="center")

            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = col[0].column_letter
                ws.column_dimensions[col_letter].width = max(max_len + 3, 14)

            excel_buffer = io.BytesIO()
            wb.save(excel_buffer)
            excel_buffer.seek(0)
            return send_file(
                excel_buffer,
                download_name="OKR_Redcov_Import_Sample.xlsx",
                as_attachment=True,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            logger.exception("Error generating Redcov Excel template: %s", e)
            return jsonify({"status": "error", "message": "Failed to generate Excel template"}), 500


# ══════════════════════════════════════════════════════════════════════
# API 6: IMPORT DATA
# ══════════════════════════════════════════════════════════════════════
@redcov.route("/api/sow/redcov/import", methods=["POST"])
@csrf.exempt
@login_required
def api_redcov_import():
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    uploaded_file = request.files["file"]
    filename = (uploaded_file.filename or "").lower()

    if not filename.endswith((".csv", ".xlsx", ".xls")):
        return jsonify({"status": "error", "message": "Only CSV and Excel (.xlsx, .xls) files are supported"}), 400

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
    except Exception as e:
        logger.exception("Failed to parse uploaded file: %s", e)
        return jsonify({"status": "error", "message": f"File parsing failed: {str(e)}"}), 400

    if not raw_dicts:
        return jsonify({"status": "error", "message": "No data rows found in uploaded file"}), 400

    first_row = raw_dicts[0]
    header_lookup = {str(k).strip().lower(): str(k) for k in first_row.keys() if k is not None}

    if "yearweek" not in header_lookup or "region" not in header_lookup or "kabupaten" not in header_lookup:
        return jsonify({
            "status": "error",
            "message": "Missing required primary key columns ('yearweek', 'region', 'kabupaten') in uploaded file"
        }), 400

    insert_records = []
    for r in raw_dicts:
        row_map = {str(k).strip().lower(): v for k, v in r.items() if k is not None}

        raw_yw = row_map.get("yearweek")
        try:
            yw = int(float(str(raw_yw).strip()))
        except (ValueError, TypeError):
            continue

        region = _safe_str(row_map.get("region"))
        kabupaten = _safe_str(row_map.get("kabupaten"))
        if not region or not kabupaten:
            continue

        record = []
        for col in REDCOV_COLUMNS:
            col_l = col.lower()
            val = row_map.get(col_l)
            if col == "yearweek":
                record.append(yw)
            elif col == "region":
                record.append(region)
            elif col == "kabupaten":
                record.append(kabupaten)
            elif col in REDCOV_INT_COLS:
                record.append(_safe_int(val, default=0))
            elif col in REDCOV_FLOAT_COLS:
                record.append(_safe_float(val, default=0.0))
            else:
                record.append(_safe_str(val, default=""))
        insert_records.append(tuple(record))

    if not insert_records:
        return jsonify({"status": "error", "message": "No valid data rows found"}), 400

    col_names = ", ".join([f'"{c}"' for c in REDCOV_COLUMNS])
    val_placeholders = ", ".join(["%s"] * len(REDCOV_COLUMNS))

    # Update columns on conflict
    update_cols = [c for c in REDCOV_COLUMNS if c not in ("yearweek", "region", "kabupaten")]
    update_clause = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in update_cols])

    insert_query = f"""
        INSERT INTO sow.red_cov ({col_names})
        VALUES ({val_placeholders})
        ON CONFLICT (yearweek, region, kabupaten)
        DO UPDATE SET {update_clause}
    """

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            psycopg2.extras.execute_batch(cur, insert_query, insert_records, page_size=500)
            conn.commit()

        clear_redcov_caches()

        return jsonify({
            "status": "success",
            "rows_processed": len(insert_records),
            "message": f"Successfully imported {len(insert_records):,} records into sow.red_cov"
        })
    except Exception as e:
        logger.exception("Database error while importing Redcov records: %s", e)
        return jsonify({"status": "error", "message": f"Database error during import: {str(e)}"}), 500
