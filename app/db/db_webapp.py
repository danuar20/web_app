import psycopg2
from psycopg2.pool import ThreadedConnectionPool
import os
import time
from flask import g
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


# ── Request-level cache to avoid repeated queries ─────────────────────────────────

def _get_cached(key, factory_fn):
    """Get value from request cache, or compute and cache it."""
    if 'request_cache' not in g:
        g.request_cache = {}
    if key not in g.request_cache:
        g.request_cache[key] = factory_fn()
    return g.request_cache[key]



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
                    SELECT DISTINCT cellid FROM "5g_kpi_zte"
                    WHERE cellid IS NOT NULL
                      AND datehour >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                    ORDER BY cellid
                    LIMIT 5000
                """)
                # cellid is numeric in postgres sometimes, need to convert to str/remove .0
                cells = []
                for r in cur.fetchall():
                    c = str(r[0]).replace(".0", "")
                    if c not in cells:
                        cells.append(c)
                return cells, "kpi"
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
