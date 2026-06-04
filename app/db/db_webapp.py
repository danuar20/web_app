import psycopg2
import os
import time

def _connect_with_retry(connect_fn, max_retries=2, delay=1.0):
    """Try connect_fn() up to max_retries times with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return connect_fn()
        except psycopg2.OperationalError:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay * (attempt + 1))
    raise psycopg2.OperationalError("Max retries exceeded")

def get_connection():
    """Connect to webapp_db for user authentication and basic data"""
    def _conn():
        return psycopg2.connect(
            host=os.getenv("WEBAPP_DB_HOST"),
            database=os.getenv("WEBAPP_DB_NAME"),
            user=os.getenv("WEBAPP_DB_USER"),
            password=os.getenv("WEBAPP_DB_PASSWORD"),
            port=os.getenv("WEBAPP_DB_PORT", "5432"),
            connect_timeout=12,
            options="-c statement_timeout=120000"
        )
    return _connect_with_retry(_conn)

def get_postgres_connection():
    """Connect to postgres database for 2G 4G 5G hourly KPI data"""
    def _conn():
        return psycopg2.connect(
            host=os.getenv("POSTGRES_DB_HOST"),
            database=os.getenv("POSTGRES_DB_NAME"),
            user=os.getenv("POSTGRES_DB_USER"),
            password=os.getenv("POSTGRES_DB_PASSWORD"),
            port=os.getenv("POSTGRES_DB_PORT", "5432"),
            connect_timeout=12,
            options="-c statement_timeout=360000"
        )
    return _connect_with_retry(_conn)


# ── Request-level cache to avoid repeated queries ─────────────────────────────────
_request_cache = {}


def _get_cached(key, factory_fn):
    """Get value from request cache, or compute and cache it."""
    if key not in _request_cache:
        _request_cache[key] = factory_fn()
    return _request_cache[key]


def clear_request_cache():
    """Clear the request cache. Call at the start of each request."""
    global _request_cache
    _request_cache = {}


def get_site_list_2g():
    """
    Get list of 2G site IDs from siteID_2g reference table.
    Cached per request for performance.
    Returns: list of site IDs
    """
    return _get_cached("2g_sites", lambda: _get_site_list_2g_impl())


def _get_site_list_2g_impl():
    """Internal implementation — uses mv_siteid_2g materialized view."""
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute('SELECT siteid FROM "mv_siteid_2g" WHERE siteid IS NOT NULL ORDER BY siteid')
        sites = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        if sites:
            return sites
    except Exception:
        pass

    # Fallback: extract from 2g_kpi_zte using siteid column
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT siteid FROM "2g_kpi_zte"
            WHERE siteid IS NOT NULL
              AND datehour >= CURRENT_TIMESTAMP - INTERVAL '30 days'
            ORDER BY siteid
            LIMIT 10000
        """)
        sites = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        return sites
    except Exception:
        return []


def get_site_list_4g():
    """Get the list of 4G site IDs from the siteID_4g reference table."""
    return _get_cached("4g_sites", lambda: _get_site_list_4g_impl())


def _get_site_list_4g_impl():
    """Internal implementation — uses mv_siteid_4g materialized view with siteid column."""
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute('SELECT siteid FROM "mv_siteid_4g" WHERE siteid IS NOT NULL ORDER BY siteid')
        sites = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        if sites:
            return sites, "reference"
    except Exception:
        pass

    # Fallback: extract from 4g_kpi_zte using siteid column
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT siteid FROM "4g_kpi_zte"
            WHERE siteid IS NOT NULL
              AND date >= CURRENT_DATE - INTERVAL '30 days'
            ORDER BY siteid
            LIMIT 5000
        """)
        sites = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        return sites, "kpi"
    except Exception as e:
        return [], str(e)


def get_site_list_5g():
    """
    Get the list of 5G site IDs from the siteID_5g view in the postgres DB.
    Returns: tuple (list of site IDs, source label)
    """
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute('SELECT siteid FROM "mv_siteid_5g" WHERE siteid IS NOT NULL ORDER BY siteid')
        sites = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        if sites:
            return sites, "reference"
    except Exception:
        pass

    return [], "no_data"
