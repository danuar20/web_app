"""5G KPI Hourly Sector Routes — /kpi_5g_hourly_sector (sector/cell level view)"""
from flask import Blueprint, render_template, request, session, flash, make_response
from app.db.db_webapp import get_postgres_connection, get_site_list_5g
from ._utils import login_required, _no_cache, json_response
import psycopg2
import psycopg2.errors
from collections import defaultdict

kpi5g_hourly_sector = Blueprint("kpi5g_hourly_sector", __name__)

@kpi5g_hourly_sector.route("/api/kpi_5g_hourly_sector/last_update")
@login_required
def api_kpi_5g_hourly_sector_last_update():
    """Lightweight endpoint to get last update timestamp without full KPI query"""
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute('SELECT MAX(datehour) FROM "5g_kpi_zte"')
        raw = cur.fetchone()
        cur.close()
        conn.close()
        last_update = raw[0].strftime('%Y-%m-%d %H:%M') if raw and raw[0] else None
        return json_response({"last_update": last_update})
    except Exception as e:
        return json_response({"error": str(e)}, 500)


@kpi5g_hourly_sector.route("/kpi_5g_hourly_sector")
@login_required
def kpi_5g_hourly_sector():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")

    site_paste_raw = request.args.get("site_paste", "")
    if site_paste_raw:
        extra = [s.strip() for s in site_paste_raw.replace("\\n", ",").split(",") if s.strip()]
        for s in extra:
            if s not in sel_sites:
                sel_sites.append(s)

    ALL_KPI_DEFS = [
        # chart_id, title, unit, y_label, y_min, y_max, sql_expr, is_lower_better
        ("payloadChart",   "Payload",                "GB",   None,  None, None,
         'ROUND((SUM("5g_payload_mb") / 1024.0)::numeric, 3)', False),
        ("dlPayloadChart", "DL Payload",             "GB",   None,  None, None,
         'ROUND((SUM(payload_dl_mbyte_xhj) / 1024.0)::numeric, 3)', False),
        ("ulPayloadChart", "UL Payload",             "GB",   None,  None, None,
         'ROUND((SUM(payload_ul_mbyte_xhj) / 1024.0)::numeric, 3)', False),
        ("availChart",     "Availability",           "%",    None, None, 100,
         'CASE WHEN SUM(denum_availability_xhj) > 0 THEN ROUND((SUM(num_availability_xhj) / SUM(denum_availability_xhj) * 100.0)::numeric, 2) ELSE NULL END', False),
        ("rrcChart",       "Max RRC User",           "Users",None,  None, None,
         'SUM(max_rrc_user_number_xhj)', False),
        ("activeUserChart","NR Active User",         "Users",None,  None, None,
         'SUM(nr_active_user_number)', False),
        ("accessibilityChart", "NR Accessibility",   "%",    None, None, 100,
         'CASE WHEN SUM(number_of_sn_add_requests) > 0 THEN ROUND((SUM(num_sn_setup_success_rate_xhj) / SUM(number_of_sn_add_requests) * 100.0)::numeric, 2) ELSE NULL END', False),
        ("retainabilityChart", "NR Retainability",   "%",    None, None, 100,
         'CASE WHEN SUM(denum_nr_retainability_xhj) > 0 THEN ROUND((100.0 - (SUM(num_nr_retainability_xhj) / SUM(denum_nr_retainability_xhj) * 100.0))::numeric, 2) ELSE NULL END', False),
        ("mobilityChart",  "NR Mobility SR",         "%",    None, None, 100,
         'CASE WHEN SUM(nr_mobility_success_rate_denum) > 0 THEN ROUND((SUM(nr_mobility_success_rate_num) / SUM(nr_mobility_success_rate_denum) * 100.0)::numeric, 2) ELSE NULL END', False),
        ("dlPrbChart",     "DL PRB",                 "%",    None, 0, 100,
         'CASE WHEN SUM(denum_prb_utilization_dl_xhj) > 0 THEN ROUND((SUM(num_prb_utilization_dl_xhj) / SUM(denum_prb_utilization_dl_xhj) * 100.0)::numeric, 2) ELSE NULL END', False),
        ("ulPrbChart",     "UL PRB",                 "%",    None, 0, 100,
         'CASE WHEN SUM(denum_prb_utilization_ul_xhj) > 0 THEN ROUND((SUM(num_prb_utilization_ul_xhj) / SUM(denum_prb_utilization_ul_xhj) * 100.0)::numeric, 2) ELSE NULL END', False),
        ("cellDlThpChart", "Cell DL Thp",            "Mbps", None, 0, None,
         'ROUND((AVG(cell_throughput_dl_xhj) / 1000.0)::numeric, 2)', False),
        ("cellUlThpChart", "Cell UL Thp",            "Mbps", None, 0, None,
         'ROUND((AVG(cell_throughput_ul_xhj) / 1000.0)::numeric, 2)', False),
        ("dlThpChart",     "User DL Thp",            "Mbps", None, None, None,
         'CASE WHEN SUM(denum_user_throughput_dl_xhj) > 0 THEN ROUND((SUM(num_user_throughput_dl_xhj) / SUM(denum_user_throughput_dl_xhj) * 100.0 / 1000.0)::numeric, 2) ELSE NULL END', False),
        ("ulThpChart",     "User UL Thp",            "Mbps", None, None, None,
         'CASE WHEN SUM(denum_user_throughput_ul_xhj) > 0 THEN ROUND((SUM(num_user_throughput_ul_xhj) / SUM(denum_user_throughput_ul_xhj) * 100.0 / 1000.0)::numeric, 2) ELSE NULL END', False),
        ("seChart",        "SE",                     "",     None, 0, None,
         'CASE WHEN SUM(spectrum_eff_bps_lw_denum) > 0 THEN ROUND((SUM(spectrum_eff_bps_lw_num) / SUM(spectrum_eff_bps_lw_denum))::numeric, 4) ELSE NULL END', False),
        ("cqiChart",       "CQI",                    "",     None, 0, None,
         'CASE WHEN SUM(denum_average_cqi_xhj) > 0 THEN ROUND((SUM(num_average_cqi_xhj) / SUM(denum_average_cqi_xhj))::numeric, 2) ELSE NULL END', False),
        ("ulIntChart",     "UL Interference",        "dBm",  None, -120, -90,
         'ROUND(AVG(avg_uplink_interference_xhj)::numeric, 2)', True),
        ("plChart",        "Packet Loss",            "%",    None, 0, None,
         'CASE WHEN SUM(denum_packet_loss_xhj) > 0 THEN ROUND((SUM(num_packet_loss_xhj) / SUM(denum_packet_loss_xhj) * 100.0)::numeric, 2) ELSE NULL END', True),
        ("latDlChart",     "Latency DL",             "ms",   None, 0, None,
         'CASE WHEN SUM(denum_latency_dl_xhj) > 0 THEN ROUND((SUM(num_latency_dl_xhj) / SUM(denum_latency_dl_xhj))::numeric, 2) ELSE NULL END', True),
        ("latUlChart",     "Latency UL",             "ms",   None, 0, None,
         'CASE WHEN SUM(denum_latency_ul_xhj) > 0 THEN ROUND((SUM(num_latency_ul_xhj) / SUM(denum_latency_ul_xhj))::numeric, 2) ELSE NULL END', True),
    ]

    sel_kpis = request.args.getlist("kpi")
    if not sel_kpis:
        sel_kpis = [k[0] for k in ALL_KPI_DEFS]
        
    KPI_DEFS = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]

    chart_labels = []
    chart_data = defaultdict(lambda: defaultdict(dict)) # kpi_id -> legend_name -> datehour -> value
    sites_list = []
    last_update = None
    active_sites = 0

    try:
        sites_list, _ = get_site_list_5g()
        active_sites = len(sites_list)
    except Exception:
        sites_list = []

    if from_date and to_date and sel_sites and KPI_DEFS:
        conn = None
        cur = None
        try:
            conn = get_postgres_connection()
            cur = conn.cursor()

            try:
                cur.execute('SELECT MAX(datehour) FROM "5g_kpi_zte"')
                raw_last = cur.fetchone()
                last_update = raw_last[0].strftime('%Y-%m-%d %H:%M') if raw_last and raw_last[0] else None
            except Exception:
                last_update = None

            kpi_selects = ", ".join([f"{k[6]} AS {k[0]}" for k in KPI_DEFS])

            query = f"""
                SELECT
                    datehour,
                    siteid,
                    cellid,
                    CASE
                        WHEN LENGTH(cellid::text) > 2 AND RIGHT(cellid::text, 1) = '5' THEN SUBSTRING(cellid::text FROM 2 FOR 1)
                        WHEN LENGTH(cellid::text) > 2 THEN LEFT(cellid::text, 2)
                        ELSE LEFT(cellid::text, 1)
                    END AS sector,
                    {kpi_selects}
                FROM "5g_kpi_zte"
                WHERE datehour::date BETWEEN %s::date AND %s::date AND siteid = ANY(%s)
                GROUP BY datehour, siteid, cellid, sector
                ORDER BY datehour, siteid, cellid, sector
            """

            cur.execute(query, [from_date, to_date, sel_sites])
            
            hours_seen = set()
            for row in cur.fetchall():
                dh = row[0].strftime("%Y-%m-%d %H:%M")
                siteid = row[1]
                cellid = str(row[2]).replace(".0", "") if row[2] is not None else ""
                sector = row[3]
                
                legend_name = f"{siteid} S{sector} - {cellid}"
                
                hours_seen.add(dh)
                
                for idx, k in enumerate(KPI_DEFS):
                    val = row[idx+4]
                    chart_data[k[0]][legend_name][dh] = round(float(val), 2) if val is not None else None

            chart_labels = sorted(list(hours_seen))

            for k in KPI_DEFS:
                kpi_id = k[0]
                for leg in chart_data[kpi_id]:
                    ordered_data = []
                    for h in chart_labels:
                        ordered_data.append(chart_data[kpi_id][leg].get(h, None))
                    chart_data[kpi_id][leg] = ordered_data

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

    formatted_chart_data = {k: dict(v) for k, v in chart_data.items()}

    return _no_cache(make_response(render_template(
        "kpi_5g_hourly_sector.html",
        username=session.get("username", "User"),
        active_sites=active_sites,
        sites_list=sites_list,
        sel_sites=sel_sites,
        from_date=from_date,
        to_date=to_date,
        last_update=last_update,
        chart_labels=chart_labels,
        chart_data=formatted_chart_data,
        kpi_defs=[(k[0],k[1],k[2],k[3],k[4],k[5],k[7]) for k in KPI_DEFS],
        all_kpis=ALL_KPI_DEFS,
        sel_kpis=sel_kpis
    )))
