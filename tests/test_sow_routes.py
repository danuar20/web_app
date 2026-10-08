import io
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


def test_crowdsource_page_authenticated(auth_client):
    """Authenticated users should see the SOW Crowdsource page with both tabs."""
    res = auth_client.get("/sow/crowdsource")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "SOW Crowdsource" in html
    assert "Achievement" in html
    assert "Trend Metrics" in html
    assert "Import Excel / CSV" in html
    assert "Quarterly Targets" in html


def test_api_sow_regions(auth_client):
    """Test API returning distinct Kabupaten regions."""
    res = auth_client.get("/api/sow/regions")
    assert res.status_code == 200
    data = res.get_json()
    assert "regions" in data
    assert len(data["regions"]) > 0
    assert "BALI NUSRA" in data["regions"]


def test_api_sow_locations_with_region(auth_client):
    """Test Kabupaten locations filtered by Region."""
    res = auth_client.get("/api/sow/locations?level=Kabupaten&region=BALI%20NUSRA")
    assert res.status_code == 200
    data = res.get_json()
    assert "locations" in data
    assert "BADUNG" in data["locations"] or "DENPASAR" in data["locations"] or "ALOR" in data["locations"]


def test_api_sow_chart_data_custom_targets(auth_client):
    """Test chart data calculation with custom quarterly targets."""
    payload = {
        "level": "Region",
        "location": "MALUKU DAN PAPUA",
        "provider": "Telkomsel",
        "start_yearweek": 202601,
        "end_yearweek": 202638,
        "target_q1": 15,
        "target_q2": 13,
        "target_q3": 14,
        "target_q4": 14
    }
    res = auth_client.post("/api/sow/chart-data", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "targets" in data
    assert len(data["targets"]) == len(data["labels"])
    # Targets are loaded dynamically from sow.sow_target
    assert isinstance(data["targets"][0], int)
    assert data["targets"][0] > 0
    assert isinstance(data["targets"][14], int)
    assert data["targets"][14] > 0


def test_api_sow_trend_metrics(auth_client):
    """Test multi-provider Trend Metrics API for 16 metrics."""
    payload = {
        "level": "Region",
        "location": "MALUKU DAN PAPUA",
        "providers": ["Indosat", "Telkomsel", "XL"],
        "start_yearweek": 202602,
        "end_yearweek": 202638
    }
    res = auth_client.post("/api/sow/trend-metrics", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "weeks" in data
    assert "metrics" in data
    assert "winners" in data
    assert len(data["ordered_metrics"]) == 16
    assert "videoexperience_overall" in data["metrics"]
    assert "Indosat" in data["metrics"]["videoexperience_overall"]["providers"]
    assert "Telkomsel" in data["metrics"]["videoexperience_overall"]["providers"]


def test_api_sow_sample_template_csv(auth_client):
    """Test downloading sample template in CSV format."""
    res = auth_client.get("/api/sow/sample-template?format=csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["Content-Type"]
    content = res.data.decode("utf-8")
    assert "yearweek" in content
    assert "metric" in content
    assert "mean or percentage" in content


def test_api_sow_sample_template_xlsx(auth_client):
    """Test downloading sample template in XLSX format."""
    res = auth_client.get("/api/sow/sample-template?format=xlsx")
    assert res.status_code == 200
    assert "spreadsheetml" in res.headers["Content-Type"]


def test_api_sow_import_csv(auth_client):
    """Test importing and upserting sample benchmark records via CSV."""
    csv_content = """Region,level,location,provider,yearweek,metric,rank,mean or percentage,lci,uci
MALUKU DAN PAPUA,Region,MALUKU DAN PAPUA,Telkomsel,202699,download_overall,1,45.5,44.0,47.0
MALUKU DAN PAPUA,Region,MALUKU DAN PAPUA,Indosat,202699,download_overall,2,35.0,33.5,36.5
"""
    data = {
        "file": (io.BytesIO(csv_content.encode("utf-8")), "test_import.csv")
    }
    res = auth_client.post("/api/sow/import", data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    res_data = res.get_json()
    assert res_data["status"] == "success"
    assert res_data["rows_processed"] == 2
