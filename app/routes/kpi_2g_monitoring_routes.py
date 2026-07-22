"""2G Monitoring Routes — /kpi_2g_monitoring (Daily aggregated, 5 dimension tabs via GROUPING SETS)"""
from flask import Blueprint, render_template, request, session, make_response, flash, jsonify
from app import cache
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, _no_cache, db_query
from datetime import datetime, timedelta
import psycopg2
import psycopg2.errors

kpi2g_monitoring = Blueprint("kpi2g_monitoring", __name__)

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
@kpi2g_monitoring.route("/kpi_2g_monitoring")
@login_required
def kpi_2g_monitoring():
    # Default date range: last 30 days
    today      = datetime.now().date()
    default_to = today.strftime("%Y-%m-%d")
    default_fr = (today - timedelta(days=29)).strftime("%Y-%m-%d")

    from_date  = request.args.get("from_date", "")
    to_date    = request.args.get("to_date",   "")
    submitted  = request.args.get("submitted", "0") == "1"
    sel_kpis   = request.args.getlist("kpi")

    # Populate KPI selection (default = DEFAULT_KPIS on initial load)
    if not sel_kpis and not submitted:
        sel_kpis = DEFAULT_KPIS
    elif not sel_kpis and submitted:
        sel_kpis = [] # User explicitly checked none

    kpi_defs   = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]

    # Result containers
    chart_labels      = []
    regional_data     = {}
    nop_data          = {}
    city_data         = {}
    bsc_data          = {}
    site_data         = {}
    
    # Relationships mapping
    nsa_city_map      = {} # { nsa: [city1, city2] }
    city_site_map     = {} # { city: [site1, site2] }
    bsc_site_map      = {} # { bsc: [site1, site2] }
    
    # For unique dimensions
    nop_dims_set      = set()
    city_dims_set     = set()
    bsc_dims_set      = set()
    site_dims_set     = set()
    
    last_update       = None
    query_done        = False

    cache_key = None
    if submitted and from_date and to_date and kpi_defs:
        kpi_names = "-".join(sorted([k[0] for k in kpi_defs]))
        cache_key = f"2g_mon_data_{from_date}_{to_date}_{kpi_names}"

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
                cur.execute("SET work_mem = '1GB'")
                cur.execute("SET jit = off")

                # Last update — also used to determine the live branch boundary
                try:
                    cur.execute('SELECT MAX(kpi_date) FROM "2g_kpi_zte_daily"')
                    raw = cur.fetchone()
                    max_daily_date = raw[0] if raw and raw[0] else None
                    last_update = max_daily_date.strftime('%Y-%m-%d') if max_daily_date else None
                except Exception:
                    max_daily_date = None
                    last_update = None

                kpi_selects = ",\n            ".join([f"{k[5]} AS {k[0]}" for k in kpi_defs])

                # All raw numerator/denominator columns used by kpi_selects expressions
                DAILY_COLS = """kpi_date AS date, nsa, city, me_name, siteid,
                    total_payload, tch_traffic, sdcch_traffic, "Offic_full_traffic", "Offic_half_traffic",
                    tch_avail_num, tch_avail_denum, cssr_num, cssr_denum,
                    "2g_ccsr_num", "2g_ccsr_denum",
                    hosr_num, hosr_denum, sdsr_num, sdsr_denum,
                    tbf_dl_est_num, tbf_dl_est_denum, tbf_comp_num, tbf_comp_denum,
                    tch_drop_num, tch_drop_denum, tch_block_num, tch_block_denum,
                    sdcch_block_num, sdcch_block_denum, fastreturn_to_lte,
                    icm_band35_num, icm_band35_denum,
                    num_icm_interference_ono, denum_icm_interference_ono,
                    mos_dl, mos_ul, sd_to_tch, cst,
                    pdch_alocation_failure_rate_num, pdch_alocation_failure_rate_denum,
                    num_dl_qual_0_5, denum_dl_qual_0_5, num_ul_qual_0_5, denum_ul_qual,
                    gprs_dl_thp, edge_dl_thp, gprs_payload, edge_payload"""

                RAW_COLS = """date_trunc('day', date)::date AS date, nsa, city, me_name, siteid,
                    SUM(total_payload), SUM(tch_traffic), SUM(sdcch_traffic),
                    SUM("Offic_full_traffic"), SUM("Offic_half_traffic"),
                    SUM(tch_avail_num), SUM(tch_avail_denum), SUM(cssr_num), SUM(cssr_denum),
                    SUM("2g_ccsr_num"), SUM("2g_ccsr_denum"),
                    SUM(hosr_num), SUM(hosr_denum), SUM(sdsr_num), SUM(sdsr_denum),
                    SUM(tbf_dl_est_num), SUM(tbf_dl_est_denum), SUM(tbf_comp_num), SUM(tbf_comp_denum),
                    SUM(tch_drop_num), SUM(tch_drop_denum), SUM(tch_block_num), SUM(tch_block_denum),
                    SUM(sdcch_block_num), SUM(sdcch_block_denum), SUM(fastreturn_to_lte),
                    SUM(icm_band35_num), SUM(icm_band35_denum),
                    SUM(num_icm_interference_ono), SUM(denum_icm_interference_ono),
                    AVG(mos_dl), AVG(mos_ul), AVG(sd_to_tch), AVG(cst),
                    SUM(pdch_alocation_failure_rate_num), SUM(pdch_alocation_failure_rate_denum),
                    SUM(num_dl_qual_0_5), SUM(denum_dl_qual_0_5), SUM(num_ul_qual_0_5), SUM(denum_ul_qual),
                    AVG(gprs_dl_thp), AVG(edge_dl_thp), SUM(gprs_payload), SUM(edge_payload)"""

                # Live branch boundary: cover dates in the raw table NOT YET aggregated into daily.
                # e.g. if daily table ends at Jun 30, live branch covers Jul 1 → to_date.
                from_dt = datetime.strptime(from_date, '%Y-%m-%d').date()
                to_dt   = datetime.strptime(to_date,   '%Y-%m-%d').date()

                if max_daily_date is None:
                    live_lower = from_dt          # daily table empty — cover full range from raw
                else:
                    live_lower = max_daily_date + timedelta(days=1)   # day after last daily entry

                include_live = live_lower <= to_dt  # only if gap exists within requested range

                live_union_sql = ""
                sql_params = [from_date, to_date]

                if include_live:
                    live_upper     = to_dt + timedelta(days=1)   # exclusive: includes all hours of to_date
                    live_lower_str = live_lower.strftime('%Y-%m-%d')
                    live_upper_str = live_upper.strftime('%Y-%m-%d')
                    live_union_sql = f"""
                    UNION ALL
                    -- Live data for dates after daily table cutoff: explicit bounds prevent full scan
                    SELECT {RAW_COLS}
                    FROM "2g_kpi_zte"
                    WHERE date >= %s::date::timestamp
                      AND date <  %s::date::timestamp
                      AND nsa IS NOT NULL AND city IS NOT NULL
                      AND me_name IS NOT NULL AND siteid IS NOT NULL
                    GROUP BY date_trunc('day', date), nsa, city, me_name, siteid"""
                    sql_params += [live_lower_str, live_upper_str]

                sql = f"""
                    SELECT
                        date AS day,
                        GROUPING(nsa) as g_nsa,
                        GROUPING(city) as g_city,
                        GROUPING(me_name) as g_bsc,
                        1 as g_site,
                        COALESCE(nsa, 'Unknown') as nsa,
                        COALESCE(city, 'Unknown') as city,
                        COALESCE(me_name, 'Unknown') as me_name,
                        'Unknown' as siteid,
                        {kpi_selects}
                    FROM (
                        -- Historical: query daily pre-aggregated table directly (fast index scan)
                        SELECT {DAILY_COLS}
                        FROM "2g_kpi_zte_daily"
                        WHERE kpi_date >= %s::date AND kpi_date <= %s::date
                        {live_union_sql}
                    ) daily_base
                    GROUP BY GROUPING SETS (
                        (date),
                        (date, nsa),
                        (date, nsa, city),
                        (date, me_name)
                    )
                """

                cur.execute("SET work_mem = '2GB'")
                cur.execute("SET jit = off")           # JIT adds overhead on I/O-bound queries
                cur.execute(sql, sql_params)
                rows = cur.fetchall()

                cur.execute("RESET work_mem")
                cur.execute("RESET jit")
            
                days_set = set()
            
                # Temporary storage for data: { kpi_id: { dim_val: { day: val } } }
                temp_regional = {k[0]: {} for k in kpi_defs}
                temp_nop      = {k[0]: {} for k in kpi_defs}
                temp_city     = {k[0]: {} for k in kpi_defs}
                temp_bsc      = {k[0]: {} for k in kpi_defs}
                temp_site     = {k[0]: {} for k in kpi_defs}
            
                for row in rows:
                    day_str = row[0].strftime("%Y-%m-%d") if row[0] else ""
                    days_set.add(day_str)
                
                    g_nsa, g_city, g_bsc, g_site = row[1], row[2], row[3], row[4]
                    nsa, city, me_name, siteid = row[5], row[6], row[7], row[8]
                
                    # Extract KPIs
                    kpi_vals = {}
                    for idx, k in enumerate(kpi_defs):
                        v = row[9 + idx]
                        if k[0] == 'payloadChart' and g_site == 0 and v is not None:
                            v = float(v) * 1024
                        kpi_vals[k[0]] = round(float(v), 2) if v is not None else None

                    # Regional (g_nsa=1, g_city=1, g_bsc=1, g_site=1)
                    if g_nsa == 1 and g_city == 1 and g_bsc == 1 and g_site == 1:
                        dim_val = "Regional"
                        for k in kpi_defs:
                            if dim_val not in temp_regional[k[0]]:
                                temp_regional[k[0]][dim_val] = {}
                            temp_regional[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                        
                    # NOP (g_nsa=0, g_city=1, g_bsc=1, g_site=1)
                    elif g_nsa == 0 and g_city == 1 and g_bsc == 1 and g_site == 1:
                        dim_val = nsa
                        nop_dims_set.add(dim_val)
                        for k in kpi_defs:
                            if dim_val not in temp_nop[k[0]]:
                                temp_nop[k[0]][dim_val] = {}
                            temp_nop[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                        
                    # City (g_nsa=0, g_city=0, g_bsc=1, g_site=1)
                    elif g_nsa == 0 and g_city == 0 and g_bsc == 1 and g_site == 1:
                        dim_val = city
                        city_dims_set.add(dim_val)
                        if nsa not in nsa_city_map: nsa_city_map[nsa] = set()
                        nsa_city_map[nsa].add(city)
                        for k in kpi_defs:
                            if dim_val not in temp_city[k[0]]:
                                temp_city[k[0]][dim_val] = {}
                            temp_city[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                        
                    # BSC (g_nsa=1, g_city=1, g_bsc=0)
                    elif g_nsa == 1 and g_city == 1 and g_bsc == 0:
                        dim_val = me_name
                        bsc_dims_set.add(dim_val)
                        for k in kpi_defs:
                            if dim_val not in temp_bsc[k[0]]:
                                temp_bsc[k[0]][dim_val] = {}
                            temp_bsc[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                        
                # Format data to align with chart labels correctly
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
                bsc_data      = align_data(temp_bsc, sorted(bsc_dims_set))

                # Fetch site topology for cascading dropdowns using the latest available date in the selected range
                # This ensures dropdowns are populated even if 'to_date' itself has no data yet.
                cur.execute('SELECT MAX(kpi_date) FROM "2g_kpi_zte_daily" WHERE kpi_date >= %s AND kpi_date <= %s', [from_date, to_date])
                max_date = cur.fetchone()[0]
            
                if max_date:
                    cur.execute("""
                        SELECT city, me_name, siteid 
                        FROM "2g_kpi_zte_daily"
                        WHERE kpi_date = %s
                        GROUP BY city, me_name, siteid
                    """, [max_date])
                
                    for r in cur.fetchall():
                        c, b, s = r[0], r[1], r[2]
                        if c not in city_site_map: city_site_map[c] = set()
                        city_site_map[c].add(s)
                        if b not in bsc_site_map: bsc_site_map[b] = set()
                        bsc_site_map[b].add(s)

                query_done = True
        except psycopg2.OperationalError:
            flash("Database connection failed. Please try again.", "warning")
        except psycopg2.errors.QueryCanceled:
            flash("Query timed out. Try a shorter date range or fewer KPIs.", "warning")
        except psycopg2.errors.ConnectionDoesNotExist:
            flash("Database server unreachable. Please try again later.", "warning")
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")

    # Serialize mappings to lists so they are JSON-friendly
    nsa_city_map_list = {k: sorted(v) for k, v in nsa_city_map.items()}
    city_site_map_list = {k: sorted(v) for k, v in city_site_map.items()}
    bsc_site_map_list = {k: sorted(v) for k, v in bsc_site_map.items()}

    return _no_cache(make_response(render_template(
        "kpi_2g_monitoring.html",
        username=session["username"],
        from_date=from_date or default_fr,
        to_date=to_date or default_to,
        default_fr=default_fr,
        default_to=default_to,
        sel_kpis=sel_kpis,
        all_kpis=ALL_KPI_DEFS,
        kpi_defs=[(k[0], k[1], k[2], k[3], k[4], k[6]) for k in kpi_defs],
        # per-tab data
        chart_labels=chart_labels,
        regional_dims=["Regional"],
        regional_data=regional_data,
        nop_dims=sorted(nop_dims_set),
        nop_data=nop_data,
        city_dims=sorted(city_dims_set),
        city_data=city_data,
        bsc_dims=sorted(bsc_dims_set),
        bsc_data=bsc_data,
        site_dims=[],
        site_data={},
        # cascading maps
        nsa_city_map=nsa_city_map_list,
        city_site_map=city_site_map_list,
        bsc_site_map=bsc_site_map_list,
        last_update=last_update,
        query_done=query_done,
    )))

@kpi2g_monitoring.route("/api/kpi_2g/hourly", methods=["POST"])
@login_required
def api_kpi_2g_hourly():
    data = request.get_json()
    from_date = data.get("from_date")
    to_date = data.get("to_date")
    tab = data.get("tab") # regional, nop, city, bsc, site
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
            cur.execute("SET work_mem = '1GB'")
            cur.execute("SET jit = off")
        
            kpi_selects = ",\n            ".join([f"{k[5]} AS {k[0]}" for k in kpi_defs])
        
            # Determine GROUP BY clause based on tab
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
            elif tab == "bsc":
                group_col = "me_name"
                where_clause = "AND me_name = ANY(%s)"
                params = [from_date, to_date, entities]
            elif tab == "site":
                group_col = "siteid"
                where_clause = "AND siteid = ANY(%s)"
                params = [from_date, to_date, entities]
            elif tab == "sector":
                group_col = "site"
                where_clause = "AND site = ANY(%s)"
                params = [from_date, to_date, entities]
            else:
                return jsonify({"error": "Invalid tab"}), 400
            
            if granularity == 'hourly':
                date_col = "TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI')"
                group_by = "datehour, dt_label, dimension"
                order_by = "datehour"
                table_name = '"2g_kpi_zte"'
                date_filter_col = 'date'
            else:
                date_col = "TO_CHAR(kpi_date, 'YYYY-MM-DD')"
                group_by = "kpi_date, dt_label, dimension"
                order_by = "kpi_date"
                table_name = '"2g_kpi_zte_daily"'
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
        
            # Format response
            # { dimension_name: { kpi_id: [vals...] }, "labels": [labels...] }
            labels_set = set()
            raw_map = {} # dt_label -> { dimension -> { kpi -> val } }
        
            for r in rows:
                dt_label = r[0]
                dim = r[1]
                labels_set.add(dt_label)
            
                if dt_label not in raw_map: raw_map[dt_label] = {}
                if dim not in raw_map[dt_label]: raw_map[dt_label][dim] = {}
            
                for idx, k in enumerate(kpi_defs):
                    val = r[2 + idx]
                    if tab in ['site', 'sector'] and k[0] in ['payloadChart', 'gprsPayloadChart', 'edgePayloadChart'] and val is not None:
                        val = float(val) * 1024
                    raw_map[dt_label][dim][k[0]] = round(float(val), 2) if val is not None else None
                
            labels = sorted(list(labels_set))
        
            # Re-pivot to match TAB_DATA structure: { kpi_id: { dimension: [vals...] } }
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
@kpi2g_monitoring.route('/api/kpi_2g/site_cluster', methods=['POST'])
@login_required
def api_kpi_2g_site_cluster():
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
            cur.execute("SET work_mem = '1GB'")
            cur.execute("SET jit = off")
        
            kpi_selects = ",\n            ".join([f"{k[5]} AS {k[0]}" for k in kpi_defs])
        
            if granularity == 'hourly':
                date_col = "TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI')"
                group_by = "datehour, dt_label"
                order_by = "datehour"
                table_name = '"2g_kpi_zte"'
                date_filter_col = 'date'
            else:
                date_col = "TO_CHAR(kpi_date, 'YYYY-MM-DD')"
                group_by = "kpi_date, dt_label"
                order_by = "kpi_date"
                table_name = '"2g_kpi_zte_daily"'
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
            raw_map = {} # dt_label -> { kpi -> val }
        
            for r in rows:
                dt_label = r[0]
                labels_set.add(dt_label)
                raw_map[dt_label] = {}
            
                for idx, k in enumerate(kpi_defs):
                    val = r[1 + idx]
                    if k[0] in ['payloadChart', 'gprsPayloadChart', 'edgePayloadChart'] and val is not None:
                        val = float(val) * 1024
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


@kpi2g_monitoring.route('/api/kpi_2g/sector_data', methods=['POST'])
@login_required
def api_kpi_2g_sector_data():
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
            cur.execute("SET work_mem = '1GB'")
            cur.execute("SET jit = off")
        
            # We need the formulas from the Hourly Sector logic.
            # But in kpi_2g_monitoring ALL_KPI_DEFS has sql_expr at index 5.
            # Let's check kpi_selects... it should be the same.
            kpi_selects = ",\n            ".join([f"{k[5]} AS {k[0]}" for k in kpi_defs])
        
            # 1. Fetch Hourly
            sql_hourly = f'''
                SELECT 
                    TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI') as dt_label,
                    siteid,
                    RIGHT(bts_name::text, 1) AS sector,
                    "Tech" AS tech,
                    {kpi_selects}
                FROM "2g_kpi_zte"
                WHERE datehour >= %s::date AND datehour < (%s::date + interval '1 day')
                  AND siteid = ANY(%s)
                GROUP BY datehour, siteid, bts_name, sector, "Tech"
                ORDER BY datehour
            '''
            cur.execute(sql_hourly, [from_date, to_date, sites])
            rows_hourly = cur.fetchall()
        
            # 2. Fetch Daily
            sql_daily = f'''
                SELECT 
                    TO_CHAR(datehour::date, 'YYYY-MM-DD') as dt_label,
                    siteid,
                    RIGHT(bts_name::text, 1) AS sector,
                    "Tech" AS tech,
                    {kpi_selects}
                FROM "2g_kpi_zte"
                WHERE datehour >= %s::date AND datehour < (%s::date + interval '1 day')
                  AND siteid = ANY(%s)
                GROUP BY datehour::date, siteid, bts_name, sector, "Tech"
                ORDER BY datehour::date
            '''
            cur.execute(sql_daily, [from_date, to_date, sites])
            rows_daily = cur.fetchall()
        
            def process_rows(rows):
                labels_set = set()
                raw_map = {} # dt_label -> { legend_name -> { kpi -> val } }
            
                for r in rows:
                    dt_label = r[0]
                    siteid = r[1]
                    sector = r[2]
                    tech = r[3]
                
                    tech_str = f"-{tech}" if tech else ""
                    legend_name = f"{siteid} S{sector}{tech_str}"
                
                    labels_set.add(dt_label)
                    if dt_label not in raw_map: raw_map[dt_label] = {}
                    if legend_name not in raw_map[dt_label]: raw_map[dt_label][legend_name] = {}
                
                    for idx, k in enumerate(kpi_defs):
                        val = r[4 + idx]
                        if k[0] in ['payloadChart', 'gprsPayloadChart', 'edgePayloadChart'] and val is not None:
                            val = float(val) * 1024
                        raw_map[dt_label][legend_name][k[0]] = round(float(val), 2) if val is not None else None
            
                labels = sorted(list(labels_set))
            
                # Extract all legends found
                all_legends = set()
                for dt in raw_map:
                    for leg in raw_map[dt]:
                        all_legends.add(leg)
                all_legends = sorted(list(all_legends))
            
                # Format: { kpi_id: { legend_name: [vals...] } }
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
