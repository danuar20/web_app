import pytest
from app import create_app


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
        sess["role"] = "admin"
    return c


def test_dashboard_5g_initial_view(auth_client):
    """Dashboard 5G initial GET returns 200."""
    res = auth_client.get("/dashboard_5g")
    assert res.status_code == 200
    assert "Dashboard 5G" in res.data.decode("utf-8")


def test_dashboard_5g_compare_missing_after_data(auth_client):
    """Dashboard 5G comparison must not crash (500) when After period has no data."""
    params = {
        "submitted": "1",
        "trend_from_date": "2026-10-01",
        "trend_to_date": "2026-10-05",
        "before_from_date": "2026-10-01",
        "before_to_date": "2026-10-02",
        "after_from_date": "2026-10-25",  # Future date without data
        "after_to_date": "2026-10-26",
        "filter_type": "siteid",
        "site": ["JAP013"],
    }
    res = auth_client.get("/dashboard_5g", query_string=params)
    assert res.status_code == 200


def test_dashboard_5g_compare_missing_before_data(auth_client):
    """Dashboard 5G comparison must not crash (500) when Before period has no data."""
    params = {
        "submitted": "1",
        "trend_from_date": "2026-10-01",
        "trend_to_date": "2026-10-05",
        "before_from_date": "2026-10-25",  # Future date without data
        "before_to_date": "2026-10-26",
        "after_from_date": "2026-10-01",
        "after_to_date": "2026-10-02",
        "filter_type": "siteid",
        "site": ["JAP013"],
    }
    res = auth_client.get("/dashboard_5g", query_string=params)
    assert res.status_code == 200


def test_dashboard_5g_inverted_trend_dates(auth_client):
    """Dashboard 5G must handle inverted trend dates without raising IndexError."""
    params = {
        "submitted": "1",
        "trend_from_date": "2026-10-10",
        "trend_to_date": "2026-10-01",
        "filter_type": "siteid",
        "site": ["JAP013"],
    }
    res = auth_client.get("/dashboard_5g", query_string=params)
    assert res.status_code == 200
