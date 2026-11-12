"""
Read-only SQL query console for the Postgres **public** schema (admin only).

Enforcement layers, from strongest to weakest:

1. Connection level  — the dedicated pool is opened with
   ``default_transaction_read_only=on`` and ``statement_timeout``, so even a
   bug in this module cannot write to the database.
2. Transaction level — every request runs ``SET TRANSACTION READ ONLY`` plus a
   local ``statement_timeout`` / ``lock_timeout`` / ``work_mem`` cap.
3. Statement level   — :func:`validate_sql` accepts exactly one SELECT/WITH
   statement, rejects DML/DDL keywords, non-public schemas and any function
   able to touch the server filesystem or block a worker (COPY ... TO PROGRAM,
   pg_read_file, dblink, pg_sleep, ...).
4. Resource level    — a dedicated 3-connection pool, global concurrency slots
   (extra requests get HTTP 429), a server-side cursor that only pulls the
   preview window, and hard row caps for preview and CSV export.

Routes
    GET  /database/query              → console page
    GET  /api/query_db/tables         → public tables/views (name, kind, rows)
    GET  /api/query_db/columns        → column list for one public table
    POST /api/query_db/run            → execute, return JSON preview
    POST /api/query_db/export         → execute, stream full CSV
"""

import csv
import io
import json
import logging
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time as dt_time
from decimal import Decimal

import psycopg2
import psycopg2.errors
import psycopg2.pool
from flask import Blueprint, Response, make_response, render_template, request, session

from ._utils import _no_cache, json_response, login_required

logger = logging.getLogger(__name__)

query_db_bp = Blueprint("query_db", __name__)

# ── Limits (overridable through the environment) ─────────────────────────────
QUERY_TIMEOUT_MS     = int(os.getenv("QUERY_DB_TIMEOUT_MS", "60000"))
PREVIEW_MAX_ROWS     = int(os.getenv("QUERY_DB_PREVIEW_ROWS", "1000"))
EXPORT_MAX_ROWS      = int(os.getenv("QUERY_DB_EXPORT_ROWS", "50000"))
MAX_CONCURRENT_QUERY = int(os.getenv("QUERY_DB_MAX_CONCURRENT", "2"))
MAX_SQL_LENGTH       = 100_000
FETCH_BATCH          = 500          # server-side cursor batch (memory footprint)
PREVIEW_CELL_BUDGET  = int(os.getenv("QUERY_DB_PREVIEW_CELLS", "60000"))   # rows × columns
EXPORT_BATCH_CELLS   = 100_000      # cursor batch sized by column count
TABLES_CACHE_TTL     = 120          # seconds — the catalog rarely changes
SCHEMA_CACHE_TTL     = 300

_PUBLIC = "public"

# Sample queries shown as clickable chips in the console. Kept here (not in the
# template) so tests can execute every one of them against the live catalog.
# All of them are index-friendly: each filters on a date/`kpi_date` column that
# already has a btree index, and every one ends with a LIMIT.
SAMPLE_QUERIES = [
    {
        "title": "Preview table",
        "sql": 'SELECT * FROM "sites_db" LIMIT 50;',
    },
    {
        "title": "Latest 2G sites",
        "sql": ('SELECT nsa, city, me_name AS bsc, siteid, bts_name, kpi_date\n'
                'FROM "2g_kpi_zte_daily"\n'
                'WHERE kpi_date = (SELECT MAX(kpi_date) FROM "2g_kpi_zte_daily")\n'
                'LIMIT 50;'),
    },
    {
        "title": "CSSR by BSC",
        "sql": ('SELECT nsa, me_name AS bsc,\n'
                '       ROUND((SUM(cssr_num) / NULLIF(SUM(cssr_denum), 0) * 100)::numeric, 2) AS cssr_pct\n'
                'FROM "2g_kpi_zte_daily"\n'
                'WHERE kpi_date = (SELECT MAX(kpi_date) FROM "2g_kpi_zte_daily")\n'
                'GROUP BY nsa, me_name\n'
                'ORDER BY cssr_pct ASC\n'
                'LIMIT 20;'),
    },
    {
        "title": "4G payload by city",
        "sql": ('SELECT city,\n'
                '       ROUND(SUM("4g_payload_mb")::numeric, 1) AS payload_mb\n'
                'FROM "4g_kpi_zte_daily"\n'
                'WHERE kpi_date = (SELECT MAX(kpi_date) FROM "4g_kpi_zte_daily")\n'
                'GROUP BY city\n'
                'ORDER BY payload_mb DESC\n'
                'LIMIT 20;'),
    },
    {
        "title": "4G DL PRB",
        "sql": ('SELECT siteid, city,\n'
                '       ROUND((SUM(dl_prb_util_num) / NULLIF(SUM(dl_prb_util_denum), 0))::numeric, 2) AS dl_prb_pct\n'
                'FROM "4g_kpi_zte_daily"\n'
                'WHERE kpi_date = (SELECT MAX(kpi_date) FROM "4g_kpi_zte_daily")\n'
                'GROUP BY siteid, city\n'
                'ORDER BY dl_prb_pct DESC\n'
                'LIMIT 20;'),
    },
    {
        "title": "5G by city",
        "sql": ('SELECT city, COUNT(*) AS cells,\n'
                '       ROUND(AVG(availability_xhj)::numeric, 2) AS availability_pct\n'
                'FROM "5g_kpi_zte"\n'
                'WHERE date = (SELECT MAX(date) FROM "5g_kpi_zte")\n'
                'GROUP BY city\n'
                'ORDER BY cells DESC\n'
                'LIMIT 20;'),
    },
    {
        "title": "2G packet loss",
        "sql": ('SELECT "Site ID", ROUND(AVG("Packet Loss")::numeric, 3) AS avg_pl_pct\n'
                'FROM "2G_pl_hy"\n'
                'WHERE "Date" = (SELECT MAX("Date") FROM "2G_pl_hy")\n'
                'GROUP BY "Site ID"\n'
                'ORDER BY avg_pl_pct DESC\n'
                'LIMIT 20;'),
    },
    {
        "title": "4G availability",
        "sql": ('SELECT "eNodeB Name" AS enodeb, "Cell Name" AS cell,\n'
                '       "Cell_Availability_4G_(%)" AS availability_pct\n'
                'FROM "measKpiDy4G"\n'
                'WHERE "Date" = (SELECT MAX("Date") FROM "measKpiDy4G")\n'
                'ORDER BY availability_pct ASC\n'
                'LIMIT 50;'),
    },
    {
        "title": "Sites per NOP",
        "sql": ('SELECT "NOP", COUNT(*) AS sites\n'
                'FROM "sites_db"\n'
                'GROUP BY "NOP"\n'
                'ORDER BY sites DESC\n'
                'LIMIT 20;'),
    },
]

# DML / DDL / session control — never valid in a read-only console.
_DENY_KEYWORDS = (
    "insert", "update", "delete", "merge", "upsert",
    "drop", "alter", "create", "truncate", "comment", "rename",
    "grant", "revoke", "copy", "vacuum", "analyze", "reindex", "cluster",
    "call", "do", "execute", "prepare", "deallocate", "discard",
    "set", "reset", "lock", "listen", "notify", "unlisten",
    "refresh", "declare", "fetch", "move", "close", "cursor",
    "begin", "commit", "rollback", "savepoint", "release",
    "into", "import", "attach", "detach", "security",
)

# Functions that read/write the server filesystem, reach other servers, or
# block a backend worker. Blocked by name before the statement ever reaches
# PostgreSQL (COPY ... TO PROGRAM also slips past read-only transactions).
_DENY_FUNCTIONS = (
    "pg_read_file", "pg_read_binary_file", "pg_write_file", "pg_ls_dir",
    "pg_stat_file", "pg_logdir_ls", "lo_import", "lo_export", "lo_unlink",
    "dblink", "dblink_exec", "dblink_connect", "dblink_open",
    "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf",
    "pg_rotate_logfile", "pg_switch_wal", "pg_create_restore_point",
    "pg_promote", "pg_start_backup", "pg_stop_backup",
    "pg_backup_start", "pg_backup_stop",
    "set_config", "current_setting",
    "pg_advisory_lock", "pg_advisory_xact_lock", "pg_advisory_lock_shared",
    "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "pg_notify", "nextval", "setval",
    "pg_execute_server_program", "pg_read_server_files",
)

# Always forbidden regardless of what the catalog reports.
_ALWAYS_BLOCKED_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast", "pg_temp"}


class SqlRejected(Exception):
    """Raised when a statement violates the read-only rules."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


# ── Dedicated, read-only connection pool ─────────────────────────────────────
# The main app pool (maxconn=20) serves every dashboard. The console gets its
# own tiny pool so a runaway query can never starve the dashboards.
_pool = None
_pool_lock = threading.Lock()

_slots = threading.BoundedSemaphore(max(1, MAX_CONCURRENT_QUERY))


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=max(2, MAX_CONCURRENT_QUERY + 1),
                    host=os.getenv("POSTGRES_DB_HOST"),
                    database=os.getenv("POSTGRES_DB_NAME"),
                    user=os.getenv("POSTGRES_DB_USER"),
                    password=os.getenv("POSTGRES_DB_PASSWORD"),
                    port=os.getenv("POSTGRES_DB_PORT", "5432"),
                    connect_timeout=12,
                    options=(
                        "-c default_transaction_read_only=on "
                        f"-c statement_timeout={QUERY_TIMEOUT_MS} "
                        f"-c idle_in_transaction_session_timeout={QUERY_TIMEOUT_MS + 15000}"
                    ),
                )
    return _pool


@contextmanager
def _readonly_connection():
    """Yield a pooled connection pinned to a read-only transaction."""
    conn = _get_pool().getconn()
    try:
        setup = conn.cursor()
        try:
            setup.execute("SET TRANSACTION READ ONLY")
            setup.execute("SET LOCAL statement_timeout = %s", (f"{QUERY_TIMEOUT_MS}ms",))
            setup.execute("SET LOCAL idle_in_transaction_session_timeout = %s",
                          (f"{QUERY_TIMEOUT_MS + 15000}ms",))
            setup.execute("SET LOCAL lock_timeout = '5000ms'")
            setup.execute("SET LOCAL work_mem = '32MB'")
            setup.execute("SET LOCAL search_path = public")
        finally:
            setup.close()
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            _get_pool().putconn(conn)
        except Exception:
            logger.exception("Failed to return query console connection to pool")


# ── SQL validation ───────────────────────────────────────────────────────────
def _mask_sql(sql):
    """Return ``sql`` with comments and quoted literals blanked out.

    Masked text keeps SQL keywords only, so a literal such as
    ``'-- drop table x'`` can never trip the keyword checks and a ``;`` inside
    a string is not mistaken for a second statement.
    """
    out = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":                       # line comment
            while i < n and sql[i] != "\n":
                out.append(" ")
                i += 1
        elif ch == "/" and nxt == "*":                     # block comment
            out.append("  ")
            i += 2
            depth = 1
            while i < n and depth:
                if sql[i] == "/" and i + 1 < n and sql[i + 1] == "*":
                    depth += 1
                    out.append("  ")
                    i += 2
                elif sql[i] == "*" and i + 1 < n and sql[i + 1] == "/":
                    depth -= 1
                    out.append("  ")
                    i += 2
                else:
                    out.append(" ")
                    i += 1
        elif ch == "'":                                    # standard literal
            out.append(" ")
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        out.append("  ")
                        i += 2
                        continue
                    out.append(" ")
                    i += 1
                    break
                out.append(" ")
                i += 1
        elif ch == "$":                                    # dollar-quoted block
            tag_match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[i:])
            if tag_match:
                tag = tag_match.group(0)
                out.append(" " * len(tag))
                i += len(tag)
                end = sql.find(tag, i)
                end = n if end < 0 else end
                out.append(" " * (end - i))
                i = min(n, end + len(tag))
            else:
                out.append(ch)
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _strip_trailing(sql):
    """Drop trailing whitespace and semicolons (a single statement is allowed)."""
    trimmed = sql.rstrip()
    while trimmed.endswith(";"):
        trimmed = trimmed[:-1].rstrip()
    return trimmed


def validate_sql(sql, blocked_schemas=frozenset()):
    """Return the executable statement or raise :class:`SqlRejected`."""
    if not isinstance(sql, str) or not sql.strip():
        raise SqlRejected("Query is empty.")
    if len(sql) > MAX_SQL_LENGTH:
        raise SqlRejected(f"Query is too long ({len(sql)} characters, limit {MAX_SQL_LENGTH}).")

    masked = _strip_trailing(_mask_sql(sql))

    if not masked.strip():
        raise SqlRejected("Query contains no SQL statement (only comments?).")

    if ";" in masked:
        raise SqlRejected("Only one statement per run is allowed — remove the extra ';'.")

    if not re.match(r"(select|with|table|values)\b", masked, re.I):
        raise SqlRejected(
            "This console is read-only: a query must start with SELECT or WITH."
        )

    keywords = sorted({kw for kw in _DENY_KEYWORDS
                       if re.search(rf"\b{kw}\b", masked, re.I)})
    if keywords:
        raise SqlRejected(
            "Read-only mode rejects the keyword(s): " + ", ".join(k.upper() for k in keywords) + "."
        )

    functions = sorted({fn for fn in _DENY_FUNCTIONS
                        if re.search(rf"\b{fn}\b", masked, re.I)})
    if functions:
        raise SqlRejected(
            "Function not allowed in this console: " + ", ".join(functions) + "."
        )

    for schema in sorted(set(blocked_schemas) | _ALWAYS_BLOCKED_SCHEMAS):
        if re.search(rf"\b{re.escape(schema)}\s*\.", masked, re.I):
            raise SqlRejected(
                f"Only the '{_PUBLIC}' schema can be queried — '{schema}' is not allowed."
            )

    # The statement that actually runs: original text minus trailing ';'
    exec_sql = _strip_trailing(sql)
    if not exec_sql:
        raise SqlRejected("Query is empty.")
    return exec_sql


# ── Catalog helpers (cached, cheap) ──────────────────────────────────────────
_tables_cache = {"at": 0.0, "data": None}
_schemas_cache = {"at": 0.0, "names": frozenset()}


def _blocked_schemas(cur):
    """Schemas that must never be referenced by a console query."""
    now = time.time()
    if not _schemas_cache["names"] or now - _schemas_cache["at"] > SCHEMA_CACHE_TTL:
        cur.execute("""
            SELECT nspname
            FROM pg_namespace
            WHERE nspname <> %s
              AND nspname <> 'information_schema'
              AND nspname NOT LIKE 'pg\\_%%'
        """, (_PUBLIC,))
        names = {row[0] for row in cur.fetchall()}
        _schemas_cache["names"] = frozenset(names)
        _schemas_cache["at"] = now
    return _schemas_cache["names"]


def _blocked_schemas_snapshot():
    """Same as :func:`_blocked_schemas` but opens its own short-lived cursor."""
    now = time.time()
    if _schemas_cache["names"] and now - _schemas_cache["at"] <= SCHEMA_CACHE_TTL:
        return _schemas_cache["names"]
    try:
        with _readonly_connection() as conn:
            cur = conn.cursor()
            try:
                return _blocked_schemas(cur)
            finally:
                cur.close()
    except Exception:
        logger.exception("Could not read schema list; using defaults")
        return _ALWAYS_BLOCKED_SCHEMAS


def _load_tables():
    """Base tables (and partitioned tables) in ``public``.

    Views and materialized views are intentionally excluded: the console's
    table browser lists physical tables only. They stay queryable by name for
    anyone who types the SQL themselves.
    """
    now = time.time()
    if _tables_cache["data"] is not None and now - _tables_cache["at"] <= TABLES_CACHE_TTL:
        return _tables_cache["data"]

    with _readonly_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT c.relname,
                       c.relkind,
                       GREATEST(c.reltuples, 0)::bigint AS est_rows,
                       obj_description(c.oid, 'pg_class') AS comment,
                       (SELECT count(*)
                          FROM pg_attribute a
                         WHERE a.attrelid = c.oid
                           AND a.attnum > 0
                           AND NOT a.attisdropped) AS col_count
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s
                  AND c.relkind IN ('r', 'p')
                ORDER BY c.relname
            """, (_PUBLIC,))
            rows = cur.fetchall()
        finally:
            cur.close()

    kind_label = {
        "r": "table",
        "p": "partitioned table",
    }
    data = [{
        "name": r[0],
        "kind": kind_label.get(r[1], r[1]),
        "est_rows": int(r[2] or 0),
        "comment": r[3],
        "columns": int(r[4] or 0),
    } for r in rows]

    _tables_cache["data"] = data
    _tables_cache["at"] = now
    return data


def _find_table(name):
    """Look up one public relation by exact name (also returns its oid)."""
    with _readonly_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT c.oid, c.relkind
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s
                  AND c.relname = %s
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
            """, (_PUBLIC, name))
            return cur.fetchone()
        finally:
            cur.close()


def _load_columns(name):
    """Column metadata + primary keys for one public relation."""
    found = _find_table(name)
    if not found:
        return None
    oid, relkind = found

    with _readonly_connection() as conn:
        cur = conn.cursor()
        try:
            # pg_attribute covers tables, views *and* materialized views —
            # information_schema.columns silently skips materialized views.
            cur.execute("""
                SELECT a.attname,
                       format_type(a.atttypid, a.atttypmod) AS column_type,
                       NOT a.attnotnull AS is_nullable,
                       pg_get_expr(d.adbin, d.adrelid) AS column_default,
                       a.attnum
                FROM pg_attribute a
                LEFT JOIN pg_attrdef d
                  ON d.adrelid = a.attrelid
                 AND d.adnum = a.attnum
                WHERE a.attrelid = %s
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                ORDER BY a.attnum
            """, (oid,))
            columns = cur.fetchall()

            cur.execute("""
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a
                  ON a.attrelid = i.indrelid
                 AND a.attnum = ANY (i.indkey)
                WHERE i.indrelid = %s
                  AND i.indisprimary
            """, (oid,))
            pk = {row[0] for row in cur.fetchall()}
        finally:
            cur.close()

    return {
        "name": name,
        "kind": relkind,
        "primary_key": sorted(pk),
        "columns": [{
            "name": c[0],
            "type": c[1],
            "nullable": bool(c[2]),
            "default": c[3],
            "position": c[4],
            "is_pk": c[0] in pk,
        } for c in columns],
    }


# ── Value serialisation ──────────────────────────────────────────────────────
def _cell(value):
    """Convert a psycopg2 value into something JSON- and CSV-friendly."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dt_time):
        return value.isoformat()
    if isinstance(value, (bytes, memoryview)):
        raw = bytes(value)
        return f"<binary {len(raw)} bytes>"
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


# ── Concurrency & Error Helpers ──────────────────────────────────────────────
def _acquire_slot():
    return _slots.acquire(blocking=False)


def _release_slot():
    try:
        _slots.release()
    except ValueError:
        pass


def _busy():
    return json_response({
        "status": "error",
        "message": "The query console is busy running another query. Please try again in a moment.",
    }, 429)


def _sql_error_message(exc):
    """Turn a psycopg2 error into a short, useful message for the operator."""
    if isinstance(exc, psycopg2.errors.QueryCanceled):
        return (f"Query cancelled after {QUERY_TIMEOUT_MS / 1000:g}s "
                "(statement timeout). Add a WHERE filter or a LIMIT.")
    if isinstance(exc, psycopg2.errors.LockNotAvailable):
        return "Query could not obtain a lock within 5s. Try again later."
    if isinstance(exc, psycopg2.errors.ReadOnlySqlTransaction):
        return "Blocked: this console runs inside a read-only transaction."
    if isinstance(exc, psycopg2.errors.InsufficientPrivilege):
        return "Permission denied by the database for this object."
    if isinstance(exc, psycopg2.Error):
        return (getattr(exc, "pgerror", None) or str(exc)).strip()
    return "Unexpected error while running the query."


# ── Pages & APIs ─────────────────────────────────────────────────────────────
@query_db_bp.route("/database/query")
@login_required
def query_db_page():
    response = make_response(render_template(
        "query_db.html",
        username=session.get("username"),
        role=session.get("role", "viewer"),
        preview_rows=PREVIEW_MAX_ROWS,
        export_rows=EXPORT_MAX_ROWS,
        timeout_s=int(QUERY_TIMEOUT_MS / 1000),
        sample_queries=SAMPLE_QUERIES,
    ))
    return _no_cache(response)


@query_db_bp.route("/api/query_db/tables")
@login_required
def api_query_db_tables():
    try:
        return json_response({"status": "success", "schema": _PUBLIC, "tables": _load_tables()})
    except Exception:
        logger.exception("Could not list public tables")
        return json_response(
            {"status": "error", "message": "Could not read the table list from the database."}, 500
        )


@query_db_bp.route("/api/query_db/columns")
@login_required
def api_query_db_columns():
    name = (request.args.get("table") or "").strip()
    if not name or len(name) > 128:
        return json_response({"status": "error", "message": "Missing table name."}, 400)
    try:
        info = _load_columns(name)
    except Exception:
        logger.exception("Could not read columns for %s", name)
        return json_response(
            {"status": "error", "message": "Could not read the column list."}, 500
        )
    if not info:
        return json_response(
            {"status": "error", "message": f"Table '{name}' was not found in schema '{_PUBLIC}'."}, 404
        )
    return json_response({
        "status": "success",
        "table": info["name"],
        "columns": info["columns"],
        "primary_key": info["primary_key"],
    })


@query_db_bp.route("/api/query_db/run", methods=["POST"])
@login_required
def api_query_db_run():
    payload = request.get_json(silent=True) or {}
    sql = payload.get("sql")

    try:
        exec_sql = validate_sql(sql, _blocked_schemas_snapshot())
    except SqlRejected as exc:
        return json_response({"status": "error", "message": exc.message}, 400)

    if not _acquire_slot():
        return _busy()

    started = time.perf_counter()
    try:
        with _readonly_connection() as conn:
            cur = conn.cursor(name=f"qdb_{uuid.uuid4().hex[:12]}")
            try:
                cur.itersize = FETCH_BATCH
                cur.execute(exec_sql)
                # One row first: the column count decides how many rows we can
                # afford to send without freezing the browser on wide results.
                first = cur.fetchmany(1)
                columns = [d[0] for d in (cur.description or [])]
                row_cap = PREVIEW_MAX_ROWS
                if columns:
                    row_cap = max(1, min(PREVIEW_MAX_ROWS,
                                         PREVIEW_CELL_BUDGET // max(1, len(columns))))
                raw = first + cur.fetchmany(row_cap)
            finally:
                cur.close()
    except psycopg2.Error as exc:
        logger.warning("Read-only query failed: %s", str(exc).splitlines()[0][:200])
        return json_response({"status": "error", "message": _sql_error_message(exc)}, 400)
    except Exception:
        logger.exception("Unexpected failure running read-only query")
        return json_response(
            {"status": "error",
             "message": "Could not connect to the database. Please try again later."}, 500
        )
    finally:
        _release_slot()

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    truncated = len(raw) > row_cap
    rows = [[_cell(v) for v in row] for row in raw[:row_cap]]

    return json_response({
        "status": "success",
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "preview_limit": row_cap,
        "preview_max": PREVIEW_MAX_ROWS,
        "cell_limited": row_cap < PREVIEW_MAX_ROWS,
        "elapsed_ms": elapsed_ms,
        "executed_sql": exec_sql,
    })


@query_db_bp.route("/api/query_db/export", methods=["POST"])
@login_required
def api_query_db_export():
    payload = request.get_json(silent=True) or {}
    sql = payload.get("sql")

    try:
        exec_sql = validate_sql(sql, _blocked_schemas_snapshot())
    except SqlRejected as exc:
        return json_response({"status": "error", "message": exc.message}, 400)

    if not _acquire_slot():
        return _busy()

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        emitted = 0
        try:
            with _readonly_connection() as conn:
                cur = conn.cursor(name=f"qdb_{uuid.uuid4().hex[:12]}")
                try:
                    cur.itersize = FETCH_BATCH * 4
                    cur.execute(exec_sql)
                    # A server-side cursor only reports its column list after the
                    # first fetch, so pull one batch before writing the header.
                    batch = cur.fetchmany(min(FETCH_BATCH * 4, EXPORT_MAX_ROWS))
                    columns = [d[0] for d in (cur.description or [])]
                    # Wide results get smaller batches so one batch never holds
                    # a huge number of Python values in memory.
                    step = max(200, min(FETCH_BATCH * 4,
                                        EXPORT_BATCH_CELLS // max(1, len(columns))))
                    writer.writerow(columns)
                    buffer.seek(0)
                    yield buffer.read()
                    buffer.seek(0)
                    buffer.truncate(0)

                    while batch and emitted < EXPORT_MAX_ROWS:
                        for row in batch:
                            writer.writerow([_cell(v) for v in row])
                        emitted += len(batch)
                        buffer.seek(0)
                        yield buffer.read()
                        buffer.seek(0)
                        buffer.truncate(0)
                        if emitted >= EXPORT_MAX_ROWS:
                            break
                        batch = cur.fetchmany(min(step, EXPORT_MAX_ROWS - emitted))
                finally:
                    cur.close()
        except psycopg2.Error as exc:
            logger.warning("CSV export aborted: %s", str(exc).splitlines()[0][:200])
        except GeneratorExit:
            logger.info("CSV export cancelled by client after %s rows", emitted)
            raise
        except Exception:
            logger.exception("Unexpected failure during CSV export")
        finally:
            _release_slot()

    filename = f"query_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = Response(generate(), mimetype="text/csv")
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Row-Limit"] = str(EXPORT_MAX_ROWS)
    # Hint to stop proxies from buffering the whole download.
    response.headers["X-Accel-Buffering"] = "no"
    return response
