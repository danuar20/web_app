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

            # Determine date range explicitly (last 14 days)
            cur.execute("""
                SELECT DISTINCT "Date"::date AS d
                FROM traffic_payload
                WHERE "Date" >= CURRENT_DATE - INTERVAL '14 days'
                ORDER BY d
            """)
            all_dates_rows = cur.fetchall()
            dates = [r[0].strftime("%d %b") for r in all_dates_rows]
            date_objs = [r[0] for r in all_dates_rows]

            # Initialize dicts
            payload_by_tech = {}
            traffic_by_tech = {}
            
            # Helper function to initialize tech lists
            def get_tech_list(tech_dict, tech):
                if tech not in tech_dict:
                    tech_dict[tech] = [0.0] * len(dates)
                return tech_dict[tech]

            # Payload per Tech
            cur.execute("""
                SELECT "Date"::date AS d, "Tech", SUM("Payload (MB)")/1024.0/1024.0 AS val
                FROM traffic_payload
                WHERE "Date" >= CURRENT_DATE - INTERVAL '14 days' AND "Tech" IS NOT NULL
                GROUP BY "Date"::date, "Tech" ORDER BY d, "Tech"
            """)
            for r in cur.fetchall():
                d_obj = r[0]
                tech = r[1]
                val = round(float(r[2] or 0), 2)
                if d_obj in date_objs:
                    idx = date_objs.index(d_obj)
                    get_tech_list(payload_by_tech, tech)[idx] = val

            # Traffic per Tech
            cur.execute("""
                SELECT "Date"::date AS d, "Tech", SUM("Traffic (erlang)")/1000.0 AS val
                FROM traffic_payload
                WHERE "Date" >= CURRENT_DATE - INTERVAL '14 days' AND "Tech" IS NOT NULL
                GROUP BY "Date"::date, "Tech" ORDER BY d, "Tech"
            """)
            for r in cur.fetchall():
                d_obj = r[0]
                tech = r[1]
                val = round(float(r[2] or 0), 2)
                if d_obj in date_objs:
                    idx = date_objs.index(d_obj)
                    get_tech_list(traffic_by_tech, tech)[idx] = val

            summary["trend_labels"] = dates
            summary["trend_payload"] = payload_by_tech
            summary["trend_traffic"] = traffic_by_tech

            cur.close(); conn.close()
        except Exception as e:
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

# ── Database Status Page ──────────────────────────────────────────────────────
@auth.route("/database/<db_type>")
@login_required
def database_page(db_type):
    from ._utils import _no_cache
    if db_type not in ["pumaz", "postgres"]:
        return redirect(url_for("auth.dashboard"))
        
    response = make_response(render_template("database.html",
        username=session["username"],
        db_type=db_type
    ))
    return _no_cache(response)

_db_cache = {"ts": 0, "data": None}

@auth.route("/api/database_status")
@login_required
def api_database_status():
    from app.db.db_webapp import get_postgres_connection
    from app.db.db_pumaz import get_pumaz_connection
    from ._utils import json_response
    import datetime, time
    
    now = time.time()
    if _db_cache["data"] and (now - _db_cache["ts"]) < 3600:
        return json_response(_db_cache["data"])
    
    today = datetime.date.today()
    date_list = [(today - datetime.timedelta(days=i)) for i in range(13, -1, -1)]
    date_strs = [d.strftime("%Y-%m-%d") for d in date_list]
    date_labels = [d.strftime("%d %b") for d in date_list]
    
    result = {
        "labels": date_labels,
        "pumaz": [],
        "postgres": []
    }
    
    # ── PUMAZ DB ──
    pumaz_tables = [
        ("traffic_payload", "Date"),
        ("measKpiDy2G", "Date"),
        ("measKpiDy4G", "Date"),
        ("measKpiBdbh2G", "Date"),
        ("measKpiBdbh4G", "Date"),
        ("measTA4G", "Date"),
        ("2G_pl_hy", "Date"),
        ("4G_pl_hy", "date"),
    ]
    try:
        conn = get_pumaz_connection()
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '60s'")
        for tbl, d_col in pumaz_tables:
            try:
                cur.execute(f'SELECT MIN("{d_col}"), MAX("{d_col}") FROM "{tbl}"')
                row = cur.fetchone()
                min_str = row[0].strftime("%Y-%m-%d") if row and row[0] else "No Data"
                max_str = row[1].strftime("%Y-%m-%d") if row and row[1] else "No Data"
                
                cur.execute(f'''
                    SELECT "{d_col}"::date, COUNT(*) 
                    FROM "{tbl}" 
                    WHERE "{d_col}" >= CURRENT_DATE - INTERVAL '13 days' 
                    GROUP BY "{d_col}"::date
                ''')
                counts = {r[0].strftime("%Y-%m-%d"): r[1] for r in cur.fetchall()}
                history = [counts.get(d, 0) for d in date_strs]
                
                result["pumaz"].append({
                    "table": tbl,
                    "min_date": min_str,
                    "max_date": max_str,
                    "history": history
                })
            except Exception as e:
                conn.rollback()
                result["pumaz"].append({"table": tbl, "min_date": "Error", "max_date": "Error", "history": [0]*14})
        cur.close(); conn.close()
    except Exception:
        pass

    # ── POSTGRES DB ──
    pg_tables = [
        ("2g_kpi_zte", "date"),
        ("4g_kpi_zte", "date"),
        ("5g_kpi_zte", "date"),
    ]
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '60s'")
        for tbl, d_col in pg_tables:
            try:
                cur.execute(f'SELECT MIN("{d_col}"), MAX("{d_col}") FROM "{tbl}"')
                row = cur.fetchone()
                min_str = row[0].strftime("%Y-%m-%d") if row and row[0] else "No Data"
                max_str = row[1].strftime("%Y-%m-%d") if row and row[1] else "No Data"
                
                cur.execute(f'''
                    SELECT "{d_col}"::date, COUNT(*) 
                    FROM "{tbl}" 
                    WHERE "{d_col}" >= CURRENT_DATE - INTERVAL '13 days' 
                    GROUP BY "{d_col}"::date
                ''')
                counts = {r[0].strftime("%Y-%m-%d"): r[1] for r in cur.fetchall()}
                history = [counts.get(d, 0) for d in date_strs]
                
                result["postgres"].append({
                    "table": tbl,
                    "min_date": min_str,
                    "max_date": max_str,
                    "history": history
                })
            except Exception as e:
                conn.rollback()
                result["postgres"].append({"table": tbl, "min_date": "Error", "max_date": "Error", "history": [0]*14})
        cur.close(); conn.close()
    except Exception:
        pass

    _db_cache["ts"] = now
    _db_cache["data"] = result
    return json_response(result)

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