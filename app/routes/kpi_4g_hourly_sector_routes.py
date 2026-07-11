"""4G KPI Hourly Sector Routes — /kpi_4g_hourly_sector"""
from flask import Blueprint, render_template, request, session, flash, make_response
from app.db.db_webapp import get_postgres_connection, get_site_list_4g
from ._utils import viewer_blocked, login_required, _no_cache, json_response, db_query
import psycopg2
import psycopg2.errors
from collections import defaultdict

kpi4g_hourly_sector = Blueprint("kpi4g_hourly_sector", __name__)

ALL_KPI_DEFS = [
    # chart_id, title, unit, y_label, y_min, y_max, sql_expr, group_name, is_lower_better
    ("payloadChart",   "4G Payload",             "MB",             "4G Payload (MB)",  None, None,
     'SUM("4g_payload_mb")',             "Productivity", False),
    ("volteChart",     "VoLTE Traffic",         "Erl",            "VoLTE (Erl)",  None, None,
     "SUM(volte_traffic)",                "Productivity", False),
    ("availChart",     "Availability",          "%",              "Availability (%)", None, 100,
     'CASE WHEN SUM(avail_denum)>0 THEN ROUND((SUM(avail_num)/SUM(avail_denum)*100)::numeric,2) ELSE NULL END',    "Availability", False),
    ("maxRrcChart",    "Max RRC User",          "Users",          "Max RRC Users",  None, None,
     "SUM(max_rrc_conn_user)",            "User", False),
    ("activeUserChart","Active User",           "Users",          "Active Users",  None, None,
     "SUM(new_active_users)",            "User", False),
    ("cssrChart",      "CSSR",                  "%",              "CSSR (%)", None, 100,
     'CASE WHEN SUM(cssr_denum)>0 THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),
    ("rrcSrChart",     "RRC SR",                "%",              "RRC SR (%)", None, 100,
     'CASE WHEN SUM(rrc_setup_denum)>0 THEN ROUND((SUM(rrc_setup_num)/SUM(rrc_setup_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),
    ("erabSrChart",    "ERAB SR",                "%",              "ERAB SR (%)", None, 100,
     'CASE WHEN SUM(erab_setup_denum)>0 THEN ROUND((SUM(erab_setup_num)/SUM(erab_setup_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),
    ("sdrChart",       "SDR",                   "%",              "SDR (%)",  None, None,
     'CASE WHEN SUM(sdr_denum)>0 THEN ROUND((SUM(sdr_num)/SUM(sdr_denum)*100)::numeric,2) ELSE NULL END', "Retainability", True),
    ("dlPrbChart",     "DL PRB",                "%",              "DL PRB (%)", 0, 100,
     'CASE WHEN SUM(dl_prb_util_denum)>0 THEN ROUND((SUM(dl_prb_util_num)/SUM(dl_prb_util_denum)*100)::numeric,2) ELSE NULL END', "Capacity", True),
    ("ulPrbChart",     "UL PRB",                "%",              "UL PRB (%)", 0, 100,
     'CASE WHEN SUM(ul_prb_util_denum)>0 THEN ROUND((SUM(ul_prb_util_num)/SUM(ul_prb_util_denum)*100)::numeric,2) ELSE NULL END', "Capacity", True),
    ("dlThpChart",     "User DL Throughput",    "Mbps",           "DL Thp (Mbps)",  None, None,
     'CASE WHEN SUM(user_dl_thp_denum)>0 THEN ROUND((SUM(user_dl_thp_num)/SUM(user_dl_thp_denum)/1000.0)::numeric,2) ELSE NULL END', "Integrity", False),
    ("ulThpChart",     "User UL Throughput",    "Mbps",           "UL Thp (Mbps)",  None, None,
     'CASE WHEN SUM(user_ul_thp_denum)>0 THEN ROUND((SUM(user_ul_thp_num)/SUM(user_ul_thp_denum)/1000.0)::numeric,2) ELSE NULL END', "Integrity", False),
    ("ifhoChart",      "IFHO",                  "%",              "IFHO (%)", None, 100,
     'CASE WHEN SUM(ifho_denum)>0 THEN ROUND((SUM(ifho_num)/SUM(ifho_denum)*100)::numeric,2) ELSE NULL END', "Mobility", False),
    ("seChart",        "Spectral Efficiency",    "",               "SE",  None, None,
     'CASE WHEN SUM(se_v3_denum)>0 THEN ROUND((SUM(se_v3_num)/SUM(se_v3_denum))::numeric,2) ELSE NULL END', "Quality", False),
    ("cqiChart",       "CQI",                  "",               "CQI", 0, None,
     'CASE WHEN SUM(denum_average_cqi)>0 THEN ROUND((SUM(num_average_cqi)/SUM(denum_average_cqi))::numeric,2) ELSE NULL END', "Quality", False),
    ("csfbChart",       "CSFB",                  "%",              "CSFB (%)", None, 100,
     'CASE WHEN SUM(csfb_denum)>0 THEN ROUND((SUM(csfb_num)/SUM(csfb_denum)*100)::numeric,2) ELSE NULL END', "Others", False),
    ("s1SrChart",      "S1 SR",                  "%",              "S1 SR (%)", None, 100,
     'CASE WHEN SUM(s1_signaling_sr_denum)>0 THEN ROUND((SUM(s1_signaling_sr_num)/SUM(s1_signaling_sr_denum)*100)::numeric,2) ELSE NULL END', "Others", False),
]

KPI_GROUPS = ["Productivity","Availability","User","Accessibility","Retainability","Capacity","Integrity","Mobility","Quality","Others"]

@kpi4g_hourly_sector.route("/kpi_4g_hourly_sector")
@login_required
@viewer_blocked
def kpi_4g_hourly_sector_view():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")
    sel_kpis  = request.args.getlist("kpi")

    if not sel_kpis:
        sel_kpis = ["payloadChart", "cssrChart", "volteChart", "activeUserChart"]

    KPI_DEFS = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]

    site_paste_raw = request.args.get("site_paste", "")
    if site_paste_raw:
        extra = [s.strip() for s in site_paste_raw.replace("\n", ",").split(",") if s.strip()]
        for s in extra:
            if s not in sel_sites:
                sel_sites.append(s)

    chart_labels = []
    chart_data = defaultdict(lambda: defaultdict(dict)) # kpi_id -> legend_name -> datehour -> value
    
    sites_list = []
    last_update = None

    try:
        sites_list, _ = get_site_list_4g()
    except Exception:
        sites_list = []

    if from_date and to_date and sel_sites:
        conn = None
        cur = None
        try:
            with db_query() as (conn, cur):

                try:
                    cur.execute('SELECT MAX(datehour::date) FROM "4g_kpi_zte"')
                    raw_last = cur.fetchone()
                    last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
                except Exception:
                    last_update = None

                kpi_selects = ", ".join([f"{k[6]} AS {k[0]}" for k in KPI_DEFS])
            
                query = f"""
                    SELECT
                        datehour,
                        siteid,
                        cell,
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
                            ELSE NULL
                        END AS band,
                        {kpi_selects}
                    FROM "4g_kpi_zte"
                    WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                    GROUP BY datehour, siteid, cell, sector, band
                    ORDER BY datehour, siteid, cell, sector, band
                """
            
                cur.execute(query, [from_date, to_date, sel_sites])
            
                hours_seen = set()
                for row in cur.fetchall():
                    dh = row[0].strftime("%Y-%m-%d %H:%M")
                    siteid = row[1]
                    cell = str(row[2]).split('.')[0] if row[2] is not None else ""
                    sector = row[3]
                    band = row[4]
                
                    # legend format: {siteid} S{sector}|{band}-{cell}
                    band_str = band if band else "Unknown"
                    legend_name = f"{siteid} S{sector}|{band_str}-{cell}"
                                
                
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
        except psycopg2.errors.ConnectionDoesNotExist:
            flash("Database server unreachable. Please try again later.", "warning")
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")

    # Serialize chart_data dict properly for JS
    return _no_cache(make_response(render_template(
        "kpi_4g_hourly_sector.html",
        username=session.get("username", "User"),
        sites_list=sites_list,
        sel_sites=sel_sites,
        sel_kpis=sel_kpis,
        from_date=from_date,
        to_date=to_date,
        last_update=last_update,
        chart_labels=chart_labels,
        chart_data=chart_data,
        kpi_defs=[(k[0], k[1], k[2], k[3], k[4], k[5], k[7], k[8]) for k in ALL_KPI_DEFS],
        kpi_group_map={k[0]: k[7] for k in ALL_KPI_DEFS},
        kpi_groups=KPI_GROUPS,
    )))
