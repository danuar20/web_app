# Shared utilities for all route modules
from flask import session, redirect, url_for, make_response, jsonify
from functools import wraps
import io, csv, psycopg2


def login_required(f):
    """Decorator: redirect to /login if user has no session."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("auth.login"))
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