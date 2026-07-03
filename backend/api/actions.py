"""
Integration tests for backend/api/actions.py.

TestRouterIsMounted exists specifically because this router was fully
built but never actually registered in main.py for an unknown period --
its own docstring claimed otherwise. A test that hits the real app
(not just imports the router module in isolation) is the only kind of
test that would have caught that class of bug.
"""


class TestRouterIsMounted:
    def test_list_actions_endpoint_exists(self, client, auth_headers):
        """Would 404 (or worse, hang on a route that doesn't exist) if
        the router weren't actually mounted in main.py -- this is the
        regression guard for that exact bug."""
        resp = client.get("/actions", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_requires_auth(self, client):
        resp = client.get("/actions")
        assert resp.status_code == 401


class TestActionCrud:
    def test_create_action(self, client, auth_headers):
        resp = client.post("/actions", json={
            "name": "Test Webhook",
            "webhook_url": "https://example.com/webhook",
        }, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Test Webhook"
        assert body["enabled"] is True

    def test_created_action_appears_in_list(self, client, auth_headers):
        client.post("/actions", json={
            "name": "Test Webhook", "webhook_url": "https://example.com/webhook",
        }, headers=auth_headers)
        resp = client.get("/actions", headers=auth_headers)
        assert len(resp.json()) == 1

    def test_rejects_non_http_webhook_url(self, client, auth_headers):
        resp = client.post("/actions", json={
            "name": "Bad", "webhook_url": "ftp://example.com/x",
        }, headers=auth_headers)
        assert resp.status_code == 422

    def test_rejects_duplicate_name(self, client, auth_headers):
        client.post("/actions", json={
            "name": "Dup", "webhook_url": "https://example.com/a",
        }, headers=auth_headers)
        resp = client.post("/actions", json={
            "name": "Dup", "webhook_url": "https://example.com/b",
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_update_action(self, client, auth_headers):
        created = client.post("/actions", json={
            "name": "Original", "webhook_url": "https://example.com/a",
        }, headers=auth_headers).json()
        resp = client.put(f"/actions/{created['id']}", json={
            "name": "Renamed", "webhook_url": "https://example.com/a", "enabled": False,
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"
        assert resp.json()["enabled"] is False

    def test_delete_action(self, client, auth_headers):
        created = client.post("/actions", json={
            "name": "ToDelete", "webhook_url": "https://example.com/a",
        }, headers=auth_headers).json()
        resp = client.delete(f"/actions/{created['id']}", headers=auth_headers)
        assert resp.status_code == 200
        assert client.get("/actions", headers=auth_headers).json() == []

    def test_actions_are_scoped_per_user(self, client, auth_headers, admin_headers):
        client.post("/actions", json={
            "name": "Mine", "webhook_url": "https://example.com/a",
        }, headers=auth_headers)
        # A different user must not see it.
        resp = client.get("/actions", headers=admin_headers)
        assert resp.json() == []


class TestActionSSRFGuard:
    def test_blocks_localhost_webhook(self, client, auth_headers):
        created = client.post("/actions", json={
            "name": "Local", "webhook_url": "http://localhost:8000/x",
        }, headers=auth_headers).json()
        resp = client.post(f"/actions/{created['id']}/test", headers=auth_headers)
        assert resp.status_code == 200  # the trigger endpoint itself succeeds...
        assert "blocked for safety" in resp.json()["result"]  # ...but refuses to actually call it

    def test_blocks_private_ip_webhook(self, client, auth_headers):
        created = client.post("/actions", json={
            "name": "Private", "webhook_url": "http://192.168.1.1/x",
        }, headers=auth_headers).json()
        resp = client.post(f"/actions/{created['id']}/test", headers=auth_headers)
        assert "blocked for safety" in resp.json()["result"]