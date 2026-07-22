"""4G Monitoring Routes — /wpc_4g_monitoring (Daily aggregated, 5 dimension tabs via GROUPING SETS)"""
from flask import Blueprint, render_template, request, session, make_response, flash, jsonify
from app import cache
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, _no_cache, db_query
from datetime import datetime, timedelta
import psycopg2
import psycopg2.errors

wpc_4g_monitoring = Blueprint("wpc_4g_monitoring", __name__)

def make_post_cache_key(*args, **kwargs):
    import hashlib
    import json
    data = request.get_json() or {}
    key = f"{request.path}:{json.dumps(data, sort_keys=True)}"
    return "post_cache_" + hashlib.md5(key.encode('utf-8')).hexdigest()

# ── Main Page Route ─────────────────────────────────────────────────────────────
@wpc_4g_monitoring.route("/wpc_4g_monitoring")
@login_required
def wpc_4g_monitoring_page():
    # Default date range: last 30 days
    today      = datetime.now().date()
    default_to = today.strftime("%Y-%m-%d")
    default_fr = (today - timedelta(days=6)).strftime("%Y-%m-%d")

    from_date = request.args.get("from_date", default_fr)
    to_date   = request.args.get("to_date", default_to)
    
    # We just need to populate cascading dropdowns
    nsa_city_map      = {} # { nsa: [city1, city2] }
    sub_list          = set()

    conn = None
    cur  = None
    try:
        with db_query() as (conn, cur):
            # Fetch topology for filters. We just need the unique NSA, City, Subnetwork Name.
            cur.execute('SELECT MAX(kpi_date) FROM "4g_kpi_zte_daily" WHERE kpi_date >= %s AND kpi_date <= %s', [from_date, to_date])
            max_date = cur.fetchone()[0]
            if max_date:
                cur.execute('SELECT nsa, city, subnetwork_name FROM "4g_kpi_zte_daily" WHERE kpi_date = %s GROUP BY nsa, city, subnetwork_name', [max_date])
                for r in cur.fetchall():
                    nsa, city, subnetwork_name = r[0], r[1], r[2]
                    if nsa and city:
                        if nsa not in nsa_city_map:
                            nsa_city_map[nsa] = set()
                        nsa_city_map[nsa].add(city)
                    if subnetwork_name:
                        sub_list.add(subnetwork_name)
    except Exception as e:
        flash(f"Error fetching topology: {str(e)}", "danger")

    nsa_city_map_list = {k: sorted(v) for k, v in nsa_city_map.items()}
    sub_list_sorted = sorted(sub_list)

    return _no_cache(make_response(render_template(
        "wpc_4g_monitoring.html",
        username=session.get("username"),
        from_date=from_date,
        to_date=to_date,
        default_fr=default_fr,
        default_to=default_to,
        nsa_city_map=nsa_city_map_list,
        sub_list=sub_list_sorted
    )))

@wpc_4g_monitoring.route("/api/wpc_4g/wpc_data", methods=["POST"])
@login_required
@cache.cached(timeout=21600, key_prefix=make_post_cache_key)
def api_wpc_4g_data():
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
            cur.execute("SET jit = off")
            
            if level == 'cell':
                sql = """
                    SELECT 
                        cell_name,
                        nsa,
                        city,
                        subnetwork_name,
                        SUM(avail_num) as avail_num,
                        SUM(avail_denum) as avail_denum,
                        SUM(cssr_num) as cssr_num,
                        SUM(cssr_denum) as cssr_denum,
                        SUM(erab_setup_num) as erab_num,
                        SUM(erab_setup_denum) as erab_denum,
                        SUM(rrc_setup_num) as rrc_num,
                        SUM(rrc_setup_denum) as rrc_denum,
                        SUM(s1_signaling_sr_num) as s1_num,
                        SUM(s1_signaling_sr_denum) as s1_denum,
                        SUM(srvcc_gsm_num) as srvcc_num,
                        SUM(srvcc_gsm_denum) as srvcc_denum,
                        SUM(sdr_num) as sdr_num,
                        SUM(sdr_denum) as sdr_denum,
                        SUM(volte_call_drop_rate_mme_num) as volte_drop_num,
                        SUM(volte_call_drop_rate_mme_denum) as volte_drop_denum,
                        SUM(ifho_num) as ifho_num,
                        SUM(ifho_denum) as ifho_denum,
                        SUM(csfb_num) as csfb_num,
                        SUM(csfb_denum) as csfb_denum,
                        SUM("DL_CCE_Failure_Num") as dl_cce_num,
                        SUM("DL_CCE_Failure_Denum") as dl_cce_denum,
                        SUM("UL_CCE_Failure_Num") as ul_cce_num,
                        SUM("UL_CCE_Failure_Denum") as ul_cce_denum
                    FROM "4g_kpi_zte_daily"
                    WHERE kpi_date >= %s::date AND kpi_date <= %s::date
                      AND cell_name IS NOT NULL
                    GROUP BY nsa, city, subnetwork_name, cell_name
                """
            else:
                sql = """
                    SELECT 
                        siteid,
                        nsa,
                        city,
                        subnetwork_name,
                        SUM(avail_num) as avail_num,
                        SUM(avail_denum) as avail_denum,
                        SUM(cssr_num) as cssr_num,
                        SUM(cssr_denum) as cssr_denum,
                        SUM(erab_setup_num) as erab_num,
                        SUM(erab_setup_denum) as erab_denum,
                        SUM(rrc_setup_num) as rrc_num,
                        SUM(rrc_setup_denum) as rrc_denum,
                        SUM(s1_signaling_sr_num) as s1_num,
                        SUM(s1_signaling_sr_denum) as s1_denum,
                        SUM(srvcc_gsm_num) as srvcc_num,
                        SUM(srvcc_gsm_denum) as srvcc_denum,
                        SUM(sdr_num) as sdr_num,
                        SUM(sdr_denum) as sdr_denum,
                        SUM(volte_call_drop_rate_mme_num) as volte_drop_num,
                        SUM(volte_call_drop_rate_mme_denum) as volte_drop_denum,
                        SUM(ifho_num) as ifho_num,
                        SUM(ifho_denum) as ifho_denum,
                        SUM(csfb_num) as csfb_num,
                        SUM(csfb_denum) as csfb_denum,
                        SUM("DL_CCE_Failure_Num") as dl_cce_num,
                        SUM("DL_CCE_Failure_Denum") as dl_cce_denum,
                        SUM("UL_CCE_Failure_Num") as ul_cce_num,
                        SUM("UL_CCE_Failure_Denum") as ul_cce_denum
                    FROM "4g_kpi_zte_daily"
                    WHERE kpi_date >= %s::date AND kpi_date <= %s::date
                      AND siteid IS NOT NULL
                    GROUP BY nsa, city, subnetwork_name, siteid
                """
            
            cur.execute(sql, [from_date, to_date])
            rows = cur.fetchall()
            
            raw_data = []
            for r in rows:
                row_dict = {
                    "nsa": r[1],
                    "city": r[2],
                    "subnet": r[3],
                    "avail_num": float(r[4]) if r[4] else 0,
                    "avail_denum": float(r[5]) if r[5] else 0,
                    "cssr_num": float(r[6]) if r[6] else 0,
                    "cssr_denum": float(r[7]) if r[7] else 0,
                    "erab_num": float(r[8]) if r[8] else 0,
                    "erab_denum": float(r[9]) if r[9] else 0,
                    "rrc_num": float(r[10]) if r[10] else 0,
                    "rrc_denum": float(r[11]) if r[11] else 0,
                    "s1_num": float(r[12]) if r[12] else 0,
                    "s1_denum": float(r[13]) if r[13] else 0,
                    "srvcc_num": float(r[14]) if r[14] else 0,
                    "srvcc_denum": float(r[15]) if r[15] else 0,
                    "sdr_num": float(r[16]) if r[16] else 0,
                    "sdr_denum": float(r[17]) if r[17] else 0,
                    "volte_drop_num": float(r[18]) if r[18] else 0,
                    "volte_drop_denum": float(r[19]) if r[19] else 0,
                    "ifho_num": float(r[20]) if r[20] else 0,
                    "ifho_denum": float(r[21]) if r[21] else 0,
                    "csfb_num": float(r[22]) if r[22] else 0,
                    "csfb_denum": float(r[23]) if r[23] else 0,
                    "dl_cce_num": float(r[24]) if r[24] else 0,
                    "dl_cce_denum": float(r[25]) if r[25] else 0,
                    "ul_cce_num": float(r[26]) if r[26] else 0,
                    "ul_cce_denum": float(r[27]) if r[27] else 0
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
