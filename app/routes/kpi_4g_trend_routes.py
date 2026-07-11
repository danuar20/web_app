"""4G KPI Hourly Trend Routes — /kpi_4g_hourly/trend (cluster aggregation)"""
from flask import Blueprint, render_template, request, session, flash, make_response
from app.db.db_webapp import get_postgres_connection, get_site_list_4g
from ._utils import viewer_blocked, login_required, _no_cache, json_response, db_query
import psycopg2
import psycopg2.errors

kpi4g_trend = Blueprint("kpi4g_trend", __name__)


# ── Get last update timestamp (async endpoint) ────────────────────────────────
@kpi4g_trend.route("/api/kpi_4g_hourly/trend/last_update")
@login_required
@viewer_blocked
def api_kpi_4g_trend_last_update():
    """Lightweight endpoint to get last update timestamp without full KPI query"""
    try:
        with db_query() as (conn, cur):
            cur.execute('SELECT MAX(datehour::date) FROM "4g_kpi_zte"')
            raw = cur.fetchone()
            last_update = raw[0].strftime('%Y-%m-%d') if raw and raw[0] else None
            return json_response({"last_update": last_update})
    except Exception as e:
        return json_response({"error": str(e)}, 500)


# ── 4G KPI Hourly Trend (Multi-Site comparison) ────────────────────────────────
@kpi4g_trend.route("/kpi_4g_hourly/trend")
@login_required
@viewer_blocked
def kpi_4g_hourly_trend():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")
    cluster_name = request.args.get("cluster_name", "Cluster").strip() or "Cluster"

    # Support site IDs pasted from CSV — comma/newline separated, deduplicate
    site_paste_raw = request.args.get("site_paste", "")
    if site_paste_raw:
        extra = [s.strip() for s in site_paste_raw.replace("\n", ",").split(",") if s.strip()]
        for s in extra:
            if s not in sel_sites:
                sel_sites.append(s)

    # Initialize chart data structures
    chart_labels = []
    chart_payload = {}
    chart_cssr = {}
    chart_volte = {}
    chart_max_rrc = {}
    chart_active_user = {}
    chart_dl_prb = {}
    chart_ul_prb = {}
    chart_dl_thp = {}
    chart_ul_thp = {}
    chart_avail = {}
    chart_erab_sr = {}
    chart_rrc_sr = {}
    chart_s1_sr = {}
    chart_sdr = {}
    chart_ifho = {}
    chart_csfb = {}
    chart_se = {}
    chart_cqi = {}
    sites_list = []
    last_update = None

    # Load site list from siteID_4g reference table (fast, no KPI table scan)
    # This runs outside the main try block to ensure it happens even if DB fails
    try:
        sites_list, _ = get_site_list_4g()
    except Exception:
        sites_list = []

    # Only query KPI data when user has selected filters
    if from_date and to_date and sel_sites:
        conn = None
        cur = None
        try:
            with db_query() as (conn, cur):

                # Get last update timestamp
                try:
                    cur.execute('SELECT MAX(datehour::date) FROM "4g_kpi_zte"')
                    raw_last = cur.fetchone()
                    last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
                except Exception:
                    last_update = None

                # Cluster aggregation: GROUP BY datehour only (no siteid in GROUP BY)
                # SUM for counter KPIs, AVG for rate KPIs
                cur.execute("""
                    SELECT
                        datehour,
                        SUM("4g_payload_mb") AS payload_mb,
                        CASE WHEN SUM(cssr_denum)>0
                             THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100.0)::numeric,2)
                             ELSE NULL END AS cssr_pct,
                        SUM(volte_traffic) AS volte_traffic,
                        SUM(max_rrc_conn_user) AS max_rrc_conn_user,
                        SUM(new_active_users) AS active_users,
                        CASE WHEN SUM(dl_prb_util_denum)>0
                             THEN ROUND((SUM(dl_prb_util_num)/SUM(dl_prb_util_denum)*100.0)::numeric,2)
                             ELSE NULL END AS dl_prb_util_pct,
                        CASE WHEN SUM(ul_prb_util_denum)>0
                             THEN ROUND((SUM(ul_prb_util_num)/SUM(ul_prb_util_denum)*100.0)::numeric,2)
                             ELSE NULL END AS ul_prb_util_pct,
                        CASE WHEN SUM(user_dl_thp_denum)>0
                             THEN ROUND((SUM(user_dl_thp_num)/SUM(user_dl_thp_denum)/1000.0)::numeric,2)
                             ELSE NULL END AS user_dl_thp_mbps,
                        CASE WHEN SUM(user_ul_thp_denum)>0
                             THEN ROUND((SUM(user_ul_thp_num)/SUM(user_ul_thp_denum)/1000.0)::numeric,2)
                             ELSE NULL END AS user_ul_thp_mbps,
                        CASE WHEN SUM(avail_denum)>0
                             THEN ROUND((SUM(avail_num)/SUM(avail_denum)*100.0)::numeric,2)
                             ELSE NULL END AS avail_pct,
                        CASE WHEN SUM(erab_setup_denum)>0
                             THEN ROUND((SUM(erab_setup_num)/SUM(erab_setup_denum)*100.0)::numeric,2)
                             ELSE NULL END AS erab_sr_pct,
                        CASE WHEN SUM(rrc_setup_denum)>0
                             THEN ROUND((SUM(rrc_setup_num)/SUM(rrc_setup_denum)*100.0)::numeric,2)
                             ELSE NULL END AS rrc_sr_pct,
                        CASE WHEN SUM(s1_signaling_sr_denum)>0
                             THEN ROUND((SUM(s1_signaling_sr_num)/SUM(s1_signaling_sr_denum)*100.0)::numeric,2)
                             ELSE NULL END AS s1_sr_pct,
                        CASE WHEN SUM(sdr_denum)>0
                             THEN ROUND((SUM(sdr_num)/SUM(sdr_denum)*100.0)::numeric,2)
                             ELSE NULL END AS sdr_pct,
                        CASE WHEN SUM(ifho_denum)>0
                             THEN ROUND((SUM(ifho_num)/SUM(ifho_denum)*100.0)::numeric,2)
                             ELSE NULL END AS ifho_pct,
                        CASE WHEN SUM(csfb_denum)>0
                             THEN ROUND((SUM(csfb_num)/SUM(csfb_denum)*100.0)::numeric,2)
                             ELSE NULL END AS csfb_pct,
                        CASE WHEN SUM(se_v3_denum)>0
                             THEN ROUND((SUM(se_v3_num)/SUM(se_v3_denum))::numeric,2)
                             ELSE NULL END AS se,
                        CASE WHEN SUM(denum_average_cqi)>0
                             THEN ROUND((SUM(num_average_cqi)/SUM(denum_average_cqi))::numeric,2)
                             ELSE NULL END AS cqi
                    FROM "4g_kpi_zte"
                    WHERE date BETWEEN %s AND %s AND siteid=ANY(%s)
                    GROUP BY datehour
                    ORDER BY datehour
                """, [from_date, to_date, sel_sites])

                # Build chart dicts keyed by cluster_name (single dataset)
                for r in cur.fetchall():
                    dh = r[0].strftime("%Y-%m-%d %H:%M")
                    chart_labels.append(dh)
                    chart_payload.setdefault(cluster_name, []).append(round(float(r[1]), 2) if r[1] is not None else 0)
                    chart_cssr.setdefault(cluster_name, []).append(float(r[2])  if r[2]  is not None else None)
                    chart_volte.setdefault(cluster_name, []).append(float(r[3])  if r[3]  is not None else None)
                    chart_max_rrc.setdefault(cluster_name, []).append(float(r[4])  if r[4]  is not None else None)
                    chart_active_user.setdefault(cluster_name, []).append(float(r[5])  if r[5]  is not None else None)
                    chart_dl_prb.setdefault(cluster_name, []).append(float(r[6])  if r[6]  is not None else None)
                    chart_ul_prb.setdefault(cluster_name, []).append(float(r[7])  if r[7]  is not None else None)
                    chart_dl_thp.setdefault(cluster_name, []).append(float(r[8])  if r[8]  is not None else None)
                    chart_ul_thp.setdefault(cluster_name, []).append(float(r[9])  if r[9]  is not None else None)
                    chart_avail.setdefault(cluster_name, []).append(float(r[10]) if r[10] is not None else None)
                    chart_erab_sr.setdefault(cluster_name, []).append(float(r[11]) if r[11] is not None else None)
                    chart_rrc_sr.setdefault(cluster_name, []).append(float(r[12]) if r[12] is not None else None)
                    chart_s1_sr.setdefault(cluster_name, []).append(float(r[13]) if r[13] is not None else None)
                    chart_sdr.setdefault(cluster_name, []).append(float(r[14]) if r[14] is not None else None)
                    chart_ifho.setdefault(cluster_name, []).append(float(r[15]) if r[15] is not None else None)
                    chart_csfb.setdefault(cluster_name, []).append(float(r[16]) if r[16] is not None else None)
                    chart_se.setdefault(cluster_name, []).append(float(r[17]) if r[17] is not None else None)
                    chart_cqi.setdefault(cluster_name, []).append(float(r[18]) if r[18] is not None else None)
        except psycopg2.OperationalError:
            flash("Database connection failed. Please try again.", "warning")
        except psycopg2.errors.QueryCanceled:
            flash("Query timed out. Please try a shorter date range.", "warning")
        except psycopg2.errors.ConnectionDoesNotExist:
            flash("Database server unreachable. Please try again later.", "warning")
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")

    # KPI display configuration with threshold settings
    kpi_defaults = [
        {"id": "payloadChart",    "label": "Payload",       "unit": "MB",     "defaultMin": None, "defaultMax": None},
        {"id": "cssrChart",       "label": "CSSR",           "unit": "%",      "defaultMin": 85,   "defaultMax": 100},
        {"id": "volteChart",      "label": "VoLTE Traffic", "unit": "Erl",    "defaultMin": None, "defaultMax": None},
        {"id": "maxRrcChart",     "label": "Max RRC",        "unit": "Users", "defaultMin": None, "defaultMax": None},
        {"id": "activeUserChart", "label": "Active User",    "unit": "Users", "defaultMin": None, "defaultMax": None},
        {"id": "dlPrbChart",      "label": "DL PRB",         "unit": "%",      "defaultMin": 0,    "defaultMax": 75},
        {"id": "ulPrbChart",      "label": "UL PRB",         "unit": "%",      "defaultMin": 0,    "defaultMax": 75},
        {"id": "dlThpChart",      "label": "User DL Thp",   "unit": "Mbps",   "defaultMin": 5,    "defaultMax": None},
        {"id": "ulThpChart",      "label": "User UL Thp",   "unit": "Mbps",   "defaultMin": 2,    "defaultMax": None},
        {"id": "availChart",      "label": "Availability",   "unit": "%",      "defaultMin": 95,   "defaultMax": 100},
        {"id": "erabSrChart",     "label": "ERAB SR",         "unit": "%",      "defaultMin": 85,   "defaultMax": 100},
        {"id": "rrcSrChart",      "label": "RRC SR",          "unit": "%",      "defaultMin": 85,   "defaultMax": 100},
        {"id": "s1SrChart",       "label": "S1 SR",           "unit": "%",      "defaultMin": 95,   "defaultMax": 100},
        {"id": "sdrChart",        "label": "SDR",             "unit": "%",      "defaultMin": 0,    "defaultMax": 5},
        {"id": "ifhoChart",       "label": "IFHO",            "unit": "%",      "defaultMin": 90,   "defaultMax": 100},
        {"id": "csfbChart",       "label": "CSFB",            "unit": "%",      "defaultMin": 85,   "defaultMax": 100},
        {"id": "seChart",         "label": "SE",              "unit": "",       "defaultMin": None, "defaultMax": None},
        {"id": "cqiChart",        "label": "CQI",             "unit": "",       "defaultMin": 0,    "defaultMax": 15},
    ]

    return _no_cache(make_response(render_template(
        "kpi_4g_hourly_cluster.html",
        username=session["username"],
        sites_list=sites_list,
        sel_sites=sel_sites,
        from_date=from_date,
        to_date=to_date,
        last_update=last_update,
        cluster_name=cluster_name,
        chart_labels=chart_labels,
        chart_payload=chart_payload,
        chart_cssr=chart_cssr,
        chart_volte=chart_volte,
        chart_max_rrc=chart_max_rrc,
        chart_active_user=chart_active_user,
        chart_dl_prb=chart_dl_prb,
        chart_ul_prb=chart_ul_prb,
        chart_dl_thp=chart_dl_thp,
        chart_ul_thp=chart_ul_thp,
        chart_avail=chart_avail,
        chart_erab_sr=chart_erab_sr,
        chart_rrc_sr=chart_rrc_sr,
        chart_s1_sr=chart_s1_sr,
        chart_sdr=chart_sdr,
        chart_ifho=chart_ifho,
        chart_csfb=chart_csfb,
        chart_se=chart_se,
        chart_cqi=chart_cqi,
        kpi_defaults=kpi_defaults,
    )))