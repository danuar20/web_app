"""5G Monitoring Routes — /kpi_5g_monitoring"""
from flask import Blueprint, render_template, request, session, make_response, flash, jsonify
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, _no_cache, db_query
from datetime import datetime, timedelta
import psycopg2
import psycopg2.errors

kpi5g_monitoring = Blueprint("kpi5g_monitoring", __name__)

# ── KPI Definitions ─────────────────────────────────────────────────────────────
# (chart_id, label, unit, y_min, y_max, sql_expr, is_lower_better)
ALL_KPI_DEFS = [
    ("payloadChart", "Payload", "GB", None, None, 'ROUND((SUM("5g_payload_mb") / 1024.0)::numeric, 3)', False),
    ("dlPayloadChart", "DL Payload", "GB", None, None, 'ROUND((SUM(payload_dl_mbyte_xhj) / 1024.0)::numeric, 3)', False),
    ("ulPayloadChart", "UL Payload", "GB", None, None, 'ROUND((SUM(payload_ul_mbyte_xhj) / 1024.0)::numeric, 3)', False),
    ("availChart", "Availability", "%", None, None, 'CASE WHEN SUM(denum_availability_xhj) > 0 THEN ROUND((SUM(num_availability_xhj) / SUM(denum_availability_xhj) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("rrcChart", "Max RRC User", "Users", None, None, 'SUM(max_rrc_user_number_xhj)', False),
    ("activeUserChart", "NR Active User", "Users", None, None, 'SUM(nr_active_user_number)', False),
    ("accessibilityChart", "NR Accessibility", "%", None, None, 'CASE WHEN SUM(number_of_sn_add_requests) > 0 THEN ROUND((SUM(num_sn_setup_success_rate_xhj) / SUM(number_of_sn_add_requests) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("retainabilityChart", "NR Retainability", "%", None, None, 'CASE WHEN SUM(denum_nr_retainability_xhj) > 0 THEN ROUND((100.0 - (SUM(num_nr_retainability_xhj) / SUM(denum_nr_retainability_xhj) * 100.0))::numeric, 2) ELSE NULL END', False),
    ("mobilityChart", "NR Mobility SR", "%", None, None, 'CASE WHEN SUM(nr_mobility_success_rate_denum) > 0 THEN ROUND((SUM(nr_mobility_success_rate_num) / SUM(nr_mobility_success_rate_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("dlPrbChart", "DL PRB", "%", None, None, 'CASE WHEN SUM(denum_prb_utilization_dl_xhj) > 0 THEN ROUND((SUM(num_prb_utilization_dl_xhj) / SUM(denum_prb_utilization_dl_xhj) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("ulPrbChart", "UL PRB", "%", None, None, 'CASE WHEN SUM(denum_prb_utilization_ul_xhj) > 0 THEN ROUND((SUM(num_prb_utilization_ul_xhj) / SUM(denum_prb_utilization_ul_xhj) * 100.0)::numeric, 2) ELSE NULL END', False),
    ("cellDlThpChart", "Cell DL Thp", "Mbps", None, None, 'ROUND((AVG(cell_throughput_dl_xhj))::numeric, 2)', False),
    ("cellUlThpChart", "Cell UL Thp", "Mbps", None, None, 'ROUND((AVG(cell_throughput_ul_xhj) )::numeric, 2)', False),
    ("dlThpChart", "User DL Thp", "Mbps", None, None, 'CASE WHEN SUM(denum_user_throughput_dl_xhj) > 0 THEN ROUND((SUM(num_user_throughput_dl_xhj) / SUM(denum_user_throughput_dl_xhj) )::numeric, 2) ELSE NULL END', False),
    ("ulThpChart", "User UL Thp", "Mbps", None, None, 'CASE WHEN SUM(denum_user_throughput_ul_xhj) > 0 THEN ROUND((SUM(num_user_throughput_ul_xhj) / SUM(denum_user_throughput_ul_xhj) )::numeric, 2) ELSE NULL END', False),
    ("seChart", "SE", "", None, None, 'CASE WHEN SUM(spectrum_eff_bps_lw_denum) > 0 THEN ROUND((SUM(spectrum_eff_bps_lw_num) / SUM(spectrum_eff_bps_lw_denum))::numeric, 4) ELSE NULL END', False),
    ("cqiChart", "CQI", "", None, None, 'CASE WHEN SUM(denum_average_cqi_xhj) > 0 THEN ROUND((SUM(num_average_cqi_xhj) / SUM(denum_average_cqi_xhj))::numeric, 2) ELSE NULL END', False),
    ("ulIntChart", "UL Interference", "dBm", None, None, 'ROUND(AVG(avg_uplink_interference_xhj)::numeric, 2)', True),
    ("plChart", "Packet Loss", "%", None, None, 'CASE WHEN SUM(denum_packet_loss_xhj) > 0 THEN ROUND((SUM(num_packet_loss_xhj) / SUM(denum_packet_loss_xhj) * 100.0)::numeric, 2) ELSE NULL END', True),
    ("latDlChart", "Latency DL", "ms", None, None, 'CASE WHEN SUM(denum_latency_dl_xhj) > 0 THEN ROUND((SUM(num_latency_dl_xhj) / SUM(denum_latency_dl_xhj))::numeric, 2) ELSE NULL END', True),
    ("latUlChart", "Latency UL", "ms", None, None, 'CASE WHEN SUM(denum_latency_ul_xhj) > 0 THEN ROUND((SUM(num_latency_ul_xhj) / SUM(denum_latency_ul_xhj))::numeric, 2) ELSE NULL END', True),
]

DEFAULT_KPIS = [k[0] for k in ALL_KPI_DEFS]

# ── Main Page Route ─────────────────────────────────────────────────────────────
@kpi5g_monitoring.route("/kpi_5g_monitoring")
@login_required
def kpi_5g_monitoring():
    today = datetime.now().date()
    default_to = today.strftime("%Y-%m-%d")
    default_fr = (today - timedelta(days=29)).strftime("%Y-%m-%d")

    from_date  = request.args.get("from_date", "")
    to_date    = request.args.get("to_date",   "")
    submitted  = request.args.get("submitted", "0") == "1"
    sel_kpis   = request.args.getlist("kpi")

    if not sel_kpis:
        sel_kpis = [k[0] for k in ALL_KPI_DEFS]

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

    if submitted and from_date and to_date and kpi_defs:
        conn = None
        cur  = None
        try:
            with db_query() as (conn, cur):
                cur.execute("SET work_mem = '1GB'")
                cur.execute("SET jit = off")

                try:
                    cur.execute('SELECT MAX(datehour::date) FROM "5g_kpi_zte"')
                    raw = cur.fetchone()
                    last_update = raw[0].strftime('%Y-%m-%d') if raw and raw[0] else None
                except Exception:
                    last_update = None

                kpi_selects = ",\n            ".join([f"{k[5]} AS {k[0]}" for k in kpi_defs])
            
                sql = f"""
                
                    SELECT
                        datehour::date AS day,
                        GROUPING(nsa) as g_nsa,
                        GROUPING(city) as g_city,
                        GROUPING(subnetwork_name) as g_subnet,
                        1 as g_site,
                        COALESCE(nsa, 'Unknown') as nsa,
                        COALESCE(city, 'Unknown') as city,
                        COALESCE(subnetwork_name, 'Unknown') as subnet,
                        'Unknown' as siteid,

                        {kpi_selects}
                    FROM "5g_kpi_zte"
                    WHERE datehour::date >= %s::date AND datehour::date <= %s::date
                    GROUP BY GROUPING SETS (
                        (datehour::date),
                        (datehour::date, nsa),
                        (datehour::date, nsa, city),
                        (datehour::date, subnetwork_name),
                        (datehour::date, subnetwork_name, city)
                    )
                """
            
                cur.execute("SET work_mem = '1GB'")
                cur.execute(sql, [from_date, to_date])
                rows = cur.fetchall()
                cur.execute("RESET work_mem")
            
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

                cur.execute("""
                    SELECT city, subnetwork_name, siteid 
                    FROM "5g_kpi_zte" 
                    WHERE datehour::date >= %s::date AND datehour::date <= %s::date
                      AND siteid IS NOT NULL AND siteid != '' AND siteid != 'Unknown'
                    GROUP BY city, subnetwork_name, siteid
                """, [from_date, to_date])
            
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
        "kpi_5g_monitoring.html",
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

@kpi5g_monitoring.route("/api/kpi_5g_monitoring/hourly", methods=["POST"])
@login_required
def api_kpi_5g_monitoring_hourly():
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
            cur.execute("SET work_mem = '1GB'")
            cur.execute("SET jit = off")
        
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
            else:
                date_col = "TO_CHAR(datehour::date, 'YYYY-MM-DD')"
                group_by = "datehour::date, dt_label, dimension"
                order_by = "datehour::date"

            sql = f"""
                SELECT 
                    {date_col} as dt_label,
                    {group_col} as dimension,
                    {kpi_selects}
                FROM "5g_kpi_zte"
                WHERE datehour::date >= %s::date AND datehour::date <= %s::date
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

@kpi5g_monitoring.route('/api/kpi_5g_monitoring/site_cluster', methods=['POST'])
@login_required
def api_kpi_5g_monitoring_site_cluster():
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
            else:
                date_col = "TO_CHAR(datehour::date, 'YYYY-MM-DD')"
                group_by = "datehour::date, dt_label"
                order_by = "datehour::date"
            
            sql = f"""
                SELECT 
                    {date_col} as dt_label,
                    {kpi_selects}
                FROM "5g_kpi_zte"
                WHERE datehour::date >= %s::date AND datehour::date <= %s::date
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

@kpi5g_monitoring.route('/api/kpi_5g_monitoring/sector_data', methods=['POST'])
@login_required
def api_kpi_5g_monitoring_sector_data():
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
        
            kpi_selects = ",\n            ".join([f"{k[5]} AS {k[0]}" for k in kpi_defs])
        
            sql_hourly = f'''
                SELECT 
                    TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI') as dt_label,
                    siteid,
                    CASE
                        WHEN LENGTH(cellid::text) > 2 AND RIGHT(cellid::text, 1) = '5' THEN SUBSTRING(cellid::text FROM 2 FOR 1)
                        WHEN LENGTH(cellid::text) > 2 THEN LEFT(cellid::text, 2)
                        ELSE LEFT(cellid::text, 1)
                    END AS sector,
                    CASE RIGHT(cellid::text, 1)
                        WHEN '1' THEN 'NR1800'
                        WHEN '2' THEN 'NR900'
                        WHEN '3' THEN 'NR2100'
                        WHEN '4' THEN 'NR2300_1'
                        WHEN '5' THEN 'NR2300_2'
                        WHEN '6' THEN 'NR2300_3'
                        WHEN '7' THEN 'NR700'
                        ELSE 'Unknown'
                    END AS band,
                    cellid::text AS tech,
                    {kpi_selects}
                FROM "5g_kpi_zte"
                WHERE datehour >= %s::date AND datehour < (%s::date + interval '1 day')
                  AND siteid = ANY(%s)
                GROUP BY datehour, siteid, cellid, sector, band, tech
                ORDER BY datehour
            '''
            cur.execute(sql_hourly, [from_date, to_date, sites])
            rows_hourly = cur.fetchall()
        
            sql_daily = f'''
                SELECT 
                    TO_CHAR(datehour::date, 'YYYY-MM-DD') as dt_label,
                    siteid,
                    CASE
                        WHEN LENGTH(cellid::text) > 2 AND RIGHT(cellid::text, 1) = '5' THEN SUBSTRING(cellid::text FROM 2 FOR 1)
                        WHEN LENGTH(cellid::text) > 2 THEN LEFT(cellid::text, 2)
                        ELSE LEFT(cellid::text, 1)
                    END AS sector,
                    CASE RIGHT(cellid::text, 1)
                        WHEN '1' THEN 'NR1800'
                        WHEN '2' THEN 'NR900'
                        WHEN '3' THEN 'NR2100'
                        WHEN '4' THEN 'NR2300_1'
                        WHEN '5' THEN 'NR2300_2'
                        WHEN '6' THEN 'NR2300_3'
                        WHEN '7' THEN 'NR700'
                        ELSE 'Unknown'
                    END AS band,
                    cellid::text AS tech,
                    {kpi_selects}
                FROM "5g_kpi_zte"
                WHERE datehour >= %s::date AND datehour < (%s::date + interval '1 day')
                  AND siteid = ANY(%s)
                GROUP BY datehour::date, siteid, cellid, sector, band, tech
                ORDER BY datehour::date
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
