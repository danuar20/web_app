"""OKR Healthy Site Dashboard Routes — /okr/healthy_site

Regional Papua Maluku (PUMA) Multi-Domain Network Health Check:
Aggregates and correlates health status across 4 OKR / SOW pillars:
  1. CEI (Cell Efficiency / Crowdsource Experience Index) — sow.cei_score (remark_cell = 'Bad_cell')
  2. RHI (Radio Health Index) — sow.rhi_score (UPPER(TRIM(remark_week)) = 'FAIL')
  3. RCI (Radio Condition Index) — sow.rci_redsector (grouping_rci = 'optimization')
  4. UNBALANCE (Unbalance P1) — sow.rci_redsector (unbalanced_3method = 'unbalanced_p1')

Supports both:
  - Site Level aggregation (Logical OR / MAX across all cells/sectors of the site)
  - Sector Level granular breakdown (AMB004-1, AMB004-2, ...)
"""
import io
import csv
import time
import logging
from collections import defaultdict
from flask import Blueprint, render_template, request, session, jsonify, make_response, send_file
from app import csrf
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, db_query

logger = logging.getLogger(__name__)

healthy_site = Blueprint("healthy_site", __name__)

# In-memory cache for fast interactive response
_HS_CACHE = {}
_HS_CACHE_TTL = 900  # 15 minutes
_HS_WEEKS_CACHE = {"ts": 0, "weeks": []}


def clear_healthy_site_cache():
    """Clear in-memory cache."""
    global _HS_CACHE, _HS_WEEKS_CACHE
    _HS_CACHE.clear()
    _HS_WEEKS_CACHE = {"ts": 0, "weeks": []}


def _get_available_weeks():
    """Fetch distinct common evaluated weeks across CEI, RHI, and RCI."""
    now = time.time()
    if _HS_WEEKS_CACHE["weeks"] and (now - _HS_WEEKS_CACHE["ts"] < 120):
        return _HS_WEEKS_CACHE["weeks"]

    query = """
        SELECT DISTINCT weeknum FROM sow.cei_score WHERE weeknum BETWEEN 202001 AND 202952
        INTERSECT
        SELECT DISTINCT weeknum FROM sow.rhi_score WHERE weeknum BETWEEN 202001 AND 202952
        INTERSECT
        SELECT DISTINCT week FROM sow.rci_redsector WHERE week BETWEEN 202001 AND 202952
        ORDER BY 1 DESC
        LIMIT 52
    """
    weeks = []
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(query)
            weeks = [r[0] for r in cur.fetchall()]
    except Exception as e:
        logger.exception("Error fetching healthy site weeks: %s", e)

    if not weeks:
        # Fallback to any weeks in sow.rhi_score
        try:
            with db_query(get_postgres_connection) as (conn, cur):
                cur.execute("SELECT DISTINCT weeknum FROM sow.rhi_score WHERE weeknum BETWEEN 202001 AND 202952 ORDER BY 1 DESC LIMIT 20")
                weeks = [r[0] for r in cur.fetchall()]
        except Exception:
            pass

    _HS_WEEKS_CACHE["weeks"] = weeks
    _HS_WEEKS_CACHE["ts"] = now
    return weeks


def _fetch_healthy_dataset(week):
    """Fetch and aggregate sector and site level data for a specific week."""
    cache_key = f"hs_week_{week}"
    now = time.time()
    if cache_key in _HS_CACHE:
        entry = _HS_CACHE[cache_key]
        if now - entry["ts"] < _HS_CACHE_TTL:
            return entry["data"]

    t0 = time.time()
    query = """
    WITH cei_sec AS (
        SELECT 
            UPPER(TRIM(site_id)) AS site_id,
            COALESCE(
                SUBSTRING(cell_name FROM '_[A-Za-z]{2}(\\d{1,2})$'),
                SUBSTRING(cell_name FROM '(\\d+)$')
            )::int AS sector_num,
            MAX(UPPER(TRIM(kabupaten))) AS kabupaten,
            MAX(CASE WHEN remark_cell = 'Bad_cell' THEN 1 ELSE 0 END) AS cei
        FROM sow.cei_score
        WHERE weeknum = %(week)s AND site_id IS NOT NULL AND TRIM(site_id) != ''
        GROUP BY UPPER(TRIM(site_id)), sector_num
    ),
    rhi_sec AS (
        SELECT 
            UPPER(TRIM(site_id)) AS site_id,
            COALESCE(
                SUBSTRING(cell_name FROM '_[A-Za-z]{2}(\\d{1,2})$'),
                SUBSTRING(cell_name FROM '(\\d+)$')
            )::int AS sector_num,
            MAX(UPPER(TRIM(kabupaten))) AS kabupaten,
            MAX(CASE WHEN UPPER(TRIM(remark_week)) = 'FAIL' THEN 1 ELSE 0 END) AS rhi,
            MAX(CASE 
                WHEN availability_cellbasedconsecutive_remark = 'fail' 
                     OR total_fail_availability_cellbasedconsecutive_remark = 1 THEN 1 
                ELSE 0 
            END) AS avail
        FROM sow.rhi_score
        WHERE weeknum = %(week)s AND site_id IS NOT NULL AND TRIM(site_id) != ''
        GROUP BY UPPER(TRIM(site_id)), sector_num
    ),
    rci_sec AS (
        SELECT 
            UPPER(TRIM(site_id)) AS site_id,
            sector_id_new AS sector_num,
            MAX(UPPER(TRIM(kabupaten))) AS kabupaten,
            MAX(CASE WHEN grouping_rci = 'optimization' THEN 1 ELSE 0 END) AS rci,
            MAX(CASE WHEN unbalanced_3method = 'unbalanced_p1' THEN 1 ELSE 0 END) AS unb
        FROM sow.rci_redsector
        WHERE week = %(week)s AND site_id IS NOT NULL AND TRIM(site_id) != ''
        GROUP BY UPPER(TRIM(site_id)), sector_id_new
    ),
    pl_site AS (
        SELECT 
            UPPER(TRIM(siteid)) AS site_id,
            CASE 
                WHEN (SUM(packet_loss_num)::numeric / NULLIF(SUM(packet_loss_denum), 0) * 100.0) > 0.10 THEN 1 
                ELSE 0 
            END AS pl
        FROM "4G_pl_hy_daily"
        WHERE TO_CHAR(date, 'IYYYIW') = %(week_str)s AND siteid IS NOT NULL AND TRIM(siteid) != ''
        GROUP BY UPPER(TRIM(siteid))
    ),
    all_sec_keys AS (
        SELECT site_id, sector_num FROM cei_sec WHERE sector_num IS NOT NULL
        UNION
        SELECT site_id, sector_num FROM rhi_sec WHERE sector_num IS NOT NULL
        UNION
        SELECT site_id, sector_num FROM rci_sec WHERE sector_num IS NOT NULL
    )
    SELECT 
        k.site_id,
        k.sector_num,
        k.site_id || '-' || k.sector_num AS sector_id,
        COALESCE(rh.kabupaten, c.kabupaten, rc.kabupaten, '-') AS kabupaten,
        COALESCE(c.cei, 0) AS cei,
        COALESCE(rh.rhi, 0) AS rhi,
        COALESCE(rc.rci, 0) AS rci,
        COALESCE(rc.unb, 0) AS unbalance,
        COALESCE(rh.avail, 0) AS availability,
        COALESCE(pl.pl, 0) AS pl
    FROM all_sec_keys k
    LEFT JOIN cei_sec c ON k.site_id = c.site_id AND k.sector_num = c.sector_num
    LEFT JOIN rhi_sec rh ON k.site_id = rh.site_id AND k.sector_num = rh.sector_num
    LEFT JOIN rci_sec rc ON k.site_id = rc.site_id AND k.sector_num = rc.sector_num
    LEFT JOIN pl_site pl ON k.site_id = pl.site_id
    ORDER BY k.site_id, k.sector_num
    """

    sectors = []
    with db_query(get_postgres_connection) as (conn, cur):
        cur.execute(query, {"week": week, "week_str": str(week)})
        sectors = cur.fetchall()

    logger.info("Fetched %d sectors for week %s in %.2fs", len(sectors), week, time.time() - t0)

    # Process and build Site and Sector records
    sector_records = []
    site_map = {}

    for row in sectors:
        site_id, sec_num, sec_id, kab, cei, rhi, rci, unb, avail, pl = row
        cei = int(cei or 0)
        rhi = int(rhi or 0)
        rci = int(rci or 0)
        unb = int(unb or 0)
        avail = int(avail or 0)
        pl = int(pl or 0)
        issues = cei + rhi + rci + unb + avail + pl

        issue_names = []
        if cei: issue_names.append("CEI")
        if rhi: issue_names.append("RHI")
        if rci: issue_names.append("RCI")
        if unb: issue_names.append("UNBALANCE")
        if avail: issue_names.append("AVAILABILITY")
        if pl: issue_names.append("PL")

        remark_str = "Healthy" if issues == 0 else f"Issue: {', '.join(issue_names)}"

        sec_rec = {
            "site_id": site_id,
            "sector_num": sec_num,
            "sector_id": sec_id,
            "kabupaten": kab,
            "cei": cei,
            "rhi": rhi,
            "rci": rci,
            "unbalance": unb,
            "availability": avail,
            "pl": pl,
            "issues_count": issues,
            "remark": remark_str,
            "issue_names": issue_names
        }
        sector_records.append(sec_rec)

        if site_id not in site_map:
            site_map[site_id] = {
                "site_id": site_id,
                "kabupaten": kab,
                "total_sectors": 0,
                "cei": 0,
                "rhi": 0,
                "rci": 0,
                "unbalance": 0,
                "availability": 0,
                "pl": 0,
                "sectors": []
            }

        s_entry = site_map[site_id]
        s_entry["total_sectors"] += 1
        s_entry["sectors"].append(sec_id)
        if kab != '-' and s_entry["kabupaten"] == '-':
            s_entry["kabupaten"] = kab
        if cei: s_entry["cei"] = 1
        if rhi: s_entry["rhi"] = 1
        if rci: s_entry["rci"] = 1
        if unb: s_entry["unbalance"] = 1
        if avail: s_entry["availability"] = 1
        if pl: s_entry["pl"] = 1

    site_records = []
    for s_id, s_data in site_map.items():
        cei = s_data["cei"]
        rhi = s_data["rhi"]
        rci = s_data["rci"]
        unb = s_data["unbalance"]
        avail = s_data["availability"]
        pl = s_data["pl"]
        issues = cei + rhi + rci + unb + avail + pl

        issue_names = []
        if cei: issue_names.append("CEI")
        if rhi: issue_names.append("RHI")
        if rci: issue_names.append("RCI")
        if unb: issue_names.append("UNBALANCE")
        if avail: issue_names.append("AVAILABILITY")
        if pl: issue_names.append("PL")

        remark_str = "Healthy" if issues == 0 else f"Issue: {', '.join(issue_names)}"

        site_records.append({
            "site_id": s_id,
            "kabupaten": s_data["kabupaten"],
            "total_sectors": s_data["total_sectors"],
            "cei": cei,
            "rhi": rhi,
            "rci": rci,
            "unbalance": unb,
            "availability": avail,
            "pl": pl,
            "issues_count": issues,
            "remark": remark_str,
            "issue_names": issue_names
        })

    # Sort site_records alphabetically by site_id
    site_records.sort(key=lambda x: x["site_id"])

    # Compute high-level summary KPIs
    tot_sites = len(site_records)
    healthy_sites = sum(1 for s in site_records if s["issues_count"] == 0)
    issue_sites = tot_sites - healthy_sites
    healthy_site_pct = round(healthy_sites / tot_sites * 100, 2) if tot_sites > 0 else 0.0

    tot_sectors = len(sector_records)
    healthy_sectors = sum(1 for s in sector_records if s["issues_count"] == 0)
    issue_sectors = tot_sectors - healthy_sectors
    healthy_sec_pct = round(healthy_sectors / tot_sectors * 100, 2) if tot_sectors > 0 else 0.0

    # Issue breakdown by domain
    cei_sites = sum(1 for s in site_records if s["cei"] == 1)
    rhi_sites = sum(1 for s in site_records if s["rhi"] == 1)
    rci_sites = sum(1 for s in site_records if s["rci"] == 1)
    unb_sites = sum(1 for s in site_records if s["unbalance"] == 1)
    avail_sites = sum(1 for s in site_records if s["availability"] == 1)
    pl_sites = sum(1 for s in site_records if s["pl"] == 1)

    cei_sec = sum(1 for s in sector_records if s["cei"] == 1)
    rhi_sec = sum(1 for s in sector_records if s["rhi"] == 1)
    rci_sec = sum(1 for s in sector_records if s["rci"] == 1)
    unb_sec = sum(1 for s in sector_records if s["unbalance"] == 1)
    avail_sec = sum(1 for s in sector_records if s["availability"] == 1)
    pl_sec = sum(1 for s in sector_records if s["pl"] == 1)

    # Issue count distribution (0, 1, 2, 3, 4, 5, 6)
    distrib = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
    for s in site_records:
        cnt = min(s["issues_count"], 6)
        distrib[cnt] = distrib.get(cnt, 0) + 1

    # Kabupaten breakdown
    kab_map = defaultdict(lambda: {"total": 0, "healthy": 0, "issue": 0, "cei": 0, "rhi": 0, "rci": 0, "unb": 0, "avail": 0, "pl": 0})
    for s in site_records:
        k = s["kabupaten"] or "UNKNOWN"
        kab_map[k]["total"] += 1
        if s["issues_count"] == 0:
            kab_map[k]["healthy"] += 1
        else:
            kab_map[k]["issue"] += 1
        if s["cei"]: kab_map[k]["cei"] += 1
        if s["rhi"]: kab_map[k]["rhi"] += 1
        if s["rci"]: kab_map[k]["rci"] += 1
        if s["unbalance"]: kab_map[k]["unb"] += 1
        if s["availability"]: kab_map[k]["avail"] += 1
        if s["pl"]: kab_map[k]["pl"] += 1

    kab_list = []
    for k, v in kab_map.items():
        pct = round(v["healthy"] / v["total"] * 100, 1) if v["total"] > 0 else 0.0
        kab_list.append({
            "kabupaten": k,
            "total": v["total"],
            "healthy": v["healthy"],
            "issue": v["issue"],
            "healthy_pct": pct,
            "cei": v["cei"],
            "rhi": v["rhi"],
            "rci": v["rci"],
            "unb": v["unb"],
            "avail": v["avail"],
            "pl": v["pl"]
        })
    kab_list.sort(key=lambda x: x["total"], reverse=True)

    result_data = {
        "week": week,
        "summary": {
            "total_sites": tot_sites,
            "healthy_sites": healthy_sites,
            "issue_sites": issue_sites,
            "healthy_site_pct": healthy_site_pct,
            "total_sectors": tot_sectors,
            "healthy_sectors": healthy_sectors,
            "issue_sectors": issue_sectors,
            "healthy_sector_pct": healthy_sec_pct,
            "cei_sites": cei_sites,
            "rhi_sites": rhi_sites,
            "rci_sites": rci_sites,
            "unbalance_sites": unb_sites,
            "availability_sites": avail_sites,
            "pl_sites": pl_sites,
            "cei_sectors": cei_sec,
            "rhi_sectors": rhi_sec,
            "rci_sectors": rci_sec,
            "unbalance_sectors": unb_sec,
            "availability_sectors": avail_sec,
            "pl_sectors": pl_sec,
            "issue_distribution": distrib,
        },
        "kabupaten_list": kab_list,
        "site_records": site_records,
        "sector_records": sector_records
    }

    _HS_CACHE[cache_key] = {
        "ts": now,
        "data": result_data
    }
    return result_data


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@healthy_site.route("/okr/healthy_site")
@healthy_site.route("/sow/healthy_site")
@login_required
def healthy_site_page():
    """Render the OKR Healthy Site Dashboard page."""
    if request.args.get("refresh") == "1" or "no-cache" in request.headers.get("Cache-Control", ""):
        clear_healthy_site_cache()

    weeks = _get_available_weeks()
    default_week = weeks[0] if weeks else 202640

    return render_template(
        "sow_healthy_site.html",
        weeks=weeks,
        latest_week=default_week,
        default_week=default_week
    )


@healthy_site.route("/api/okr/healthy_site/weeks", methods=["GET"])
@login_required
def api_healthy_site_weeks():
    """Return available weeks."""
    weeks = _get_available_weeks()
    return jsonify({"status": "success", "weeks": weeks, "latest_week": weeks[0] if weeks else None})


@healthy_site.route("/api/okr/healthy_site/data", methods=["GET", "POST"])
@login_required
def api_healthy_site_data():
    """Fetch health summary and filtered records for site and sector levels."""
    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form.to_dict() if request.method == "POST" else request.args.to_dict()

    week_raw = payload.get("week")
    weeks = _get_available_weeks()
    try:
        week = int(week_raw) if week_raw else (weeks[0] if weeks else 202640)
    except (ValueError, TypeError):
        week = weeks[0] if weeks else 202640

    kabupaten_filter = payload.get("kabupaten", "ALL").strip().upper()
    status_filter = payload.get("status_filter", "ALL").strip().upper()
    search = payload.get("search", "").strip().upper()

    try:
        full_data = _fetch_healthy_dataset(week)
    except Exception as e:
        logger.exception("Error evaluating healthy site dataset for week %s: %s", week, e)
        return jsonify({"status": "error", "message": f"Failed to load health check data: {str(e)}"}), 500

    # Filter site records
    sites = full_data["site_records"]
    sectors = full_data["sector_records"]

    if kabupaten_filter and kabupaten_filter != "ALL":
        sites = [s for s in sites if s["kabupaten"].upper() == kabupaten_filter]
        sectors = [s for s in sectors if s["kabupaten"].upper() == kabupaten_filter]

    if search:
        sites = [s for s in sites if search in s["site_id"].upper() or search in s["kabupaten"].upper()]
        sectors = [s for s in sectors if search in s["sector_id"].upper() or search in s["kabupaten"].upper()]

    if status_filter == "HEALTHY":
        sites = [s for s in sites if s["issues_count"] == 0]
        sectors = [s for s in sectors if s["issues_count"] == 0]
    elif status_filter == "ISSUE":
        sites = [s for s in sites if s["issues_count"] > 0]
        sectors = [s for s in sectors if s["issues_count"] > 0]
    elif status_filter == "CEI":
        sites = [s for s in sites if s["cei"] == 1]
        sectors = [s for s in sectors if s["cei"] == 1]
    elif status_filter == "RHI":
        sites = [s for s in sites if s["rhi"] == 1]
        sectors = [s for s in sectors if s["rhi"] == 1]
    elif status_filter == "RCI":
        sites = [s for s in sites if s["rci"] == 1]
        sectors = [s for s in sectors if s["rci"] == 1]
    elif status_filter == "UNBALANCE":
        sites = [s for s in sites if s["unbalance"] == 1]
        sectors = [s for s in sectors if s["unbalance"] == 1]
    elif status_filter == "AVAILABILITY":
        sites = [s for s in sites if s["availability"] == 1]
        sectors = [s for s in sectors if s["availability"] == 1]
    elif status_filter == "PL":
        sites = [s for s in sites if s["pl"] == 1]
        sectors = [s for s in sectors if s["pl"] == 1]
    elif status_filter == "MULTI":
        sites = [s for s in sites if s["issues_count"] >= 2]
        sectors = [s for s in sectors if s["issues_count"] >= 2]

    # Recompute quick metrics for current filter view
    filtered_summary = {
        "filtered_sites": len(sites),
        "filtered_sectors": len(sectors),
        "healthy_sites": sum(1 for s in sites if s["issues_count"] == 0),
        "issue_sites": sum(1 for s in sites if s["issues_count"] > 0),
        "healthy_sectors": sum(1 for s in sectors if s["issues_count"] == 0),
        "issue_sectors": sum(1 for s in sectors if s["issues_count"] > 0),
        "cei_sites": sum(1 for s in sites if s["cei"] == 1),
        "rhi_sites": sum(1 for s in sites if s["rhi"] == 1),
        "rci_sites": sum(1 for s in sites if s["rci"] == 1),
        "unbalance_sites": sum(1 for s in sites if s["unbalance"] == 1),
        "availability_sites": sum(1 for s in sites if s["availability"] == 1),
        "pl_sites": sum(1 for s in sites if s["pl"] == 1),
    }

    return jsonify({
        "status": "success",
        "week": week,
        "summary": full_data["summary"],
        "filtered_summary": filtered_summary,
        "kabupaten_list": full_data["kabupaten_list"],
        "sites": sites,
        "sectors": sectors,
        "site_records": sites,
        "sector_records": sectors
    })


@healthy_site.route("/api/okr/healthy_site/export", methods=["GET", "POST"])
@login_required
def api_healthy_site_export():
    """Export filtered site or sector level data as CSV."""
    if request.method == "POST" and request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form.to_dict() if request.method == "POST" else request.args.to_dict()

    week_raw = payload.get("week")
    level = payload.get("level", "site").lower()  # 'site' or 'sector'
    weeks = _get_available_weeks()
    try:
        week = int(week_raw) if week_raw else (weeks[0] if weeks else 202640)
    except (ValueError, TypeError):
        week = weeks[0] if weeks else 202640

    kabupaten_filter = payload.get("kabupaten", "ALL").strip().upper()
    status_filter = payload.get("status_filter", "ALL").strip().upper()
    search = payload.get("search", "").strip().upper()

    try:
        full_data = _fetch_healthy_dataset(week)
    except Exception as e:
        logger.exception("Export failed for week %s: %s", week, e)
        return jsonify({"status": "error", "message": str(e)}), 500

    if level == "sector":
        records = full_data["sector_records"]
        id_col = "Sector ID"
        filename = f"OKR_Healthy_Sector_W{str(week)[4:]}_{week}.csv"
    else:
        records = full_data["site_records"]
        id_col = "Site ID"
        filename = f"OKR_Healthy_Site_W{str(week)[4:]}_{week}.csv"

    if kabupaten_filter and kabupaten_filter != "ALL":
        records = [r for r in records if r["kabupaten"].upper() == kabupaten_filter]

    if search:
        records = [r for r in records if search in (r.get("sector_id") or r.get("site_id")).upper() or search in r["kabupaten"].upper()]

    if status_filter == "HEALTHY":
        records = [r for r in records if r["issues_count"] == 0]
    elif status_filter == "ISSUE":
        records = [r for r in records if r["issues_count"] > 0]
    elif status_filter == "CEI":
        records = [r for r in records if r["cei"] == 1]
    elif status_filter == "RHI":
        records = [r for r in records if r["rhi"] == 1]
    elif status_filter == "RCI":
        records = [r for r in records if r["rci"] == 1]
    elif status_filter == "UNBALANCE":
        records = [r for r in records if r["unbalance"] == 1]
    elif status_filter == "AVAILABILITY":
        records = [r for r in records if r["availability"] == 1]
    elif status_filter == "PL":
        records = [r for r in records if r["pl"] == 1]
    elif status_filter == "MULTI":
        records = [r for r in records if r["issues_count"] >= 2]

    # Generate CSV in memory using StringIO -> BytesIO
    string_buffer = io.StringIO()
    writer = csv.writer(string_buffer)

    headers = [id_col, "Kabupaten", "CEI", "RHI", "RCI", "UNBALANCE", "AVAILABILITY", "PL", "Total Issues", "Remark"]
    writer.writerow(headers)

    for r in records:
        entity_id = r.get("sector_id") if level == "sector" else r.get("site_id")
        writer.writerow([
            entity_id,
            r["kabupaten"],
            r["cei"],
            r["rhi"],
            r["rci"],
            r["unbalance"],
            r["availability"],
            r["pl"],
            r["issues_count"],
            r["remark"]
        ])

    bytes_buffer = io.BytesIO()
    bytes_buffer.write(string_buffer.getvalue().encode("utf-8-sig"))
    bytes_buffer.seek(0)

    return send_file(
        bytes_buffer,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )
