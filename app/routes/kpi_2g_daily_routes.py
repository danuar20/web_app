"""2G KPI Daily Routes — /kpi_2g_daily (BSC Level & Site Level)"""
from flask import Blueprint, render_template, request, session, make_response, flash
from app.db.db_pumaz import get_pumaz_connection
from ._utils import login_required, _no_cache
import psycopg2
import psycopg2.errors

kpi2g_daily = Blueprint("kpi2g_daily", __name__)

# ── Shared helpers ──────────────────────────────────────────────────────────────
def _fv(v): return round(float(v), 2) if v is not None else 0
def _pv(v): return round(float(v), 2) if v is not None else None


# ── 2G KPI Daily (BSC Level & Site Level) ─────────────────────────────────────
@kpi2g_daily.route("/kpi_2g_daily")
@login_required
def kpi_2g_daily():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_bscs  = request.args.getlist("bsc")
    sel_sites = request.args.getlist("site")
    view_mode = request.args.get("view", "bsc")  # "bsc" or "site"

    bsc_list    = []
    site_list   = []
    table_rows  = []
    last_update = None
    active_bscs  = 0
    active_sites = 0
    # Chart data for daily view
    chart_labels  = []
    chart_tch      = {}
    chart_sdcch    = {}
    chart_payload  = {}
    chart_avail    = {}
    chart_access   = {}
    chart_ret      = {}
    chart_ho       = {}
    chart_tchblk   = {}
    chart_sdcchblk = {}
    chart_sdsr     = {}
    chart_tbf_est  = {}
    chart_tch_drop = {}
    chart_tbf_comp = {}
    chart_sd2tch   = {}
    chart_icm      = {}
    chart_dl_rxq   = {}
    chart_ul_rxq   = {}

    conn = None
    cur  = None
    try:
        conn = get_pumaz_connection()
        cur  = conn.cursor()

        # Last data update
        try:
            cur.execute('SELECT MAX("Date") FROM "measKpiDy2G"')
            raw_last = cur.fetchone()
            last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
        except Exception:
            last_update = None

        # Load BSC list
        try:
            cur.execute('SELECT DISTINCT "BSC Name" FROM "measKpiDy2G" WHERE "BSC Name" IS NOT NULL ORDER BY "BSC Name"')
            bsc_list = [r[0] for r in cur.fetchall()]
        except Exception:
            bsc_list = []

        # Load Site list — extract site ID from "Site Name" using Excel MID/LEFT convention:
        # Formula: IF char-2 is "-" or "_" → MID(name,3,6), ELSE → LEFT(name,6)
        # In Python: position 1 (0-indexed) is char-2 (1-indexed)
        def extract_2g_site_id(name):
            if name and len(name) >= 3 and name[1] in ("-", "_"):
                return name[2:8].strip() if len(name) >= 8 else name.strip()
            return name[:6].strip() if name else ""
        try:
            cur.execute('SELECT DISTINCT "Site Name" FROM "measKpiDy2G" WHERE "Site Name" IS NOT NULL ORDER BY "Site Name"')
            all_names = [r[0] for r in cur.fetchall()]
            site_list = []
            seen = set()
            for name in all_names:
                sid = extract_2g_site_id(name)
                if sid and sid not in seen:
                    seen.add(sid)
                    site_list.append(sid)
            site_list.sort()
        except Exception:
            site_list = []

        # Only run queries when a date range is explicitly provided
        if from_date and to_date:
            # ── BSC Level ────────────────────────────────────────────────────────
            if view_mode == "bsc":
                bsc_filter = 'AND "BSC Name" = ANY(%s)' if sel_bscs else ""
                params_bsc = [sel_bscs] if sel_bscs else []

                cur.execute(f"""
                    SELECT
                        "Date"::date AS date,
                        "BSC Name",
                        ROUND(SUM("TCH Traffic (erl)")::numeric, 2) AS tch_traffic,
                        ROUND(SUM("SDCCH Traffic (erl)")::numeric, 2) AS sdcch_traffic,
                        ROUND((SUM("EDGE DL Payload (Mbyte)")::numeric
                              +SUM("EDGE UL Payload (Mbyte)")::numeric
                              +SUM("GPRS Payload (Mbyte)")::numeric), 2)::numeric AS payload_mb,
                        CASE WHEN SUM("TCH Availability Denum")::numeric > 0
                             THEN ROUND(SUM("TCH Availability Num")::numeric
                                      / SUM("TCH Availability Denum")::numeric * 100, 2)
                             ELSE NULL END AS avail_pct,
                        CASE WHEN SUM("2g_cssr_denum")::numeric > 0
                             THEN ROUND(SUM("2g_cssr_num")::numeric
                                      / SUM("2g_cssr_denum")::numeric * 100, 2)
                             ELSE NULL END AS cssr_pct,
                        CASE WHEN SUM("2g_ccsr_denum")::numeric > 0
                             THEN ROUND(SUM("2g_ccsr_num")::numeric
                                      / SUM("2g_ccsr_denum")::numeric * 100, 2)
                             ELSE NULL END AS ccsr_pct,
                        CASE WHEN SUM("HOSR Denum")::numeric > 0
                             THEN ROUND(SUM("HOSR Num")::numeric
                                      / SUM("HOSR Denum")::numeric * 100, 2)
                             ELSE NULL END AS hosr_pct,
                        CASE WHEN SUM("TCH Block Denum")::numeric > 0
                             THEN ROUND(SUM("TCH Block Num")::numeric
                                      / SUM("TCH Block Denum")::numeric * 100, 2)
                             ELSE NULL END AS tch_blk_pct,
                        ROUND(SUM("TCH Block Num")::numeric, 0) AS tch_blk_num,
                        CASE WHEN SUM("SDCCH Block Denum")::numeric > 0
                             THEN ROUND(SUM("SDCCH Block Num")::numeric
                                      / SUM("SDCCH Block Denum")::numeric * 100, 2)
                             ELSE NULL END AS sdcch_blk_pct,
                        ROUND(SUM("SDCCH Block Num")::numeric, 0) AS sdcch_blk_num,
                        CASE WHEN SUM("SDSR Denum")::numeric > 0
                             THEN ROUND(SUM("SDSR Num")::numeric
                                      / SUM("SDSR Denum")::numeric * 100, 2)
                             ELSE NULL END AS sdsr_pct,
                        CASE WHEN SUM("TBF Establishment Denum")::numeric > 0
                             THEN ROUND(SUM("TBF Establishment Num")::numeric
                                      / SUM("TBF Establishment Denum")::numeric * 100, 2)
                             ELSE NULL END AS tbf_est_pct,
                        CASE WHEN SUM("TCH Drop Denum")::numeric > 0
                             THEN ROUND(SUM("TCH Drop Num")::numeric
                                      / SUM("TCH Drop Denum")::numeric * 100, 2)
                             ELSE NULL END AS tch_drop_pct,
                        ROUND(SUM("TCH Drop Num")::numeric, 0) AS tch_drop_num,
                        CASE WHEN SUM("TBF Completion Denum")::numeric > 0
                             THEN ROUND(SUM("TBF Completion Num")::numeric
                                      / SUM("TBF Completion Denum")::numeric * 100, 2)
                             ELSE NULL END AS tbf_comp_pct,
                        CASE WHEN SUM("SD To TCH Denum")::numeric > 0
                             THEN ROUND(SUM("SD To TCH Num")::numeric
                                      / SUM("SD To TCH Denum")::numeric * 100, 2)
                             ELSE NULL END AS sd2tch_pct,
                        ROUND(SUM("Fastreturn to LTE")::numeric, 0) AS fastreturn,
                        CASE WHEN SUM("DeNum ICM Band 3-5")::numeric > 0
                             THEN ROUND(SUM("Num ICM Band 3-5")::numeric
                                      / SUM("DeNum ICM Band 3-5")::numeric * 100, 2)
                             ELSE NULL END AS icm_pct,
                        CASE WHEN SUM("Denum DL RxQual 0-4")::numeric > 0
                             THEN ROUND(SUM("Num DL RxQual 0-4")::numeric
                                      / SUM("Denum DL RxQual 0-4")::numeric * 100, 2)
                             ELSE NULL END AS dl_rxq_pct,
                        CASE WHEN SUM("Denum UL RxQual 0-4")::numeric > 0
                             THEN ROUND(SUM("Num UL RxQual 0-4")::numeric
                                      / SUM("Denum UL RxQual 0-4")::numeric * 100, 2)
                             ELSE NULL END AS ul_rxq_pct
                    FROM "measKpiDy2G"
                    WHERE "Date" BETWEEN %s AND %s {bsc_filter}
                    GROUP BY "Date"::date, "BSC Name"
                    ORDER BY "Date"::date, "BSC Name"
                """, [from_date, to_date] + params_bsc)

                # Build data: {date_str: {bsc_name: row_tuple}}
                rows_data = cur.fetchall()
                date_dict = {}
                timestamps_set = set()
                bscs_in_data = set()
                for r in rows_data:
                    date_str = r[0].strftime("%Y-%m-%d") if r[0] else ""
                    bsc = (r[1] or "").strip()
                    timestamps_set.add(date_str)
                    bscs_in_data.add(bsc)
                    if date_str not in date_dict:
                        date_dict[date_str] = {}
                    date_dict[date_str][bsc] = r

                chart_labels = sorted(timestamps_set)

                # Table rows: per-date, per-BSC
                for r in rows_data:
                    table_rows.append({
                        "bsc":        r[1],
                        "date":       r[0].strftime("%Y-%m-%d") if r[0] else "",
                        "tch":        float(r[2]) if r[2] is not None else None,
                        "sdcch":      float(r[3]) if r[3] is not None else None,
                        "payload":    float(r[4]) if r[4] is not None else 0,
                        "avail":      float(r[5]) if r[5] is not None else None,
                        "access":     float(r[6]) if r[6] is not None else None,
                        "ret":        float(r[7]) if r[7] is not None else None,
                        "ho":         float(r[8]) if r[8] is not None else None,
                        "tchblk":     float(r[9]) if r[9] is not None else None,
                        "tchblk_n":   int(float(r[10])) if r[10] is not None else 0,
                        "sdcchblk":   float(r[11]) if r[11] is not None else None,
                        "sdcchblk_n": int(float(r[12])) if r[12] is not None else 0,
                        "sdsr":       float(r[13]) if r[13] is not None else None,
                        "tbf_est":    float(r[14]) if r[14] is not None else None,
                        "tch_drop":   float(r[15]) if r[15] is not None else None,
                        "tch_drop_n": int(float(r[16])) if r[16] is not None else 0,
                        "tbf_comp":   float(r[17]) if r[17] is not None else None,
                        "sd2tch":     float(r[18]) if r[18] is not None else None,
                        "fastreturn": int(float(r[19])) if r[19] is not None else 0,
                        "icm":        float(r[20]) if r[20] is not None else None,
                        "dl_rxq":     float(r[21]) if r[21] is not None else None,
                        "ul_rxq":     float(r[22]) if r[22] is not None else None,
                    })

                active_bscs = len(bscs_in_data)

                # Build chart datasets: BSC name -> list of values per date (chart_labels order)
                for bsc in sorted(bscs_in_data):
                    vals = []
                    for ts in chart_labels:
                        day_data = date_dict.get(ts, {}).get(bsc)
                        if day_data:
                            vals.append(_fv(day_data[2]))   # tch
                        else:
                            vals.append(_fv(None))
                    chart_tch[bsc] = vals

                for bsc in sorted(bscs_in_data):
                    vals = []
                    for ts in chart_labels:
                        day_data = date_dict.get(ts, {}).get(bsc)
                        vals.append(_fv(day_data[3]) if day_data else None)
                    chart_sdcch[bsc] = vals

                for bsc in sorted(bscs_in_data):
                    vals = []
                    for ts in chart_labels:
                        day_data = date_dict.get(ts, {}).get(bsc)
                        vals.append(_fv(day_data[4]) if day_data else None)
                    chart_payload[bsc] = vals

                for idx, field in enumerate([(5,'avail',chart_avail),(6,'access',chart_access),(7,'ret',chart_ret),
                                             (8,'ho',chart_ho),(9,'tchblk',chart_tchblk),(11,'sdcchblk',chart_sdcchblk),
                                             (13,'sdsr',chart_sdsr),(14,'tbf_est',chart_tbf_est),(15,'tch_drop',chart_tch_drop),
                                             (17,'tbf_comp',chart_tbf_comp),(18,'sd2tch',chart_sd2tch),(20,'icm',chart_icm),
                                             (21,'dl_rxq',chart_dl_rxq),(22,'ul_rxq',chart_ul_rxq)]):
                    fi, name, target = field
                    for bsc in sorted(bscs_in_data):
                        vals = []
                        for ts in chart_labels:
                            day_data = date_dict.get(ts, {}).get(bsc)
                            vals.append(_pv(day_data[fi]) if day_data else None)
                        target[bsc] = vals

            # ── Site Level ───────────────────────────────────────────────────────
            elif view_mode == "site":
                # Site ID formula: IF char-2 is "-" or "_" → SUBSTRING(name,3,6), ELSE → SUBSTRING(name,1,6)
                site_filter_expr = (
                    'CASE WHEN SUBSTRING("Site Name", 2, 1) IN (\'-\', \'_\') '
                    'THEN TRIM(SUBSTRING("Site Name", 3, 6)) '
                    'ELSE TRIM(SUBSTRING("Site Name", 1, 6)) END'
                )
                site_filter = f'AND {site_filter_expr} = ANY(%s)' if sel_sites else ""
                params_site = [sel_sites] if sel_sites else []

                cur.execute(f"""
                    SELECT
                        "Date"::date AS date,
                        {site_filter_expr} AS site_id,
                        ROUND(SUM("TCH Traffic (erl)")::numeric, 2) AS tch_traffic,
                        ROUND(SUM("SDCCH Traffic (erl)")::numeric, 2) AS sdcch_traffic,
                        ROUND((SUM("EDGE DL Payload (Mbyte)")::numeric
                              +SUM("EDGE UL Payload (Mbyte)")::numeric
                              +SUM("GPRS Payload (Mbyte)")::numeric), 2)::numeric AS payload_mb,
                        CASE WHEN SUM("TCH Availability Denum")::numeric > 0
                             THEN ROUND(SUM("TCH Availability Num")::numeric
                                      / SUM("TCH Availability Denum")::numeric * 100, 2)
                             ELSE NULL END AS avail_pct,
                        CASE WHEN SUM("2g_cssr_denum")::numeric > 0
                             THEN ROUND(SUM("2g_cssr_num")::numeric
                                      / SUM("2g_cssr_denum")::numeric * 100, 2)
                             ELSE NULL END AS cssr_pct,
                        CASE WHEN SUM("2g_ccsr_denum")::numeric > 0
                             THEN ROUND(SUM("2g_ccsr_num")::numeric
                                      / SUM("2g_ccsr_denum")::numeric * 100, 2)
                             ELSE NULL END AS ccsr_pct,
                        CASE WHEN SUM("HOSR Denum")::numeric > 0
                             THEN ROUND(SUM("HOSR Num")::numeric
                                      / SUM("HOSR Denum")::numeric * 100, 2)
                             ELSE NULL END AS hosr_pct,
                        CASE WHEN SUM("TCH Block Denum")::numeric > 0
                             THEN ROUND(SUM("TCH Block Num")::numeric
                                      / SUM("TCH Block Denum")::numeric * 100, 2)
                             ELSE NULL END AS tch_blk_pct,
                        ROUND(SUM("TCH Block Num")::numeric, 0) AS tch_blk_num,
                        CASE WHEN SUM("SDCCH Block Denum")::numeric > 0
                             THEN ROUND(SUM("SDCCH Block Num")::numeric
                                      / SUM("SDCCH Block Denum")::numeric * 100, 2)
                             ELSE NULL END AS sdcch_blk_pct,
                        ROUND(SUM("SDCCH Block Num")::numeric, 0) AS sdcch_blk_num,
                        CASE WHEN SUM("SDSR Denum")::numeric > 0
                             THEN ROUND(SUM("SDSR Num")::numeric
                                      / SUM("SDSR Denum")::numeric * 100, 2)
                             ELSE NULL END AS sdsr_pct,
                        CASE WHEN SUM("TBF Establishment Denum")::numeric > 0
                             THEN ROUND(SUM("TBF Establishment Num")::numeric
                                      / SUM("TBF Establishment Denum")::numeric * 100, 2)
                             ELSE NULL END AS tbf_est_pct,
                        CASE WHEN SUM("TCH Drop Denum")::numeric > 0
                             THEN ROUND(SUM("TCH Drop Num")::numeric
                                      / SUM("TCH Drop Denum")::numeric * 100, 2)
                             ELSE NULL END AS tch_drop_pct,
                        ROUND(SUM("TCH Drop Num")::numeric, 0) AS tch_drop_num,
                        CASE WHEN SUM("TBF Completion Denum")::numeric > 0
                             THEN ROUND(SUM("TBF Completion Num")::numeric
                                      / SUM("TBF Completion Denum")::numeric * 100, 2)
                             ELSE NULL END AS tbf_comp_pct,
                        CASE WHEN SUM("SD To TCH Denum")::numeric > 0
                             THEN ROUND(SUM("SD To TCH Num")::numeric
                                      / SUM("SD To TCH Denum")::numeric * 100, 2)
                             ELSE NULL END AS sd2tch_pct,
                        ROUND(SUM("Fastreturn to LTE")::numeric, 0) AS fastreturn,
                        CASE WHEN SUM("DeNum ICM Band 3-5")::numeric > 0
                             THEN ROUND(SUM("Num ICM Band 3-5")::numeric
                                      / SUM("DeNum ICM Band 3-5")::numeric * 100, 2)
                             ELSE NULL END AS icm_pct,
                        CASE WHEN SUM("Denum DL RxQual 0-4")::numeric > 0
                             THEN ROUND(SUM("Num DL RxQual 0-4")::numeric
                                      / SUM("Denum DL RxQual 0-4")::numeric * 100, 2)
                             ELSE NULL END AS dl_rxq_pct,
                        CASE WHEN SUM("Denum UL RxQual 0-4")::numeric > 0
                             THEN ROUND(SUM("Num UL RxQual 0-4")::numeric
                                      / SUM("Denum UL RxQual 0-4")::numeric * 100, 2)
                             ELSE NULL END AS ul_rxq_pct
                    FROM "measKpiDy2G"
                    WHERE "Date" BETWEEN %s AND %s {site_filter}
                    GROUP BY "Date"::date, {site_filter_expr}
                    ORDER BY "Date"::date, site_id
                """, [from_date, to_date] + params_site)

                rows_data = cur.fetchall()
                date_dict = {}
                timestamps_set = set()
                sites_in_data = set()
                for r in rows_data:
                    date_str = r[0].strftime("%Y-%m-%d") if r[0] else ""
                    site = (r[1] or "").strip()
                    timestamps_set.add(date_str)
                    sites_in_data.add(site)
                    if date_str not in date_dict:
                        date_dict[date_str] = {}
                    date_dict[date_str][site] = r

                chart_labels = sorted(timestamps_set)

                for r in rows_data:
                    table_rows.append({
                        "site":       (r[1] or "").strip(),
                        "date":       r[0].strftime("%Y-%m-%d") if r[0] else "",
                        "tch":        float(r[2]) if r[2] is not None else None,
                        "sdcch":      float(r[3]) if r[3] is not None else None,
                        "payload":    float(r[4]) if r[4] is not None else 0,
                        "avail":      float(r[5]) if r[5] is not None else None,
                        "access":     float(r[6]) if r[6] is not None else None,
                        "ret":        float(r[7]) if r[7] is not None else None,
                        "ho":         float(r[8]) if r[8] is not None else None,
                        "tchblk":     float(r[9]) if r[9] is not None else None,
                        "tchblk_n":   int(float(r[10])) if r[10] is not None else 0,
                        "sdcchblk":   float(r[11]) if r[11] is not None else None,
                        "sdcchblk_n": int(float(r[12])) if r[12] is not None else 0,
                        "sdsr":       float(r[13]) if r[13] is not None else None,
                        "tbf_est":    float(r[14]) if r[14] is not None else None,
                        "tch_drop":   float(r[15]) if r[15] is not None else None,
                        "tch_drop_n": int(float(r[16])) if r[16] is not None else 0,
                        "tbf_comp":   float(r[17]) if r[17] is not None else None,
                        "sd2tch":     float(r[18]) if r[18] is not None else None,
                        "fastreturn": int(float(r[19])) if r[19] is not None else 0,
                        "icm":        float(r[20]) if r[20] is not None else None,
                        "dl_rxq":     float(r[21]) if r[21] is not None else None,
                        "ul_rxq":     float(r[22]) if r[22] is not None else None,
                    })

                active_sites = len(sites_in_data)

                for site in sorted(sites_in_data):
                    def _safe(ts, idx, default=None):
                        r = date_dict.get(ts, {}).get(site)
                        if r is None: return default
                        if idx < 0 or idx >= len(r): return default
                        v = r[idx]
                        return default if v is None else v

                    chart_tch[site]      = [_fv(_safe(ts, 2)) for ts in chart_labels]
                    chart_sdcch[site]    = [_fv(_safe(ts, 3)) for ts in chart_labels]
                    chart_payload[site]  = [_fv(_safe(ts, 4)) for ts in chart_labels]
                    chart_avail[site]    = [_pv(_safe(ts, 5)) for ts in chart_labels]
                    chart_access[site]   = [_pv(_safe(ts, 6)) for ts in chart_labels]
                    chart_ret[site]      = [_pv(_safe(ts, 7)) for ts in chart_labels]
                    chart_ho[site]       = [_pv(_safe(ts, 8)) for ts in chart_labels]
                    chart_tchblk[site]   = [_pv(_safe(ts, 9)) for ts in chart_labels]
                    chart_sdcchblk[site] = [_pv(_safe(ts, 11)) for ts in chart_labels]
                    chart_sdsr[site]     = [_pv(_safe(ts, 13)) for ts in chart_labels]
                    chart_tbf_est[site]  = [_pv(_safe(ts, 14)) for ts in chart_labels]
                    chart_tch_drop[site] = [_pv(_safe(ts, 15)) for ts in chart_labels]
                    chart_tbf_comp[site] = [_pv(_safe(ts, 17)) for ts in chart_labels]
                    chart_sd2tch[site]   = [_pv(_safe(ts, 18)) for ts in chart_labels]
                    chart_icm[site]      = [_pv(_safe(ts, 20)) for ts in chart_labels]
                    chart_dl_rxq[site]   = [_pv(_safe(ts, 21)) for ts in chart_labels]
                    chart_ul_rxq[site]   = [_pv(_safe(ts, 22)) for ts in chart_labels]

        cur.close(); conn.close()
        cur = None; conn = None

    except psycopg2.OperationalError:
        if conn: conn.rollback()
        if cur: cur.close()
        if conn: conn.close()
        flash("PUMAZ database connection failed. Please try again.", "warning")
    except psycopg2.errors.QueryCanceled:
        if conn: conn.rollback()
        if cur: cur.close()
        if conn: conn.close()
        flash("Query timed out. Please try a shorter date range.", "warning")
    except psycopg2.errors.ConnectionDoesNotExist:
        if conn: conn.rollback()
        if cur: cur.close()
        if conn: conn.close()
        flash("Database server unreachable. Please try again later.", "warning")
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        if cur: cur.close()
        if conn: conn.close()
        flash(f"Error: {str(e)}", "danger")

    kpi_defaults = [
        {"id": "availChart",    "label": "Availability",      "unit": "%", "defaultMin": 95,   "defaultMax": 100},
        {"id": "accessChart",   "label": "Accessibility",    "unit": "%", "defaultMin": 85,   "defaultMax": 100},
        {"id": "retChart",      "label": "Retainability",    "unit": "%", "defaultMin": 90,   "defaultMax": 100},
        {"id": "hoChart",       "label": "HO SR",             "unit": "%", "defaultMin": 85,   "defaultMax": 100},
        {"id": "tchblkChart",   "label": "TCH Blocking",      "unit": "%", "defaultMin": 0,    "defaultMax": 3},
        {"id": "sdcchblkChart", "label": "SDCCH Blocking",   "unit": "%", "defaultMin": 0,    "defaultMax": 3},
        {"id": "sdsrChart",     "label": "SDSR",              "unit": "%", "defaultMin": 90,   "defaultMax": 100},
        {"id": "tbfEstChart",   "label": "TBF Establishment", "unit": "%","defaultMin": 80,   "defaultMax": 100},
        {"id": "tchDropChart",  "label": "TCH Drop",          "unit": "%", "defaultMin": 0,    "defaultMax": 3},
        {"id": "tbfCompChart",  "label": "TBF Completion",   "unit": "%", "defaultMin": 80,   "defaultMax": 100},
        {"id": "sd2tchChart",   "label": "SD to TCH SR",     "unit": "%", "defaultMin": 85,   "defaultMax": 100},
        {"id": "icmChart",      "label": "ICM Band 3-5",      "unit": "%", "defaultMin": 90,   "defaultMax": 100},
        {"id": "dlRxqChart",    "label": "DL RxQual 0-4",    "unit": "%", "defaultMin": 90,   "defaultMax": 100},
        {"id": "ulRxqChart",    "label": "UL RxQual 0-4",   "unit": "%", "defaultMin": 90,   "defaultMax": 100},
    ]

    return _no_cache(make_response(render_template(
        "kpi_2g_daily.html",
        username=session["username"],
        bsc_list=bsc_list, site_list=site_list,
        sel_bscs=sel_bscs, sel_sites=sel_sites,
        from_date=from_date, to_date=to_date,
        view_mode=view_mode,
        last_update=last_update,
        table_rows=table_rows,
        active_bscs=active_bscs,
        active_sites=active_sites,
        kpi_defaults=kpi_defaults,
        chart_labels=chart_labels,
        chart_tch=chart_tch, chart_sdcch=chart_sdcch, chart_payload=chart_payload,
        chart_avail=chart_avail, chart_access=chart_access, chart_ret=chart_ret,
        chart_ho=chart_ho, chart_tchblk=chart_tchblk, chart_sdcchblk=chart_sdcchblk,
        chart_sdsr=chart_sdsr, chart_tbf_est=chart_tbf_est, chart_tch_drop=chart_tch_drop,
        chart_tbf_comp=chart_tbf_comp, chart_sd2tch=chart_sd2tch,
        chart_icm=chart_icm, chart_dl_rxq=chart_dl_rxq, chart_ul_rxq=chart_ul_rxq,
    )))