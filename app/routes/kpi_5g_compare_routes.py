"""5G KPI Hourly Compare Routes — /kpi_5g_hourly/compare (before/after comparison)"""
from flask import Blueprint, render_template, request, session, flash, make_response
from app.db.db_webapp import get_postgres_connection, get_site_list_5g
from ._utils import viewer_blocked, login_required, _no_cache, json_response, db_query
import psycopg2
import psycopg2.errors

kpi5g_compare = Blueprint("kpi5g_compare", __name__)

@kpi5g_compare.route("/api/kpi_5g_hourly/compare/last_update")
@login_required
@viewer_blocked
def api_kpi_5g_compare_last_update():
    try:
        with db_query() as (conn, cur):
            cur.execute('SELECT MAX(datehour::date) FROM "5g_kpi_zte"')
            raw = cur.fetchone()
            last_update = raw[0].strftime('%Y-%m-%d') if raw and raw[0] else None
            return json_response({"last_update": last_update})
    except Exception as e:
        return json_response({"error": str(e)}, 500)


@kpi5g_compare.route("/kpi_5g_hourly/compare")
@login_required
@viewer_blocked
def kpi_5g_hourly_compare():
    from_date_b = request.args.get("from_date_before", "")
    to_date_b   = request.args.get("to_date_before",   "")
    from_date_a = request.args.get("from_date_after",  "")
    to_date_a   = request.args.get("to_date_after",    "")
    sel_sites   = request.args.getlist("site")

    site_paste_raw = request.args.get("site_paste", "")
    if site_paste_raw:
        extra = [s.strip() for s in site_paste_raw.replace("\n", ",").split(",") if s.strip()]
        for s in extra:
            if s not in sel_sites:
                sel_sites.append(s)

    ALL_KPI_DEFS = [
        # chart_id, title, unit, y_label, y_min, y_max, sql_expr, group_name, is_lower_better
        ("payloadChart",   "Payload",                "GB",   None,  None, None,
         'ROUND((SUM("5g_payload_mb") / 1024.0)::numeric, 3)', "Productivity", False),
        ("dlPayloadChart", "DL Payload",             "GB",   None,  None, None,
         'ROUND((SUM(payload_dl_mbyte_xhj) / 1024.0)::numeric, 3)', "Productivity", False),
        ("ulPayloadChart", "UL Payload",             "GB",   None,  None, None,
         'ROUND((SUM(payload_ul_mbyte_xhj) / 1024.0)::numeric, 3)', "Productivity", False),
        ("availChart",     "Availability",           "%",    None, None, 100,
         'CASE WHEN SUM(denum_availability_xhj) > 0 THEN ROUND((SUM(num_availability_xhj) / SUM(denum_availability_xhj) * 100.0)::numeric, 2) ELSE NULL END', "Availability", False),
        ("rrcChart",       "Max RRC User",           "Users",None,  None, None,
         'SUM(max_rrc_user_number_xhj)', "User", False),
        ("activeUserChart","NR Active User",         "Users",None,  None, None,
         'SUM(nr_active_user_number)', "User", False),
        ("accessibilityChart", "NR Accessibility",   "%",    None, None, 100,
         'CASE WHEN SUM(number_of_sn_add_requests) > 0 THEN ROUND((SUM(num_sn_setup_success_rate_xhj) / SUM(number_of_sn_add_requests) * 100.0)::numeric, 2) ELSE NULL END', "Accessibility", False),
        ("retainabilityChart", "NR Retainability",   "%",    None, None, 100,
         'CASE WHEN SUM(denum_nr_retainability_xhj) > 0 THEN ROUND((100.0 - (SUM(num_nr_retainability_xhj) / SUM(denum_nr_retainability_xhj) * 100.0))::numeric, 2) ELSE NULL END', "Retainability", False),
        ("mobilityChart",  "NR Mobility SR",         "%",    None, None, 100,
         'CASE WHEN SUM(nr_mobility_success_rate_denum) > 0 THEN ROUND((SUM(nr_mobility_success_rate_num) / SUM(nr_mobility_success_rate_denum) * 100.0)::numeric, 2) ELSE NULL END', "Mobility", False),
        ("dlPrbChart",     "DL PRB",                 "%",    None, 0, 100,
         'CASE WHEN SUM(denum_prb_utilization_dl_xhj) > 0 THEN ROUND((SUM(num_prb_utilization_dl_xhj) / SUM(denum_prb_utilization_dl_xhj) * 100.0)::numeric, 2) ELSE NULL END', "Capacity", False),
        ("ulPrbChart",     "UL PRB",                 "%",    None, 0, 100,
         'CASE WHEN SUM(denum_prb_utilization_ul_xhj) > 0 THEN ROUND((SUM(num_prb_utilization_ul_xhj) / SUM(denum_prb_utilization_ul_xhj) * 100.0)::numeric, 2) ELSE NULL END', "Capacity", False),
        ("cellDlThpChart", "Cell DL Thp",            "Mbps", None, 0, None,
         'ROUND((AVG(cell_throughput_dl_xhj))::numeric, 2)', "Integrity", False),
        ("cellUlThpChart", "Cell UL Thp",            "Mbps", None, 0, None,
         'ROUND((AVG(cell_throughput_ul_xhj) )::numeric, 2)', "Integrity", False),
        ("dlThpChart",     "User DL Thp",            "Mbps", None, None, None,
         'CASE WHEN SUM(denum_user_throughput_dl_xhj) > 0 THEN ROUND((SUM(num_user_throughput_dl_xhj) / SUM(denum_user_throughput_dl_xhj) )::numeric, 2) ELSE NULL END', "Integrity", False),
        ("ulThpChart",     "User UL Thp",            "Mbps", None, None, None,
         'CASE WHEN SUM(denum_user_throughput_ul_xhj) > 0 THEN ROUND((SUM(num_user_throughput_ul_xhj) / SUM(denum_user_throughput_ul_xhj) )::numeric, 2) ELSE NULL END', "Integrity", False),
        ("seChart",        "SE",                     "",     None, 0, None,
         'CASE WHEN SUM(spectrum_eff_bps_lw_denum) > 0 THEN ROUND((SUM(spectrum_eff_bps_lw_num) / SUM(spectrum_eff_bps_lw_denum))::numeric, 4) ELSE NULL END', "Quality", False),
        ("cqiChart",       "CQI",                    "",     None, 0, None,
         'CASE WHEN SUM(denum_average_cqi_xhj) > 0 THEN ROUND((SUM(num_average_cqi_xhj) / SUM(denum_average_cqi_xhj))::numeric, 2) ELSE NULL END', "Quality", False),
        ("ulIntChart",     "UL Interference",        "dBm",  None, -120, -90,
         'ROUND(AVG(avg_uplink_interference_xhj)::numeric, 2)', "Quality", True),
        ("plChart",        "Packet Loss",            "%",    None, 0, None,
         'CASE WHEN SUM(denum_packet_loss_xhj) > 0 THEN ROUND((SUM(num_packet_loss_xhj) / SUM(denum_packet_loss_xhj) * 100.0)::numeric, 2) ELSE NULL END', "Transport", True),
        ("latDlChart",     "Latency DL",             "ms",   None, 0, None,
         'CASE WHEN SUM(denum_latency_dl_xhj) > 0 THEN ROUND((SUM(num_latency_dl_xhj) / SUM(denum_latency_dl_xhj))::numeric, 2) ELSE NULL END', "Transport", True),
        ("latUlChart",     "Latency UL",             "ms",   None, 0, None,
         'CASE WHEN SUM(denum_latency_ul_xhj) > 0 THEN ROUND((SUM(num_latency_ul_xhj) / SUM(denum_latency_ul_xhj))::numeric, 2) ELSE NULL END', "Transport", True),
    ]

    KPI_GROUPS = ["Productivity", "Availability", "User", "Accessibility", "Retainability", "Mobility", "Capacity", "Integrity", "Quality", "Transport"]

    sel_kpis = request.args.getlist("kpi")
    if not sel_kpis:
        sel_kpis = [k[0] for k in ALL_KPI_DEFS]
        
    KPI_DEFS = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]

    chart_labels  = []
    compare_data  = {}
    site_compare_table = {}
    agg_data      = {}

    sites_list = []
    last_update = None
    active_sites = 0

    try:
        sites_list, _ = get_site_list_5g()
        active_sites = len(sites_list)
    except Exception:
        sites_list = []

    if from_date_b and to_date_b and from_date_a and to_date_a and sel_sites and KPI_DEFS:
        conn = None
        cur = None
        try:
            with db_query() as (conn, cur):

                try:
                    cur.execute('SELECT MAX(datehour::date) FROM "5g_kpi_zte"')
                    raw_last = cur.fetchone()
                    last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
                except Exception:
                    last_update = None

                HR_FMT = "'HH24:00'"
                kpi_selects = ", ".join([f"{k[6]} AS {k[0]}" for k in KPI_DEFS])

                # 1. Get Cluster Hourly Trends
                cur.execute(f"""
                    SELECT TO_CHAR(datehour, {HR_FMT}) AS hr, {kpi_selects}
                    FROM "5g_kpi_zte"
                    WHERE datehour::date BETWEEN %s AND %s AND siteid = ANY(%s)
                    GROUP BY hr ORDER BY hr
                """, [from_date_b, to_date_b, sel_sites])
                before_hourly = cur.fetchall()

                cur.execute(f"""
                    SELECT TO_CHAR(datehour, {HR_FMT}) AS hr, {kpi_selects}
                    FROM "5g_kpi_zte"
                    WHERE datehour::date BETWEEN %s AND %s AND siteid = ANY(%s)
                    GROUP BY hr ORDER BY hr
                """, [from_date_a, to_date_a, sel_sites])
                after_hourly = cur.fetchall()

                chart_labels = sorted(list(set([r[0] for r in before_hourly] + [r[0] for r in after_hourly])))
            
                before_hourly_map = {r[0]: r[1:] for r in before_hourly}
                after_hourly_map = {r[0]: r[1:] for r in after_hourly}

                for idx, kpi in enumerate(KPI_DEFS):
                    chart_id = kpi[0]
                    compare_data[chart_id] = {"before": [], "after": []}
                    for hr in chart_labels:
                        b_val = before_hourly_map.get(hr)
                        a_val = after_hourly_map.get(hr)
                        b = round(float(b_val[idx]), 2) if b_val and b_val[idx] is not None else None
                        a = round(float(a_val[idx]), 2) if a_val and a_val[idx] is not None else None
                        compare_data[chart_id]["before"].append(b)
                        compare_data[chart_id]["after"].append(a)

                # 2. Get Site Level Aggregates
                cur.execute(f"""
                    SELECT siteid, {kpi_selects}
                    FROM "5g_kpi_zte"
                    WHERE datehour::date BETWEEN %s AND %s AND siteid = ANY(%s)
                    GROUP BY siteid
                """, [from_date_b, to_date_b, sel_sites])
                before_sites = {r[0]: r[1:] for r in cur.fetchall()}

                cur.execute(f"""
                    SELECT siteid, {kpi_selects}
                    FROM "5g_kpi_zte"
                    WHERE datehour::date BETWEEN %s AND %s AND siteid = ANY(%s)
                    GROUP BY siteid
                """, [from_date_a, to_date_a, sel_sites])
                after_sites = {r[0]: r[1:] for r in cur.fetchall()}

                for site in sel_sites:
                    site_compare_table[site] = {}
                    b_row = before_sites.get(site)
                    a_row = after_sites.get(site)
                
                    for idx, kpi in enumerate(KPI_DEFS):
                        chart_id, title, unit, y_label, y_min, y_max, sql_expr, group_name, is_lower_better = kpi
                        b_val = round(float(b_row[idx]), 2) if b_row and b_row[idx] is not None else None
                        a_val = round(float(a_row[idx]), 2) if a_row and a_row[idx] is not None else None
                    
                        if b_val is not None and a_val is not None and b_val != 0:
                            delta = round(a_val - b_val, 2)
                            delta_pct = round((delta / abs(b_val)) * 100, 1)
                        else:
                            delta = delta_pct = None

                        site_compare_table[site][chart_id] = {
                            "before": b_val, "after": a_val,
                            "delta": delta, "delta_pct": delta_pct
                        }

                # 3. Get Cluster Network Aggregates
                cur.execute(f"""
                    SELECT {kpi_selects}
                    FROM "5g_kpi_zte"
                    WHERE datehour::date BETWEEN %s AND %s AND siteid = ANY(%s)
                """, [from_date_b, to_date_b, sel_sites])
                agg_before_row = cur.fetchone()

                cur.execute(f"""
                    SELECT {kpi_selects}
                    FROM "5g_kpi_zte"
                    WHERE datehour::date BETWEEN %s AND %s AND siteid = ANY(%s)
                """, [from_date_a, to_date_a, sel_sites])
                agg_after_row = cur.fetchone()

                for idx, kpi in enumerate(KPI_DEFS):
                    chart_id, title, unit, y_label, y_min, y_max, sql_expr, group_name, is_lower_better = kpi
                
                    b_val = round(float(agg_before_row[idx]), 2) if agg_before_row and agg_before_row[idx] is not None else None
                    a_val = round(float(agg_after_row[idx]), 2) if agg_after_row and agg_after_row[idx] is not None else None

                    if b_val is not None and a_val is not None and b_val != 0:
                        delta = round(a_val - b_val, 2)
                        delta_pct = round((delta / abs(b_val)) * 100, 1)
                    else:
                        delta = delta_pct = None

                    agg_data[chart_id] = {
                        "before": b_val, "after": a_val,
                        "delta": delta, "delta_pct": delta_pct,
                        "title": title, "unit": unit, "group": group_name, "is_lower_better": is_lower_better
                    }
        except psycopg2.OperationalError:
            flash("Database connection failed. Please try again.", "warning")
        except psycopg2.errors.QueryCanceled:
            flash("Query timed out. Please try a shorter date range.", "warning")
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")

    return _no_cache(make_response(render_template(
        "kpi_5g_hourly_compare.html",
        username=session.get("username", "User"),
        active_sites=active_sites,
        sites_list=sites_list,
        sel_sites=sel_sites,
        from_date_before=from_date_b,
        to_date_before=to_date_b,
        from_date_after=from_date_a,
        to_date_after=to_date_a,
        last_update=last_update,
        chart_labels=chart_labels,
        compare_data=compare_data,
        site_compare_table=site_compare_table,
        agg_data=agg_data,
        kpi_defs=[(k[0],k[1],k[2],k[3],k[4],k[5],k[7],k[8]) for k in KPI_DEFS],
        kpi_group_map={k[0]: k[7] for k in ALL_KPI_DEFS},
        all_kpis=ALL_KPI_DEFS,
        sel_kpis=sel_kpis,
        kpi_groups=KPI_GROUPS
    )))
