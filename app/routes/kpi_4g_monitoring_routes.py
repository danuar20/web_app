"""4G Monitoring Routes — /kpi_4g_monitoring"""
from flask import Blueprint, render_template, request, session, make_response, flash, jsonify
from app import cache
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, _no_cache, db_query
from datetime import datetime, timedelta
import psycopg2
import psycopg2.errors

kpi4g_monitoring = Blueprint("kpi4g_monitoring", __name__)

def make_post_cache_key(*args, **kwargs):
    import hashlib
    import json
    data = request.get_json() or {}
    key = f"{request.path}:{json.dumps(data, sort_keys=True)}"
    return "post_cache_" + hashlib.md5(key.encode('utf-8')).hexdigest()



# ── KPI Definitions ─────────────────────────────────────────────────────────────
# (chart_id, label, unit, y_min, y_max, sql_expr, is_lower_better)
ALL_KPI_DEFS = [
    ("payloadChart", "Payload", "GB", None, None, 'ROUND((SUM("4g_payload_mb") / 1024.0)::numeric, 3)', False),
    ("dlPayloadChart", "DL Payload", "GB", None, None, 'ROUND((SUM(dl_traffic_volume) / 1024.0)::numeric, 3)', False),
    ("ulPayloadChart", "UL Payload", "GB", None, None, 'ROUND((SUM(ul_traffic_volume) / 1024.0)::numeric, 3)', False),
    ("dlPayloadCaChart", "DL Payload CA", "GB", None, None, 'ROUND((SUM(dl_payload_ca_mbyte) / 1024.0)::numeric, 3)', False),
    ("ulPayloadCaChart", "UL Payload CA", "GB", None, None, 'ROUND((SUM(ul_payload_ca_mbyte) / 1024.0)::numeric, 3)', False),
    ("volteTrafficChart", "VoLTE Traffic", "Erl", None, None, 'SUM(volte_traffic)', False),
    ("rrcChart", "Max RRC User", "Users", None, None, 'SUM(max_rrc_conn_user)', False),
    ("activeUserChart", "Active Users", "Users", None, None, 'SUM(new_active_users)', False),
    ("availChart", "Availability", "%", None, None, 'CASE WHEN SUM(avail_denum) > 0 THEN ROUND((SUM(avail_num) / SUM(avail_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("cssrChart", "CSSR", "%", None, None, 'CASE WHEN SUM(cssr_denum) > 0 THEN ROUND((SUM(cssr_num) / SUM(cssr_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("erabSrChart", "E-RAB SR", "%", None, None, 'CASE WHEN SUM(erab_setup_denum) > 0 THEN ROUND((SUM(erab_setup_num) / SUM(erab_setup_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("rrcSrChart", "RRC SR", "%", None, None, 'CASE WHEN SUM(rrc_setup_denum) > 0 THEN ROUND((SUM(rrc_setup_num) / SUM(rrc_setup_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("s1SrChart", "S1 SR", "%", None, None, 'CASE WHEN SUM(s1_signaling_sr_denum) > 0 THEN ROUND((SUM(s1_signaling_sr_num) / SUM(s1_signaling_sr_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("srvcc2gChart", "SRVCC 2G", "%", None, None, 'CASE WHEN SUM(srvcc_gsm_denum) > 0 THEN ROUND((SUM(srvcc_gsm_num) / SUM(srvcc_gsm_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("sdrChart", "SDR", "%", None, None, 'CASE WHEN SUM(sdr_denum) > 0 THEN ROUND((SUM(sdr_num) / SUM(sdr_denum) * 100.0)::numeric, 2) ELSE NULL END', True),
    ("erabDropChart", "ERAB Drop", "%", None, None, 'CASE WHEN SUM(erab_drop_denum) > 0 THEN ROUND((SUM(erab_drop_num) / SUM(erab_drop_denum) * 100.0)::numeric, 2) ELSE NULL END', True),
    ("volteDropChart", "VoLTE Call Drop", "%", None, None, 'CASE WHEN SUM(volte_call_drop_rate_mme_denum) > 0 THEN ROUND((SUM(volte_call_drop_rate_mme_num) / SUM(volte_call_drop_rate_mme_denum) * 100.0)::numeric, 2) ELSE NULL END', True),
    ("ifhoChart", "IFHO", "%", None, None, 'CASE WHEN SUM(ifho_denum) > 0 THEN ROUND((SUM(ifho_num) / SUM(ifho_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("intraFreqHoChart", "Intra Freq HO", "%", None, None, 'CASE WHEN SUM(inta_rat_ifho_denum) > 0 THEN ROUND((SUM(inta_rat_ifho_num) / SUM(inta_rat_ifho_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("dlPrbChart", "DL PRB", "%", None, None, 'CASE WHEN SUM(dl_prb_util_denum) > 0 THEN ROUND((SUM(dl_prb_util_num) / SUM(dl_prb_util_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("ulPrbChart", "UL PRB", "%", None, None, 'CASE WHEN SUM(ul_prb_util_denum) > 0 THEN ROUND((SUM(ul_prb_util_num) / SUM(ul_prb_util_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("dlThpChart", "User DL Thp", "Mbps", None, None, 'CASE WHEN SUM(user_dl_thp_denum) > 0 THEN ROUND((SUM(user_dl_thp_num) / SUM(user_dl_thp_denum) / 1000.0)::numeric, 2) ELSE NULL END', False),
    ("ulThpChart", "User UL Thp", "Mbps", None, None, 'CASE WHEN SUM(user_ul_thp_denum) > 0 THEN ROUND((SUM(user_ul_thp_num) / SUM(user_ul_thp_denum) / 1000.0)::numeric, 2) ELSE NULL END', False),
    ("seChart", "SE", "", None, None, 'CASE WHEN SUM(se_v3_denum) > 0 THEN ROUND((SUM(se_v3_num) / SUM(se_v3_denum))::numeric, 2) ELSE NULL END', False),
    ("cqiChart", "CQI", "", None, None, 'CASE WHEN SUM(denum_average_cqi) > 0 THEN ROUND((SUM(num_average_cqi) / SUM(denum_average_cqi))::numeric, 2) ELSE NULL END', False),
    ("csfbChart", "CSFB", "%", None, None, 'CASE WHEN SUM(csfb_denum) > 0 THEN ROUND((SUM(csfb_num) / SUM(csfb_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("dlMcsAvgChart", "DL MCS Average", "", None, None, 'CASE WHEN SUM(denum_dl_avg_mcs) > 0 THEN ROUND((SUM(num_dl_avg_mcs) / SUM(denum_dl_avg_mcs))::numeric, 2) ELSE NULL END', False),
    ("ulMcsAvgChart", "UL MCS Average", "", None, None, 'CASE WHEN SUM(denum_ul_avg_mcs) > 0 THEN ROUND((SUM(num_ul_avg_mcs) / SUM(denum_ul_avg_mcs))::numeric, 2) ELSE NULL END', False),
    ("agg8Chart", "Agg8", "%", None, None, 'CASE WHEN SUM(denum_agg8) > 0 THEN ROUND((SUM(num_agg8) / SUM(denum_agg8) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("dlCceFailChart", "DL CCE Failure", "%", None, None, 'CASE WHEN SUM("DL_CCE_Failure_Denum") > 0 THEN ROUND((SUM("DL_CCE_Failure_Num") / SUM("DL_CCE_Failure_Denum") * 100.0)::numeric, 2) ELSE NULL END', True),
    ("ulCceFailChart", "UL CCE Failure", "%", None, None, 'CASE WHEN SUM("UL_CCE_Failure_Denum") > 0 THEN ROUND((SUM("UL_CCE_Failure_Num") / SUM("UL_CCE_Failure_Denum") * 100.0)::numeric, 2) ELSE NULL END', True),
    ("badRsrpChart", "Bad RSRP (<-105)", "%", None, None, 'CASE WHEN SUM(denum_rsrp_dbm) > 0 THEN ROUND((SUM(num_rsrp_dbm) / SUM(denum_rsrp_dbm) * 100.0)::numeric, 2) ELSE NULL END', True),
    ("goodRsrpChart", "Good RSRP (>-105)", "%", None, None, 'CASE WHEN SUM("Good_RSRP (>-105) Ratio Denum") > 0 THEN ROUND((SUM("Good_RSRP (>-105) Ratio Num") / SUM("Good_RSRP (>-105) Ratio Denum") * 100.0)::numeric, 2) ELSE NULL END', False),
    ("bsrAttemptChart", "BSR Attempt", "", None, None, 'SUM("Number of Outgoing HO Preparation Attempts(based UL Service)")', False),
    ("bsrSrChart", "BSR SR", "%", None, None, 'CASE WHEN SUM("Number of Outgoing HO Preparation Attempts(based UL Service)") > 0 THEN ROUND((SUM("Number of Outgoing HO Success(based UL Service)") / SUM("Number of Outgoing HO Preparation Attempts(based UL Service)") * 100.0)::numeric, 2) ELSE NULL END', False),
    ("avgCpuChart", "Avg CPU Util", "%", None, None, 'ROUND((AVG(average_cpu_utilization) * 100.0)::numeric, 2)', False),
    ("peakCpuChart", "Peak CPU Util", "%", None, None, 'ROUND((AVG(peak_cpu_utilization) * 100.0)::numeric, 2)', False),
    ("avgRsrpChart", "Avg RSRP", "dBm", None, None, 'ROUND(AVG(avg_rsrp_dbm)::numeric, 0)', False),
    ("avgRsrqChart", "Avg RSRQ", "dB", None, None, 'ROUND(AVG("Average of RSRQ Value of Serving Cell(period measurement)(dB)")::numeric, 0)', False),
    ("avgRssiChart", "Avg Rssi", "dBm", None, None, 'ROUND(AVG(avg_cell_rssi)::numeric, 0)', False),
    ("avgNiChart", "Avg Ni", "dBm", None, None, 'ROUND(AVG(average_ni_of_carrier)::numeric, 0)', False),
    ("avgPucchChart", "Avg Pucch Ni", "dBm", None, None, 'ROUND(AVG(pucch_avg_ni_of_carrier)::numeric, 0)', False),
    ("avgPuschChart", "Avg Pusch Ni", "dBm", None, None, 'ROUND(AVG(pusch_avg_ni_of_carrier)::numeric, 0)', False),
    ("ulBlerChart", "UL Bler", "%", None, None, 'ROUND((AVG(cell_uplink_init_bler) * 100.0)::numeric, 2)', True),
    ("dlBlerChart", "DL Bler", "%", None, None, 'ROUND((AVG(cell_downlink_init_bler) * 100.0)::numeric, 2)', True),
    ("pagingDiscardedChart", "Paging Discarded", "%", None, None, 'CASE WHEN SUM(number_of_paging_records_received_by_the_enodeb) > 0 THEN ROUND((SUM(number_of_paging_records_discarded_at_the_enodeb) / SUM(number_of_paging_records_received_by_the_enodeb) * 100.0)::numeric, 2) ELSE NULL END', True),
    ("procDelayChart", "Processing Delay", "ms", None, None, 'CASE WHEN SUM(processing_delay_denum) > 0 THEN ROUND((SUM(processing_delay_num) / SUM(processing_delay_denum))::numeric, 2) ELSE NULL END', True),
]

DEFAULT_KPIS = [
    "payloadChart", "dlPayloadChart", "ulPayloadChart", "volteTrafficChart", 
    "rrcChart", "activeUserChart", "availChart", "cssrChart", "erabSrChart", 
    "rrcSrChart", "s1SrChart", "sdrChart", "erabDropChart", "ifhoChart", 
    "dlPrbChart", "ulPrbChart", "dlThpChart", "ulThpChart", "seChart", 
    "cqiChart", "csfbChart"
]

# ── Main Page Route ─────────────────────────────────────────────────────────────
@kpi4g_monitoring.route("/kpi_4g_monitoring")
@login_required
def kpi_4g_monitoring():
    today = datetime.now().date()
    default_to = today.strftime("%Y-%m-%d")
    default_fr = (today - timedelta(days=29)).strftime("%Y-%m-%d")

    from_date  = request.args.get("from_date", "")
    to_date    = request.args.get("to_date",   "")
    submitted  = request.args.get("submitted", "0") == "1"
    sel_kpis   = request.args.getlist("kpi")

    if not sel_kpis and not submitted:
        sel_kpis = DEFAULT_KPIS
    elif not sel_kpis and submitted:
        sel_kpis = [] # User explicitly checked none

    kpi_defs = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]

    chart_labels      = []
    regional_data     = {}
    nop_data          = {}
    city_data         = {}
    subnet_data       = {}
    site_data         = {}
    
    nsa_city_map      = {} 
    city_subnet_map   = {}
    subnet_city_map   = {}
    city_site_map     = {} 
    subnet_site_map   = {}
    
    nop_dims_set      = set()
    city_dims_set     = set()
    subnet_dims_set   = set()
    site_dims_set     = set()
    
    last_update       = None
    query_done        = False

    cache_key = None
    if submitted and from_date and to_date and kpi_defs:
        kpi_names = "-".join(sorted([k[0] for k in kpi_defs]))
        cache_key = f"4g_mon_data_{from_date}_{to_date}_{kpi_names}"

    cached_data = cache.get(cache_key) if cache_key else None
    
    if cached_data:
        (regional_data, nop_data, city_data, subnet_data, site_data, 
         nsa_city_map, city_subnet_map, subnet_city_map, city_site_map, subnet_site_map, 
         nop_dims_set, city_dims_set, subnet_dims_set, site_dims_set, 
         chart_labels, last_update, query_done) = cached_data
    elif submitted and from_date and to_date and kpi_defs:
        conn = None
        cur  = None
        try:
            with db_query() as (conn, cur):

                try:
                    cur.execute('SELECT MAX(kpi_date) FROM "4g_kpi_zte_daily"')
                    raw = cur.fetchone()
                    last_update = raw[0].strftime('%Y-%m-%d') if raw and raw[0] else None
                except Exception:
                    last_update = None

                kpi_cols = ",\n                ".join([k[0] for k in kpi_defs])
            
                kpi_selects = ",\n            ".join([f"{k[5]} AS {k[0]}" for k in kpi_defs])
                
                sql = f"""
                SELECT day, g_nsa, g_city, g_subnet, g_site, nsa, city, subnet, siteid, {kpi_cols} FROM (
                    SELECT kpi_date as day, 1 as g_nsa, 1 as g_city, 1 as g_subnet, 1 as g_site, 'Unknown' as nsa, 'Unknown' as city, 'Unknown' as subnet, 'Unknown' as siteid, {kpi_selects}
                    FROM "4g_kpi_zte_daily" WHERE kpi_date >= %s::date AND kpi_date <= %s::date GROUP BY kpi_date
                    UNION ALL
                    SELECT kpi_date as day, 0 as g_nsa, 1 as g_city, 1 as g_subnet, 1 as g_site, COALESCE(nsa, 'Unknown') as nsa, 'Unknown' as city, 'Unknown' as subnet, 'Unknown' as siteid, {kpi_selects}
                    FROM "4g_kpi_zte_daily" WHERE kpi_date >= %s::date AND kpi_date <= %s::date GROUP BY kpi_date, nsa
                    UNION ALL
                    SELECT kpi_date as day, 0 as g_nsa, 0 as g_city, 1 as g_subnet, 1 as g_site, COALESCE(nsa, 'Unknown') as nsa, COALESCE(city, 'Unknown') as city, 'Unknown' as subnet, 'Unknown' as siteid, {kpi_selects}
                    FROM "4g_kpi_zte_daily" WHERE kpi_date >= %s::date AND kpi_date <= %s::date GROUP BY kpi_date, nsa, city
                    UNION ALL
                    SELECT kpi_date as day, 1 as g_nsa, 1 as g_city, 0 as g_subnet, 1 as g_site, 'Unknown' as nsa, 'Unknown' as city, COALESCE(subnetwork_name, 'Unknown') as subnet, 'Unknown' as siteid, {kpi_selects}
                    FROM "4g_kpi_zte_daily" WHERE kpi_date >= %s::date AND kpi_date <= %s::date GROUP BY kpi_date, subnetwork_name
                    UNION ALL
                    SELECT kpi_date as day, 1 as g_nsa, 0 as g_city, 0 as g_subnet, 1 as g_site, 'Unknown' as nsa, COALESCE(city, 'Unknown') as city, COALESCE(subnetwork_name, 'Unknown') as subnet, 'Unknown' as siteid, {kpi_selects}
                    FROM "4g_kpi_zte_daily" WHERE kpi_date >= %s::date AND kpi_date <= %s::date GROUP BY kpi_date, subnetwork_name, city
                ) sub
                """
            
                params = [from_date, to_date] * 5
                cur.execute(sql, params)
                rows = cur.fetchall()

            
                days_set = set()
            
                temp_regional = {k[0]: {} for k in kpi_defs}
                temp_nop      = {k[0]: {} for k in kpi_defs}
                temp_city     = {k[0]: {} for k in kpi_defs}
                temp_subnet   = {k[0]: {} for k in kpi_defs}
            
                for row in rows:
                    day_str = row[0].strftime("%Y-%m-%d") if row[0] else ""
                    days_set.add(day_str)
                
                    g_nsa, g_city, g_subnet, g_site = row[1], row[2], row[3], row[4]
                    nsa, city, subnet, siteid = row[5], row[6], row[7], row[8]
                
                    kpi_vals = {}
                    for idx, k in enumerate(kpi_defs):
                        v = row[9 + idx]
                        kpi_vals[k[0]] = round(float(v), 2) if v is not None else None

                    # Regional (g_nsa=1, g_city=1, g_site=1)
                    if g_nsa == 1 and g_city == 1 and g_site == 1 and g_subnet == 1:
                        dim_val = "Regional"
                        for k in kpi_defs:
                            if dim_val not in temp_regional[k[0]]:
                                temp_regional[k[0]][dim_val] = {}
                            temp_regional[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                        
                    # NOP (g_nsa=0, g_city=1, g_site=1)
                    elif g_nsa == 0 and g_city == 1 and g_site == 1 and g_subnet == 1:
                        dim_val = nsa
                        nop_dims_set.add(dim_val)
                        for k in kpi_defs:
                            if dim_val not in temp_nop[k[0]]:
                                temp_nop[k[0]][dim_val] = {}
                            temp_nop[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                        
                    # City (g_nsa=0, g_city=0, g_site=1, g_subnet=1)
                    elif g_nsa == 0 and g_city == 0 and g_site == 1 and g_subnet == 1:
                        dim_val = city
                        city_dims_set.add(dim_val)
                        if nsa not in nsa_city_map: nsa_city_map[nsa] = set()
                        nsa_city_map[nsa].add(city)
                        for k in kpi_defs:
                            if dim_val not in temp_city[k[0]]:
                                temp_city[k[0]][dim_val] = {}
                            temp_city[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                        
                    # Subnet (g_nsa=1, g_city=1, g_site=1, g_subnet=0)
                    elif g_nsa == 1 and g_city == 1 and g_site == 1 and g_subnet == 0:
                        dim_val = subnet
                        subnet_dims_set.add(dim_val)
                        for k in kpi_defs:
                            if dim_val not in temp_subnet[k[0]]:
                                temp_subnet[k[0]][dim_val] = {}
                            temp_subnet[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                        
                    # Subnet Split by City (g_nsa=1, g_city=0, g_site=1, g_subnet=0)
                    elif g_nsa == 1 and g_city == 0 and g_site == 1 and g_subnet == 0:
                        dim_val = f"{subnet}|{city}"
                        subnet_dims_set.add(dim_val)
                        for k in kpi_defs:
                            if dim_val not in temp_subnet[k[0]]:
                                temp_subnet[k[0]][dim_val] = {}
                            temp_subnet[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                        
                chart_labels = sorted(days_set)
            
                def align_data(temp_dict, dims):
                    res = {}
                    for k_id, dim_dict in temp_dict.items():
                        res[k_id] = {}
                        for dim in dims:
                            res[k_id][dim] = [dim_dict.get(dim, {}).get(d) for d in chart_labels]
                    return res
            
                regional_data = align_data(temp_regional, ["Regional"])
                nop_data      = align_data(temp_nop, sorted(nop_dims_set))
                city_data     = align_data(temp_city, sorted(city_dims_set))
                subnet_data   = align_data(temp_subnet, sorted(subnet_dims_set))

                cur.execute('SELECT MAX(kpi_date) FROM "4g_kpi_zte_daily" WHERE kpi_date >= %s::date AND kpi_date <= %s::date', [from_date, to_date])
                max_date = cur.fetchone()[0]
            
                if max_date:
                    cur.execute("""
                        SELECT city, subnetwork_name, siteid 
                        FROM "4g_kpi_zte_daily" 
                        WHERE kpi_date = %s::date 
                        GROUP BY city, subnetwork_name, siteid
                    """, [max_date])
                
                    for r in cur.fetchall():
                        c, sub, s = r[0], r[1], r[2]
                        if c not in city_site_map: city_site_map[c] = set()
                        city_site_map[c].add(s)
                    
                        if c not in city_subnet_map: city_subnet_map[c] = set()
                        if sub: city_subnet_map[c].add(sub)
                    
                        if sub:
                            if sub not in subnet_site_map: subnet_site_map[sub] = set()
                            subnet_site_map[sub].add(s)
                        
                            if sub not in subnet_city_map: subnet_city_map[sub] = set()
                            subnet_city_map[sub].add(c)

                query_done = True
        except psycopg2.OperationalError:
            flash("Database connection failed. Please try again.", "warning")
        except psycopg2.errors.QueryCanceled:
            flash("Query timed out. Try a shorter date range or fewer KPIs.", "warning")
        except psycopg2.errors.ConnectionDoesNotExist:
            flash("Database server unreachable. Please try again later.", "warning")
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")

    nsa_city_map_list = {k: sorted(v) for k, v in nsa_city_map.items()}
    city_subnet_map_list = {k: sorted(v) for k, v in city_subnet_map.items()}
    subnet_city_map_list = {k: sorted(v) for k, v in subnet_city_map.items() if k}
    city_site_map_list = {k: sorted(v) for k, v in city_site_map.items()}
    subnet_site_map_list = {k: sorted(v) for k, v in subnet_site_map.items()}

    return _no_cache(make_response(render_template(
        "kpi_4g_monitoring.html",
        username=session.get("username", "User"),
        from_date=from_date or default_fr,
        to_date=to_date or default_to,
        default_fr=default_fr,
        default_to=default_to,
        sel_kpis=sel_kpis,
        all_kpis=ALL_KPI_DEFS,
        kpi_defs=[(k[0], k[1], k[2], k[3], k[4], k[5]) for k in kpi_defs],
        chart_labels=chart_labels,
        regional_dims=["Regional"],
        regional_data=regional_data,
        nop_dims=sorted(nop_dims_set),
        nop_data=nop_data,
        city_dims=sorted(city_dims_set),
        city_data=city_data,
        subnet_dims=sorted(subnet_dims_set),
        subnet_data=subnet_data,
        site_dims=[],
        site_data={},
        nsa_city_map=nsa_city_map_list,
        city_subnet_map=city_subnet_map_list,
        subnet_city_map=subnet_city_map_list,
        city_site_map=city_site_map_list,
        subnet_site_map=subnet_site_map_list,
        last_update=last_update,
        query_done=query_done,
    )))

@kpi4g_monitoring.route("/api/kpi_4g_monitoring/hourly", methods=["POST"])
@login_required
@cache.cached(timeout=21600, make_cache_key=make_post_cache_key)
def api_kpi_4g_monitoring_hourly():
    data = request.get_json()
    from_date = data.get("from_date")
    to_date = data.get("to_date")
    tab = data.get("tab") 
    entities = data.get("entities", [])
    kpi_ids = data.get("kpis", [])
    granularity = data.get("granularity", "hourly")
    
    if not all([from_date, to_date, tab, kpi_ids]):
        return jsonify({"error": "Missing parameters"}), 400
        
    kpi_defs = [k for k in ALL_KPI_DEFS if k[0] in kpi_ids]
    if not kpi_defs:
        return jsonify({"error": "Invalid KPIs"}), 400
        
    conn = None
    cur = None
    try:
        with db_query() as (conn, cur):
        
            kpi_selects = ",\n            ".join([f"{k[5]} AS {k[0]}" for k in kpi_defs])
        
            if tab == "regional":
                group_col = "'Regional'"
                where_clause = ""
                params = [from_date, to_date]
            elif tab == "nop":
                group_col = "nsa"
                where_clause = "AND nsa = ANY(%s)"
                params = [from_date, to_date, entities]
            elif tab == "city":
                group_col = "city"
                where_clause = "AND city = ANY(%s)"
                params = [from_date, to_date, entities]
            elif tab == "subnet":
                group_col = "subnetwork_name"
                where_clause = "AND subnetwork_name = ANY(%s)"
                params = [from_date, to_date, entities]
            elif tab == "site":
                group_col = "siteid"
                where_clause = "AND siteid = ANY(%s)"
                params = [from_date, to_date, entities]
            else:
                return jsonify({"error": "Invalid tab"}), 400
            
            if granularity == 'hourly':
                date_col = "TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI')"
                group_by = "datehour, dt_label, dimension"
                order_by = "datehour"
                table_name = '"4g_kpi_zte"'
                date_filter_col = 'date'
            else:
                date_col = "TO_CHAR(kpi_date, 'YYYY-MM-DD')"
                group_by = "kpi_date, dt_label, dimension"
                order_by = "kpi_date"
                table_name = '"4g_kpi_zte_daily"'
                date_filter_col = 'kpi_date'

            sql = f"""
                SELECT 
                    {date_col} as dt_label,
                    {group_col} as dimension,
                    {kpi_selects}
                FROM {table_name}
                WHERE {date_filter_col} >= %s::date AND {date_filter_col} <= %s::date
                  {where_clause}
                GROUP BY {group_by}
                ORDER BY {order_by}
            """
        
            cur.execute(sql, params)
            rows = cur.fetchall()
        
            labels_set = set()
            raw_map = {} 
        
            for r in rows:
                dt_label = r[0]
                dim = r[1]
                labels_set.add(dt_label)
            
                if dt_label not in raw_map: raw_map[dt_label] = {}
                if dim not in raw_map[dt_label]: raw_map[dt_label][dim] = {}
            
                for idx, k in enumerate(kpi_defs):
                    val = r[2 + idx]
                    raw_map[dt_label][dim][k[0]] = round(float(val), 2) if val is not None else None
                
            labels = sorted(list(labels_set))
        
            res_data = {}
            for k in kpi_defs:
                res_data[k[0]] = {}
                for dim in (['Regional'] if tab == 'regional' else entities):
                    res_data[k[0]][dim] = [raw_map.get(dt, {}).get(dim, {}).get(k[0], None) for dt in labels]
                
            return jsonify({
                "labels": labels,
                "data": res_data
            })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()

@kpi4g_monitoring.route('/api/kpi_4g_monitoring/site_cluster', methods=['POST'])
@login_required
@cache.cached(timeout=21600, make_cache_key=make_post_cache_key)
def api_kpi_4g_monitoring_site_cluster():
    req = request.json
    from_date   = req.get('from_date')
    to_date     = req.get('to_date')
    sites       = req.get('sites', [])
    granularity = req.get('granularity', 'daily')
    sel_kpis    = req.get('kpis', [])
    
    if not sites:
        return jsonify({'error': 'No sites selected'}), 400
        
    kpi_defs = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]
    if not kpi_defs:
        kpi_defs = ALL_KPI_DEFS

    conn = None
    cur  = None
    try:
        with db_query() as (conn, cur):
        
            kpi_selects = ",\n            ".join([f"{k[5]} AS {k[0]}" for k in kpi_defs])
        
            if granularity == 'hourly':
                date_col = "TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI')"
                group_by = "datehour, dt_label"
                order_by = "datehour"
                table_name = '"4g_kpi_zte"'
                date_filter_col = 'date'
            else:
                date_col = "TO_CHAR(kpi_date, 'YYYY-MM-DD')"
                group_by = "kpi_date, dt_label"
                order_by = "kpi_date"
                table_name = '"4g_kpi_zte_daily"'
                date_filter_col = 'kpi_date'
            
            sql = f"""
                SELECT 
                    {date_col} as dt_label,
                    {kpi_selects}
                FROM {table_name}
                WHERE {date_filter_col} >= %s::date AND {date_filter_col} <= %s::date
                  AND siteid = ANY(%s)
                GROUP BY {group_by}
                ORDER BY {order_by}
            """
        
            cur.execute(sql, [from_date, to_date, sites])
            rows = cur.fetchall()
        
            labels_set = set()
            raw_map = {} 
        
            for r in rows:
                dt_label = r[0]
                labels_set.add(dt_label)
                raw_map[dt_label] = {}
            
                for idx, k in enumerate(kpi_defs):
                    val = r[1 + idx]
                    raw_map[dt_label][k[0]] = round(float(val), 2) if val is not None else None
                
            labels = sorted(list(labels_set))
        
            res_data = {}
            for k in kpi_defs:
                res_data[k[0]] = {}
                res_data[k[0]]['Cluster'] = [raw_map.get(dt, {}).get(k[0], None) for dt in labels]
                
            return jsonify({
                'labels': labels,
                'data': res_data
            })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()

@kpi4g_monitoring.route('/api/kpi_4g_monitoring/sector_data', methods=['POST'])
@login_required
@cache.cached(timeout=21600, make_cache_key=make_post_cache_key)
def api_kpi_4g_monitoring_sector_data():
    req = request.json
    from_date = req.get('from_date')
    to_date = req.get('to_date')
    sites = req.get('sites', [])
    sel_kpis = req.get('kpis', [])
    
    if not sites:
        return jsonify({'error': 'No sites selected'}), 400
        
    kpi_defs = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]
    if not kpi_defs:
        kpi_defs = ALL_KPI_DEFS

    conn = None
    cur = None
    try:
        with db_query() as (conn, cur):
        
            kpi_selects = ",\n            ".join([f"{k[5]} AS {k[0]}" for k in kpi_defs])
        
            sql_hourly = f'''
                SELECT 
                    TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI') as dt_label,
                    siteid,
                    CASE
                        WHEN LENGTH(cell::text) > 2 AND RIGHT(cell::text, 1) = '5' THEN SUBSTRING(cell::text FROM 2 FOR 1)
                        WHEN LENGTH(cell::text) > 2 THEN LEFT(cell::text, 2)
                        ELSE LEFT(cell::text, 1)
                    END AS sector,
                    CASE RIGHT(cell::text, 1)
                        WHEN '1' THEN 'L1800'
                        WHEN '2' THEN 'L900'
                        WHEN '3' THEN 'L2100'
                        WHEN '4' THEN 'L2300_1'
                        WHEN '5' THEN 'L2300_2'
                        WHEN '6' THEN 'L2300_3'
                        WHEN '7' THEN 'L700'
                        ELSE 'Unknown'
                    END AS band,
                    cell::text AS tech,
                    {kpi_selects}
                FROM "4g_kpi_zte"
                WHERE datehour >= %s::date AND datehour < (%s::date + interval '1 day')
                  AND siteid = ANY(%s)
                GROUP BY datehour, siteid, cell, sector, band, tech
                ORDER BY datehour
            '''
            cur.execute(sql_hourly, [from_date, to_date, sites])
            rows_hourly = cur.fetchall()
        
            sql_daily = f'''
                SELECT 
                    TO_CHAR(date, 'YYYY-MM-DD') as dt_label,
                    siteid,
                    CASE
                        WHEN LENGTH(cell::text) > 2 AND RIGHT(cell::text, 1) = '5' THEN SUBSTRING(cell::text FROM 2 FOR 1)
                        WHEN LENGTH(cell::text) > 2 THEN LEFT(cell::text, 2)
                        ELSE LEFT(cell::text, 1)
                    END AS sector,
                    CASE RIGHT(cell::text, 1)
                        WHEN '1' THEN 'L1800'
                        WHEN '2' THEN 'L900'
                        WHEN '3' THEN 'L2100'
                        WHEN '4' THEN 'L2300_1'
                        WHEN '5' THEN 'L2300_2'
                        WHEN '6' THEN 'L2300_3'
                        WHEN '7' THEN 'L700'
                        ELSE 'Unknown'
                    END AS band,
                    cell::text AS tech,
                    {kpi_selects}
                FROM "4g_kpi_zte"
                WHERE datehour >= %s::date AND datehour < (%s::date + interval '1 day')
                  AND siteid = ANY(%s)
                GROUP BY date, siteid, cell, sector, band, tech
                ORDER BY date
            '''
            cur.execute(sql_daily, [from_date, to_date, sites])
            rows_daily = cur.fetchall()
        
            def process_rows(rows):
                labels_set = set()
                raw_map = {}
            
                for r in rows:
                    dt_label = r[0]
                    siteid = r[1]
                    sector = r[2]
                    band = r[3]
                    tech = r[4]
                
                    legend_name = f"{siteid} S{sector}|{band}-{tech}"
                
                    labels_set.add(dt_label)
                    if dt_label not in raw_map: raw_map[dt_label] = {}
                    if legend_name not in raw_map[dt_label]: raw_map[dt_label][legend_name] = {}
                
                    for idx, k in enumerate(kpi_defs):
                        val = r[5 + idx]
                        raw_map[dt_label][legend_name][k[0]] = round(float(val), 2) if val is not None else None
            
                labels = sorted(list(labels_set))
            
                all_legends = set()
                for dt in raw_map:
                    for leg in raw_map[dt]:
                        all_legends.add(leg)
                all_legends = sorted(list(all_legends))
            
                res_data = {}
                for k in kpi_defs:
                    res_data[k[0]] = {}
                    for leg in all_legends:
                        res_data[k[0]][leg] = [raw_map.get(dt, {}).get(leg, {}).get(k[0], None) for dt in labels]
                    
                return {"labels": labels, "data": res_data, "legends": all_legends}
            
            return jsonify({
                "hourly": process_rows(rows_hourly),
                "daily": process_rows(rows_daily)
            })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()


# ── BDBH KPI Definitions (measKpiBdbh4G) ────────────────────────────────────────
# Only KPIs that have a valid mapping in measKpiBdbh4G are included here.
# (chart_id, sql_expr)  — chart_id must match ALL_KPI_DEFS
BDBH_KPI_EXPR = {
    "payloadChart":        'ROUND((SUM("4G Payload (MByte) NFJ") / 1024.0)::numeric, 3)',
    "dlPayloadChart":      'ROUND((SUM("DL Traffic Volume (MByte) AMQ") / 1024.0)::numeric, 3)',
    "ulPayloadChart":      'ROUND((SUM("UL Traffic Volume (MByte) AMQ") / 1024.0)::numeric, 3)',
    "dlPayloadCaChart":    'ROUND((SUM("DL Payload CA_(MByte) AMQ") / 1024.0)::numeric, 3)',
    "ulPayloadCaChart":    'ROUND((SUM("UL Payload CA_(MByte) AMQ") / 1024.0)::numeric, 3)',
    "volteTrafficChart":   'SUM("[VoLTE]_Traffic (Erl)")',
    "rrcChart":            'SUM("Max RRC Connection User")',
    "activeUserChart":     'SUM("New Active Users rnp")',
    "availChart":          'CASE WHEN SUM("Cell Availability Denum 4G AMQ") > 0 THEN ROUND((SUM("Cell Availability Num 4G AMQ") / SUM("Cell Availability Denum 4G AMQ") * 100.0)::numeric, 2) ELSE NULL END',
    "cssrChart":           'CASE WHEN SUM("Denum CSSR AMQ") > 0 THEN ROUND((SUM("Num CSSR AMQ") / SUM("Denum CSSR AMQ") * 100.0)::numeric, 2) ELSE NULL END',
    "erabSrChart":         'CASE WHEN SUM("Denum E-RAB Setup SR AMQ") > 0 THEN ROUND((SUM("Num E-RAB Setup SR AMQ") / SUM("Denum E-RAB Setup SR AMQ") * 100.0)::numeric, 2) ELSE NULL END',
    "rrcSrChart":          'CASE WHEN SUM("Denum RRC Setup SR AMQ") > 0 THEN ROUND((SUM("Num RRC Setup SR AMQ") / SUM("Denum RRC Setup SR AMQ") * 100.0)::numeric, 2) ELSE NULL END',
    "srvcc2gChart":        'CASE WHEN SUM("[VoLTE]_SRVCC_Handover SR (LTE->GSM)_denum") > 0 THEN ROUND((SUM("[VoLTE]_SRVCC_Handover SR (LTE->GSM)_num") / SUM("[VoLTE]_SRVCC_Handover SR (LTE->GSM)_denum") * 100.0)::numeric, 2) ELSE NULL END',
    "s1SrChart":           'CASE WHEN SUM("KPI Denum S1 Signaling SR") > 0 THEN ROUND((SUM("KPI Num S1 Signaling SR") / SUM("KPI Denum S1 Signaling SR") * 100.0)::numeric, 2) ELSE NULL END',
    "sdrChart":            'CASE WHEN SUM("Denum Service Drop Rate AMQ") > 0 THEN ROUND((SUM("Num Service Drop Rate AMQ") / SUM("Denum Service Drop Rate AMQ") * 100.0)::numeric, 2) ELSE NULL END',
    "erabDropChart":       'CASE WHEN SUM("Denum E-RAB Drop AMQ") > 0 THEN ROUND((SUM("Num E-RAB Drop AMQ") / SUM("Denum E-RAB Drop AMQ") * 100.0)::numeric, 2) ELSE NULL END',
    "volteDropChart":      'CASE WHEN SUM("[VoLTE]_Call Drop Rate_MME (%%)_denum") > 0 THEN ROUND((SUM("[VoLTE]_Call Drop Rate_MME (%%)_num") / SUM("[VoLTE]_Call Drop Rate_MME (%%)_denum") * 100.0)::numeric, 2) ELSE NULL END',
    "ifhoChart":           'CASE WHEN SUM("Denum IFHO SR AMQ") > 0 THEN ROUND((SUM("Num IFHO SR AMQ") / SUM("Denum IFHO SR AMQ") * 100.0)::numeric, 2) ELSE NULL END',
    "dlPrbChart":          'CASE WHEN SUM("DL PRB Utilization Denum") > 0 THEN ROUND((SUM("DL PRB Utilization Num") / SUM("DL PRB Utilization Denum") * 100.0)::numeric, 2) ELSE NULL END',
    "ulPrbChart":          'CASE WHEN SUM("UL PRB Utilization Denum") > 0 THEN ROUND((SUM("UL PRB Utilization Num") / SUM("UL PRB Utilization Denum") * 100.0)::numeric, 2) ELSE NULL END',
    "dlThpChart":          'CASE WHEN SUM("User DL Throughput Denum") > 0 THEN ROUND((SUM("User DL Throughput Num") / SUM("User DL Throughput Denum") / 1000.0)::numeric, 2) ELSE NULL END',
    "ulThpChart":          'CASE WHEN SUM("User UL Throughput Denum") > 0 THEN ROUND((SUM("User UL Throughput Num") / SUM("User UL Throughput Denum") / 1000.0)::numeric, 2) ELSE NULL END',
    "seChart":             'CASE WHEN SUM("SE_New v2_TI_Denum") > 0 THEN ROUND((SUM("SE_New v2_TI_Num") / SUM("SE_New v2_TI_Denum"))::numeric, 2) ELSE NULL END',
    "cqiChart":            'CASE WHEN SUM("Denum Average CQI") > 0 THEN ROUND((SUM("Num Average CQI") / SUM("Denum Average CQI"))::numeric, 2) ELSE NULL END',
    "dlMcsAvgChart":       'ROUND(AVG("DL Average MCS[CMCC]")::numeric, 2)',
    "ulMcsAvgChart":       'ROUND(AVG("UL Average MCS[CMCC]")::numeric, 2)',
    "agg8Chart":           'CASE WHEN SUM("Denum AGG8") > 0 THEN ROUND((SUM("Num AGG8") / SUM("Denum AGG8") * 100.0)::numeric, 2) ELSE NULL END',
    "avgRssiChart":        'ROUND(AVG("Average Cell RSSI(dBm)")::numeric, 0)',
    "avgNiChart":          'ROUND(AVG("Average NI of Carrier(dBm)")::numeric, 0)',
    "avgPucchChart":       'ROUND(AVG("PUCCH Average NI of Carrier(dBm)")::numeric, 0)',
    "avgPuschChart":       'ROUND(AVG("PUSCH Average NI of Carrier(dBm)")::numeric, 0)',
    "ulBlerChart":         'ROUND((AVG("[LTE]Cell Uplink Init BLER") * 100.0)::numeric, 2)',
    "dlBlerChart":         'ROUND((AVG("[LTE]Cell Downlink Init BLER") * 100.0)::numeric, 2)',
    "procDelayChart":      'CASE WHEN SUM("Packet_Processing_Delay_Denum") > 0 THEN ROUND((SUM("Packet_Processing_Delay_Num") / SUM("Packet_Processing_Delay_Denum"))::numeric, 2) ELSE NULL END',
    "csfbChart":           'CASE WHEN SUM("Denum CSFB SR AMQ") > 0 THEN ROUND((SUM("Num CSFB SR AMQ") / SUM("Denum CSFB SR AMQ") * 100.0)::numeric, 2) ELSE NULL END',
    "badRsrpChart":        'CASE WHEN SUM("Denum RSRP<-105dBm") > 0 THEN ROUND((SUM("Num RSRP<-105dBm") / SUM("Denum RSRP<-105dBm") * 100.0)::numeric, 2) ELSE NULL END',
    "avgCpuChart":         'ROUND((AVG("Average CPU Utilization Rate of the Baseband Control-Plane(%%)"))::numeric, 2)',
    "peakCpuChart":        'ROUND((AVG("Peak CPU Utilization Rate of the Baseband Control-Plane(%%)"))::numeric, 2)',
}


@kpi4g_monitoring.route('/api/kpi_4g_monitoring/sector_data_bdbh', methods=['POST'])
@login_required
@cache.cached(timeout=21600, make_cache_key=make_post_cache_key)
def api_kpi_4g_monitoring_sector_data_bdbh():
    """
    Sector data endpoint using measKpiBdbh4G table.
    Field mapping:
      4g_kpi_zte.date      → measKpiBdbh4G."Date"
      4g_kpi_zte.datehour  → measKpiBdbh4G."Time"
      4g_kpi_zte.cell      → measKpiBdbh4G."Cell ID"
      4g_kpi_zte.siteid    → SUBSTRING(measKpiBdbh4G."ME Name", 3, 6)
    """
    import traceback
    req = request.json
    from_date = req.get('from_date')
    to_date   = req.get('to_date')
    sites     = req.get('sites', [])
    sel_kpis  = req.get('kpis', [])

    if not sites:
        return jsonify({'error': 'No sites selected'}), 400

    # Build KPI defs filtered to those requested AND available in BDBH
    kpi_defs_bdbh = []
    for k in ALL_KPI_DEFS:
        if k[0] in sel_kpis and k[0] in BDBH_KPI_EXPR:
            kpi_defs_bdbh.append(k)

    if not kpi_defs_bdbh:
        kpi_defs_bdbh = [k for k in ALL_KPI_DEFS if k[0] in BDBH_KPI_EXPR]

    conn = None
    cur  = None
    try:
        with db_query() as (conn, cur):

            # Build SELECT expressions using BDBH column names
            kpi_selects_hourly = ",\n            ".join(
                [f'{BDBH_KPI_EXPR[k[0]]} AS {k[0]}' for k in kpi_defs_bdbh]
            )

            # --- Hourly query (grouped by "Time") ---
            sql_hourly = f'''
                SELECT
                    TO_CHAR("Time", 'YYYY-MM-DD HH24:MI') as dt_label,
                    SUBSTRING("ME Name", 3, 6) AS siteid,
                    CASE
                        WHEN LENGTH("Cell ID"::text) > 2 AND RIGHT("Cell ID"::text, 1) = '5' THEN SUBSTRING("Cell ID"::text FROM 2 FOR 1)
                        WHEN LENGTH("Cell ID"::text) > 2 THEN LEFT("Cell ID"::text, 2)
                        ELSE LEFT("Cell ID"::text, 1)
                    END AS sector,
                    CASE RIGHT("Cell ID"::text, 1)
                        WHEN '1' THEN 'L1800'
                        WHEN '2' THEN 'L900'
                        WHEN '3' THEN 'L2100'
                        WHEN '4' THEN 'L2300_1'
                        WHEN '5' THEN 'L2300_2'
                        WHEN '6' THEN 'L2300_3'
                        WHEN '7' THEN 'L700'
                        ELSE 'Unknown'
                    END AS band,
                    "Cell ID"::text AS tech,
                    {kpi_selects_hourly}
                FROM "measKpiBdbh4G"
                WHERE "Date" >= %s::date AND "Date" <= %s::date
                  AND SUBSTRING("ME Name", 3, 6) = ANY(%s)
                GROUP BY "Time", siteid, "Cell ID", sector, band, tech
                ORDER BY "Time"
            '''
            cur.execute(sql_hourly, [from_date, to_date, sites])
            rows_hourly = cur.fetchall()

            # --- Daily query (grouped by "Date") ---
            sql_daily = f'''
                SELECT
                    TO_CHAR("Date", 'YYYY-MM-DD') as dt_label,
                    SUBSTRING("ME Name", 3, 6) AS siteid,
                    CASE
                        WHEN LENGTH("Cell ID"::text) > 2 AND RIGHT("Cell ID"::text, 1) = '5' THEN SUBSTRING("Cell ID"::text FROM 2 FOR 1)
                        WHEN LENGTH("Cell ID"::text) > 2 THEN LEFT("Cell ID"::text, 2)
                        ELSE LEFT("Cell ID"::text, 1)
                    END AS sector,
                    CASE RIGHT("Cell ID"::text, 1)
                        WHEN '1' THEN 'L1800'
                        WHEN '2' THEN 'L900'
                        WHEN '3' THEN 'L2100'
                        WHEN '4' THEN 'L2300_1'
                        WHEN '5' THEN 'L2300_2'
                        WHEN '6' THEN 'L2300_3'
                        WHEN '7' THEN 'L700'
                        ELSE 'Unknown'
                    END AS band,
                    "Cell ID"::text AS tech,
                    {kpi_selects_hourly}
                FROM "measKpiBdbh4G"
                WHERE "Date" >= %s::date AND "Date" <= %s::date
                  AND SUBSTRING("ME Name", 3, 6) = ANY(%s)
                GROUP BY "Date", siteid, "Cell ID", sector, band, tech
                ORDER BY "Date"
            '''
            cur.execute(sql_daily, [from_date, to_date, sites])
            rows_daily = cur.fetchall()

            def process_rows(rows):
                labels_set = set()
                raw_map = {}

                for r in rows:
                    dt_label    = r[0]
                    siteid      = r[1]
                    sector      = r[2]
                    band        = r[3]
                    tech        = r[4]

                    legend_name = f"{siteid} S{sector}|{band}-{tech}"

                    labels_set.add(dt_label)
                    if dt_label not in raw_map:
                        raw_map[dt_label] = {}
                    if legend_name not in raw_map[dt_label]:
                        raw_map[dt_label][legend_name] = {}

                    for idx, k in enumerate(kpi_defs_bdbh):
                        val = r[5 + idx]
                        raw_map[dt_label][legend_name][k[0]] = round(float(val), 2) if val is not None else None

                labels = sorted(list(labels_set))

                all_legends = set()
                for dt in raw_map:
                    for leg in raw_map[dt]:
                        all_legends.add(leg)
                all_legends = sorted(list(all_legends))

                res_data = {}
                for k in kpi_defs_bdbh:
                    res_data[k[0]] = {}
                    for leg in all_legends:
                        res_data[k[0]][leg] = [
                            raw_map.get(dt, {}).get(leg, {}).get(k[0], None)
                            for dt in labels
                        ]

                return {"labels": labels, "data": res_data, "legends": all_legends}

            return jsonify({
                "hourly": process_rows(rows_hourly),
                "daily":  process_rows(rows_daily)
            })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cur:  cur.close()
        if conn: conn.close()
