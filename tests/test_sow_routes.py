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
    """Authenticated users should see the OKR Crowdsource page with both tabs."""
    res = auth_client.get("/sow/crowdsource")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "OKR Crowdsource" in html
    assert "Achievement" in html
    assert "Trend Metrics" in html
    assert "Import Excel / CSV" in html
    # assert "Quarterly Targets" in html


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


def test_fb_share_compare_weeks_blank_fallback(auth_client):
    """A blank comparison week (202540 has rows but all provider columns NULL) must
    fall back one week to the last week that carries data, while weeks with data
    (WoW/MoM) stay nominal."""
    res = auth_client.get("/api/sow/fb-share/compare-weeks?week=202640")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["weeks"]["wow"] == 202639
    assert data["weeks"]["mom"] == 202636
    assert data["nominal"]["yoy"] == 202540
    assert data["weeks"]["yoy"] == 202539
    assert data["shift"]["yoy"] == 1


def test_fb_share_compare_api_uses_resolved_weeks(auth_client):
    """The dashboard comparison endpoint reports the resolved comparison weeks."""
    res = auth_client.post("/api/sow/fb-share/compare", json={"yearweek": 202640, "threshold": 95})
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["compare_weeks"] == {"wow": 202639, "mom": 202636, "yoy": 202539}
    assert data["summary"]["regional_tsel"] > 0
    assert len(data["branch_table"]) >= 2
    assert data["branch_table"][-1]["is_regional"] is True


def test_fb_share_pptx_export(auth_client):
    """The PPTX export returns a 2-slide deck rendered from the template."""
    from pptx import Presentation

    res = auth_client.get("/export/sow/fb-share-pptx?week=202640&threshold=95")
    assert res.status_code == 200
    assert "presentationml.presentation" in res.headers["Content-Type"]
    assert "crowdsource_fb_share_2026w40.pptx" in res.headers["Content-Disposition"]
    assert res.data[:2] == b"PK"

    prs = Presentation(io.BytesIO(res.data))
    assert len(prs.slides) == 2
    slide_text = "\n".join(
        sh.text_frame.text for sh in prs.slides[0].shapes if sh.has_text_frame
    )
    assert "Summary :" in slide_text
    assert "W40'26" in slide_text
    assert "vs W39'25" in slide_text  # YoY compares against the fallback week


def test_fb_share_pptx_export_blank_week(auth_client):
    """A week whose provider columns are all NULL has no report to build."""
    res = auth_client.get("/export/sow/fb-share-pptx?week=202540")
    assert res.status_code == 404
    assert res.get_json()["status"] == "error"


def test_api_sow_import_csv(auth_client):
    """Test importing and upserting sample benchmark records via CSV."""
    import os
    import psycopg2
    from dotenv import load_dotenv

    csv_content = """Region,level,location,provider,yearweek,metric,rank,mean or percentage,lci,uci
MALUKU DAN PAPUA,Region,MALUKU DAN PAPUA,Telkomsel,202699,download_overall,1,45.5,44.0,47.0
MALUKU DAN PAPUA,Region,MALUKU DAN PAPUA,Indosat,202699,download_overall,2,35.0,33.5,36.5
"""
    data = {
        "file": (io.BytesIO(csv_content.encode("utf-8")), "test_import.csv")
    }
    try:
        res = auth_client.post("/api/sow/import", data=data, content_type="multipart/form-data")
        assert res.status_code == 200
        res_data = res.get_json()
        assert res_data["status"] == "success"
        assert res_data["rows_processed"] == 2
    finally:
        load_dotenv(".env")
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_DB_HOST"), database=os.getenv("POSTGRES_DB_NAME"),
            user=os.getenv("POSTGRES_DB_USER"), password=os.getenv("POSTGRES_DB_PASSWORD"),
            port=os.getenv("POSTGRES_DB_PORT", "5432"), connect_timeout=10,
        )
        cur = conn.cursor()
        cur.execute("DELETE FROM sow.onx_rank_score WHERE yearweek = 202699")
        conn.commit()
        cur.close()
        conn.close()
