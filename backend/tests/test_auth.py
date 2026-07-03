"""
Integration tests for backend/api/auth.py, run against a real (SQLite)
database and the actual FastAPI app via TestClient -- not mocked.
"""


class TestSignup:
    def test_signup_succeeds(self, client):
        resp = client.post("/auth/signup", json={
            "name": "New User", "email": "new@example.com", "password": "a-strong-password",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["user"]["email"] == "new@example.com"
        assert "access_token" in body["tokens"]
        assert "refresh_token" in body["tokens"]

    def test_signup_duplicate_email_rejected(self, client, test_user):
        resp = client.post("/auth/signup", json={
            "name": "Someone Else", "email": test_user["email"], "password": "another-password",
        })
        assert resp.status_code >= 400


class TestLogin:
    def test_login_succeeds_with_correct_password(self, client, test_user):
        resp = client.post("/auth/login", json={
            "email": test_user["email"], "password": test_user["password"],
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()["tokens"]

    def test_login_fails_with_wrong_password(self, client, test_user):
        resp = client.post("/auth/login", json={
            "email": test_user["email"], "password": "definitely-wrong",
        })
        assert resp.status_code >= 400

    def test_login_fails_for_nonexistent_user(self, client):
        resp = client.post("/auth/login", json={
            "email": "nobody@example.com", "password": "whatever",
        })
        assert resp.status_code >= 400


class TestAuthenticatedEndpoint:
    def test_me_requires_auth(self, client):
        resp = client.get("/me")
        assert resp.status_code == 401

    def test_me_succeeds_with_valid_token(self, client, test_user, auth_headers):
        resp = client.get("/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == test_user["email"]

    def test_me_rejects_garbage_token(self, client):
        resp = client.get("/me", headers={"Authorization": "Bearer not-a-real-token"})
        assert resp.status_code == 401


class TestAuthRateLimiting:
    """Phase 29: /auth/login previously had no rate limiting at all."""

    def test_login_gets_rate_limited_after_repeated_attempts(self, client, test_user):
        # The limiter allows 10/minute per IP; TestClient requests all
        # share the same test client "IP", so this should trip it.
        responses = [
            client.post("/auth/login", json={"email": test_user["email"], "password": "wrong"})
            for _ in range(15)
        ]
        statuses = [r.status_code for r in responses]
        assert 429 in statuses, f"Expected a 429 among {statuses}"
