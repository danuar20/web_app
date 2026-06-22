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

    ALL_KPI_DEFS = [
        # chart_id, title, unit, y_label, y_min, y_max, sql_expr, group_name, is_lower_better
        ("payloadChart",   "4G Payload",             "GB",             None,  None, None,
         'SUM("4g_payload_mb")/1024.0',             "Productivity", False),
        ("volteChart",     "VoLTE Traffic",         "Erl",            None,  None, None,
         "SUM(volte_traffic)",                "Productivity", False),
        ("availChart",     "Availability",          "Avail (%)",      None, None, 100,
         'CASE WHEN SUM(avail_denum)>0 THEN ROUND((SUM(avail_num)/SUM(avail_denum)*100)::numeric,2) ELSE NULL END',    "Availability", False),
        ("maxRrcChart",    "Max RRC User",          "Users",          None,  None, None,
         "SUM(max_rrc_conn_user)",            "User", False),
        ("activeUserChart","Active User",           "Users",          None,  None, None,
         "SUM(new_active_users)",            "User", False),
        ("cssrChart",      "CSSR",                  "CSSR (%)",       None, None, 100,
         'CASE WHEN SUM(cssr_denum)>0 THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),
        ("rrcSrChart",     "RRC SR",                "RRC SR (%)",     None, None, 100,
         'CASE WHEN SUM(rrc_setup_denum)>0 THEN ROUND((SUM(rrc_setup_num)/SUM(rrc_setup_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),
        ("erabSrChart",    "ERAB SR",                "ERAB SR (%)",    None, None, 100,
         'CASE WHEN SUM(erab_setup_denum)>0 THEN ROUND((SUM(erab_setup_num)/SUM(erab_setup_denum)*100)::numeric,2) ELSE NULL END', "Accessibility", False),
        ("sdrChart",       "SDR",                   "SDR (%)",        None,  None, None,
         'CASE WHEN SUM(sdr_denum)>0 THEN ROUND((SUM(sdr_num)/SUM(sdr_denum)*100)::numeric,2) ELSE NULL END', "Retainability", True),
        ("dlPrbChart",     "DL PRB",                "DL PRB (%)",     None, 0, 100,
         'CASE WHEN SUM(dl_prb_util_denum)>0 THEN ROUND((SUM(dl_prb_util_num)/SUM(dl_prb_util_denum)*100)::numeric,2) ELSE NULL END', "Capacity", False),
        ("ulPrbChart",     "UL PRB",                "UL PRB (%)",     None, 0, 100,
         'CASE WHEN SUM(ul_prb_util_denum)>0 THEN ROUND((SUM(ul_prb_util_num)/SUM(ul_prb_util_denum)*100)::numeric,2) ELSE NULL END', "Capacity", False),
        ("dlThpChart",     "User DL Throughput",    "DL Thp (Mbps)",  None,  None, None,
         'CASE WHEN SUM(user_dl_thp_denum)>0 THEN ROUND((SUM(user_dl_thp_num)/SUM(user_dl_thp_denum)/1000)::numeric,2) ELSE NULL END', "Integrity", False),
        ("ulThpChart",     "User UL Throughput",    "UL Thp (Mbps)",  None,  None, None,
         'CASE WHEN SUM(user_ul_thp_denum)>0 THEN ROUND((SUM(user_ul_thp_num)/SUM(user_ul_thp_denum)/1000)::numeric,2) ELSE NULL END', "Integrity", False),
        ("ifhoChart",      "IFHO",                  "IFHO (%)",       None, None, 100,
         'CASE WHEN SUM(ifho_denum)>0 THEN ROUND((SUM(ifho_num)/SUM(ifho_denum)*100)::numeric,2) ELSE NULL END', "Mobility", False),
        ("seChart",        "Spectral Efficiency",    "SE",             None,  None, None,
         'CASE WHEN SUM(se_v3_denum)>0 THEN ROUND((SUM(se_v3_num)/SUM(se_v3_denum))::numeric,2) ELSE NULL END', "Quality", False),
        ("cqiChart",       "CQI",                  "CQI",            None, None, None,
         'CASE WHEN SUM(denum_average_cqi)>0 THEN ROUND((SUM(num_average_cqi)/SUM(denum_average_cqi))::numeric,2) ELSE NULL END', "Quality", False),
        ("csfbChart",       "CSFB",                  "CSFB (%)",       None, None, 100,
         'CASE WHEN SUM(csfb_denum)>0 THEN ROUND((SUM(csfb_num)/SUM(csfb_denum)*100)::numeric,2) ELSE NULL END', "Others", False),
        ("s1SrChart",      "S1 SR",                  "S1 SR (%)",      None, None, 100,
         'CASE WHEN SUM(s1_signaling_sr_denum)>0 THEN ROUND((SUM(s1_signaling_sr_num)/SUM(s1_signaling_sr_denum)*100)::numeric,2) ELSE NULL END', "Others", False),
    ]

    KPI_GROUPS = ["Productivity","Availability","User","Accessibility","Retainability","Capacity","Integrity","Mobility","Quality","Others"]

    sel_kpis = request.args.getlist("kpi")
    if not sel_kpis:
        # Default to all if none selected to maintain backwards compatibility
        sel_kpis = [k[0] for k in ALL_KPI_DEFS]
        
    # Filter active definitions
    KPI_DEFS = [k for k in ALL_KPI_DEFS if k[0] in sel_kpis]

    # Initialize data structures
    chart_labels  = []
    compare_data  = {}
    site_compare_table = {}
    agg_data      = {}
    sites_list    = []
    last_update   = None

    # Load site list from siteID_4g reference table (fast, no KPI table scan)
    try:
        sites_list, _ = get_site_list_4g()
    except Exception:
        sites_list = []

    # Only query KPI data when user has selected all required filters
    if from_date_b and to_date_b and from_date_a and to_date_a and sel_sites and KPI_DEFS:
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

            # Construct dynamic select fields
            kpi_selects = ", ".join([f"{k[6]} AS {k[0]}" for k in KPI_DEFS])
            
            # --- 1. Get Cluster Hourly Trends ---
            cur.execute(f"""
                SELECT TO_CHAR(datehour, {HR_FMT}) AS hr, {kpi_selects}
                FROM "4g_kpi_zte"
                WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                GROUP BY hr ORDER BY hr
            """, [from_date_b, to_date_b, sel_sites])
            before_hourly = cur.fetchall()

            cur.execute(f"""
                SELECT TO_CHAR(datehour, {HR_FMT}) AS hr, {kpi_selects}
                FROM "4g_kpi_zte"
                WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                GROUP BY hr ORDER BY hr
            """, [from_date_a, to_date_a, sel_sites])
            after_hourly = cur.fetchall()

            # Extract labels and map hourly data
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

            # --- 2. Get Site Level Aggregates ---
            cur.execute(f"""
                SELECT siteid, {kpi_selects}
                FROM "4g_kpi_zte"
                WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
                GROUP BY siteid
            """, [from_date_b, to_date_b, sel_sites])
            before_sites = {r[0]: r[1:] for r in cur.fetchall()}

            cur.execute(f"""
                SELECT siteid, {kpi_selects}
                FROM "4g_kpi_zte"
                WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
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

            # --- 3. Get Cluster Network Aggregates ---
            cur.execute(f"""
                SELECT {kpi_selects}
                FROM "4g_kpi_zte"
                WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
            """, [from_date_b, to_date_b, sel_sites])
            agg_before_row = cur.fetchone()

            cur.execute(f"""
                SELECT {kpi_selects}
                FROM "4g_kpi_zte"
                WHERE date BETWEEN %s AND %s AND siteid = ANY(%s)
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
        sel_kpis=sel_kpis, all_kpis=ALL_KPI_DEFS,
        from_date_before=from_date_b, to_date_before=to_date_b,
        from_date_after=from_date_a, to_date_after=to_date_a,
        last_update=last_update,
        chart_labels=chart_labels,
        compare_data=compare_data,
        agg_data=agg_data,
        site_compare_table=site_compare_table,
        kpi_defs=[(k[0],k[1],k[2],k[3],k[4],k[5],k[7],k[8]) for k in KPI_DEFS],
        kpi_groups=KPI_GROUPS,
        kpi_group_map={k[0]:k[7] for k in ALL_KPI_DEFS},
    )))
