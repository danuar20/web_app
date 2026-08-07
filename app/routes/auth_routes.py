from flask import Blueprint, make_response, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import check_password_hash
from app.db.db_webapp import get_connection, get_postgres_connection
from ._utils import login_required, viewer_blocked, json_response, db_query, _no_cache
import psycopg2
import json
import uuid
import logging
import traceback
import urllib.request
import datetime as _dt_mod
from datetime import datetime, timezone, timedelta
from contextlib import closing
import concurrent.futures

logger = logging.getLogger(__name__)

auth = Blueprint("auth", __name__)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _log_login_safe(username, status, ip, ua, cpu_cores=None, ram_gb=None, gpu_info=None):
    """Audit-log a login attempt using its OWN connection.

    IMPORTANT: never pass the shared login cursor here — a failed INSERT would
    abort the caller's transaction and prevent failed_attempts from being saved.
    """
    import json
    import urllib.request
    location = None
    isp = None
    
    # Try fetching location and ISP
    try:
        if ip and not ip.startswith("127.") and not ip.startswith("192.168.") and not ip.startswith("10."):
            req = urllib.request.Request(f"http://ip-api.com/json/{ip}?fields=city,country,isp")
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    if data.get("city") and data.get("country"):
                        location = f"{data['city']}, {data['country']}"
                    isp = data.get("isp")
    except Exception:
        pass
        
    # Convert hardware stats from string to int safely
    try:
        cpu_cores = int(cpu_cores) if cpu_cores else None
    except ValueError:
        cpu_cores = None
        
    try:
        ram_gb = int(ram_gb) if ram_gb else None
    except ValueError:
        ram_gb = None

    try:
        with db_query(get_connection) as (conn, cur):
            cur.execute(
                "INSERT INTO login_logs (username, ip_address, user_agent, status, location, isp, cpu_cores, ram_gb, gpu_info)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (username, ip, ua, status, location, isp, cpu_cores, ram_gb, gpu_info)
            )
            conn.commit()
    except Exception:
        pass  # Logging must never break the login flow


def _create_session_safe(user_id, ip, ua):
    """Insert a session row using its OWN connection; UUID generated in Python.

    Generates the UUID in Python (uuid.uuid4) to avoid relying on
    gen_random_uuid() which requires pgcrypto on older PostgreSQL versions.
    Returns the UUID string, or None if the insert fails.
    """
    import uuid
    from datetime import datetime, timezone, timedelta
    session_uuid = str(uuid.uuid4())
    expires = datetime.now(timezone.utc) + timedelta(hours=3)
    try:
        with db_query(get_connection) as (conn, cur):
            cur.execute(
                "INSERT INTO user_sessions (id, user_id, ip_address, user_agent, expires_at)"
                " VALUES (%s, %s, %s, %s, %s)",
                (session_uuid, user_id, ip, ua, expires)
            )
            conn.commit()
        return session_uuid
    except Exception:
        import logging
        logging.getLogger(__name__).error(
            "Failed to create user_sessions row for user_id=%s — "
            "is migrate_security.sql applied?", user_id
        )
        return None


# ── Home redirect ───────────────────────────────────────────────────────────────
@auth.route("/")
def home():
    return redirect(url_for("auth.login", v=2))


# ── Login ──────────────────────────────────────────────────────────────────────
@auth.route("/login", methods=["GET", "POST"])
def login():
    # If already logged in, redirect to home
    if request.method == "GET" and "username" in session and "session_id" in session:
        return redirect(url_for("auth.home_page", v=2))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("login.html")

        try:
            ip = request.remote_addr or "unknown"
            ua = request.headers.get("User-Agent", "unknown")[:500]
            
            cpu_cores = request.form.get("cpu_cores")
            ram_gb = request.form.get("ram_gb")
            gpu_info = request.form.get("gpu_info")

            # ── Step 1: Read user (read-only, no commit needed) ─────────────
            user = None
            with db_query(get_connection) as (conn, cur):
                cur.execute(
                    "SELECT id, username, password, role, is_active,"
                    "       failed_attempts, locked_until, max_session"
                    " FROM users WHERE username = %s",
                    (username,)
                )
                user = cur.fetchone()

            if user is None:
                _log_login_safe(username, "FAILED_PASSWORD", ip, ua, cpu_cores, ram_gb, gpu_info)
                flash("Wrong username or password!", "danger")
                return render_template("login.html")

            (user_id, db_username, db_password, role,
             is_active, failed_attempts, locked_until, max_session) = user

            # ── Step 2: Check is_active ─────────────────────────────────────
            if not is_active:
                _log_login_safe(db_username, "INACTIVE", ip, ua, cpu_cores, ram_gb, gpu_info)
                flash("Your account has been disabled. Please contact admin.", "danger")
                return render_template("login.html")

            # ── Step 3: Check lock (compare in Python, no extra query) ───────
            if locked_until is not None:
                from datetime import timezone, datetime as dt_cls
                now_utc = dt_cls.now(timezone.utc)
                # Ensure locked_until is timezone-aware for comparison
                lu = locked_until if locked_until.tzinfo else locked_until.replace(tzinfo=timezone.utc)
                if lu > now_utc:
                    _log_login_safe(db_username, "LOCKED", ip, ua, cpu_cores, ram_gb, gpu_info)
                    flash(
                        f"User {db_username} Locked, please contact admin or try again later!",
                        "danger"
                    )
                    return render_template("login.html")
                else:
                    # Lock has naturally expired — reset (independent commit)
                    try:
                        with db_query(get_connection) as (conn, cur):
                            cur.execute(
                                "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = %s",
                                (user_id,)
                            )
                            conn.commit()
                    except Exception:
                        pass
                    failed_attempts = 0

            # ── Step 4: Verify password ─────────────────────────────────────
            if not check_password_hash(db_password, password):
                new_attempts = failed_attempts + 1
                # Each write is its own transaction — logging can NEVER abort this commit
                try:
                    with db_query(get_connection) as (conn, cur):
                        if new_attempts >= 3:
                            cur.execute(
                                "UPDATE users SET failed_attempts = %s,"
                                " locked_until = NOW() + INTERVAL '5 minutes'"
                                " WHERE id = %s",
                                (new_attempts, user_id)
                            )
                        else:
                            cur.execute(
                                "UPDATE users SET failed_attempts = %s WHERE id = %s",
                                (new_attempts, user_id)
                            )
                        conn.commit()  # Committed independently — safe from log failures
                except Exception:
                    pass
                _log_login_safe(db_username, "FAILED_PASSWORD", ip, ua, cpu_cores, ram_gb, gpu_info)

                if new_attempts >= 3:
                    flash(
                        f"User {db_username} Locked, please contact admin or try again later!",
                        "danger"
                    )
                else:
                    remaining = 3 - new_attempts
                    flash(
                        f"Wrong password! {remaining} attempt(s) remaining before account is locked.",
                        "danger"
                    )
                return render_template("login.html")

            # ── Step 5: Password correct — cleanup old ghost sessions ────────
            # If the user closed the browser (e.g. incognito) and lost their cookie without logging out,
            # their old session is still in the DB. We delete any sessions from the exact same device (IP + UA)
            # BEFORE checking the max_session limit so they don't get unfairly blocked.
            try:
                with db_query(get_connection) as (conn, cur):
                    cur.execute(
                        "DELETE FROM user_sessions WHERE user_id = %s AND ip_address = %s AND user_agent = %s",
                        (user_id, ip, ua)
                    )
                    conn.commit()
            except Exception:
                pass

            # ── Step 5b: Check concurrent session limit ──────────────────────
            active_count = 0
            try:
                with db_query(get_connection) as (conn, cur):
                    cur.execute(
                        "SELECT COUNT(*) FROM user_sessions"
                        " WHERE user_id = %s AND expires_at > NOW()",
                        (user_id,)
                    )
                    active_count = cur.fetchone()[0]
            except Exception:
                pass  # If user_sessions missing, skip limit check

            if active_count >= max_session:
                _log_login_safe(db_username, "SESSION_LIMIT", ip, ua, cpu_cores, ram_gb, gpu_info)
                flash("Maximum User session reached.", "warning")
                return render_template("login.html")

            # ── Step 6: Reset failed_attempts (independent commit) ───────────
            try:
                with db_query(get_connection) as (conn, cur):
                    cur.execute(
                        "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = %s",
                        (user_id,)
                    )
                    conn.commit()
            except Exception:
                pass

            # ── Step 7: Create DB session (independent commit, Python UUID) ──
            # Prevent orphaned sessions: kill old session if they logged in over an existing one
            old_session_id = session.get("session_id")
            if old_session_id:
                try:
                    with db_query(get_connection) as (conn, cur):
                        cur.execute("DELETE FROM user_sessions WHERE id = %s", (old_session_id,))
                        conn.commit()
                except Exception:
                    pass

            session_id = _create_session_safe(user_id, ip, ua)

            # ── Step 8: Log success ──────────────────────────────────────────
            _log_login_safe(db_username, "SUCCESS", ip, ua, cpu_cores, ram_gb, gpu_info)

            session.clear()
            session["username"]   = db_username
            session["user_id"]    = user_id
            session["role"]       = role
            session["session_id"] = session_id
            session.permanent     = True

            return redirect(url_for("auth.home_page", v=2))

        except psycopg2.OperationalError:
            flash("Server offline, please try again later.", "warning")
        except Exception as e:
            import traceback, logging
            logging.getLogger(__name__).error("Login Exception: %s\n%s", e, traceback.format_exc())
            flash("System error: Connection to server timeout", "danger")

    return render_template("login.html")


# ── Home ───────────────────────────────────────────────────────────────────────
@auth.route("/home")
@login_required
def home_page():
    from ._utils import _no_cache
    from datetime import datetime
    response = make_response(render_template("home.html",
        username=session["username"],
        role=session.get("role", "viewer"),
        now=datetime.now().strftime("%d %b %Y %H:%M"),
    ))
    return _no_cache(response)


# ── Home API (async data) ─────────────────────────────────────────────────────
@auth.route("/api/home")
@login_required
def api_home():
    from app import cache
    from app.db.db_webapp import get_postgres_connection, get_connection
    from ._utils import json_response
    import time as _time

    cached_data = cache.get("api_home")
    if cached_data:
        return json_response(cached_data)

    summary = {
        "postgres_db": {"status": "unknown", "last_update_2g": None, "last_update_4g": None, "last_update_5g": None, "site_count_2g": 0, "site_count_4g": 0, "site_count_5g": 0, "last_tp": None, "last_mk2g": None, "last_mk4g": None, "last_2gpl": None, "last_4gpl": None, "last_ta4g": None},
        "webapp_db": {"status": "unknown"},
        "trend_labels": [],
        "trend_payload": {},
        "trend_traffic": {},
    }

    postgres_ok = False

    # ── PostgreSQL DB ──
    try:
        with db_query(get_postgres_connection) as (conn, cur):
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

            for tbl, col, key in [
                ("traffic_payload", "Date", "last_tp"),
                ("measKpiDy2G", "Date", "last_mk2g"),
                ("measKpiDy4G", "Date", "last_mk4g"),
                ("2G_pl_hy", "Date", "last_2gpl"),
                ("4G_pl_hy", "date", "last_4gpl"),
                ("measTA4G", "Date", "last_ta4g"),
                ("measTA5G", "Date", "last_ta5g")
            ]:
                try:
                    cur.execute(f'SELECT MAX("{col}") FROM "{tbl}"')
                    row = cur.fetchone()
                    if row and row[0]:
                        import datetime
                        dt = row[0].date() if isinstance(row[0], datetime.datetime) else row[0]
                        summary["postgres_db"][key] = dt.strftime("%d %b %Y")
                except Exception:
                    pass

            summary["postgres_db"]["status"] = "ok"
            postgres_ok = True
    except Exception:
        summary["postgres_db"]["status"] = "error"


    # ── Productivity trend 30 hari (Traffic + Payload per Tech) ──
    if postgres_ok:
        try:
            with db_query(get_postgres_connection) as (conn, cur):
                cur.execute("SET statement_timeout = '30s'")

                # Determine date range explicitly (last 30 days)
                cur.execute("""
                    SELECT DISTINCT "Date"::date AS d
                    FROM traffic_payload
                    WHERE "Date" >= CURRENT_DATE - INTERVAL '30 days'
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
                    WHERE "Date" >= CURRENT_DATE - INTERVAL '30 days' AND "Tech" IS NOT NULL
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
                    WHERE "Date" >= CURRENT_DATE - INTERVAL '30 days' AND "Tech" IS NOT NULL
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
        except Exception as e:
            logger.error("api_home trend query failed: %s", e, exc_info=True)

    # ── Webapp DB ──
    try:
        with db_query(get_connection) as (conn, cur):
            cur.execute("SELECT 1")
            summary["webapp_db"]["status"] = "ok"
    except Exception:
        summary["webapp_db"]["status"] = "error"

    cache.set("api_home", summary, timeout=300)
    return json_response(summary)


# ── Database Status Page ──────────────────────────────────────────────────────
@auth.route("/database/<db_type>")
@login_required
@viewer_blocked
def database_page(db_type):
    from ._utils import _no_cache
    if db_type != "postgres":
        return redirect(url_for("auth.home_page"))

    response = make_response(render_template("database.html",
        username=session["username"],
        role=session.get("role", "viewer"),
        db_type=db_type
    ))
    return _no_cache(response)


@auth.route("/api/database_status/<db_type>")
@login_required
@viewer_blocked
def api_database_status(db_type):
    from app import cache
    from app.db.db_webapp import get_postgres_connection
    from ._utils import json_response
    import datetime, time

    if db_type != "postgres":
        return json_response({"error": "Invalid db type"})

    cache_key = f"api_database_status_{db_type}_v2"
    cached_data = cache.get(cache_key)
    if cached_data:
        return json_response(cached_data)

    today = datetime.date.today()
    date_list = [(today - datetime.timedelta(days=i)) for i in range(13, -1, -1)]
    date_strs = [d.strftime("%Y-%m-%d") for d in date_list]
    date_labels = [d.strftime("%d %b") for d in date_list]

    result = {
        "labels": date_labels,
        db_type: []
    }

    if db_type == "postgres":
        # ── POSTGRES DB ──
        pg_tables = [
            ("2g_kpi_zte", "datehour"),
            ("4g_kpi_zte", "datehour"),
            ("5g_kpi_zte", "datehour"),
            # Formerly Pumaz tables:
            ("traffic_payload", "Date"),
            ("measKpiDy2G", "Date"),
            ("measKpiDy4G", "Date"),
            ("measKpiBdbh2G", "Date"),
            ("measKpiBdbh4G", "Date"),
            ("measTA4G", "Date"),
            ("measTA5G", "Date"),
            ("2G_pl_hy", "Date"),
            ("4G_pl_hy", "date"),
        ]

        import concurrent.futures

        def fetch_pg_tbl(tbl_info):
            tbl, d_col = tbl_info
            try:
                from contextlib import closing
                with closing(get_postgres_connection()) as conn:
                    with closing(conn.cursor()) as cur:
                        cur.execute("SET statement_timeout = '60s'")
        
                        cur.execute(f'SELECT MIN("{d_col}"), MAX("{d_col}") FROM "{tbl}"')
                        row = cur.fetchone()
                        min_date = row[0] if row else None
                        max_date = row[1] if row else None
        
                        min_str = min_date.strftime("%Y-%m-%d") if min_date else "No Data"
                        max_str = max_date.strftime("%Y-%m-%d") if max_date else "No Data"
        
                        # Calculate the 14-day window relative to today
                        ref_date = datetime.date.today()
        
                        tbl_date_list = [(ref_date - datetime.timedelta(days=i)) for i in range(13, -1, -1)]
                        tbl_date_strs = [d.strftime("%Y-%m-%d") for d in tbl_date_list]
                        tbl_labels = [d.strftime("%d %b") for d in tbl_date_list]
        
                        cur.execute(f'''
                            SELECT "{d_col}"::date, COUNT(*)
                            FROM "{tbl}"
                            WHERE "{d_col}" >= %s
                            GROUP BY "{d_col}"::date
                        ''', [tbl_date_list[0]])
                        counts = {r[0].strftime("%Y-%m-%d"): r[1] for r in cur.fetchall()}
                        history = [counts.get(d, 0) for d in tbl_date_strs]
        
                        return {
                            "table": tbl,
                            "min_date": min_str,
                            "max_date": max_str,
                            "labels": tbl_labels,
                            "history": history
                        }
            except Exception as e:
                return {"table": tbl, "min_date": "Error", "max_date": "Error", "labels": [], "history": [0]*14}

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(fetch_pg_tbl, pg_tables))

        result["postgres"] = results

    cache.set(cache_key, result, timeout=3600)
    return json_response(result)


# ── Health check ───────────────────────────────────────────────────────────────
@auth.route("/health")
def health_check():
    """No auth required — used by load balancers / monitoring."""
    from app.db.db_webapp import get_connection, get_postgres_connection

    status = {
        "app": "ok",
        "postgres_db": None,
        "webapp_db": None
    }
    code = 200

    # Check postgres
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT 1")
            status["postgres_db"] = "ok"
    except Exception as e:
        status["postgres_db"] = str(e)[:80]
        code = 503

    # Check webapp db
    try:
        with db_query(get_connection) as (conn, cur):
            cur.execute("SELECT 1")
            status["webapp_db"] = "ok"
    except Exception as e:
        status["webapp_db"] = str(e)[:80]
        code = 503

    return json_response(status, code)


# ── API: cities by NSA ────────────────────────────────────────────────────────
@auth.route("/api/cities")
@login_required
def api_cities():
    from app.db.db_webapp import get_postgres_connection
    nsas = request.args.getlist("nsa")
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            if nsas:
                cur.execute("""
                    SELECT DISTINCT "KABUPATEN" FROM traffic_payload
                    WHERE "NSA" = ANY(%s) AND "KABUPATEN" IS NOT NULL ORDER BY "KABUPATEN"
                """, (nsas,))
            else:
                cur.execute('SELECT DISTINCT "KABUPATEN" FROM traffic_payload WHERE "KABUPATEN" IS NOT NULL ORDER BY "KABUPATEN"')
            cities = [r[0] for r in cur.fetchall()]
            return jsonify({"cities": cities})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: sites by city ────────────────────────────────────────────────────────
@auth.route("/api/sites")
@login_required
def api_sites():
    from app.db.db_webapp import get_postgres_connection
    cities = request.args.getlist("city")
    nsas   = request.args.getlist("nsa")
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            conditions = ['"Site ID" IS NOT NULL']
            params     = []
            if nsas:
                conditions.append('"NSA" = ANY(%s)'); params.append(nsas)
            if cities:
                conditions.append('"KABUPATEN" = ANY(%s)'); params.append(cities)
            cur.execute(f'SELECT DISTINCT "Site ID" FROM traffic_payload WHERE {" AND ".join(conditions)} ORDER BY "Site ID"', params)
            sites = [r[0] for r in cur.fetchall()]
            return jsonify({"sites": sites})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Logout ─────────────────────────────────────────────────────────────────────
@auth.route("/logout")
def logout():
    """Delete the server-side session row then clear Flask session."""
    session_id = session.get("session_id")
    if session_id:
        try:
            with db_query(get_connection) as (conn, cur):
                cur.execute("DELETE FROM user_sessions WHERE id = %s", (session_id,))
                conn.commit()
        except Exception:
            pass
    session.clear()
    return redirect(url_for("auth.login"))