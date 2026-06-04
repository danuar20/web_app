"""
conftest.py — pytest fixtures and shared test configuration.

The app connects to three real databases via environment variables in .env.
For testing, we monkey-patch the connection factories so they raise
psycopg2.OperationalError — this lets us exercise route logic (auth checks,
redirects, flash messages) WITHOUT needing live database servers.
"""
import pytest
import sys
import os

# Ensure the project root is on the import path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def app():
    """Build a test-ready Flask app (without touching any databases)."""
    from app import create_app

    test_app = create_app()
    test_app.config["TESTING"]          = True
    test_app.config["WTF_CSRF_ENABLED"]  = False   # disable CSRF in forms
    test_app.config["SECRET_KEY"]        = "test-secret-key"

    yield test_app


# ---------------------------------------------------------------------------
# Client fixture  (two variants for different session needs)
# ---------------------------------------------------------------------------
@pytest.fixture
def client(app):
    """Flask test client that shares NO session between tests (isolated)."""
    with app.test_client() as c:
        yield c


@pytest.fixture
def authenticated_client(app):
    """
    Flask test client pre-logged-in as 'testuser'.

    Because DB calls are patched to raise OperationalError, the login route
    will always hit the except-block and call flash("Server offline...", "warning").
    To work around this we inject the session key directly.
    """
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["username"] = "testuser"
        yield c


# ---------------------------------------------------------------------------
# Patched DB factories  (raise OperationalError so route code follows the
#  error-handling path without requiring a live database)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def patch_db(monkeypatch):
    """Replace every DB connection factory with a version that raises."""
    import psycopg2

    def raise_error(*args, **kwargs):
        raise psycopg2.OperationalError("test: simulated DB unavailable")

    for attr in ("get_connection", "get_postgres_connection", "get_pumaz_connection"):
        for mod in ("app.db.db_webapp", "app.db.db_pumaz"):
            if attr in sys.modules[mod].__dict__:
                monkeypatch.setattr(f"{mod}.{attr}", raise_error)


# ---------------------------------------------------------------------------
# Helper: POST to login with the given username / password
# ---------------------------------------------------------------------------
@pytest.fixture
def post_login(client):
    """Return a callable that POSTs credentials to /login."""
    def _do(username="testuser", password="testpassword", follow_redirects=False):
        return client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=follow_redirects,
        )
    return _do