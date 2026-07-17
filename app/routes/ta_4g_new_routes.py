"""TA 4G New Routes -- /ta_4g_new
Monitoring and comparison of 4G Timing Advance distribution.
Source table: measTA4G
"""
from flask import Blueprint, render_template, request, session, make_response, jsonify
from ._utils import login_required, _no_cache, db_query
import psycopg2
import datetime
import traceback
import logging

logger = logging.getLogger(__name__)

ta4g_new = Blueprint("ta4g_new", __name__)

TA_LABELS = [
    "0-0.156", "0.156-0.312", "0.312-0.468", "0.468-0.624", "0.624-0.780",
    "0.780-0.936", "0.936-1.092", "1.092-1.638", "1.638-2.184", "2.184-2.730",
    "2.730-3.198", "3.198-3.978", "3.978-6.396", "6.396-10.140", ">10.140"
]

TA_COLUMNS = [
    '"0-0,156_km"', '"0,156-0,312_km"', '"0,312-0,468_km"', '"0,468-0,624_km"',
    '"0,624-0,780_km"', '"0,780-0,936_km"', '"0,936-1,092_km"', '"1,092-1,638_km"',
    '"1,638-2,184_km"', '"2,184-2,730_km"', '"2,730-3,198_km"', '"3,198-3,978_km"',
    '"3,978-6,396_km"', '"6,396-10,140_km"', '"TA > 10,140_km"'
]

BAND_MAP = {
    "1": "L1800", "2": "L900", "3": "L2100",
    "4": "L2300_1", "5": "L2300_2", "6": "L2300_3", "7": "L700"
}


def extract_site_id(me_name):
    if me_name and len(me_name) >= 8:
        return me_name[2:8].strip()
    return (me_name or "").strip()


def get_sector(cell_id_str):
    s = str(cell_id_str or "")
    if len(s) > 2 and s[-1] == "5":
        return s[1]
    elif len(s) > 2:
        return s[:2]
    else:
        return s[:1]


def get_band(cell_id_str):
    s = str(cell_id_str or "")
    return BAND_MAP.get(s[-1], "Unknown") if s else "Unknown"


def query_ta_data(cur, site_ids, from_date, to_date):
    """Query measTA4G and return aggregated TA data summed over date range."""
    if not site_ids or not from_date or not to_date:
        return {}

    site_filter = " OR ".join(['"ME Name" LIKE %s' for _ in site_ids])
    site_params = ["%" + s + "%" for s in site_ids]
    ta_sums = ", ".join(["COALESCE(SUM(" + col + "), 0)" for col in TA_COLUMNS])

    sql = (
        "SELECT \"ME Name\", \"Cell ID\", \"Product\", " + ta_sums + " "
        "FROM \"measTA4G\" "
        "WHERE \"Date\"::date >= %s::date "
        "  AND \"Date\"::date <= %s::date "
        "  AND (" + site_filter + ") "
        "GROUP BY \"ME Name\", \"Cell ID\", \"Product\" "
        "ORDER BY \"ME Name\", \"Cell ID\""
    )
    params = [from_date, to_date] + site_params
    cur.execute(sql, params)
    rows = cur.fetchall()

    result = {}
    for row in rows:
        me_name = row[0]
        cell_id = row[1]
        ta_vals = [float(v) if v is not None else 0.0 for v in row[3:18]]
        site_id = extract_site_id(me_name)
        try:
            cid_str = str(int(float(cell_id))) if cell_id is not None else ""
        except (ValueError, TypeError):
            cid_str = str(cell_id) if cell_id else ""
        sector = get_sector(cid_str)
        band = get_band(cid_str)
        sec_key = site_id + "_S" + sector
        if sec_key not in result:
            result[sec_key] = {}
        if band not in result[sec_key]:
            result[sec_key][band] = {
                "site_id": site_id, "sector": sector, "band": band,
                "ta_vals": [0.0] * 15, "total": 0.0
            }
        existing = result[sec_key][band]["ta_vals"]
        for i in range(15):
            existing[i] += ta_vals[i]
        result[sec_key][band]["total"] += sum(ta_vals)

    def sector_sort(item):
        key = item[0]   # item is (sec_key, bands_dict)
        parts = key.rsplit("_S", 1)
        try:
            return (parts[0], int(parts[1]))
        except Exception:
            return (key, 999)

    return dict(sorted(result.items(), key=sector_sort))


def get_sites_list(cur):
    cur.execute(
        "SELECT DISTINCT \"ME Name\" FROM \"measTA4G\" "
        "WHERE \"ME Name\" IS NOT NULL "
        "  AND \"Date\" >= CURRENT_DATE - INTERVAL '60 days' "
        "ORDER BY \"ME Name\""
    )
    raw = [r[0] for r in cur.fetchall()]
    sites = []
    for me in raw:
        sid = extract_site_id(me)
        if sid and sid not in sites:
            sites.append(sid)
    sites.sort()
    return sites


@ta4g_new.route("/api/ta_4g_query", methods=["POST"])
@login_required
def api_ta_4g_query():
    data = request.json or {}
    tab = data.get("tab", "actual")
    sel_sites = data.get("site", [])
    
    if not sel_sites:
        return jsonify({"error": "No sites selected", "actual_data": {}, "before_data": {}, "after_data": {}})
        
    actual_data = {}
    before_data = {}
    after_data = {}
    
    try:
        with db_query() as (conn, cur):
            if tab == "actual":
                from_date = data.get("from_date")
                to_date = data.get("to_date")
                actual_data = query_ta_data(cur, sel_sites, from_date, to_date)
            else:
                before_from = data.get("before_from")
                before_to = data.get("before_to")
                after_from = data.get("after_from")
                after_to = data.get("after_to")
                before_data = query_ta_data(cur, sel_sites, before_from, before_to)
                after_data = query_ta_data(cur, sel_sites, after_from, after_to)
                
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500
        
    return jsonify({
        "actual_data": actual_data,
        "before_data": before_data,
        "after_data": after_data,
        "ta_labels": TA_LABELS
    })


@ta4g_new.route("/ta_4g_new")
@login_required
def ta_4g_new_page():
    today = datetime.date.today()
    default_to = today.strftime("%Y-%m-%d")
    default_fr = (today - datetime.timedelta(days=6)).strftime("%Y-%m-%d")

    sites_list = []
    last_update = None

    try:
        with db_query() as (conn, cur):
            sites_list = get_sites_list(cur)
            try:
                cur.execute("SELECT MAX(\"Date\"::date) FROM \"measTA4G\"")
                raw = cur.fetchone()
                last_update = raw[0].strftime("%Y-%m-%d") if raw and raw[0] else None
            except Exception:
                last_update = None
    except psycopg2.OperationalError:
        session["flash"] = ("Database connection failed.", "warning")
    except Exception as e:
        logger.error("TA 4G route error: %s\n%s", e, traceback.format_exc())
        session["flash"] = ("Error: " + str(e), "danger")

    return _no_cache(make_response(render_template(
        "ta_4g_new.html",
        username    = session.get("username", "User"),
        sites_list  = sites_list,
        from_date   = default_fr,
        to_date     = default_to,
        before_from = default_fr,
        before_to   = default_to,
        after_from  = default_fr,
        after_to    = default_to,
        ta_labels   = TA_LABELS,
        last_update = last_update
    )))
