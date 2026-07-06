"""5G KPI Hourly Routes — /kpi_5g_hourly (main view per-site)"""
from flask import Blueprint, render_template, request, session, flash, make_response
from app.db.db_webapp import get_postgres_connection, get_site_list_5g
from ._utils import login_required, _no_cache, json_response, db_query
import psycopg2
import psycopg2.errors

kpi5g_hourly = Blueprint("kpi5g_hourly", __name__)


# ── Get last update timestamp (async endpoint) ────────────────────────────────
@kpi5g_hourly.route("/api/kpi_5g_hourly/last_update")
@login_required
def api_kpi_5g_hourly_last_update():
    """Lightweight endpoint to get last update timestamp without full KPI query"""
    try:
        with db_query() as (conn, cur):
            cur.execute('SELECT MAX(datehour::date) FROM "5g_kpi_zte"')
            raw = cur.fetchone()
            last_update = raw[0].strftime('%Y-%m-%d') if raw and raw[0] else None
            return json_response({"last_update": last_update})
    except Exception:
        return json_response({"last_update": None})


# ── 5G KPI Hourly (main page) ─────────────────────────────────────────────────
@kpi5g_hourly.route("/kpi_5g_hourly")
@login_required
def kpi_5g_hourly():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")

    # Support site IDs pasted from CSV — comma/newline separated, deduplicate
    site_paste_raw = request.args.get("site_paste", "")
    if site_paste_raw:
        extra = [s.strip() for s in site_paste_raw.replace("\n", ",").split(",") if s.strip()]
        for s in extra:
            if s not in sel_sites:
                sel_sites.append(s)

    # Initialize chart data structures
    chart_labels = []
    chart_payload = {}         # 5G Payload (GB)
    chart_dl_payload = {}     # 5G DL Payload (GB)
    chart_ul_payload = {}     # 5G UL Payload (GB)
    chart_availability = {}  # Availability (%)
    chart_rrc_user = {}        # RRC User
    chart_nr_active_user = {}  # NR Active User
    chart_nr_accessibility = {}# NR Accessibility (%)
    chart_nr_retainability = {}# NR Retainability (%)
    chart_nr_mobility = {}     # NR Mobility SR (%)
    chart_dl_prb = {}          # DL PRB (%)
    chart_ul_prb = {}          # UL PRB (%)
    chart_cell_dl_thp = {}     # Cell DL Thp (Mbps)
    chart_cell_ul_thp = {}     # Cell UL Thp (Mbps)
    chart_dl_thp = {}          # User DL Thp (Mbps)
    chart_ul_thp = {}          # User UL Thp (Mbps)
    chart_se = {}              # SE
    chart_cqi = {}             # CQI
    chart_ul_interference = {}# UL Interference (dBm)
    chart_packet_loss = {}    # Packet Loss (%)
    chart_latency_dl = {}      # Latency DL (ms)
    chart_latency_ul = {}      # Latency UL (ms)
    sites_list = []; last_update = None; active_sites = 0

    # Load site list from siteID_5g reference view
    try:
        sites_list, _ = get_site_list_5g()
        active_sites = len(sites_list)
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
                    cur.execute('SELECT MAX(datehour::date) FROM "5g_kpi_zte"')
                    raw_last = cur.fetchone()
                    last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
                except Exception:
                    last_update = None

                # Execute KPI query for 5G
                cur.execute("""
                    SELECT
                        datehour,
                        siteid,
                        ROUND((SUM("5g_payload_mb") / 1024.0)::numeric, 3) AS payload_gb,
                        ROUND((SUM(payload_dl_mbyte_xhj) / 1024.0)::numeric, 3) AS payload_dl_gb,
                        ROUND((SUM(payload_ul_mbyte_xhj) / 1024.0)::numeric, 3) AS payload_ul_gb,
                        CASE WHEN SUM(denum_availability_xhj) > 0
                             THEN ROUND((SUM(num_availability_xhj) / SUM(denum_availability_xhj) * 100.0)::numeric, 2)
                             ELSE NULL END AS availability_pct,
                        SUM(max_rrc_user_number_xhj) AS rrc_user,
                        SUM(nr_active_user_number) AS nr_active_user,
                        CASE WHEN SUM(number_of_sn_add_requests) > 0
                             THEN ROUND((SUM(num_sn_setup_success_rate_xhj) / SUM(number_of_sn_add_requests) * 100.0)::numeric, 2)
                             ELSE NULL END AS nr_accessibility_pct,
                        CASE WHEN SUM(denum_nr_retainability_xhj) > 0
                             THEN ROUND((100.0 - (SUM(num_nr_retainability_xhj) / SUM(denum_nr_retainability_xhj) * 100.0))::numeric, 2)
                             ELSE NULL END AS nr_retainability_pct,
                        CASE WHEN SUM(nr_mobility_success_rate_denum) > 0
                             THEN ROUND((SUM(nr_mobility_success_rate_num) / SUM(nr_mobility_success_rate_denum) * 100.0)::numeric, 2)
                             ELSE NULL END AS nr_mobility_pct,
                        CASE WHEN SUM(denum_prb_utilization_dl_xhj) > 0
                             THEN ROUND((SUM(num_prb_utilization_dl_xhj) / SUM(denum_prb_utilization_dl_xhj) * 100.0)::numeric, 2)
                             ELSE NULL END AS dl_prb_pct,
                        CASE WHEN SUM(denum_prb_utilization_ul_xhj) > 0
                             THEN ROUND((SUM(num_prb_utilization_ul_xhj) / SUM(denum_prb_utilization_ul_xhj) * 100.0)::numeric, 2)
                             ELSE NULL END AS ul_prb_pct,
                        ROUND((AVG(cell_throughput_dl_xhj))::numeric, 2) AS cell_dl_thp_mbps,
                        ROUND((AVG(cell_throughput_ul_xhj))::numeric, 2) AS cell_ul_thp_mbps,
                        CASE WHEN SUM(denum_user_throughput_dl_xhj) > 0
                             THEN ROUND((SUM(num_user_throughput_dl_xhj) / SUM(denum_user_throughput_dl_xhj) )::numeric, 2)
                             ELSE NULL END AS user_dl_thp_mbps,
                        CASE WHEN SUM(denum_user_throughput_ul_xhj) > 0
                             THEN ROUND((SUM(num_user_throughput_ul_xhj) / SUM(denum_user_throughput_ul_xhj) )::numeric, 2)
                             ELSE NULL END AS user_ul_thp_mbps,
                        CASE WHEN SUM(spectrum_eff_bps_lw_denum) > 0
                             THEN ROUND((SUM(spectrum_eff_bps_lw_num) / SUM(spectrum_eff_bps_lw_denum))::numeric, 4)
                             ELSE NULL END AS se,
                        CASE WHEN SUM(denum_average_cqi_xhj) > 0
                             THEN ROUND((SUM(num_average_cqi_xhj) / SUM(denum_average_cqi_xhj))::numeric, 2)
                             ELSE NULL END AS cqi,
                        AVG(avg_uplink_interference_xhj) AS ul_interference,
                        CASE WHEN SUM(denum_packet_loss_xhj) > 0
                             THEN ROUND((SUM(num_packet_loss_xhj) / SUM(denum_packet_loss_xhj) * 100.0)::numeric, 2)
                             ELSE NULL END AS packet_loss_pct,
                        CASE WHEN SUM(denum_latency_dl_xhj) > 0
                             THEN ROUND((SUM(num_latency_dl_xhj) / SUM(denum_latency_dl_xhj))::numeric, 2)
                             ELSE NULL END AS latency_dl_ms,
                        CASE WHEN SUM(denum_latency_ul_xhj) > 0
                             THEN ROUND((SUM(num_latency_ul_xhj) / SUM(denum_latency_ul_xhj))::numeric, 2)
                             ELSE NULL END AS latency_ul_ms
                    FROM "5g_kpi_zte"
                    WHERE datehour::date BETWEEN %s AND %s
                      AND siteid = ANY(%s)
                    GROUP BY datehour, siteid
                    ORDER BY datehour, siteid
                """, [from_date, to_date, sel_sites])

                # Build hours seen set and per-site data dictionaries
                hours_seen = {}
                for r in cur.fetchall():
                    dh    = r[0].strftime("%Y-%m-%d %H:%M")
                    site  = r[1]
                    pl    = round(float(r[2]), 2) if r[2] is not None else 0
                    dlpl  = round(float(r[3]), 2) if r[3] is not None else 0
                    ulpl  = round(float(r[4]), 2) if r[4] is not None else 0
                    av    = float(r[5])  if r[5]  is not None else None
                    rrc   = float(r[6])  if r[6]  is not None else None
                    nrau  = float(r[7])  if r[7]  is not None else None
                    nrac  = float(r[8])  if r[8]  is not None else None
                    nrre  = float(r[9])  if r[9]  is not None else None
                    nrmo  = float(r[10]) if r[10] is not None else None
                    dlprb = float(r[11]) if r[11] is not None else None
                    ulprb = float(r[12]) if r[12] is not None else None
                    cdlthp= float(r[13]) if r[13] is not None else None
                    culthp= float(r[14]) if r[14] is not None else None
                    dlthp = float(r[15]) if r[15] is not None else None
                    ulthp = float(r[16]) if r[16] is not None else None
                    se    = float(r[17]) if r[17] is not None else None
                    cqi   = float(r[18]) if r[18] is not None else None
                    ulint = round(float(r[19]), 2) if r[19] is not None else None
                    plos  = float(r[20]) if r[20] is not None else None
                    ltdl  = float(r[21]) if r[21] is not None else None
                    ltul  = float(r[22]) if r[22] is not None else None

                    hours_seen[dh] = True
                    chart_payload.setdefault(site, {})[dh] = pl
                    chart_dl_payload.setdefault(site, {})[dh] = dlpl
                    chart_ul_payload.setdefault(site, {})[dh] = ulpl
                    chart_availability.setdefault(site, {})[dh] = av
                    chart_rrc_user.setdefault(site, {})[dh] = rrc
                    chart_nr_active_user.setdefault(site, {})[dh] = nrau
                    chart_nr_accessibility.setdefault(site, {})[dh] = nrac
                    chart_nr_retainability.setdefault(site, {})[dh] = nrre
                    chart_nr_mobility.setdefault(site, {})[dh] = nrmo
                    chart_dl_prb.setdefault(site, {})[dh] = dlprb
                    chart_ul_prb.setdefault(site, {})[dh] = ulprb
                    chart_cell_dl_thp.setdefault(site, {})[dh] = cdlthp
                    chart_cell_ul_thp.setdefault(site, {})[dh] = culthp
                    chart_dl_thp.setdefault(site, {})[dh] = dlthp
                    chart_ul_thp.setdefault(site, {})[dh] = ulthp
                    chart_se.setdefault(site, {})[dh] = se
                    chart_cqi.setdefault(site, {})[dh] = cqi
                    chart_ul_interference.setdefault(site, {})[dh] = ulint
                    chart_packet_loss.setdefault(site, {})[dh] = plos
                    chart_latency_dl.setdefault(site, {})[dh] = ltdl
                    chart_latency_ul.setdefault(site, {})[dh] = ltul

                chart_labels = sorted(hours_seen.keys())

                # Convert per-hour dicts to ordered lists for chart rendering
                for s in chart_payload:
                    chart_payload[s]            = [chart_payload[s].get(h, 0) for h in chart_labels]
                    chart_dl_payload[s]        = [chart_dl_payload[s].get(h, 0) for h in chart_labels]
                    chart_ul_payload[s]        = [chart_ul_payload[s].get(h, 0) for h in chart_labels]
                    chart_availability[s]      = [chart_availability[s].get(h) for h in chart_labels]
                    chart_rrc_user[s]          = [chart_rrc_user[s].get(h) for h in chart_labels]
                    chart_nr_active_user[s]    = [chart_nr_active_user[s].get(h) for h in chart_labels]
                    chart_nr_accessibility[s]   = [chart_nr_accessibility[s].get(h) for h in chart_labels]
                    chart_nr_retainability[s]   = [chart_nr_retainability[s].get(h) for h in chart_labels]
                    chart_nr_mobility[s]       = [chart_nr_mobility[s].get(h) for h in chart_labels]
                    chart_dl_prb[s]          = [chart_dl_prb[s].get(h) for h in chart_labels]
                    chart_ul_prb[s]          = [chart_ul_prb[s].get(h) for h in chart_labels]
                    chart_cell_dl_thp[s]      = [chart_cell_dl_thp[s].get(h) for h in chart_labels]
                    chart_cell_ul_thp[s]      = [chart_cell_ul_thp[s].get(h) for h in chart_labels]
                    chart_dl_thp[s]          = [chart_dl_thp[s].get(h) for h in chart_labels]
                    chart_ul_thp[s]          = [chart_ul_thp[s].get(h) for h in chart_labels]
                    chart_se[s]              = [chart_se[s].get(h) for h in chart_labels]
                    chart_cqi[s]             = [chart_cqi[s].get(h) for h in chart_labels]
                    chart_ul_interference[s] = [chart_ul_interference[s].get(h) for h in chart_labels]
                    chart_packet_loss[s]       = [chart_packet_loss[s].get(h) for h in chart_labels]
                    chart_latency_dl[s]      = [chart_latency_dl[s].get(h) for h in chart_labels]
                    chart_latency_ul[s]      = [chart_latency_ul[s].get(h) for h in chart_labels]
        except psycopg2.OperationalError:
            flash("Database connection failed. Please try again.", "warning")
        except psycopg2.errors.QueryCanceled:
            flash("Query timed out. Please try a shorter date range.", "warning")
        except psycopg2.errors.ConnectionDoesNotExist:
            flash("Database server unreachable. Please try again later.", "warning")
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")

    return _no_cache(make_response(render_template(
        "kpi_5g_hourly.html",
        username=session["username"],
        active_sites=active_sites,
        sites_list=sites_list,
        sel_sites=sel_sites,
        from_date=from_date,
        to_date=to_date,
        last_update=last_update,
        chart_labels=chart_labels,
        chart_payload=chart_payload,
        chart_dl_payload=chart_dl_payload,
        chart_ul_payload=chart_ul_payload,
        chart_availability=chart_availability,
        chart_rrc_user=chart_rrc_user,
        chart_nr_active_user=chart_nr_active_user,
        chart_nr_accessibility=chart_nr_accessibility,
        chart_nr_retainability=chart_nr_retainability,
        chart_nr_mobility=chart_nr_mobility,
        chart_dl_prb=chart_dl_prb,
        chart_ul_prb=chart_ul_prb,
        chart_cell_dl_thp=chart_cell_dl_thp,
        chart_cell_ul_thp=chart_cell_ul_thp,
        chart_dl_thp=chart_dl_thp,
        chart_ul_thp=chart_ul_thp,
        chart_se=chart_se,
        chart_cqi=chart_cqi,
        chart_ul_interference=chart_ul_interference,
        chart_packet_loss=chart_packet_loss,
        chart_latency_dl=chart_latency_dl,
        chart_latency_ul=chart_latency_ul,
    )))
