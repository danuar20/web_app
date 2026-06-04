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
    response = make_response(render_template("dashboard.html", username=session["username"]))
    return _no_cache(response)

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