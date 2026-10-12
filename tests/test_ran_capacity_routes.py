import pytest
from app import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "test_engineer"
        sess["role"] = "engineer"
    return client


@pytest.fixture
def viewer_client(client):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "test_viewer"
        sess["role"] = "viewer"
    return client


def test_ran_capacity_page_authenticated(auth_client):
    """Authenticated user should see the SOW RAN Capacity page."""
    res = auth_client.get("/sow/ran_capacity")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "SOW RAN Capacity" in html
    assert "RAN Capacity Achievement" in html
    assert "Trend & Regional Analysis" in html
    assert "Comparison & Sector Table" in html
    assert "chartMacroTrend" in html
    assert "chartTransition" in html
    assert "branchDistribWrap" in html


def test_ran_capacity_page_viewer_blocked(viewer_client):
    """Viewer role should be blocked from /sow/ran_capacity."""
    res = viewer_client.get("/sow/ran_capacity", follow_redirects=False)
    assert res.status_code in (302, 403)


def test_api_ran_capacity_summary_w38(auth_client):
    """Verify W38 summary matches reference RCI data."""
    res = auth_client.get("/api/sow/ran_capacity/summary?region=PUMA&week=202638")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["yearweek"] == 202638

    # RCI assertions
    rci = data["rci"]
    assert rci["total_sectors"] == 8509
    assert rci["optim_sectors"] == 52
    assert rci["optim_pct"] == 0.61
    assert rci["engineering_sectors"] == 125
    assert rci["operation_sectors"] == 60
    assert rci["target"] == 0.42
    assert rci["is_pass"] is False
    assert rci["ach_gap"] == -0.19
    assert rci["excess_sectors"] == 17

    # Check Aging categories
    aging = rci["aging_counts"]
    assert aging["new comer"] == 19
    assert aging["1 month"] == 28
    assert aging["2 month"] == 2
    assert aging["3 month"] == 1
    assert aging[">3 month"] == 2

    # Check NOP gauge
    gauge = rci["regional_gauge"]
    assert len(gauge) == 4
    ambon = next(b for b in gauge if b["name"] == "AMBON")
    assert ambon["optim"] == 14
    assert ambon["engineering"] == 21


def test_api_ran_capacity_summary_w37(auth_client):
    """Verify W37 summary matches reference Unbalance data."""
    res = auth_client.get("/api/sow/ran_capacity/summary?region=PUMA&week=202637")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"

    # Unbalance assertions
    unb = data["unbalance"]
    assert unb["total_sectors"] == 8498
    assert unb["p1_sectors"] == 179
    assert unb["p1_pct"] == 2.11
    assert unb["balanced_sectors"] == 7829
    assert unb["p2_sectors"] == 357
    assert unb["p3_sectors"] == 133
    assert unb["target"] == 1.85
    assert unb["is_pass"] is False
    assert unb["ach_gap"] == -0.26

    # V1, V2, V3 breakdown within P1
    assert unb["v1_p1"]["balanced"] == 105
    assert unb["v1_p1"]["unbalanced"] == 74
    assert unb["v2_p1"]["balanced"] == 92
    assert unb["v2_p1"]["unbalanced"] == 87
    assert unb["v3_p1"]["balanced_thp"] == 117
    assert unb["v3_p1"]["unbalanced_thp"] == 62


def test_api_ran_capacity_trend(auth_client):
    """Verify trend timeline returns both RCI and Unbalance data series."""
    res = auth_client.get("/api/sow/ran_capacity/trend?region=PUMA&start_week=202628&end_week=202638")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert len(data["yearweeks"]) >= 10

    # RCI trend series
    rci_t = data["rci_trend"]
    assert "optimization" in rci_t
    assert "engineering" in rci_t
    assert "optim_pct" in rci_t
    assert "target_series" in rci_t

    # Unbalance trend series
    unb_t = data["unbalance_trend"]
    assert "p1" in unb_t
    assert "balanced" in unb_t
    assert "p1_pct" in unb_t
    assert "q_targets" in unb_t

    # Deep-dive kabupaten series
    assert "kabupaten_list" in data
    assert len(data["kabupaten_list"]) >= 50
    assert "kabupaten_trends" in data
    sample_kab = data["kabupaten_list"][0]
    assert "optim" in data["kabupaten_trends"][sample_kab]
    assert "p1" in data["kabupaten_trends"][sample_kab]


def test_api_ran_capacity_comparison(auth_client):
    """Verify comparison table endpoint."""
    res_rci = auth_client.get("/api/sow/ran_capacity/comparison?region=PUMA&week=202638&mode=rci")
    assert res_rci.status_code == 200
    data_rci = res_rci.get_json()
    assert data_rci["status"] == "success"
    assert "table_nop" in data_rci
    assert "table_kab" in data_rci
    assert len(data_rci["table_nop"]) == 4

    res_unb = auth_client.get("/api/sow/ran_capacity/comparison?region=PUMA&week=202637&mode=unbalance")
    assert res_unb.status_code == 200
    data_unb = res_unb.get_json()
    assert data_unb["status"] == "success"
    assert len(data_unb["table_nop"]) == 4


def test_api_ran_capacity_export(auth_client):
    """Verify export endpoints for CSV."""
    res_kab = auth_client.get("/api/sow/ran_capacity/export?region=PUMA&week=202638&mode=rci&level=kabupaten")
    assert res_kab.status_code == 200
    assert "text/csv" in res_kab.content_type
    assert "RAN_Capacity_RCI_Kabupaten_202638.csv" in res_kab.headers.get("Content-Disposition", "")

    res_sec = auth_client.get("/api/sow/ran_capacity/export?region=PUMA&week=202638&mode=unbalance&level=sector")
    assert res_sec.status_code == 200
    assert "text/csv" in res_sec.content_type
    assert "RAN_Capacity_Sectors_UNBALANCE_202638.csv" in res_sec.headers.get("Content-Disposition", "")


def test_api_ran_capacity_sample(auth_client):
    """Verify sample template generation."""
    res_csv = auth_client.get("/api/sow/ran_capacity/sample?format=csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.content_type

    res_xlsx = auth_client.get("/api/sow/ran_capacity/sample?format=xlsx")
    assert res_xlsx.status_code == 200
    assert "openxmlformats" in res_xlsx.content_type


def test_api_ran_capacity_behavioral_math_consistency(auth_client):
    """Verify behavioral sum strictly equals total optim sectors (prevent double counting)."""
    res = auth_client.get("/api/sow/ran_capacity/summary?region=PUMA&week=202639")
    assert res.status_code == 200
    data = res.get_json()
    rci = data["rci"]
    beh = rci["behavior"]
    assert rci["optim_sectors"] == 49
    assert beh["consecutive"] + beh["flipflop"] + beh["new_comer"] == 49
    assert beh["new_comer"] == 17
    assert beh["consecutive"] == 29
    assert beh["flipflop"] == 3


def test_api_ran_capacity_branch_filter_accuracy(auth_client):
    """Verify branch filter returns accurate branch scoped data quickly."""
    res = auth_client.get("/api/sow/ran_capacity/summary?region=PUMA&week=202638&branch=AMBON")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["branch"] == "AMBON"
    rci = data["rci"]
    assert rci["total_sectors"] == 2607
    assert rci["optim_sectors"] == 14
    assert rci["engineering_sectors"] == 21

