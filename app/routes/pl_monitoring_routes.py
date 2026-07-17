"""4G Monitoring Routes — /pl_monitoring"""
from flask import Blueprint, render_template, request, session, make_response, flash, jsonify
from app import cache
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, _no_cache, db_query
from datetime import datetime, timedelta
import psycopg2
import psycopg2.errors

pl_monitoring = Blueprint("pl_monitoring", __name__)

def make_post_cache_key(*args, **kwargs):
    import hashlib
    import json
    data = request.get_json() or {}
    key = f"{request.path}:{json.dumps(data, sort_keys=True)}"
    return "post_cache_" + hashlib.md5(key.encode('utf-8')).hexdigest()



# ── KPI Definitions ─────────────────────────────────────────────────────────────
# (chart_id, label, unit, y_min, y_max, sql_expr, is_lower_better)
ALL_KPI_DEFS = [
    ("packetLossChart", "Packet Loss", "%", 0, None, 'CASE WHEN SUM(packet_loss_denum) > 0 THEN ROUND((SUM(packet_loss_num) / SUM(packet_loss_denum) * 100.0)::numeric, 4) ELSE 0 END', True),
    ("latencyChart", "Latency", "ms", 0, None, 'ROUND(AVG(latency)::numeric, 2)', True),
    ("jitterChart", "Jitter", "ms", 0, None, 'ROUND(AVG(mean_delay_jitter)::numeric, 2)', True),
    ("txPacketsChart", "Tx Packets", "", 0, None, 'SUM(tx_packets)', False),
    ("rxPacketsChart", "Rx Packets", "", 0, None, 'SUM(rx_packets)', False)
]

DEFAULT_KPIS = [
    "packetLossChart", "latencyChart", "jitterChart", "txPacketsChart", "rxPacketsChart"
]

# ── Main Page Route ─────────────────────────────────────────────────────────────
@pl_monitoring.route("/pl_monitoring")
@login_required
def pl_monitoring_main():
    today = datetime.now().date()
    default_to = today.strftime("%Y-%m-%d")
    default_fr = (today - timedelta(days=29)).strftime("%Y-%m-%d")

    from_date  = request.args.get("from_date", "")
    to_date    = request.args.get("to_date",   "")
    submitted  = request.args.get("submitted", "0") == "1"
    sel_kpis   = request.args.getlist("kpi")
    tech = request.args.get('tech', '4G')
    if tech == '2G':
        # Remove Tx/Rx packets for 2G
        sel_kpis = [k for k in sel_kpis if k not in ("txPacketsChart", "rxPacketsChart")]


    if not sel_kpis and not submitted:
        sel_kpis = DEFAULT_KPIS
    elif not sel_kpis and submitted:
        sel_kpis = [] # User explicitly checked none

    kpi_defs = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]

    chart_labels      = set()
    
    all_data = {
        '4G': {'regional': {}, 'nop': {}, 'city': {}, 'cluster': {}},
        '2G': {'regional': {}, 'nop': {}, 'city': {}, 'cluster': {}}
    }
    
    nsa_city_map      = {} 
    city_cluster_map   = {}
    cluster_city_map   = {}
    city_site_map     = {} 
    cluster_site_map   = {}
    
    nop_dims_set      = set()
    city_dims_set     = set()
    cluster_dims_set   = set()
    
    last_update       = None
    query_done        = False

    cache_key = None
    if submitted and from_date and to_date and kpi_defs:
        kpi_names = "-".join(sorted([k[0] for k in kpi_defs]))
        cache_key = f"both_pl_data_{from_date}_{to_date}_{kpi_names}"

    cached_data = cache.get(cache_key) if cache_key else None
    
    if cached_data:
        (all_data, nsa_city_map, city_cluster_map, cluster_city_map, city_site_map, cluster_site_map, 
         nop_dims_set, city_dims_set, cluster_dims_set, chart_labels, last_update, query_done) = cached_data
    elif submitted and from_date and to_date and kpi_defs:
        conn = None
        cur  = None
        try:
            with db_query() as (conn, cur):
                for current_tech in ['4G', '2G']:
                    # Determine which daily table to use based on tech
                    daily_table = f'"{current_tech}_pl_hy_daily"'
    
                    # Check what's the max date in the pre-aggregated daily table
                    cur.execute(f'SELECT MAX(date) FROM {daily_table}')
                    raw = cur.fetchone()
                    max_daily_date = raw[0] if raw and raw[0] else None
                    if max_daily_date and (last_update is None or max_daily_date > datetime.strptime(last_update, '%Y-%m-%d').date()):
                        last_update = max_daily_date.strftime('%Y-%m-%d')
    
                    # Determine gap: dates requested that aren't in the daily table yet
                    to_date_obj   = datetime.strptime(to_date,   '%Y-%m-%d').date()
                    from_date_obj = datetime.strptime(from_date, '%Y-%m-%d').date()
    
                    has_gap   = max_daily_date is not None and max_daily_date < to_date_obj
                    gap_start = (max_daily_date + timedelta(days=1)) if has_gap else None
                    gap_end   = to_date_obj if has_gap else None
                    daily_to  = min(to_date_obj, max_daily_date) if max_daily_date else None
    
                    kpi_selects = ",\n            ".join([f"{k[5]} AS {k[0]}" for k in kpi_defs])
    
                    # ── Build KPI selects for pre-aggregated daily table ──
                    daily_kpi_parts = []
                    for k in kpi_defs:
                        if k[0] == 'packetLossChart':
                            daily_kpi_parts.append(
                                "CASE WHEN SUM(packet_loss_denum) > 0 "
                                "THEN ROUND((SUM(packet_loss_num)::numeric / SUM(packet_loss_denum) * 100.0), 4) "
                                "ELSE 0 END AS packetLossChart"
                            )
                        elif k[0] == 'latencyChart':
                            daily_kpi_parts.append(
                                "CASE WHEN SUM(latency_count) > 0 "
                                "THEN ROUND((SUM(latency_sum) / SUM(latency_count))::numeric, 2) "
                                "ELSE NULL END AS latencyChart"
                            )
                        elif k[0] == 'jitterChart':
                            daily_kpi_parts.append(
                                "CASE WHEN SUM(jitter_count) > 0 "
                                "THEN ROUND((SUM(jitter_sum) / SUM(jitter_count))::numeric, 2) "
                                "ELSE NULL END AS jitterChart"
                            )
                        elif k[0] == 'txPacketsChart':
                            if current_tech == '4G':
                                daily_kpi_parts.append("SUM(tx_packets) AS txPacketsChart")
                            else:
                                daily_kpi_parts.append("0 AS txPacketsChart")
                        elif k[0] == 'rxPacketsChart':
                            if current_tech == '4G':
                                daily_kpi_parts.append("SUM(rx_packets) AS rxPacketsChart")
                            else:
                                daily_kpi_parts.append("0 AS rxPacketsChart")
                    daily_kpi_selects = ",\n            ".join(daily_kpi_parts)
    
                    # ── Query from pre-aggregated daily table ──
                    all_rows = []
    
                    if max_daily_date and from_date_obj <= daily_to:
                        sql_daily = f"""
                        SELECT
                            date as day,
                            GROUPING(nsa) as g_nsa,
                            GROUPING(city) as g_city,
                            GROUPING(cluster) as g_cluster,
                            1 as g_site,
                            COALESCE(nsa, 'Unknown') as nsa,
                            COALESCE(city, 'Unknown') as city,
                            COALESCE(cluster, 'Unknown') as cluster,
                            'Unknown' as siteid,
                            {daily_kpi_selects}
                        FROM {daily_table}
                        WHERE date >= %s::date AND date <= %s::date
                        GROUP BY GROUPING SETS (
                            (date),
                            (date, nsa),
                            (date, nsa, city),
                            (date, cluster),
                            (date, cluster, city)
                        )
                        """
                        cur.execute(sql_daily, [from_date_obj, daily_to])
                        all_rows.extend(cur.fetchall())
    
                    # ── Fallback: use vw_pl_hourly ──
                    if has_gap and gap_start and gap_end:
                        sql_gap = f"""
                        SELECT
                            date as day,
                            GROUPING(nsa) as g_nsa,
                            GROUPING(city) as g_city,
                            GROUPING(cluster) as g_cluster,
                            1 as g_site,
                            COALESCE(nsa, 'Unknown') as nsa,
                            COALESCE(city, 'Unknown') as city,
                            COALESCE(cluster, 'Unknown') as cluster,
                            'Unknown' as siteid,
                            {kpi_selects}
                        FROM "vw_pl_hourly"
                        WHERE tech = %s AND date >= %s::date AND date <= %s::date
                          AND siteid IS NOT NULL
                        GROUP BY GROUPING SETS (
                            (date),
                            (date, nsa),
                            (date, nsa, city),
                            (date, cluster),
                            (date, cluster, city)
                        )
                        """
                        cur.execute(sql_gap, [current_tech, gap_start, gap_end])
                        all_rows.extend(cur.fetchall())
    
                    if not max_daily_date:
                        sql_fallback = f"""
                        SELECT
                            date as day,
                            GROUPING(nsa) as g_nsa,
                            GROUPING(city) as g_city,
                            GROUPING(cluster) as g_cluster,
                            1 as g_site,
                            COALESCE(nsa, 'Unknown') as nsa,
                            COALESCE(city, 'Unknown') as city,
                            COALESCE(cluster, 'Unknown') as cluster,
                            'Unknown' as siteid,
                            {kpi_selects}
                        FROM "vw_pl_daily"
                        WHERE tech = %s AND date >= %s::date AND date <= %s::date
                        GROUP BY GROUPING SETS (
                            (date),
                            (date, nsa),
                            (date, nsa, city),
                            (date, cluster),
                            (date, cluster, city)
                        )
                        """
                        cur.execute(sql_fallback, [current_tech, from_date, to_date])
                        all_rows = cur.fetchall()
                        
                    temp_regional = {k[0]: {} for k in kpi_defs}
                    temp_nop      = {k[0]: {} for k in kpi_defs}
                    temp_city     = {k[0]: {} for k in kpi_defs}
                    temp_cluster  = {k[0]: {} for k in kpi_defs}
                
                    for row in all_rows:
                        day_str = row[0].strftime("%Y-%m-%d") if row[0] else ""
                        chart_labels.add(day_str)
                    
                        g_nsa, g_city, g_cluster, g_site = row[1], row[2], row[3], row[4]
                        nsa, city, cluster, siteid = row[5], row[6], row[7], row[8]
                    
                        kpi_vals = {}
                        for idx, k in enumerate(kpi_defs):
                            v = row[9 + idx]
                            kpi_vals[k[0]] = round(float(v), 2) if v is not None else None
    
                        if g_nsa == 1 and g_city == 1 and g_site == 1 and g_cluster == 1:
                            dim_val = "Regional"
                            for k in kpi_defs:
                                if dim_val not in temp_regional[k[0]]:
                                    temp_regional[k[0]][dim_val] = {}
                                temp_regional[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                            
                        elif g_nsa == 0 and g_city == 1 and g_site == 1 and g_cluster == 1:
                            dim_val = nsa
                            nop_dims_set.add(dim_val)
                            for k in kpi_defs:
                                if dim_val not in temp_nop[k[0]]:
                                    temp_nop[k[0]][dim_val] = {}
                                temp_nop[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                            
                        elif g_nsa == 0 and g_city == 0 and g_site == 1 and g_cluster == 1:
                            dim_val = city
                            city_dims_set.add(dim_val)
                            if nsa not in nsa_city_map: nsa_city_map[nsa] = set()
                            nsa_city_map[nsa].add(city)
                            for k in kpi_defs:
                                if dim_val not in temp_city[k[0]]:
                                    temp_city[k[0]][dim_val] = {}
                                temp_city[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                            
                        elif g_nsa == 1 and g_city == 1 and g_site == 1 and g_cluster == 0:
                            dim_val = cluster
                            cluster_dims_set.add(dim_val)
                            for k in kpi_defs:
                                if dim_val not in temp_cluster[k[0]]:
                                    temp_cluster[k[0]][dim_val] = {}
                                temp_cluster[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                            
                        elif g_nsa == 1 and g_city == 0 and g_site == 1 and g_cluster == 0:
                            dim_val = f"{cluster}|{city}"
                            cluster_dims_set.add(dim_val)
                            for k in kpi_defs:
                                if dim_val not in temp_cluster[k[0]]:
                                    temp_cluster[k[0]][dim_val] = {}
                                temp_cluster[k[0]][dim_val][day_str] = kpi_vals[k[0]]
                            
                    all_data[current_tech]['regional'] = temp_regional
                    all_data[current_tech]['nop']      = temp_nop
                    all_data[current_tech]['city']     = temp_city
                    all_data[current_tech]['cluster']  = temp_cluster
                    
                    # Also run site mapping queries
                    cur.execute('SELECT MAX(date) FROM "vw_pl_daily" WHERE tech = %s AND date >= %s::date AND date <= %s::date', [current_tech, from_date, to_date])
                    max_date = cur.fetchone()[0]
                
                    if max_date:
                        cur.execute("""
                            SELECT city, cluster, siteid 
                            FROM "vw_pl_daily" 
                            WHERE tech = %s AND date = %s::date 
                            GROUP BY city, cluster, siteid
                        """, [current_tech, max_date])
                    
                        for r in cur.fetchall():
                            c, sub, s = r[0], r[1], r[2]
                            if c not in city_site_map: city_site_map[c] = set()
                            city_site_map[c].add(s)
                        
                            if c not in city_cluster_map: city_cluster_map[c] = set()
                            if sub: city_cluster_map[c].add(sub)
                        
                            if sub:
                                if sub not in cluster_site_map: cluster_site_map[sub] = set()
                                cluster_site_map[sub].add(s)
                            
                                if sub not in cluster_city_map: cluster_city_map[sub] = set()
                                cluster_city_map[sub].add(c)
                
                # After looping techs, sort labels and align data
                chart_labels = sorted(list(chart_labels))
                
                def align_data(temp_dict, dims):
                    res = {}
                    for k_id, dim_dict in temp_dict.items():
                        res[k_id] = {}
                        for dim in dims:
                            res[k_id][dim] = [dim_dict.get(dim, {}).get(d) for d in chart_labels]
                    return res
                    
                for t in ['4G', '2G']:
                    all_data[t]['regional'] = align_data(all_data[t]['regional'], ["Regional"])
                    all_data[t]['nop']      = align_data(all_data[t]['nop'], sorted(list(nop_dims_set)))
                    all_data[t]['city']     = align_data(all_data[t]['city'], sorted(list(city_dims_set)))
                    all_data[t]['cluster']  = align_data(all_data[t]['cluster'], sorted(list(cluster_dims_set)))

                query_done = True
                
                # Cache results
                if cache_key:
                    cache.set(cache_key, (
                        all_data, nsa_city_map, city_cluster_map, cluster_city_map, city_site_map, cluster_site_map, 
                        nop_dims_set, city_dims_set, cluster_dims_set, chart_labels, last_update, query_done
                    ), timeout=21600)

        except psycopg2.OperationalError:
            flash("Database connection failed. Please try again.", "warning")
        except psycopg2.errors.QueryCanceled:
            flash("Query timed out. Try a shorter date range or fewer KPIs.", "warning")
        except psycopg2.errors.ConnectionDoesNotExist:
            flash("Database server unreachable. Please try again later.", "warning")
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")

    nsa_city_map_list = {k: sorted(v) for k, v in nsa_city_map.items()}
    city_cluster_map_list = {k: sorted(v) for k, v in city_cluster_map.items()}
    cluster_city_map_list = {k: sorted(v) for k, v in cluster_city_map.items() if k}
    city_site_map_list = {k: sorted(v) for k, v in city_site_map.items()}
    cluster_site_map_list = {k: sorted(v) for k, v in cluster_site_map.items()}

    return _no_cache(make_response(render_template(
        "pl_monitoring.html",
        username=session.get("username", "User"),
        from_date=from_date or default_fr,
        to_date=to_date or default_to,
        default_fr=default_fr,
        default_to=default_to,
        sel_kpis=sel_kpis,
        all_kpis=ALL_KPI_DEFS,
        kpi_defs=[(k[0], k[1], k[2], k[3], k[4], k[5]) for k in kpi_defs],
        chart_labels=list(chart_labels),
        regional_dims=["Regional"],
        all_data=all_data,
        nop_dims=sorted(list(nop_dims_set)),
        city_dims=sorted(list(city_dims_set)),
        cluster_dims=sorted(list(cluster_dims_set)),
        nsa_city_map=nsa_city_map_list,
        city_cluster_map=city_cluster_map_list,
        cluster_city_map=cluster_city_map_list,
        city_site_map=city_site_map_list,
        cluster_site_map=cluster_site_map_list,
        last_update=last_update,
        query_done=query_done,
    )))

@pl_monitoring.route("/api/pl_monitoring/hourly", methods=["POST"])
@login_required
@cache.cached(timeout=21600, make_cache_key=make_post_cache_key)
def api_pl_monitoring_hourly():
    data = request.get_json()
    from_date = data.get("from_date")
    to_date = data.get("to_date")
    tab = data.get("tab") 
    entities = data.get("entities", [])
    kpi_ids = data.get("kpis", [])
    granularity = data.get("granularity", "hourly")
    tech = data.get("tech", "4G")
    
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
                group_by_col = ""  # no extra group column for regional
                where_clause = ""
                params = [from_date, to_date]
            elif tab == "nop":
                group_col = "nsa"
                group_by_col = "nsa"
                where_clause = "AND nsa = ANY(%s)"
                params = [from_date, to_date, entities]
            elif tab == "city":
                group_col = "city"
                group_by_col = "city"
                where_clause = "AND city = ANY(%s)"
                params = [from_date, to_date, entities]
            elif tab == "cluster":
                group_col = "cluster"
                group_by_col = "cluster"
                where_clause = "AND cluster = ANY(%s)"
                params = [from_date, to_date, entities]
            elif tab == "site":
                group_col = "siteid"
                group_by_col = "siteid"
                where_clause = "AND siteid = ANY(%s)"
                params = [from_date, to_date, entities]
            else:
                return jsonify({"error": "Invalid tab"}), 400
            
            if granularity == 'hourly':
                hour_clean = """
                    CASE 
                        WHEN hour::text ~ '^[0-9]+\\.[0-9]+$' THEN LPAD(ROUND(hour::numeric * 24)::text, 2, '0')
                        WHEN hour::text ~ '^[0-9]+$' THEN LPAD(hour::text, 2, '0')
                        ELSE TO_CHAR(hour::time, 'HH24')
                    END
                """
                date_col = f"TO_CHAR(date, 'YYYY-MM-DD') || ' ' || ({hour_clean}) || ':00'"
                group_by = (f"1, 2" if group_by_col else "1")
                order_by = "1"
                table_name = '"vw_pl_hourly"'
                date_filter_col = 'date'
            else:
                date_col = "TO_CHAR(date, 'YYYY-MM-DD')"
                group_by = (f"1, 2" if group_by_col else "1")
                order_by = "1"
                table_name = '"vw_pl_daily"'
                date_filter_col = 'date'

            sql = f"""
                SELECT 
                    {date_col} as dt_label,
                    {group_col} as dimension,
                    {kpi_selects}
                FROM {table_name}
                WHERE tech = %s AND {date_filter_col} >= %s::date AND {date_filter_col} <= %s::date
                  {where_clause}
                GROUP BY {group_by}
                ORDER BY {order_by}
            """
        
            cur.execute(sql, [tech] + params)
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

@pl_monitoring.route('/api/pl_monitoring/site_cluster', methods=['POST'])
@login_required
@cache.cached(timeout=21600, make_cache_key=make_post_cache_key)
def api_pl_monitoring_site_cluster():
    req = request.json
    from_date   = req.get('from_date')
    to_date     = req.get('to_date')
    sites       = req.get('sites', [])
    granularity = req.get('granularity', 'daily')
    sel_kpis    = req.get('kpis', [])
    tech        = req.get('tech', '4G')
    
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
                hour_clean = """
                    CASE 
                        WHEN hour::text ~ '^[0-9]+\\.[0-9]+$' THEN LPAD(ROUND(hour::numeric * 24)::text, 2, '0')
                        WHEN hour::text ~ '^[0-9]+$' THEN LPAD(hour::text, 2, '0')
                        ELSE TO_CHAR(hour::time, 'HH24')
                    END
                """
                date_col = f"TO_CHAR(date, 'YYYY-MM-DD') || ' ' || ({hour_clean}) || ':00'"
                group_by = "1"
                order_by = "1"
                table_name = '"vw_pl_hourly"'
                date_filter_col = 'date'
            else:
                date_col = "TO_CHAR(date, 'YYYY-MM-DD')"
                group_by = "1"
                order_by = "1"
                table_name = '"vw_pl_daily"'
                date_filter_col = 'date'
            
            sql = f"""
                SELECT 
                    {date_col} as dt_label,
                    {kpi_selects}
                FROM {table_name}
                WHERE tech = %s AND {date_filter_col} >= %s::date AND {date_filter_col} <= %s::date
                  AND siteid = ANY(%s)
                GROUP BY {group_by}
                ORDER BY {order_by}
            """
        
            cur.execute(sql, [tech, from_date, to_date, sites])
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

