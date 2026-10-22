import pytest
import os
from unittest.mock import patch, MagicMock
from app import create_app
from app.routes.kpi_4g_monitoring_routes import (
    extract_sector_code,
    get_4g_sector_and_band,
)

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "testuser"
            sess["role"] = "admin"
        yield client

def test_extract_sector_code():
    assert extract_sector_code("E_AMB004IL1_Sitanala-DMT_IL01", "AMB004") == "IL"
    assert extract_sector_code("E_AMB004ML1_Sitanala-DMT_ML01", "AMB004") == "ML"
    assert extract_sector_code("E_AMB004IR1_Sitanala-DMT_IR01", "AMB004") == "IR"
    assert extract_sector_code("E_AMB004MR1_Sitanala-DMT_MR01", "AMB004") == "MR"
    assert extract_sector_code("E_JAP050IE1_AirportSentani_IE04", "JAP050") == "IE"
    assert extract_sector_code("E_JAP050IF1_AirportSentani_IF02", "JAP050") == "IF"
    assert extract_sector_code("E_AMB004EL1_iMacro035_Sitanala-DMT_EL07", "AMB004") == "EL"

def test_get_4g_sector_and_band():
    # Cell 11 -> Sector 1, Band L1800
    sec, band = get_4g_sector_and_band("11")
    assert sec == "1"
    assert band == "L1800"

    # Cell 12 -> Sector 1, Band L900
    sec, band = get_4g_sector_and_band("12")
    assert sec == "1"
    assert band == "L900"

    # Cell 13 -> Sector 1, Band L2100
    sec, band = get_4g_sector_and_band("13")
    assert sec == "1"
    assert band == "L2100"

    # Cell 14 -> Sector 1, Band L2300_1
    sec, band = get_4g_sector_and_band("14")
    assert sec == "1"
    assert band == "L2300_1"

    # Cell 71 -> Sector 7, Band L1800
    sec, band = get_4g_sector_and_band("71")
    assert sec == "7"
    assert band == "L1800"

def test_sector_data_indoor_macro_separation(client):
    """
    Verify that an Indoor cell (IL01) and a Macro cell (ML01) sharing
    the same cell number (11) on the same site (AMB004) do NOT get collapsed
    into a single Macro series, but generate distinct legends.
    """
    mock_rows = [
        # dt_label, siteid, cell, cell_name, payloadChart
        ("2026-10-22", "AMB004", "11", "E_AMB004IL1_Sitanala-DMT_IL01", 6.27),
        ("2026-10-22", "AMB004", "11", "E_AMB004ML1_Sitanala-DMT_ML01", 66.95),
        ("2026-10-22", "AMB004", "13", "E_AMB004IR1_Sitanala-DMT_IR01", 4.33),
        ("2026-10-22", "AMB004", "13", "E_AMB004MR1_Sitanala-DMT_MR01", 51.07),
    ]

    with patch("app.routes.kpi_4g_monitoring_routes.db_query") as mock_db:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value.__enter__.return_value = (mock_conn, mock_cur)
        mock_cur.fetchall.return_value = mock_rows

        res = client.post(
            "/api/kpi_4g_monitoring/sector_data",
            json={
                "from_date": "2026-10-22",
                "to_date": "2026-10-22",
                "sites": ["AMB004"],
                "kpis": ["payloadChart"],
            },
        )
        assert res.status_code == 200
        data = res.get_json()
        assert "daily" in data
        legends = data["daily"]["legends"]

        # Must have both Indoor and Macro series
        assert "AMB004 S1|L1800 IL-11" in legends
        assert "AMB004 S1|L1800 ML-11" in legends
        assert "AMB004 S1|L2100 IR-13" in legends
        assert "AMB004 S1|L2100 MR-13" in legends

        # Check payload values did not get lost or overwritten
        p_data = data["daily"]["data"]["payloadChart"]
        assert p_data["AMB004 S1|L1800 IL-11"] == [6.27]
        assert p_data["AMB004 S1|L1800 ML-11"] == [66.95]
        assert p_data["AMB004 S1|L2100 IR-13"] == [4.33]
        assert p_data["AMB004 S1|L2100 MR-13"] == [51.07]

def test_sector_data_bdbh_indoor_macro_separation(client):
    """
    Verify that BDBH mode also separates Indoor and Macro cells properly.
    """
    mock_rows = [
        ("2026-10-20", "AMB004", "11", "E_AMB004IL1_Sitanala-DMT_IL01", 5.5),
        ("2026-10-20", "AMB004", "11", "E_AMB004ML1_Sitanala-DMT_ML01", 55.0),
    ]

    with patch("app.routes.kpi_4g_monitoring_routes.db_query") as mock_db:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value.__enter__.return_value = (mock_conn, mock_cur)
        mock_cur.fetchall.return_value = mock_rows

        res = client.post(
            "/api/kpi_4g_monitoring/sector_data_bdbh",
            json={
                "from_date": "2026-10-20",
                "to_date": "2026-10-20",
                "sites": ["AMB004"],
                "kpis": ["payloadChart"],
            },
        )
        assert res.status_code == 200
        data = res.get_json()
        assert "daily" in data
        legends = data["daily"]["legends"]

        assert "AMB004 S1|L1800 IL-11" in legends
        assert "AMB004 S1|L1800 ML-11" in legends
        p_data = data["daily"]["data"]["payloadChart"]
        assert p_data["AMB004 S1|L1800 IL-11"] == [5.5]
        assert p_data["AMB004 S1|L1800 ML-11"] == [55.0]
