from flask import Blueprint, render_template, request, session, flash, make_response
from app.db.db_pumaz import get_pumaz_connection
from ._utils import login_required, _no_cache, json_response, csv_response, validate_date_params
from datetime import datetime
import psycopg2

pl = Blueprint("pl", __name__)

# ── Helper: hour value from raw DB value ─────────────────────────────────────
def _hour_val(raw):
    if isinstance(raw, str):
        if ':' in raw:
            return int(raw.split(':')[0])
        # string decimal fraction like "0.041666667" (fraction of a day)
        try:
            return int(float(raw) * 24)
        except:
            return 0
    if isinstance(raw, datetime):
        return raw.hour
    if isinstance(raw, (int, float)):
        return int(float(raw) * 24)
    try:
        return int(raw)
    except:
        return 0

# ── PL 2G ──────────────────────────────────────────────────────────────────────
@pl.route("/pl_2g")
@login_required
def pl_2g():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")

    chart_labels = []; chart_pl = {}; chart_latency = {}; chart_jitter = {}
    sites_list = []; last_update = None

    conn = None; cur = None
    try:
        conn = get_pumaz_connection(); cur = conn.cursor()

        try:
            cur.execute('SELECT DISTINCT "Site ID" FROM "2G_pl_hy" WHERE "Site ID" IS NOT NULL ORDER BY "Site ID" LIMIT 20000')
            sites_list = [r[0] for r in cur.fetchall()]
        except psycopg2.OperationalError: raise
        except Exception:
            sites_list = []
            flash("Site list could not be loaded. Please filter by site manually.", "warning")

        try:
            cur.execute('SELECT MAX("Date") FROM "2G_pl_hy"')
            raw_last = cur.fetchone()
            last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
        except psycopg2.OperationalError: raise
        except Exception:
            last_update = None

        if from_date and to_date and sel_sites:
            cur.execute("""
                SELECT
                    "Date", "Hour", "Site ID",
                    CASE WHEN SUM("Packet Loss Rate Denum")>0
                         THEN ROUND((SUM("Packet Loss Rate Num")::numeric/SUM("Packet Loss Rate Denum")::numeric)*100.0, 2)
                         ELSE NULL END AS packet_loss_pct,
                    AVG("Mean round-trip delay(ms)") AS latency_ms,
                    AVG("Mean delay jitter(ms)") AS jitter_ms
                FROM "2G_pl_hy"
                WHERE "Date" BETWEEN %s AND %s AND "Site ID"=ANY(%s)
                GROUP BY "Date", "Hour", "Site ID"
                ORDER BY "Date", "Hour", "Site ID"
            """, [from_date, to_date, sel_sites])

            hours_seen = {}
            for r in cur.fetchall():
                dh = f"{r[0].strftime('%Y-%m-%d')} {_hour_val(r[1]):02d}:00"
                site = r[2]
                pl_v = float(r[3]) if r[3] is not None else None
                lat  = float(r[4]) if r[4] is not None else None
                jit  = float(r[5]) if r[5] is not None else None
                hours_seen[dh] = True
                chart_pl.setdefault(site, {})[dh] = pl_v
                chart_latency.setdefault(site, {})[dh] = lat
                chart_jitter.setdefault(site, {})[dh] = jit

            chart_labels = sorted(hours_seen.keys())
            for s in chart_pl:
                chart_pl[s]     = [chart_pl[s].get(h)     for h in chart_labels]
                chart_latency[s] = [chart_latency[s].get(h) for h in chart_labels]
                chart_jitter[s]  = [chart_jitter[s].get(h)  for h in chart_labels]

        cur.close(); conn.close()
        cur = None; conn = None
    except psycopg2.OperationalError:
        if cur:   cur.close()
        if conn:  conn.rollback(); conn.close()
        flash("Database connection failed. Please try again.", "warning")
    except Exception as e:
        if cur:   cur.close()
        if conn:  conn.rollback(); conn.close()
        flash(f"Error: {str(e)}", "danger")

    return _no_cache(make_response(render_template(
        "pl_2g.html",
        username=session["username"],
        sites_list=sites_list,
        sel_sites=sel_sites,
        from_date=from_date,
        to_date=to_date,
        last_update=last_update,
        chart_labels=chart_labels,
        chart_pl=chart_pl,
        chart_latency=chart_latency,
        chart_jitter=chart_jitter,
    )))

# ── PL 4G ──────────────────────────────────────────────────────────────────────
@pl.route("/pl_4g")
@login_required
def pl_4g():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")

    chart_labels = []; chart_pl = {}; chart_latency = {}; chart_jitter = {}
    sites_list = []; last_update = None

    conn = None; cur = None
    try:
        conn = get_pumaz_connection(); cur = conn.cursor()

        try:
            cur.execute('SELECT DISTINCT siteid FROM "4G_pl_hy" WHERE siteid IS NOT NULL ORDER BY siteid LIMIT 20000')
            sites_list = [r[0] for r in cur.fetchall()]
        except psycopg2.OperationalError: raise
        except Exception:
            sites_list = []
            flash("Site list could not be loaded. Please filter by site manually.", "warning")

        try:
            cur.execute('SELECT MAX(date) FROM "4G_pl_hy"')
            raw_last = cur.fetchone()
            last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
        except psycopg2.OperationalError: raise
        except Exception:
            last_update = None

        if from_date and to_date and sel_sites:
            cur.execute("""
                SELECT
                    date, hour, siteid,
                    CASE WHEN SUM(packet_loss_denum)>0
                         THEN ROUND((SUM(packet_loss_num)::numeric/SUM(packet_loss_denum)::numeric)*100.0, 2)
                         ELSE NULL END AS packet_loss_pct,
                    AVG(latency) AS latency_ms,
                    AVG(mean_delay_jitter) AS jitter_ms
                FROM "4G_pl_hy"
                WHERE date BETWEEN %s AND %s AND siteid=ANY(%s)
                GROUP BY date, hour, siteid
                ORDER BY date, hour, siteid
            """, [from_date, to_date, sel_sites])

            hours_seen = {}
            for r in cur.fetchall():
                dh = f"{r[0].strftime('%Y-%m-%d')} {_hour_val(r[1]):02d}:00"
                site = r[2]
                pl_v = float(r[3]) if r[3] is not None else None
                lat  = float(r[4]) if r[4] is not None else None
                jit  = float(r[5]) if r[5] is not None else None
                hours_seen[dh] = True
                chart_pl.setdefault(site, {})[dh] = pl_v
                chart_latency.setdefault(site, {})[dh] = lat
                chart_jitter.setdefault(site, {})[dh] = jit

            chart_labels = sorted(hours_seen.keys())
            for s in chart_pl:
                chart_pl[s]     = [chart_pl[s].get(h)     for h in chart_labels]
                chart_latency[s] = [chart_latency[s].get(h) for h in chart_labels]
                chart_jitter[s]  = [chart_jitter[s].get(h)  for h in chart_labels]

        cur.close(); conn.close()
        cur = None; conn = None
    except psycopg2.OperationalError:
        if cur:   cur.close()
        if conn:  conn.rollback(); conn.close()
        flash("Database connection failed. Please try again.", "warning")
    except Exception as e:
        if cur:   cur.close()
        if conn:  conn.rollback(); conn.close()
        flash(f"Error: {str(e)}", "danger")

    return _no_cache(make_response(render_template(
        "pl_4g.html",
        username=session["username"],
        sites_list=sites_list,
        sel_sites=sel_sites,
        from_date=from_date,
        to_date=to_date,
        last_update=last_update,
        chart_labels=chart_labels,
        chart_pl=chart_pl,
        chart_latency=chart_latency,
        chart_jitter=chart_jitter,
    )))



# ── Export: PL 4G (CSV) ─────────────────────────────────────────────────────────
@pl.route("/export/pl_4g")
@login_required
def export_pl_4g():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")

    valid, err = validate_date_params(from_date, to_date)
    if from_date and to_date and not valid:
        return json_response({"error": err}, 400)
    if not all([from_date, to_date, sel_sites]):
        return json_response({"error": "Missing required parameters"}, 400)

    try:
        conn = get_pumaz_connection(); cur = conn.cursor()
        cur.execute("""
            SELECT
                date, hour, siteid,
                CASE WHEN SUM(packet_loss_denum)>0
                     THEN ROUND((SUM(packet_loss_num)::numeric/SUM(packet_loss_denum)::numeric)*100.0, 2)
                     ELSE NULL END AS packet_loss_pct,
                AVG(latency) AS latency_ms,
                AVG(mean_delay_jitter) AS jitter_ms
            FROM "4G_pl_hy"
            WHERE date BETWEEN %s AND %s AND siteid=ANY(%s)
            GROUP BY date, hour, siteid
            ORDER BY date, hour, siteid
        """, [from_date, to_date, sel_sites])

        headers = ["date", "hour", "siteid", "packet_loss_pct", "latency_ms", "jitter_ms"]
        rows = []
        for r in cur.fetchall():
            rows.append([
                r[0].isoformat() if r[0] else "",
                _hour_val(r[1]),
                r[2] or "",
                float(r[3]) if r[3] is not None else "",
                round(float(r[4]), 2) if r[4] is not None else "",
                round(float(r[5]), 2) if r[5] is not None else "",
            ])
        cur.close(); conn.close()
        return csv_response(rows, headers, f"pl_4g_{from_date}_{to_date}.csv")
    except psycopg2.OperationalError:
        if cur:   cur.close()
        if conn:  conn.rollback(); conn.close()
        return json_response({"error": "Database connection failed."}, 503)
    except Exception as e:
        if cur:   cur.close()
        if conn:  conn.rollback(); conn.close()
        return json_response({"error": str(e)}, 500)

# ── Export: PL 2G (CSV) ─────────────────────────────────────────────────────────
@pl.route("/export/pl_2g")
@login_required
def export_pl_2g():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")

    valid, err = validate_date_params(from_date, to_date)
    if from_date and to_date and not valid:
        return json_response({"error": err}, 400)
    if not all([from_date, to_date, sel_sites]):
        return json_response({"error": "Missing required parameters"}, 400)

    try:
        conn = get_pumaz_connection(); cur = conn.cursor()
        cur.execute("""
            SELECT
                "Date", "Hour", "Site ID",
                CASE WHEN SUM("Packet Loss Rate Denum")>0
                     THEN ROUND((SUM("Packet Loss Rate Num")::numeric/SUM("Packet Loss Rate Denum")::numeric)*100.0, 2)
                     ELSE NULL END AS packet_loss_pct,
                AVG("Mean round-trip delay(ms)") AS latency_ms,
                AVG("Mean delay jitter(ms)") AS jitter_ms
            FROM "2G_pl_hy"
            WHERE "Date" BETWEEN %s AND %s AND "Site ID"=ANY(%s)
            GROUP BY "Date", "Hour", "Site ID"
            ORDER BY "Date", "Hour", "Site ID"
        """, [from_date, to_date, sel_sites])

        headers = ["date", "hour", "site_id", "packet_loss_pct", "latency_ms", "jitter_ms"]
        rows = []
        for r in cur.fetchall():
            rows.append([
                r[0].isoformat() if r[0] else "",
                _hour_val(r[1]),
                r[2] or "",
                float(r[3]) if r[3] is not None else "",
                round(float(r[4]), 2) if r[4] is not None else "",
                round(float(r[5]), 2) if r[5] is not None else "",
            ])
        cur.close(); conn.close()
        return csv_response(rows, headers, f"pl_2g_{from_date}_{to_date}.csv")
    except psycopg2.OperationalError:
        if cur:   cur.close()
        if conn:  conn.rollback(); conn.close()
        return json_response({"error": "Database connection failed."}, 503)
    except Exception as e:
        if cur:   cur.close()
        if conn:  conn.rollback(); conn.close()
        return json_response({"error": str(e)}, 500)