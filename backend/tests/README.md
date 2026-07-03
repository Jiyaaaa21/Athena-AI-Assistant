# Tests

## Running locally

From the repo root (same folder as `main.py` and `requirements.txt`):

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

That's it — no real API keys, no real database, no Docker needed.
`conftest.py` sets safe dummy values for anything the app needs just to
import (e.g. `GROQ_API_KEY`), and uses a throwaway SQLite file
(`/tmp/athena_test.db`) that gets its tables dropped and recreated
before every single test for full isolation.

Useful variations:

```bash
pytest -v                              # verbose, one line per test
pytest backend/tests/test_calculator.py   # just one file
pytest -k "calculator"                 # anything matching a keyword
pytest --cov=backend --cov-report=term-missing   # coverage report
```

## What's covered so far

This suite prioritizes the highest-risk and highest-value code over
exhaustive coverage of every endpoint in the app -- specifically the
security fixes and new features from this pass:

- **`test_calculator.py`** -- the most important file here. Regression
  guard for a fixed `eval()`-based RCE vulnerability: every legitimate
  math case, plus every real injection technique tried against it
  (`__import__`, `__class__.__subclasses__`, `exec`, etc.), all asserted
  to be rejected.
- **`test_pdf_generator.py`** -- regression tests for two real bugs
  found while building document generation (a cursor-position bug that
  crashed any multi-line PDF, and Latin-1 encoding limits on LLM output).
- **`test_rate_limit.py`** -- sliding-window behavior, per-key isolation,
  the `require_budget()` helper every rate-limited endpoint uses.
- **`test_auth.py`** -- signup/login success and failure paths, auth
  rate limiting.
- **`test_account_deletion.py`** -- the highest-stakes test in the
  suite, given how irreversible that operation is. Verifies the full
  cascading delete actually removes every row across all 24 user-owned
  tables (including the three indirectly-scoped ones with no `user_id`
  column of their own), that a deleted account's still-valid JWT stops
  working immediately, and that deleting one user never touches
  another's data.

## What's NOT covered yet

Most of the app: documents, calendar, reminders, notes, goals, voice,
the agent orchestrator's routing logic, the frontend entirely. This is
a foundation to build on, not a finished suite -- the infrastructure
here (fixtures for a real authenticated user, a fresh isolated DB per
test, a real `TestClient` against the actual app) makes adding more
tests for any of the above straightforward; there just isn't a test
file for them yet.

## Adding a new test

Any test that needs a logged-in user gets one for free:

```python
def test_something(client, auth_headers):
    resp = client.get("/some/protected/endpoint", headers=auth_headers)
    assert resp.status_code == 200
```

Any test that needs direct DB access:

```python
def test_something(db, test_user):
    from backend.database.models import Note
    row = Note(user_id=test_user["user_id"], title="x", content="y")
    db.add(row)
    db.commit()
    ...
```
