"""Tests for the read-only Query Database console (/database/query)."""

import pathlib
import re
import subprocess

import pytest

from app import create_app
from app.routes import query_db_routes as qdb


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(client):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "test_admin"
        sess["role"] = "admin"
    return client


@pytest.fixture
def viewer_client(client):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "test_viewer"
        sess["role"] = "viewer"
    return client


# ── Page & access control ────────────────────────────────────────────────────
def test_query_page_admin_allowed(admin_client):
    res = admin_client.get("/database/query")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "qdb-shell" in html
    assert 'href="/database/query"' in html          # menu entry rendered
    assert 'href="/database/postgres"' in html       # admin sees sibling db pages
    assert 'href="/database/sites_db"' in html


def test_query_page_viewer_allowed(viewer_client):
    """Viewers can open Query Database, run queries, and export, but cannot access admin sibling pages."""
    res = viewer_client.get("/database/query")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "qdb-shell" in html
    assert 'href="/database/query"' in html
    assert 'href="/database/postgres"' not in html   # viewer cannot see Postgres DB link
    assert 'href="/database/sites_db"' not in html   # viewer cannot see Sites DB link

    # Viewer APIs work for read-only querying
    assert viewer_client.get("/api/query_db/tables").status_code == 200
    assert viewer_client.get("/api/query_db/columns?table=sites_db").status_code == 200
    res_run = viewer_client.post("/api/query_db/run", json={"sql": "SELECT 1 AS n"})
    assert res_run.status_code == 200
    assert res_run.get_json()["rows"] == [[1]]

    # Sibling admin pages remain blocked for viewer
    assert viewer_client.get("/database/postgres").status_code == 302
    assert viewer_client.get("/database/sites_db").status_code == 302


def test_query_page_scripts_parse(admin_client, tmp_path):
    """A JS syntax error would silently freeze every control on the page."""
    res = admin_client.get("/database/query")
    html = res.get_data(as_text=True)
    assert 'id="qdbBuilderOpen"' in html
    assert 'id="qdbBuilderDialog"' in html
    assert "query_builder.js" in html

    bodies = [b for b in re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", html, re.DOTALL) if b.strip()]
    assert bodies, "expected at least one inline script"
    for index, body in enumerate(bodies):
        target = tmp_path / f"query_db_{index}.js"
        target.write_text(body, encoding="utf-8")
        result = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    # Also verify external static scripts linked by the page
    script_srcs = re.findall(r'<script\s+[^>]*src="([^"]+)"', html)
    for src in script_srcs:
        clean_src = src.split("?")[0]
        if clean_src.startswith("/static/"):
            rel_path = clean_src[len("/static/"):]
            local_file = pathlib.Path("D:/Database/Coding/Belajar Coding Basic/Web-server/web_app/static") / rel_path
            assert local_file.is_file(), f"linked script {local_file} not found"
            res_node = subprocess.run(["node", "--check", str(local_file)], capture_output=True, text=True)
            assert res_node.returncode == 0, res_node.stderr


# ── Catalog endpoints ────────────────────────────────────────────────────────
def test_tables_and_columns(admin_client):
    res = admin_client.get("/api/query_db/tables")
    body = res.get_json()
    assert res.status_code == 200
    assert body["schema"] == "public"
    tables = body["tables"]
    names = {t["name"] for t in tables}

    assert "sites_db" in names            # base table
    assert "4g_kpi_zte" in names
    assert "mv_siteid_4g" not in names    # materialized views hidden
    assert "BSC_2g" not in names          # views hidden
    assert {t["kind"] for t in tables} == {"table"}, "table list must contain base tables only"

    res = admin_client.get("/api/query_db/columns?table=sites_db")
    body = res.get_json()
    assert res.status_code == 200
    assert [c["name"] for c in body["columns"]][:2] == ["SiteID", "SiteID_v2"]

    assert admin_client.get("/api/query_db/columns?table=nope_not_here").status_code == 404


def test_materialized_view_hidden_but_still_queryable(admin_client):
    """Hidden from the browser does not mean blocked in SQL."""
    res = admin_client.post("/api/query_db/run", json={"sql": 'SELECT siteid FROM "mv_siteid_4g" LIMIT 3'})
    assert res.status_code == 200
    assert len(res.get_json()["rows"]) == 3


def test_sample_queries_are_rendered_and_executable(admin_client):
    html = admin_client.get("/database/query").get_data(as_text=True)
    assert html.count('class="qdb-chip"') == len(qdb.SAMPLE_QUERIES)

    for sample in qdb.SAMPLE_QUERIES:
        res = admin_client.post("/api/query_db/run", json={"sql": sample["sql"]})
        body = res.get_json()
        assert res.status_code == 200, f"sample '{sample['title']}' failed: {body.get('message')}"
        assert body["row_count"] >= 1, f"sample '{sample['title']}' returned no rows"


# ── Read-only enforcement ────────────────────────────────────────────────────
@pytest.mark.parametrize("sql", [
    "UPDATE sites_db SET siteid = 'X'",
    "DELETE FROM sites_db",
    "INSERT INTO sites_db (siteid) VALUES ('X')",
    "DROP TABLE sites_db",
    "SELECT 1; SELECT 2",
    "WITH d AS (DELETE FROM sites_db RETURNING 1) SELECT * FROM d",
    "SELECT * INTO new_tbl FROM mv_siteid_4g",
    "COPY (SELECT 1) TO PROGRAM 'echo x'",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_sleep(5)",
    "SELECT * FROM pg_catalog.pg_class",
    "SELECT * FROM sow.some_table",
])
def test_writes_and_foreign_schemas_are_rejected(admin_client, sql):
    res = admin_client.post("/api/query_db/run", json={"sql": sql})
    assert res.status_code == 400
    assert res.get_json()["status"] == "error"


def test_literal_text_does_not_trigger_validation(admin_client):
    res = admin_client.post("/api/query_db/run", json={
        "sql": "SELECT '-- drop table x ; delete' AS txt -- trailing note"
    })
    assert res.status_code == 200
    assert res.get_json()["rows"] == [["-- drop table x ; delete"]]


def test_select_returns_rows_and_is_capped(admin_client):
    res = admin_client.post("/api/query_db/run", json={
        "sql": 'SELECT siteid FROM "mv_siteid_4g" ORDER BY siteid LIMIT 5'
    })
    body = res.get_json()
    assert res.status_code == 200
    assert body["columns"] == ["siteid"]
    assert len(body["rows"]) == 5
    assert body["truncated"] is False

    res = admin_client.post("/api/query_db/run", json={"sql": 'SELECT siteid FROM "mv_siteid_4g"'})
    body = res.get_json()
    assert body["row_count"] == body["preview_limit"]
    assert body["truncated"] is True


def test_wide_result_is_cell_capped(admin_client):
    """row_count * columns must stay within the preview cell budget."""
    res = admin_client.post("/api/query_db/run", json={"sql": 'SELECT * FROM "4g_kpi_zte"'})
    body = res.get_json()
    assert res.status_code == 200
    assert body["row_count"] * len(body["columns"]) <= qdb.PREVIEW_CELL_BUDGET + len(body["columns"])
    assert body["cell_limited"] is True


def test_busy_console_returns_429(admin_client):
    qdb._slots.acquire()
    qdb._slots.acquire()
    try:
        assert admin_client.post("/api/query_db/run", json={"sql": "SELECT 1"}).status_code == 429
    finally:
        qdb._slots.release()
        qdb._slots.release()


# ── CSV export ───────────────────────────────────────────────────────────────
def test_csv_export_after_query(admin_client):
    res = admin_client.post("/api/query_db/export", json={
        "sql": 'SELECT siteid FROM "mv_siteid_4g" ORDER BY siteid LIMIT 7'
    })
    assert res.status_code == 200
    assert "text/csv" in res.headers["Content-Type"]
    assert "attachment" in res.headers["Content-Disposition"]
    lines = [ln for ln in res.get_data(as_text=True).splitlines() if ln.strip()]
    assert lines[0] == "siteid"
    assert len(lines) == 8


def test_csv_export_refuses_writes(admin_client):
    res = admin_client.post("/api/query_db/export", json={"sql": "UPDATE sites_db SET siteid='x'"})
    assert res.status_code == 400
