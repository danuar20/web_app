"""2G KPI Hourly Trend Routes — /kpi_2g_hourly/trend (cluster aggregation)"""
from flask import Blueprint, render_template, request, session, flash, make_response
from app.db.db_webapp import get_postgres_connection, get_site_list_2g
from ._utils import login_required, _no_cache, json_response
import psycopg2
import psycopg2.errors

kpi2g_trend = Blueprint("kpi2g_trend", __name__)

@kpi2g_trend.route("/api/kpi_2g_hourly/trend/last_update")
@login_required
def api_kpi_2g_trend_last_update():
    """Lightweight endpoint to get last update timestamp without full KPI query"""
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute('SELECT MAX(datehour::date) FROM "2g_kpi_zte"')
        raw = cur.fetchone()
        cur.close()
        conn.close()
        last_update = raw[0].strftime('%Y-%m-%d') if raw and raw[0] else None
        return json_response({"last_update": last_update})
    except Exception as e:
        return json_response({"error": str(e)}, 500)

@kpi2g_trend.route("/kpi_2g_hourly/trend")
@login_required
def kpi_2g_hourly_trend():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")
    cluster_name = request.args.get("cluster_name", "Cluster").strip() or "Cluster"

    # Support site IDs pasted from CSV — comma/newline separated, deduplicate
    site_paste_raw = request.args.get("site_paste", "")
    if site_paste_raw:
        extra = [s.strip() for s in site_paste_raw.replace("\\n", ",").split(",") if s.strip()]
        for s in extra:
            if s not in sel_sites:
                sel_sites.append(s)

    ALL_KPI_DEFS = [
        # chart_id, title, unit, y_label, y_min, y_max, sql_expr, is_lower_better
        ("payloadChart",   "Payload",                "GB",   None,  None, None,
         'ROUND(SUM(total_payload)::numeric,2)', False),
        ("tchTrafficChart","TCH Traffic",            "Erl",  None,  None, None,
         'ROUND(SUM(tch_traffic)::numeric,2)', False),
        ("sdcchTrafficChart","SDCCH Traffic",        "Erl",  None,  None, None,
         'ROUND(SUM(sdcch_traffic)::numeric,2)', False),
        ("fullRateChart",  "Full Rate Traffic",      "Erl",  None,  0, None,
         'ROUND(SUM("Offic_full_traffic")::numeric,2)', False),
        ("halfRateChart",  "Half Rate Traffic",      "Erl",  None,  None, None,
         'ROUND(SUM("Offic_half_traffic")::numeric,2)', False),
        ("availChart",     "Availability",           "%", None, None, 100,
         'CASE WHEN SUM(tch_avail_denum)>0 THEN ROUND((SUM(tch_avail_num)/SUM(tch_avail_denum)*100)::numeric,2) ELSE NULL END', False),
        ("cssrChart",      "CSSR",                   "%", None, None, 100,
         'CASE WHEN SUM(cssr_denum)>0 THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100)::numeric,2) ELSE NULL END', False),
        ("ccsrChart",      "CCSR",                   "%", None, None, 100,
         'CASE WHEN SUM("2g_ccsr_denum")>0 THEN ROUND((SUM("2g_ccsr_num")/SUM("2g_ccsr_denum")*100)::numeric,2) ELSE NULL END', False),
        ("sdsrChart",      "SDSR",                   "%", None, None, 100,
         'CASE WHEN SUM(sdsr_denum)>0 THEN ROUND((SUM(sdsr_num)/SUM(sdsr_denum)*100)::numeric,2) ELSE NULL END', False),
        ("tbfEstChart",    "TBF DL Est",             "%", None, None, 100,
         'CASE WHEN SUM(tbf_dl_est_denum)>0 THEN ROUND((SUM(tbf_dl_est_num)/SUM(tbf_dl_est_denum)*100)::numeric,2) ELSE NULL END', False),
        ("tbfCompChart",   "TBF Comp",               "%", None, None, 100,
         'CASE WHEN SUM(tbf_comp_denum)>0 THEN ROUND((SUM(tbf_comp_num)/SUM(tbf_comp_denum)*100)::numeric,2) ELSE NULL END', False),
        ("tchDropChart",   "TCH Drop",               "%", None, 0, None,
         'CASE WHEN SUM(tch_drop_denum)>0 THEN ROUND((SUM(tch_drop_num)/SUM(tch_drop_denum)*100)::numeric,2) ELSE NULL END', True),
        ("tchDropNumChart","TCH Drop Num",           "", None, 0, None,
         'SUM(tch_drop_num)', True),
        ("tchBlkChart",    "TCH Blocking",           "%", None, 0, None,
         'CASE WHEN SUM(tch_block_denum)>0 THEN ROUND((SUM(tch_block_num)/SUM(tch_block_denum)*100)::numeric,2) ELSE NULL END', True),
        ("tchBlkNumChart", "TCH Block Num",          "",  None, 0, None,
         'SUM(tch_block_num)', True),
        ("sdcchBlkChart",  "SDCCH Blocking",         "%", None, 0, None,
         'CASE WHEN SUM(sdcch_block_denum)>0 THEN ROUND((SUM(sdcch_block_num)/SUM(sdcch_block_denum)*100)::numeric,2) ELSE NULL END', True),
        ("sdcchBlkNumChart","SDCCH Block Num",       "",  None, 0, None,
         'SUM(sdcch_block_num)', True),
        ("hosrChart",      "HOSR",                   "%", None, None, 100,
         'CASE WHEN SUM(hosr_denum)>0 THEN ROUND((SUM(hosr_num)/SUM(hosr_denum)*100)::numeric,2) ELSE NULL END', False),
        ("fastRetChart",   "Fast Return to LTE",     "",  None, None, None,
         'SUM(fastreturn_to_lte)', False),
        ("icmChart",       "ICM Band 3-5",           "%", None, 0, None,
         'CASE WHEN SUM(icm_band35_denum)>0 THEN ROUND((SUM(icm_band35_num)/SUM(icm_band35_denum)*100)::numeric,2) ELSE NULL END', True),
        ("interfChart",    "Interference",           "%", None, 0, None,
         'CASE WHEN SUM(denum_icm_interference_ono)>0 THEN ROUND((SUM(num_icm_interference_ono)/SUM(denum_icm_interference_ono)*100)::numeric,2) ELSE NULL END', True),
    ]

    sel_kpis = request.args.getlist("kpi")
    if not sel_kpis:
        # Default to all if none selected
        sel_kpis = [k[0] for k in ALL_KPI_DEFS]
        
    KPI_DEFS = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]

    chart_labels = []
    cluster_data = {} # { "payloadChart": {"ClusterName": [1, 2, 3]} }
    sites_list = []
    last_update = None

    try:
        sites_list = get_site_list_2g()
    except Exception:
        sites_list = []

    if from_date and to_date and sel_sites and KPI_DEFS:
        conn = None
        cur = None
        try:
            conn = get_postgres_connection()
            cur = conn.cursor()

            try:
                cur.execute('SELECT MAX(datehour::date) FROM "2g_kpi_zte"')
                raw_last = cur.fetchone()
                last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
            except Exception:
                last_update = None

            HR_FMT = "'YYYY-MM-DD HH24:MI'"
            kpi_selects = ", ".join([f"{k[6]} AS {k[0]}" for k in KPI_DEFS])

            cur.execute(f"""
                SELECT TO_CHAR(datehour, {HR_FMT}) AS hr, {kpi_selects}
                FROM "2g_kpi_zte"
                WHERE datehour::date BETWEEN %s::date AND %s::date AND siteid = ANY(%s)
                GROUP BY datehour
                ORDER BY datehour
            """, [from_date, to_date, sel_sites])
            
            rows = cur.fetchall()

            for k in KPI_DEFS:
                cluster_data[k[0]] = {cluster_name: []}

            for row in rows:
                chart_labels.append(row[0])
                for idx, k in enumerate(KPI_DEFS):
                    val = row[idx+1]
                    cluster_data[k[0]][cluster_name].append(round(float(val), 2) if val is not None else None)

            cur.close()
            conn.close()

        except psycopg2.OperationalError:
            if conn:  conn.rollback()
            if cur:   cur.close()
            if conn:  conn.close()
            flash("Database connection failed. Please try again.", "warning")
        except psycopg2.errors.QueryCanceled:
            if conn:  conn.rollback()
            if cur:   cur.close()
            if conn:  conn.close()
            flash("Query timed out. Please try a shorter date range.", "warning")
        except Exception as e:
            if conn:
                try: conn.rollback()
                except: pass
            if cur: cur.close()
            if conn: conn.close()
            flash(f"Error: {str(e)}", "danger")

    return _no_cache(make_response(render_template(
        "kpi_2g_hourly_cluster.html",
        username=session["username"],
        sites_list=sites_list,
        sel_sites=sel_sites,
        from_date=from_date,
        to_date=to_date,
        last_update=last_update,
        cluster_name=cluster_name,
        chart_labels=chart_labels,
        cluster_data=cluster_data,
        kpi_defs=[(k[0],k[1],k[2],k[3],k[4],k[5],k[7]) for k in KPI_DEFS],
        all_kpis=ALL_KPI_DEFS,
        sel_kpis=sel_kpis
    )))
