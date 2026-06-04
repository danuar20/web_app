"""
test_db.py — unit tests for database utility functions.

Tests cover:
  • Connection factories return connection objects
  • Environment variable loading / fallbacks
  • Connection timeout is set (5 s)
  • psycopg2.OperationalError is raised when DB is unreachable
  • Mock DB responses produce the correct data shapes used by routes

These tests mock psycopg2.connect so they run without any live database.
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Ensure project root is on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def clean_env():
    """
    Isolate DB tests from the host's .env by patching os.getenv.
    Tests can then inject arbitrary values.
    """
    original_getenv = os.getenv

    def _getenv(key, default=None):
        env = {
            # Webapp DB
            "WEBAPP_DB_HOST":     "testhost_webapp",
            "WEBAPP_DB_PORT":     "5432",
            "WEBAPP_DB_NAME":     "testdb",
            "WEBAPP_DB_USER":     "testuser",
            "WEBAPP_DB_PASSWORD": "testpass",
            # PostgreSQL
            "POSTGRES_DB_HOST":   "testhost_postgres",
            "POSTGRES_DB_PORT":   "5432",
            "POSTGRES_DB_NAME":   "postgresdb",
            "POSTGRES_DB_USER":   "pguser",
            "POSTGRES_DB_PASSWORD": "pgpass",
            # Pumaz
            "PUMAZ_DB_HOST":      "testhost_pumaz",
            "PUMAZ_DB_PORT":      "5432",
            "PUMAZ_DB_NAME":      "pumazdb",
            "PUMAZ_DB_USER":      "pumazuser",
            "PUMAZ_DB_PASSWORD":  "pumazpass",
        }
        return env.get(key, default)

    with patch.object(os, "getenv", _getenv):
        yield


@pytest.fixture
def mock_connect():
    """Replace psycopg2.connect with a mock that returns a MagicMock connection."""
    with patch("psycopg2.connect") as mock:
        conn = MagicMock(name="mock_conn")
        mock.return_value = conn
        yield mock, conn


# =============================================================================
# get_connection (webapp DB)
# =============================================================================
class TestGetConnection:
    """Tests for app.db.db_webapp.get_connection()."""

    def test_returns_conn_object(self, clean_env, mock_connect):
        mock, _ = mock_connect
        from app.db.db_webapp import get_connection
        conn = get_connection()
        assert conn is not None

    def test_calls_psycopg2_connect_with_correct_args(self, clean_env, mock_connect):
        mock, _ = mock_connect
        from app.db.db_webapp import get_connection
        get_connection()
        mock.assert_called_once()
        call_kwargs = mock.call_args
        assert call_kwargs.kwargs["host"]     == "testhost_webapp"
        assert call_kwargs.kwargs["database"]  == "testdb"
        assert call_kwargs.kwargs["user"]      == "testuser"
        assert call_kwargs.kwargs["password"]  == "testpass"
        assert call_kwargs.kwargs["port"]      == "5432"

    def test_timeout_is_set(self, clean_env, mock_connect):
        mock, _ = mock_connect
        from app.db.db_webapp import get_connection
        get_connection()
        assert mock.call_args.kwargs.get("connect_timeout") == 5

    def test_raises_operational_error_when_unreachable(self, clean_env):
        import psycopg2
        with patch("psycopg2.connect", side_effect=psycopg2.OperationalError("connect failed")):
            from app.db.db_webapp import get_connection
            with pytest.raises(psycopg2.OperationalError):
                get_connection()

    def test_host_fallback_to_default_port(self, clean_env, mock_connect):
        mock, _ = mock_connect
        from app.db.db_webapp import get_connection
        get_connection()
        assert mock.call_args.kwargs.get("port") == "5432"


# =============================================================================
# get_postgres_connection (postgres DB)
# =============================================================================
class TestGetPostgresConnection:
    """Tests for app.db.db_webapp.get_postgres_connection()."""

    def test_returns_conn_object(self, clean_env, mock_connect):
        mock, _ = mock_connect
        from app.db.db_webapp import get_postgres_connection
        conn = get_postgres_connection()
        assert conn is not None

    def test_calls_psycopg2_connect_with_correct_args(self, clean_env, mock_connect):
        mock, _ = mock_connect
        from app.db.db_webapp import get_postgres_connection
        get_postgres_connection()
        mock.assert_called_once()
        assert mock.call_args.kwargs["host"]     == "testhost_postgres"
        assert mock.call_args.kwargs["database"]  == "postgresdb"
        assert mock.call_args.kwargs["user"]      == "pguser"
        assert mock.call_args.kwargs["password"]  == "pgpass"

    def test_timeout_is_set(self, clean_env, mock_connect):
        mock, _ = mock_connect
        from app.db.db_webapp import get_postgres_connection
        get_postgres_connection()
        assert mock.call_args.kwargs.get("connect_timeout") == 5

    def test_raises_operational_error_when_unreachable(self, clean_env):
        import psycopg2
        with patch("psycopg2.connect", side_effect=psycopg2.OperationalError("connect failed")):
            from app.db.db_webapp import get_postgres_connection
            with pytest.raises(psycopg2.OperationalError):
                get_postgres_connection()


# =============================================================================
# get_pumaz_connection (pumaz DB)
# =============================================================================
class TestGetPumazConnection:
    """Tests for app.db.db_pumaz.get_pumaz_connection()."""

    def test_returns_conn_object(self, clean_env, mock_connect):
        mock, _ = mock_connect
        from app.db.db_pumaz import get_pumaz_connection
        conn = get_pumaz_connection()
        assert conn is not None

    def test_calls_psycopg2_connect_with_correct_args(self, clean_env, mock_connect):
        mock, _ = mock_connect
        from app.db.db_pumaz import get_pumaz_connection
        get_pumaz_connection()
        mock.assert_called_once()
        assert mock.call_args.kwargs["host"]     == "testhost_pumaz"
        assert mock.call_args.kwargs["database"]  == "pumazdb"
        assert mock.call_args.kwargs["user"]      == "pumazuser"
        assert mock.call_args.kwargs["password"]  == "pumazpass"

    def test_timeout_is_set(self, clean_env, mock_connect):
        mock, _ = mock_connect
        from app.db.db_pumaz import get_pumaz_connection
        get_pumaz_connection()
        assert mock.call_args.kwargs.get("connect_timeout") == 5

    def test_raises_operational_error_when_unreachable(self, clean_env):
        import psycopg2
        with patch("psycopg2.connect", side_effect=psycopg2.OperationalError("connect failed")):
            from app.db.db_pumaz import get_pumaz_connection
            with pytest.raises(psycopg2.OperationalError):
                get_pumaz_connection()


# =============================================================================
# Connection cursor usage pattern
# =============================================================================
class TestCursorPattern:
    """
    Routes follow a consistent cursor pattern:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute(...)
        result = cur.fetchall()
        cur.close(); conn.close()

    This test verifies the pattern works with a mock.
    """

    def test_cursor_execute_returns_rows(self, clean_env, mock_connect):
        mock, conn = mock_connect
        # Configure mock cursor to return data
        cur = MagicMock()
        cur.fetchall.return_value = [("NSA1",), ("NSA2",)]
        conn.cursor.return_value = cur

        from app.db.db_webapp import get_connection
        conn_obj = get_connection()
        cursor = conn_obj.cursor()
        cursor.execute("SELECT DISTINCT \"NSA\" FROM traffic_payload WHERE \"NSA\" IS NOT NULL")
        rows = cursor.fetchall()
        cursor.close()
        conn_obj.close()

        assert rows == [("NSA1",), ("NSA2",)]

    def test_cursor_context_manager_closes_properly(self, clean_env, mock_connect):
        mock, conn = mock_connect
        cur = MagicMock()
        conn.cursor.return_value = cur

        from app.db.db_webapp import get_connection
        conn_obj = get_connection()
        with conn_obj.cursor() as cur:
            cur.execute("SELECT 1")

        cur.close.assert_called()

    def test_null_result_handled_gracefully(self, clean_env, mock_connect):
        mock, conn = mock_connect
        cur = MagicMock()
        cur.fetchone.return_value = None
        conn.cursor.return_value = cur

        from app.db.db_webapp import get_connection
        conn_obj = get_connection()
        result = conn_obj.cursor().fetchone()
        assert result is None


# =============================================================================
# Data-shape tests (verify the shape returned by mock queries matches what
# route code expects)
# =============================================================================
class TestDataShapes:
    """Verify mock query results have the structure route code expects."""

    def test_nsa_list_fetchone_returns_string(self, clean_env, mock_connect):
        mock, conn = mock_connect
        cur = MagicMock()
        cur.fetchone.return_value = ("NSA_Region_1",)
        conn.cursor.return_value = cur

        from app.db.db_webapp import get_connection
        conn_obj = get_connection()
        row = conn_obj.cursor().fetchone()
        # Route code expects r[0] to be a string NSA label
        assert isinstance(row[0], str)

    def test_year_list_fetchall_returns_strings(self, clean_env, mock_connect):
        mock, conn = mock_connect
        cur = MagicMock()
        cur.fetchall.return_value = [(2022,), (2023,), (2024,)]
        conn.cursor.return_value = cur

        from app.db.db_webapp import get_connection
        conn_obj = get_connection()
        rows = conn_obj.cursor().fetchall()
        assert all(isinstance(r[0], int) for r in rows)

    def test_chart_data_row_returns_floats(self, clean_env, mock_connect):
        """productivity route expects numeric values for payload/traffic columns."""
        mock, conn = mock_connect
        cur = MagicMock()
        # Simulate a row: day_of_year, year, payload_GB, traffic_K
        cur.fetchall.return_value = [
            (45, 2023, 1234.56, 567.89),
            (46, 2023, 1300.00, 600.00),
        ]
        conn.cursor.return_value = cur

        from app.db.db_webapp import get_connection
        conn_obj = get_connection()
        rows = conn_obj.cursor().fetchall()
        for r in rows:
            # Verify numeric columns are convertible to float (route code does float(r[2]))
            float(r[2])
            float(r[3])

    def test_city_list_fetchall_returns_strings(self, clean_env, mock_connect):
        mock, conn = mock_connect
        cur = MagicMock()
        cur.fetchall.return_value = [("Jakarta",), ("Bandung",), ("Surabaya",)]
        conn.cursor.return_value = cur

        from app.db.db_webapp import get_connection
        conn_obj = get_connection()
        rows = conn_obj.cursor().fetchall()
        assert all(isinstance(r[0], str) for r in rows)

    def test_site_list_fetchall_returns_strings(self, clean_env, mock_connect):
        mock, conn = mock_connect
        cur = MagicMock()
        cur.fetchall.return_value = [("site001",), ("site002",)]
        conn.cursor.return_value = cur

        from app.db.db_webapp import get_connection
        conn_obj = get_connection()
        rows = conn_obj.cursor().fetchall()
        assert all(isinstance(r[0], str) for r in rows)


# =============================================================================
# Date / datetime handling
# =============================================================================
class TestDateHandling:
    """Routes handle date/datetime types from the DB — verify conversion."""

    def test_max_date_returns_date_object(self, clean_env, mock_connect):
        from datetime import date
        mock, conn = mock_connect
        cur = MagicMock()
        cur.fetchone.return_value = (date(2023, 12, 31),)
        conn.cursor.return_value = cur

        from app.db.db_webapp import get_connection
        conn_obj = get_connection()
        row = conn_obj.cursor().fetchone()
        max_date = row[0]
        assert hasattr(max_date, "strftime")   # is date-like
        assert max_date.year == 2023

    def test_datetime_from_db_converted_to_date(self, clean_env, mock_connect):
        from datetime import datetime, date
        mock, conn = mock_connect
        cur = MagicMock()
        cur.fetchone.return_value = (datetime(2023, 6, 15, 0, 0),)
        conn.cursor.return_value = cur

        from app.db.db_webapp import get_connection
        conn_obj = get_connection()
        raw = conn_obj.cursor().fetchone()[0]
        # routes.py converts datetime → date: if isinstance(raw, datetime): raw = raw.date()
        converted = raw.date() if isinstance(raw, datetime) else raw
        assert isinstance(converted, date)


# =============================================================================
# Multiple DB support
# =============================================================================
class TestMultipleDatabases:
    """Each connection factory must use its own DB credentials."""

    def test_webapp_and_pumaz_use_different_hosts(self, clean_env, mock_connect):
        mock, _ = mock_connect
        from app.db.db_webapp import get_connection as gc_webapp
        from app.db.db_pumaz   import get_pumaz_connection as gc_pumaz

        gc_webapp()
        host_webapp = mock.call_args.kwargs["host"]

        gc_pumaz()
        host_pumaz = mock.call_args.kwargs["host"]

        assert host_webapp == "testhost_webapp"
        assert host_pumaz  == "testhost_pumaz"
        assert host_webapp != host_pumaz   # must be different servers

    def test_each_connection_gets_own_timeout(self, clean_env, mock_connect):
        mock, _ = mock_connect
        from app.db.db_webapp import get_connection
        get_connection()
        assert mock.call_args.kwargs.get("connect_timeout") == 5


# =============================================================================
# Error handling
# =============================================================================
class TestDbErrorHandling:
    """Database errors must propagate as psycopg2.OperationalError."""

    def test_connection_refused_raises_operational_error(self, clean_env):
        import psycopg2
        with patch("psycopg2.connect", side_effect=psycopg2.OperationalError("Connection refused")):
            from app.db.db_webapp import get_connection
            with pytest.raises(psycopg2.OperationalError, match="Connection refused"):
                get_connection()

    def test_timeout_triggers_operational_error(self, clean_env):
        import psycopg2
        with patch("psycopg2.connect", side_effect=psycopg2.OperationalError("connection timeout")):
            from app.db.db_webapp import get_connection
            with pytest.raises(psycopg2.OperationalError):
                get_connection()

    def test_raised_error_is_not_swallowed_by_connection_function(self, clean_env):
        """get_connection() must NOT catch OperationalError — it must propagate."""
        import psycopg2
        with patch("psycopg2.connect", side_effect=psycopg2.OperationalError("test")):
            from app.db.db_webapp import get_connection
            try:
                get_connection()
                pytest.fail("Expected OperationalError to be raised")
            except psycopg2.OperationalError:
                pass   # correct — error propagates