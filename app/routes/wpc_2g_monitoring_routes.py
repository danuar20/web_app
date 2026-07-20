"""2G Monitoring Routes — /wpc_2g_monitoring (Daily aggregated, 5 dimension tabs via GROUPING SETS)"""
from flask import Blueprint, render_template, request, session, make_response, flash, jsonify
from app import cache
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, _no_cache, db_query
from datetime import datetime, timedelta
import psycopg2
import psycopg2.errors

wpc_2g_monitoring = Blueprint("wpc_2g_monitoring", __name__)

def make_post_cache_key(*args, **kwargs):
    import hashlib
    import json
    data = request.get_json() or {}
    key = f"{request.path}:{json.dumps(data, sort_keys=True)}"
    return "post_cache_" + hashlib.md5(key.encode('utf-8')).hexdigest()



# ── KPI Definitions ─────────────────────────────────────────────────────────────
# (chart_id, label, unit, y_min, y_max, sql_expr, is_lower_better)
ALL_KPI_DEFS = [
    ("payloadChart",       "Payload",              "GB",   None,    None,
     "SUM(total_payload)::numeric/1024",  False),
    ("tchTrafficChart",    "TCH Traffic",           "Erl",  None,    None,
     "ROUND(SUM(tch_traffic)::numeric, 2)",         False),
    ("sdcchTrafficChart",  "SDCCH Traffic",         "Erl",  None,    None,
     "ROUND(SUM(sdcch_traffic)::numeric, 2)",       False),
    ("fullRateChart",      "Full Rate Traffic",     "Erl",  None,    None,
     'ROUND(SUM("Offic_full_traffic")::numeric, 2)', False),
    ("halfRateChart",      "Half Rate Traffic",     "Erl",  None,    None,
     'ROUND(SUM("Offic_half_traffic")::numeric, 2)', False),
    ("availChart",         "Availability",          "%",    None, None,
     "CASE WHEN SUM(tch_avail_denum)>0 THEN ROUND((SUM(tch_avail_num)/SUM(tch_avail_denum)*100)::numeric,2) ELSE NULL END",
     False),
    ("cssrChart",          "CSSR",                  "%",    None, None,
     "CASE WHEN SUM(cssr_denum)>0 THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100)::numeric,2) ELSE NULL END",
     False),
    ("ccsrChart",          "CCSR",                  "%",    None, None,
     'CASE WHEN SUM("2g_ccsr_denum")>0 THEN ROUND((SUM("2g_ccsr_num")/SUM("2g_ccsr_denum")*100)::numeric,2) ELSE NULL END',
     False),
    ("hosrChart",          "HOSR",                  "%",    None, None,
     "CASE WHEN SUM(hosr_denum)>0 THEN ROUND((SUM(hosr_num)/SUM(hosr_denum)*100)::numeric,2) ELSE NULL END",
     False),
    ("sdsrChart",          "SDSR",                  "%",    None, None,
     "CASE WHEN SUM(sdsr_denum)>0 THEN ROUND((SUM(sdsr_num)/SUM(sdsr_denum)*100)::numeric,2) ELSE NULL END",
     False),
    ("tbfEstChart",        "TBF DL Est",            "%",    None, None,
     "CASE WHEN SUM(tbf_dl_est_denum)>0 THEN ROUND((SUM(tbf_dl_est_num)/SUM(tbf_dl_est_denum)*100)::numeric,2) ELSE NULL END",
     False),
    ("tbfCompChart",       "TBF Comp",              "%",    None, None,
     "CASE WHEN SUM(tbf_comp_denum)>0 THEN ROUND((SUM(tbf_comp_num)/SUM(tbf_comp_denum)*100)::numeric,2) ELSE NULL END",
     False),
    ("tchDropChart",       "TCH Drop",              "%",    None,    None,
     "CASE WHEN SUM(tch_drop_denum)>0 THEN ROUND((SUM(tch_drop_num)/SUM(tch_drop_denum)*100)::numeric,2) ELSE NULL END",
     True),
    ("tchDropNumChart",    "TCH Drop Num",          "num",     None,    None,
     "ROUND(SUM(tch_drop_num)::numeric, 0)",        True),
    ("tchBlkChart",        "TCH Blocking",          "%",    None,    None,
     "CASE WHEN SUM(tch_block_denum)>0 THEN ROUND((SUM(tch_block_num)/SUM(tch_block_denum)*100)::numeric,2) ELSE NULL END",
     True),
    ("tchBlkNumChart",     "TCH Block Num",         "num",     None,    None,
     "ROUND(SUM(tch_block_num)::numeric, 0)",       True),
    ("sdcchBlkChart",      "SDCCH Blocking",        "%",    None,    None,
     "CASE WHEN SUM(sdcch_block_denum)>0 THEN ROUND((SUM(sdcch_block_num)/SUM(sdcch_block_denum)*100)::numeric,2) ELSE NULL END",
     True),
    ("sdcchBlkNumChart",   "SDCCH Block Num",       "num",     None,    None,
     "ROUND(SUM(sdcch_block_num)::numeric, 0)",     True),
    ("fastRetChart",       "Fast Return to LTE",    "num",     None,    None,
     "ROUND(SUM(fastreturn_to_lte)::numeric, 0)",   False),
    ("icmChart",           "ICM Band 3-5",          "%",    None,    None,
     "CASE WHEN SUM(icm_band35_denum)>0 THEN ROUND((SUM(icm_band35_num)/SUM(icm_band35_denum)*100)::numeric,2) ELSE NULL END",
     True),
    ("interfChart",        "Interference",          "%",    None,    None,
     "CASE WHEN SUM(denum_icm_interference_ono)>0 THEN ROUND((SUM(num_icm_interference_ono)/SUM(denum_icm_interference_ono)*100)::numeric,2) ELSE NULL END",
     True),
    ("dlMosChart",         "DL MOS",                "mos",     None,    None,
     "ROUND(AVG(mos_dl)::numeric, 2)",              False),
    ("ulMosChart",         "UL MOS",                "mos",     None,    None,
     "ROUND(AVG(mos_ul)::numeric, 2)",              False),
    ("sdToTchChart",       "SD to TCH",             "%",    None,    None,
     "ROUND((AVG(sd_to_tch)*100)::numeric, 2)",     False),
    ("cstChart",           "CST",                   "ms",   None,    None,
     "ROUND(AVG(cst)::numeric, 2)",                 False),
    ("pdchAllocFailChart", "PDCH Alocation Fail",   "%",    None,    None,
     "CASE WHEN SUM(pdch_alocation_failure_rate_denum)>0 THEN ROUND((SUM(pdch_alocation_failure_rate_num)/SUM(pdch_alocation_failure_rate_denum)*100)::numeric,2) ELSE NULL END",
     True),
    ("dlQualChart",        "DL Qual",               "%",    None,    None,
     "CASE WHEN SUM(denum_dl_qual_0_5)>0 THEN ROUND((SUM(num_dl_qual_0_5)/SUM(denum_dl_qual_0_5)*100)::numeric,2) ELSE NULL END",
     True),
    ("ulQualChart",        "UL Qual",               "%",    None,    None,
     "CASE WHEN SUM(denum_ul_qual)>0 THEN ROUND((SUM(num_ul_qual_0_5)/SUM(denum_ul_qual)*100)::numeric,2) ELSE NULL END",
     True),
    ("gprsDlThpChart",     "GPRS DL Thp",           "Kbps", None,    None,
     "ROUND(AVG(gprs_dl_thp)::numeric, 2)",         False),
    ("edgeDlThpChart",     "EDGE DL Thp",           "Kbps", None,    None,
     "ROUND(AVG(edge_dl_thp)::numeric, 2)",         False),
    ("gprsPayloadChart",   "GPRS Payload",          "GB",   None,    None,
     "SUM(gprs_payload)::numeric/1024",             False),
    ("edgePayloadChart",   "EDGE Payload",          "GB",   None,    None,
     "SUM(edge_payload)::numeric/1024",             False),
]

DEFAULT_KPIS = [
    "payloadChart", "tchTrafficChart", "availChart", "cssrChart", "ccsrChart",
    "hosrChart", "sdsrChart", "tbfEstChart", "tbfCompChart", "tchDropChart", "tchDropNumChart",
    "tchBlkChart", "tchBlkNumChart", "sdcchBlkChart", "sdcchBlkNumChart",
    "dlMosChart", "ulMosChart", "dlQualChart", "ulQualChart", "sdToTchChart", "fastRetChart"
]


# ── Main Page Route ─────────────────────────────────────────────────────────────
@wpc_2g_monitoring.route("/wpc_2g_monitoring")
@login_required
def wpc_2g_monitoring_page():
    # Default date range: last 30 days
    today      = datetime.now().date()
    default_to = today.strftime("%Y-%m-%d")
    default_fr = (today - timedelta(days=6)).strftime("%Y-%m-%d")

    # Initial page load doesn't need to do any heavy SQL, just fetch dropdown filters
    from_date = request.args.get("from_date", default_fr)
    to_date   = request.args.get("to_date", default_to)
    
    # We just need to populate cascading dropdowns
    nsa_city_map      = {} # { nsa: [city1, city2] }
    bsc_list          = set()

    conn = None
    cur  = None
    try:
        with db_query() as (conn, cur):
            # Fetch topology for filters. We just need the unique NSA, City, BSC.
            # Using the latest available date is a good trick
            cur.execute('SELECT MAX(kpi_date) FROM "2g_kpi_zte_daily" WHERE kpi_date >= %s AND kpi_date <= %s', [from_date, to_date])
            max_date = cur.fetchone()[0]
            if max_date:
                cur.execute('SELECT nsa, city, me_name FROM "2g_kpi_zte_daily" WHERE kpi_date = %s GROUP BY nsa, city, me_name', [max_date])
                for r in cur.fetchall():
                    nsa, city, me_name = r[0], r[1], r[2]
                    if nsa and city:
                        if nsa not in nsa_city_map:
                            nsa_city_map[nsa] = set()
                        nsa_city_map[nsa].add(city)
                    if me_name:
                        bsc_list.add(me_name)
    except Exception as e:
        flash(f"Error fetching topology: {str(e)}", "danger")

    nsa_city_map_list = {k: sorted(v) for k, v in nsa_city_map.items()}
    bsc_list_sorted = sorted(bsc_list)

    return _no_cache(make_response(render_template(
        "wpc_2g_monitoring.html",
        username=session.get("username"),
        from_date=from_date,
        to_date=to_date,
        default_fr=default_fr,
        default_to=default_to,
        nsa_city_map=nsa_city_map_list,
        bsc_list=bsc_list_sorted
    )))

@wpc_2g_monitoring.route("/api/wpc_2g/wpc_data", methods=["POST"])
@login_required
def api_wpc_2g_data():
    data = request.get_json()
    from_date = data.get("from_date")
    to_date = data.get("to_date")
    level = data.get("level", "site")
    
    if not all([from_date, to_date]):
        return jsonify({"error": "Missing parameters"}), 400
        
    conn = None
    cur = None
    try:
        with db_query() as (conn, cur):
            cur.execute("SET work_mem = '1GB'")
            
            if level == 'cell':
                sql = """
                    SELECT 
                        bts_name as cell_name,
                        nsa,
                        city,
                        me_name as bsc,
                        SUM(tch_avail_num) as avail_num,
                        SUM(tch_avail_denum) as avail_denum,
                        SUM(cssr_num) as cssr_num,
                        SUM(cssr_denum) as cssr_denum,
                        SUM("2g_ccsr_num") as ccsr_num,
                        SUM("2g_ccsr_denum") as ccsr_denum,
                        SUM(hosr_num) as hosr_num,
                        SUM(hosr_denum) as hosr_denum,
                        SUM(tch_block_num) as tchblk_num,
                        SUM(tch_block_denum) as tchblk_denum,
                        SUM(sdcch_block_num) as sdblk_num,
                        SUM(sdcch_block_denum) as sdblk_denum,
                        SUM(tch_drop_num) as tch_drop_num,
                        SUM(tch_drop_denum) as tch_drop_denum,
                        SUM(tbf_dl_est_num) as tbf_dl_est_num,
                        SUM(tbf_dl_est_denum) as tbf_dl_est_denum,
                        SUM(tbf_comp_num) as tbf_comp_num,
                        SUM(tbf_comp_denum) as tbf_comp_denum
                    FROM "2g_kpi_zte_daily"
                    WHERE kpi_date >= %s::date AND kpi_date <= %s::date
                      AND bts_name IS NOT NULL
                    GROUP BY nsa, city, me_name, bts_name
                """
            else:
                sql = """
                    SELECT 
                        siteid,
                        nsa,
                        city,
                        me_name as bsc,
                        SUM(tch_avail_num) as avail_num,
                        SUM(tch_avail_denum) as avail_denum,
                        SUM(cssr_num) as cssr_num,
                        SUM(cssr_denum) as cssr_denum,
                        SUM("2g_ccsr_num") as ccsr_num,
                        SUM("2g_ccsr_denum") as ccsr_denum,
                        SUM(hosr_num) as hosr_num,
                        SUM(hosr_denum) as hosr_denum,
                        SUM(tch_block_num) as tchblk_num,
                        SUM(tch_block_denum) as tchblk_denum,
                        SUM(sdcch_block_num) as sdblk_num,
                        SUM(sdcch_block_denum) as sdblk_denum,
                        SUM(tch_drop_num) as tch_drop_num,
                        SUM(tch_drop_denum) as tch_drop_denum,
                        SUM(tbf_dl_est_num) as tbf_dl_est_num,
                        SUM(tbf_dl_est_denum) as tbf_dl_est_denum,
                        SUM(tbf_comp_num) as tbf_comp_num,
                        SUM(tbf_comp_denum) as tbf_comp_denum
                    FROM "2g_kpi_zte_daily"
                    WHERE kpi_date >= %s::date AND kpi_date <= %s::date
                      AND siteid IS NOT NULL
                    GROUP BY nsa, city, me_name, siteid
                """
            
            cur.execute(sql, [from_date, to_date])
            rows = cur.fetchall()
            
            raw_data = []
            for r in rows:
                row_dict = {
                    "nsa": r[1],
                    "city": r[2],
                    "bsc": r[3],
                    "avail_num": float(r[4]) if r[4] else 0,
                    "avail_denum": float(r[5]) if r[5] else 0,
                    "cssr_num": float(r[6]) if r[6] else 0,
                    "cssr_denum": float(r[7]) if r[7] else 0,
                    "ccsr_num": float(r[8]) if r[8] else 0,
                    "ccsr_denum": float(r[9]) if r[9] else 0,
                    "hosr_num": float(r[10]) if r[10] else 0,
                    "hosr_denum": float(r[11]) if r[11] else 0,
                    "tchblk_num": float(r[12]) if r[12] else 0,
                    "tchblk_denum": float(r[13]) if r[13] else 0,
                    "sdblk_num": float(r[14]) if r[14] else 0,
                    "sdblk_denum": float(r[15]) if r[15] else 0,
                    "tchdrop_num": float(r[16]) if r[16] else 0,
                    "tchdrop_denum": float(r[17]) if r[17] else 0,
                    "tbfdlest_num": float(r[18]) if r[18] else 0,
                    "tbfdlest_denum": float(r[19]) if r[19] else 0,
                    "tbfcomp_num": float(r[20]) if r[20] else 0,
                    "tbfcomp_denum": float(r[21]) if r[21] else 0
                }
                if level == 'cell':
                    row_dict["cell_name"] = r[0]
                else:
                    row_dict["siteid"] = r[0]
                raw_data.append(row_dict)
                
            cur.execute("RESET work_mem")
            
            return jsonify({"raw_data": raw_data})
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
