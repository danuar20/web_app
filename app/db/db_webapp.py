import psycopg2
from psycopg2.pool import ThreadedConnectionPool
import os
import time
from flask import g, has_request_context
from contextlib import closing

class PooledConnectionWrapper:
    """Wraps a pooled psycopg2 connection to intercept .close() calls."""
    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn

    def __getattr__(self, name):
        # Delegate all other attributes/methods to the underlying psycopg2 connection
        return getattr(self._conn, name)

    def close(self):
        # Instead of physically closing the connection, return it to the pool
        if self._conn is not None:
            try:
                # Always rollback to ensure clean state before returning to pool
                self._conn.rollback()
            except Exception:
                pass
            self._pool.putconn(self._conn)
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

# ── Connection Pools ──────────────────────────────────────────────────────────

_webapp_pool = None
_postgres_pool = None

def get_webapp_pool():
    global _webapp_pool
    if _webapp_pool is None:
        _webapp_pool = ThreadedConnectionPool(
            minconn=1, maxconn=20,
            host=os.getenv("WEBAPP_DB_HOST"),
            database=os.getenv("WEBAPP_DB_NAME"),
            user=os.getenv("WEBAPP_DB_USER"),
            password=os.getenv("WEBAPP_DB_PASSWORD"),
            port=os.getenv("WEBAPP_DB_PORT", "5432"),
            connect_timeout=12,
            options="-c statement_timeout=120000"
        )
    return _webapp_pool

def get_postgres_pool():
    global _postgres_pool
    if _postgres_pool is None:
        _postgres_pool = ThreadedConnectionPool(
            minconn=1, maxconn=20,
            host=os.getenv("POSTGRES_DB_HOST"),
            database=os.getenv("POSTGRES_DB_NAME"),
            user=os.getenv("POSTGRES_DB_USER"),
            password=os.getenv("POSTGRES_DB_PASSWORD"),
            port=os.getenv("POSTGRES_DB_PORT", "5432"),
            connect_timeout=12,
            options="-c statement_timeout=360000"
        )
    return _postgres_pool

def _get_connection_with_retry(pool, max_retries=2, delay=1.0):
    for attempt in range(max_retries):
        try:
            conn = pool.getconn()
            return PooledConnectionWrapper(pool, conn)
        except psycopg2.OperationalError:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay * (attempt + 1))
    raise psycopg2.OperationalError("Max retries exceeded")

def get_connection():
    """Connect to webapp_db for user authentication and basic data"""
    return _get_connection_with_retry(get_webapp_pool())

def get_postgres_connection():
    """Connect to postgres database for 2G 4G 5G hourly KPI data"""
    return _get_connection_with_retry(get_postgres_pool())


# ── Process-level & Request-level Cache ─────────────────────────────────────────

_GLOBAL_MEM_CACHE = {}
_GLOBAL_MEM_CACHE_TTL = 900  # 15 minutes

def _get_cached(key, factory_fn):
    """Get value from process memory cache or request cache, or compute and cache it."""
    now = time.time()
    if key in _GLOBAL_MEM_CACHE:
        val, expiry = _GLOBAL_MEM_CACHE[key]
        if now < expiry:
            return val
            
    if has_request_context():
        if 'request_cache' not in g:
            g.request_cache = {}
        if key in g.request_cache:
            return g.request_cache[key]
        
    val = factory_fn()
    if has_request_context():
        g.request_cache[key] = val
    if val and isinstance(val, tuple) and val[0]:
        _GLOBAL_MEM_CACHE[key] = (val, now + _GLOBAL_MEM_CACHE_TTL)
    return val



def get_site_list_4g():
    """Get the list of 4G site IDs from the siteID_4g reference table."""
    return _get_cached("4g_sites", lambda: _get_site_list_4g_impl())


def _get_site_list_4g_impl():
    """Internal implementation — uses mv_siteid_4g materialized view with siteid column."""
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute('SELECT siteid FROM "mv_siteid_4g" WHERE siteid IS NOT NULL ORDER BY siteid')
                sites = [r[0] for r in cur.fetchall()]
                if sites:
                    return sites, "reference"
    except Exception:
        pass

    # Fallback: extract from 4g_kpi_zte using siteid column
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT siteid FROM "4g_kpi_zte"
                    WHERE siteid IS NOT NULL
                      AND date >= CURRENT_DATE - INTERVAL '30 days'
                    ORDER BY siteid
                    LIMIT 5000
                """)
                return [r[0] for r in cur.fetchall()], "kpi"
    except Exception as e:
        return [], str(e)

def get_site_cell_list_4g():
    """Get the list of 4G site cells from the mv_site_cell_4g reference table."""
    return _get_cached("4g_site_cells", lambda: _get_site_cell_list_4g_impl())

def _get_site_cell_list_4g_impl():
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute('SELECT site_cell FROM "mv_site_cell_4g" WHERE site_cell IS NOT NULL ORDER BY site_cell')
                cells = [r[0] for r in cur.fetchall()]
                if cells:
                    return cells, "reference"
    except Exception:
        pass

    # Fallback: extract from 4g_kpi_zte using cell column
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT cell FROM "4g_kpi_zte"
                    WHERE cell IS NOT NULL
                      AND date >= CURRENT_DATE - INTERVAL '30 days'
                    ORDER BY cell
                    LIMIT 5000
                """)
                return [r[0] for r in cur.fetchall()], "kpi"
    except Exception as e:
        return [], str(e)


def get_site_list_5g():
    """Get the list of 5G site IDs from the siteID_5g view in the postgres DB."""
    return _get_cached("5g_sites", lambda: _get_site_list_5g_impl())

def _get_site_list_5g_impl():
    """Internal implementation — uses mv_siteid_5g materialized view with siteid column."""
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute('SELECT siteid FROM "mv_siteid_5g" WHERE siteid IS NOT NULL ORDER BY siteid')
                sites = [r[0] for r in cur.fetchall()]
                if sites:
                    return sites, "reference"
    except Exception:
        pass

    # Fallback: extract from 5g_kpi_zte
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT siteid FROM "5g_kpi_zte"
                    WHERE siteid IS NOT NULL
                      AND datehour >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                    ORDER BY siteid
                    LIMIT 5000
                """)
                return [r[0] for r in cur.fetchall()], "kpi"
    except Exception as e:
        return [], str(e)

def get_site_cellid_list_5g():
    """Get the list of 5G site cells."""
    return _get_cached("5g_site_cellids", lambda: _get_site_cellid_list_5g_impl())

def _get_site_cellid_list_5g_impl():
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute('SELECT site_cell FROM "mv_site_cell_5g" WHERE site_cell IS NOT NULL ORDER BY site_cell')
                cells = [r[0] for r in cur.fetchall()]
                if cells:
                    return cells, "reference"
    except Exception:
        pass

    # Fallback: extract from 5g_kpi_zte using cellid column
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT siteid || '-' || REPLACE(cellid::text, '.0', '') AS site_cell
                    FROM "5g_kpi_zte"
                    WHERE siteid IS NOT NULL AND cellid IS NOT NULL
                      AND datehour >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                    ORDER BY site_cell
                    LIMIT 50000
                """)
                return [r[0] for r in cur.fetchall()], "kpi"
    except Exception as e:
        return [], str(e)

def get_site_list_2g():
    """Get the list of 2G site IDs from the mv_siteid_2g view in the postgres DB."""
    return _get_cached("2g_sites", lambda: _get_site_list_2g_impl())

def _get_site_list_2g_impl():
    """Internal implementation — uses mv_siteid_2g materialized view with siteid column."""
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute('SELECT siteid FROM "mv_siteid_2g" WHERE siteid IS NOT NULL ORDER BY siteid')
                sites = [r[0] for r in cur.fetchall()]
                if sites:
                    return sites, "reference"
    except Exception:
        pass

    # Fallback: extract from 2g_kpi_zte
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT siteid FROM "2g_kpi_zte"
                    WHERE siteid IS NOT NULL
                      AND datehour >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                    ORDER BY siteid
                    LIMIT 5000
                """)
                return [r[0] for r in cur.fetchall()], "kpi"
    except Exception as e:
        return [], str(e)


def get_site_cell_list_2g():
    """Get the list of 2G site cells."""
    return _get_cached("2g_site_cells", lambda: _get_site_cell_list_2g_impl())

def _get_site_cell_list_2g_impl():
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute('SELECT site_cell FROM "mv_site_cell_2g" WHERE site_cell IS NOT NULL ORDER BY site_cell')
                cells = [r[0] for r in cur.fetchall()]
                if cells:
                    return cells, "reference"
    except Exception:
        pass

    # Fallback: extract from 2g_kpi_zte using siteid and bts columns
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT siteid || '-' || bts AS site_cell
                    FROM "2g_kpi_zte"
                    WHERE siteid IS NOT NULL AND bts IS NOT NULL
                      AND datehour >= CURRENT_TIMESTAMP - INTERVAL '7 days'
                    ORDER BY site_cell
                    LIMIT 50000
                """)
                return [r[0] for r in cur.fetchall()], "kpi"
    except Exception as e:
        return [], str(e)


# ── City Lists ────────────────────────────────────────────────────────────────

def get_city_list_4g():
    """Get the list of unique 4G cities using latest date and cache."""
    return _get_cached("4g_cities", lambda: _get_city_list_4g_impl())

def _get_city_list_4g_impl():
    # 1. Fast: Query distinct cities from daily table for the latest date
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT city FROM "4g_kpi_zte_daily"
                    WHERE kpi_date = (SELECT MAX(kpi_date) FROM "4g_kpi_zte_daily")
                      AND city IS NOT NULL AND city != ''
                    ORDER BY city
                """)
                cities = [r[0] for r in cur.fetchall()]
                if cities:
                    return cities, "daily_latest"
    except Exception:
        pass
    # 2. Fallback: Query from hourly table on the latest date
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT city FROM "4g_kpi_zte"
                    WHERE date = (SELECT MAX(date) FROM "4g_kpi_zte")
                      AND city IS NOT NULL AND city != ''
                    ORDER BY city
                """)
                cities = [r[0] for r in cur.fetchall()]
                if cities:
                    return cities, "hourly_latest"
    except Exception as e:
        return [], str(e)


def get_city_list_2g():
    """Get the list of unique 2G cities grouped by NSA using latest date and cache."""
    return _get_cached("2g_cities_grouped", lambda: _get_city_list_2g_impl())

def _get_city_list_2g_impl():
    # 1. Fast: Query distinct NSA and city from daily table for the latest date
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT COALESCE(nsa, 'UNKNOWN') AS nsa, city
                    FROM "2g_kpi_zte_daily"
                    WHERE kpi_date = (SELECT MAX(kpi_date) FROM "2g_kpi_zte_daily")
                      AND city IS NOT NULL AND city != ''
                    ORDER BY nsa, city
                """)
                rows = cur.fetchall()
                if rows:
                    cities = [{"name": r[1], "group": r[0]} for r in rows]
                    return cities, "daily_latest"
    except Exception:
        pass
    # 2. Fallback: Query from hourly table on the latest date
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT COALESCE(nsa, 'UNKNOWN') AS nsa, city
                    FROM "2g_kpi_zte"
                    WHERE date = (SELECT MAX(date) FROM "2g_kpi_zte")
                      AND city IS NOT NULL AND city != ''
                    ORDER BY nsa, city
                """)
                rows = cur.fetchall()
                if rows:
                    cities = [{"name": r[1], "group": r[0]} for r in rows]
                    return cities, "hourly_latest"
    except Exception as e:
        return [], str(e)


def get_bsc_list_2g():
    """Get the list of unique 2G BSCs (me_name) grouped by NSA using latest date and cache."""
    return _get_cached("2g_bscs_grouped", lambda: _get_bsc_list_2g_impl())

def _get_bsc_list_2g_impl():
    # 1. Fast: Query distinct NSA and BSC from daily table for the latest date
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT COALESCE(nsa, 'UNKNOWN') AS nsa, me_name
                    FROM "2g_kpi_zte_daily"
                    WHERE kpi_date = (SELECT MAX(kpi_date) FROM "2g_kpi_zte_daily")
                      AND me_name IS NOT NULL AND me_name != ''
                    ORDER BY nsa, me_name
                """)
                rows = cur.fetchall()
                if rows:
                    bscs = [{"name": r[1], "group": r[0]} for r in rows]
                    return bscs, "daily_latest"
    except Exception:
        pass
    # 2. Fallback: Query from hourly table on the latest date
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT COALESCE(nsa, 'UNKNOWN') AS nsa, me_name
                    FROM "2g_kpi_zte"
                    WHERE date = (SELECT MAX(date) FROM "2g_kpi_zte")
                      AND me_name IS NOT NULL AND me_name != ''
                    ORDER BY nsa, me_name
                """)
                rows = cur.fetchall()
                if rows:
                    bscs = [{"name": r[1], "group": r[0]} for r in rows]
                    return bscs, "hourly_latest"
    except Exception as e:
        return [], str(e)


def get_city_list_5g():
    """Get the list of unique 5G cities using latest date and cache."""
    return _get_cached("5g_cities", lambda: _get_city_list_5g_impl())

def _get_city_list_5g_impl():
    # Query from 5G table on the latest date
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT city FROM "5g_kpi_zte"
                    WHERE date = (SELECT MAX(date) FROM "5g_kpi_zte")
                      AND city IS NOT NULL AND city != ''
                    ORDER BY city
                """)
                cities = [r[0] for r in cur.fetchall()]
                if cities:
                    return cities, "hourly_latest"
    except Exception:
        pass
    try:
        with closing(get_postgres_connection()) as conn:
            with closing(conn.cursor()) as cur:
                cur.execute("""
                    SELECT DISTINCT city FROM "5g_kpi_zte"
                    WHERE datehour >= (SELECT MAX(datehour) - INTERVAL '1 day' FROM "5g_kpi_zte")
                      AND city IS NOT NULL AND city != ''
                    ORDER BY city
                """)
                cities = [r[0] for r in cur.fetchall()]
                if cities:
                    return cities, "datehour_latest"
    except Exception as e:
        return [], str(e)

