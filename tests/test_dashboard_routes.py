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


def test_5g_intra_inter_ho_kpis(auth_client):
    """5G Monitoring and Dashboard 5G support Intra and Inter HO SR KPIs."""
    # 1. Dashboard 5G
    params_dash = {
        "submitted": "1",
        "trend_from_date": "2026-10-01",
        "trend_to_date": "2026-10-05",
        "before_from_date": "2026-10-01",
        "before_to_date": "2026-10-02",
        "after_from_date": "2026-10-03",
        "after_to_date": "2026-10-04",
        "filter_type": "siteid",
        "site": ["JAP013"],
        "kpi": ["intraHoChart", "interHoChart"],
    }
    res_dash = auth_client.get("/dashboard_5g", query_string=params_dash)
    assert res_dash.status_code == 200
    html_dash = res_dash.data.decode("utf-8")
    assert "Intra HO SR" in html_dash
    assert "Inter HO SR" in html_dash

    # 2. 5G Monitoring
    params_mon = {
        "submitted": "1",
        "from_date": "2026-10-01",
        "to_date": "2026-10-05",
        "kpi": ["intraHoChart", "interHoChart"],
    }
    res_mon = auth_client.get("/kpi_5g_monitoring", query_string=params_mon)
    assert res_mon.status_code == 200
    html_mon = res_mon.data.decode("utf-8")
    assert "Intra HO SR" in html_mon
    assert "Inter HO SR" in html_mon

