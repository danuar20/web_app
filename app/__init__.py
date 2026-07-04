from flask import Flask, render_template
from flask_wtf import CSRFProtect


from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

# Load .env from the project root (absolute path, works regardless of CWD)
_project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_project_dir, ".env"))

def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    )

    # ── 1. SECRET KEY ─────────────────────────────────────────────────────────
    secret_key = os.getenv("FLASK_SECRET_KEY")
    if not secret_key:
        raise RuntimeError(
            "FLASK_SECRET_KEY environment variable is not set. "
            "Set it to a strong random value before starting the server."
        )
    app.secret_key = secret_key

    app.config['JSON_SORT_KEYS'] = False

    # ── 2. SECURE SESSION COOKIES ───────────────────────────────────────────────
    # NOTE: SECURE=False because app runs on HTTP (no SSL behind reverse proxy)
    app.config['SESSION_COOKIE_SECURE']  = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE']  = 'Lax'

    # ── 3. CSRF PROTECTION via Flask-WTF ───────────────────────────────────────
    app.config['WTF_CSRF_ENABLED']    = True
    app.config['WTF_CSRF_TIME_LIMIT']  = 3600

    # Initialize CSRF protection so `csrf_token()` is available in templates
    csrf = CSRFProtect()
    csrf.init_app(app)

    # ── 4. CUSTOM JINJA2 FILTERS ────────────────────────────────────────────────
    def _date_modify(value, modifier):
        try:
            dt = datetime.strptime(str(value), '%Y-%m-%d') if value != "now" else datetime.now()
        except (ValueError, TypeError):
            dt = datetime.now()
        parts = modifier.strip().split()
        if len(parts) == 2:
            delta = timedelta(**{parts[1]: int(parts[0])})
            return (dt + delta).strftime('%Y-%m-%d')
        return value

    def _fmt_date(value, fmt='%Y-%m-%d'):
        if value == "now":
            return datetime.now().strftime(fmt)
        if isinstance(value, datetime):
            return value.strftime(fmt)
        try:
            return datetime.strptime(str(value), '%Y-%m-%d').strftime(fmt)
        except (ValueError, TypeError):
            return value

    app.jinja_env.filters['date_modify'] = _date_modify
    app.jinja_env.filters['date'] = _fmt_date

    # ── 5. REGISTER BLUEPRINTS ─────────────────────────────────────────────────
    from .routes import (
        auth, prod,
        kpi2g_hourly_sector, kpi2g_compare, kpi2g_monitoring,
        kpi4g_daily, kpi4g_hourly, kpi4g_trend, kpi4g_compare, kpi4g_api, kpi4g_hourly_sector, kpi4g_monitoring,
        kpi5g_daily, kpi5g_hourly, kpi5g_hourly_sector, kpi5g_compare, kpi5g_monitoring,
        pl, ta4g, dashboard_2g, dashboard_4g, dashboard_5g, coverage, okumura_hata, nettilt3d
    )
    app.register_blueprint(auth)
    app.register_blueprint(prod)
    app.register_blueprint(kpi2g_hourly_sector)
    app.register_blueprint(kpi2g_compare)
    app.register_blueprint(kpi2g_monitoring)
    app.register_blueprint(kpi4g_daily)
    app.register_blueprint(kpi4g_hourly)
    app.register_blueprint(kpi4g_hourly_sector)
    app.register_blueprint(kpi4g_trend)
    app.register_blueprint(kpi4g_compare)
    app.register_blueprint(kpi4g_api)
    app.register_blueprint(kpi4g_monitoring)
    app.register_blueprint(kpi5g_daily)
    app.register_blueprint(kpi5g_hourly)
    app.register_blueprint(kpi5g_hourly_sector)
    app.register_blueprint(kpi5g_compare)
    app.register_blueprint(kpi5g_monitoring)
    app.register_blueprint(pl)
    app.register_blueprint(ta4g)
    app.register_blueprint(dashboard_2g)
    app.register_blueprint(dashboard_4g)
    app.register_blueprint(dashboard_5g)
    app.register_blueprint(coverage)
    app.register_blueprint(okumura_hata)
    app.register_blueprint(nettilt3d)
 

    # ── 6. CACHE BUSTING ───────────────────────────────────────────────────────
    @app.after_request
    def add_header(response):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    # ── 7. CUSTOM ERROR HANDLERS ───────────────────────────────────────────────
    @app.errorhandler(404)
    def handle_404(e):
        return render_template("error.html", code=404,
                               message="Page not found."), 404

    @app.errorhandler(500)
    def handle_500(e):
        import logging
        logging.error("Unhandled 500 error: %s", str(e), exc_info=True)
        return render_template("error.html", code=500,
                               message="An internal error occurred. Please try again later."), 500

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        import logging
        logging.error("Unhandled exception: %s", str(e), exc_info=True)
        return render_template("error.html", code=500,
                               message="An unexpected error occurred. Please try again later."), 500

    return app