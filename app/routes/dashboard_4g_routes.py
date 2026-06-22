"""4G Dashboard Routes — /dashboard_4g"""
from flask import Blueprint, render_template, request, session, flash, make_response, jsonify
from app.db.db_webapp import get_postgres_connection, get_site_list_4g
from ._utils import login_required, _no_cache, json_response
import psycopg2
import psycopg2.extras
import psycopg2.errors
from collections import defaultdict
import json

dashboard_4g = Blueprint("dashboard_4g", __name__)

ALL_KPI_DEFS = [
    # chart_id, title, unit, y_label, y_min, y_max, sql_expr, group_name, is_lower_better
    ("payloadChart",   "4G Payload",             "GB",             "4G Payload (GB)",  None, None,
     'SUM("4g_payload_mb")/1024.0',             "Productivity", False),
    ("volteChart",     "VoLTE Traffic",         "Erl",            "VoLTE (Erl)",  None, None,
     "SUM(volte_traffic)",                "Productivity", False),
    ("availChart",     "Availability",          "%",      "Availability (%)", None, 100,
     'CASE WHEN SUM(avail_denum)>0 THEN ROUND((SUM(avail_num)/SUM(avail_denum)*100)::numeric,2) ELSE NULL END',    "Availability", False),
    ("maxRrcChart",    "Max RRC User",          "Users",          "Max RRC Users",  None, None,
     "SUM(max_rrc_conn_user)",            "User", False),
    ("activeUserChart","Active User",           "Users",          "Active Users",  None, None,
     "SUM(new_active_users)",            "User", False),
    ("cssrChart",      "CSSR",                  "%",       "CSSR (%)", None, 100,
     'CASE WHEN SUM(cssr_denum)>0 THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),
    ("rrcSrChart",     "RRC SR",                "%",     "RRC SR (%)", None, 100,
     'CASE WHEN SUM(rrc_setup_denum)>0 THEN ROUND((SUM(rrc_setup_num)/SUM(rrc_setup_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),
    ("erabSrChart",    "ERAB SR",               "%",    "ERAB SR (%)", None, 100,
     'CASE WHEN SUM(erab_setup_denum)>0 THEN ROUND((SUM(erab_setup_num)/SUM(erab_setup_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),
    ("sdrChart",       "SDR",                   "%",        "SDR (%)",  None, None,
     'CASE WHEN SUM(sdr_denum)>0 THEN ROUND((SUM(sdr_num)/SUM(sdr_denum)*100)::numeric,2) ELSE NULL END', "Retainability", True),
    ("dlPrbChart",     "DL PRB",                "%",     "DL PRB (%)", 0, 100,
     'CASE WHEN SUM(dl_prb_util_denum)>0 THEN ROUND((SUM(dl_prb_util_num)/SUM(dl_prb_util_denum)*100)::numeric,2) ELSE NULL END', "Capacity", False),
    ("ulPrbChart",     "UL PRB",                "%",     "UL PRB (%)", 0, 100,
     'CASE WHEN SUM(ul_prb_util_denum)>0 THEN ROUND((SUM(ul_prb_util_num)/SUM(ul_prb_util_denum)*100)::numeric,2) ELSE NULL END', "Capacity", False),
    ("dlThpChart",     "User DL Throughput",    "Mbps",  "DL Thp (Mbps)",  None, None,
     'CASE WHEN SUM(user_dl_thp_denum)>0 THEN ROUND((SUM(user_dl_thp_num)/SUM(user_dl_thp_denum)/1000)::numeric,2) ELSE NULL END', "Integrity", False),
    ("ulThpChart",     "User UL Throughput",    "Mbps",  "UL Thp (Mbps)",  None, None,
     'CASE WHEN SUM(user_ul_thp_denum)>0 THEN ROUND((SUM(user_ul_thp_num)/SUM(user_ul_thp_denum)/1000)::numeric,2) ELSE NULL END', "Integrity", False),
    ("ifhoChart",      "IFHO",                  "%",       "IFHO (%)", None, 100,
     'CASE WHEN SUM(ifho_denum)>0 THEN ROUND((SUM(ifho_num)/SUM(ifho_denum)*100)::numeric,2) ELSE NULL END', "Mobility", False),
    ("seChart",        "Spectral Efficiency",   "SE",             "SE",  None, None,
     'CASE WHEN SUM(se_v3_denum)>0 THEN ROUND((SUM(se_v3_num)/SUM(se_v3_denum))::numeric,2) ELSE NULL END', "Quality", False),
    ("cqiChart",       "CQI",                  "CQI",            "CQI", None, None,
     'CASE WHEN SUM(denum_average_cqi)>0 THEN ROUND((SUM(num_average_cqi)/SUM(denum_average_cqi))::numeric,2) ELSE NULL END', "Quality", False),
    ("csfbChart",      "CSFB",                  "%",       "CSFB (%)", None, 100,
     'CASE WHEN SUM(csfb_denum)>0 THEN ROUND((SUM(csfb_num)/SUM(csfb_denum)*100)::numeric,2) ELSE NULL END', "Others", False),
    ("s1SrChart",      "S1 SR",                 "%",      "S1 SR (%)", None, 100,
     'CASE WHEN SUM(s1_signaling_sr_denum)>0 THEN ROUND((SUM(s1_signaling_sr_num)/SUM(s1_signaling_sr_denum)*100)::numeric,2) ELSE NULL END', "Others", False),
]

KPI_GROUPS = ["Productivity","Availability","User","Accessibility","Retainability","Capacity","Integrity","Mobility","Quality","Others"]


@dashboard_4g.route("/dashboard_4g")
@login_required
def dashboard_4g_view():
    trend_from_date = request.args.get("trend_from_date", "")
    trend_to_date   = request.args.get("trend_to_date",   "")
    before_from_date = request.args.get("before_from_date", "")
    before_to_date   = request.args.get("before_to_date",   "")
    after_from_date = request.args.get("after_from_date",  "")
    after_to_date   = request.args.get("after_to_date",    "")
    
    execution_dates_raw = request.args.get("execution_dates", "")
    execution_dates = [d.strip() for d in execution_dates_raw.split(",") if d.strip()]
    
    sel_sites = request.args.getlist("site")
    
    # Support site IDs pasted from CSV — comma/newline separated, deduplicate
    site_paste_raw = request.args.get("site_paste", "")
    if site_paste_raw:
        extra = [s.strip() for s in site_paste_raw.replace("\n", ",").split(",") if s.strip()]
        for s in extra:
            if s not in sel_sites:
                sel_sites.append(s)

    sel_kpis = request.args.getlist("kpi")
    if not sel_kpis:
        # Default to some standard KPIs if none selected
        sel_kpis = ["payloadChart", "cssrChart", "dlPrbChart", "dlThpChart", "rrcSrChart", "erabSrChart", "callSetupChart", "sdrChart", "erabDropChart", "serviceDropChart", "ulPrbChart", "ulThpChart", "packetLossChart"]
        
    KPI_DEFS = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]

    sites_list = []
    try:
        sites_list, _ = get_site_list_4g()
    except Exception:
        sites_list = []

    last_update = None
    
    # Initialize response structures
    trend_labels = []
    trend_chart_data = defaultdict(lambda: {"total": []})
    band_trend_chart_data = defaultdict(lambda: defaultdict(list))
    
    cluster_compare = {}
    band_compare = defaultdict(dict)
    sector_compare = defaultdict(dict)
    site_compare = defaultdict(dict)
    
    compare_hourly_labels = []
    compare_hourly_data = {}
    
    conn = None
    cur = None
    
    has_trend = trend_from_date and trend_to_date and sel_sites and KPI_DEFS
    has_compare = before_from_date and before_to_date and after_from_date and after_to_date and sel_sites and KPI_DEFS

    if has_trend or has_compare:
        try:
            conn = get_postgres_connection()
            cur = conn.cursor()
            
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
                # 1. Cluster Trend
                query_trend = f"""
                    SELECT 
                        TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI') AS dt_label,
                        datehour,
                        {kpi_selects}
                    FROM "4g_kpi_zte"
                    WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                    GROUP BY datehour, dt_label ORDER BY datehour
                """
                cur.execute(query_trend, [trend_from_date, trend_to_date, sel_sites])
                rows_trend = cur.fetchall()
                
                # Keep original order by date
                trend_labels = []
                trend_map = {}
                for r in rows_trend:
                    if r[0] not in trend_labels:
                        trend_labels.append(r[0])
                    trend_map[r[0]] = r[2:]
                
                for idx, kpi in enumerate(KPI_DEFS):
                    kpi_id = kpi[0]
                    for hr in trend_labels:
                        val_row = trend_map.get(hr)
                        val = round(float(val_row[idx]), 2) if val_row and val_row[idx] is not None else None
                        trend_chart_data[kpi_id]["total"].append(val)
                
                # 2. Band Trend
                query_trend_band = f"""
                    SELECT 
                        TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI') AS dt_label,
                        datehour,
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
                        {kpi_selects}
                    FROM "4g_kpi_zte"
                    WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                    GROUP BY datehour, dt_label, band ORDER BY datehour
                """
                cur.execute(query_trend_band, [trend_from_date, trend_to_date, sel_sites])
                rows_band_trend = cur.fetchall()
                band_trend_map = defaultdict(dict)
                for r in rows_band_trend:
                    dt_label = r[0]
                    band = r[2]
                    band_trend_map[band][dt_label] = r[3:]
                
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
                    # Cluster
                    cur.execute(f"""
                        SELECT {kpi_selects}
                        FROM "4g_kpi_zte"
                        WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                    """, [from_d, to_d, sel_sites])
                    cluster_row = cur.fetchone()
                    
                    # Band
                    cur.execute(f"""
                        SELECT 
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
                            {kpi_selects}
                        FROM "4g_kpi_zte"
                        WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                        GROUP BY band
                    """, [from_d, to_d, sel_sites])
                    band_rows = cur.fetchall()
                    
                    # Sector
                    cur.execute(f"""
                        SELECT 
                            siteid,
                            CASE
                                WHEN LENGTH(cell::text) > 2 AND RIGHT(cell::text, 1) = '5' THEN SUBSTRING(cell::text FROM 2 FOR 1)
                                WHEN LENGTH(cell::text) > 2 THEN LEFT(cell::text, 2)
                                ELSE LEFT(cell::text, 1)
                            END AS sector,
                            {kpi_selects}
                        FROM "4g_kpi_zte"
                        WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                        GROUP BY siteid, sector
                    """, [from_d, to_d, sel_sites])
                    sector_rows = cur.fetchall()
                    
                    # Site
                    cur.execute(f"""
                        SELECT siteid, {kpi_selects}
                        FROM "4g_kpi_zte"
                        WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                        GROUP BY siteid
                    """, [from_d, to_d, sel_sites])
                    site_rows = cur.fetchall()
                    
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

                # --- Compare Hourly Trend ---
                HR_FMT = "'HH24:00'"
                cur.execute(f"""
                    SELECT TO_CHAR(datehour, {HR_FMT}) AS hr, {kpi_selects}
                    FROM "4g_kpi_zte"
                    WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                    GROUP BY hr ORDER BY hr
                """, [before_from_date, before_to_date, sel_sites])
                before_hourly = cur.fetchall()

                cur.execute(f"""
                    SELECT TO_CHAR(datehour, {HR_FMT}) AS hr, {kpi_selects}
                    FROM "4g_kpi_zte"
                    WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                    GROUP BY hr ORDER BY hr
                """, [after_from_date, after_to_date, sel_sites])
                after_hourly = cur.fetchall()

                compare_hourly_labels = sorted(list(set([r[0] for r in before_hourly] + [r[0] for r in after_hourly])))
                before_hourly_map = {r[0]: r[1:] for r in before_hourly}
                after_hourly_map = {r[0]: r[1:] for r in after_hourly}

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
        conn = get_postgres_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT id, dashboard_name, chart_config FROM user_custom_charts WHERE username = %s ORDER BY dashboard_name", [username])
        user_charts = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error fetching custom charts: {e}")

    return _no_cache(make_response(render_template(
        "dashboard_4g.html",
        username=username,
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
        band_trend_chart_data=dict(band_trend_chart_data),
        
        cluster_compare=cluster_compare,
        band_compare=dict(sorted(band_compare.items(), key=lambda x: (len(x[0]), x[0]))),
        sector_compare=dict(sector_compare),
        site_compare=dict(site_compare),
        
        compare_hourly_labels=compare_hourly_labels,
        compare_hourly_data=compare_hourly_data,
        
        kpi_defs=[(k[0], k[1], k[2], k[3], k[4], k[5], k[7], k[8]) for k in KPI_DEFS],
        kpi_groups=KPI_GROUPS,
        user_charts=user_charts,
    )))

@dashboard_4g.route("/api/dashboard_4g/save_chart", methods=["POST"])
@login_required
def save_custom_chart():
    username = session.get("username", "User")
    data = request.get_json()
    dashboard_name = data.get("dashboard_name")
    chart_config = data.get("chart_config")
    
    if not dashboard_name or not chart_config:
        return json_response({"error": "Missing dashboard name or config"}, 400)
        
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO user_custom_charts (username, dashboard_name, chart_config, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (username, dashboard_name) 
            DO UPDATE SET chart_config = EXCLUDED.chart_config, updated_at = CURRENT_TIMESTAMP
        """, [username, dashboard_name, json.dumps(chart_config)])
        conn.commit()
        cur.close()
        conn.close()
        return json_response({"success": True, "message": "Dashboard saved successfully"})
    except Exception as e:
        return json_response({"error": str(e)}, 500)

@dashboard_4g.route("/api/dashboard_4g/delete_chart", methods=["POST"])
@login_required
def delete_custom_chart():
    username = session.get("username", "User")
    data = request.get_json()
    dashboard_name = data.get("dashboard_name")
    
    if not dashboard_name:
        return json_response({"error": "Missing dashboard name"}, 400)
        
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM user_custom_charts WHERE username = %s AND dashboard_name = %s", [username, dashboard_name])
        conn.commit()
        cur.close()
        conn.close()
        return json_response({"success": True, "message": "Dashboard deleted successfully"})
    except Exception as e:
        return json_response({"error": str(e)}, 500)
