"""4G KPI Hourly Compare Routes — /kpi_4g_hourly/compare (before/after comparison)"""
from flask import Blueprint, render_template, request, session, flash, make_response
from app.db.db_webapp import get_postgres_connection, get_site_list_4g
from ._utils import login_required, _no_cache, json_response
import psycopg2
import psycopg2.errors

kpi4g_compare = Blueprint("kpi4g_compare", __name__)


# ── Get last update timestamp (async endpoint) ────────────────────────────────
@kpi4g_compare.route("/api/kpi_4g_hourly/compare/last_update")
@login_required
def api_kpi_4g_compare_last_update():
    """Lightweight endpoint to get last update timestamp without full KPI query"""
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute('SELECT MAX(datehour::date) FROM "4g_kpi_zte"')
        raw = cur.fetchone()
        cur.close()
        conn.close()
        last_update = raw[0].strftime('%Y-%m-%d') if raw and raw[0] else None
        return json_response({"last_update": last_update})
    except Exception as e:
        return json_response({"error": str(e)}, 500)


# ── 4G KPI Hourly Comparison ────────────────────────────────────────────────
@kpi4g_compare.route("/kpi_4g_hourly/compare")
@login_required
def kpi_4g_hourly_compare():
    from_date_b = request.args.get("from_date_before", "")
    to_date_b   = request.args.get("to_date_before",   "")
    from_date_a = request.args.get("from_date_after",  "")
    to_date_a   = request.args.get("to_date_after",    "")
    sel_sites   = request.args.getlist("site")

    # Support site IDs pasted from CSV — comma/newline separated, deduplicate
    site_paste_raw = request.args.get("site_paste", "")
    if site_paste_raw:
        extra = [s.strip() for s in site_paste_raw.replace("\n", ",").split(",") if s.strip()]
        for s in extra:
            if s not in sel_sites:
                sel_sites.append(s)

    KPI_DEFS = [
        ("payloadChart",   "4G Payload",             "GB",             None,  None, None,
         'SUM("4g_payload_mb")/1024.0',             'SUM("4g_payload_mb")/1024.0',             "Productivity"),
        ("volteChart",     "VoLTE Traffic",         "Erl",            None,  None, None,
         "SUM(volte_traffic)",                "SUM(volte_traffic)",                "Productivity"),
        ("availChart",     "Availability",          "Avail (%)",      None, 95, 100,
         'CASE WHEN SUM(avail_denum)>0 THEN ROUND((SUM(avail_num)/SUM(avail_denum)*100)::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(avail_denum)>0 THEN ROUND((SUM(avail_num)/SUM(avail_denum)*100)::numeric,2) ELSE NULL END',    "Availability"),
        ("maxRrcChart",    "Max RRC User",          "Users",          None,  None, None,
         "SUM(max_rrc_conn_user)",            "SUM(max_rrc_conn_user)",            "User"),
        ("activeUserChart","Active User",           "Users",          None,  None, None,
         "SUM(new_active_users)",             "SUM(new_active_users)",            "User"),
        ("cssrChart",      "CSSR",                  "CSSR (%)",       None, 85, 100,
         'CASE WHEN SUM(cssr_denum)>0 THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100)::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(cssr_denum)>0 THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100)::numeric,2) ELSE NULL END', "Accessibility"),
        ("rrcSrChart",     "RRC SR",                "RRC SR (%)",     None, 85, 100,
         'CASE WHEN SUM(rrc_setup_denum)>0 THEN ROUND((SUM(rrc_setup_num)/SUM(rrc_setup_denum)*100)::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(rrc_setup_denum)>0 THEN ROUND((SUM(rrc_setup_num)/SUM(rrc_setup_denum)*100)::numeric,2) ELSE NULL END', "Accessibility"),
        ("erabSrChart",    "ERAB SR",                "ERAB SR (%)",    None, 85, 100,
         'CASE WHEN SUM(erab_setup_denum)>0 THEN ROUND((SUM(erab_setup_num)/SUM(erab_setup_denum)*100)::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(erab_setup_denum)>0 THEN ROUND((SUM(erab_setup_num)/SUM(erab_setup_denum)*100)::numeric,2) ELSE NULL END', "Accessibility"),
        ("sdrChart",       "SDR",                   "SDR (%)",        None,  None, None,
         'CASE WHEN SUM(sdr_denum)>0 THEN ROUND((SUM(sdr_num)/SUM(sdr_denum)*100)::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(sdr_denum)>0 THEN ROUND((SUM(sdr_num)/SUM(sdr_denum)*100)::numeric,2) ELSE NULL END', "Retainability"),
        ("dlPrbChart",     "DL PRB",                "DL PRB (%)",     None, 0, 100,
         'CASE WHEN SUM(dl_prb_util_denum)>0 THEN ROUND((SUM(dl_prb_util_num)/SUM(dl_prb_util_denum)*100)::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(dl_prb_util_denum)>0 THEN ROUND((SUM(dl_prb_util_num)/SUM(dl_prb_util_denum)*100)::numeric,2) ELSE NULL END', "Capacity"),
        ("ulPrbChart",     "UL PRB",                "UL PRB (%)",     None, 0, 100,
         'CASE WHEN SUM(ul_prb_util_denum)>0 THEN ROUND((SUM(ul_prb_util_num)/SUM(ul_prb_util_denum)*100)::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(ul_prb_util_denum)>0 THEN ROUND((SUM(ul_prb_util_num)/SUM(ul_prb_util_denum)*100)::numeric,2) ELSE NULL END', "Capacity"),
        ("dlThpChart",     "User DL Throughput",    "DL Thp (Mbps)",  None,  None, None,
         'CASE WHEN SUM(user_dl_thp_denum)>0 THEN ROUND((SUM(user_dl_thp_num)/SUM(user_dl_thp_denum)/1000)::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(user_dl_thp_denum)>0 THEN ROUND((SUM(user_dl_thp_num)/SUM(user_dl_thp_denum)/1000)::numeric,2) ELSE NULL END', "Integrity"),
        ("ulThpChart",     "User UL Throughput",    "UL Thp (Mbps)",  None,  None, None,
         'CASE WHEN SUM(user_ul_thp_denum)>0 THEN ROUND((SUM(user_ul_thp_num)/SUM(user_ul_thp_denum)/1000)::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(user_ul_thp_denum)>0 THEN ROUND((SUM(user_ul_thp_num)/SUM(user_ul_thp_denum)/1000)::numeric,2) ELSE NULL END', "Integrity"),
        ("ifhoChart",      "IFHO",                  "IFHO (%)",       None, 90, 100,
         'CASE WHEN SUM(ifho_denum)>0 THEN ROUND((SUM(ifho_num)/SUM(ifho_denum)*100)::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(ifho_denum)>0 THEN ROUND((SUM(ifho_num)/SUM(ifho_denum)*100)::numeric,2) ELSE NULL END', "Mobility"),
        ("seChart",        "Spectral Efficiency",    "SE",             None,  None, None,
         'CASE WHEN SUM(se_v3_denum)>0 THEN ROUND((SUM(se_v3_num)/SUM(se_v3_denum))::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(se_v3_denum)>0 THEN ROUND((SUM(se_v3_num)/SUM(se_v3_denum))::numeric,2) ELSE NULL END', "Quality"),
        ("cqiChart",       "CQI",                  "CQI",            None, 0, 15,
         'CASE WHEN SUM(denum_average_cqi)>0 THEN ROUND((SUM(num_average_cqi)/SUM(denum_average_cqi))::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(denum_average_cqi)>0 THEN ROUND((SUM(num_average_cqi)/SUM(denum_average_cqi))::numeric,2) ELSE NULL END', "Quality"),
        ("csfbChart",       "CSFB",                  "CSFB (%)",       None, 85, 100,
         'CASE WHEN SUM(csfb_denum)>0 THEN ROUND((SUM(csfb_num)/SUM(csfb_denum)*100)::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(csfb_denum)>0 THEN ROUND((SUM(csfb_num)/SUM(csfb_denum)*100)::numeric,2) ELSE NULL END', "Others"),
        ("s1SrChart",      "S1 SR",                  "S1 SR (%)",      None, 95, 100,
         'CASE WHEN SUM(s1_signaling_sr_denum)>0 THEN ROUND((SUM(s1_signaling_sr_num)/SUM(s1_signaling_sr_denum)*100)::numeric,2) ELSE NULL END',
         'CASE WHEN SUM(s1_signaling_sr_denum)>0 THEN ROUND((SUM(s1_signaling_sr_num)/SUM(s1_signaling_sr_denum)*100)::numeric,2) ELSE NULL END', "Others"),
    ]

    KPI_GROUPS = ["Productivity","Availability","User","Accessibility","Retainability","Capacity","Integrity","Mobility","Quality","Others"]

    # Initialize data structures
    chart_labels  = []
    compare_data  = {}
    compare_table = {}
    agg_data      = {}
    site_compare_table = {}
    sites_list    = []
    last_update   = None

    # Load site list from siteID_4g reference table (fast, no KPI table scan)
    # This runs outside the main try block to ensure it happens even if DB fails
    try:
        sites_list, _ = get_site_list_4g()
    except Exception:
        sites_list = []

    # Only query KPI data when user has selected all required filters
    if from_date_b and to_date_b and from_date_a and to_date_a and sel_sites:
        conn = None
        cur  = None
        try:
            conn = get_postgres_connection()
            cur  = conn.cursor()

            # Get last update timestamp
            try:
                cur.execute('SELECT MAX(datehour::date) FROM "4g_kpi_zte"')
                raw = cur.fetchone()
                last_update = raw[0].strftime('%Y-%m-%d') if raw and raw[0] else None
            except Exception:
                last_update = None

            HR_FMT = "'HH24:00'"

            # Get distinct hours for chart labels
            cur.execute(f"""
                SELECT DISTINCT hr FROM (
                    SELECT TO_CHAR(datehour, {HR_FMT}) AS hr
                    FROM "4g_kpi_zte"
                    WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                    UNION
                    SELECT TO_CHAR(datehour, {HR_FMT}) AS hr
                    FROM "4g_kpi_zte"
                    WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                ) t
                ORDER BY hr
            """, [from_date_b, to_date_b, sel_sites, from_date_a, to_date_a, sel_sites])
            chart_labels = [r[0] for r in cur.fetchall()]

            # Build compare data for each site and KPI
            for site in sel_sites:
                for kpi in KPI_DEFS:
                    chart_id, title, unit, y_label, y_min, y_max, sql_expr, sql_agg, group_name = kpi
                    compare_data.setdefault(site, {}).setdefault(chart_id, {"before": [], "after": []})

                    # Query before period
                    cur.execute(f"""
                        SELECT TO_CHAR(datehour, {HR_FMT}) AS hr, {sql_expr}
                        FROM "4g_kpi_zte"
                        WHERE date BETWEEN %s AND %s AND siteid = %s
                        GROUP BY hr ORDER BY hr
                    """, [from_date_b, to_date_b, site])
                    before_map = {str(r[0]): round(float(r[1]), 2) if r[1] is not None else None for r in cur.fetchall()}

                    # Query after period
                    cur.execute(f"""
                        SELECT TO_CHAR(datehour, {HR_FMT}) AS hr, {sql_expr}
                        FROM "4g_kpi_zte"
                        WHERE date BETWEEN %s AND %s AND siteid = %s
                        GROUP BY hr ORDER BY hr
                    """, [from_date_a, to_date_a, site])
                    after_map = {str(r[0]): round(float(r[1]), 2) if r[1] is not None else None for r in cur.fetchall()}

                    compare_data[site][chart_id]["before"] = [before_map.get(h) for h in chart_labels]
                    compare_data[site][chart_id]["after"]  = [after_map.get(h)  for h in chart_labels]

            # Build site-level compare_table (per site, per KPI)
            site_compare_table = {}
            agg_data = {}  # aggregated across all sites (for main summary table)

            for kpi in KPI_DEFS:
                chart_id, title, unit, y_label, y_min, y_max, sql_expr, sql_agg, group_name = kpi
                agg_before_vals = []
                agg_after_vals = []

                for site in sel_sites:
                    # Query before period aggregate
                    cur.execute(f"SELECT {sql_agg} FROM \"4g_kpi_zte\" WHERE date BETWEEN %s AND %s AND siteid = %s",
                                [from_date_b, to_date_b, site])
                    r_b = cur.fetchone()
                    before_val = round(float(r_b[0]), 2) if r_b and r_b[0] is not None else None

                    # Query after period aggregate
                    cur.execute(f"SELECT {sql_agg} FROM \"4g_kpi_zte\" WHERE date BETWEEN %s AND %s AND siteid = %s",
                                [from_date_a, to_date_a, site])
                    r_a = cur.fetchone()
                    after_val = round(float(r_a[0]), 2) if r_a and r_a[0] is not None else None

                    if before_val is not None and after_val is not None and before_val != 0:
                        delta = round(after_val - before_val, 2)
                        delta_pct = round((delta / abs(before_val)) * 100, 1)
                    else:
                        delta = delta_pct = None

                    site_compare_table.setdefault(site, {})[chart_id] = {
                        "before": before_val, "after": after_val,
                        "delta": delta, "delta_pct": delta_pct,
                        "title": title, "unit": unit, "group": group_name,
                    }

                    # Collect for aggregation
                    if before_val is not None:
                        agg_before_vals.append(before_val)
                    if after_val is not None:
                        agg_after_vals.append(after_val)

                # Compute aggregated values across all sites
                agg_before = round(sum(agg_before_vals) / len(agg_before_vals), 2) if agg_before_vals else None
                agg_after = round(sum(agg_after_vals) / len(agg_after_vals), 2) if agg_after_vals else None
                if agg_before is not None and agg_after is not None and agg_before != 0:
                    agg_delta = round(agg_after - agg_before, 2)
                    agg_delta_pct = round((agg_delta / abs(agg_before)) * 100, 1)
                else:
                    agg_delta = agg_delta_pct = None

                agg_data[chart_id] = {
                    "before": agg_before, "after": agg_after,
                    "delta": agg_delta, "delta_pct": agg_delta_pct,
                    "title": title, "unit": unit, "group": group_name,
                }

            cur.close()
            conn.close()

        except psycopg2.OperationalError:
            if conn: conn.rollback()
            if cur: cur.close()
            if conn: conn.close()
            conn = None; cur = None
            flash("Database connection failed.", "warning")
        except Exception as e:
            import traceback; traceback.print_exc()
            if conn:
                try: conn.rollback()
                except: pass
            if cur:
                try: cur.close()
                except: pass
            if conn:
                try: conn.close()
                except: pass
            conn = None; cur = None
            flash(f"Error: {str(e)}", "danger")

    return _no_cache(make_response(render_template(
        "kpi_4g_hourly_compare.html",
        username=session["username"],
        active_sites=len(sel_sites),
        sites_list=sites_list, sel_sites=sel_sites,
        from_date_before=from_date_b, to_date_before=to_date_b,
        from_date_after=from_date_a, to_date_after=to_date_a,
        last_update=last_update,
        chart_labels=chart_labels,
        compare_data=compare_data,
        compare_table=site_compare_table,
        agg_data=agg_data,
        site_compare_table=site_compare_table,
        kpi_defs=[(k[0],k[1],k[2],k[3],k[4],k[5]) for k in KPI_DEFS],
        kpi_groups=KPI_GROUPS,
        kpi_group_map={k[0]:k[8] for k in KPI_DEFS},
    )))