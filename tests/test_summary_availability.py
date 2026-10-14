"""The Summary endpoint must degrade to an explicit empty state, never crash.

Every aggregate in /api/sow/summary-availability now comes from a UNION ALL of
five branches. With an empty database each branch returns no rows, so the
assembly has to emit nulls (rendered as an em dash) rather than blowing up on a
missing key or dividing by zero.
"""
import contextlib

import pytest

from app import create_app


class _FakeCur:
    def execute(self, *args, **kwargs):
        return None

    def fetchall(self):
        return []

    def close(self):
        return None


class _FakeConn:
    def cursor(self):
        return _FakeCur()


@contextlib.contextmanager
def _empty_db_query(*args, **kwargs):
    """Stand-in for db_query() that reports an entirely empty database."""
    yield _FakeConn(), _FakeCur()


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def auth_client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "test_engineer"
        sess["role"] = "engineer"
    return c


def test_summary_availability_empty_database(auth_client, monkeypatch):
    import app.routes.sow_routes as sow_routes

    monkeypatch.setattr(sow_routes, "db_query", _empty_db_query)

    res = auth_client.get("/api/sow/summary-availability")
    assert res.status_code == 200, res.data[:400]

    data = res.get_json()
    assert data["status"] == "success"

    # No week anywhere, so the banner must not invent one.
    assert data["latest_week"] is None
    assert data["prev_week"] is None

    assert len(data["metrics"]) == 6
    assert data["ach_count"] == 0
    assert data["ny_ach_count"] == 0
    assert data["no_data_count"] == 6

    for m in data["metrics"]:
        assert m["latest_val"] is None, m["id"]
        assert m["prev_val"] is None, m["id"]
        assert m["target"] is None, m["id"]
        assert m["wow"] is None, m["id"]
        assert m["gap"] is None, m["id"]
        assert m["ach"] is None, m["id"]
        assert m["status"] == "NO DATA", m["id"]
        assert m["movement"] is None, m["id"]
        assert m["latest_week"] is None, m["id"]
        # The insight must say so plainly instead of quoting a figure.
        assert "No " in m["insight"] and "data available" in m["insight"], m["id"]


def test_summary_availability_missing_targets(auth_client, monkeypatch):
    """Data present but sow.sow_target empty -> values shown, target unknown."""
    import app.routes.sow_routes as sow_routes

    rows_by_call = [
        [],  # targets: empty table
        # merged week+aggregate: RHI only, one week, no previous week
        [("RHI", 202640, 100, 90, 10)],
        [],  # breakdown drivers
        [],  # onx trailing
    ]

    class _Cur:
        def __init__(self):
            self.i = -1

        def execute(self, *a, **k):
            self.i += 1

        def fetchall(self):
            return rows_by_call[self.i] if 0 <= self.i < len(rows_by_call) else []

        def close(self):
            return None

    cur = _Cur()

    @contextlib.contextmanager
    def _fake(*a, **k):
        yield object(), cur

    monkeypatch.setattr(sow_routes, "db_query", _fake)

    res = auth_client.get("/api/sow/summary-availability")
    assert res.status_code == 200, res.data[:400]
    data = res.get_json()

    rhi = next(m for m in data["metrics"] if m["id"] == "RHI")
    assert rhi["latest_val"] == 90.0
    assert rhi["prev_val"] is None
    assert rhi["wow"] is None
    assert rhi["target"] is None            # no target row for this week
    assert rhi["ach"] is None               # cannot judge without a target
    assert rhi["status"] == "NO DATA"
    assert rhi["movement"] is None
    assert rhi["latest_week"] == 202640

    cei = next(m for m in data["metrics"] if m["id"] == "CEI")
    assert cei["latest_val"] is None
    assert cei["status"] == "NO DATA"
