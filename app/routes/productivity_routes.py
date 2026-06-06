from flask import Blueprint, make_response, redirect, render_template, request, session, flash, url_for
from app.db.db_pumaz import get_pumaz_connection
from ._utils import login_required, _no_cache, ytd_pct
from datetime import datetime, timedelta
from collections import OrderedDict
import psycopg2
import psycopg2.errors

prod = Blueprint("prod", __name__)

# ── Productivity ───────────────────────────────────────────────────────────────
@prod.route("/productivity")
@login_required
def productivity():
    year_before = request.args.get("year_before", "")
    year_after  = request.args.get("year_after",  "")
    sel_nsas    = request.args.getlist("nsa")

    # Auto-select most-recent and previous year when page first loads (no args)
    # Then redirect so the URL carries the params and data loads on this same request
    if not year_before and not year_after:
        try:
            conn_default = get_pumaz_connection()
            cur_default = conn_default.cursor()
            cur_default.execute('SELECT DISTINCT "Year by Date" FROM traffic_payload WHERE "Year by Date" IS NOT NULL ORDER BY "Year by Date" DESC LIMIT 2')
            rows = [r[0] for r in cur_default.fetchall()]
            cur_default.close(); conn_default.close()
            if len(rows) >= 2:
                return redirect(url_for("prod.productivity", year_before=str(rows[1]), year_after=str(rows[0])))
            elif len(rows) == 1:
                return redirect(url_for("prod.productivity", year_after=str(rows[0])))
        except Exception:
            pass

    chart_labels   = []
    payload_before = []; payload_after = []; payload_ytd = []
    traffic_before = []; traffic_after = []; traffic_ytd = []
    table_rows     = []

    total_payload_after = 0.0; total_traffic_after = 0.0
    peak_payload_after  = 0.0
    ytd_payload_final  = None; ytd_traffic_final = None
    last_date_after_str = ""; data_days = 0
    years_list = []; nsas_list = []
    filter_error = None

    try:
        conn = get_pumaz_connection()
        cur  = conn.cursor()

        cur.execute('SELECT DISTINCT "Year by Date" FROM traffic_payload WHERE "Year by Date" IS NOT NULL ORDER BY "Year by Date"')
        years_list = [r[0] for r in cur.fetchall()]

        cur.execute('SELECT DISTINCT "NSA" FROM traffic_payload WHERE "NSA" IS NOT NULL ORDER BY "NSA"')
        nsas_list = [r[0] for r in cur.fetchall()]

        if year_before and year_after:
            if year_before >= year_after:
                filter_error = "Year Before harus lebih kecil dari Year After!"
            else:
                nsa_clause  = 'AND "NSA" = ANY(%s)' if sel_nsas else ""
                base_params = [sel_nsas] if sel_nsas else []

                cur.execute(f'SELECT MAX("Date") FROM traffic_payload WHERE "Year by Date" = %s {nsa_clause}',
                            [year_before] + base_params)
                max_date_before = (cur.fetchone() or [None])[0]

                if max_date_before is None:
                    flash(f"Tidak ada data untuk Year Before = {year_before}.", "warning")
                else:
                    if isinstance(max_date_before, datetime):
                        max_date_before = max_date_before.date()

                cur.execute(f'SELECT MAX("Date") FROM traffic_payload WHERE "Year by Date" = %s {nsa_clause}',
                            [year_after] + base_params)
                max_date_after = (cur.fetchone() or [None])[0]

                if max_date_after is None:
                    flash(f"Tidak ada data untuk Year After = {year_after}.", "warning")
                else:
                    if isinstance(max_date_after, datetime):
                        max_date_after = max_date_after.date()
                    last_date_after_str = max_date_after.strftime("%d %b %Y")

                    cur.execute(f"""
                        SELECT
                            EXTRACT(DOY FROM "Date")::INT AS day_of_year,
                            "Year by Date",
                            SUM("Payload (MB)")/1024.0/1024.0,
                            SUM("Traffic (erlang)")/1000.0
                        FROM traffic_payload
                        WHERE ("Year by Date"=%s OR "Year by Date"=%s) {nsa_clause}
                        AND NOT (EXTRACT(MONTH FROM "Date") = 2 AND EXTRACT(DAY FROM "Date") = 29)
                        GROUP BY EXTRACT(DOY FROM "Date")::INT, "Year by Date"
                        ORDER BY EXTRACT(DOY FROM "Date")::INT, "Year by Date"
                    """, [year_before, year_after] + ([sel_nsas] if sel_nsas else []))

                    day_map = {}
                    for r in cur.fetchall():
                        doy = int(r[0])
                        year = r[1]
                        payload = float(r[2] or 0)
                        traffic = float(r[3] or 0)
                        if doy not in day_map:
                            day_map[doy] = {}
                        day_map[doy][year] = {"payload": payload, "traffic": traffic}

                    is_before_complete = (max_date_before.month == 12 and max_date_before.day == 31)
                    max_doy_before = 366 if is_before_complete else max_date_before.timetuple().tm_yday
                    max_doy_after = max_date_after.timetuple().tm_yday
                    max_doy_to_show = max(max_doy_before, max_doy_after)

                    cum_pb = cum_pa = cum_tb = cum_ta = 0.0
                    ytd_p_list = []; ytd_t_list = []

                    def doy_to_ddmm(doy, year):
                        return (datetime(year, 1, 1) + timedelta(days=doy - 1)).strftime("%d %b")

                    for doy in range(1, max_doy_to_show + 1):
                        day_data = day_map.get(doy, {})
                        before_data = day_data.get(year_before, {})
                        after_data  = day_data.get(year_after, {})
                        pb = float(before_data.get("payload", 0))
                        pa = float(after_data.get("payload", 0))
                        tb = float(before_data.get("traffic", 0))
                        ta = float(after_data.get("traffic", 0))

                        chart_labels.append(doy_to_ddmm(doy, int(year_after)))
                        payload_before.append(pb if pb else None)
                        payload_after.append(pa if pa else None)
                        traffic_before.append(tb if tb else None)
                        traffic_after.append(ta if ta else None)

                        cum_pb += pb; cum_tb += tb
                        cum_pa += pa; cum_ta += ta

                        if doy <= max_doy_after:
                            yp = round((cum_pa - cum_pb) / cum_pb * 100, 2) if cum_pb > 0 else None
                            yt = round((cum_ta - cum_tb) / cum_tb * 100, 2) if cum_tb > 0 else None
                        else:
                            yp = None; yt = None

                        payload_ytd.append(yp); traffic_ytd.append(yt)
                        if yp is not None: ytd_p_list.append(yp)
                        if yt is not None: ytd_t_list.append(yt)

                    ytd_payload_final = ytd_p_list[-1] if ytd_p_list else None
                    ytd_traffic_final = ytd_t_list[-1] if ytd_t_list else None

                    cur.execute(f"""
                        SELECT "Regional","NSA","TO",
                            SUM(CASE WHEN "Year by Date"=%s THEN "Payload (MB)" END)/1024.0/1024.0,
                            SUM(CASE WHEN "Year by Date"=%s THEN "Payload (MB)" END)/1024.0/1024.0,
                            SUM(CASE WHEN "Year by Date"=%s THEN "Traffic (erlang)" END)/1000.0,
                            SUM(CASE WHEN "Year by Date"=%s THEN "Traffic (erlang)" END)/1000.0
                        FROM traffic_payload
                        WHERE (
                            ("Year by Date"=%s AND EXTRACT(DOY FROM "Date") <= EXTRACT(DOY FROM %s::date))
                            OR
                            ("Year by Date"=%s AND EXTRACT(DOY FROM "Date") <= EXTRACT(DOY FROM %s::date))
                        )
                        {nsa_clause}
                        AND NOT (EXTRACT(MONTH FROM "Date") = 2 AND EXTRACT(DAY FROM "Date") = 29)
                        GROUP BY "Regional","NSA","TO"
                        ORDER BY "Regional","NSA","TO"
                    """,
                    [year_before, year_after, year_before, year_after,
                     year_before, max_date_after, year_after, max_date_after] + base_params)

                    regional_data = OrderedDict()
                    for r in cur.fetchall():
                        reg = r[0] or "N/A"; nop = r[1] or "N/A"; to_ = r[2] or "N/A"
                        pb = float(r[3] or 0); pa = float(r[4] or 0)
                        tb = float(r[5] or 0); ta = float(r[6] or 0)
                        regional_data.setdefault(reg, OrderedDict()).setdefault(nop, {})[to_] = {
                            "pb": pb, "pa": pa, "tb": tb, "ta": ta
                        }

                    for reg, nops in regional_data.items():
                        reg_pb=reg_pa=reg_tb=reg_ta=0.0; nop_rows=[]
                        for nop, tos in nops.items():
                            nop_pb=nop_pa=nop_tb=nop_ta=0.0; to_rows=[]
                            for to_, v in tos.items():
                                nop_pb+=v["pb"]; nop_pa+=v["pa"]
                                nop_tb+=v["tb"]; nop_ta+=v["ta"]
                                to_rows.append({"level":"to","label":to_,
                                    "p_before":round(v["pb"],2),"p_after":round(v["pa"],2),"ytd_p":ytd_pct(v["pa"],v["pb"]),
                                    "t_before":round(v["tb"],1),"t_after":round(v["ta"],1),"ytd_t":ytd_pct(v["ta"],v["tb"])})
                            reg_pb+=nop_pb; reg_pa+=nop_pa; reg_tb+=nop_tb; reg_ta+=nop_ta
                            nop_rows.append({"level":"nop","label":nop,
                                "p_before":round(nop_pb,2),"p_after":round(nop_pa,2),"ytd_p":ytd_pct(nop_pa,nop_pb),
                                "t_before":round(nop_tb,1),"t_after":round(nop_ta,1),"ytd_t":ytd_pct(nop_ta,nop_tb),
                                "children":to_rows})
                        table_rows.append({"level":"regional","label":reg,
                            "p_before":round(reg_pb,2),"p_after":round(reg_pa,2),"ytd_p":ytd_pct(reg_pa,reg_pb),
                            "t_before":round(reg_tb,1),"t_after":round(reg_ta,1),"ytd_t":ytd_pct(reg_ta,reg_tb),
                            "children":nop_rows})

                    pa_vals = [v for v in payload_after if v is not None]
                    ta_vals = [v for v in traffic_after if v is not None]
                    total_payload_after = sum(pa_vals)
                    total_traffic_after = sum(ta_vals)
                    peak_payload_after  = max(pa_vals) if pa_vals else 0.0
                    data_days = len(pa_vals)

        cur.close(); conn.close()
    except psycopg2.OperationalError:
        flash("Database connection failed. Please try again.", "warning")
    except psycopg2.errors.QueryCanceled:
        flash("Query timed out. Please try a shorter date range.", "warning")
    except psycopg2.errors.ConnectionDoesNotExist:
        flash("Database server unreachable. Please try again later.", "warning")
    except Exception as e:
        flash(f"Failed to fetch data: {str(e)}", "danger")

    return _no_cache(make_response(render_template(
        "productivity.html",
        username=session["username"],
        years_list=years_list,
        nsas_list=nsas_list,
        year_before=year_before,
        year_after=year_after,
        sel_nsas=sel_nsas,
        filter_error=filter_error,
        chart_labels=chart_labels,
        payload_before=payload_before,
        payload_after=payload_after,
        payload_ytd=payload_ytd,
        traffic_before=traffic_before,
        traffic_after=traffic_after,
        traffic_ytd=traffic_ytd,
        table_rows=table_rows,
        last_date_after=last_date_after_str,
        data_days=data_days,
        total_payload_after=total_payload_after,
        total_traffic_after=total_traffic_after,
        peak_payload_after=peak_payload_after,
        ytd_payload_final=ytd_payload_final,
        ytd_traffic_final=ytd_traffic_final,
    )))

# ── City Level ─────────────────────────────────────────────────────────────────
@prod.route("/city_level")
@login_required
def city_level():
    from_date   = request.args.get("from_date", "")
    to_date     = request.args.get("to_date", "")
    sel_nsas    = request.args.getlist("nsa")
    sel_cities  = request.args.getlist("city")
    yw_before   = request.args.get("yw_before", "")
    yw_after    = request.args.get("yw_after", "")

    chart_labels    = []
    chart_payload   = {}
    chart_traffic   = {}
    chart_availability = {}
    chart_rrc       = {}
    nsas_list = []; cities_list = []; filtered_cities = []; yw_list = []
    compare_table = []   # [{nsa, rows: [{city, pb, pa, pch, tb, ta, tch, ab, aa, ach, rb, ra, rch}]}]

    kpi_payload = 0.0; kpi_traffic = 0.0
    kpi_availability = None; kpi_rrc = 0.0

    try:
        conn = get_pumaz_connection(); cur = conn.cursor()

        cur.execute('SELECT DISTINCT "NSA" FROM traffic_payload WHERE "NSA" IS NOT NULL ORDER BY "NSA"')
        nsas_list = [r[0] for r in cur.fetchall()]

        cur.execute('SELECT DISTINCT "Y_W" FROM traffic_payload WHERE "Y_W" IS NOT NULL ORDER BY "Y_W" DESC LIMIT 104')
        yw_list = [r[0] for r in cur.fetchall()]

        if sel_nsas:
            cur.execute('SELECT DISTINCT "KABUPATEN" FROM traffic_payload WHERE "NSA"=ANY(%s) AND "KABUPATEN" IS NOT NULL ORDER BY "KABUPATEN"', (sel_nsas,))
        else:
            cur.execute('SELECT DISTINCT "KABUPATEN" FROM traffic_payload WHERE "KABUPATEN" IS NOT NULL ORDER BY "KABUPATEN"')
        cities_list = [r[0] for r in cur.fetchall()]
        filtered_cities = cities_list

        # ── Chart data (daily) ────────────────────────────────────────────────
        if from_date and to_date and sel_cities:
            nsa_clause  = 'AND "NSA"=ANY(%s)' if sel_nsas else ""
            base_params = [from_date, to_date, sel_cities] + ([sel_nsas] if sel_nsas else [])

            cur.execute(f"""
                SELECT
                    "Date"::text,
                    "KABUPATEN",
                    SUM("Payload (MB)")/1024.0,
                    SUM("Traffic (erlang)")/1000.0,
                    SUM(CASE WHEN "Avail_Num" IS NOT NULL AND "Avail_Denum" IS NOT NULL
                             AND "Avail_Denum" > 0 THEN "Avail_Num" END),
                    SUM(CASE WHEN "Avail_Denum" IS NOT NULL AND "Avail_Denum" > 0
                             THEN "Avail_Denum" END),
                    SUM("Max_RRC_Conn_User")
                FROM traffic_payload
                WHERE "Date" BETWEEN %s AND %s AND "KABUPATEN"=ANY(%s) {nsa_clause}
                GROUP BY "Date"::text,"KABUPATEN"
                ORDER BY 1,"KABUPATEN"
            """, base_params)

            months_seen = {}
            for r in cur.fetchall():
                fd   = str(r[0] or ''); city = str(r[1] or '')
                try: pg = float(r[2]) if r[2] is not None else 0.0
                except: pg = 0.0
                try: te = float(r[3]) if r[3] is not None else 0.0
                except: te = 0.0
                try: anum = float(r[4]) if r[4] is not None else 0.0
                except: anum = 0.0
                try: aden = float(r[5]) if r[5] is not None else 0.0
                except: aden = 0.0
                try: rrc = float(r[6]) if r[6] is not None else 0.0
                except: rrc = 0.0
                if fd not in months_seen: months_seen[fd] = fd
                chart_payload.setdefault(city, {})[fd] = round(pg, 2)
                chart_traffic.setdefault(city, {})[fd] = round(te, 1)
                chart_rrc.setdefault(city, {})[fd] = round(rrc, 0)
                av = round(anum / aden * 100, 2) if aden > 0 else 0.0
                chart_availability.setdefault(city, {})[fd] = av

            sorted_dates = sorted(months_seen.keys())
            chart_labels = sorted_dates
            for c in list(chart_payload.keys()):
                chart_payload[c]     = [chart_payload[c].get(d, 0)     for d in sorted_dates]
                chart_traffic[c]      = [chart_traffic[c].get(d, 0)      for d in sorted_dates]
                chart_availability[c] = [chart_availability[c].get(d, 0) for d in sorted_dates]
                chart_rrc[c]          = [chart_rrc[c].get(d, 0)          for d in sorted_dates]

            all_av = []
            for c in sel_cities:
                all_av.extend(chart_availability.get(c, []))
                kpi_payload += sum(chart_payload.get(c, []))
                kpi_traffic += sum(chart_traffic.get(c, []))
                kpi_rrc     += sum(chart_rrc.get(c, []))
            kpi_availability = round(sum(all_av)/len(all_av), 2) if all_av else None

        # ── Y_W Comparison Table ──────────────────────────────────────────────
        # If the UI shows "Semua Kota" but no explicit checkboxes were sent, treat as all cities
        if not sel_cities:
            sel_cities = cities_list

        if yw_before and yw_after and sel_cities:
            # Build query dynamically — number of placeholders always matches params
            p = [yw_before, yw_after, sel_cities]
            city_clause2 = ""
            nsa_clause2 = ""
            if sel_nsas:
                nsa_clause2 = 'AND t."NSA"=ANY(%s)'
                p.append(sel_nsas)

            cur.execute(f"""
                SELECT
                    t."NSA",
                    t."KABUPATEN",
                    SUM(CASE WHEN t."Y_W"=%s THEN t."Payload (MB)" END)/1024.0 AS pb,
                    SUM(CASE WHEN t."Y_W"=%s THEN t."Payload (MB)" END)/1024.0 AS pa,
                    SUM(CASE WHEN t."Y_W"=%s THEN t."Traffic (erlang)" END)/1000.0 AS tb,
                    SUM(CASE WHEN t."Y_W"=%s THEN t."Traffic (erlang)" END)/1000.0 AS ta,
                    SUM(CASE WHEN t."Y_W"=%s AND t."Avail_Num" IS NOT NULL
                                AND t."Avail_Denum" IS NOT NULL AND t."Avail_Denum">0
                             THEN t."Avail_Num" END) AS ab_num,
                    SUM(CASE WHEN t."Y_W"=%s AND t."Avail_Denum" IS NOT NULL AND t."Avail_Denum">0
                             THEN t."Avail_Denum" END) AS ab_den,
                    SUM(CASE WHEN t."Y_W"=%s AND t."Avail_Num" IS NOT NULL
                                AND t."Avail_Denum" IS NOT NULL AND t."Avail_Denum">0
                             THEN t."Avail_Num" END) AS aa_num,
                    SUM(CASE WHEN t."Y_W"=%s AND t."Avail_Denum" IS NOT NULL AND t."Avail_Denum">0
                             THEN t."Avail_Denum" END) AS aa_den,
                    SUM(CASE WHEN t."Y_W"=%s THEN t."Max_RRC_Conn_User" END) AS rb,
                    SUM(CASE WHEN t."Y_W"=%s THEN t."Max_RRC_Conn_User" END) AS ra
                FROM traffic_payload t
                WHERE t."Y_W" IN (%s,%s) {nsa_clause2} {city_clause2}
                GROUP BY t."NSA", t."KABUPATEN"
                ORDER BY t."NSA", t."KABUPATEN"
            """, p)

            def pct(a, b):
                if not b or b == 0: return None
                return round((a - b) / b * 100, 1)

            grouped = {}
            for r in cur.fetchall():
                nsa   = str(r[0]) if r[0] else "—"
                kota  = str(r[1]) if r[1] else "—"
                pb = float(r[2]) if r[2] is not None else 0.0
                pa = float(r[3]) if r[3] is not None else 0.0
                tb = float(r[4]) if r[4] is not None else 0.0
                ta = float(r[5]) if r[5] is not None else 0.0
                ab_num = float(r[6]) if r[6] is not None else 0.0
                ab_den = float(r[7]) if r[7] is not None else 0.0
                aa_num = float(r[8]) if r[8] is not None else 0.0
                aa_den = float(r[9]) if r[9] is not None else 0.0
                rb = float(r[10]) if r[10] is not None else 0.0
                ra = float(r[11]) if r[11] is not None else 0.0

                ab = round(ab_num / ab_den * 100, 2) if ab_den > 0 else 0.0
                aa = round(aa_num / aa_den * 100, 2) if aa_den > 0 else 0.0

                row = {
                    "kota": kota,
                    "pb": round(pb, 2), "pa": round(pa, 2), "pch": pct(pa, pb),
                    "tb": round(tb, 2), "ta": round(ta, 2), "tch": pct(ta, tb),
                    "ab": ab, "aa": aa, "ach": pct(aa, ab),
                    "rb": round(rb, 0), "ra": round(ra, 0), "rch": pct(ra, rb),
                }
                grouped.setdefault(nsa, []).append(row)

            compare_table = [{"nsa": n, "rows": rows} for n, rows in grouped.items()]

        cur.close(); conn.close()
    except Exception as e:
        if conn: conn.rollback(); conn.close()
        flash(f"Error: {str(e)}", "danger")

    # Auto-select all cities if user is trying to compare weeks but no city selected
    if yw_before and yw_after and not sel_cities and cities_list:
        sel_cities = cities_list

    last_update = None
    try:
        conn2 = get_pumaz_connection()
        cur2 = conn2.cursor()
        cur2.execute('SELECT MAX("Date") FROM traffic_payload')
        row = cur2.fetchone()
        if row and row[0]:
            last_update = row[0].strftime("%d %b %Y")
        cur2.close(); conn2.close()
    except Exception:
        pass

    return _no_cache(make_response(render_template("city_level.html",
        username=session["username"],
        nsas_list=nsas_list, cities_list=cities_list,
        filtered_cities=filtered_cities,
        sel_nsas=sel_nsas, sel_cities=sel_cities,
        from_date=from_date, to_date=to_date,
        yw_list=yw_list, yw_before=yw_before, yw_after=yw_after,
        chart_labels=chart_labels,
        chart_payload=chart_payload,
        chart_traffic=chart_traffic,
        chart_availability=chart_availability,
        chart_rrc=chart_rrc,
        kpi_payload=round(kpi_payload, 1),
        kpi_traffic=round(kpi_traffic, 1),
        kpi_availability=kpi_availability,
        kpi_rrc=round(kpi_rrc, 0),
        compare_table=compare_table,
        last_update=last_update,
    )))

# ── Site Level ─────────────────────────────────────────────────────────────────
@prod.route("/site_level")
@login_required
def site_level():
    from_date  = request.args.get("from_date", "")
    to_date    = request.args.get("to_date", "")
    sel_nsas   = request.args.getlist("nsa")
    sel_cities = request.args.getlist("city")
    sel_sites  = request.args.getlist("site")
    yw_before  = request.args.get("yw_before", "")
    yw_after   = request.args.get("yw_after", "")

    chart_labels    = []
    chart_payload   = {}; chart_traffic   = {}
    chart_availability = {}; chart_rrc       = {}
    nsas_list = []; cities_list = []; sites_list = []; filtered_cities = []; yw_list = []
    compare_table = []   # [{city, rows: [{site, pb, pa, pch, tb, ta, tch, ab, aa, ach, rb, ra, rch}]}]

    kpi_payload = 0.0; kpi_traffic = 0.0
    kpi_availability = None; kpi_rrc = 0.0

    try:
        conn = get_pumaz_connection(); cur = conn.cursor()

        cur.execute('SELECT DISTINCT "NSA" FROM traffic_payload WHERE "NSA" IS NOT NULL ORDER BY "NSA"')
        nsas_list = [r[0] for r in cur.fetchall()]

        cur.execute('SELECT DISTINCT "Y_W" FROM traffic_payload WHERE "Y_W" IS NOT NULL ORDER BY "Y_W" DESC LIMIT 104')
        yw_list = [r[0] for r in cur.fetchall()]

        if sel_nsas:
            cur.execute('SELECT DISTINCT "KABUPATEN" FROM traffic_payload WHERE "NSA"=ANY(%s) AND "KABUPATEN" IS NOT NULL ORDER BY "KABUPATEN"', (sel_nsas,))
        else:
            cur.execute('SELECT DISTINCT "KABUPATEN" FROM traffic_payload WHERE "KABUPATEN" IS NOT NULL ORDER BY "KABUPATEN"')
        cities_list = [r[0] for r in cur.fetchall()]

        if sel_cities:
            cur.execute('SELECT DISTINCT "Site ID" FROM traffic_payload WHERE "KABUPATEN"=ANY(%s) AND "Site ID" IS NOT NULL ORDER BY "Site ID" LIMIT 2000', (sel_cities,))
        else:
            cur.execute('SELECT DISTINCT "Site ID" FROM traffic_payload WHERE "Site ID" IS NOT NULL ORDER BY "Site ID" LIMIT 2000')
        sites_list = [r[0] for r in cur.fetchall()]

        # Cascading: cities filtered by NSA, sites filtered by NSA+city
        if sel_nsas:
            cur.execute('SELECT DISTINCT "KABUPATEN" FROM traffic_payload WHERE "NSA"=ANY(%s) AND "KABUPATEN" IS NOT NULL ORDER BY "KABUPATEN"', (sel_nsas,))
        else:
            cur.execute('SELECT DISTINCT "KABUPATEN" FROM traffic_payload WHERE "KABUPATEN" IS NOT NULL ORDER BY "KABUPATEN"')
        filtered_cities = [r[0] for r in cur.fetchall()]

        if sel_cities and sel_nsas:
            cur.execute('SELECT DISTINCT "Site ID" FROM traffic_payload WHERE "NSA"=ANY(%s) AND "KABUPATEN"=ANY(%s) AND "Site ID" IS NOT NULL ORDER BY "Site ID" LIMIT 2000', (sel_nsas, sel_cities))
        elif sel_cities:
            cur.execute('SELECT DISTINCT "Site ID" FROM traffic_payload WHERE "KABUPATEN"=ANY(%s) AND "Site ID" IS NOT NULL ORDER BY "Site ID" LIMIT 2000', (sel_cities,))
        elif sel_nsas:
            cur.execute('SELECT DISTINCT "Site ID" FROM traffic_payload WHERE "NSA"=ANY(%s) AND "Site ID" IS NOT NULL ORDER BY "Site ID" LIMIT 2000', (sel_nsas,))
        sites_list = [r[0] for r in cur.fetchall()]

        # ── Chart data (daily) ────────────────────────────────────────────────
        if from_date and to_date and sel_sites:
            city_clause  = 'AND "KABUPATEN"=ANY(%s)' if sel_cities else ""
            nsa_clause   = 'AND "NSA"=ANY(%s)'      if sel_nsas  else ""
            params = [from_date, to_date, sel_sites] + ([sel_cities] if sel_cities else []) + ([sel_nsas] if sel_nsas else [])

            cur.execute(f"""
                SELECT
                    "Date"::text,
                    "Site ID",
                    SUM("Payload (MB)")/1024.0,
                    SUM("Traffic (erlang)")/1000.0,
                    SUM(CASE WHEN "Avail_Num" IS NOT NULL AND "Avail_Denum" IS NOT NULL
                             AND "Avail_Denum" > 0 THEN "Avail_Num" END),
                    SUM(CASE WHEN "Avail_Denum" IS NOT NULL AND "Avail_Denum" > 0
                             THEN "Avail_Denum" END),
                    SUM("Max_RRC_Conn_User")
                FROM traffic_payload
                WHERE "Date" BETWEEN %s AND %s AND "Site ID"=ANY(%s) {city_clause} {nsa_clause}
                GROUP BY "Date"::text,"Site ID"
                ORDER BY 1,"Site ID"
            """, params)

            months_seen = {}
            for r in cur.fetchall():
                fd   = str(r[0] or ''); site = str(r[1] or '')
                try: pg = float(r[2]) if r[2] is not None else 0.0
                except: pg = 0.0
                try: te = float(r[3]) if r[3] is not None else 0.0
                except: te = 0.0
                try: anum = float(r[4]) if r[4] is not None else 0.0
                except: anum = 0.0
                try: aden = float(r[5]) if r[5] is not None else 0.0
                except: aden = 0.0
                try: rrc = float(r[6]) if r[6] is not None else 0.0
                except: rrc = 0.0
                if fd not in months_seen: months_seen[fd] = fd
                chart_payload.setdefault(site, {})[fd] = round(pg, 2)
                chart_traffic.setdefault(site, {})[fd] = round(te, 1)
                chart_rrc.setdefault(site, {})[fd] = round(rrc, 0)
                av = round(anum / aden * 100, 2) if aden > 0 else 0.0
                chart_availability.setdefault(site, {})[fd] = av

            sorted_dates = sorted(months_seen.keys())
            chart_labels = sorted_dates

            for s in list(chart_payload.keys()):
                chart_payload[s]     = [chart_payload[s].get(d, 0)     for d in sorted_dates]
                chart_traffic[s]       = [chart_traffic[s].get(d, 0)      for d in sorted_dates]
                chart_availability[s] = [chart_availability[s].get(d, 0)  for d in sorted_dates]
                chart_rrc[s]          = [chart_rrc[s].get(d, 0)          for d in sorted_dates]

            av_all = []
            # Guard: only aggregate over sites that actually have chart data
            chart_sites = list(chart_payload.keys())
            for s in sel_sites:
                if s not in chart_sites:
                    continue
                kpi_payload  += sum(chart_payload.get(s) or [])
                kpi_traffic  += sum(chart_traffic.get(s) or [])
                kpi_rrc      += sum(chart_rrc.get(s) or [])
                av_all.extend(chart_availability.get(s) or [])
            kpi_availability = round(sum(av_all)/len(av_all), 2) if av_all else None

        # ── Y_W Comparison Table ──────────────────────────────────────────────
        # If the UI shows "Semua Site" but no explicit checkboxes were sent, treat as all sites
        if not sel_sites:
            sel_sites = sites_list

        if yw_before and yw_after and sel_sites:
            # Build query dynamically — number of placeholders always matches params
            p = [yw_before, yw_after, sel_sites]
            city_clause2 = ""
            if sel_cities:
                city_clause2 = 'AND t."KABUPATEN"=ANY(%s)'
                p.append(sel_cities)
            nsa_clause2 = ""
            if sel_nsas:
                nsa_clause2 = 'AND t."NSA"=ANY(%s)'
                p.append(sel_nsas)

            cur.execute(f"""
                SELECT
                    t."KABUPATEN",
                    t."Site ID",
                    SUM(CASE WHEN t."Y_W"=%s THEN t."Payload (MB)" END)/1024.0 AS pb,
                    SUM(CASE WHEN t."Y_W"=%s THEN t."Payload (MB)" END)/1024.0 AS pa,
                    SUM(CASE WHEN t."Y_W"=%s THEN t."Traffic (erlang)" END)/1000.0 AS tb,
                    SUM(CASE WHEN t."Y_W"=%s THEN t."Traffic (erlang)" END)/1000.0 AS ta,
                    SUM(CASE WHEN t."Y_W"=%s AND t."Avail_Num" IS NOT NULL
                                AND t."Avail_Denum" IS NOT NULL AND t."Avail_Denum">0
                             THEN t."Avail_Num" END) AS ab_num,
                    SUM(CASE WHEN t."Y_W"=%s AND t."Avail_Denum" IS NOT NULL AND t."Avail_Denum">0
                             THEN t."Avail_Denum" END) AS ab_den,
                    SUM(CASE WHEN t."Y_W"=%s AND t."Avail_Num" IS NOT NULL
                                AND t."Avail_Denum" IS NOT NULL AND t."Avail_Denum">0
                             THEN t."Avail_Num" END) AS aa_num,
                    SUM(CASE WHEN t."Y_W"=%s AND t."Avail_Denum" IS NOT NULL AND t."Avail_Denum">0
                             THEN t."Avail_Denum" END) AS aa_den,
                    SUM(CASE WHEN t."Y_W"=%s THEN t."Max_RRC_Conn_User" END) AS rb,
                    SUM(CASE WHEN t."Y_W"=%s THEN t."Max_RRC_Conn_User" END) AS ra
                FROM traffic_payload t
                WHERE t."Y_W" IN (%s,%s) {nsa_clause2} {city_clause2}
                GROUP BY t."KABUPATEN", t."Site ID"
                ORDER BY t."KABUPATEN", t."Site ID"
            """, p)

            def pct(a, b):
                if not b or b == 0: return None
                return round((a - b) / b * 100, 1)

            grouped = {}
            for r in cur.fetchall():
                kota  = str(r[0]) if r[0] else "—"
                site  = str(r[1]) if r[1] else "—"
                pb = float(r[2]) if r[2] is not None else 0.0
                pa = float(r[3]) if r[3] is not None else 0.0
                tb = float(r[4]) if r[4] is not None else 0.0
                ta = float(r[5]) if r[5] is not None else 0.0
                ab_num = float(r[6]) if r[6] is not None else 0.0
                ab_den = float(r[7]) if r[7] is not None else 0.0
                aa_num = float(r[8]) if r[8] is not None else 0.0
                aa_den = float(r[9]) if r[9] is not None else 0.0
                rb = float(r[10]) if r[10] is not None else 0.0
                ra = float(r[11]) if r[11] is not None else 0.0

                ab = round(ab_num / ab_den * 100, 2) if ab_den > 0 else 0.0
                aa = round(aa_num / aa_den * 100, 2) if aa_den > 0 else 0.0

                row = {
                    "site": site,
                    "pb": round(pb, 2), "pa": round(pa, 2), "pch": pct(pa, pb),
                    "tb": round(tb, 2), "ta": round(ta, 2), "tch": pct(ta, tb),
                    "ab": ab, "aa": aa, "ach": pct(aa, ab),
                    "rb": round(rb, 0), "ra": round(ra, 0), "rch": pct(ra, rb),
                }
                grouped.setdefault(kota, []).append(row)

            compare_table = [{"city": c, "rows": rows} for c, rows in grouped.items()]

        cur.close(); conn.close()
    except Exception as e:
        if conn: conn.rollback(); conn.close()
        flash(f"Error: {str(e)}", "danger")

    # Auto-select all sites if user is trying to compare weeks but no site selected
    if yw_before and yw_after and not sel_sites and sites_list:
        sel_sites = sites_list

    last_update = None
    try:
        conn2 = get_pumaz_connection()
        cur2 = conn2.cursor()
        cur2.execute('SELECT MAX("Date") FROM traffic_payload')
        row = cur2.fetchone()
        if row and row[0]:
            last_update = row[0].strftime("%d %b %Y")
        cur2.close(); conn2.close()
    except Exception:
        pass

    return _no_cache(make_response(render_template("site_level.html",
        username=session["username"],
        nsas_list=nsas_list, cities_list=cities_list, sites_list=sites_list,
        filtered_cities=filtered_cities,
        sel_nsas=sel_nsas, sel_cities=sel_cities, sel_sites=sel_sites,
        from_date=from_date, to_date=to_date,
        yw_list=yw_list, yw_before=yw_before, yw_after=yw_after,
        chart_labels=chart_labels,
        chart_payload=chart_payload,
        chart_traffic=chart_traffic,
        chart_availability=chart_availability,
        chart_rrc=chart_rrc,
        kpi_payload=round(kpi_payload, 1),
        kpi_traffic=round(kpi_traffic, 1),
        kpi_availability=kpi_availability,
        kpi_rrc=round(kpi_rrc, 0),
        compare_table=compare_table,
        last_update=last_update,
    )))