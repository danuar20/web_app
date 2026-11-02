# Shared utilities for all route modules
from flask import session, redirect, url_for, make_response, jsonify, flash, request
from functools import wraps
from contextlib import contextmanager
import io, csv, logging, time, psycopg2, psycopg2.errors

logger = logging.getLogger(__name__)


# ── Database Context Manager ─────────────────────────────────────────────────
@contextmanager
def db_query(connection_fn=None):
    """Context manager that provides a (conn, cur) tuple with guaranteed cleanup.

    Usage:
        from app.db.db_webapp import get_postgres_connection
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute("SELECT ...")
            rows = cur.fetchall()

    On exit (normal or exception):
        - cursor is closed
        - connection is rolled back and returned to the pool
    """
    if connection_fn is None:
        from app.db.db_webapp import get_postgres_connection
        connection_fn = get_postgres_connection

    conn = None
    cur = None
    t0 = time.monotonic()
    try:
        conn = connection_fn()
        cur = conn.cursor()
        yield conn, cur
    finally:
        elapsed = time.monotonic() - t0
        if elapsed > 2.0:
            logger.warning("Slow DB query block: %.2fs", elapsed)
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass


def handle_db_errors(f):
    """Decorator that wraps a route function with standardized DB error handling.

    Catches common psycopg2 exceptions and flashes user-friendly messages.
    Must be applied AFTER @login_required (i.e., listed before it in decorator stack).
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except psycopg2.OperationalError:
            logger.exception("DB OperationalError in %s", f.__name__)
            flash("Database connection failed. Please try again.", "warning")
        except psycopg2.errors.QueryCanceled:
            logger.warning("Query timed out in %s", f.__name__)
            flash("Query timed out. Please try a shorter date range.", "warning")
        except psycopg2.errors.ConnectionDoesNotExist:
            logger.error("DB connection lost in %s", f.__name__)
            flash("Database server unreachable. Please try again later.", "warning")
        except psycopg2.Error as e:
            logger.exception("Unexpected DB error in %s: %s", f.__name__, e)
            flash("A database error occurred. Please try again.", "danger")
        except Exception as e:
            logger.exception("Unexpected error in %s: %s", f.__name__, e)
            flash("An unexpected error occurred. Please try again.", "danger")
        # If we caught an error, return None — the caller must handle this
        # (routes should have a fallback render after the try block)
        return None
    return wrapper


def login_required(f):
    """Decorator: redirect to /login if user has no session.

    Also validates that the session UUID still exists and hasn't expired
    in the user_sessions table, preventing access after an admin invalidates
    a user's sessions or the session naturally expires server-side.

    If session_id is None (e.g. migration not yet applied), the DB check is
    skipped so users are not accidentally locked out during a partial deployment.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("auth.login"))

        session_id = session.get("session_id")

        # Only validate against DB if we actually have a UUID stored
        if session_id:
            try:
                from app.db.db_webapp import get_connection
                with db_query(get_connection) as (conn, cur):
                    cur.execute(
                        "SELECT 1 FROM user_sessions WHERE id = %s AND expires_at > NOW()",
                        (session_id,)
                    )
                    if not cur.fetchone():
                        # Session revoked by admin, or expired server-side
                        session.clear()
                        flash("Your session has expired. Please log in again.", "warning")
                        return redirect(url_for("auth.login"))
            except Exception:
                # If DB is unreachable, allow through to avoid lockout on DB hiccup
                pass

        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    """Decorator: requires role == 'admin'. Redirects viewers with a 403 flash.

    Must be stacked AFTER @login_required:
        @blueprint.route("/admin/...")
        @login_required
        @admin_required
        def my_admin_view():
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Access denied. Admin privileges required.", "danger")
            return redirect(url_for("auth.home_page"))
        return f(*args, **kwargs)
    return wrapper


def viewer_blocked(f):
    """Decorator: blocks viewer role from accessing specific pages (e.g. /database).

    Admin can access, viewer is redirected with a flash message.
    Must be stacked AFTER @login_required.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") == "viewer":
            if request.path.startswith("/api/"):
                return jsonify({"status": "error", "message": "Access denied: Role 'viewer' is not authorized for this operation."}), 403
            flash("Access denied. This page is not available for your role.", "danger")
            return redirect(url_for("auth.home_page"))
        return f(*args, **kwargs)
    return wrapper


def json_response(data, status=200):
    """Create JSON response with no-cache headers."""
    resp = make_response(jsonify(data), status)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def csv_response(rows, headers, filename):
    """Create CSV download response with no-cache headers."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    resp = make_response(output.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def _no_cache(response):
    """Add no-store headers so browsers never cache dynamic pages."""
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def ytd_pct(after, before):
    if before and before > 0:
        return round((after - before) / before * 100, 2)
    return None


def validate_date_params(from_date, to_date):
    """Validate from_date and to_date. Returns (is_valid, error_message)."""
    from datetime import datetime
    if not from_date or not to_date:
        return False, None
    try:
        f = datetime.strptime(from_date, "%Y-%m-%d")
        t = datetime.strptime(to_date, "%Y-%m-%d")
        if f > t:
            return False, "from_date must be before or equal to to_date"
        return True, None
    except ValueError:
        return False, "Invalid date format. Use YYYY-MM-DD"


# ── Per-user "last generated view" state ─────────────────────────────────────
# Monitoring pages are plain GET forms. Navigating away to another menu item and
# back used to land on an empty form, forcing the user to re-pick dates + KPIs and
# re-run a multi-second aggregation. The helpers below keep the last generated
# filter set in the (server-side signed) session so a bare menu click restores the
# dashboard, and the result cache serves it without touching the database.

_VIEW_STATE_KEY = "_view_states"
# Flask sessions live in a signed cookie (~4 KB), so keep only the pages the user
# visited most recently instead of every page they ever generated.
_VIEW_STATE_MAX_PAGES = 12

# Boards whose underlying daily/hourly tables are refreshed by batch imports, so a
# result may be reused for an hour without showing stale numbers to the user.
RESULT_CACHE_TTL = 3600


def remember_view(name, **state):
    """Persist the last generated filter state of a page in the user's session."""
    states = dict(session.get(_VIEW_STATE_KEY) or {})
    states.pop(name, None)          # re-insert so the dict stays in LRU order
    states[name] = state
    while len(states) > _VIEW_STATE_MAX_PAGES:
        states.pop(next(iter(states)))
    session[_VIEW_STATE_KEY] = states
    session.modified = True


def recall_view(name):
    """Return the last remembered filter state for a page ({}) when none is saved."""
    return dict((session.get(_VIEW_STATE_KEY) or {}).get(name) or {})

def to_dict(d):
    """Recursively convert defaultdicts and nested containers to standard picklable Python types."""
    from collections import defaultdict
    if isinstance(d, defaultdict):
        return {k: to_dict(v) for k, v in d.items()}
    elif isinstance(d, dict):
        return {k: to_dict(v) for k, v in d.items()}
    elif isinstance(d, list):
        return [to_dict(x) for x in d]
    elif isinstance(d, tuple):
        return tuple(to_dict(x) for x in d)
    return d
