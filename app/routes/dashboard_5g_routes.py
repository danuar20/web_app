"""5G Dashboard Routes — /dashboard_5g"""
from flask import Blueprint, render_template, request, session, flash, make_response, jsonify
from app.db.db_webapp import get_postgres_connection, get_site_list_5g, get_site_cellid_list_5g
from ._utils import login_required, _no_cache, json_response, db_query
import psycopg2
import psycopg2.extras
import psycopg2.errors
from collections import defaultdict
import json
import logging
from contextlib import closing
from .kpi_5g_monitoring_routes import DEFAULT_KPIS

logger = logging.getLogger(__name__)

dashboard_5g = Blueprint("dashboard_5g", __name__)

ALL_KPI_DEFS = [
    # chart_id, title, unit, y_label, y_min, y_max, sql_expr, group_name, is_lower_better
    ("payloadChart", "Payload", "GB", "Payload (GB)", None, None, 'ROUND((SUM("5g_payload_mb") / 1024.0)::numeric, 3)', "Productivity", False),
    ("dlPayloadChart", "DL Payload", "GB", "DL Payload (GB)", None, None, 'ROUND((SUM(payload_dl_mbyte_xhj) / 1024.0)::numeric, 3)', "Productivity", False),
    ("ulPayloadChart", "UL Payload", "GB", "UL Payload (GB)", None, None, 'ROUND((SUM(payload_ul_mbyte_xhj) / 1024.0)::numeric, 3)', "Productivity", False),
    
    ("availChart", "Availability", "%", "Availability (%)", None, 100, 'CASE WHEN SUM(denum_availability_xhj) > 0 THEN ROUND((SUM(num_availability_xhj) / SUM(denum_availability_xhj) * 100.0)::numeric, 2) ELSE NULL END', "Availability", False),
    
    ("rrcChart", "Max RRC User", "Users", "Max RRC User", None, None, 'SUM(max_rrc_user_number_xhj)', "User", False),
    ("activeUserChart", "NR Active User", "Users", "NR Active User", None, None, 'SUM(nr_active_user_number)', "User", False),
    
    ("accessibilityChart", "NR Accessibility", "%", "NR Accessibility (%)", None, 100, 'CASE WHEN SUM(number_of_sn_add_requests) > 0 THEN ROUND((SUM(num_sn_setup_success_rate_xhj) / SUM(number_of_sn_add_requests) * 100.0)::numeric, 2) ELSE NULL END', "Accessibility", False),
    
    ("retainabilityChart", "NR Retainability", "%", "NR Retainability (%)", None, 100, 'CASE WHEN SUM(denum_nr_retainability_xhj) > 0 THEN ROUND((100.0 - (SUM(num_nr_retainability_xhj) / SUM(denum_nr_retainability_xhj) * 100.0))::numeric, 2) ELSE NULL END', "Retainability", False),
    
    ("mobilityChart", "NR Mobility SR", "%", "NR Mobility SR (%)", None, 100, 'CASE WHEN SUM(nr_mobility_success_rate_denum) > 0 THEN ROUND((SUM(nr_mobility_success_rate_num) / SUM(nr_mobility_success_rate_denum) * 100.0)::numeric, 2) ELSE NULL END', "Mobility", False),
    
    ("dlPrbChart", "DL PRB", "%", "DL PRB (%)", 0, 100, 'CASE WHEN SUM(denum_prb_utilization_dl_xhj) > 0 THEN ROUND((SUM(num_prb_utilization_dl_xhj) / SUM(denum_prb_utilization_dl_xhj) * 100.0)::numeric, 2) ELSE NULL END', "Capacity", False),
    ("ulPrbChart", "UL PRB", "%", "UL PRB (%)", 0, 100, 'CASE WHEN SUM(denum_prb_utilization_ul_xhj) > 0 THEN ROUND((SUM(num_prb_utilization_ul_xhj) / SUM(denum_prb_utilization_ul_xhj) * 100.0)::numeric, 2) ELSE NULL END', "Capacity", False),
    
    ("cellDlThpChart", "Cell DL Thp", "Mbps", "Cell DL Thp (Mbps)", 0, None, 'ROUND((AVG(cell_throughput_dl_xhj))::numeric, 2)', "Integrity", False),
    ("cellUlThpChart", "Cell UL Thp", "Mbps", "Cell UL Thp (Mbps)", 0, None, 'ROUND((AVG(cell_throughput_ul_xhj) )::numeric, 2)', "Integrity", False),
    ("dlThpChart", "User DL Thp", "Mbps", "User DL Thp (Mbps)", None, None, 'CASE WHEN SUM(denum_user_throughput_dl_xhj) > 0 THEN ROUND((SUM(num_user_throughput_dl_xhj) / SUM(denum_user_throughput_dl_xhj) )::numeric, 2) ELSE NULL END', "Integrity", False),
    ("ulThpChart", "User UL Thp", "Mbps", "User UL Thp (Mbps)", None, None, 'CASE WHEN SUM(denum_user_throughput_ul_xhj) > 0 THEN ROUND((SUM(num_user_throughput_ul_xhj) / SUM(denum_user_throughput_ul_xhj) )::numeric, 2) ELSE NULL END', "Integrity", False),
    
    ("seChart", "SE", "", "SE", 0, None, 'CASE WHEN SUM(spectrum_eff_bps_lw_denum) > 0 THEN ROUND((SUM(spectrum_eff_bps_lw_num) / SUM(spectrum_eff_bps_lw_denum))::numeric, 4) ELSE NULL END', "Quality", False),
    ("cqiChart", "CQI", "", "CQI", 0, None, 'CASE WHEN SUM(denum_average_cqi_xhj) > 0 THEN ROUND((SUM(num_average_cqi_xhj) / SUM(denum_average_cqi_xhj))::numeric, 2) ELSE NULL END', "Quality", False),
    ("ulIntChart", "UL Interference", "dBm", "UL Interference (dBm)", -120, -90, 'ROUND(AVG(avg_uplink_interference_xhj)::numeric, 2)', "Quality", True),
    ("plChart", "Packet Loss", "%", "Packet Loss (%)", 0, None, 'CASE WHEN SUM(denum_packet_loss_xhj) > 0 THEN ROUND((SUM(num_packet_loss_xhj) / SUM(denum_packet_loss_xhj) * 100.0)::numeric, 2) ELSE NULL END', "Quality", True),
    ("latDlChart", "Latency DL", "ms", "Latency DL (ms)", 0, None, 'CASE WHEN SUM(denum_latency_dl_xhj) > 0 THEN ROUND((SUM(num_latency_dl_xhj) / SUM(denum_latency_dl_xhj))::numeric, 2) ELSE NULL END', "Quality", True),
    ("latUlChart", "Latency UL", "ms", "Latency UL (ms)", 0, None, 'CASE WHEN SUM(denum_latency_ul_xhj) > 0 THEN ROUND((SUM(num_latency_ul_xhj) / SUM(denum_latency_ul_xhj))::numeric, 2) ELSE NULL END', "Quality", True),
]

KPI_GROUPS = ["Productivity","Availability","User","Accessibility","Retainability","Capacity","Integrity","Mobility","Quality","Hardware","Others"]


@dashboard_5g.route("/dashboard_5g")
@login_required
def dashboard_5g_view():
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
    
    if filter_type == "site_cell":
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
        where_entity = "(siteid, cellid) IN %s"
        sel_sites_param = tuple(parsed)
        group_entity = "siteid || '-' || REPLACE(cellid::text, '.0', '')"
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
        if filter_type == "site_cell":
            sites_list, _ = get_site_cellid_list_5g()
        else:
            sites_list, _ = get_site_list_5g()
    except Exception:
        sites_list = []

    last_update = None
    
    # Initialize response structures
    trend_labels = []
    trend_chart_data = defaultdict(lambda: {"total": {}})
    band_trend_chart_data = defaultdict(lambda: defaultdict(list))
    site_trend_chart_data = defaultdict(lambda: defaultdict(list))
    
    cluster_compare = {}
    band_compare = defaultdict(dict)
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
                    cur.execute('SELECT MAX(datehour::date) FROM "5g_kpi_zte"')
                    raw_last = cur.fetchone()
                    last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
                except Exception:
                    last_update = None

                kpi_selects = ", ".join([f"{k[6]} AS {k[0]}" for k in KPI_DEFS])
            
                # --- TREND DATA ---
                if has_trend:
                    # 1. Cluster Trend
                    query_trend = f"""
                        SELECT 
                            TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI') AS dt_label,
                            datehour,
                            {kpi_selects}
                        FROM "5g_kpi_zte"
                        WHERE date BETWEEN %s AND %s AND {where_entity}
                        GROUP BY datehour, dt_label ORDER BY datehour
                    """
                    cur.execute(query_trend, [trend_from_date, trend_to_date, sel_sites_param])
                    rows_trend = cur.fetchall()
                
                    # Keep original order by date
                    trend_labels = []
                    trend_map = {}
                    for r in rows_trend:
                        if r[0] not in trend_labels:
                            trend_labels.append(r[0])
                        trend_map[r[0]] = r[2:]
                
                    # We need to initialize total arrays
                    for kpi in KPI_DEFS:
                        trend_chart_data[kpi[0]]["total"] = []
                
                    for idx, kpi in enumerate(KPI_DEFS):
                        kpi_id = kpi[0]
                        for hr in trend_labels:
                            val_row = trend_map.get(hr)
                            val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                            trend_chart_data[kpi_id]["total"].append(val)
                
                # --- TREND DATA ---
                if has_trend:
                    band_expr = """CASE RIGHT(cellid::text, 1)
                                WHEN '1' THEN 'NR1800'
                                WHEN '2' THEN 'NR900'
                                WHEN '3' THEN 'NR2100'
                                WHEN '4' THEN 'NR2300_1'
                                WHEN '5' THEN 'NR2300_2'
                                WHEN '6' THEN 'NR2300_3'
                                WHEN '7' THEN 'NR700'
                                ELSE 'Unknown'
                            END"""

                    query_trend_all = f"""
                        SELECT 
                            TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI') AS dt_label,
                            datehour,
                            {group_entity} AS siteid,
                            {band_expr} AS band,
                            GROUPING({group_entity}) AS g_site,
                            GROUPING({band_expr}) AS g_band,
                            {kpi_selects}
                        FROM "5g_kpi_zte"
                        WHERE date BETWEEN %s AND %s AND {where_entity}
                        GROUP BY GROUPING SETS (
                            (datehour, dt_label),
                            (datehour, dt_label, {group_entity}),
                            (datehour, dt_label, {band_expr})
                        )
                        ORDER BY datehour
                    """
                    cur.execute(query_trend_all, [trend_from_date, trend_to_date, sel_sites_param])
                    rows_trend_all = cur.fetchall()

                    trend_labels = []
                    trend_map = {}
                    site_trend_map = defaultdict(dict)
                    band_trend_map = defaultdict(dict)

                    for r in rows_trend_all:
                        dt_label, dh, siteid, band, g_site, g_band = r[:6]
                        kpis = r[6:]

                        if dt_label not in trend_labels:
                            trend_labels.append(dt_label)

                        if g_site == 1 and g_band == 1:
                            trend_map[dt_label] = kpis
                        elif g_site == 0:
                            site_trend_map[siteid][dt_label] = kpis
                        elif g_band == 0:
                            band_trend_map[band][dt_label] = kpis

                    for kpi in KPI_DEFS:
                        trend_chart_data[kpi[0]]["total"] = []

                    for idx, kpi in enumerate(KPI_DEFS):
                        kpi_id = kpi[0]
                        for hr in trend_labels:
                            val_row = trend_map.get(hr)
                            val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                            trend_chart_data[kpi_id]["total"].append(val)

                    for site in site_trend_map:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            for hr in trend_labels:
                                val_row = site_trend_map[site].get(hr)
                                val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                                site_trend_chart_data[kpi_id][site].append(val)

                    for band in band_trend_map:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            for hr in trend_labels:
                                val_row = band_trend_map[band].get(hr)
                                val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                                band_trend_chart_data[kpi_id][band].append(val)
                            
                # --- COMPARE DATA ---
                if has_compare:
                    def get_aggregates(from_d, to_d):
                        band_expr = """CASE RIGHT(cellid::text, 1)
                                    WHEN '1' THEN 'L1800'
                                    WHEN '2' THEN 'L900'
                                    WHEN '3' THEN 'L2100'
                                    WHEN '4' THEN 'L2300_1'
                                    WHEN '5' THEN 'L2300_2'
                                    WHEN '6' THEN 'L2300_3'
                                    WHEN '7' THEN 'L700'
                                    ELSE 'Unknown'
                                END"""
                        sector_expr = """CASE
                                    WHEN LENGTH(cellid::text) > 2 AND RIGHT(cellid::text, 1) = '5' THEN SUBSTRING(cellid::text FROM 2 FOR 1)
                                    WHEN LENGTH(cellid::text) > 2 THEN LEFT(cellid::text, 2)
                                    ELSE LEFT(cellid::text, 1)
                                END"""

                        query_compare = f"""
                            SELECT 
                                {group_entity} AS siteid,
                                {band_expr} AS band,
                                {sector_expr} AS sector,
                                GROUPING({group_entity}) AS g_site,
                                GROUPING({band_expr}) AS g_band,
                                GROUPING({sector_expr}) AS g_sector,
                                {kpi_selects}
                            FROM "5g_kpi_zte"
                            WHERE date BETWEEN %s AND %s AND {where_entity}
                            GROUP BY GROUPING SETS (
                                (),
                                ({band_expr}),
                                ({group_entity}, {sector_expr}),
                                ({group_entity})
                            )
                        """
                        cur.execute(query_compare, [from_d, to_d, sel_sites_param])
                        rows = cur.fetchall()
                        
                        cluster_row = None
                        band_rows = []
                        sector_rows = []
                        site_rows = []
                        
                        for r in rows:
                            siteid, band, sector, g_site, g_band, g_sector = r[:6]
                            kpis = r[6:]
                            
                            if g_site == 1 and g_band == 1 and g_sector == 1:
                                cluster_row = kpis
                            elif g_band == 0 and g_site == 1:
                                band_rows.append((band,) + kpis)
                            elif g_sector == 0 and g_site == 0:
                                sector_rows.append((siteid, sector) + kpis)
                            elif g_site == 0 and g_sector == 1:
                                site_rows.append((siteid,) + kpis)
                                
                        return cluster_row, band_rows, sector_rows, site_rows

                    b_cluster, b_band, b_sector, b_site = get_aggregates(before_from_date, before_to_date)
                    a_cluster, a_band, a_sector, a_site = get_aggregates(after_from_date, after_to_date)
                
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
                            FROM "5g_kpi_zte"
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
                cur.execute("SELECT id, dashboard_name, chart_config FROM user_custom_charts WHERE username = %s AND dashboard_name LIKE '5G%%' ORDER BY dashboard_name", [username])
                user_charts = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("Error fetching custom charts: %s", e)

    return _no_cache(make_response(render_template(
        "dashboard_5g.html",
        username=username,
        filter_type=filter_type,
        sites_list=sites_list,
        sel_sites=sel_sites,
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
        
        trend_labels=trend_labels,
        trend_chart_data=dict(trend_chart_data),
        site_trend_chart_data=dict(site_trend_chart_data),
        band_trend_chart_data=dict(band_trend_chart_data),
        
        cluster_compare=cluster_compare,
        band_compare=dict(sorted(band_compare.items(), key=lambda x: (len(x[0]), x[0]))),
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

@dashboard_5g.route("/api/dashboard_5g/save_chart", methods=["POST"])
@login_required
def save_custom_chart():
    username = session.get("username", "User")
    data = request.get_json()
    dashboard_name = data.get("dashboard_name", "").strip()
    if dashboard_name and not dashboard_name.upper().startswith("5G"):
        dashboard_name = f"5G - {dashboard_name}"
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

@dashboard_5g.route("/api/dashboard_5g/delete_chart", methods=["POST"])
@login_required
def delete_custom_chart():
    username = session.get("username", "User")
    data = request.get_json()
    dashboard_name = data.get("dashboard_name", "").strip()
    if dashboard_name and not dashboard_name.upper().startswith("5G"):
        dashboard_name = f"5G - {dashboard_name}"
    
    if not dashboard_name:
        return json_response({"error": "Missing dashboard name"}, 400)
        
    try:
        with db_query() as (conn, cur):
            cur.execute("DELETE FROM user_custom_charts WHERE username = %s AND dashboard_name = %s", [username, dashboard_name])
            conn.commit()
            return json_response({"success": True, "message": "Dashboard deleted successfully"})
    except Exception as e:
        return json_response({"error": str(e)}, 500)

@dashboard_5g.route("/api/filter_list_5g", methods=["GET"])
@login_required
def get_filter_list_5g():
    ftype = request.args.get("filter_type", "siteid")
    try:
        if ftype == "site_cell":
            items, _ = get_site_cellid_list_5g()
        else:
            items, _ = get_site_list_5g()
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
