from flask import Blueprint, make_response, redirect, render_template, request, session, flash, url_for, jsonify
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, _no_cache, ytd_pct, db_query
from datetime import datetime, timedelta
from collections import OrderedDict
import psycopg2
import psycopg2.errors
import time
import logging

logger = logging.getLogger(__name__)

prod = Blueprint("prod", __name__)

_prod_cache = {"ts": 0, "years": [], "nsas": [], "yw": [], "cities": [], "sites": []}

def _get_dropdown_data():
    now = time.time()
    if now - _prod_cache["ts"] < 3600 and _prod_cache["years"] and _prod_cache["nsas"]:
        return _prod_cache
    
    try:
        with db_query() as (conn, cur):
            # Years
            cur.execute('SELECT DISTINCT "Year by Date" FROM mv_traffic_payload_daily_city WHERE "Year by Date" IS NOT NULL ORDER BY "Year by Date"')
            years = [r[0] for r in cur.fetchall()]
            
            # NSAs (exclude bad data like SORONG RAJA AMPAT)
            cur.execute('SELECT DISTINCT "NSA" FROM mv_traffic_payload_daily_city WHERE "NSA" IS NOT NULL AND "NSA" NOT ILIKE \'%SORONG RAJA AMPAT%\' ORDER BY "NSA"')
            nsas = [r[0] for r in cur.fetchall()]
            
            # YW (Year Week) - latest 104 weeks
            cur.execute('SELECT DISTINCT "Y_W" FROM mv_traffic_payload_yw_city WHERE "Y_W" IS NOT NULL ORDER BY "Y_W" DESC LIMIT 104')
            yw = [r[0] for r in cur.fetchall()]
            
            # Cities (Recent 30 days)
            cur.execute('SELECT DISTINCT "KABUPATEN" FROM mv_traffic_payload_daily_city WHERE "KABUPATEN" IS NOT NULL AND "Date" >= CURRENT_DATE - INTERVAL \'30 days\' ORDER BY "KABUPATEN"')
            cities = [r[0] for r in cur.fetchall()]
            
            _prod_cache["years"] = years
            _prod_cache["nsas"] = nsas
            _prod_cache["yw"] = yw
            _prod_cache["cities"] = cities
            _prod_cache["ts"] = now
            
    except Exception as e:
        logger.error("Error populating dropdown cache: %s", e)
        
    return _prod_cache

def _get_sites(sel_nsas=None, sel_cities=None):
    sites = []
    try:
        # If no NSA or City filter is active, fetch full site list from reference view
        if not sel_nsas and not sel_cities:
            try:
                from app.db.db_webapp import get_site_list_4g
                res = get_site_list_4g()
                if isinstance(res, tuple):
                    res = res[0]
                if res and isinstance(res, list) and len(res) > 0:
                    return res
            except Exception as ref_err:
                logger.warning("Reference site list fetch fallback: %s", ref_err)

        with db_query() as (conn, cur):
            params = []
            nsa_clause = ""
            if sel_nsas:
                nsa_clause = 'AND "NSA"=ANY(%s)'
                params.append(sel_nsas)
                
            city_clause = ""
            if sel_cities:
                city_clause = 'AND "KABUPATEN"=ANY(%s)'
                params.append(sel_cities)
                
            cur.execute(f'''
                SELECT DISTINCT "Site ID" 
                FROM traffic_payload 
                WHERE "Site ID" IS NOT NULL 
                {nsa_clause} {city_clause}
                ORDER BY "Site ID"
            ''', params)
            sites = [r[0] for r in cur.fetchall()]
    except Exception as e:
        logger.error("Error fetching sites: %s", e)
    return sites

def _get_last_update():
    try:
        with db_query() as (conn, cur):
            cur.execute('SELECT MAX("Date") FROM mv_traffic_payload_daily_city')
            row = cur.fetchone()
            if row and row[0]:
                if isinstance(row[0], datetime):
                    return row[0].strftime("%d %b %Y")
                return row[0].strftime("%d %b %Y") # if it's already a date object
    except Exception:
        pass
    return None

# ── Productivity (Trend YoY) ──────────────────────────────────────────────────
@prod.route("/productivity")
@login_required
def productivity():
    data = _get_dropdown_data()
    return _no_cache(make_response(render_template(
        "productivity.html",
        username=session.get("username"),
        years_list=data["years"],
        nsas_list=data["nsas"],
        last_date_after=_get_last_update()
    )))

@prod.route("/api/productivity/trend")
@login_required
def api_productivity_trend():
    year_before = request.args.get("year_before", "")
    year_after  = request.args.get("year_after",  "")
    sel_nsas    = request.args.getlist("nsa")
    sel_nsas = [n for n in sel_nsas if n]

    if not year_before or not year_after:
        return jsonify({"error": "Please provide year_before and year_after"}), 400

    if year_before >= year_after:
        return jsonify({"error": "Year Before must be smaller than Year After"}), 400

    try:
        with db_query() as (conn, cur):
            nsa_clause = ""
            params_after = [year_after]
            params_before = [year_before]
            
            if sel_nsas:
                nsa_clause = 'AND "NSA" = ANY(%s)'
                params_after.append(sel_nsas)
                params_before.append(sel_nsas)

            # Get daily data using Materialized Views
            cur.execute(f'''
                SELECT 
                    EXTRACT(DOY FROM "Date")::INT AS doy, 
                    SUM(sum_payload_mb)/1024.0/1024.0 AS pb,
                    SUM(sum_traffic_erl)/1000.0 AS tb
                FROM mv_traffic_payload_daily_city
                WHERE "Year by Date" = %s {nsa_clause}
                GROUP BY EXTRACT(DOY FROM "Date")::INT
                ORDER BY EXTRACT(DOY FROM "Date")::INT
            ''', params_before)
            before_daily = {int(r[0]): {"pb": float(r[1] or 0), "tb": float(r[2] or 0)} for r in cur.fetchall()}

            cur.execute(f'''
                SELECT 
                    EXTRACT(DOY FROM "Date")::INT AS doy, 
                    SUM(sum_payload_mb)/1024.0/1024.0 AS pa,
                    SUM(sum_traffic_erl)/1000.0 AS ta,
                    MAX("Date")
                FROM mv_traffic_payload_daily_city
                WHERE "Year by Date" = %s {nsa_clause}
                GROUP BY EXTRACT(DOY FROM "Date")::INT
                ORDER BY EXTRACT(DOY FROM "Date")::INT
            ''', params_after)
            after_rows = cur.fetchall()
            after_daily = {int(r[0]): {"pa": float(r[1] or 0), "ta": float(r[2] or 0), "date": r[3]} for r in after_rows}
            
            max_doy_after = max(after_daily.keys()) if after_daily else 0
            max_doy_before = max(before_daily.keys()) if before_daily else 0
            
            # If Before year is leap, it might have 366. Show up to max available.
            max_doy_to_show = max(max_doy_before, max_doy_after)
            
            chart_labels = []
            payload_before = []; payload_after = []; payload_ytd = []
            traffic_before = []; traffic_after = []; traffic_ytd = []
            
            cum_pb = cum_pa = cum_tb = cum_ta = 0.0
            
            for doy in range(1, max_doy_to_show + 1):
                b_data = before_daily.get(doy, {"pb": 0, "tb": 0})
                a_data = after_daily.get(doy, {"pa": 0, "ta": 0})
                
                pb = b_data["pb"]
                tb = b_data["tb"]
                pa = a_data["pa"]
                ta = a_data["ta"]
                
                # Exclude leap day from YTD logic if we want, but for simplicity let's map directly
                
                # Chart labels: just dd Mon
                label_date = datetime(int(year_after), 1, 1) + timedelta(days=doy - 1)
                chart_labels.append(label_date.strftime("%d %b"))
                
                # Skip leap day on non-leap years
                if int(year_after) % 4 != 0 and doy == 60 and int(year_before) % 4 == 0:
                    continue # Skip Feb 29 logic simplified

                payload_before.append(pb if doy in before_daily else None)
                payload_after.append(pa if doy in after_daily else None)
                traffic_before.append(tb if doy in before_daily else None)
                traffic_after.append(ta if doy in after_daily else None)
                
                if doy in before_daily: cum_pb += pb
                if doy in before_daily: cum_tb += tb
                
                if doy in after_daily: cum_pa += pa
                if doy in after_daily: cum_ta += ta
                
                if doy <= max_doy_after:
                    yp = round((cum_pa - cum_pb) / cum_pb * 100, 2) if cum_pb > 0 else None
                    yt = round((cum_ta - cum_tb) / cum_tb * 100, 2) if cum_tb > 0 else None
                else:
                    yp = yt = None
                    
                payload_ytd.append(yp)
                traffic_ytd.append(yt)

            # Table Data (Regional > NOP > TO)
            # Using the mv_traffic_payload_daily_regional
            params_reg = [year_before, max_doy_after, year_after, max_doy_after, year_before, max_doy_after, year_after, max_doy_after, year_before, year_after]
            reg_nsa_clause = ""
            if sel_nsas:
                reg_nsa_clause = 'AND "NSA" = ANY(%s)'
                params_reg.append(sel_nsas)
            
            cur.execute(f'''
                SELECT 
                    "Regional", "NSA", "TO",
                    SUM(CASE WHEN "Year by Date"=%s AND EXTRACT(DOY FROM "Date") <= %s THEN sum_payload_mb END)/1024.0/1024.0 AS pb,
                    SUM(CASE WHEN "Year by Date"=%s AND EXTRACT(DOY FROM "Date") <= %s THEN sum_payload_mb END)/1024.0/1024.0 AS pa,
                    SUM(CASE WHEN "Year by Date"=%s AND EXTRACT(DOY FROM "Date") <= %s THEN sum_traffic_erl END)/1000.0 AS tb,
                    SUM(CASE WHEN "Year by Date"=%s AND EXTRACT(DOY FROM "Date") <= %s THEN sum_traffic_erl END)/1000.0 AS ta
                FROM mv_traffic_payload_daily_regional
                WHERE "Year by Date" IN (%s, %s) {reg_nsa_clause}
                GROUP BY "Regional", "NSA", "TO"
                ORDER BY "Regional", "NSA", "TO"
            ''', params_reg)
            
            regional_data = OrderedDict()
            for r in cur.fetchall():
                reg = r[0] or "N/A"; nop = r[1] or "N/A"; to_ = r[2] or "N/A"
                pb = float(r[3] or 0); pa = float(r[4] or 0)
                tb = float(r[5] or 0); ta = float(r[6] or 0)
                regional_data.setdefault(reg, OrderedDict()).setdefault(nop, {})[to_] = {
                    "pb": pb, "pa": pa, "tb": tb, "ta": ta
                }

            table_rows = []
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
            
            # Filter None from payload after
            pa_vals = [v for v in payload_after if v is not None]
            ta_vals = [v for v in traffic_after if v is not None]
            
            valid_yp = [v for v in payload_ytd if v is not None]
            valid_yt = [v for v in traffic_ytd if v is not None]

            # Calculate peak and date
            peak_val = 0.0
            peak_date = None
            for idx, p in enumerate(payload_after):
                if p is not None and p > peak_val:
                    peak_val = p
                    peak_date = chart_labels[idx]

            return jsonify({
                "chart_labels": chart_labels,
                "payload_before": payload_before,
                "payload_after": payload_after,
                "payload_ytd": payload_ytd,
                "traffic_before": traffic_before,
                "traffic_after": traffic_after,
                "traffic_ytd": traffic_ytd,
                "table_rows": table_rows,
                "total_payload_after": sum(pa_vals),
                "total_traffic_after": sum(ta_vals),
                "peak_payload_after": peak_val,
                "peak_payload_date": peak_date,
                "ytd_payload_final": valid_yp[-1] if valid_yp else None,
                "ytd_traffic_final": valid_yt[-1] if valid_yt else None
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@prod.route("/api/productivity/cities")
@login_required
def api_productivity_cities():
    sel_nsas = [n for n in request.args.getlist("nsa") if n]
    if not sel_nsas:
        return jsonify({"cities": _get_dropdown_data()["cities"]})
    cities = []
    try:
        with db_query() as (conn, cur):
            cur.execute('''
                SELECT DISTINCT "KABUPATEN" 
                FROM mv_traffic_payload_daily_city 
                WHERE "NSA"=ANY(%s) 
                ORDER BY "KABUPATEN"
            ''', [sel_nsas])
            cities = [r[0] for r in cur.fetchall()]
            
            # Cleanup bad mappings where SORONG RAJA AMPAT appears under wrong NSAs
            if not any("Sorong" in n for n in sel_nsas):
                cities = [c for c in cities if c != "SORONG RAJA AMPAT"]
                
    except Exception as e:
        cities = _get_dropdown_data()["cities"]
    return jsonify({"cities": cities})

@prod.route("/api/productivity/sites")
@login_required
def api_productivity_sites():
    sel_nsas = [n for n in request.args.getlist("nsa") if n]
    sel_cities = [c for c in request.args.getlist("city") if c]
    return jsonify({"sites": _get_sites(sel_nsas, sel_cities)})

# ── City Level ────────────────────────────────────────────────────────────────
@prod.route("/city_level")
@login_required
def city_level():
    data = _get_dropdown_data()
    return _no_cache(make_response(render_template(
        "city_level.html",
        username=session.get("username"),
        nsas_list=data["nsas"],
        cities_list=data["cities"],
        yw_list=data["yw"],
        last_update=_get_last_update()
    )))

@prod.route("/api/productivity/city")
@login_required
def api_productivity_city():
    mode = request.args.get("mode", "trend") # 'trend' or 'compare'
    
    sel_nsas = [n for n in request.args.getlist("nsa") if n]
    sel_cities = [c for c in request.args.getlist("city") if c]
    
    try:
        with db_query() as (conn, cur):
            if mode == "trend":
                from_date = request.args.get("from_date", "")
                to_date = request.args.get("to_date", "")
                if not from_date or not to_date or not sel_cities:
                    return jsonify({"error": "Missing required filters for trend mode"})
                
                params = [from_date, to_date, sel_cities]
                nsa_clause = ""
                if sel_nsas:
                    nsa_clause = 'AND "NSA"=ANY(%s)'
                    params.append(sel_nsas)
                
                cur.execute(f'''
                    SELECT
                        "Date"::text,
                        "KABUPATEN",
                        SUM(sum_payload_mb)/1024.0/1024.0 AS pb,
                        SUM(sum_traffic_erl)/1000.0 AS tb,
                        SUM(sum_avail_num) AS anum,
                        SUM(sum_avail_denum) AS aden,
                        SUM(sum_max_rrc) AS rrc
                    FROM mv_traffic_payload_daily_city
                    WHERE "Date" BETWEEN %s AND %s AND "KABUPATEN"=ANY(%s) {nsa_clause}
                    GROUP BY "Date"::text, "KABUPATEN"
                    ORDER BY 1, 2
                ''', params)
                
                chart_labels = []
                chart_payload = {}
                chart_traffic = {}
                chart_availability = {}
                chart_rrc = {}
                months_seen = {}
                
                for r in cur.fetchall():
                    fd = str(r[0] or '')
                    city = str(r[1] or '')
                    pg = float(r[2] or 0)
                    te = float(r[3] or 0)
                    anum = float(r[4] or 0)
                    aden = float(r[5] or 0)
                    rrc = float(r[6] or 0)
                    
                    if fd not in months_seen: months_seen[fd] = fd
                    chart_payload.setdefault(city, {})[fd] = round(pg, 2)
                    chart_traffic.setdefault(city, {})[fd] = round(te, 1)
                    chart_rrc.setdefault(city, {})[fd] = round(rrc, 0)
                    av = round(anum / aden * 100, 2) if aden > 0 else 0.0
                    chart_availability.setdefault(city, {})[fd] = av

                sorted_dates = sorted(months_seen.keys())
                for c in list(chart_payload.keys()):
                    chart_payload[c] = [chart_payload[c].get(d, 0) for d in sorted_dates]
                    chart_traffic[c] = [chart_traffic[c].get(d, 0) for d in sorted_dates]
                    chart_availability[c] = [chart_availability[c].get(d, 0) for d in sorted_dates]
                    chart_rrc[c] = [chart_rrc[c].get(d, 0) for d in sorted_dates]

                # KPIs
                all_av = []; kpi_payload = 0; kpi_traffic = 0; kpi_rrc = 0
                for c in sel_cities:
                    all_av.extend(chart_availability.get(c, []))
                    kpi_payload += sum(chart_payload.get(c, []))
                    kpi_traffic += sum(chart_traffic.get(c, []))
                    kpi_rrc += sum(chart_rrc.get(c, []))
                
                kpi_availability = round(sum(all_av)/len(all_av), 2) if all_av else None

                return jsonify({
                    "chart_labels": sorted_dates,
                    "chart_payload": chart_payload,
                    "chart_traffic": chart_traffic,
                    "chart_availability": chart_availability,
                    "chart_rrc": chart_rrc,
                    "kpis": {
                        "payload": round(kpi_payload, 1),
                        "traffic": round(kpi_traffic, 1),
                        "availability": kpi_availability,
                        "rrc": round(kpi_rrc, 0)
                    }
                })
            
            elif mode == "compare":
                yw_before = request.args.get("yw_before", "")
                yw_after = request.args.get("yw_after", "")
                
                if not yw_before or not yw_after:
                    return jsonify({"error": "Missing weeks for compare"})
                
                if not sel_cities:
                    sel_cities = _get_dropdown_data()["cities"]
                    
                params = [yw_before, yw_after, sel_cities]
                nsa_clause = ""
                if sel_nsas:
                    nsa_clause = 'AND "NSA"=ANY(%s)'
                    params.append(sel_nsas)
                    
                cur.execute(f'''
                    SELECT
                        "NSA",
                        "KABUPATEN",
                        SUM(CASE WHEN "Y_W"=%s THEN sum_payload_mb END)/1024.0/1024.0 AS pb,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_payload_mb END)/1024.0/1024.0 AS pa,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_traffic_erl END)/1000.0 AS tb,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_traffic_erl END)/1000.0 AS ta,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_avail_num END) AS ab_num,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_avail_denum END) AS ab_den,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_avail_num END) AS aa_num,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_avail_denum END) AS aa_den,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_max_rrc END) AS rb,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_max_rrc END) AS ra
                    FROM mv_traffic_payload_yw_city
                    WHERE "Y_W" IN (%s, %s) AND "KABUPATEN"=ANY(%s) {nsa_clause}
                    GROUP BY "NSA", "KABUPATEN"
                    ORDER BY "NSA", "KABUPATEN"
                ''', [yw_before, yw_after, yw_before, yw_after, yw_before, yw_before, yw_after, yw_after, yw_before, yw_after] + [yw_before, yw_after, sel_cities] + ([sel_nsas] if sel_nsas else []))
                
                grouped = {}
                def pct(a, b): return round((a - b) / b * 100, 1) if b and b > 0 else None
                
                for r in cur.fetchall():
                    nsa = str(r[0] or "—"); kota = str(r[1] or "—")
                    pb = float(r[2] or 0); pa = float(r[3] or 0)
                    tb = float(r[4] or 0); ta = float(r[5] or 0)
                    ab_num = float(r[6] or 0); ab_den = float(r[7] or 0)
                    aa_num = float(r[8] or 0); aa_den = float(r[9] or 0)
                    rb = float(r[10] or 0); ra = float(r[11] or 0)
                    
                    ab = round(ab_num / ab_den * 100, 2) if ab_den > 0 else 0.0
                    aa = round(aa_num / aa_den * 100, 2) if aa_den > 0 else 0.0
                    
                    grouped.setdefault(nsa, []).append({
                        "kota": kota,
                        "pb": round(pb, 2), "pa": round(pa, 2), "pch": pct(pa, pb),
                        "tb": round(tb, 2), "ta": round(ta, 2), "tch": pct(ta, tb),
                        "ab": ab, "aa": aa, "ach": pct(aa, ab),
                        "rb": round(rb, 0), "ra": round(ra, 0), "rch": pct(ra, rb),
                    })
                
                compare_table = [{"nsa": k, "rows": v} for k, v in grouped.items()]
                return jsonify({"compare_table": compare_table})
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Site Level ────────────────────────────────────────────────────────────────
@prod.route("/site_level")
@login_required
def site_level():
    data = _get_dropdown_data()
    sel_nsas = [n for n in request.args.getlist("nsa") if n]
    sel_cities = [c for c in request.args.getlist("city") if c]
    
    sites_list = _get_sites(sel_nsas, sel_cities)
    last_up = _get_last_update()

    from datetime import datetime, timedelta
    if last_up:
        try:
            to_dt = datetime.strptime(last_up, "%d %b %Y")
        except Exception:
            to_dt = datetime.now()
    else:
        to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=30)
    
    return _no_cache(make_response(render_template(
        "site_level.html",
        username=session.get("username"),
        nsas_list=data["nsas"],
        cities_list=data["cities"],
        sites_list=sites_list,
        yw_list=data["yw"],
        default_from=from_dt.strftime("%Y-%m-%d"),
        default_to=to_dt.strftime("%Y-%m-%d"),
        last_update=last_up
    )))

@prod.route("/api/productivity/sites")
@login_required
def api_productivity_sites_list():
    sel_nsas = [n for n in request.args.getlist("nsa") if n]
    sel_cities = [c for c in request.args.getlist("city") if c]
    sites = _get_sites(sel_nsas, sel_cities)
    return jsonify({"sites": sites})

@prod.route("/api/productivity/site")
@login_required
def api_productivity_site():
    mode = request.args.get("mode", "trend")
    
    sel_nsas = [n for n in request.args.getlist("nsa") if n]
    sel_cities = [c for c in request.args.getlist("city") if c]
    sel_sites = [s for s in request.args.getlist("site") if s]
    
    try:
        with db_query() as (conn, cur):
            if mode == "trend":
                from_date = request.args.get("from_date", "")
                to_date = request.args.get("to_date", "")
                if not from_date or not to_date:
                    return jsonify({"error": "Missing required date filters for trend mode"})
                
                if not sel_sites:
                    sel_sites = _get_sites(sel_nsas, sel_cities)
                    if len(sel_sites) > 50:
                        sel_sites = sel_sites[:50]
                
                if not sel_sites:
                    return jsonify({"error": "No sites found matching selected filters"})

                params = [from_date, to_date, sel_sites]
                nsa_clause = ""
                city_clause = ""
                if sel_nsas:
                    nsa_clause = 'AND "NSA"=ANY(%s)'
                    params.append(sel_nsas)
                if sel_cities:
                    city_clause = 'AND "KABUPATEN"=ANY(%s)'
                    params.append(sel_cities)
                
                cur.execute(f'''
                    SELECT
                        "Date"::text,
                        "Site ID",
                        SUM(sum_payload_mb)/1024.0 AS pb,
                        SUM(sum_traffic_erl)/1000.0 AS tb,
                        SUM(sum_avail_num) AS anum,
                        SUM(sum_avail_denum) AS aden,
                        SUM(sum_max_rrc) AS rrc
                    FROM mv_traffic_payload_daily_site
                    WHERE "Date" BETWEEN %s AND %s AND "Site ID"=ANY(%s) {nsa_clause} {city_clause}
                    GROUP BY "Date"::text, "Site ID"
                    ORDER BY 1, 2
                ''', params)
                
                chart_labels = []
                chart_payload = {}
                chart_traffic = {}
                chart_availability = {}
                chart_rrc = {}
                months_seen = {}
                
                for r in cur.fetchall():
                    fd = str(r[0] or '')
                    site = str(r[1] or '')
                    pg = float(r[2] or 0)
                    te = float(r[3] or 0)
                    anum = float(r[4] or 0)
                    aden = float(r[5] or 0)
                    rrc = float(r[6] or 0)
                    
                    if fd not in months_seen: months_seen[fd] = fd
                    chart_payload.setdefault(site, {})[fd] = round(pg, 2)
                    chart_traffic.setdefault(site, {})[fd] = round(te, 1)
                    chart_rrc.setdefault(site, {})[fd] = round(rrc, 0)
                    av = round(anum / aden * 100, 2) if aden > 0 else 0.0
                    chart_availability.setdefault(site, {})[fd] = av

                sorted_dates = sorted(months_seen.keys())
                for s in list(chart_payload.keys()):
                    chart_payload[s] = [chart_payload[s].get(d, 0) for d in sorted_dates]
                    chart_traffic[s] = [chart_traffic[s].get(d, 0) for d in sorted_dates]
                    chart_availability[s] = [chart_availability[s].get(d, 0) for d in sorted_dates]
                    chart_rrc[s] = [chart_rrc[s].get(d, 0) for d in sorted_dates]

                # KPIs
                all_av = []; kpi_payload = 0; kpi_traffic = 0; kpi_rrc = 0
                for s in sel_sites:
                    if s in chart_payload:
                        all_av.extend(chart_availability.get(s, []))
                        kpi_payload += sum(chart_payload.get(s, []))
                        kpi_traffic += sum(chart_traffic.get(s, []))
                        kpi_rrc += sum(chart_rrc.get(s, []))
                
                kpi_availability = round(sum(all_av)/len(all_av), 2) if all_av else None

                return jsonify({
                    "chart_labels": sorted_dates,
                    "chart_payload": chart_payload,
                    "chart_traffic": chart_traffic,
                    "chart_availability": chart_availability,
                    "chart_rrc": chart_rrc,
                    "kpis": {
                        "payload": round(kpi_payload, 1),
                        "traffic": round(kpi_traffic, 1),
                        "availability": kpi_availability,
                        "rrc": round(kpi_rrc, 0)
                    }
                })
                
            elif mode == "compare":
                yw_before = request.args.get("yw_before", "")
                yw_after = request.args.get("yw_after", "")
                
                if not yw_before or not yw_after:
                    return jsonify({"error": "Missing weeks for compare"})
                
                query_params = []
                site_clause = ""
                nsa_clause = ""
                city_clause = ""
                
                if sel_sites:
                    site_clause = 'AND "Site ID"=ANY(%s)'
                    query_params.append(sel_sites)
                if sel_nsas:
                    nsa_clause = 'AND "NSA"=ANY(%s)'
                    query_params.append(sel_nsas)
                if sel_cities:
                    city_clause = 'AND "KABUPATEN"=ANY(%s)'
                    query_params.append(sel_cities)
                    
                cur.execute(f'''
                    SELECT
                        "KABUPATEN",
                        "Site ID",
                        SUM(CASE WHEN "Y_W"=%s THEN sum_payload_mb END)/1024.0 AS pb,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_payload_mb END)/1024.0 AS pa,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_traffic_erl END)/1000.0 AS tb,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_traffic_erl END)/1000.0 AS ta,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_avail_num END) AS ab_num,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_avail_denum END) AS ab_den,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_avail_num END) AS aa_num,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_avail_denum END) AS aa_den,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_max_rrc END) AS rb,
                        SUM(CASE WHEN "Y_W"=%s THEN sum_max_rrc END) AS ra
                    FROM mv_traffic_payload_yw_site
                    WHERE "Y_W" IN (%s, %s) {site_clause} {nsa_clause} {city_clause}
                    GROUP BY "KABUPATEN", "Site ID"
                    ORDER BY "KABUPATEN", "Site ID"
                ''', [yw_before, yw_after, yw_before, yw_after, yw_before, yw_before, yw_after, yw_after, yw_before, yw_after, yw_before, yw_after] + query_params)
                
                grouped = {}
                def pct(a, b): return round((a - b) / b * 100, 1) if b and b > 0 else None
                
                for r in cur.fetchall():
                    kota = str(r[0] or "—"); site = str(r[1] or "—")
                    pb = float(r[2] or 0); pa = float(r[3] or 0)
                    tb = float(r[4] or 0); ta = float(r[5] or 0)
                    ab_num = float(r[6] or 0); ab_den = float(r[7] or 0)
                    aa_num = float(r[8] or 0); aa_den = float(r[9] or 0)
                    rb = float(r[10] or 0); ra = float(r[11] or 0)
                    
                    ab = round(ab_num / ab_den * 100, 2) if ab_den > 0 else 0.0
                    aa = round(aa_num / aa_den * 100, 2) if aa_den > 0 else 0.0
                    
                    grouped.setdefault(kota, []).append({
                        "site": site,
                        "pb": round(pb, 2), "pa": round(pa, 2), "pch": pct(pa, pb),
                        "tb": round(tb, 2), "ta": round(ta, 2), "tch": pct(ta, tb),
                        "ab": ab, "aa": aa, "ach": pct(aa, ab),
                        "rb": round(rb, 0), "ra": round(ra, 0), "rch": pct(ra, rb),
                    })
                
                compare_table = [{"city": k, "rows": v} for k, v in grouped.items()]
                return jsonify({"compare_table": compare_table})
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500