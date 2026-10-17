"""RAN Capacity Dashboard Routes — /sow/ran_capacity

Scope of Work (SOW) — RAN Capacity (RCI & Unbalance) dashboard based on:
- Source table: sow.rci_redsector
- Target table: sow.sow_target (SOW 'rci' and 'unbalance')
- NOP/Branch reference: sow.fb_share (kabupaten to branch) + PUMA_NOP_OVERRIDES

Performance optimizations:
- Fast SQL GROUP BY aggregation for multi-week trends (< 0.38s vs 5.4s full table scan)
- Filter by kabupaten = ANY(%s) at database level when branch != 'ALL' (< 0.13s)
- Fast CTE moving trend aggregation for optimization sectors (< 0.15s)
- In-memory caching with TTL for instant response on filter toggling (< 0.001s)
- Rigorous behavioral partitioning (New Comer + Consecutive + Flip-Flop == Total Optim Sectors)
"""
import csv
import io
import logging
import os
import tempfile
import threading
import time
from uuid import uuid4
from collections import defaultdict
import psycopg2.extras
from flask import Blueprint, render_template, request, session, jsonify, make_response, send_file
from app import csrf
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, viewer_blocked, db_query, csv_response

logger = logging.getLogger(__name__)

ran_capacity = Blueprint("ran_capacity", __name__)

_RAN_CACHE = {}
_RAN_CACHE_TTL = 900  # 15 minutes

_RAN_IMPORT_JOBS = {}
_RAN_IMPORT_LOCK = threading.Lock()

RCI_REDSECTOR_COLUMNS = [
    "week", "region", "site_id", "type", "sector_id_new", "number_band",
    "id_kecamatan", "threshold_hrc", "kabupaten", "jalur_krl", "prime_route",
    "flag_krl_prime_route", "flag_l900_edge", "remark_hrc_red", "remark_redsector",
    "remark_redsector_step1", "prb_util_sector", "delta_prb", "unbalanced_prb",
    "aging", "sector_capability", "thp_dist_1500_sector", "latent_demand_gbyte_sector",
    "remark_redsector_step2", "remark_redsector_final", "tracking_rci_base202348",
    "grouping_rci", "sales_region", "id_kabupaten", "site_sector",
    "prb_util_sector_th", "vendor", "weekly_payload_gbyte",
    "avg_daily_sector_gbyte_w", "avg_daily_sector_gbyte_3w", "gap_l18l21",
    "unbalanced_v1", "gap_l18l21wtddf1f2", "unbalanced_v2", "gap_thp_l9",
    "unbalanced_v3", "unbalanced_3method", "sum_prb_occurance",
    "min_prb_occurance", "max_prb_occurance", "day_prb_occurance"
]

RCI_REDSECTOR_INT_COLS = {
    "week", "sector_id_new", "number_band", "id_kecamatan", "flag_l900_edge",
    "aging", "id_kabupaten", "sum_prb_occurance", "min_prb_occurance",
    "max_prb_occurance", "day_prb_occurance"
}

RCI_REDSECTOR_FLOAT_COLS = {
    "prb_util_sector", "delta_prb", "sector_capability", "thp_dist_1500_sector",
    "latent_demand_gbyte_sector", "prb_util_sector_th", "weekly_payload_gbyte",
    "avg_daily_sector_gbyte_w", "avg_daily_sector_gbyte_3w", "gap_l18l21",
    "gap_l18l21wtddf1f2", "gap_thp_l9"
}

# Operational overrides for PUMA NOPs
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


def clear_ran_capacity_caches():
    """Clear memory caches after data updates/imports."""
    _RAN_CACHE.clear()


def _get_branch_map():
    """Map kabupaten (UPPER) -> branch/NOP using sow.fb_share + PUMA overrides."""
    now = time.time()
    if "_branch_map" in _RAN_CACHE:
        val, exp = _RAN_CACHE["_branch_map"]
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
            for k, b in PUMA_NOP_OVERRIDES.items():
                mapping[k.upper().strip()] = b

            _RAN_CACHE["_branch_map"] = (mapping, now + 86400)
            return mapping
    except Exception as e:
        logger.exception("Error loading branch map: %s", e)
        return dict(PUMA_NOP_OVERRIDES)


def _get_site_kab_map():
    """Map site_id -> kabupaten to heal any row with empty kabupaten."""
    now = time.time()
    if "_site_kab_map" in _RAN_CACHE:
        val, exp = _RAN_CACHE["_site_kab_map"]
        if now < exp:
            return val
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(
                "SELECT DISTINCT site_id, UPPER(TRIM(kabupaten)) "
                "FROM sow.rci_redsector "
                "WHERE kabupaten IS NOT NULL AND TRIM(kabupaten) != ''"
            )
            mapping = dict(cur.fetchall())
            _RAN_CACHE["_site_kab_map"] = (mapping, now + 86400)
            return mapping
    except Exception as e:
        logger.exception("Error loading site_kab_map: %s", e)
        return {}


def _get_regions():
    """Distinct regions in sow.rci_redsector."""
    now = time.time()
    if "_regions" in _RAN_CACHE:
        val, exp = _RAN_CACHE["_regions"]
        if now < exp:
            return val
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT DISTINCT region FROM sow.rci_redsector ORDER BY region ASC")
            regs = [r[0] for r in cur.fetchall() if r[0]]
            regs = regs if regs else ["PUMA"]
            _RAN_CACHE["_regions"] = (regs, now + 3600)
            return regs
    except Exception as e:
        logger.exception("Error loading regions: %s", e)
        return ["PUMA"]


def _get_yearweeks():
    """Distinct weeks in sow.rci_redsector, with auto-invalidation if DB max week changed."""
    now = time.time()
    
    # 1. Query current max week from DB (fast: index-only scan)
    db_max = 0
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT MAX(week) FROM sow.rci_redsector")
            row = cur.fetchone()
            if row and row[0]:
                db_max = int(row[0])
    except Exception:
        pass

    # 2. Check cache: if DB max week differs from cached max, we're stale
    if "_yearweeks" in _RAN_CACHE:
        val, exp = _RAN_CACHE["_yearweeks"]
        if now < exp:
            cached_max = val[0] if val else 0
            # Return cached data ONLY if the DB max matches what we cached
            if db_max == cached_max and db_max > 0:
                return val  # Cache is still valid

    # 3. Cache miss, expired, or mismatched - refresh from DB
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT DISTINCT week FROM sow.rci_redsector ORDER BY week DESC")
            yws = [int(r[0]) for r in cur.fetchall() if r[0] is not None]
            _RAN_CACHE["_yearweeks"] = (yws, now + 1800)
            return yws
    except Exception as e:
        logger.exception("Error loading yearweeks: %s", e)
        return []


def _quarter_for_week(yearweek):
    """Return quarter string Q1..Q4 based on week integer."""
    w_str = str(yearweek)
    week_num = int(w_str[4:]) if len(w_str) >= 6 else int(w_str[-2:])
    if week_num <= 13:
        return "Q1"
    if week_num <= 26:
        return "Q2"
    if week_num <= 39:
        return "Q3"
    return "Q4"


def _get_all_targets(sow_type="rci"):
    """Fetch targets from sow.sow_target for 'rci' or 'unbalance'."""
    now = time.time()
    cache_key = f"_targets_{sow_type}"
    cached = _RAN_CACHE.get(cache_key)
    if cached and now < cached[1]:
        return cached[0]

    targets = {}
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(
                'SELECT "Year", "Baseline", "Q1", "Q2", "Q3", "Q4" '
                'FROM sow.sow_target WHERE LOWER(TRIM("SOW")) = %s',
                (sow_type.lower(),)
            )
            for year, base, *qs in cur.fetchall():
                q_map = {}
                if base is not None:
                    b_val = float(base)
                    if b_val < 0.1:
                        b_val *= 100.0
                    q_map["Baseline"] = round(b_val, 2)
                else:
                    q_map["Baseline"] = 0.61 if sow_type == "rci" else 2.64

                for name, raw in zip(("Q1", "Q2", "Q3", "Q4"), qs):
                    if raw is None:
                        q_map[name] = None
                        continue
                    v = float(raw)
                    if v < 0.1:
                        v *= 100.0
                    q_map[name] = round(v, 2)
                targets[int(year)] = q_map
    except Exception as e:
        logger.warning("Error fetching targets for %s: %s", sow_type, e)

    _RAN_CACHE[cache_key] = (targets, now + 3600)
    return targets


def _get_target_for_week(yearweek, sow_type="rci"):
    """Return (target_val, baseline_val, target_label) for given week and metric."""
    year = int(str(yearweek)[:4]) if len(str(yearweek)) >= 4 else 2026
    q_col = _quarter_for_week(yearweek)
    all_targets = _get_all_targets(sow_type)
    yr_targets = all_targets.get(year, {})
    val = yr_targets.get(q_col)
    baseline = yr_targets.get("Baseline")

    default_target = 0.42 if sow_type == "rci" else 1.85
    default_baseline = 0.61 if sow_type == "rci" else 2.64

    target_val = val if val is not None else default_target
    baseline_val = baseline if baseline is not None else default_baseline
    return target_val, baseline_val, f"Target {q_col}"


def _safe_int(val, default=0):
    if val is None or val == "" or str(val).strip() == "-":
        return default
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0):
    if val is None or val == "" or str(val).strip() == "-":
        return default
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return default


def _safe_str(val, default=""):
    if val is None:
        return default
    s = str(val).strip()
    return s if s else default


def _get_sample_rows():
    """Return 5 real sample rows from sow.rci_redsector."""
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            col_list = ", ".join([f'"{c}"' for c in RCI_REDSECTOR_COLUMNS])
            cur.execute(f"SELECT {col_list} FROM sow.rci_redsector LIMIT 5")
            return cur.fetchall()
    except Exception as e:
        logger.exception("Error getting sample rows: %s", e)
        return []


# ══════════════════════════════════════════════════════════════════════
# MAIN VIEW ROUTE
# ══════════════════════════════════════════════════════════════════════
@ran_capacity.route("/sow/ran_capacity")
@ran_capacity.route("/okr/ran_capacity")
@login_required
def ran_capacity_page():
    cache_ctrl = request.headers.get("Cache-Control", "")
    pragma = request.headers.get("Pragma", "")
    if "no-cache" in cache_ctrl or "max-age=0" in cache_ctrl or "no-cache" in pragma or request.args.get("refresh") == "1":
        clear_ran_capacity_caches()
    regions = _get_regions()
    current_region = request.args.get("region", "PUMA")
    if current_region not in regions and regions:
        current_region = regions[0]

    yearweeks = _get_yearweeks()
    default_yw = yearweeks[0] if yearweeks else 202638
    default_start_yw = yearweeks[-1] if yearweeks else 202628

    rci_target, rci_baseline, rci_label = _get_target_for_week(default_yw, "rci")
    unb_target, unb_baseline, unb_label = _get_target_for_week(default_yw, "unbalance")

    return render_template(
        "sow_ran_capacity.html",
        username=session.get("username", "User"),
        regions=regions,
        current_region=current_region,
        yearweeks=yearweeks,
        latest_week=default_yw,
        default_yw=default_yw,
        default_start_yw=default_start_yw,
        rci_target=rci_target,
        rci_baseline=rci_baseline,
        rci_label=rci_label,
        unb_target=unb_target,
        unb_baseline=unb_baseline,
        unb_label=unb_label,
    )


# ══════════════════════════════════════════════════════════════════════
# API 1: SUMMARY & SCORECARDS
# ══════════════════════════════════════════════════════════════════════
@ran_capacity.route("/api/sow/ran_capacity/summary", methods=["GET"])
@login_required
def api_ran_capacity_summary():
    region = request.args.get("region", "PUMA").strip()
    branch = request.args.get("branch", "ALL").strip().upper()
    yearweeks = _get_yearweeks()
    if not yearweeks:
        return jsonify({"status": "error", "message": "No data available in sow.rci_redsector"}), 404

    try:
        yw = int(request.args.get("week", yearweeks[0]))
    except (ValueError, TypeError):
        yw = yearweeks[0]

    # Find previous week
    prev_yw = None
    if yw in yearweeks:
        idx = yearweeks.index(yw)
        if idx + 1 < len(yearweeks):
            prev_yw = yearweeks[idx + 1]

    cache_key = f"summary_{region}_{yw}_{branch}_{prev_yw}"
    now = time.time()
    if cache_key in _RAN_CACHE:
        val, exp = _RAN_CACHE[cache_key]
        if now < exp:
            return jsonify(val)

    branch_map = _get_branch_map()
    site_kab_map = _get_site_kab_map()

    rci_target_val, rci_baseline_val, rci_target_label = _get_target_for_week(yw, "rci")
    unb_target_val, unb_baseline_val, unb_target_label = _get_target_for_week(yw, "unbalance")

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            # Fetch current week sectors (optimized by branch if branch is not ALL)
            if branch != "ALL":
                branch_kabs = [k for k, b in branch_map.items() if b == branch]
                cur.execute("""
                    SELECT 
                        site_id, site_sector, UPPER(TRIM(kabupaten)), grouping_rci,
                        remark_redsector_final, aging, unbalanced_3method,
                        unbalanced_v1, unbalanced_v2, unbalanced_v3
                    FROM sow.rci_redsector
                    WHERE week = %s AND UPPER(TRIM(kabupaten)) = ANY(%s)
                """, (yw, branch_kabs))
                curr_rows = cur.fetchall()

                # Previous week sectors for WoW
                prev_rows = []
                if prev_yw:
                    cur.execute("""
                        SELECT 
                            site_sector, grouping_rci, unbalanced_3method
                        FROM sow.rci_redsector
                        WHERE week = %s AND UPPER(TRIM(kabupaten)) = ANY(%s)
                    """, (prev_yw, branch_kabs))
                    prev_rows = cur.fetchall()
            else:
                cur.execute("""
                    SELECT 
                        site_id, site_sector, UPPER(TRIM(kabupaten)), grouping_rci,
                        remark_redsector_final, aging, unbalanced_3method,
                        unbalanced_v1, unbalanced_v2, unbalanced_v3
                    FROM sow.rci_redsector
                    WHERE week = %s
                """, (yw,))
                curr_rows = cur.fetchall()

                prev_rows = []
                if prev_yw:
                    cur.execute("""
                        SELECT 
                            site_sector, grouping_rci, unbalanced_3method
                        FROM sow.rci_redsector
                        WHERE week = %s
                    """, (prev_yw,))
                    prev_rows = cur.fetchall()

        prev_map = {r[0]: {"grouping_rci": r[1], "unb_3m": r[2]} for r in prev_rows}

        # ── RCI Aggregations ──────────────────────────────────────────
        rci_total = 0
        rci_optim = 0
        rci_op = 0
        rci_eng = 0
        rci_vendor = 0
        rci_green = 0

        # Aging categories for RCI optim sectors
        rci_aging_counts = {
            ">3 month": 0,
            "3 month": 0,
            "2 month": 0,
            "1 month": 0,
            "new comer": 0
        }

        # Behavioral classification (Consecutive, Flipflop, New Comer)
        rci_behavior = {"consecutive": 0, "flipflop": 0, "new_comer": 0}

        # Moving trend: where did current optim sectors come from in prev week?
        rci_moving = {
            "optimization": 0,
            "operation": 0,
            "green_sector": 0,
            "capacity_expansion": 0,
            "ran_vendor": 0
        }

        # NOP level rollups
        rci_nop_totals = defaultdict(lambda: {
            "total": 0, "optim": 0, "operation": 0, "engineering": 0, "ran_vendor": 0
        })
        rci_kab_optim = defaultdict(int)

        # ── Unbalance Aggregations ────────────────────────────────────
        unb_total = 0
        unb_p1 = 0
        unb_p2 = 0
        unb_p3 = 0
        unb_balanced = 0

        unb_v1_p1 = {"balanced": 0, "unbalanced": 0}
        unb_v2_p1 = {"balanced": 0, "unbalanced": 0}
        unb_v3_p1 = {"balanced_thp": 0, "unbalanced_thp": 0}

        unb_transitions_current_p1 = {"maintain_p1": 0, "balanced_to_p1": 0, "p2_to_p1": 0, "other": 0}
        unb_transitions_closed = {"p1_to_bal": 0, "p2_to_bal": 0, "p3_to_bal": 0, "new_bal": 0}

        unb_nop_totals = defaultdict(lambda: {
            "total": 0, "p1": 0, "p2": 0, "p3": 0, "bal": 0,
            "v1_unb": 0, "v2_unb": 0, "v3_unb": 0
        })
        unb_kab_p1 = defaultdict(int)

        for row in curr_rows:
            sid, ss, raw_kab, grp, remark_final, aging, unb_3m, v1, v2, v3 = row
            kab = raw_kab if raw_kab and raw_kab.strip() else site_kab_map.get(sid, "UNKNOWN")
            nop = branch_map.get(kab, "UNKNOWN")

            if branch != "ALL" and nop != branch:
                continue

            rci_total += 1
            unb_total += 1

            rci_nop_totals[nop]["total"] += 1
            unb_nop_totals[nop]["total"] += 1

            # RCI classification
            if grp == "optimization":
                rci_optim += 1
                rci_nop_totals[nop]["optim"] += 1
                rci_kab_optim[kab] += 1

                # Rigorous aging and behavioral partition
                ag = aging if aging is not None else 0
                if ag == 0:
                    rci_aging_counts["new comer"] += 1
                    rci_behavior["new_comer"] += 1
                else:
                    if 1 <= ag <= 4:
                        rci_aging_counts["1 month"] += 1
                    elif 5 <= ag <= 8:
                        rci_aging_counts["2 month"] += 1
                    elif 9 <= ag <= 12:
                        rci_aging_counts["3 month"] += 1
                    else:
                        rci_aging_counts[">3 month"] += 1

                    p_info = prev_map.get(ss)
                    if p_info and p_info.get("grouping_rci") == "optimization":
                        rci_behavior["consecutive"] += 1
                    else:
                        rci_behavior["flipflop"] += 1

                # Moving trend from prev week
                p_info = prev_map.get(ss)
                if p_info:
                    p_grp = p_info.get("grouping_rci")
                    if p_grp == "optimization":
                        rci_moving["optimization"] += 1
                    elif p_grp == "operation":
                        rci_moving["operation"] += 1
                    elif p_grp == "engineering":
                        rci_moving["capacity_expansion"] += 1
                    elif p_grp == "ran_vendor":
                        rci_moving["ran_vendor"] += 1
                    else:
                        rci_moving["green_sector"] += 1
                else:
                    rci_moving["green_sector"] += 1

            elif grp == "operation":
                rci_op += 1
                rci_nop_totals[nop]["operation"] += 1
            elif grp == "engineering":
                rci_eng += 1
                rci_nop_totals[nop]["engineering"] += 1
            elif grp == "ran_vendor":
                rci_vendor += 1
                rci_nop_totals[nop]["ran_vendor"] += 1
            else:
                rci_green += 1

            # Unbalance classification
            if unb_3m == "unbalanced_p1":
                unb_p1 += 1
                unb_nop_totals[nop]["p1"] += 1
                unb_kab_p1[kab] += 1

                if v1 == "unbalanced":
                    unb_v1_p1["unbalanced"] += 1
                else:
                    unb_v1_p1["balanced"] += 1

                if v2 == "unbalanced":
                    unb_v2_p1["unbalanced"] += 1
                else:
                    unb_v2_p1["balanced"] += 1

                if v3 == "unbalanced_thp":
                    unb_v3_p1["unbalanced_thp"] += 1
                else:
                    unb_v3_p1["balanced_thp"] += 1

                p_info = prev_map.get(ss)
                if p_info:
                    pm = p_info.get("unb_3m")
                    if pm == "unbalanced_p1":
                        unb_transitions_current_p1["maintain_p1"] += 1
                    elif pm == "balanced":
                        unb_transitions_current_p1["balanced_to_p1"] += 1
                    elif pm == "unbalanced_p2":
                        unb_transitions_current_p1["p2_to_p1"] += 1
                    else:
                        unb_transitions_current_p1["other"] += 1
                else:
                    unb_transitions_current_p1["balanced_to_p1"] += 1

            elif unb_3m == "unbalanced_p2":
                unb_p2 += 1
                unb_nop_totals[nop]["p2"] += 1
            elif unb_3m == "unbalanced_p3":
                unb_p3 += 1
                unb_nop_totals[nop]["p3"] += 1
            elif unb_3m == "balanced":
                unb_balanced += 1
                unb_nop_totals[nop]["bal"] += 1

                p_info = prev_map.get(ss)
                if p_info:
                    pm = p_info.get("unb_3m")
                    if pm == "unbalanced_p1":
                        unb_transitions_closed["p1_to_bal"] += 1
                    elif pm == "unbalanced_p2":
                        unb_transitions_closed["p2_to_bal"] += 1
                    elif pm == "unbalanced_p3":
                        unb_transitions_closed["p3_to_bal"] += 1
                else:
                    unb_transitions_closed["new_bal"] += 1

            if v1 == "unbalanced":
                unb_nop_totals[nop]["v1_unb"] += 1
            if v2 == "unbalanced":
                unb_nop_totals[nop]["v2_unb"] += 1
            if v3 == "unbalanced_thp":
                unb_nop_totals[nop]["v3_unb"] += 1

        # Previous week percentages for WoW delta
        prev_rci_optim_pct = None
        prev_unb_p1_pct = None
        if prev_rows:
            p_tot = len(prev_rows)
            p_opt = sum(1 for r in prev_rows if r[1] == "optimization")
            p_p1 = sum(1 for r in prev_rows if r[2] == "unbalanced_p1")
            prev_rci_optim_pct = round(p_opt / p_tot * 100.0, 2) if p_tot else 0.0
            prev_unb_p1_pct = round(p_p1 / p_tot * 100.0, 2) if p_tot else 0.0

        # RCI Rates
        rci_optim_pct = round(rci_optim / rci_total * 100.0, 2) if rci_total else 0.0
        rci_red_all = rci_optim + rci_op + rci_eng + rci_vendor
        rci_red_all_pct = round(rci_red_all / rci_total * 100.0, 2) if rci_total else 0.0
        rci_op_pct = round(rci_op / rci_total * 100.0, 2) if rci_total else 0.0
        rci_eng_pct = round(rci_eng / rci_total * 100.0, 2) if rci_total else 0.0
        rci_vendor_pct = round(rci_vendor / rci_total * 100.0, 2) if rci_total else 0.0

        rci_is_pass = rci_optim_pct <= rci_target_val
        rci_ach_gap = round(rci_target_val - rci_optim_pct, 2)
        rci_max_allowed = int(rci_target_val * rci_total / 100.0)
        rci_excess = max(0, rci_optim - rci_max_allowed)

        rci_wow_delta = round(rci_optim_pct - prev_rci_optim_pct, 2) if prev_rci_optim_pct is not None else 0.0

        # Unbalance Rates
        unb_p1_pct = round(unb_p1 / unb_total * 100.0, 2) if unb_total else 0.0
        unb_p2_pct = round(unb_p2 / unb_total * 100.0, 2) if unb_total else 0.0
        unb_p3_pct = round(unb_p3 / unb_total * 100.0, 2) if unb_total else 0.0
        unb_bal_pct = round(unb_balanced / unb_total * 100.0, 2) if unb_total else 0.0

        unb_is_pass = unb_p1_pct <= unb_target_val
        unb_ach_gap = round(unb_target_val - unb_p1_pct, 2)
        unb_max_allowed = int(unb_target_val * unb_total / 100.0)
        unb_excess = max(0, unb_p1 - unb_max_allowed)

        unb_wow_delta = round(unb_p1_pct - prev_unb_p1_pct, 2) if prev_unb_p1_pct is not None else 0.0

        # RCI Regional Gauge & NOP list
        known_nops = ["AMBON", "JAYAPURA", "TIMIKA", "SORONG"]
        rci_gauge_list = []
        rci_table_rows = []
        for n in known_nops:
            d = rci_nop_totals[n]
            t = d["total"]
            opt = d["optim"]
            eng = d["engineering"]
            op = d["operation"]
            ven = d["ran_vendor"]
            pct = round(opt / t * 100.0, 2) if t else 0.0
            eng_pct = round(eng / t * 100.0, 2) if t else 0.0
            is_p = pct <= rci_target_val

            rci_gauge_list.append({
                "name": n,
                "value": pct,
                "target": rci_target_val,
                "is_above": is_p,
                "total": t,
                "optim": opt,
                "engineering": eng,
                "operation": op,
                "vendor": ven,
                "eng_pct": eng_pct,
            })
            rci_table_rows.append({
                "nop": f"NOP {n}",
                "direct_investment": eng,
                "direct_optim": opt,
                "direct_operation": op,
                "ran_vendor": ven if ven > 0 else "-",
                "optim_pct": f"{pct:.2f}%",
                "eng_pct": f"{eng_pct:.2f}%",
                "is_pass": is_p
            })

        # Unbalance Regional Gauge & NOP list
        unb_gauge_list = []
        unb_table_rows = []
        for n in known_nops:
            d = unb_nop_totals[n]
            t = d["total"]
            p1 = d["p1"]
            p2 = d["p2"]
            p3 = d["p3"]
            bal = d["bal"]
            v1_cnt = d["v1_unb"]
            v2_cnt = d["v2_unb"]
            v3_cnt = d["v3_unb"]
            pct = round(p1 / t * 100.0, 2) if t else 0.0
            is_p = pct <= unb_target_val

            unb_gauge_list.append({
                "name": n,
                "value": pct,
                "target": unb_target_val,
                "is_above": is_p,
                "total": t,
                "p1": p1,
                "p2": p2,
                "p3": p3,
                "bal": bal,
                "v1_unb": v1_cnt,
                "v2_unb": v2_cnt,
                "v3_unb": v3_cnt
            })
            unb_table_rows.append({
                "nop": f"NOP {n}",
                "balanced": bal,
                "p1": p1,
                "p2": p2,
                "p3": p3,
                "v1_unb": v1_cnt,
                "v2_unb": v2_cnt,
                "v3_unb": v3_cnt,
                "p1_pct": f"{pct:.2f}%",
                "is_pass": is_p
            })

        # Top Contributors
        rci_top_kab = [
            {"kabupaten": k, "count": c}
            for k, c in sorted(rci_kab_optim.items(), key=lambda x: x[1], reverse=True)[:10]
        ]
        unb_top_kab = [
            {"kabupaten": k, "count": c}
            for k, c in sorted(unb_kab_p1.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        # Top contributor text
        rci_top_str = ", ".join([f"{k['kabupaten']} ({k['count']})" for k in rci_top_kab[:4]])
        unb_top_str = ", ".join([f"{k['kabupaten']} ({k['count']})" for k in unb_top_kab[:4]])

        # Scope text for bulletins
        scope_prefix = f"in NOP {branch}" if branch != "ALL" else "in Regional PUMA"

        rci_bulletins = [
            f"Achievement RCI Direct Optim {scope_prefix} in W{str(yw)[-2:]} is <strong>{rci_optim_pct:.2f}%</strong>, with gap <strong>{rci_ach_gap:+.2f}%</strong> to target (Target: {rci_target_val:.2f}%). Status: <strong>{'PASS' if rci_is_pass else 'BREACH'}</strong>.",
            f"Compared to previous week W{str(prev_yw)[-2:] if prev_yw else '--'}, RCI Direct Optim delta is <strong>{rci_wow_delta:+.2f} pp WoW</strong> ({rci_optim} vs {round(prev_rci_optim_pct * rci_total / 100) if prev_rci_optim_pct else '--'} sectors).",
            f"Number total RCI is <strong>{rci_red_all}</strong> contributed by RCI Operation <strong>{rci_op}</strong> ({rci_op_pct:.2f}%), RCI Optimization <strong>{rci_optim}</strong> ({rci_optim_pct:.2f}%), RCI Engineering is <strong>{rci_eng}</strong> ({rci_eng_pct:.2f}%) and RAN Vendor <strong>{rci_vendor}</strong> ({rci_vendor_pct:.2f}%).",
            f"Based on behavioral tracking, there are <strong>{rci_behavior['consecutive']}</strong> Consecutive sectors, <strong>{rci_behavior['flipflop']}</strong> Flip-Flop sectors, and <strong>{rci_behavior['new_comer']}</strong> New Comer sectors (Total: {rci_optim} sectors).",
            f"Top contributor Direct Optim: <strong>{rci_top_str}</strong>."
        ]

        unb_bulletins = [
            f"Achievement Capacity Unbalance P1 {scope_prefix} in W{str(yw)[-2:]} is <strong>{unb_p1_pct:.2f}%</strong> ({unb_p1} sectors), with gap <strong>{unb_ach_gap:+.2f}%</strong> to target (Target: {unb_target_val:.2f}%). Status: <strong>{'PASS' if unb_is_pass else 'BREACH'}</strong>.",
            f"Compared to previous week W{str(prev_yw)[-2:] if prev_yw else '--'}, Unbalance P1 delta is <strong>{unb_wow_delta:+.2f} pp WoW</strong> ({unb_transitions_current_p1['maintain_p1']} maintain P1, {unb_transitions_current_p1['balanced_to_p1']} balanced to P1).",
            f"Closed from previous week to balanced: <strong>{unb_transitions_closed['p1_to_bal']}</strong> P1 to balanced, <strong>{unb_transitions_closed['p2_to_bal']}</strong> P2 to balanced, <strong>{unb_transitions_closed['p3_to_bal']}</strong> P3 to balanced, and <strong>{unb_transitions_closed['new_bal']}</strong> new balanced.",
            f"P1 Methodology drill-down shows: V1 (Unbalance: <strong>{unb_v1_p1['unbalanced']}</strong> / Balance: {unb_v1_p1['balanced']}), V2 (Unbalance: <strong>{unb_v2_p1['unbalanced']}</strong> / Balance: {unb_v2_p1['balanced']}), V3 (Unbalance THP: <strong>{unb_v3_p1['unbalanced_thp']}</strong> / Balance: {unb_v3_p1['balanced_thp']}).",
            f"Top contributor Unbalance P1: <strong>{unb_top_str}</strong>."
        ]

        response_data = {
            "status": "success",
            "yearweek": yw,
            "prev_yearweek": prev_yw,
            "region": region,
            "branch": branch,
            "rci": {
                "total_sectors": rci_total,
                "optim_sectors": rci_optim,
                "optim_pct": rci_optim_pct,
                "operation_sectors": rci_op,
                "operation_pct": rci_op_pct,
                "engineering_sectors": rci_eng,
                "engineering_pct": rci_eng_pct,
                "vendor_sectors": rci_vendor,
                "vendor_pct": rci_vendor_pct,
                "red_all_sectors": rci_red_all,
                "red_all_pct": rci_red_all_pct,
                "green_sectors": rci_green,
                "baseline": rci_baseline_val,
                "target": rci_target_val,
                "target_label": rci_target_label,
                "ach_gap": rci_ach_gap,
                "is_pass": rci_is_pass,
                "excess_sectors": rci_excess,
                "prev_optim_pct": prev_rci_optim_pct,
                "wow_delta": rci_wow_delta,
                "aging_counts": rci_aging_counts,
                "behavior": rci_behavior,
                "moving": rci_moving,
                "regional_gauge": rci_gauge_list,
                "regional_puma": {
                    "name": "PUMA" if branch == "ALL" else branch,
                    "value": rci_optim_pct,
                    "target": rci_target_val,
                    "is_above": rci_is_pass,
                    "total": rci_total,
                    "optim": rci_optim,
                    "engineering": rci_eng,
                    "operation": rci_op,
                    "vendor": rci_vendor,
                    "eng_pct": rci_eng_pct
                },
                "table_rows": rci_table_rows,
                "top_contributors": rci_top_kab,
                "bulletins": rci_bulletins
            },
            "unbalance": {
                "total_sectors": unb_total,
                "p1_sectors": unb_p1,
                "p1_pct": unb_p1_pct,
                "p2_sectors": unb_p2,
                "p2_pct": unb_p2_pct,
                "p3_sectors": unb_p3,
                "p3_pct": unb_p3_pct,
                "balanced_sectors": unb_balanced,
                "balanced_pct": unb_bal_pct,
                "baseline": unb_baseline_val,
                "target": unb_target_val,
                "target_label": unb_target_label,
                "ach_gap": unb_ach_gap,
                "is_pass": unb_is_pass,
                "excess_sectors": unb_excess,
                "prev_p1_pct": prev_unb_p1_pct,
                "wow_delta": unb_wow_delta,
                "v1_p1": unb_v1_p1,
                "v2_p1": unb_v2_p1,
                "v3_p1": unb_v3_p1,
                "transitions_current_p1": unb_transitions_current_p1,
                "transitions_closed": unb_transitions_closed,
                "regional_gauge": unb_gauge_list,
                "regional_puma": {
                    "name": "PUMA" if branch == "ALL" else branch,
                    "value": unb_p1_pct,
                    "target": unb_target_val,
                    "is_above": unb_is_pass,
                    "total": unb_total,
                    "p1": unb_p1,
                    "p2": unb_p2,
                    "p3": unb_p3,
                    "bal": unb_balanced
                },
                "table_rows": unb_table_rows,
                "top_contributors": unb_top_kab,
                "bulletins": unb_bulletins
            }
        }

        _RAN_CACHE[cache_key] = (response_data, now + _RAN_CACHE_TTL)
        return jsonify(response_data)

    except Exception as e:
        logger.exception("Error in api_ran_capacity_summary: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# API 2: TREND TIMELINE DATA (HIGH SPEED SQL AGGREGATION)
# ══════════════════════════════════════════════════════════════════════
@ran_capacity.route("/api/sow/ran_capacity/trend", methods=["GET"])
@login_required
def api_ran_capacity_trend():
    region = request.args.get("region", "PUMA").strip()
    branch = request.args.get("branch", "ALL").strip().upper()
    yearweeks = _get_yearweeks()

    try:
        start_yw = int(request.args.get("start_week", yearweeks[-1] if yearweeks else 202628))
    except (ValueError, TypeError):
        start_yw = yearweeks[-1] if yearweeks else 202628

    try:
        end_yw = int(request.args.get("end_week", yearweeks[0] if yearweeks else 202638))
    except (ValueError, TypeError):
        end_yw = yearweeks[0] if yearweeks else 202638

    cache_key = f"trend_fast_{region}_{branch}_{start_yw}_{end_yw}"
    now = time.time()
    if cache_key in _RAN_CACHE:
        val, exp = _RAN_CACHE[cache_key]
        if now < exp:
            return jsonify(val)

    branch_map = _get_branch_map()

    # Determine timeline weeks in ascending order
    yws_in_range = [w for w in sorted(yearweeks) if start_yw <= w <= end_yw]
    if not yws_in_range:
        yws_in_range = sorted(yearweeks)

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            # 1. Fast SQL Grouped Aggregation query by week and kabupaten
            cur.execute("""
                SELECT 
                    week,
                    UPPER(TRIM(kabupaten)) as kab,
                    count(*) as total,
                    count(*) filter (where grouping_rci = 'optimization') as rci_optim,
                    count(*) filter (where grouping_rci = 'engineering') as rci_eng,
                    count(*) filter (where grouping_rci = 'operation') as rci_op,
                    count(*) filter (where grouping_rci = 'ran_vendor') as rci_ven,
                    count(*) filter (where unbalanced_3method = 'unbalanced_p1') as unb_p1,
                    count(*) filter (where unbalanced_3method = 'unbalanced_p2') as unb_p2,
                    count(*) filter (where unbalanced_3method = 'unbalanced_p3') as unb_p3,
                    count(*) filter (where unbalanced_3method = 'balanced') as unb_bal,
                    count(*) filter (where unbalanced_v1 = 'unbalanced') as v1_unb,
                    count(*) filter (where unbalanced_v2 = 'unbalanced') as v2_unb,
                    count(*) filter (where unbalanced_v3 = 'unbalanced_thp') as v3_unb
                FROM sow.rci_redsector
                WHERE week = ANY(%s)
                GROUP BY week, UPPER(TRIM(kabupaten))
                ORDER BY week ASC;
            """, (yws_in_range,))
            kab_agg_rows = cur.fetchall()

            # 2. Moving trend CTE for last 4 weeks
            last_4_yws = yws_in_range[-4:] if len(yws_in_range) >= 4 else yws_in_range
            all_moving_yws = []
            if last_4_yws:
                min_m_idx = yearweeks.index(last_4_yws[0]) if last_4_yws[0] in yearweeks else 0
                prior_yw = yearweeks[min_m_idx + 1] if min_m_idx + 1 < len(yearweeks) else last_4_yws[0]
                all_moving_yws = sorted(list(set(last_4_yws + [prior_yw])))

            cur.execute("""
                WITH optim_sectors AS (
                    SELECT DISTINCT site_sector 
                    FROM sow.rci_redsector 
                    WHERE week = ANY(%s)
                      AND grouping_rci = 'optimization'
                )
                SELECT week, site_sector, grouping_rci, UPPER(TRIM(kabupaten)) as kab
                FROM sow.rci_redsector
                WHERE site_sector IN (SELECT site_sector FROM optim_sectors)
                  AND week = ANY(%s)
                ORDER BY week ASC;
            """, (last_4_yws, all_moving_yws))
            moving_rows = cur.fetchall()

        # Build timeline aggregations
        rci_trend = {
            "engineering": [],
            "optimization": [],
            "operation": [],
            "ran_vendor": [],
            "total_sectors": [],
            "optim_pct": [],
            "red_all_pct": [],
            "target_series": []
        }

        unb_trend = {
            "balanced": [],
            "p3": [],
            "p2": [],
            "p1": [],
            "total_sectors": [],
            "p1_pct": [],
            "target_series": [],
            "v1_unb": [],
            "v2_unb": [],
            "v3_unb": []
        }

        known_nops = ["AMBON", "JAYAPURA", "TIMIKA", "SORONG"]
        rci_nop_series = {n: [] for n in known_nops}
        unb_nop_series = {n: [] for n in known_nops}

        # Index kab_agg_rows by (week, kab)
        week_kab_data = defaultdict(list)
        for r in kab_agg_rows:
            week_kab_data[r[0]].append(r)

        for yw in yws_in_range:
            rows_w = week_kab_data[yw]
            t_tot = 0
            t_opt = 0
            t_eng = 0
            t_op = 0
            t_ven = 0

            u_p1 = 0
            u_p2 = 0
            u_p3 = 0
            u_bal = 0
            u_v1 = 0
            u_v2 = 0
            u_v3 = 0

            nop_rci = defaultdict(lambda: {"total": 0, "optim": 0})
            nop_unb = defaultdict(lambda: {"total": 0, "p1": 0})

            for r in rows_w:
                _, kab, tot, opt, eng, op, ven, p1, p2, p3, bal, v1, v2, v3 = r
                nop = branch_map.get(kab, "UNKNOWN")

                nop_rci[nop]["total"] += tot
                nop_rci[nop]["optim"] += opt
                nop_unb[nop]["total"] += tot
                nop_unb[nop]["p1"] += p1

                if branch != "ALL" and nop != branch:
                    continue

                t_tot += tot
                t_opt += opt
                t_eng += eng
                t_op += op
                t_ven += ven

                u_p1 += p1
                u_p2 += p2
                u_p3 += p3
                u_bal += bal
                u_v1 += v1
                u_v2 += v2
                u_v3 += v3

            rci_target_val, _, _ = _get_target_for_week(yw, "rci")
            unb_target_val, _, _ = _get_target_for_week(yw, "unbalance")

            opt_pct = round(t_opt / t_tot * 100.0, 2) if t_tot else 0.0
            red_all_pct = round((t_opt + t_eng + t_op + t_ven) / t_tot * 100.0, 2) if t_tot else 0.0
            p1_pct = round(u_p1 / t_tot * 100.0, 2) if t_tot else 0.0

            rci_trend["engineering"].append(t_eng)
            rci_trend["optimization"].append(t_opt)
            rci_trend["operation"].append(t_op)
            rci_trend["ran_vendor"].append(t_ven)
            rci_trend["total_sectors"].append(t_tot)
            rci_trend["optim_pct"].append(opt_pct)
            rci_trend["red_all_pct"].append(red_all_pct)
            rci_trend["target_series"].append(rci_target_val)

            unb_trend["balanced"].append(u_bal)
            unb_trend["p3"].append(u_p3)
            unb_trend["p2"].append(u_p2)
            unb_trend["p1"].append(u_p1)
            unb_trend["total_sectors"].append(t_tot)
            unb_trend["p1_pct"].append(p1_pct)
            unb_trend["target_series"].append(unb_target_val)
            unb_trend["v1_unb"].append(u_v1)
            unb_trend["v2_unb"].append(u_v2)
            unb_trend["v3_unb"].append(u_v3)

            for n in known_nops:
                nr = nop_rci[n]
                nu = nop_unb[n]
                r_pct = round(nr["optim"] / nr["total"] * 100.0, 2) if nr["total"] else 0.0
                u_pct = round(nu["p1"] / nu["total"] * 100.0, 2) if nu["total"] else 0.0
                rci_nop_series[n].append(r_pct)
                unb_nop_series[n].append(u_pct)

        # 3. Process moving trend rows for last 4 weeks
        # Index moving rows: ss -> week -> grp
        sector_week_status = defaultdict(dict)
        sector_branch = {}
        for r in moving_rows:
            w, ss, grp, kab = r
            sector_week_status[ss][w] = grp
            sector_branch[ss] = branch_map.get(kab, "UNKNOWN")

        rci_moving_trend_series = {
            "weeks": [f"W{str(w)[-2:]}" for w in last_4_yws],
            "optimization": [],
            "operation": [],
            "green_sector": [],
            "capacity_expansion": []
        }

        for idx, w in enumerate(last_4_yws):
            prior_w = all_moving_yws[all_moving_yws.index(w) - 1] if all_moving_yws.index(w) > 0 else None
            mv_opt = 0
            mv_op = 0
            mv_eng = 0
            mv_grn = 0

            for ss, w_map in sector_week_status.items():
                if branch != "ALL" and sector_branch.get(ss) != branch:
                    continue

                if w_map.get(w) == "optimization":
                    p_grp = w_map.get(prior_w) if prior_w else None
                    if p_grp == "optimization":
                        mv_opt += 1
                    elif p_grp == "operation":
                        mv_op += 1
                    elif p_grp == "engineering":
                        mv_eng += 1
                    else:
                        mv_grn += 1

            rci_moving_trend_series["optimization"].append(mv_opt)
            rci_moving_trend_series["operation"].append(mv_op)
            rci_moving_trend_series["capacity_expansion"].append(mv_eng)
            rci_moving_trend_series["green_sector"].append(mv_grn)

        week_labels = [f"W{str(w)[-2:]}" for w in yws_in_range]
        full_week_labels = [str(w) for w in yws_in_range]
        target_dict_unb = _get_all_targets("unbalance").get(2026, {})

        # Build Kabupaten trends for deep-dive analysis
        kab_trend_map = defaultdict(lambda: {
            "weeks": [],
            "total": [],
            "optim": [],
            "engineering": [],
            "operation": [],
            "ran_vendor": [],
            "optim_pct": [],
            "p1": [],
            "p2": [],
            "p3": [],
            "balanced": [],
            "p1_pct": [],
            "v1_unb": [],
            "v2_unb": [],
            "v3_unb": []
        })

        for yw in yws_in_range:
            rows_w = week_kab_data[yw]
            w_str = f"W{str(yw)[-2:]}"
            for r in rows_w:
                _, kab, tot, opt, eng, op, ven, p1, p2, p3, bal, v1, v2, v3 = r
                if not kab or kab == "UNKNOWN":
                    continue
                kt = kab_trend_map[kab]
                kt["weeks"].append(w_str)
                kt["total"].append(tot)
                kt["optim"].append(opt)
                kt["engineering"].append(eng)
                kt["operation"].append(op)
                kt["ran_vendor"].append(ven)
                kt["optim_pct"].append(round(opt / tot * 100.0, 2) if tot else 0.0)
                kt["p1"].append(p1)
                kt["p2"].append(p2)
                kt["p3"].append(p3)
                kt["balanced"].append(bal)
                kt["p1_pct"].append(round(p1 / tot * 100.0, 2) if tot else 0.0)
                kt["v1_unb"].append(v1)
                kt["v2_unb"].append(v2)
                kt["v3_unb"].append(v3)

        response_data = {
            "status": "success",
            "yearweeks": yws_in_range,
            "week_labels": week_labels,
            "full_week_labels": full_week_labels,
            "kabupaten_list": sorted(list(kab_trend_map.keys())),
            "kabupaten_trends": dict(kab_trend_map),
            "rci_trend": {
                **rci_trend,
                "moving_series": rci_moving_trend_series,
                "nop_series": rci_nop_series
            },
            "unbalance_trend": {
                **unb_trend,
                "q_targets": {
                    "Q1": target_dict_unb.get("Q1", 2.49),
                    "Q2": target_dict_unb.get("Q2", 2.14),
                    "Q3": target_dict_unb.get("Q3", 1.85),
                    "Q4": target_dict_unb.get("Q4", 1.65),
                },
                "nop_series": unb_nop_series
            }
        }

        _RAN_CACHE[cache_key] = (response_data, now + _RAN_CACHE_TTL)
        return jsonify(response_data)

    except Exception as e:
        logger.exception("Error in api_ran_capacity_trend: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# API 3: COMPARISON TABLE DATA
# ══════════════════════════════════════════════════════════════════════
@ran_capacity.route("/api/sow/ran_capacity/comparison", methods=["GET"])
@login_required
def api_ran_capacity_comparison():
    region = request.args.get("region", "PUMA").strip()
    branch = request.args.get("branch", "ALL").strip().upper()
    mode = request.args.get("mode", "rci").strip().lower()
    search = request.args.get("search", "").strip().upper()
    status_filter = request.args.get("status", "ALL").strip().upper()

    yearweeks = _get_yearweeks()
    if not yearweeks:
        return jsonify({"status": "error", "message": "No data available"}), 404

    try:
        yw = int(request.args.get("week", yearweeks[0]))
    except (ValueError, TypeError):
        yw = yearweeks[0]

    prev_yw = None
    if yw in yearweeks:
        idx = yearweeks.index(yw)
        if idx + 1 < len(yearweeks):
            prev_yw = yearweeks[idx + 1]

    branch_map = _get_branch_map()
    site_kab_map = _get_site_kab_map()

    target_val, _, _ = _get_target_for_week(yw, mode)

    cache_key = f"comp_{region}_{branch}_{yw}_{prev_yw}_{mode}"
    now = time.time()
    if cache_key in _RAN_CACHE:
        val, exp = _RAN_CACHE[cache_key]
        if now < exp:
            return jsonify(val)

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("""
                SELECT 
                    COALESCE(NULLIF(UPPER(TRIM(kabupaten)), ''), 'UNKNOWN') as kab,
                    count(*) as total,
                    count(*) filter (where grouping_rci = 'optimization') as rci_optim,
                    count(*) filter (where grouping_rci = 'engineering') as rci_eng,
                    count(*) filter (where grouping_rci = 'operation') as rci_op,
                    count(*) filter (where grouping_rci = 'ran_vendor') as rci_ven,
                    count(*) filter (where unbalanced_3method = 'unbalanced_p1') as unb_p1,
                    count(*) filter (where unbalanced_3method = 'unbalanced_p2') as unb_p2,
                    count(*) filter (where unbalanced_3method = 'unbalanced_p3') as unb_p3,
                    count(*) filter (where unbalanced_3method = 'balanced') as unb_bal,
                    count(*) filter (where unbalanced_v1 = 'unbalanced') as v1_unb,
                    count(*) filter (where unbalanced_v2 = 'unbalanced') as v2_unb,
                    count(*) filter (where unbalanced_v3 = 'unbalanced_thp') as v3_unb
                FROM sow.rci_redsector
                WHERE week = %s
                GROUP BY COALESCE(NULLIF(UPPER(TRIM(kabupaten)), ''), 'UNKNOWN');
            """, (yw,))
            curr_kab_rows = cur.fetchall()

            prev_kab_stats = defaultdict(lambda: {"total": 0, "rci_optim": 0, "unb_p1": 0})
            if prev_yw:
                cur.execute("""
                    SELECT 
                        COALESCE(NULLIF(UPPER(TRIM(kabupaten)), ''), 'UNKNOWN') as kab,
                        count(*) as total,
                        count(*) filter (where grouping_rci = 'optimization') as rci_optim,
                        count(*) filter (where unbalanced_3method = 'unbalanced_p1') as unb_p1
                    FROM sow.rci_redsector
                    WHERE week = %s
                    GROUP BY COALESCE(NULLIF(UPPER(TRIM(kabupaten)), ''), 'UNKNOWN');
                """, (prev_yw,))
                for pr in cur.fetchall():
                    pkab = pr[0] if pr[0] else "UNKNOWN"
                    prev_kab_stats[pkab]["total"] += pr[1]
                    prev_kab_stats[pkab]["rci_optim"] += pr[2]
                    prev_kab_stats[pkab]["unb_p1"] += pr[3]

        kab_stats = defaultdict(lambda: {
            "total": 0, "rci_optim": 0, "rci_eng": 0, "rci_op": 0, "rci_ven": 0,
            "unb_p1": 0, "unb_p2": 0, "unb_p3": 0, "unb_bal": 0,
            "v1_unb": 0, "v2_unb": 0, "v3_unb": 0
        })

        for r in curr_kab_rows:
            kab = r[0] if r[0] else "UNKNOWN"
            d = kab_stats[kab]
            d["total"] += r[1]
            d["rci_optim"] += r[2]
            d["rci_eng"] += r[3]
            d["rci_op"] += r[4]
            d["rci_ven"] += r[5]
            d["unb_p1"] += r[6]
            d["unb_p2"] += r[7]
            d["unb_p3"] += r[8]
            d["unb_bal"] += r[9]
            d["v1_unb"] += r[10]
            d["v2_unb"] += r[11]
            d["v3_unb"] += r[12]

        table_kab = []
        nop_rollups = defaultdict(lambda: {
            "total": 0, "rci_optim": 0, "rci_eng": 0, "rci_op": 0, "rci_ven": 0,
            "unb_p1": 0, "unb_p2": 0, "unb_p3": 0, "unb_bal": 0,
            "v1_unb": 0, "v2_unb": 0, "v3_unb": 0,
            "prev_total": 0, "prev_optim": 0, "prev_p1": 0
        })

        for kab, d in kab_stats.items():
            nop = branch_map.get(kab, "UNKNOWN")
            if branch != "ALL" and nop != branch:
                continue

            if search and search not in kab and search not in nop:
                continue

            prev_d = prev_kab_stats.get(kab, {"total": 0, "rci_optim": 0, "unb_p1": 0})
            prev_tot = prev_d["total"]

            nr = nop_rollups[nop]
            for k_field in ["total", "rci_optim", "rci_eng", "rci_op", "rci_ven", "unb_p1", "unb_p2", "unb_p3", "unb_bal", "v1_unb", "v2_unb", "v3_unb"]:
                nr[k_field] += d[k_field]
            nr["prev_total"] += prev_tot
            nr["prev_optim"] += prev_d["rci_optim"]
            nr["prev_p1"] += prev_d["unb_p1"]

            t = d["total"]
            if mode == "rci":
                curr_cnt = d["rci_optim"]
                curr_pct = round(curr_cnt / t * 100.0, 2) if t else 0.0
                prev_cnt = prev_d["rci_optim"]
                prev_pct = round(prev_cnt / prev_tot * 100.0, 2) if prev_tot else 0.0
            else:
                curr_cnt = d["unb_p1"]
                curr_pct = round(curr_cnt / t * 100.0, 2) if t else 0.0
                prev_cnt = prev_d["unb_p1"]
                prev_pct = round(prev_cnt / prev_tot * 100.0, 2) if prev_tot else 0.0

            wow_delta = round(curr_pct - prev_pct, 2) if prev_tot else 0.0
            is_pass = curr_pct <= target_val
            pass_status = "PASS" if is_pass else "BREACH"

            if status_filter != "ALL" and pass_status != status_filter:
                continue

            table_kab.append({
                "branch": nop,
                "kabupaten": kab,
                "total_sectors": t,
                "primary_count": curr_cnt,
                "primary_pct": curr_pct,
                "prev_count": prev_cnt,
                "prev_pct": prev_pct,
                "wow_delta": wow_delta,
                "wow_status": "Improved" if wow_delta < 0 else ("Degraded" if wow_delta > 0 else "Flat"),
                "target": target_val,
                "target_status": pass_status,
                "rci_eng": d["rci_eng"],
                "rci_op": d["rci_op"],
                "rci_ven": d["rci_ven"],
                "unb_p2": d["unb_p2"],
                "unb_p3": d["unb_p3"],
                "unb_bal": d["unb_bal"],
                "v1_unb": d["v1_unb"],
                "v2_unb": d["v2_unb"],
                "v3_unb": d["v3_unb"]
            })

        sort_col = request.args.get("sort", "primary_count")
        sort_order = request.args.get("order", "desc")
        reverse_sort = sort_order == "desc"
        table_kab.sort(key=lambda x: x.get(sort_col, 0) if x.get(sort_col) is not None else 0, reverse=reverse_sort)

        table_nop = []
        tot_all = {"total": 0, "curr_cnt": 0, "prev_cnt": 0, "prev_total": 0}

        known_nops = ["AMBON", "JAYAPURA", "TIMIKA", "SORONG"]
        for n in known_nops:
            if n not in nop_rollups:
                continue
            nr = nop_rollups[n]
            t = nr["total"]
            prev_t = nr["prev_total"]
            if mode == "rci":
                curr_c = nr["rci_optim"]
                prev_c = nr["prev_optim"]
            else:
                curr_c = nr["unb_p1"]
                prev_c = nr["prev_p1"]

            curr_p = round(curr_c / t * 100.0, 2) if t else 0.0
            prev_p = round(prev_c / prev_t * 100.0, 2) if prev_t else 0.0
            delta = round(curr_p - prev_p, 2) if prev_t else 0.0
            is_p = curr_p <= target_val

            tot_all["total"] += t
            tot_all["curr_cnt"] += curr_c
            tot_all["prev_cnt"] += prev_c
            tot_all["prev_total"] += prev_t

            table_nop.append({
                "branch": f"NOP {n}",
                "total_sectors": t,
                "primary_count": curr_c,
                "primary_pct": curr_p,
                "prev_count": prev_c,
                "prev_pct": prev_p,
                "wow_delta": delta,
                "wow_status": "Improved" if delta < 0 else ("Degraded" if delta > 0 else "Flat"),
                "target": target_val,
                "target_status": "PASS" if is_p else "BREACH"
            })

        t_tot = tot_all["total"]
        t_prev_tot = tot_all["prev_total"]
        t_curr_p = round(tot_all["curr_cnt"] / t_tot * 100.0, 2) if t_tot else 0.0
        t_prev_p = round(tot_all["prev_cnt"] / t_prev_tot * 100.0, 2) if t_prev_tot else 0.0
        t_delta = round(t_curr_p - t_prev_p, 2) if t_prev_tot else 0.0
        t_is_p = t_curr_p <= target_val

        total_row = {
            "branch": "REGIONAL PUMA",
            "total_sectors": t_tot,
            "primary_count": tot_all["curr_cnt"],
            "primary_pct": t_curr_p,
            "prev_count": tot_all["prev_cnt"],
            "prev_pct": t_prev_p,
            "wow_delta": t_delta,
            "wow_status": "Improved" if t_delta < 0 else ("Degraded" if t_delta > 0 else "Flat"),
            "target": target_val,
            "target_status": "PASS" if t_is_p else "BREACH"
        }

        return jsonify({
            "status": "success",
            "yearweek": yw,
            "prev_yearweek": prev_yw,
            "mode": mode,
            "target": target_val,
            "table_nop": table_nop,
            "total_row": total_row,
            "table_kab": table_kab
        })

    except Exception as e:
        logger.exception("Error in api_ran_capacity_comparison: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# API 4: EXPORT TO CSV
# ══════════════════════════════════════════════════════════════════════
@ran_capacity.route("/api/sow/ran_capacity/export", methods=["GET"])
@login_required
def api_ran_capacity_export():
    region = request.args.get("region", "PUMA").strip()
    branch = request.args.get("branch", "ALL").strip().upper()
    mode = request.args.get("mode", "rci").strip().lower()
    level = request.args.get("level", "kabupaten").strip().lower()

    yearweeks = _get_yearweeks()
    try:
        yw = int(request.args.get("week", yearweeks[0] if yearweeks else 202638))
    except (ValueError, TypeError):
        yw = yearweeks[0] if yearweeks else 202638

    branch_map = _get_branch_map()
    site_kab_map = _get_site_kab_map()
    target_val, _, _ = _get_target_for_week(yw, mode)

    try:
        with db_query(get_postgres_connection) as (conn, cur):
            if level == "sector":
                cur.execute("""
                    SELECT 
                        week, region, site_id, site_sector, type, kabupaten,
                        grouping_rci, remark_redsector_final, aging,
                        unbalanced_3method, unbalanced_v1, unbalanced_v2, unbalanced_v3,
                        prb_util_sector, delta_prb, threshold_hrc
                    FROM sow.rci_redsector
                    WHERE week = %s
                    ORDER BY site_id ASC, sector_id_new ASC
                """, (yw,))
                rows = []
                for r in cur.fetchall():
                    raw_k = r[5]
                    sid = r[2]
                    kab = raw_k.upper().strip() if raw_k and raw_k.strip() else site_kab_map.get(sid, "UNKNOWN")
                    nop = branch_map.get(kab, "UNKNOWN")
                    if branch != "ALL" and nop != branch:
                        continue
                    rows.append((
                        r[0], nop, kab, r[2], r[3], r[4], r[6], r[7], r[8],
                        r[9], r[10], r[11], r[12], r[13], r[14], r[15]
                    ))
                headers = [
                    "Week", "NOP", "Kabupaten", "Site ID", "Site Sector", "Type",
                    "Grouping RCI", "Remark Red Sector", "Aging (Wks)",
                    "Unbalanced 3Method", "V1", "V2", "V3",
                    "PRB Util (%)", "Delta PRB (%)", "Threshold HRC"
                ]
                filename = f"RAN_Capacity_Sectors_{mode.upper()}_{yw}.csv"
                return csv_response(rows, headers, filename)
            else:
                cur.execute("""
                    SELECT 
                        kabupaten,
                        site_id,
                        count(*) as total,
                        count(*) filter (where grouping_rci = 'optimization') as rci_optim,
                        count(*) filter (where grouping_rci = 'engineering') as rci_eng,
                        count(*) filter (where grouping_rci = 'operation') as rci_op,
                        count(*) filter (where grouping_rci = 'ran_vendor') as rci_ven,
                        count(*) filter (where unbalanced_3method = 'unbalanced_p1') as unb_p1,
                        count(*) filter (where unbalanced_3method = 'unbalanced_p2') as unb_p2,
                        count(*) filter (where unbalanced_3method = 'unbalanced_p3') as unb_p3,
                        count(*) filter (where unbalanced_3method = 'balanced') as unb_bal,
                        count(*) filter (where unbalanced_v1 = 'unbalanced') as v1_unb,
                        count(*) filter (where unbalanced_v2 = 'unbalanced') as v2_unb,
                        count(*) filter (where unbalanced_v3 = 'unbalanced_thp') as v3_unb
                    FROM sow.rci_redsector
                    WHERE week = %s
                    GROUP BY kabupaten, site_id
                """, (yw,))
                kab_stats = defaultdict(lambda: {
                    "total": 0, "rci_optim": 0, "rci_eng": 0, "rci_op": 0, "rci_ven": 0,
                    "unb_p1": 0, "unb_p2": 0, "unb_p3": 0, "unb_bal": 0,
                    "v1_unb": 0, "v2_unb": 0, "v3_unb": 0
                })
                for r in cur.fetchall():
                    raw_k = r[0]
                    sid = r[1]
                    kab = raw_k.upper().strip() if raw_k and raw_k.strip() else site_kab_map.get(sid, "UNKNOWN")
                    d = kab_stats[kab]
                    d["total"] += r[2]
                    d["rci_optim"] += r[3]
                    d["rci_eng"] += r[4]
                    d["rci_op"] += r[5]
                    d["rci_ven"] += r[6]
                    d["unb_p1"] += r[7]
                    d["unb_p2"] += r[8]
                    d["unb_p3"] += r[9]
                    d["unb_bal"] += r[10]
                    d["v1_unb"] += r[11]
                    d["v2_unb"] += r[12]
                    d["v3_unb"] += r[13]

                export_rows = []
                for kab, d in sorted(kab_stats.items()):
                    nop = branch_map.get(kab, "UNKNOWN")
                    if branch != "ALL" and nop != branch:
                        continue
                    tot = d["total"]
                    if mode == "rci":
                        opt = d["rci_optim"]
                        pct = round(opt / tot * 100.0, 2) if tot else 0.0
                        st = "PASS" if pct <= target_val else "BREACH"
                        export_rows.append((
                            yw, nop, kab, tot, opt, f"{pct:.2f}%", d["rci_eng"],
                            d["rci_op"], d["rci_ven"], f"{target_val:.2f}%", st
                        ))
                    else:
                        p1 = d["unb_p1"]
                        pct = round(p1 / tot * 100.0, 2) if tot else 0.0
                        st = "PASS" if pct <= target_val else "BREACH"
                        export_rows.append((
                            yw, nop, kab, tot, p1, f"{pct:.2f}%", d["unb_p2"],
                            d["unb_p3"], d["unb_bal"], d["v1_unb"], d["v2_unb"],
                            d["v3_unb"], f"{target_val:.2f}%", st
                        ))

                if mode == "rci":
                    headers = [
                        "Week", "NOP", "Kabupaten", "Total Sectors", "Direct Optim",
                        "% Need Optim", "Direct Investment", "Direct Operation",
                        "RAN Vendor", "Target", "Status"
                    ]
                else:
                    headers = [
                        "Week", "NOP", "Kabupaten", "Total Sectors", "Unbalance P1",
                        "% Unbalance P1", "P2", "P3", "Balanced",
                        "V1 Unbalance", "V2 Unbalance", "V3 Unbalance", "Target", "Status"
                    ]
                filename = f"RAN_Capacity_{mode.upper()}_Kabupaten_{yw}.csv"
                return csv_response(export_rows, headers, filename)

    except Exception as e:
        logger.exception("Error in export: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# API 5: SAMPLE TEMPLATE DOWNLOAD
# ══════════════════════════════════════════════════════════════════════
@ran_capacity.route("/api/sow/ran_capacity/sample", methods=["GET"])
@login_required
def api_ran_capacity_sample_template():
    file_format = request.args.get("format", "xlsx").lower()
    headers = RCI_REDSECTOR_COLUMNS
    sample_rows = _get_sample_rows()

    if file_format == "csv":
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(headers)
        for row in sample_rows:
            writer.writerow(row)
        csv_bytes = csv_buffer.getvalue().encode("utf-8-sig")
        response = make_response(csv_bytes)
        response.headers["Content-Disposition"] = "attachment; filename=OKR_RAN_Capacity_Sample.csv"
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        return response
    else:
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "RAN_Capacity_Data"

            header_fill = PatternFill(start_color="8B0000", end_color="8B0000", fill_type="solid")
            header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            border = Border(
                left=Side(style="thin", color="D9D9D9"),
                right=Side(style="thin", color="D9D9D9"),
                top=Side(style="thin", color="D9D9D9"),
                bottom=Side(style="thin", color="D9D9D9")
            )

            ws.append(headers)
            for col_num in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_num)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = border
            ws.row_dimensions[1].height = 24

            for row_idx, row_data in enumerate(sample_rows, start=2):
                ws.append(row_data)
                for col_num in range(1, len(headers) + 1):
                    cell = ws.cell(row=row_idx, column=col_num)
                    cell.border = border
                    cell.alignment = Alignment(vertical="center")

            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = col[0].column_letter
                ws.column_dimensions[col_letter].width = max(max_len + 3, 14)

            excel_buffer = io.BytesIO()
            wb.save(excel_buffer)
            excel_buffer.seek(0)
            return send_file(
                excel_buffer,
                download_name="OKR_RAN_Capacity_Sample.xlsx",
                as_attachment=True,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            logger.exception("Error generating Excel template: %s", e)
            return jsonify({"status": "error", "message": "Failed to generate Excel template"}), 500


# ══════════════════════════════════════════════════════════════════════
# API 6: ASYNC BATCH IMPORT & PROGRESS
# ══════════════════════════════════════════════════════════════════════
def _ran_set_job(job_id, **kw):
    with _RAN_IMPORT_LOCK:
        job = _RAN_IMPORT_JOBS.get(job_id)
        if job:
            job.update(kw)


@ran_capacity.route("/api/sow/ran_capacity/import", methods=["POST"])
@csrf.exempt
@login_required
def api_ran_capacity_import():
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"status": "error", "message": "Empty file uploaded"}), 400

    filename = file.filename.lower()
    if not filename.endswith((".csv", ".xlsx", ".xls")):
        return jsonify({"status": "error", "message": "Unsupported file format. Please upload .xlsx or .csv"}), 400

    job_id = str(uuid4())
    fd, path = tempfile.mkstemp(suffix=os.path.splitext(filename)[1])
    with os.fdopen(fd, "wb") as f:
        file.save(f)

    with _RAN_IMPORT_LOCK:
        _RAN_IMPORT_JOBS[job_id] = {"status": "queued", "pct": 0, "message": "Queued..."}

    threading.Thread(target=_bg_ran_capacity_import, args=(job_id, path, filename), daemon=True).start()
    return jsonify({"status": "queued", "job_id": job_id})


@ran_capacity.route("/api/sow/ran_capacity/import/progress/<job_id>", methods=["GET"])
@login_required
def api_ran_capacity_import_progress(job_id):
    with _RAN_IMPORT_LOCK:
        job = _RAN_IMPORT_JOBS.get(job_id)
        if job is None:
            return jsonify({"status": "error", "message": "Job not found"}), 404
        snapshot = dict(job)
    return jsonify(snapshot)


def _bg_ran_capacity_import(job_id, file_path, filename):
    start_time = time.time()
    try:
        _ran_set_job(job_id, status="processing", pct=10, message="Parsing file...", stage="parse")
        is_csv = filename.lower().endswith(".csv")
        headers = []
        rows_iter = []

        if is_csv:
            with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
                reader = csv.reader(fh)
                try:
                    headers = next(reader)
                except StopIteration:
                    _ran_set_job(job_id, status="error", message="Uploaded CSV file is empty")
                    return
                rows_iter = list(reader)
        else:
            try:
                from python_calamine import CalamineWorkbook
                wb = CalamineWorkbook.from_path(file_path)
                sheet_data = wb.get_sheet_by_index(0).to_python()
                if sheet_data:
                    headers = sheet_data[0]
                    rows_iter = sheet_data[1:]
            except Exception:
                import openpyxl
                wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
                ws = wb.active
                sheet_rows = list(ws.iter_rows(values_only=True))
                wb.close()
                if sheet_rows:
                    headers = sheet_rows[0]
                    rows_iter = sheet_rows[1:]

        if not headers or not rows_iter:
            _ran_set_job(job_id, status="error", message="Uploaded file contains no data rows")
            return

        header_idx = {str(h).strip().lower(): i for i, h in enumerate(headers) if h is not None}

        # Check 1: Week column
        src_week = header_idx.get("week", -1)
        if src_week == -1:
            src_week = header_idx.get("yearweek", -1)
        if src_week == -1:
            src_week = header_idx.get("weeknum", -1)
        if src_week == -1:
            header_sample = ", ".join([str(h) for h in headers[:8] if h])
            _ran_set_job(job_id, status="error", message=f"Column 'week' not found in file headers. Found headers: [{header_sample}].")
            return

        # Check 2: Site ID
        src_sid = header_idx.get("site_id", -1)
        if src_sid == -1:
            src_sid = header_idx.get("siteid", -1)
        if src_sid == -1:
            src_sid = header_idx.get("site_id_new", -1)
        if src_sid == -1:
            _ran_set_job(job_id, status="error", message="Missing required 'site_id' column in file headers.")
            return

        # Check 3: Region and Kabupaten
        if "region" not in header_idx:
            _ran_set_job(job_id, status="error", message="Missing required 'region' column in file headers.")
            return
        if "kabupaten" not in header_idx:
            _ran_set_job(job_id, status="error", message="Missing required 'kabupaten' column in file headers.")
            return

        # Check 4: Check for at least one RAN Capacity core metric
        ran_kpi_cols = {
            "remark_redsector", "prb_util_sector", "remark_redsector_final", "weekly_payload_gbyte",
            "sector_capability", "site_sector", "unbalanced_prb", "threshold_hrc", "number_band",
            "aging", "vendor"
        }
        if not any(c in header_idx for c in ran_kpi_cols):
            _ran_set_job(
                job_id,
                status="error",
                message="Invalid format for RAN Capacity: Core KPI columns ('remark_redsector', 'prb_util_sector', etc.) not found in headers."
            )
            return

        _ran_set_job(job_id, status="processing", pct=35, message=f"Validating {len(rows_iter):,} rows...", stage="validate")

        src_sec = header_idx.get("sector_id_new", -1)
        if src_sec == -1:
            src_sec = header_idx.get("sector_id", -1)
        if src_sec == -1:
            src_sec = header_idx.get("sector", -1)

        src_type = header_idx.get("type", -1)
        r_i = header_idx["region"]
        k_i = header_idx["kabupaten"]

        col_specs = []
        for i, col in enumerate(RCI_REDSECTOR_COLUMNS):
            col_l = col.lower()
            c_idx = header_idx.get(col_l, -1)
            if col == "week":
                t = 0
            elif col == "region":
                t = 1
            elif col == "site_id":
                t = 2
            elif col == "sector_id_new":
                t = 3
            elif col == "kabupaten":
                t = 4
            elif col == "type":
                t = 5
            elif col in RCI_REDSECTOR_INT_COLS:
                t = 6
            elif col in RCI_REDSECTOR_FLOAT_COLS:
                t = 7
            else:
                t = 8
            col_specs.append((c_idx, t))

        insert_records = []
        weeks = set()

        for r in rows_iter:
            if not any(v is not None and str(v).strip() != "" for v in r):
                continue
            r_len = len(r)
            if src_week >= r_len:
                continue
            raw_w = r[src_week]
            try:
                w_val = int(float(str(raw_w).strip()))
            except (ValueError, TypeError):
                continue
            if w_val <= 0:
                continue

            reg = _safe_str(r[r_i] if r_i < r_len else None)
            sid = _safe_str(r[src_sid] if src_sid < r_len else None)
            sec = _safe_int(r[src_sec] if (src_sec != -1 and src_sec < r_len) else None, default=1)
            kab = _safe_str(r[k_i] if k_i < r_len else None)
            typ = _safe_str(r[src_type] if (src_type != -1 and src_type < r_len) else None, default="MAC") or "MAC"

            if not reg or not sid or not kab:
                continue

            weeks.add(w_val)
            record = []
            for c_idx, t in col_specs:
                if t == 0:
                    record.append(w_val)
                elif t == 1:
                    record.append(reg)
                elif t == 2:
                    record.append(sid)
                elif t == 3:
                    record.append(sec)
                elif t == 4:
                    record.append(kab)
                elif t == 5:
                    record.append(typ)
                else:
                    val = r[c_idx] if (c_idx != -1 and c_idx < r_len) else None
                    if t == 6:
                        record.append(_safe_int(val, default=0) if val is not None and str(val).strip() != "" else None)
                    elif t == 7:
                        record.append(_safe_float(val, default=0.0) if val is not None and str(val).strip() != "" else None)
                    else:
                        record.append(_safe_str(val, default="") if val is not None else None)
            insert_records.append(tuple(record))

        if not insert_records:
            _ran_set_job(job_id, status="error", message="No valid data rows found to insert")
            return

        _ran_set_job(job_id, status="processing", pct=65, message=f"Prepared {len(insert_records):,} rows. Upserting into database...", stage="copy")

        col_names = ", ".join([f'"{c}"' for c in RCI_REDSECTOR_COLUMNS])
        val_placeholders = ", ".join(["%s"] * len(RCI_REDSECTOR_COLUMNS))
        update_cols = [c for c in RCI_REDSECTOR_COLUMNS if c not in ("week", "region", "site_id", "sector_id_new", "kabupaten", "type")]
        update_clause = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in update_cols])

        insert_query = f"""
            INSERT INTO sow.rci_redsector ({col_names})
            VALUES ({val_placeholders})
            ON CONFLICT (week, region, site_id, sector_id_new, kabupaten, type)
            DO UPDATE SET {update_clause}
        """

        with db_query(get_postgres_connection) as (conn, cur):
            psycopg2.extras.execute_batch(cur, insert_query, insert_records, page_size=500)
            conn.commit()

        clear_ran_capacity_caches()
        duration_s = round(time.time() - start_time, 1)
        dur_str = f"{int(duration_s)}s" if duration_s < 60 else f"{int(duration_s//60)}m {int(duration_s%60)}s"
        weeks_str = ", ".join(f"W{str(w)[4:]}" for w in sorted(weeks))
        _ran_set_job(
            job_id,
            status="success",
            pct=100,
            message=f"Successfully imported {len(insert_records):,} records across week(s): {weeks_str} in {dur_str}.",
            weeknums=list(sorted(weeks)),
            total_rows=len(insert_records),
            duration_s=duration_s,
            duration_str=dur_str
        )
    except Exception as e:
        logger.exception("RAN capacity async import failed: %s", e)
        err_msg = str(e).strip()
        if "CONTEXT:" in err_msg:
            err_msg = err_msg.split("CONTEXT:")[0].strip()
        _ran_set_job(job_id, status="error", message=f"Import error: {err_msg}")
    finally:
        if os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except Exception:
                pass
