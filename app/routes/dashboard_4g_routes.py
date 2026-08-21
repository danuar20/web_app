"""4G Dashboard Routes — /dashboard_4g"""
from flask import Blueprint, render_template, request, session, flash, make_response, jsonify
from app.db.db_webapp import get_postgres_connection, get_site_list_4g, get_site_cell_list_4g, get_city_list_4g
from ._utils import login_required, _no_cache, json_response, db_query
import psycopg2
import psycopg2.extras
import psycopg2.errors
from collections import defaultdict
import json
import logging
from contextlib import closing
from .kpi_4g_monitoring_routes import DEFAULT_KPIS

logger = logging.getLogger(__name__)

dashboard_4g = Blueprint("dashboard_4g", __name__)

ALL_KPI_DEFS = [
    # chart_id, title, unit, y_label, y_min, y_max, sql_expr, group_name, is_lower_better

    # --- Productivity ---
    ("payloadChart",   "4G Payload",             "GB",             "4G Payload (GB)",  None, None,
     'SUM("4g_payload_mb")/1024.0',             "Productivity", False),
    ("volteTrafficChart",     "VoLTE Traffic",         "Erl",            "VoLTE (Erl)",  None, None,
     "SUM(volte_traffic)",                "Productivity", False),
    ("dlPayloadChart", "DL Payload",            "GB",     "DL Payload (GB)", None, None,
     'ROUND((SUM(dl_traffic_volume) / 1024.0)::numeric, 3)', "Productivity", False),
    ("ulPayloadChart", "UL Payload",            "GB",     "UL Payload (GB)", None, None,
     'ROUND((SUM(ul_traffic_volume) / 1024.0)::numeric, 3)', "Productivity", False),
    ("dlPayloadCaChart", "DL Payload CA",       "GB",     "DL Payload CA (GB)", None, None,
     'ROUND((SUM(dl_payload_ca_mbyte) / 1024.0)::numeric, 3)', "Productivity", False),
    ("ulPayloadCaChart", "UL Payload CA",       "GB",     "UL Payload CA (GB)", None, None,
     'ROUND((SUM(ul_payload_ca_mbyte) / 1024.0)::numeric, 3)', "Productivity", False),

    # --- Availability ---
    ("availChart",     "Availability",          "%",      "Availability (%)", None, 100,
     'CASE WHEN SUM(avail_denum)>0 THEN ROUND((SUM(avail_num)/SUM(avail_denum)*100)::numeric,2) ELSE NULL END',    "Availability", False),

    # --- User ---
    ("rrcChart",    "Max RRC User",          "Users",          "Max RRC Users",  None, None,
     "SUM(max_rrc_conn_user)",            "User", False),
    ("activeUserChart","Active User",           "Users",          "Active Users",  None, None,
     "SUM(new_active_users)",            "User", False),

    # --- Accessibility ---
    ("cssrChart",      "CSSR",                  "%",       "CSSR (%)", None, 100,
     'CASE WHEN SUM(cssr_denum)>0 THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),
    ("rrcSrChart",     "RRC SR",                "%",     "RRC SR (%)", None, 100,
     'CASE WHEN SUM(rrc_setup_denum)>0 THEN ROUND((SUM(rrc_setup_num)/SUM(rrc_setup_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),
    ("erabSrChart",    "ERAB SR",               "%",    "ERAB SR (%)", None, 100,
     'CASE WHEN SUM(erab_setup_denum)>0 THEN ROUND((SUM(erab_setup_num)/SUM(erab_setup_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),
    ("srvcc2gChart",   "SRVCC 2G",              "%",      "SRVCC 2G (%)", None, 100,
     'CASE WHEN SUM(srvcc_gsm_denum) > 0 THEN ROUND((SUM(srvcc_gsm_num) / SUM(srvcc_gsm_denum) * 100.0)::numeric, 2) ELSE NULL END', "Accessibility", False),
    ("pagingDiscardedChart", "Paging Discarded", "%",     "Paging Discarded (%)", 0, None,
     'CASE WHEN SUM(number_of_paging_records_received_by_the_enodeb) > 0 THEN ROUND((SUM(number_of_paging_records_discarded_at_the_enodeb) / SUM(number_of_paging_records_received_by_the_enodeb) * 100.0)::numeric, 2) ELSE NULL END', "Accessibility", True),
    ("s1SrChart",      "S1 SR",                 "%",      "S1 SR (%)", None, 100,
     'CASE WHEN SUM(s1_signaling_sr_denum)>0 THEN ROUND((SUM(s1_signaling_sr_num)/SUM(s1_signaling_sr_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),

    # --- Retainability ---
    ("sdrChart",       "SDR",                   "%",        "SDR (%)",  None, None,
     'CASE WHEN SUM(sdr_denum)>0 THEN ROUND((SUM(sdr_num)/SUM(sdr_denum)*100)::numeric,2) ELSE NULL END', "Retainability", True),
    ("erabDropChart",  "ERAB Drop",             "%",      "ERAB Drop (%)", 0, None,
     'CASE WHEN SUM(erab_drop_denum) > 0 THEN ROUND((SUM(erab_drop_num) / SUM(erab_drop_denum) * 100.0)::numeric, 2) ELSE NULL END', "Retainability", True),
    ("volteDropChart", "VoLTE Call Drop",       "%",      "VoLTE Call Drop (%)", 0, None,
     'CASE WHEN SUM(volte_call_drop_rate_mme_denum) > 0 THEN ROUND((SUM(volte_call_drop_rate_mme_num) / SUM(volte_call_drop_rate_mme_denum) * 100.0)::numeric, 2) ELSE NULL END', "Retainability", True),

    # --- Mobility ---
    ("ifhoChart",      "IFHO",                  "%",       "IFHO (%)", None, 100,
     'CASE WHEN SUM(ifho_denum)>0 THEN ROUND((SUM(ifho_num)/SUM(ifho_denum)*100)::numeric,2) ELSE NULL END', "Mobility", False),
    ("intraFreqHoChart", "Intra Freq HO",       "%",      "Intra Freq HO (%)", None, 100,
     'CASE WHEN SUM(inta_rat_ifho_denum) > 0 THEN ROUND((SUM(inta_rat_ifho_num) / SUM(inta_rat_ifho_denum) * 100.0)::numeric, 2) ELSE NULL END', "Mobility", False),
    ("bsrAttemptChart","BSR Attempt",           "",       "BSR Attempt", 0, None,
     'SUM("Number of Outgoing HO Preparation Attempts(based UL Service)")', "Mobility", False),
    ("bsrSrChart",     "BSR SR",                "%",      "BSR SR (%)", None, 100,
     'CASE WHEN SUM("Number of Outgoing HO Preparation Attempts(based UL Service)") > 0 THEN ROUND((SUM("Number of Outgoing HO Success(based UL Service)") / SUM("Number of Outgoing HO Preparation Attempts(based UL Service)") * 100.0)::numeric, 2) ELSE NULL END', "Mobility", False),

    # --- Capacity ---
    ("dlPrbChart",     "DL PRB",                "%",     "DL PRB (%)", 0, 100,
     'CASE WHEN SUM(dl_prb_util_denum)>0 THEN ROUND((SUM(dl_prb_util_num)/SUM(dl_prb_util_denum)*100)::numeric,2) ELSE NULL END', "Capacity", False),
    ("ulPrbChart",     "UL PRB",                "%",     "UL PRB (%)", 0, 100,
     'CASE WHEN SUM(ul_prb_util_denum)>0 THEN ROUND((SUM(ul_prb_util_num)/SUM(ul_prb_util_denum)*100)::numeric,2) ELSE NULL END', "Capacity", False),

    # --- Integrity ---
    ("dlThpChart",     "User DL Throughput",    "Mbps",  "DL Thp (Mbps)",  None, None,
     'CASE WHEN SUM(user_dl_thp_denum)>0 THEN ROUND((SUM(user_dl_thp_num)/SUM(user_dl_thp_denum)/1000)::numeric,2) ELSE NULL END', "Integrity", False),
    ("ulThpChart",     "User UL Throughput",    "Mbps",  "UL Thp (Mbps)",  None, None,
     'CASE WHEN SUM(user_ul_thp_denum)>0 THEN ROUND((SUM(user_ul_thp_num)/SUM(user_ul_thp_denum)/1000)::numeric,2) ELSE NULL END', "Integrity", False),

    # --- Quality ---
    ("seChart",        "Spectral Efficiency",   "SE",             "SE",  None, None,
     'CASE WHEN SUM(se_v3_denum)>0 THEN ROUND((SUM(se_v3_num)/SUM(se_v3_denum))::numeric,2) ELSE NULL END', "Quality", False),
    ("cqiChart",       "CQI",                  "CQI",            "CQI", None, None,
     'CASE WHEN SUM(denum_average_cqi)>0 THEN ROUND((SUM(num_average_cqi)/SUM(denum_average_cqi))::numeric,2) ELSE NULL END', "Quality", False),
    ("dlMcsAvgChart",  "DL MCS Average",        "",       "DL MCS Average", 0, None,
     'CASE WHEN SUM(denum_dl_avg_mcs) > 0 THEN ROUND((SUM(num_dl_avg_mcs) / SUM(denum_dl_avg_mcs))::numeric, 2) ELSE NULL END', "Quality", False),
    ("ulMcsAvgChart",  "UL MCS Average",        "",       "UL MCS Average", 0, None,
     'CASE WHEN SUM(denum_ul_avg_mcs) > 0 THEN ROUND((SUM(num_ul_avg_mcs) / SUM(denum_ul_avg_mcs))::numeric, 2) ELSE NULL END', "Quality", False),
    ("agg8Chart",      "Agg8",                  "%",      "Agg8 (%)", 0, None,
     'CASE WHEN SUM(denum_agg8) > 0 THEN ROUND((SUM(num_agg8) / SUM(denum_agg8) * 100.0)::numeric, 2) ELSE NULL END', "Quality", False),
    ("dlCceFailChart", "DL CCE Failure",        "%",      "DL CCE Failure (%)", 0, None,
     'CASE WHEN SUM("DL_CCE_Failure_Denum") > 0 THEN ROUND((SUM("DL_CCE_Failure_Num") / SUM("DL_CCE_Failure_Denum") * 100.0)::numeric, 2) ELSE NULL END', "Quality", True),
    ("ulCceFailChart", "UL CCE Failure",        "%",      "UL CCE Failure (%)", 0, None,
     'CASE WHEN SUM("UL_CCE_Failure_Denum") > 0 THEN ROUND((SUM("UL_CCE_Failure_Num") / SUM("UL_CCE_Failure_Denum") * 100.0)::numeric, 2) ELSE NULL END', "Quality", True),
    ("avgRssiChart",   "Avg Rssi",              "dBm",     "Avg Rssi (dBm)", None, None,
     'ROUND(AVG(avg_cell_rssi)::numeric, 0)', "Quality", False),
    ("avgNiChart",     "Avg Ni",                "dBm",     "Avg Ni (dBm)", None, None,
     'ROUND(AVG(average_ni_of_carrier)::numeric, 0)', "Quality", False),
    ("avgPucchChart",  "Avg Pucch Ni",             "dBm",     "Avg Pucch Ni (dBm)", None, None,
     'ROUND(AVG(pucch_avg_ni_of_carrier)::numeric, 0)', "Quality", False),
    ("avgPuschChart",  "Avg Pusch Ni",             "dBm",     "Avg Pusch Ni (dBm)", None, None,
     'ROUND(AVG(pusch_avg_ni_of_carrier)::numeric, 0)', "Quality", False),
    ("ulBlerChart",    "UL Bler",               "%",      "UL Bler (%)", 0, None,
     'ROUND((AVG(cell_uplink_init_bler) * 100.0)::numeric, 2)', "Quality", True),
    ("dlBlerChart",    "DL Bler",               "%",      "DL Bler (%)", 0, None,
     'ROUND((AVG(cell_downlink_init_bler) * 100.0)::numeric, 2)', "Quality", True),
    ("procDelayChart", "Processing Delay",      "ms",     "Processing Delay (ms)", 0, None,
     'CASE WHEN SUM(processing_delay_denum) > 0 THEN ROUND((SUM(processing_delay_num) / SUM(processing_delay_denum))::numeric, 2) ELSE NULL END', "Quality", True),
    ("csfbChart",      "CSFB",                  "%",       "CSFB (%)", None, 100,
     'CASE WHEN SUM(csfb_denum)>0 THEN ROUND((SUM(csfb_num)/SUM(csfb_denum)*100)::numeric,2) ELSE NULL END', "Quality", False),

    # --- Coverage ---
    ("badRsrpChart",   "Bad RSRP (<-105)",              "%",      "Bad RSRP (<-105) (%)", 0, None,
     'CASE WHEN SUM(denum_rsrp_dbm) > 0 THEN ROUND((SUM(num_rsrp_dbm) / SUM(denum_rsrp_dbm) * 100.0)::numeric, 2) ELSE NULL END', "Coverage", True),
    ("goodRsrpChart",  "Good RSRP (>-105)",             "%",      "Good RSRP (>-105) (%)", None, 100,
     'CASE WHEN SUM("Good_RSRP (>-105) Ratio Denum") > 0 THEN ROUND((SUM("Good_RSRP (>-105) Ratio Num") / SUM("Good_RSRP (>-105) Ratio Denum") * 100.0)::numeric, 2) ELSE NULL END', "Coverage", False),
    ("avgRsrpChart",   "Avg RSRP",              "dBm",     "Avg RSRP (dBm)", None, None,
     'ROUND(AVG(avg_rsrp_dbm)::numeric, 0)', "Coverage", False),
    ("avgRsrqChart",   "Avg RSRQ",              "dB",     "Avg RSRQ (dB)", None, None,
     'ROUND(AVG("Average of RSRQ Value of Serving Cell(period measurement)(dB)")::numeric, 0)', "Coverage", False),

    # --- Hardware ---
    ("avgCpuChart",    "Avg CPU Util",          "%",      "Avg CPU Util (%)", 0, None,
     'ROUND((AVG(average_cpu_utilization) * 100.0)::numeric, 2)', "Hardware", False),
    ("peakCpuChart",   "Peak CPU Util",         "%",      "Peak CPU Util (%)", 0, None,
     'ROUND((AVG(peak_cpu_utilization) * 100.0)::numeric, 2)', "Hardware", False),
]

KPI_GROUPS = ["Productivity","Availability","User","Accessibility","Retainability","Capacity","Integrity","Mobility","Quality","Coverage","Hardware","Others"]


@dashboard_4g.route("/dashboard_4g")
@login_required
def dashboard_4g_view():
    submitted = request.args.get("submitted", "")
    query_done = bool(submitted)
    trend_from_date = request.args.get("trend_from_date", "")
    trend_to_date   = request.args.get("trend_to_date",   "")
    before_from_date = request.args.get("before_from_date", "")
    before_to_date   = request.args.get("before_to_date",   "")
    after_from_date = request.args.get("after_from_date",  "")
    after_to_date   = request.args.get("after_to_date",    "")
    
    execution_dates_raw = request.args.get("execution_dates", "")
    execution_dates = [d.strip() for d in execution_dates_raw.split(",") if d.strip()]
    
    filter_type = request.args.get("filter_type", "siteid")
    sel_sites = request.args.getlist("site")
    
    # Support site IDs pasted from CSV — comma/newline separated, deduplicate
    site_paste_raw = request.args.get("site_paste", "")
    if site_paste_raw:
        extra = [s.strip() for s in site_paste_raw.replace("\n", ",").split(",") if s.strip()]
        for s in extra:
            if s not in sel_sites:
                sel_sites.append(s)
                
    sel_sites_db = [s.strip().upper() for s in sel_sites if s.strip()]
    
    if filter_type == "city":
        if not sel_sites_db:
            sel_sites_db = ['UNKNOWN']
        where_entity = "city IN %s"
        sel_sites_param = tuple(sel_sites_db)
        group_entity = "city"
    elif filter_type == "site_cell":
        parsed = []
        for s in sel_sites_db:
            if '-' in s:
                sid, c = s.rsplit('-', 1)
                try:
                    parsed.append((sid.upper(), float(c)))
                except ValueError:
                    pass
        if not parsed:
            parsed = [('UNKNOWN', -1)]
        where_entity = "(siteid, cell) IN %s"
        sel_sites_param = tuple(parsed)
        group_entity = "siteid || '-' || cell::text"
    else:
        if not sel_sites_db:
            sel_sites_db = ['UNKNOWN']
        where_entity = "siteid IN %s"
        sel_sites_param = tuple(sel_sites_db)
        group_entity = "siteid"

    sel_kpis = request.args.getlist("kpi")
    if not sel_kpis:
        sel_kpis = DEFAULT_KPIS
        
    KPI_DEFS = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]

    sites_list = []
    try:
        if filter_type == "city":
            sites_list, _ = get_city_list_4g()
        elif filter_type == "site_cell":
            sites_list, _ = get_site_cell_list_4g()
        else:
            sites_list, _ = get_site_list_4g()
    except Exception:
        sites_list = []

    last_update = None
    
    # Initialize response structures
    daily_trend_labels = []
    hourly_trend_labels = []
    daily_trend_chart_data = defaultdict(lambda: {"total": []})
    hourly_trend_chart_data = defaultdict(lambda: {"total": []})
    daily_site_trend_chart_data = defaultdict(lambda: defaultdict(list))
    hourly_site_trend_chart_data = defaultdict(lambda: defaultdict(list))
    daily_band_trend_chart_data = defaultdict(lambda: defaultdict(list))
    hourly_band_trend_chart_data = defaultdict(lambda: defaultdict(list))
    daily_tech_trend_chart_data = defaultdict(lambda: defaultdict(list))
    hourly_tech_trend_chart_data = defaultdict(lambda: defaultdict(list))
    
    cluster_compare = {}
    band_compare = defaultdict(dict)
    tech_compare = defaultdict(dict)
    sector_compare = defaultdict(dict)
    site_compare = defaultdict(dict)
    
    compare_hourly_labels = []
    compare_hourly_data = {}
    site_compare_hourly_data = defaultdict(lambda: {"before": defaultdict(list), "after": defaultdict(list)})
    
    conn = None
    cur = None
    
    has_trend = trend_from_date and trend_to_date and sel_sites and KPI_DEFS
    has_compare = before_from_date and before_to_date and after_from_date and after_to_date and sel_sites and KPI_DEFS

    if has_trend or has_compare:
        try:
            with db_query() as (conn, cur):
            
                try:
                    from datetime import datetime
                    before_str = f"{datetime.strptime(before_from_date, '%Y-%m-%d').strftime('%d %b')} to {datetime.strptime(before_to_date, '%Y-%m-%d').strftime('%d %b')}" if before_from_date and before_to_date else ""
                    after_str = f"{datetime.strptime(after_from_date, '%Y-%m-%d').strftime('%d %b')} to {datetime.strptime(after_to_date, '%Y-%m-%d').strftime('%d %b')}" if after_from_date and after_to_date else ""
                except Exception:
                    before_str = ""
                    after_str = ""

                try:
                    cur.execute('SELECT MAX(datehour::date) FROM "4g_kpi_zte"')
                    raw_last = cur.fetchone()
                    last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
                except Exception:
                    last_update = None

                kpi_selects = ", ".join([f"{k[6]} AS {k[0]}" for k in KPI_DEFS])
            
                # --- TREND DATA ---
                if has_trend:
                    band_expr = """CASE RIGHT(cell::text, 1)
                                WHEN '1' THEN 'L1800'
                                WHEN '2' THEN 'L900'
                                WHEN '3' THEN 'L2100'
                                WHEN '4' THEN 'L2300_1'
                                WHEN '5' THEN 'L2300_2'
                                WHEN '6' THEN 'L2300_3'
                                WHEN '7' THEN 'L700'
                                ELSE 'Unknown'
                            END"""
                    tech_expr = """CASE RIGHT(cell::text, 1)
                                WHEN '1' THEN 'FDD'
                                WHEN '2' THEN 'FDD'
                                WHEN '3' THEN 'FDD'
                                WHEN '4' THEN 'TDD'
                                WHEN '5' THEN 'TDD'
                                WHEN '6' THEN 'TDD'
                                WHEN '7' THEN 'FDD'
                                ELSE 'Unknown'
                            END"""

                    query_trend_all = f"""
                        SELECT 
                            CASE WHEN GROUPING(datehour) = 1 THEN TO_CHAR(date, 'YYYY-MM-DD') ELSE TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI') END AS dt_label,
                            CASE WHEN GROUPING(datehour) = 1 THEN 'daily' ELSE 'hourly' END AS gran,
                            date,
                            datehour,
                            {group_entity} AS siteid,
                            {band_expr} AS band,
                            {tech_expr} AS tech,
                            GROUPING({group_entity}) AS g_site,
                            GROUPING({band_expr}) AS g_band,
                            GROUPING({tech_expr}) AS g_tech,
                            GROUPING(datehour) AS g_hour,
                            {kpi_selects}
                        FROM "4g_kpi_zte"
                        WHERE date BETWEEN %s AND %s AND {where_entity}
                        GROUP BY GROUPING SETS (
                            -- Daily
                            (date),
                            (date, {group_entity}),
                            (date, {band_expr}),
                            (date, {tech_expr}),
                            -- Hourly
                            (date, datehour),
                            (date, datehour, {group_entity}),
                            (date, datehour, {band_expr}),
                            (date, datehour, {tech_expr})
                        )
                        ORDER BY gran, date, datehour NULLS FIRST
                    """
                    cur.execute(query_trend_all, [trend_from_date, trend_to_date, sel_sites_param])
                    rows_trend_all = cur.fetchall()

                    daily_trend_map = {}
                    hourly_trend_map = {}
                    daily_site_trend_map = defaultdict(dict)
                    hourly_site_trend_map = defaultdict(dict)
                    daily_band_trend_map = defaultdict(dict)
                    hourly_band_trend_map = defaultdict(dict)
                    daily_tech_trend_map = defaultdict(dict)
                    hourly_tech_trend_map = defaultdict(dict)

                    for r in rows_trend_all:
                        dt_label, gran, d, dh, siteid, band, tech, g_site, g_band, g_tech, g_hour = r[:11]
                        kpis = r[11:]

                        if gran == 'daily':
                            if dt_label not in daily_trend_labels:
                                daily_trend_labels.append(dt_label)
                            if g_site == 1 and g_band == 1 and g_tech == 1:
                                daily_trend_map[dt_label] = kpis
                            elif g_site == 0:
                                daily_site_trend_map[siteid][dt_label] = kpis
                            elif g_band == 0:
                                daily_band_trend_map[band][dt_label] = kpis
                            elif g_tech == 0:
                                daily_tech_trend_map[tech][dt_label] = kpis
                        else:
                            if dt_label not in hourly_trend_labels:
                                hourly_trend_labels.append(dt_label)
                            if g_site == 1 and g_band == 1 and g_tech == 1:
                                hourly_trend_map[dt_label] = kpis
                            elif g_site == 0:
                                hourly_site_trend_map[siteid][dt_label] = kpis
                            elif g_band == 0:
                                hourly_band_trend_map[band][dt_label] = kpis
                            elif g_tech == 0:
                                hourly_tech_trend_map[tech][dt_label] = kpis

                    # Populate Daily Chart Data
                    for idx, kpi in enumerate(KPI_DEFS):
                        kpi_id = kpi[0]
                        daily_trend_chart_data[kpi_id]["total"] = []
                        for dt in daily_trend_labels:
                            val_row = daily_trend_map.get(dt)
                            val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                            daily_trend_chart_data[kpi_id]["total"].append(val)

                    for site in daily_site_trend_map:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            for dt in daily_trend_labels:
                                val_row = daily_site_trend_map[site].get(dt)
                                val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                                daily_site_trend_chart_data[kpi_id][site].append(val)

                    for band in daily_band_trend_map:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            for dt in daily_trend_labels:
                                val_row = daily_band_trend_map[band].get(dt)
                                val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                                daily_band_trend_chart_data[kpi_id][band].append(val)

                    for tech in daily_tech_trend_map:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            for dt in daily_trend_labels:
                                val_row = daily_tech_trend_map[tech].get(dt)
                                val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                                daily_tech_trend_chart_data[kpi_id][tech].append(val)

                    # Populate Hourly Chart Data
                    for idx, kpi in enumerate(KPI_DEFS):
                        kpi_id = kpi[0]
                        hourly_trend_chart_data[kpi_id]["total"] = []
                        for hr in hourly_trend_labels:
                            val_row = hourly_trend_map.get(hr)
                            val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                            hourly_trend_chart_data[kpi_id]["total"].append(val)

                    for site in hourly_site_trend_map:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            for hr in hourly_trend_labels:
                                val_row = hourly_site_trend_map[site].get(hr)
                                val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                                hourly_site_trend_chart_data[kpi_id][site].append(val)

                    for band in hourly_band_trend_map:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            for hr in hourly_trend_labels:
                                val_row = hourly_band_trend_map[band].get(hr)
                                val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                                hourly_band_trend_chart_data[kpi_id][band].append(val)

                    for tech in hourly_tech_trend_map:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            for hr in hourly_trend_labels:
                                val_row = hourly_tech_trend_map[tech].get(hr)
                                val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                                hourly_tech_trend_chart_data[kpi_id][tech].append(val)
                            
                            
                # --- COMPARE DATA ---
                if has_compare:
                    def get_aggregates(from_d, to_d):
                        band_expr = """CASE RIGHT(cell::text, 1)
                                    WHEN '1' THEN 'L1800'
                                    WHEN '2' THEN 'L900'
                                    WHEN '3' THEN 'L2100'
                                    WHEN '4' THEN 'L2300_1'
                                    WHEN '5' THEN 'L2300_2'
                                    WHEN '6' THEN 'L2300_3'
                                    WHEN '7' THEN 'L700'
                                    ELSE 'Unknown'
                                END"""
                        tech_expr = """CASE RIGHT(cell::text, 1)
                                    WHEN '1' THEN 'FDD'
                                    WHEN '2' THEN 'FDD'
                                    WHEN '3' THEN 'FDD'
                                    WHEN '4' THEN 'TDD'
                                    WHEN '5' THEN 'TDD'
                                    WHEN '6' THEN 'TDD'
                                    WHEN '7' THEN 'FDD'
                                    ELSE 'Unknown'
                                END"""
                        sector_expr = """CASE
                                    WHEN LENGTH(cell::text) > 2 AND RIGHT(cell::text, 1) = '5' THEN SUBSTRING(cell::text FROM 2 FOR 1)
                                    WHEN LENGTH(cell::text) > 2 THEN LEFT(cell::text, 2)
                                    ELSE LEFT(cell::text, 1)
                                END"""

                        query_compare = f"""
                            SELECT 
                                {group_entity} AS siteid,
                                {band_expr} AS band,
                                {tech_expr} AS tech,
                                {sector_expr} AS sector,
                                GROUPING({group_entity}) AS g_site,
                                GROUPING({band_expr}) AS g_band,
                                GROUPING({tech_expr}) AS g_tech,
                                GROUPING({sector_expr}) AS g_sector,
                                {kpi_selects}
                            FROM "4g_kpi_zte"
                            WHERE date BETWEEN %s AND %s AND {where_entity}
                            GROUP BY GROUPING SETS (
                                (),
                                ({band_expr}),
                                ({tech_expr}),
                                ({group_entity}, {sector_expr}),
                                ({group_entity})
                            )
                        """
                        cur.execute(query_compare, [from_d, to_d, sel_sites_param])
                        rows = cur.fetchall()
                        
                        cluster_row = None
                        band_rows = []
                        tech_rows = []
                        sector_rows = []
                        site_rows = []
                        
                        for r in rows:
                            siteid, band, tech, sector, g_site, g_band, g_tech, g_sector = r[:8]
                            kpis = r[8:]
                            
                            if g_site == 1 and g_band == 1 and g_tech == 1 and g_sector == 1:
                                cluster_row = kpis
                            elif g_band == 0 and g_site == 1:
                                band_rows.append((band,) + kpis)
                            elif g_tech == 0 and g_site == 1:
                                tech_rows.append((tech,) + kpis)
                            elif g_sector == 0 and g_site == 0:
                                sector_rows.append((siteid, sector) + kpis)
                            elif g_site == 0 and g_sector == 1:
                                site_rows.append((siteid,) + kpis)
                                
                        return cluster_row, band_rows, tech_rows, sector_rows, site_rows

                    b_cluster, b_band, b_tech, b_sector, b_site = get_aggregates(before_from_date, before_to_date)
                    a_cluster, a_band, a_tech, a_sector, a_site = get_aggregates(after_from_date, after_to_date)
                
                    # Process Cluster
                    for idx, kpi in enumerate(KPI_DEFS):
                        kpi_id, title, unit, _, _, _, _, group_name, is_lb = kpi
                        b_val = round(float(b_cluster[idx]), 2) if b_cluster and b_cluster[idx] is not None else None
                        a_val = round(float(a_cluster[idx]), 2) if a_cluster and a_cluster[idx] is not None else None
                    
                        delta = round(a_val - b_val, 2) if (b_val is not None and a_val is not None) else None
                        delta_pct = round((delta / abs(b_val)) * 100, 1) if (delta is not None and b_val) else None
                    
                        cluster_compare[kpi_id] = {
                            "before": b_val, "after": a_val, "delta": delta, "delta_pct": delta_pct,
                            "title": title, "unit": unit, "group": group_name, "is_lower_better": is_lb
                        }
                
                    # Process Band
                    b_band_map = {r[0]: r[1:] for r in b_band}
                    a_band_map = {r[0]: r[1:] for r in a_band}
                    all_bands = set(list(b_band_map.keys()) + list(a_band_map.keys()))
                    for band in all_bands:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            b_val = round(float(b_band_map[band][idx]), 2) if band in b_band_map and b_band_map[band][idx] is not None else None
                            a_val = round(float(a_band_map[band][idx]), 2) if band in a_band_map and a_band_map[band][idx] is not None else None
                            delta = round(a_val - b_val, 2) if (b_val is not None and a_val is not None) else None
                            delta_pct = round((delta / abs(b_val)) * 100, 1) if (delta is not None and b_val) else None
                            band_compare[band][kpi_id] = {"before": b_val, "after": a_val, "delta": delta, "delta_pct": delta_pct}

                    # Process Tech
                    b_tech_map = {r[0]: r[1:] for r in b_tech}
                    a_tech_map = {r[0]: r[1:] for r in a_tech}
                    all_techs = set(list(b_tech_map.keys()) + list(a_tech_map.keys()))
                    for tech in all_techs:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            b_val = round(float(b_tech_map[tech][idx]), 2) if tech in b_tech_map and b_tech_map[tech][idx] is not None else None
                            a_val = round(float(a_tech_map[tech][idx]), 2) if tech in a_tech_map and a_tech_map[tech][idx] is not None else None
                            delta = round(a_val - b_val, 2) if (b_val is not None and a_val is not None) else None
                            delta_pct = round((delta / abs(b_val)) * 100, 1) if (delta is not None and b_val) else None
                            tech_compare[tech][kpi_id] = {"before": b_val, "after": a_val, "delta": delta, "delta_pct": delta_pct}

                    # Process Sector
                    b_sec_map = {f"{r[0]}_Sec{r[1]}": r[2:] for r in b_sector}
                    a_sec_map = {f"{r[0]}_Sec{r[1]}": r[2:] for r in a_sector}
                    all_sectors = set(list(b_sec_map.keys()) + list(a_sec_map.keys()))
                    for sec in all_sectors:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            b_val = round(float(b_sec_map[sec][idx]), 2) if sec in b_sec_map and b_sec_map[sec][idx] is not None else None
                            a_val = round(float(a_sec_map[sec][idx]), 2) if sec in a_sec_map and a_sec_map[sec][idx] is not None else None
                            delta = round(a_val - b_val, 2) if (b_val is not None and a_val is not None) else None
                            delta_pct = round((delta / abs(b_val)) * 100, 1) if (delta is not None and b_val) else None
                            sector_compare[sec][kpi_id] = {"before": b_val, "after": a_val, "delta": delta, "delta_pct": delta_pct}

                    # Process Site
                    b_site_map = {r[0]: r[1:] for r in b_site}
                    a_site_map = {r[0]: r[1:] for r in a_site}
                    all_sites = set(list(b_site_map.keys()) + list(a_site_map.keys()))
                    for site in all_sites:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            b_val = round(float(b_site_map[site][idx]), 2) if site in b_site_map and b_site_map[site][idx] is not None else None
                            a_val = round(float(a_site_map[site][idx]), 2) if site in a_site_map and a_site_map[site][idx] is not None else None
                            delta = round(a_val - b_val, 2) if (b_val is not None and a_val is not None) else None
                            delta_pct = round((delta / abs(b_val)) * 100, 1) if (delta is not None and b_val) else None
                            site_compare[site][kpi_id] = {"before": b_val, "after": a_val, "delta": delta, "delta_pct": delta_pct}

                    # --- Compare Hourly Trend (Cluster & Site Level) ---
                    def get_hourly_profiles(from_d, to_d):
                        query_h = f"""
                            SELECT 
                                TO_CHAR(datehour, 'HH24:00') AS hr,
                                {group_entity} AS siteid,
                                GROUPING({group_entity}) AS g_site,
                                {kpi_selects}
                            FROM "4g_kpi_zte"
                            WHERE date BETWEEN %s AND %s AND {where_entity}
                            GROUP BY GROUPING SETS (
                                (TO_CHAR(datehour, 'HH24:00')),
                                (TO_CHAR(datehour, 'HH24:00'), {group_entity})
                            )
                            ORDER BY hr
                        """
                        cur.execute(query_h, [from_d, to_d, sel_sites_param])
                        rows = cur.fetchall()
                        h_map = {}
                        site_h_map = defaultdict(dict)
                        for r in rows:
                            hr, siteid, g_site = r[0], r[1], r[2]
                            kpis = r[3:]
                            if g_site == 1:
                                h_map[hr] = kpis
                            else:
                                site_h_map[siteid][hr] = kpis
                        return h_map, site_h_map

                    before_hourly_map, b_site_h_map = get_hourly_profiles(before_from_date, before_to_date)
                    after_hourly_map, a_site_h_map = get_hourly_profiles(after_from_date, after_to_date)
                
                    compare_hourly_labels = sorted(list(set(list(before_hourly_map.keys()) + list(after_hourly_map.keys()))))

                    for idx, kpi in enumerate(KPI_DEFS):
                        chart_id = kpi[0]
                        compare_hourly_data[chart_id] = {"before": [], "after": []}
                        for hr in compare_hourly_labels:
                            b_val = before_hourly_map.get(hr)
                            a_val = after_hourly_map.get(hr)
                            b = round(float(b_val[idx]), 2) if b_val and b_val[idx] is not None else None
                            a = round(float(a_val[idx]), 2) if a_val and a_val[idx] is not None else None
                            compare_hourly_data[chart_id]["before"].append(b)
                            compare_hourly_data[chart_id]["after"].append(a)

                    all_sh_sites = set(list(b_site_h_map.keys()) + list(a_site_h_map.keys()))
                    for site in all_sh_sites:
                        for idx, kpi in enumerate(KPI_DEFS):
                            chart_id = kpi[0]
                            for hr in compare_hourly_labels:
                                b_val = b_site_h_map[site].get(hr)
                                a_val = a_site_h_map[site].get(hr)
                                b = round(float(b_val[idx]), 2) if b_val and b_val[idx] is not None else None
                                a = round(float(a_val[idx]), 2) if a_val and a_val[idx] is not None else None
                                site_compare_hourly_data[chart_id]["before"][site].append(b)
                                site_compare_hourly_data[chart_id]["after"][site].append(a)

        except Exception as e:
            if conn:
                try: conn.rollback()
                except: pass
            import traceback; traceback.print_exc()
            flash(f"Error executing dashboard query: {str(e)}", "danger")
        finally:
            if cur:
                try: cur.close()
                except: pass
            if conn:
                try: conn.close()
                except: pass

    # Fetch User's Custom Charts
    user_charts = []
    username = session.get("username", "User")
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor(cursor_factory=psycopg2.extras.DictCursor)) as cur:
                cur.execute("SELECT id, dashboard_name, chart_config FROM user_custom_charts WHERE username = %s AND dashboard_name LIKE '4G%%' ORDER BY dashboard_name", [username])
                user_charts = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("Error fetching custom charts: %s", e)

    return _no_cache(make_response(render_template(
        "dashboard_4g.html",
        username=username,
        filter_type=filter_type,
        sites_list=sites_list,
        sel_sites=sel_sites,
        site_paste=site_paste_raw,
        sel_kpis=sel_kpis,
        all_kpis=ALL_KPI_DEFS,
        trend_from_date=trend_from_date,
        trend_to_date=trend_to_date,
        before_from_date=before_from_date,
        before_to_date=before_to_date,
        after_from_date=after_from_date,
        after_to_date=after_to_date,
        execution_dates=",".join(execution_dates),
        last_update=last_update,
        
        before_str=before_str if 'before_str' in locals() else "",
        after_str=after_str if 'after_str' in locals() else "",
        
        trend_labels=daily_trend_labels,
        trend_chart_data=dict(daily_trend_chart_data),
        site_trend_chart_data=dict(daily_site_trend_chart_data),
        band_trend_chart_data=dict(daily_band_trend_chart_data),
        tech_trend_chart_data=dict(daily_tech_trend_chart_data),

        daily_trend_labels=daily_trend_labels,
        daily_trend_chart_data=dict(daily_trend_chart_data),
        daily_site_trend_chart_data=dict(daily_site_trend_chart_data),
        daily_band_trend_chart_data=dict(daily_band_trend_chart_data),
        daily_tech_trend_chart_data=dict(daily_tech_trend_chart_data),

        hourly_trend_labels=hourly_trend_labels,
        hourly_trend_chart_data=dict(hourly_trend_chart_data),
        hourly_site_trend_chart_data=dict(hourly_site_trend_chart_data),
        hourly_band_trend_chart_data=dict(hourly_band_trend_chart_data),
        hourly_tech_trend_chart_data=dict(hourly_tech_trend_chart_data),
        
        cluster_compare=cluster_compare,
        band_compare=dict(sorted(band_compare.items(), key=lambda x: (len(x[0]), x[0]))),
        tech_compare=dict(sorted(tech_compare.items(), key=lambda x: (len(x[0]), x[0]))),
        sector_compare=dict(sector_compare),
        site_compare=dict(site_compare),
        
        compare_hourly_labels=compare_hourly_labels,
        compare_hourly_data=compare_hourly_data,
        site_compare_hourly_data=dict(site_compare_hourly_data),
        
        kpi_defs=[(k[0], k[1], k[2], k[3], k[4], k[5], k[7], k[8]) for k in KPI_DEFS],
        kpi_groups=KPI_GROUPS,
        user_charts=user_charts,
        query_done=query_done,
    )))

@dashboard_4g.route("/api/dashboard_4g/save_chart", methods=["POST"])
@login_required
def save_custom_chart():
    username = session.get("username", "User")
    data = request.get_json()
    dashboard_name = data.get("dashboard_name", "").strip()
    if dashboard_name and not dashboard_name.upper().startswith("4G"):
        dashboard_name = f"4G - {dashboard_name}"
    chart_config = data.get("chart_config")
    
    if not dashboard_name or not chart_config:
        return json_response({"error": "Missing dashboard name or config"}, 400)
        
    try:
        with db_query() as (conn, cur):
        
            cur.execute("""
                INSERT INTO user_custom_charts (username, dashboard_name, chart_config, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (username, dashboard_name) 
                DO UPDATE SET chart_config = EXCLUDED.chart_config, updated_at = CURRENT_TIMESTAMP
            """, [username, dashboard_name, json.dumps(chart_config)])
            conn.commit()
            return json_response({"success": True, "message": "Dashboard saved successfully"})
    except Exception as e:
        return json_response({"error": str(e)}, 500)

@dashboard_4g.route("/api/dashboard_4g/delete_chart", methods=["POST"])
@login_required
def delete_custom_chart():
    username = session.get("username", "User")
    data = request.get_json()
    dashboard_name = data.get("dashboard_name", "").strip()
    if dashboard_name and not dashboard_name.upper().startswith("4G"):
        dashboard_name = f"4G - {dashboard_name}"
    
    if not dashboard_name:
        return json_response({"error": "Missing dashboard name"}, 400)
        
    try:
        with db_query() as (conn, cur):
            cur.execute("DELETE FROM user_custom_charts WHERE username = %s AND dashboard_name = %s", [username, dashboard_name])
            conn.commit()
            return json_response({"success": True, "message": "Dashboard deleted successfully"})
    except Exception as e:
        return json_response({"error": str(e)}, 500)

@dashboard_4g.route("/api/filter_list_4g", methods=["GET"])
@login_required
def get_filter_list_4g():
    ftype = request.args.get("filter_type", "siteid")
    try:
        if ftype == "city":
            items, _ = get_city_list_4g()
        elif ftype == "site_cell":
            items, _ = get_site_cell_list_4g()
        else:
            items, _ = get_site_list_4g()
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@dashboard_4g.route("/api/dashboard_4g_tech", methods=["POST"])
@login_required
def dashboard_4g_tech_api():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Missing JSON data"})
            
        trend_from_date = data.get("trend_from_date")
        trend_to_date = data.get("trend_to_date")
        before_from_date = data.get("before_from_date")
        before_to_date = data.get("before_to_date")
        after_from_date = data.get("after_from_date")
        after_to_date = data.get("after_to_date")
        
        filter_type = data.get("filter_type", "siteid")
        sel_sites = data.get("site", [])
        site_paste = data.get("site_paste", "")
        
        if site_paste:
            extra = [s.strip() for s in site_paste.replace("\\n", ",").split(",") if s.strip()]
            for s in extra:
                if s not in sel_sites:
                    sel_sites.append(s)
                    
        sel_sites_db = [s.strip() for s in sel_sites if s.strip()]
        
        if filter_type == "city":
            if not sel_sites_db:
                sel_sites_db = ['UNKNOWN']
            where_entity = "city IN %s"
            sel_sites_param = tuple(sel_sites_db)
        elif filter_type == "site_cell":
            parsed = []
            for s in sel_sites_db:
                if '-' in s:
                    sid, c = s.rsplit('-', 1)
                    try:
                        parsed.append((sid, float(c)))
                    except ValueError:
                        pass
            if not parsed:
                parsed = [('UNKNOWN', -1)]
            where_entity = "(siteid, cell) IN %s"
            sel_sites_param = tuple(parsed)
        else:
            if not sel_sites_db:
                sel_sites_db = ['UNKNOWN']
            where_entity = "siteid IN %s"
            sel_sites_param = tuple(sel_sites_db)

        sel_kpis = data.get("kpi", [])
        if not sel_kpis:
            sel_kpis = DEFAULT_KPIS
            
        KPI_DEFS = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]
        kpi_selects = ", ".join([f"{k[6]} AS {k[0]}" for k in KPI_DEFS])
        
        fdd_bands = data.get("fdd_bands", [])
        tdd_bands = data.get("tdd_bands", [])
        
        band_mapping = """
            CASE RIGHT(cell::text, 1)
                WHEN '1' THEN 'L1800'
                WHEN '2' THEN 'L900'
                WHEN '3' THEN 'L2100'
                WHEN '4' THEN 'L2300_1'
                WHEN '5' THEN 'L2300_2'
                WHEN '6' THEN 'L2300_3'
                WHEN '7' THEN 'L700'
                ELSE 'Unknown'
            END
        """
        
        fdd_tup = tuple(fdd_bands) if fdd_bands else ('__NONE__',)
        tdd_tup = tuple(tdd_bands) if tdd_bands else ('__NONE__',)
        
        tech_case = f"""
            CASE 
                WHEN {band_mapping} IN %s THEN 'FDD'
                WHEN {band_mapping} IN %s THEN 'TDD'
                ELSE 'Unknown'
            END
        """
        
        has_trend = trend_from_date and trend_to_date and sel_sites and KPI_DEFS
        has_compare = before_from_date and before_to_date and after_from_date and after_to_date and sel_sites and KPI_DEFS
        
        from collections import defaultdict
        
        result = {
            "success": True,
            "trend_labels": [],
            "daily_trend_labels": [],
            "hourly_trend_labels": [],
            "tech_trend_chart_data": defaultdict(lambda: defaultdict(list)),
            "daily_tech_trend_chart_data": defaultdict(lambda: defaultdict(list)),
            "hourly_tech_trend_chart_data": defaultdict(lambda: defaultdict(list)),
            "tech_compare": defaultdict(dict)
        }
        
        with db_query() as (conn, cur):
            if has_trend:
                query_trend_tech = f"""
                    SELECT 
                        CASE WHEN GROUPING(datehour) = 1 THEN TO_CHAR(date, 'YYYY-MM-DD') ELSE TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI') END AS dt_label,
                        CASE WHEN GROUPING(datehour) = 1 THEN 'daily' ELSE 'hourly' END AS gran,
                        date,
                        datehour,
                        {tech_case} AS tech,
                        {kpi_selects}
                    FROM "4g_kpi_zte"
                    WHERE date BETWEEN %s AND %s AND {where_entity}
                    GROUP BY GROUPING SETS (
                        (date, {tech_case}),
                        (date, datehour, {tech_case})
                    )
                    ORDER BY gran, date, datehour NULLS FIRST
                """
                cur.execute(query_trend_tech, [fdd_tup, tdd_tup, fdd_tup, tdd_tup, trend_from_date, trend_to_date, sel_sites_param])
                rows_tech_trend = cur.fetchall()
                
                daily_trend_labels = []
                hourly_trend_labels = []
                daily_tech_map = defaultdict(dict)
                hourly_tech_map = defaultdict(dict)

                for r in rows_tech_trend:
                    dt_label, gran, d, dh, tech = r[:5]
                    kpis = r[5:]
                    if tech != 'Unknown':
                        if gran == 'daily':
                            if dt_label not in daily_trend_labels:
                                daily_trend_labels.append(dt_label)
                            daily_tech_map[tech][dt_label] = kpis
                        else:
                            if dt_label not in hourly_trend_labels:
                                hourly_trend_labels.append(dt_label)
                            hourly_tech_map[tech][dt_label] = kpis

                result["daily_trend_labels"] = daily_trend_labels
                result["hourly_trend_labels"] = hourly_trend_labels
                result["trend_labels"] = daily_trend_labels

                for tech in ['FDD', 'TDD']:
                    for idx, kpi in enumerate(KPI_DEFS):
                        kpi_id = kpi[0]
                        for dt in daily_trend_labels:
                            val_row = daily_tech_map[tech].get(dt)
                            val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                            result["daily_tech_trend_chart_data"][kpi_id][tech].append(val)
                            result["tech_trend_chart_data"][kpi_id][tech].append(val)
                        for hr in hourly_trend_labels:
                            val_row = hourly_tech_map[tech].get(hr)
                            val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                            result["hourly_tech_trend_chart_data"][kpi_id][tech].append(val)
                            
            if has_compare:
                def get_tech_compare(from_d, to_d):
                    cur.execute(f"""
                        SELECT 
                            {tech_case} AS tech,
                            {kpi_selects}
                        FROM "4g_kpi_zte"
                        WHERE date BETWEEN %s AND %s AND {where_entity}
                        GROUP BY tech
                    """, [fdd_tup, tdd_tup, from_d, to_d, sel_sites_param])
                    return cur.fetchall()
                    
                tech_before_rows = get_tech_compare(before_from_date, before_to_date)
                tech_after_rows = get_tech_compare(after_from_date, after_to_date)
                
                tech_before_map = {r[0]: r[1:] for r in tech_before_rows} if tech_before_rows else {}
                tech_after_map = {r[0]: r[1:] for r in tech_after_rows} if tech_after_rows else {}
                
                for tech in ['FDD', 'TDD']:
                    for idx, kpi in enumerate(KPI_DEFS):
                        kpi_id = kpi[0]
                        val_before = round(float(tech_before_map[tech][idx]), 2) if tech in tech_before_map and tech_before_map[tech][idx] is not None else None
                        val_after = round(float(tech_after_map[tech][idx]), 2) if tech in tech_after_map and tech_after_map[tech][idx] is not None else None
                        
                        delta = None
                        perc = None
                        if val_before is not None and val_after is not None:
                            delta = round(val_after - val_before, 2)
                            perc = round((delta / val_before) * 100, 2) if val_before != 0 else 0.0
                            
                        result["tech_compare"][tech][kpi_id] = {
                            "before": val_before,
                            "after": val_after,
                            "delta": delta,
                            "perc": perc
                        }
                        
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
