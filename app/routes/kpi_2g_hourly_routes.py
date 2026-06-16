"""2G KPI Hourly Routes — /kpi_2g_hourly (Site Level only)"""
from flask import Blueprint, render_template, request, session, make_response, flash
from app.db.db_webapp import get_postgres_connection, get_site_list_2g
from ._utils import login_required, _no_cache, json_response
import psycopg2
import psycopg2.errors

kpi2g_hourly = Blueprint("kpi2g_hourly", __name__)


# ── Site list API ──────────────────────────────────────────────────────────────
@kpi2g_hourly.route("/api/kpi_2g_hourly/sites")
@login_required
def api_kpi_2g_hourly_sites():
    """Returns 2G site list from siteID_2g"""
    try:
        sites = get_site_list_2g()
        return json_response({"sites": sites, "count": len(sites)})
    except Exception as e:
        import traceback
        return json_response({"error": str(e), "trace": traceback.format_exc()[-500:]}, 500)


# ── Last update ──────────────────────────────────────────────────────────────
@kpi2g_hourly.route("/api/kpi_2g_hourly/last_update")
@login_required
def api_kpi_2g_hourly_last_update():
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute('SELECT MAX(datehour) FROM "2g_kpi_zte"')
        raw = cur.fetchone()
        cur.close()
        conn.close()
        last_update = raw[0].strftime('%Y-%m-%d %H:%M') if raw and raw[0] else None
        return json_response({"last_update": last_update})
    except Exception:
        return json_response({"last_update": None})


# ── 2G KPI Hourly (Site Level) ──────────────────────────────────────────────
@kpi2g_hourly.route("/kpi_2g_hourly")
@login_required
def kpi_2g_hourly():
    from_date = request.args.get("from_date", "")
    to_date = request.args.get("to_date", "")
    sel_sites = request.args.getlist("site")

    # Support pasted site IDs from CSV
    site_paste_raw = request.args.get("site_paste", "")
    if site_paste_raw:
        extra = [s.strip() for s in site_paste_raw.replace("\n", ",").split(",") if s.strip()]
        for s in extra:
            if s not in sel_sites:
                sel_sites.append(s)

    # Initialize
    sites_list = []; last_update = None; active_count = 0
    chart_labels = []
    chart_tch = {}; chart_sdcch = {}; chart_fullrate = {}; chart_halfrate = {}
    chart_payload = {}
    chart_avail = {}; chart_cssr = {}; chart_ccsr = {}; chart_hosr = {}
    chart_tchblk = {}; chart_tchblk_num = {}; chart_sdcchblk = {}; chart_sdcchblk_num = {}
    chart_sdsr = {}
    chart_tbf_est = {}; chart_tbf_comp = {}; chart_tch_drop = {}; chart_tch_drop_num = {}
    chart_fastreturn = {}; chart_icm = {}; chart_interference = {}

    # Load site list synchronously (same pattern as 5G hourly)
    try:
        sites_list = get_site_list_2g()
        active_count = len(sites_list)
    except Exception:
        sites_list = []

    # Only query KPI data when user selects date range AND sites
    if from_date and to_date and sel_sites:
        conn = None
        cur = None
        try:
            conn = get_postgres_connection()
            cur = conn.cursor()

            # Last update
            try:
                cur.execute('SELECT MAX(datehour) FROM "2g_kpi_zte"')
                raw = cur.fetchone()
                last_update = raw[0].strftime('%Y-%m-%d %H:%M') if raw and raw[0] else None
            except Exception:
                last_update = None

            # KPI Query — filter by siteid directly
            cur.execute("""
                SELECT
                    datehour,
                    siteid,
                    ROUND(SUM(tch_traffic)::numeric, 2) AS tch_traffic,
                    ROUND(SUM(sdcch_traffic)::numeric, 2) AS sdcch_traffic,
                    ROUND(SUM("Offic_full_traffic")::numeric, 2) AS full_rate_traffic,
                    ROUND(SUM("Offic_half_traffic")::numeric, 2) AS half_rate_traffic,
                    ROUND(SUM(total_payload)::numeric, 2) AS payload_mb,
                    CASE WHEN SUM(tch_avail_denum) > 0
                         THEN ROUND((SUM(tch_avail_num)::numeric / SUM(tch_avail_denum)::numeric * 100), 2)
                         ELSE NULL END AS avail_pct,
                    CASE WHEN SUM(cssr_denum) > 0
                         THEN ROUND((SUM(cssr_num)::numeric / SUM(cssr_denum)::numeric * 100), 2)
                         ELSE NULL END AS cssr_pct,
                    CASE WHEN SUM("2g_ccsr_denum") > 0
                         THEN ROUND((SUM("2g_ccsr_num")::numeric / SUM("2g_ccsr_denum")::numeric * 100), 2)
                         ELSE NULL END AS ccsr_pct,
                    CASE WHEN SUM(hosr_denum) > 0
                         THEN ROUND((SUM(hosr_num)::numeric / SUM(hosr_denum)::numeric * 100), 2)
                         ELSE NULL END AS hosr_pct,
                    CASE WHEN SUM(tch_block_denum) > 0
                         THEN ROUND((SUM(tch_block_num)::numeric / SUM(tch_block_denum)::numeric * 100), 2)
                         ELSE NULL END AS tch_blk_pct,
                    ROUND(SUM(tch_block_num)::numeric, 0) AS tch_block_num,
                    CASE WHEN SUM(sdcch_block_denum) > 0
                         THEN ROUND((SUM(sdcch_block_num)::numeric / SUM(sdcch_block_denum)::numeric * 100), 2)
                         ELSE NULL END AS sdcch_blk_pct,
                    ROUND(SUM(sdcch_block_num)::numeric, 0) AS sdcch_block_num,
                    CASE WHEN SUM(sdsr_denum) > 0
                         THEN ROUND((SUM(sdsr_num)::numeric / SUM(sdsr_denum)::numeric * 100), 2)
                         ELSE NULL END AS sdsr_pct,
                    CASE WHEN SUM(tbf_dl_est_denum) > 0
                         THEN ROUND((SUM(tbf_dl_est_num)::numeric / SUM(tbf_dl_est_denum)::numeric * 100), 2)
                         ELSE NULL END AS tbf_est_pct,
                    CASE WHEN SUM(tbf_comp_denum) > 0
                         THEN ROUND((SUM(tbf_comp_num)::numeric / SUM(tbf_comp_denum)::numeric * 100), 2)
                         ELSE NULL END AS tbf_comp_pct,
                    CASE WHEN SUM(tch_drop_denum) > 0
                         THEN ROUND((SUM(tch_drop_num)::numeric / SUM(tch_drop_denum)::numeric * 100), 2)
                         ELSE NULL END AS tch_drop_pct,
                    ROUND(SUM(tch_drop_num)::numeric, 0) AS tch_drop_num,
                    ROUND(SUM(fastreturn_to_lte)::numeric, 0) AS fastreturn,
                    CASE WHEN SUM(icm_band35_num) > 0
                         THEN ROUND((SUM(icm_band35_num)::numeric / SUM(icm_band35_denum)::numeric * 100), 2)
                         ELSE NULL END AS icm_pct,
                    CASE WHEN SUM(denum_icm_interference_ono) > 0
                         THEN ROUND((SUM(num_icm_interference_ono)::numeric / SUM(denum_icm_interference_ono)::numeric * 100), 2)
                         ELSE NULL END AS interference_pct
                FROM "2g_kpi_zte"
                WHERE datehour::date BETWEEN %s::date AND %s::date
                  AND siteid = ANY(%s)
                GROUP BY datehour, siteid
                ORDER BY datehour, siteid
            """, [from_date, to_date, sel_sites])

            # Build data dict keyed by siteid
            hours_seen = {}
            for r in cur.fetchall():
                dh = r[0].strftime("%Y-%m-%d %H:%M")
                site = r[1]
                tch      = round(float(r[2]), 2) if r[2] is not None else 0
                sdcch    = round(float(r[3]), 2) if r[3] is not None else 0
                fullrate = round(float(r[4]), 2) if r[4] is not None else 0
                halfrate = round(float(r[5]), 2) if r[5] is not None else 0
                pl       = round(float(r[6]), 2) if r[6] is not None else 0
                avail    = float(r[7])  if r[7]  is not None else None
                cssr     = float(r[8])  if r[8]  is not None else None
                ccsr     = float(r[9])  if r[9]  is not None else None
                hosr     = float(r[10]) if r[10] is not None else None
                tblk     = float(r[11]) if r[11] is not None else None
                tblk_num = round(float(r[12]), 0) if r[12] is not None else 0
                sblk     = float(r[13]) if r[13] is not None else None
                sblk_num = round(float(r[14]), 0) if r[14] is not None else 0
                sdsr     = float(r[15]) if r[15] is not None else None
                tbf_e    = float(r[16]) if r[16] is not None else None
                tbf_c    = float(r[17]) if r[17] is not None else None
                tdorp    = float(r[18]) if r[18] is not None else None
                tdrop_num= round(float(r[19]), 0) if r[19] is not None else 0
                fret     = round(float(r[20]), 0) if r[20] is not None else 0
                icm      = float(r[21]) if r[21] is not None else None
                intr     = float(r[22]) if r[22] is not None else None

                hours_seen[dh] = True
                chart_tch.setdefault(site, {})[dh] = tch
                chart_sdcch.setdefault(site, {})[dh] = sdcch
                chart_fullrate.setdefault(site, {})[dh] = fullrate
                chart_halfrate.setdefault(site, {})[dh] = halfrate
                chart_payload.setdefault(site, {})[dh] = pl
                chart_avail.setdefault(site, {})[dh] = avail
                chart_cssr.setdefault(site, {})[dh] = cssr
                chart_ccsr.setdefault(site, {})[dh] = ccsr
                chart_hosr.setdefault(site, {})[dh] = hosr
                chart_tchblk.setdefault(site, {})[dh] = tblk
                chart_tchblk_num.setdefault(site, {})[dh] = tblk_num
                chart_sdcchblk.setdefault(site, {})[dh] = sblk
                chart_sdcchblk_num.setdefault(site, {})[dh] = sblk_num
                chart_sdsr.setdefault(site, {})[dh] = sdsr
                chart_tbf_est.setdefault(site, {})[dh] = tbf_e
                chart_tbf_comp.setdefault(site, {})[dh] = tbf_c
                chart_tch_drop.setdefault(site, {})[dh] = tdorp
                chart_tch_drop_num.setdefault(site, {})[dh] = tdrop_num
                chart_fastreturn.setdefault(site, {})[dh] = fret
                chart_icm.setdefault(site, {})[dh] = icm
                chart_interference.setdefault(site, {})[dh] = intr

            chart_labels = sorted(hours_seen.keys())

            # Convert to ordered lists
            for s in chart_payload:
                chart_tch[s]            = [chart_tch[s].get(h, 0) for h in chart_labels]
                chart_sdcch[s]          = [chart_sdcch[s].get(h, 0) for h in chart_labels]
                chart_fullrate[s]       = [chart_fullrate[s].get(h, 0) for h in chart_labels]
                chart_halfrate[s]       = [chart_halfrate[s].get(h, 0) for h in chart_labels]
                chart_payload[s]        = [chart_payload[s].get(h, 0) for h in chart_labels]
                chart_avail[s]          = [chart_avail[s].get(h) for h in chart_labels]
                chart_cssr[s]           = [chart_cssr[s].get(h) for h in chart_labels]
                chart_ccsr[s]           = [chart_ccsr[s].get(h) for h in chart_labels]
                chart_hosr[s]           = [chart_hosr[s].get(h) for h in chart_labels]
                chart_tchblk[s]         = [chart_tchblk[s].get(h) for h in chart_labels]
                chart_tchblk_num[s]     = [chart_tchblk_num[s].get(h, 0) for h in chart_labels]
                chart_sdcchblk[s]       = [chart_sdcchblk[s].get(h) for h in chart_labels]
                chart_sdcchblk_num[s]   = [chart_sdcchblk_num[s].get(h, 0) for h in chart_labels]
                chart_sdsr[s]           = [chart_sdsr[s].get(h) for h in chart_labels]
                chart_tbf_est[s]        = [chart_tbf_est[s].get(h) for h in chart_labels]
                chart_tbf_comp[s]       = [chart_tbf_comp[s].get(h) for h in chart_labels]
                chart_tch_drop[s]       = [chart_tch_drop[s].get(h) for h in chart_labels]
                chart_tch_drop_num[s]   = [chart_tch_drop_num[s].get(h, 0) for h in chart_labels]
                chart_fastreturn[s]     = [chart_fastreturn[s].get(h, 0) for h in chart_labels]
                chart_icm[s]            = [chart_icm[s].get(h) for h in chart_labels]
                chart_interference[s]   = [chart_interference[s].get(h) for h in chart_labels]

            cur.close()
            conn.close()

        except psycopg2.OperationalError:
            if conn:
                try: conn.rollback()
                except: pass
            if cur: cur.close()
            if conn: conn.close()
            flash("Database connection failed. Please try again.", "warning")
        except psycopg2.errors.QueryCanceled:
            if conn:
                try: conn.rollback()
                except: pass
            if cur: cur.close()
            if conn: conn.close()
            flash("Query timed out. Please try a shorter date range.", "warning")
        except Exception as e:
            if conn:
                try: conn.rollback()
                except: pass
            if cur: cur.close()
            if conn: conn.close()
            flash(f"Error: {str(e)}", "danger")

    return _no_cache(make_response(render_template(
        "kpi_2g_hourly.html",
        username=session["username"],
        sites_list=sites_list,
        sel_sites=sel_sites,
        from_date=from_date,
        to_date=to_date,
        last_update=last_update,
        chart_labels=chart_labels,
        chart_tch=chart_tch,
        chart_sdcch=chart_sdcch,
        chart_fullrate=chart_fullrate,
        chart_halfrate=chart_halfrate,
        chart_payload=chart_payload,
        chart_avail=chart_avail,
        chart_cssr=chart_cssr,
        chart_ccsr=chart_ccsr,
        chart_hosr=chart_hosr,
        chart_tchblk=chart_tchblk,
        chart_tchblk_num=chart_tchblk_num,
        chart_sdcchblk=chart_sdcchblk,
        chart_sdcchblk_num=chart_sdcchblk_num,
        chart_sdsr=chart_sdsr,
        chart_tbf_est=chart_tbf_est,
        chart_tbf_comp=chart_tbf_comp,
        chart_tch_drop=chart_tch_drop,
        chart_tch_drop_num=chart_tch_drop_num,
        chart_fastreturn=chart_fastreturn,
        chart_icm=chart_icm,
        chart_interference=chart_interference,
        active_count=active_count,
    )))
