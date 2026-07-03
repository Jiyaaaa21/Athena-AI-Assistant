"""
backend/tests/conftest.py — Phase 30: test infrastructure

Sets up an isolated SQLite file per test session, resets all tables
between individual tests (drop + recreate -- simple, deterministic, and
fast enough at this table count/data volume; avoids the complexity of
trying to wrap the app's own per-request SessionLocal() calls in an
outer transaction that rolls back, which doesn't compose cleanly with
how the app itself manages sessions).

IMPORTANT: env vars below are set at module level, before any `backend.*`
import in this file or in any test file that runs after conftest.py is
collected. Several modules construct third-party API clients at IMPORT
time (core/llm.py does `Groq(api_key=GROQ_API_KEY)` at module scope) and
raise immediately if that key is completely unset/empty -- not just
"None", genuinely absent breaks the import. A dummy key lets everything
import cleanly; no test in this suite makes a real network call to Groq
(that would need a real key, cost money, and be flaky in CI).
"""

import os
import tempfile

# Cross-platform temp file path -- os.path.join + tempfile.gettempdir()
# instead of a hardcoded "/tmp/..." (Unix-only; on Windows that resolved
# to C:\tmp\athena_test.db, which fails with "unable to open database
# file" since C:\tmp doesn't exist by default). Forward-slashing the
# result works for BOTH platforms' SQLite URL forms: a Unix path already
# starts with "/", so "sqlite://" + "/" + "/tmp/x.db" correctly yields
# four slashes total (sqlite:////tmp/x.db, the Unix-absolute form); a
# Windows path starts with a drive letter with no leading slash, so the
# same template yields three slashes then the drive letter
# (sqlite:///C:/Users/.../Temp/x.db, the Windows-absolute form) --
# exactly what each platform's SQLite URL syntax expects.
_TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "athena_test.db").replace("\\", "/")
_TEST_DB_URL = f"sqlite:///{_TEST_DB_PATH}"

os.environ.setdefault("DATABASE_URL", _TEST_DB_URL)
os.environ.setdefault("GROQ_API_KEY", "gsk_test_dummy_key_for_imports_only")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production-use")
os.environ.setdefault("PROACTIVE_ENABLED", "false")
os.environ.setdefault("ALLOWED_ORIGINS", "*")

import pytest
from fastapi.testclient import TestClient

from backend.database.db import engine
from backend.database.models import Base


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """
    Every RateLimiter in core/rate_limit.py is a module-level singleton,
    imported once and shared for the whole test process -- exactly like
    production, where that's the correct design (one real limit per
    user, not reset per request). But it means without this fixture,
    a test that deliberately trips a limiter (e.g. the auth rate-limit
    test) leaks that state into every test that runs after it, causing
    unrelated tests to fail with unexpected 429s depending on test
    execution order. Reset before every test so each one starts with a
    clean slate, the same isolation guarantee db_schema already gives
    the database.
    """
    from backend.core import rate_limit as rl
    for name in dir(rl):
        obj = getattr(rl, name)
        if isinstance(obj, rl.RateLimiter):
            obj.reset()
    yield


@pytest.fixture(scope="function")
def db_schema():
    """Fresh tables for every single test -- drop then recreate. Keeps
    tests fully isolated from each other with no shared state to leak
    between them, which matters a lot for something like the rate
    limiter or account-deletion tests where leftover rows/counters from
    a previous test could silently change the outcome of the next one."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_schema):
    """
    A TestClient against the real app, deliberately NOT using `with
    TestClient(app) as c:` -- that would trigger main.py's
    @app.on_event("startup") handler, which starts the reminder
    scheduler and proactive engine as real background threads. Nothing
    in this suite needs those running, and it's one less source of
    test-to-test interference/flakiness (a background thread touching
    the same SQLite file another test just dropped and recreated).
    Tables are created directly by the db_schema fixture instead of via
    run_migrations().
    """
    import main
    return TestClient(main.app)


@pytest.fixture
def db(db_schema):
    """Direct DB session for tests that need to set up or inspect rows
    the API doesn't expose a convenient endpoint for."""
    from backend.database.db import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_user(client):
    """Creates a real user through the actual signup endpoint (not a
    direct DB insert) so the password is hashed exactly the way
    production does it, and returns both the response body and the raw
    password (needed for login/delete-account tests that must supply it)."""
    email = "testuser@example.com"
    password = "correct-horse-battery-staple"
    resp = client.post("/auth/signup", json={
        "name": "Test User", "email": email, "password": password,
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {
        "email": email,
        "password": password,
        "user_id": body["user"]["id"],
        "access_token": body["tokens"]["access_token"],
        "refresh_token": body["tokens"]["refresh_token"],
    }


@pytest.fixture
def auth_headers(test_user):
    return {"Authorization": f"Bearer {test_user['access_token']}"}

