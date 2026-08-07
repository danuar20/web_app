"""TA 5G Routes -- /ta_5g
Monitoring and comparison of 5G NR Timing Advance distribution.
Source table: measTA5G
"""
from flask import Blueprint, render_template, request, session, make_response, jsonify
from ._utils import login_required, _no_cache, db_query
import psycopg2
import datetime
import traceback
import logging
import re

logger = logging.getLogger(__name__)

ta5g = Blueprint("ta5g", __name__)

# 18 distance labels matching the MSG2 TA mapping
TA_LABELS_5G = [
    "0-78m", "78-234m", "234-390m", "390-546m", "546-702m",
    "702-858m", "858-1014m", "1.0-1.56km", "1.56-2.1km", "2.1-2.65km",
    "2.65-3.1km", "3.1-3.9km", "3.9-6.3km", "6.3-10km", "10-14km",
    "14-20km", "20-30km", "30-40km"
]

# Max distance (in km) for each bucket, used by analysis table
TA_MAX_DIST_5G = [
    0.078, 0.234, 0.390, 0.546, 0.702,
    0.858, 1.014, 1.56, 2.1, 2.65,
    3.1, 3.9, 6.3, 10.0, 14.0,
    20.0, 30.0, 40.0
]

# SQL column names matching the measTA5G table
TA_COLUMNS_5G = [
    '"Normal Distribution of TA values in MSG2 messages[0,1)"',
    '"Normal Distribution of TA values in MSG2 messages[1,3)"',
    '"Normal Distribution of TA values in MSG2 messages[3,5)"',
    '"Normal Distribution of TA values in MSG2 messages[5,7)"',
    '"Normal Distribution of TA values in MSG2 messages[7,9)"',
    '"Normal Distribution of TA values in MSG2 messages[9,11)"',
    '"Normal Distribution of TA values in MSG2 messages[11,13)"',
    '"Normal Distribution of TA values in MSG2 messages[13,20)"',
    '"Normal Distribution of TA values in MSG2 messages[20,27)"',
    '"Normal Distribution of TA values in MSG2 messages[27,34)"',
    '"Normal Distribution of TA values in MSG2 messages[34,40)"',
    '"Normal Distribution of TA values in MSG2 messages[40,50)"',
    '"Normal Distribution of TA values in MSG2 messages[50,81)"',
    '"Normal Distribution of TA values in MSG2 messages[81,129)"',
    '"Normal Distribution of TA values in MSG2 messages[129,179)"',
    '"Normal Distribution of TA values in MSG2 messages[179,256)"',
    '"Normal Distribution of TA values in MSG2 messages[256,384)"',
    '"Normal Distribution of TA values in MSG2 messages[384,512)"'
]

NUM_BUCKETS = len(TA_COLUMNS_5G)  # 18

# Band mapping — last digit of NRPhysicalCellDU ID
BAND_MAP_5G = {
    "1": "NR1800", "2": "NR900", "3": "NR2100",
    "4": "NR2300_1", "5": "NR2300_2", "6": "NR2300_3", "7": "NR700"
}


def extract_site_id(me_name):
    """Extract 6-char site ID from Managed Element, e.g. 'C_JAP050' -> 'JAP050'."""
    if me_name and len(me_name) >= 8:
        return me_name[2:8].strip()
    return (me_name or "").strip()


def get_sector(cell_du_id_str):
    """Derive sector number from NRPhysicalCellDU ID (numeric like 14, 24, 34, 1)."""
    s = str(cell_du_id_str or "")
    if len(s) > 2 and s[-1] == "5":
        return s[1]
    elif len(s) > 2:
        return s[:2]
    else:
        return s[:1]


def get_band(cell_du_id_str):
    """Derive band from the last digit of NRPhysicalCellDU ID."""
    s = str(cell_du_id_str or "")
    return BAND_MAP_5G.get(s[-1], "Unknown") if s else "Unknown"


def extract_sector_code(cell_du_name, siteid=""):
    """Extract two-letter sector code from NRPhysicalCellDU Name.
    E.g. 'C_JAP050IP1_AirportSentani_IP01' -> 'IP'
         'C_JAP028TP1_AirportSentani2_TP02' -> 'TP'
    """
    if not cell_du_name:
        return ""
    cn = str(cell_du_name).strip()
    m = re.search(r'_([A-Za-z]{2})\d+$', cn)
    if m:
        return m.group(1).upper()
    if siteid:
        m = re.search(re.escape(str(siteid)) + r'([A-Za-z]{2})\d', cn, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    m = re.search(r'[A-Za-z]{3}\d{3}([A-Za-z]{2})', cn)
    if m:
        return m.group(1).upper()
    return ""


def get_sector_type(sector_code):
    """Indoor if sector code starts with 'I', otherwise Macro."""
    if sector_code and sector_code.upper().startswith("I"):
        return "Indoor"
    return "Macro"


def query_ta_data(cur, site_ids, from_date, to_date):
    """Query measTA5G and return aggregated TA data summed over date range."""
    if not site_ids or not from_date or not to_date:
        return {}

    site_filter = " OR ".join(['"Managed Element" LIKE %s' for _ in site_ids])
    site_params = ["%" + s + "%" for s in site_ids]
    ta_sums = ", ".join(["COALESCE(SUM(" + col + "), 0)" for col in TA_COLUMNS_5G])

    sql = (
        'SELECT "Managed Element", "NRPhysicalCellDU ID", "NRPhysicalCellDU Name", ' + ta_sums + " "
        'FROM "measTA5G" '
        'WHERE "Date"::date >= %s::date '
        '  AND "Date"::date <= %s::date '
        "  AND (" + site_filter + ") "
        'GROUP BY "Managed Element", "NRPhysicalCellDU ID", "NRPhysicalCellDU Name" '
        'ORDER BY "Managed Element", "NRPhysicalCellDU ID"'
    )
    params = [from_date, to_date] + site_params
    cur.execute(sql, params)
    rows = cur.fetchall()

    result = {}
    for row in rows:
        me_name = row[0]
        cell_du_id = row[1]
        cell_du_name = row[2] or ""
        ta_vals = [float(v) if v is not None else 0.0 for v in row[3:3 + NUM_BUCKETS]]
        site_id = extract_site_id(me_name)
        try:
            cid_str = str(int(float(cell_du_id))) if cell_du_id is not None else ""
        except (ValueError, TypeError):
            cid_str = str(cell_du_id) if cell_du_id else ""
        sector = get_sector(cid_str)
        band = get_band(cid_str)
        sec_key = site_id + "_S" + sector

        sec_code = extract_sector_code(cell_du_name, site_id)
        sec_type = get_sector_type(sec_code)

        if sec_key not in result:
            result[sec_key] = {}

        b_key = band
        if band in result[sec_key] and result[sec_key][band].get("sector_code") != sec_code:
            exist_old = result[sec_key].pop(band)
            exist_code = exist_old.get("sector_code", "")
            exist_bkey = f"{band} {exist_code}" if exist_code else f"{band}_1"
            result[sec_key][exist_bkey] = exist_old
            b_key = f"{band} {sec_code}" if sec_code else f"{band}_2"
        elif any(k.startswith(band + " ") for k in result[sec_key]):
            b_key = f"{band} {sec_code}" if sec_code else band

        if b_key not in result[sec_key]:
            result[sec_key][b_key] = {
                "site_id": site_id, "sector": sector, "band": band,
                "cell_name": cell_du_name, "sector_code": sec_code, "sector_type": sec_type,
                "ta_vals": [0.0] * NUM_BUCKETS, "total": 0.0
            }
        existing = result[sec_key][b_key]["ta_vals"]
        for i in range(NUM_BUCKETS):
            existing[i] += ta_vals[i]
        result[sec_key][b_key]["total"] += sum(ta_vals)

    def sector_sort(item):
        key = item[0]
        parts = key.rsplit("_S", 1)
        try:
            return (parts[0], int(parts[1]))
        except Exception:
            return (key, 999)

    return dict(sorted(result.items(), key=sector_sort))


def get_sites_list(cur):
    cur.execute(
        'SELECT DISTINCT "Managed Element" FROM "measTA5G" '
        'WHERE "Managed Element" IS NOT NULL '
        "  AND \"Date\" >= CURRENT_DATE - INTERVAL '60 days' "
        'ORDER BY "Managed Element"'
    )
    raw = [r[0] for r in cur.fetchall()]
    sites = []
    for me in raw:
        sid = extract_site_id(me)
        if sid and sid not in sites:
            sites.append(sid)
    sites.sort()
    return sites


@ta5g.route("/api/ta_5g_query", methods=["POST"])
@login_required
def api_ta_5g_query():
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
        "ta_labels": TA_LABELS_5G,
        "ta_max_dist": TA_MAX_DIST_5G
    })


@ta5g.route("/ta_5g")
@login_required
def ta_5g_page():
    today = datetime.date.today()
    default_to = today.strftime("%Y-%m-%d")
    default_fr = (today - datetime.timedelta(days=6)).strftime("%Y-%m-%d")

    sites_list = []
    last_update = None

    try:
        with db_query() as (conn, cur):
            sites_list = get_sites_list(cur)
            try:
                cur.execute('SELECT MAX("Date"::date) FROM "measTA5G"')
                raw = cur.fetchone()
                last_update = raw[0].strftime("%Y-%m-%d") if raw and raw[0] else None
            except Exception:
                last_update = None
    except psycopg2.OperationalError:
        session["flash"] = ("Database connection failed.", "warning")
    except Exception as e:
        logger.error("TA 5G route error: %s\n%s", e, traceback.format_exc())
        session["flash"] = ("Error: " + str(e), "danger")

    return _no_cache(make_response(render_template(
        "ta_5g.html",
        username    = session.get("username", "User"),
        sites_list  = sites_list,
        from_date   = default_fr,
        to_date     = default_to,
        before_from = default_fr,
        before_to   = default_to,
        after_from  = default_fr,
        after_to    = default_to,
        ta_labels   = TA_LABELS_5G,
        ta_max_dist = TA_MAX_DIST_5G,
        last_update = last_update
    )))
