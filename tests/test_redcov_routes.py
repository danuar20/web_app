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


def test_redcov_page_authenticated(auth_client):
    """Authenticated users should see the SOW Redcov page with tabs and components."""
    res = auth_client.get("/sow/redcov")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "SOW Redcov" in html
    assert "Redcov Achievement" in html
    assert "Trend & Regional Analysis" in html
    assert "Comparison Table" in html
    assert "chartCoverageTrend" in html
    assert "chartRedBreakdown" in html
    assert "chartNopTrend" in html
    assert "chartTopContributors" in html


def test_redcov_page_viewer_blocked(viewer_client):
    """Viewer role should be blocked from /sow/redcov."""
    res = viewer_client.get("/sow/redcov", follow_redirects=False)
    assert res.status_code in (302, 403)


def test_api_redcov_summary(auth_client):
    """Test API returning summary metrics, target, baseline, and NOP distribution."""
    res = auth_client.get("/api/sow/redcov/summary?region=MALUKU%20DAN%20PAPUA&week=202637")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["yearweek"] == 202637
    assert data["total_grids"] == 890039
    assert data["total_red_cov"] == 2643
    assert data["total_red_optim"] == 1289
    assert data["total_red_eng"] == 1354
    assert data["target"] == 0.23
    assert data["red_optim_pct"] == 0.14
    assert data["red_cov_pct"] == 0.30
    assert data["is_pass"] is True
    assert "regional_distribution" in data
    assert len(data["regional_distribution"]) == 4
    # Check Ambon count in W37 matches image (1,135 grids)
    ambon = next((b for b in data["regional_distribution"] if b["name"] == "AMBON"), None)
    assert ambon is not None
    assert ambon["red_cov"] == 1135
    # Check Jayapura (935)
    jayapura = next((b for b in data["regional_distribution"] if b["name"] == "JAYAPURA"), None)
    assert jayapura is not None
    assert jayapura["red_cov"] == 935
    # Check Timika (570)
    timika = next((b for b in data["regional_distribution"] if b["name"] == "TIMIKA"), None)
    assert timika is not None
    assert timika["red_cov"] == 570
    # Check Sorong (3)
    sorong = next((b for b in data["regional_distribution"] if b["name"] == "SORONG"), None)
    assert sorong is not None
    assert sorong["red_cov"] == 3
    # Check Top Contributors (10 items)
    assert len(data["top_contributors"]) == 10
    assert data["top_contributors"][0]["kabupaten"] == "MALUKU TENGAH"
    assert data["top_contributors"][0]["red_optim"] == 196


def test_api_redcov_trend(auth_client):
    """Test API returning trend time series for charts."""
    res = auth_client.get("/api/sow/redcov/trend?region=MALUKU%20DAN%20PAPUA&start_week=202630&end_week=202637")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "labels" in data
    assert len(data["labels"]) > 0
    assert "coverage_trend" in data
    assert "breakdown_trend" in data
    assert "nop_trend_red" in data
    assert "quality_trend" in data


def test_api_redcov_comparison(auth_client):
    """Test API returning kabupaten-level and NOP-level comparison table."""
    res = auth_client.get("/api/sow/redcov/comparison?region=MALUKU%20DAN%20PAPUA&week=202637&compare_week=202636")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "rows" in data
    assert len(data["rows"]) == 53
    assert "nop_rows" in data
    assert len(data["nop_rows"]) == 4
    assert data["nop_rows"][0]["branch"] == "AMBON"
    assert "total_nop_row" in data
    assert data["total_nop_row"]["total_grid"] == 890039


def test_api_redcov_export(auth_client):
    """Test CSV export endpoint."""
    res = auth_client.get("/api/sow/redcov/export?region=MALUKU%20DAN%20PAPUA&week=202637")
    assert res.status_code == 200
    assert "text/csv" in res.headers["Content-Type"]
    content = res.data.decode("utf-8")
    assert "Kabupaten" in content
    assert "MALUKU TENGAH" in content


def test_api_redcov_sample_template(auth_client):
    """Test sample template in CSV and XLSX."""
    res_csv = auth_client.get("/api/sow/redcov/sample?format=csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["Content-Type"]
    content = res_csv.data.decode("utf-8")
    assert "yearweek" in content
    assert "grid_red_cov" in content

    res_xlsx = auth_client.get("/api/sow/redcov/sample?format=xlsx")
    assert res_xlsx.status_code == 200
    assert "spreadsheetml" in res_xlsx.headers["Content-Type"]


def test_api_redcov_import_csv(auth_client):
    """Test importing and upserting Redcov records via CSV."""
    import io
    import os
    import psycopg2
    from dotenv import load_dotenv

    csv_content = """yearweek,region,kabupaten,total_geohash7,total_call_count,total_subscriber_count,bad_tiles_rsrp,total_tiles,grid_bad_tile_abv_thd,grid_subs_abv_thd,grid_luas_abv_thd,grid_bad_tiles_n_subs_abv_thd,grid_bad_tiles_n_subs_n_luas_abv_thd,grid_bad_grid,grid_more_than_3_wks,grid_forming_cluster,grid_red_cov,NOT RED COV,RED ENGINEERING,BAD NON POTENTIAL,RED OPTIM
202699,MALUKU DAN PAPUA,TEST_KABUPATEN,1000,500.0,200.0,50,1000,10,5,5,2,2,2,1,1.0,2,800,1,197,1
"""
    data = {
        "file": (io.BytesIO(csv_content.encode("utf-8")), "test_redcov_import.csv")
    }
    res = auth_client.post("/api/sow/redcov/import", data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    res_data = res.get_json()
    assert res_data["status"] == "success"
    assert res_data["rows_processed"] == 1

    # Cleanup test row
    load_dotenv(".env")
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_DB_HOST"), database=os.getenv("POSTGRES_DB_NAME"),
        user=os.getenv("POSTGRES_DB_USER"), password=os.getenv("POSTGRES_DB_PASSWORD"),
        port=os.getenv("POSTGRES_DB_PORT", "5432"), connect_timeout=10)
    cur = conn.cursor()
    cur.execute("DELETE FROM sow.red_cov WHERE yearweek = 202699 AND kabupaten = 'TEST_KABUPATEN'")
    conn.commit()
    cur.close()
    conn.close()


def test_api_redcov_summary_branch_filter(auth_client):
    """Test API returning summary filtered to AMBON NOP."""
    res = auth_client.get("/api/sow/redcov/summary?region=MALUKU%20DAN%20PAPUA&week=202637&branch=AMBON")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["branch"] == "AMBON"
    assert data["total_red_cov"] == 1135
    assert len(data["top_contributors"]) <= 11
    assert all(c["branch"] == "AMBON" for c in data["top_contributors"])
    assert "funneling" in data
    assert len(data["funneling"]) == 6


def test_api_redcov_trend_branch_filter(auth_client):
    """Test API returning trend filtered to TIMIKA NOP."""
    res = auth_client.get("/api/sow/redcov/trend?region=MALUKU%20DAN%20PAPUA&start_week=202635&end_week=202637&branch=TIMIKA")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert len(data["coverage_trend"]["total_grid"]) == 3

