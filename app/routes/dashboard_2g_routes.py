"""2G Dashboard Routes — /dashboard_2g"""
from flask import Blueprint, render_template, request, session, flash, make_response, jsonify
from app.db.db_webapp import get_postgres_connection, get_site_list_2g, get_site_cell_list_2g, get_city_list_2g, get_bsc_list_2g
from ._utils import login_required, _no_cache, json_response, db_query
import psycopg2
import psycopg2.extras
import psycopg2.errors
from collections import defaultdict
import json
import logging
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from .kpi_2g_monitoring_routes import DEFAULT_KPIS

logger = logging.getLogger(__name__)

dashboard_2g = Blueprint("dashboard_2g", __name__)

ALL_KPI_DEFS = [
    # chart_id, title, unit, y_label, y_min, y_max, sql_expr, group_name, is_lower_better

    # --- Productivity ---
    ("payloadChart",       "Payload",              "GB",   "Payload (GB)", 0,    None,
     "SUM(total_payload)::numeric/1024",  "Productivity", False),
    ("tchTrafficChart",    "TCH Traffic",           "Erl",  "TCH Traffic (Erl)", 0,    None,
     "ROUND(SUM(tch_traffic)::numeric, 2)",         "Productivity", False),
    ("sdcchTrafficChart",  "SDCCH Traffic",         "Erl",  "SDCCH Traffic (Erl)", 0,    None,
     "ROUND(SUM(sdcch_traffic)::numeric, 2)",       "Productivity", False),
    ("fullRateChart",      "Full Rate Traffic",     "Erl",  "Full Rate Traffic (Erl)", 0,    None,
     'ROUND(SUM("Offic_full_traffic")::numeric, 2)', "Productivity", False),
    ("halfRateChart",      "Half Rate Traffic",     "Erl",  "Half Rate Traffic (Erl)", 0,    None,
     'ROUND(SUM("Offic_half_traffic")::numeric, 2)', "Productivity", False),
    ("gprsPayloadChart",   "GPRS Payload",          "GB",   "GPRS Payload (GB)", 0,    None,
     "SUM(gprs_payload)::numeric/1024",             "Productivity", False),
    ("edgePayloadChart",   "EDGE Payload",          "GB",   "EDGE Payload (GB)", 0,    None,
     "SUM(edge_payload)::numeric/1024",             "Productivity", False),

    # --- Availability ---
    ("availChart",         "Availability",          "%",    "Availability (%)", None, 100,
     "CASE WHEN SUM(tch_avail_denum)>0 THEN ROUND((SUM(tch_avail_num)/SUM(tch_avail_denum)*100)::numeric,2) ELSE NULL END",
     "Availability", False),

    # --- Accessibility ---
    ("cssrChart",          "CSSR",                  "%",    "CSSR (%)", None, 100,
     "CASE WHEN SUM(cssr_denum)>0 THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100)::numeric,2) ELSE NULL END",
     "Accessibility", False),
    ("sdsrChart",          "SDSR",                  "%",    "SDSR (%)", None, 100,
     "CASE WHEN SUM(sdsr_denum)>0 THEN ROUND((SUM(sdsr_num)/SUM(sdsr_denum)*100)::numeric,2) ELSE NULL END",
     "Accessibility", False),
    ("tbfEstChart",        "TBF DL Est",            "%",    "TBF DL Est (%)", None, 100,
     "CASE WHEN SUM(tbf_dl_est_denum)>0 THEN ROUND((SUM(tbf_dl_est_num)/SUM(tbf_dl_est_denum)*100)::numeric,2) ELSE NULL END",
     "Accessibility", False),
    ("tchBlkChart",        "TCH Blocking",          "%",    "TCH Blocking (%)", 0,    None,
     "CASE WHEN SUM(tch_block_denum)>0 THEN ROUND((SUM(tch_block_num)/SUM(tch_block_denum)*100)::numeric,2) ELSE NULL END",
     "Accessibility", True),
    ("tchBlkNumChart",     "TCH Block Num",         "num",     "TCH Block Num", 0,    None,
     "ROUND(SUM(tch_block_num)::numeric, 0)",       "Accessibility", True),
    ("sdcchBlkChart",      "SDCCH Blocking",        "%",    "SDCCH Blocking (%)", 0,    None,
     "CASE WHEN SUM(sdcch_block_denum)>0 THEN ROUND((SUM(sdcch_block_num)/SUM(sdcch_block_denum)*100)::numeric,2) ELSE NULL END",
     "Accessibility", True),
    ("sdcchBlkNumChart",   "SDCCH Block Num",       "num",     "SDCCH Block Num", 0,    None,
     "ROUND(SUM(sdcch_block_num)::numeric, 0)",     "Accessibility", True),
    ("sdToTchChart",       "SD to TCH",             "%",    "SD to TCH (%)", None,    100,
     "ROUND((AVG(sd_to_tch)*100)::numeric, 2)",     "Accessibility", False),
    ("cstChart",           "CST",                   "ms",   "CST (ms)", 0,    None,
     "ROUND(AVG(cst)::numeric, 2)",                 "Accessibility", False),
    ("pdchAllocFailChart", "PDCH Alocation Fail",   "%",    "PDCH Alloc Fail (%)", None,    None,
     "CASE WHEN SUM(pdch_alocation_failure_rate_denum)>0 THEN ROUND((SUM(pdch_alocation_failure_rate_num)/SUM(pdch_alocation_failure_rate_denum)*100)::numeric,2) ELSE NULL END",
     "Accessibility", True),

    # --- Retainability ---
    ("ccsrChart",          "CCSR",                  "%",    "CCSR (%)", None, 100,
     'CASE WHEN SUM("2g_ccsr_denum")>0 THEN ROUND((SUM("2g_ccsr_num")/SUM("2g_ccsr_denum")*100)::numeric,2) ELSE NULL END',
     "Retainability", False),
    ("tbfCompChart",       "TBF Comp",              "%",    "TBF Comp (%)", None, 100,
     "CASE WHEN SUM(tbf_comp_denum)>0 THEN ROUND((SUM(tbf_comp_num)/SUM(tbf_comp_denum)*100)::numeric,2) ELSE NULL END",
     "Retainability", False),
    ("tchDropChart",       "TCH Drop",              "%",    "TCH Drop (%)", 0,    None,
     "CASE WHEN SUM(tch_drop_denum)>0 THEN ROUND((SUM(tch_drop_num)/SUM(tch_drop_denum)*100)::numeric,2) ELSE NULL END",
     "Retainability", True),
    ("tchDropNumChart",    "TCH Drop Num",          "num",     "TCH Drop Num", 0,    None,
     "ROUND(SUM(tch_drop_num)::numeric, 0)",        "Retainability", True),

    # --- Mobility ---
    ("hosrChart",          "HOSR",                  "%",    "HOSR (%)", None, 100,
     "CASE WHEN SUM(hosr_denum)>0 THEN ROUND((SUM(hosr_num)/SUM(hosr_denum)*100)::numeric,2) ELSE NULL END",
     "Mobility", False),
    ("fastRetChart",       "Fast Return to LTE",    "num",     "Fast Return to LTE", 0,    None,
     "ROUND(SUM(fastreturn_to_lte)::numeric, 0)",   "Mobility", False),

    # --- Quality ---
    ("icmChart",           "ICM Band 3-5",          "%",    "ICM Band 3-5 (%)", 0,    None,
     "CASE WHEN SUM(icm_band35_denum)>0 THEN ROUND((SUM(icm_band35_num)/SUM(icm_band35_denum)*100)::numeric,2) ELSE NULL END",
     "Quality", True),
    ("interfChart",        "Interference",          "%",    "Interference (%)", None,    100,
     "CASE WHEN SUM(denum_icm_interference_ono)>0 THEN ROUND((SUM(num_icm_interference_ono)/SUM(denum_icm_interference_ono)*100)::numeric,2) ELSE NULL END",
     "Quality", True),
    ("dlMosChart",         "DL MOS",                "mos",     "DL MOS", None,    None,
     "ROUND(AVG(mos_dl)::numeric, 2)",              "Quality", False),
    ("ulMosChart",         "UL MOS",                "mos",     "UL MOS", None,    None,
     "ROUND(AVG(mos_ul)::numeric, 2)",              "Quality", False),
    ("dlQualChart",        "DL Qual",               "%",    "DL Qual (%)", None,    None,
     "CASE WHEN SUM(denum_dl_qual_0_5)>0 THEN ROUND((SUM(num_dl_qual_0_5)/SUM(denum_dl_qual_0_5)*100)::numeric,2) ELSE NULL END",
     "Quality", True),
    ("ulQualChart",        "UL Qual",               "%",    "UL Qual (%)", None,    None,
     "CASE WHEN SUM(denum_ul_qual)>0 THEN ROUND((SUM(num_ul_qual_0_5)/SUM(denum_ul_qual)*100)::numeric,2) ELSE NULL END",
     "Quality", True),

    # --- Integrity ---
    ("gprsDlThpChart",     "GPRS DL Thp",           "Kbps", "GPRS DL Thp (Kbps)", 0,    None,
     "ROUND(AVG(gprs_dl_thp)::numeric, 2)",         "Integrity", False),
    ("edgeDlThpChart",     "EDGE DL Thp",           "Kbps", "EDGE DL Thp (Kbps)", 0,    None,
     "ROUND(AVG(edge_dl_thp)::numeric, 2)",         "Integrity", False),
]

KPI_GROUPS = ["Productivity", "Availability", "Accessibility", "Retainability", "Mobility", "Quality", "Integrity", "Others"]

@dashboard_2g.route("/dashboard_2g")
@login_required
def dashboard_2g_view():
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
    
    # Support cluster mapping from CSV (entity -> cluster)
    cluster_mapping_raw = request.args.get("cluster_mapping", "")
    cluster_mapping = {}
    if cluster_mapping_raw:
        try:
            cluster_mapping = json.loads(cluster_mapping_raw)
            if not isinstance(cluster_mapping, dict):
                cluster_mapping = {}
        except Exception:
            cluster_mapping = {}

    # If cluster_mapping has items, ensure all mapped entities are in sel_sites
    if cluster_mapping:
        for k in cluster_mapping.keys():
            if k not in sel_sites:
                sel_sites.append(k)

    # Support site IDs pasted from CSV — comma/newline separated, deduplicate
    site_paste_raw = request.args.get("site_paste", "")
    if site_paste_raw:
        extra = [s.strip() for s in site_paste_raw.replace("\n", ",").split(",") if s.strip()]
        for s in extra:
            if s not in sel_sites:
                sel_sites.append(s)
                
    sel_sites_db = list(dict.fromkeys([s.strip().upper() for s in sel_sites if s.strip()]))

    # Normalize cluster mapping
    cluster_mapping_norm = {}
    if cluster_mapping:
        for k, v in cluster_mapping.items():
            k_clean = str(k).strip().upper()
            v_clean = str(v).strip().upper()
            if k_clean and v_clean:
                cluster_mapping_norm[k_clean] = v_clean
        cluster_list = sorted(list(set(cluster_mapping_norm.values())))
        is_cluster_mode = len(cluster_list) > 0
    else:
        cluster_list = []
        is_cluster_mode = False
    
    if filter_type == "city":
        if not sel_sites_db:
            sel_sites_db = ['UNKNOWN']
        if is_cluster_mode:
            cities_arr = []
            clusters_arr = []
            for c in sel_sites_db:
                cities_arr.append(c)
                clusters_arr.append(cluster_mapping_norm.get(c, 'Other'))
            from_entity_clause = 'FROM unnest(%s::text[], %s::text[]) AS cl(cl_city, cluster) JOIN "2g_kpi_zte" ON city = cl.cl_city'
            from_entity_params = [cities_arr, clusters_arr]
            group_entity = "cl.cluster"
        else:
            from_entity_clause = 'FROM unnest(%s::text[]) AS cl(cl_city) JOIN "2g_kpi_zte" ON city = cl.cl_city'
            from_entity_params = [sel_sites_db]
            group_entity = "cl.cl_city"
    elif filter_type == "bsc":
        if not sel_sites_db:
            sel_sites_db = ['UNKNOWN']
        if is_cluster_mode:
            bscs_arr = []
            clusters_arr = []
            for b in sel_sites_db:
                bscs_arr.append(b)
                clusters_arr.append(cluster_mapping_norm.get(b, 'Other'))
            from_entity_clause = 'FROM unnest(%s::text[], %s::text[]) AS cl(cl_bsc, cluster) JOIN "2g_kpi_zte" ON me_name = cl.cl_bsc'
            from_entity_params = [bscs_arr, clusters_arr]
            group_entity = "cl.cluster"
        else:
            from_entity_clause = 'FROM unnest(%s::text[]) AS cl(cl_bsc) JOIN "2g_kpi_zte" ON me_name = cl.cl_bsc'
            from_entity_params = [sel_sites_db]
            group_entity = "cl.cl_bsc"
    elif filter_type == "site_cell":
        parsed = []
        seen = set()
        for s in sel_sites_db:
            if '-' in s:
                sid, c = s.rsplit('-', 1)
                sid_u = sid.strip().upper()
                c_u = c.strip().upper()
                key = (sid_u, c_u)
                if key not in seen:
                    seen.add(key)
                    cluster_val = cluster_mapping_norm.get(s) or cluster_mapping_norm.get(f"{sid_u}-{c_u}") or 'Other'
                    parsed.append((sid_u, c_u, cluster_val))
        if not parsed:
            parsed = [('UNKNOWN', 'UNKNOWN', 'Other')]
            
        sites_arr = [p[0] for p in parsed]
        cells_arr = [p[1] for p in parsed]
        if is_cluster_mode:
            clusters_arr = [p[2] for p in parsed]
            from_entity_clause = 'FROM unnest(%s::text[], %s::text[], %s::text[]) AS cl(cl_siteid, cl_bts, cluster) JOIN "2g_kpi_zte" ON siteid = cl.cl_siteid AND bts::text = cl.cl_bts'
            from_entity_params = [sites_arr, cells_arr, clusters_arr]
            group_entity = "cl.cluster"
        else:
            from_entity_clause = 'FROM unnest(%s::text[], %s::text[]) AS cl(cl_siteid, cl_bts) JOIN "2g_kpi_zte" ON siteid = cl.cl_siteid AND bts::text = cl.cl_bts'
            from_entity_params = [sites_arr, cells_arr]
            group_entity = "cl.cl_siteid || '-' || cl.cl_bts"
    else:
        # site ID mode (default)
        if not sel_sites_db:
            sel_sites_db = ['UNKNOWN']
        if is_cluster_mode:
            sites_arr = []
            clusters_arr = []
            for s in sel_sites_db:
                sites_arr.append(s)
                clusters_arr.append(cluster_mapping_norm.get(s, 'Other'))
            from_entity_clause = 'FROM unnest(%s::text[], %s::text[]) AS cl(cl_siteid, cluster) JOIN "2g_kpi_zte" ON siteid = cl.cl_siteid'
            from_entity_params = [sites_arr, clusters_arr]
            group_entity = "cl.cluster"
        else:
            from_entity_clause = 'FROM unnest(%s::text[]) AS cl(cl_siteid) JOIN "2g_kpi_zte" ON siteid = cl.cl_siteid'
            from_entity_params = [sel_sites_db]
            group_entity = "cl.cl_siteid"

    sel_kpis = request.args.getlist("kpi")
    if not sel_kpis:
        sel_kpis = DEFAULT_KPIS
        
    KPI_DEFS = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]

    sites_list = []
    try:
        if filter_type == "city":
            sites_list, _ = get_city_list_2g()
        elif filter_type == "site_cell":
            sites_list, _ = get_site_cell_list_2g()
        elif filter_type == "bsc":
            sites_list, _ = get_bsc_list_2g()
        else:
            sites_list, _ = get_site_list_2g()
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
    daily_cluster_band_trend_chart_data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    hourly_cluster_band_trend_chart_data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    
    cluster_compare = {}
    band_compare = defaultdict(dict)
    cluster_band_compare = defaultdict(lambda: defaultdict(dict))
    sector_compare = defaultdict(dict)
    site_compare = defaultdict(dict)
    
    compare_hourly_labels = []
    compare_hourly_data = {}
    site_compare_hourly_data = defaultdict(lambda: {"before": defaultdict(list), "after": defaultdict(list)})
    
    has_trend = trend_from_date and trend_to_date and sel_sites and KPI_DEFS
    has_compare = before_from_date and before_to_date and after_from_date and after_to_date and sel_sites and KPI_DEFS

    if has_trend or has_compare:
        try:
            try:
                from datetime import datetime
                before_str = f"{datetime.strptime(before_from_date, '%Y-%m-%d').strftime('%d %b')} to {datetime.strptime(before_to_date, '%Y-%m-%d').strftime('%d %b')}" if before_from_date and before_to_date else ""
                after_str = f"{datetime.strptime(after_from_date, '%Y-%m-%d').strftime('%d %b')} to {datetime.strptime(after_to_date, '%Y-%m-%d').strftime('%d %b')}" if after_from_date and after_to_date else ""
            except Exception:
                before_str = ""
                after_str = ""

            try:
                with closing(get_postgres_connection()) as conn_meta:
                    with conn_meta.cursor() as cur_meta:
                        cur_meta.execute('SELECT MAX(datehour::date) FROM "2g_kpi_zte"')
                        raw_last = cur_meta.fetchone()
                        last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
            except Exception:
                last_update = None

            kpi_selects = ", ".join([f"{k[6]} AS {k[0]}" for k in KPI_DEFS])
            band_expr = 'COALESCE("Tech", \'Unknown\')'
            sector_expr = 'RIGHT(bts::text, 1)'

            query_trend_all = None
            if has_trend:
                grouping_sets_trend_daily = [
                    "(date)",
                    f"(date, {group_entity})",
                    f"(date, {band_expr})"
                ]
                grouping_sets_trend_hourly = [
                    "(date, datehour)",
                    f"(date, datehour, {group_entity})",
                    f"(date, datehour, {band_expr})"
                ]
                if is_cluster_mode:
                    grouping_sets_trend_daily.append(f"(date, {group_entity}, {band_expr})")
                    grouping_sets_trend_hourly.append(f"(date, datehour, {group_entity}, {band_expr})")

                all_trend_groupings = ", ".join(grouping_sets_trend_daily + grouping_sets_trend_hourly)

                query_trend_all = f"""
                    SELECT 
                        CASE WHEN GROUPING(datehour) = 1 THEN TO_CHAR(date, 'YYYY-MM-DD') ELSE TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI') END AS dt_label,
                        CASE WHEN GROUPING(datehour) = 1 THEN 'daily' ELSE 'hourly' END AS gran,
                        date,
                        datehour,
                        {group_entity} AS siteid,
                        {band_expr} AS band,
                        GROUPING({group_entity}) AS g_site,
                        GROUPING({band_expr}) AS g_band,
                        GROUPING(datehour) AS g_hour,
                        {kpi_selects}
                    {from_entity_clause}
                    WHERE date BETWEEN %s AND %s
                    GROUP BY GROUPING SETS (
                        {all_trend_groupings}
                    )
                """

            query_compare = None
            query_h = None
            if has_compare:
                grouping_sets_compare = [
                    "()",
                    f"({band_expr})",
                    f"({group_entity}, {sector_expr})",
                    f"({group_entity})"
                ]
                if is_cluster_mode:
                    grouping_sets_compare.append(f"({group_entity}, {band_expr})")

                all_compare_groupings = ", ".join(grouping_sets_compare)

                query_compare = f"""
                    SELECT 
                        {group_entity} AS siteid,
                        {band_expr} AS band,
                        {sector_expr} AS sector,
                        GROUPING({group_entity}) AS g_site,
                        GROUPING({band_expr}) AS g_band,
                        GROUPING({sector_expr}) AS g_sector,
                        {kpi_selects}
                    {from_entity_clause}
                    WHERE date BETWEEN %s AND %s
                    GROUP BY GROUPING SETS (
                        {all_compare_groupings}
                    )
                """

                query_h = f"""
                    SELECT 
                        TO_CHAR(datehour, 'HH24:00') AS hr,
                        {group_entity} AS siteid,
                        GROUPING({group_entity}) AS g_site,
                        {kpi_selects}
                    {from_entity_clause}
                    WHERE date BETWEEN %s AND %s
                    GROUP BY GROUPING SETS (
                        (TO_CHAR(datehour, 'HH24:00')),
                        (TO_CHAR(datehour, 'HH24:00'), {group_entity})
                    )
                    ORDER BY hr
                """

            def _split_trend_dates(d_from_str, d_to_str, max_days=7):
                try:
                    from datetime import datetime as _dt, timedelta as _td
                    d_start = _dt.strptime(d_from_str, "%Y-%m-%d").date()
                    d_end = _dt.strptime(d_to_str, "%Y-%m-%d").date()
                except Exception:
                    return [(d_from_str, d_to_str)]
                chunks = []
                curr = d_start
                while curr <= d_end:
                    chunk_end = min(curr + _td(days=max_days - 1), d_end)
                    chunks.append((curr.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
                    curr = chunk_end + _td(days=1)
                return chunks

            def run_trend_worker():
                chunks = _split_trend_dates(trend_from_date, trend_to_date, max_days=7)

                def fetch_chunk(chunk):
                    c_from, c_to = chunk
                    with closing(get_postgres_connection()) as conn_c:
                        with conn_c.cursor() as cur_c:
                            cur_c.execute("SET statement_timeout = '600000'")
                            cur_c.execute("SET work_mem = '64MB'")
                            cur_c.execute(query_trend_all, from_entity_params + [c_from, c_to])
                            return cur_c.fetchall()

                if len(chunks) <= 1:
                    all_rows = fetch_chunk(chunks[0])
                else:
                    with ThreadPoolExecutor(max_workers=2) as trend_exec:
                        chunk_results = list(trend_exec.map(fetch_chunk, chunks))
                    all_rows = []
                    for r in chunk_results:
                        all_rows.extend(r)

                from datetime import datetime as dt_cls
                all_rows.sort(key=lambda r: (r[1], r[2], r[3] if r[3] else dt_cls.min))
                return all_rows

            def run_compare_worker(from_d, to_d):
                with closing(get_postgres_connection()) as conn_c:
                    with conn_c.cursor() as cur_c:
                        cur_c.execute("SET statement_timeout = '600000'")
                        cur_c.execute("SET work_mem = '64MB'")
                        cur_c.execute(query_compare, from_entity_params + [from_d, to_d])
                        rows = cur_c.fetchall()
                        
                        cluster_row = None
                        band_rows = []
                        sector_rows = []
                        site_rows = []
                        cluster_band_rows = []
                        
                        for r in rows:
                            siteid, band, sector, g_site, g_band, g_sector = r[:6]
                            kpis = r[6:]
                            
                            if g_site == 1 and g_band == 1 and g_sector == 1:
                                cluster_row = kpis
                            elif g_band == 0 and g_site == 1 and g_sector == 1:
                                band_rows.append((band,) + kpis)
                            elif g_sector == 0 and g_site == 0 and g_band == 1:
                                sector_rows.append((siteid, sector) + kpis)
                            elif g_site == 0 and g_sector == 1 and g_band == 1:
                                site_rows.append((siteid,) + kpis)
                            elif g_site == 0 and g_band == 0 and g_sector == 1:
                                cluster_band_rows.append((siteid, band) + kpis)

                        cur_c.execute(query_h, from_entity_params + [from_d, to_d])
                        rows_h = cur_c.fetchall()
                        h_map = {}
                        site_h_map = defaultdict(dict)
                        for r in rows_h:
                            hr, siteid, g_site = r[0], r[1], r[2]
                            kpis = r[3:]
                            if g_site == 1:
                                h_map[hr] = kpis
                            else:
                                site_h_map[siteid][hr] = kpis

                        return (cluster_row, band_rows, sector_rows, site_rows, cluster_band_rows), (h_map, site_h_map)

            tasks = {}
            with ThreadPoolExecutor(max_workers=3) as executor:
                if has_trend:
                    tasks['trend'] = executor.submit(run_trend_worker)
                if has_compare:
                    tasks['before'] = executor.submit(run_compare_worker, before_from_date, before_to_date)
                    tasks['after'] = executor.submit(run_compare_worker, after_from_date, after_to_date)

            rows_trend_all = tasks['trend'].result() if 'trend' in tasks else []
            if has_compare:
                (b_cluster, b_band, b_sector, b_site, b_cband), (before_hourly_map, b_site_h_map) = tasks['before'].result()
                (a_cluster, a_band, a_sector, a_site, a_cband), (after_hourly_map, a_site_h_map) = tasks['after'].result()

            # --- TREND DATA ---
            if has_trend:
                daily_trend_map = {}
                hourly_trend_map = {}
                daily_site_trend_map = defaultdict(dict)
                hourly_site_trend_map = defaultdict(dict)
                daily_band_trend_map = defaultdict(dict)
                hourly_band_trend_map = defaultdict(dict)
                daily_cluster_band_trend_map = defaultdict(lambda: defaultdict(dict))
                hourly_cluster_band_trend_map = defaultdict(lambda: defaultdict(dict))

                for r in rows_trend_all:
                    dt_label, gran, d, dh, siteid, band, g_site, g_band, g_hour = r[:9]
                    kpis = r[9:]

                    if gran == 'daily':
                        if dt_label not in daily_trend_labels:
                            daily_trend_labels.append(dt_label)
                        if g_site == 1 and g_band == 1:
                            daily_trend_map[dt_label] = kpis
                        elif g_site == 0 and g_band == 1:
                            daily_site_trend_map[siteid][dt_label] = kpis
                        elif g_band == 0 and g_site == 1:
                            daily_band_trend_map[band][dt_label] = kpis
                        elif g_site == 0 and g_band == 0:
                            daily_cluster_band_trend_map[siteid][band][dt_label] = kpis
                    else:
                        if dt_label not in hourly_trend_labels:
                            hourly_trend_labels.append(dt_label)
                        if g_site == 1 and g_band == 1:
                            hourly_trend_map[dt_label] = kpis
                        elif g_site == 0 and g_band == 1:
                            hourly_site_trend_map[siteid][dt_label] = kpis
                        elif g_band == 0 and g_site == 1:
                            hourly_band_trend_map[band][dt_label] = kpis
                        elif g_site == 0 and g_band == 0:
                            hourly_cluster_band_trend_map[siteid][band][dt_label] = kpis

                if is_cluster_mode:
                    for cluster in cluster_list:
                        for band in daily_cluster_band_trend_map[cluster]:
                            for idx, kpi in enumerate(KPI_DEFS):
                                kpi_id = kpi[0]
                                for dt in daily_trend_labels:
                                    val_row = daily_cluster_band_trend_map[cluster][band].get(dt)
                                    val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                                    daily_cluster_band_trend_chart_data[cluster][kpi_id][band].append(val)
                        for band in hourly_cluster_band_trend_map[cluster]:
                            for idx, kpi in enumerate(KPI_DEFS):
                                kpi_id = kpi[0]
                                for hr in hourly_trend_labels:
                                    val_row = hourly_cluster_band_trend_map[cluster][band].get(hr)
                                    val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                                    hourly_cluster_band_trend_chart_data[cluster][kpi_id][band].append(val)

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
                        
            # --- COMPARE DATA ---
            if has_compare:
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

                # Process Cluster Band
                if is_cluster_mode:
                    b_cband_map = {(r[0], r[1]): r[2:] for r in b_cband}
                    a_cband_map = {(r[0], r[1]): r[2:] for r in a_cband}
                    all_cbands = set(list(b_cband_map.keys()) + list(a_cband_map.keys()))
                    for (c_name, b_name) in all_cbands:
                        for idx, kpi in enumerate(KPI_DEFS):
                            kpi_id = kpi[0]
                            b_val = round(float(b_cband_map[(c_name, b_name)][idx]), 2) if (c_name, b_name) in b_cband_map and b_cband_map[(c_name, b_name)][idx] is not None else None
                            a_val = round(float(a_cband_map[(c_name, b_name)][idx]), 2) if (c_name, b_name) in a_cband_map and a_cband_map[(c_name, b_name)][idx] is not None else None
                            delta = round(a_val - b_val, 2) if (b_val is not None and a_val is not None) else None
                            delta_pct = round((delta / abs(b_val)) * 100, 1) if (delta is not None and b_val) else None
                            cluster_band_compare[c_name][b_name][kpi_id] = {"before": b_val, "after": a_val, "delta": delta, "delta_pct": delta_pct}

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
            import traceback; traceback.print_exc()
            flash(f"Error executing dashboard query: {str(e)}", "danger")

    # Fetch User's Custom Charts
    user_charts = []
    username = session.get("username", "User")
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor(cursor_factory=psycopg2.extras.DictCursor)) as cur:
                cur.execute("SELECT id, dashboard_name, chart_config FROM user_custom_charts WHERE username = %s AND dashboard_name LIKE '2G%%' ORDER BY dashboard_name", [username])
                user_charts = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("Error fetching custom charts: %s", e)

    return _no_cache(make_response(render_template(
        "dashboard_2g.html",
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

        daily_trend_labels=daily_trend_labels,
        daily_trend_chart_data=dict(daily_trend_chart_data),
        daily_site_trend_chart_data=dict(daily_site_trend_chart_data),
        daily_band_trend_chart_data=dict(daily_band_trend_chart_data),

        hourly_trend_labels=hourly_trend_labels,
        hourly_trend_chart_data=dict(hourly_trend_chart_data),
        hourly_site_trend_chart_data=dict(hourly_site_trend_chart_data),
        hourly_band_trend_chart_data=dict(hourly_band_trend_chart_data),
        
        cluster_compare=cluster_compare,
        cluster_band_compare=dict(cluster_band_compare),
        daily_cluster_band_trend_chart_data=dict(daily_cluster_band_trend_chart_data),
        hourly_cluster_band_trend_chart_data=dict(hourly_cluster_band_trend_chart_data),
        is_cluster_mode=is_cluster_mode,
        cluster_list=cluster_list,
        cluster_mapping_json=json.dumps(cluster_mapping_norm) if is_cluster_mode else "",
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

@dashboard_2g.route("/api/dashboard_2g/save_chart", methods=["POST"])
@login_required
def save_custom_chart():
    username = session.get("username", "User")
    data = request.get_json()
    dashboard_name = data.get("dashboard_name", "").strip()
    if dashboard_name and not dashboard_name.upper().startswith("2G"):
        dashboard_name = f"2G - {dashboard_name}"
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

@dashboard_2g.route("/api/dashboard_2g/delete_chart", methods=["POST"])
@login_required
def delete_custom_chart():
    username = session.get("username", "User")
    data = request.get_json()
    dashboard_name = data.get("dashboard_name", "").strip()
    if dashboard_name and not dashboard_name.upper().startswith("2G"):
        dashboard_name = f"2G - {dashboard_name}"
    
    if not dashboard_name:
        return json_response({"error": "Missing dashboard name"}, 400)
        
    try:
        with db_query() as (conn, cur):
            cur.execute("DELETE FROM user_custom_charts WHERE username = %s AND dashboard_name = %s", [username, dashboard_name])
            conn.commit()
            return json_response({"success": True, "message": "Dashboard deleted successfully"})
    except Exception as e:
        return json_response({"error": str(e)}, 500)

@dashboard_2g.route("/api/filter_list_2g", methods=["GET"])
@login_required
def get_filter_list_2g():
    ftype = request.args.get("filter_type", "siteid")
    try:
        if ftype == "city":
            items, _ = get_city_list_2g()
        elif ftype == "site_cell":
            items, _ = get_site_cell_list_2g()
        elif ftype == "bsc":
            items, _ = get_bsc_list_2g()
        else:
            items, _ = get_site_list_2g()
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
