import pytest
from app import create_app
from app.db.db_webapp import get_site_sec_list_4g


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture
def auth_client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "test_engineer"
        sess["role"] = "admin"
    return c


def test_get_site_sec_list_4g():
    """Verify that get_site_sec_list_4g returns formatted site-sector entries."""
    secs, src = get_site_sec_list_4g()
    assert len(secs) > 0, "Expected non-empty list of site-sectors"
    # Ensure format is SITEID-SEC
    sample = secs[0]
    assert "-" in sample, f"Expected '-' in site-sec name, got: {sample}"
    sid, sec = sample.rsplit("-", 1)
    assert len(sid) > 0 and len(sec) > 0


def test_dashboard_4g_filter_list_api(auth_client):
    """GET /api/filter_list_4g?filter_type=site_sec returns site-sector list."""
    res = auth_client.get("/api/filter_list_4g?filter_type=site_sec")
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("success") is True
    items = data.get("items", [])
    assert len(items) > 0
    assert any("-" in item for item in items)


def test_dashboard_4g_html_filter_order(auth_client):
    """Verify in Dashboard 4G HTML that the filter radio button order is:
    Site ID -> Site-Sec -> Site-Cell -> City
    """
    res = auth_client.get("/dashboard_4g")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'value="site_sec"' in html
    pos_siteid = html.find('value="siteid"')
    pos_sitesec = html.find('value="site_sec"')
    pos_sitecell = html.find('value="site_cell"')
    pos_city = html.find('value="city"')
    assert pos_siteid != -1 and pos_sitesec != -1 and pos_sitecell != -1 and pos_city != -1
    assert pos_siteid < pos_sitesec < pos_sitecell < pos_city, (
        f"Filter order error: siteid={pos_siteid}, sitesec={pos_sitesec}, sitecell={pos_sitecell}, city={pos_city}"
    )


def test_dashboard_4g_submit_site_sec(auth_client):
    """GET /dashboard_4g with filter_type=site_sec renders correctly."""
    res = auth_client.get(
        "/dashboard_4g?submitted=1&filter_type=site_sec"
        "&trend_from_date=2026-10-01&trend_to_date=2026-10-05"
        "&before_from_date=2026-10-01&before_to_date=2026-10-02"
        "&after_from_date=2026-10-03&after_to_date=2026-10-04"
        "&site=AGA001-1&site=AGA001-2"
    )
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Site-Sec Level Comparison" in html
    assert "Site-Sec" in html


def test_dashboard_4g_tech_api_site_sec(auth_client):
    """POST /api/dashboard_4g_tech with filter_type=site_sec succeeds."""
    res = auth_client.post(
        "/api/dashboard_4g_tech",
        json={
            "trend_from_date": "2026-10-01",
            "trend_to_date": "2026-10-05",
            "before_from_date": "2026-10-01",
            "before_to_date": "2026-10-02",
            "after_from_date": "2026-10-03",
            "after_to_date": "2026-10-04",
            "filter_type": "site_sec",
            "site": ["AGA001-1", "AGA001-2"],
            "fdd_bands": ["L1800", "L900"],
            "tdd_bands": ["L2300_1"],
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("success") is True
