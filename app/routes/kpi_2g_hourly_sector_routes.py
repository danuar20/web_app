"""2G KPI Hourly Sector Routes — /kpi_2g_hourly_sector"""
from flask import Blueprint, render_template, request, session, flash, make_response
from app.db.db_webapp import get_postgres_connection, get_site_list_2g
from ._utils import viewer_blocked, login_required, _no_cache, db_query
import psycopg2
import psycopg2.errors
from collections import defaultdict

kpi2g_hourly_sector = Blueprint("kpi2g_hourly_sector", __name__)

ALL_KPI_DEFS = [
    # chart_id, title, unit, y_label, y_min, y_max, sql_expr, is_lower_better
    ("payloadChart",   "Payload",                "MB",   "Payload (MB)", None, None,
     'ROUND(SUM(total_payload)::numeric,2)', False),
    ("tchTrafficChart","TCH Traffic",            "Erl",  "TCH (Erl)", None, None,
     'ROUND(SUM(tch_traffic)::numeric,2)', False),
    ("sdcchTrafficChart","SDCCH Traffic",        "Erl",  "SDCCH (Erl)", None, None,
     'ROUND(SUM(sdcch_traffic)::numeric,2)', False),
    ("fullRateChart",  "Full Rate Traffic",      "Erl",  "Full Rate (Erl)", 0, None,
     'ROUND(SUM("Offic_full_traffic")::numeric,2)', False),
    ("halfRateChart",  "Half Rate Traffic",      "Erl",  "Half Rate (Erl)", 0, None,
     'ROUND(SUM("Offic_half_traffic")::numeric,2)', False),
    ("availChart",     "Availability",           "%",    "Availability (%)", None, 100,
     'CASE WHEN SUM(tch_avail_denum)>0 THEN ROUND((SUM(tch_avail_num)/SUM(tch_avail_denum)*100)::numeric,2) ELSE NULL END', False),
    ("cssrChart",      "CSSR",                   "%",    "CSSR (%)", None, 100,
     'CASE WHEN SUM(cssr_denum)>0 THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100)::numeric,2) ELSE NULL END', False),
    ("ccsrChart",      "CCSR",                   "%",    "CCSR (%)", None, 100,
     'CASE WHEN SUM("2g_ccsr_denum")>0 THEN ROUND((SUM("2g_ccsr_num")/SUM("2g_ccsr_denum")*100)::numeric,2) ELSE NULL END', False),
    ("sdsrChart",      "SDSR",                   "%",    "SDSR (%)", None, 100,
     'CASE WHEN SUM(sdsr_denum)>0 THEN ROUND((SUM(sdsr_num)/SUM(sdsr_denum)*100)::numeric,2) ELSE NULL END', False),
    ("tbfEstChart",    "TBF DL Est",             "%",    "TBF Est (%)", None, 100,
     'CASE WHEN SUM(tbf_dl_est_denum)>0 THEN ROUND((SUM(tbf_dl_est_num)/SUM(tbf_dl_est_denum)*100)::numeric,2) ELSE NULL END', False),
    ("tbfCompChart",   "TBF Comp",            "%",    "TBF Comp (%)", None, 100,
     'CASE WHEN SUM(tbf_comp_denum)>0 THEN ROUND((SUM(tbf_comp_num)/SUM(tbf_comp_denum)*100)::numeric,2) ELSE NULL END', False),
    ("tchDropChart",   "TCH Drop",               "%",    "TCH Drop (%)", 0, None,
     'CASE WHEN SUM(tch_drop_denum)>0 THEN ROUND((SUM(tch_drop_num)/SUM(tch_drop_denum)*100)::numeric,2) ELSE NULL END', True),
    ("tchDropNumChart","TCH Drop Num",           "Drops","TCH Drop Num", 0, None,
     'SUM(tch_drop_num)', True),
    ("tchBlkChart",    "TCH Blocking",           "%",    "TCH Blk (%)", 0, None,
     'CASE WHEN SUM(tch_block_denum)>0 THEN ROUND((SUM(tch_block_num)/SUM(tch_block_denum)*100)::numeric,2) ELSE NULL END', True),
    ("tchBlkNumChart", "TCH Block Num",          "Blk",  "TCH Blk Num", 0, None,
     'SUM(tch_block_num)', True),
    ("sdcchBlkChart",  "SDCCH Blocking",         "%",    "SDCCH Blk (%)", 0, None,
     'CASE WHEN SUM(sdcch_block_denum)>0 THEN ROUND((SUM(sdcch_block_num)/SUM(sdcch_block_denum)*100)::numeric,2) ELSE NULL END', True),
    ("sdcchBlkNumChart","SDCCH Block Num",       "Blk",  "SDCCH Blk Num", 0, None,
     'SUM(sdcch_block_num)', True),
    ("hosrChart",      "HOSR",                   "%",    "HOSR (%)", None, 100,
     'CASE WHEN SUM(hosr_denum)>0 THEN ROUND((SUM(hosr_num)/SUM(hosr_denum)*100)::numeric,2) ELSE NULL END', False),
    ("fastRetChart",   "Fast Return to LTE",     "Ret",  "Fast Return", None, None,
     'SUM(fastreturn_to_lte)', False),
    ("icmChart",       "ICM Band 3-5",           "%",    "ICM (%)", 0, None,
     'CASE WHEN SUM(icm_band35_denum)>0 THEN ROUND((SUM(icm_band35_num)/SUM(icm_band35_denum)*100)::numeric,2) ELSE NULL END', True),
    ("interfChart",    "Interference",           "%",    "Interference (%)", None, 100,
     'CASE WHEN SUM(denum_icm_interference_ono)>0 THEN ROUND((SUM(num_icm_interference_ono)/SUM(denum_icm_interference_ono)*100)::numeric,2) ELSE NULL END', True),
]

@kpi2g_hourly_sector.route("/kpi_2g_hourly_sector")
@login_required
@viewer_blocked
def kpi_2g_hourly_sector_view():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")
    sel_kpis  = request.args.getlist("kpi")

    if not sel_kpis:
        sel_kpis = ["payloadChart", "cssrChart", "tchTrafficChart", "availChart"]

    KPI_DEFS = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]

    site_paste_raw = request.args.get("site_paste", "")
    if site_paste_raw:
        extra = [s.strip() for s in site_paste_raw.replace("\\n", ",").split(",") if s.strip()]
        for s in extra:
            if s not in sel_sites:
                sel_sites.append(s)

    chart_labels = []
    chart_data = defaultdict(lambda: defaultdict(dict)) # kpi_id -> legend_name -> datehour -> value
    
    sites_list = []
    last_update = None

    try:
        sites_list = get_site_list_2g()
    except Exception:
        sites_list = []

    if from_date and to_date and sel_sites:
        conn = None
        cur = None
        try:
            with db_query() as (conn, cur):

                try:
                    cur.execute('SELECT MAX(datehour) FROM "2g_kpi_zte"')
                    raw_last = cur.fetchone()
                    last_update = raw_last[0].strftime('%Y-%m-%d %H:%M') if raw_last and raw_last[0] else None
                except Exception:
                    last_update = None

                kpi_selects = ", ".join([f"{k[6]} AS {k[0]}" for k in KPI_DEFS])
            
                query = f"""
                    SELECT
                        datehour,
                        siteid,
                        bts_name,
                        RIGHT(bts_name::text, 1) AS sector,
                        "Tech" AS tech,
                        {kpi_selects}
                    FROM "2g_kpi_zte"
                    WHERE datehour::date BETWEEN %s::date AND %s::date AND siteid = ANY(%s)
                    GROUP BY datehour, siteid, bts_name, sector, "Tech"
                    ORDER BY datehour, siteid, bts_name, sector, "Tech"
                """
            
                cur.execute(query, [from_date, to_date, sel_sites])
            
                hours_seen = set()
                for row in cur.fetchall():
                    dh = row[0].strftime("%Y-%m-%d %H:%M")
                    siteid = row[1]
                    bts_name = str(row[2]) if row[2] is not None else ""
                    sector = row[3]
                    tech = row[4]
                
                    # legend format: {siteid} S{sector}-{tech}
                    tech_str = f"-{tech}" if tech else ""
                    legend_name = f"{siteid} S{sector}{tech_str}"
                
                    hours_seen.add(dh)
                
                    # Starting from index 5 are the KPIs
                    for idx, kpi in enumerate(KPI_DEFS):
                        val = row[5 + idx]
                        if val is not None:
                            val = float(val)
                        chart_data[kpi[0]][legend_name][dh] = val
                    
                chart_labels = sorted(list(hours_seen))
            
                # Convert per-hour dicts to ordered lists for chart rendering
                formatted_chart_data = {}
                for kpi in KPI_DEFS:
                    kpi_id = kpi[0]
                    formatted_chart_data[kpi_id] = {}
                    for legend_name, series_data in chart_data[kpi_id].items():
                        formatted_chart_data[kpi_id][legend_name] = [series_data.get(h) for h in chart_labels]
            
                chart_data = formatted_chart_data
        except psycopg2.OperationalError:
            flash("Database connection failed. Please try again.", "warning")
        except psycopg2.errors.QueryCanceled:
            flash("Query timed out. Please try a shorter date range.", "warning")
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")

    return _no_cache(make_response(render_template(
        "kpi_2g_hourly_sector.html",
        username=session.get("username", "User"),
        sites_list=sites_list,
        sel_sites=sel_sites,
        sel_kpis=sel_kpis,
        from_date=from_date,
        to_date=to_date,
        last_update=last_update,
        chart_labels=chart_labels,
        chart_data=chart_data,
        kpi_defs=[(k[0], k[1], k[2], k[3], k[4], k[5], k[7]) for k in ALL_KPI_DEFS],
    )))
