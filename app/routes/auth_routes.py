from flask import Blueprint, make_response, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import check_password_hash
from app.db.db_webapp import get_connection
from app.db.db_pumaz import get_pumaz_connection
from ._utils import login_required, json_response
import psycopg2

auth = Blueprint("auth", __name__)

# ── Home ───────────────────────────────────────────────────────────────────────
@auth.route("/")
def home():
    return redirect(url_for("auth.login"))

# ── Login ──────────────────────────────────────────────────────────────────────
@auth.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("login.html", error=error)

        try:
            conn = get_connection()
            cur  = conn.cursor()
            cur.execute("SELECT * FROM users WHERE username=%s", (username,))
            user = cur.fetchone()
            cur.close(); conn.close()

            if user and check_password_hash(user[2], password):
                session["username"] = username
                session.permanent = True  # remember me
                return redirect(url_for("auth.dashboard"))
            else:
                flash("Wrong username or password!", "danger")
        except psycopg2.OperationalError:
            flash("Server offline, please try again later.", "warning")
        except Exception:
            flash("System error: Connection to server timeout", "danger")

    return render_template("login.html", error=error)

# ── Dashboard ──────────────────────────────────────────────────────────────────
@auth.route("/dashboard")
@login_required
def dashboard():
    from ._utils import _no_cache
    from datetime import datetime
    response = make_response(render_template("dashboard.html",
        username=session["username"],
        now=datetime.now().strftime("%d %b %Y %H:%M"),
    ))
    return _no_cache(response)

# ── Dashboard API (async data) ────────────────────────────────────────────────
_dash_cache = {"ts": 0, "data": None}
_DASH_CACHE_SECS = 300  # 5 minutes

@auth.route("/api/dashboard")
@login_required
def api_dashboard():
    from app.db.db_webapp import get_postgres_connection, get_connection
    from app.db.db_pumaz import get_pumaz_connection
    from ._utils import json_response
    import time as _time

    now = _time.time()
    if _dash_cache["data"] and (now - _dash_cache["ts"]) < _DASH_CACHE_SECS:
        return json_response(_dash_cache["data"])

    summary = {
        "postgres_db": {"status": "unknown", "last_update_2g": None, "last_update_4g": None, "last_update_5g": None, "site_count_2g": 0, "site_count_4g": 0, "site_count_5g": 0},
        "pumaz_db": {"status": "unknown", "last_update": None},
        "webapp_db": {"status": "unknown"},
        "trend_labels": [],
        "trend_payload": {},
        "trend_traffic": {},
    }

    # ── PostgreSQL DB ──
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '15s'")

        for mv, key in [("mv_siteid_2g", "site_count_2g"), ("mv_siteid_4g", "site_count_4g"), ("mv_siteid_5g", "site_count_5g")]:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{mv}"')
                summary["postgres_db"][key] = (cur.fetchone() or [0])[0]
            except Exception:
                pass

        for tbl, key in [("2g_kpi_zte", "last_update_2g"), ("4g_kpi_zte", "last_update_4g"), ("5g_kpi_zte", "last_update_5g")]:
            try:
                cur.execute(f'SELECT MAX(datehour) FROM "{tbl}"')
                row = cur.fetchone()
                if row and row[0]:
                    summary["postgres_db"][key] = row[0].strftime("%d %b %Y")
            except Exception:
                pass

        summary["postgres_db"]["status"] = "ok"
        cur.close(); conn.close()
    except Exception:
        summary["postgres_db"]["status"] = "error"

    # ── Pumaz DB ──
    pumaz_ok = False
    try:
        conn = get_pumaz_connection()
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '30s'")

        cur.execute('SELECT MAX("Date") FROM traffic_payload')
        row = cur.fetchone()
        summary["pumaz_db"]["last_update"] = row[0].strftime("%d %b %Y") if row and row[0] else None
        summary["pumaz_db"]["status"] = "ok"
        pumaz_ok = True
        cur.close(); conn.close()
    except Exception:
        summary["pumaz_db"]["status"] = "error"

    # ── Productivity trend 14 hari (Traffic + Payload per Tech) ──
    if pumaz_ok:
        try:
            conn = get_pumaz_connection()
            cur = conn.cursor()
            cur.execute("SET statement_timeout = '30s'")

            # Payload per Tech
            cur.execute("""
                SELECT "Date"::date AS d, "Tech", SUM("Payload (MB)")/1024.0/1024.0 AS val
                FROM traffic_payload
                WHERE "Date" >= CURRENT_DATE - INTERVAL '14 days' AND "Tech" IS NOT NULL
                GROUP BY "Date"::date, "Tech" ORDER BY d, "Tech"
            """)
            rows = cur.fetchall()
            dates = []
            payload_by_tech = {}
            for r in rows:
                d_str = r[0].strftime("%d %b")
                if d_str not in dates:
                    dates.append(d_str)
                tech = r[1]
                if tech not in payload_by_tech:
                    payload_by_tech[tech] = []
                payload_by_tech[tech].append(round(float(r[2] or 0), 2))

            # Traffic per Tech
            cur.execute("""
                SELECT "Date"::date AS d, "Tech", SUM("Traffic (erlang)")/1000.0 AS val
                FROM traffic_payload
                WHERE "Date" >= CURRENT_DATE - INTERVAL '14 days' AND "Tech" IS NOT NULL
                GROUP BY "Date"::date, "Tech" ORDER BY d, "Tech"
            """)
            rows = cur.fetchall()
            traffic_by_tech = {}
            for r in rows:
                tech = r[1]
                if tech not in traffic_by_tech:
                    traffic_by_tech[tech] = []
                traffic_by_tech[tech].append(round(float(r[2] or 0), 2))

            summary["trend_labels"] = dates
            summary["trend_payload"] = payload_by_tech
            summary["trend_traffic"] = traffic_by_tech

            cur.close(); conn.close()
        except Exception:
            pass

    # ── Webapp DB ──
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close(); conn.close()
        summary["webapp_db"]["status"] = "ok"
    except Exception:
        summary["webapp_db"]["status"] = "error"

    _dash_cache["ts"] = now
    _dash_cache["data"] = summary
    return json_response(summary)

# ── Health check ───────────────────────────────────────────────────────────────
@auth.route("/health")
def health_check():
    """No auth required — used by load balancers / monitoring."""
    from app.db.db_webapp import get_connection, get_postgres_connection

    status = {
        "app": "ok",
        "postgres_db": None,
        "pumaz_db": None,
        "webapp_db": None
    }
    code = 200

    # Check postgres
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close(); conn.close()
        status["postgres_db"] = "ok"
    except Exception as e:
        status["postgres_db"] = str(e)[:80]
        code = 503

    # Check pumaz
    try:
        conn = get_pumaz_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close(); conn.close()
        status["pumaz_db"] = "ok"
    except Exception as e:
        status["pumaz_db"] = str(e)[:80]
        code = 503

    # Check webapp db
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close(); conn.close()
        status["webapp_db"] = "ok"
    except Exception as e:
        status["webapp_db"] = str(e)[:80]
        code = 503

    return json_response(status, code)

# ── API: cities by NSA ────────────────────────────────────────────────────────
@auth.route("/api/cities")
@login_required
def api_cities():
    nsas = request.args.getlist("nsa")
    try:
        conn = get_pumaz_connection()
        cur  = conn.cursor()
        if nsas:
            cur.execute("""
                SELECT DISTINCT "KABUPATEN" FROM traffic_payload
                WHERE "NSA" = ANY(%s) AND "KABUPATEN" IS NOT NULL ORDER BY "KABUPATEN"
            """, (nsas,))
        else:
            cur.execute('SELECT DISTINCT "KABUPATEN" FROM traffic_payload WHERE "KABUPATEN" IS NOT NULL ORDER BY "KABUPATEN"')
        cities = [r[0] for r in cur.fetchall()]
        cur.close(); conn.close()
        return jsonify({"cities": cities})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── API: sites by city ────────────────────────────────────────────────────────
@auth.route("/api/sites")
@login_required
def api_sites():
    cities = request.args.getlist("city")
    nsas   = request.args.getlist("nsa")
    try:
        conn = get_pumaz_connection()
        cur  = conn.cursor()
        conditions = ['"Site ID" IS NOT NULL']
        params     = []
        if nsas:
            conditions.append('"NSA" = ANY(%s)'); params.append(nsas)
        if cities:
            conditions.append('"KABUPATEN" = ANY(%s)'); params.append(cities)
        cur.execute(f'SELECT DISTINCT "Site ID" FROM traffic_payload WHERE {" AND ".join(conditions)} ORDER BY "Site ID"', params)
        sites = [r[0] for r in cur.fetchall()]
        cur.close(); conn.close()
        return jsonify({"sites": sites})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Logout ─────────────────────────────────────────────────────────────────────
@auth.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("auth.login"))