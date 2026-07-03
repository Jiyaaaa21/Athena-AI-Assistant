"""
Integration tests for backend/api/admin.py.
"""


class TestAdminAuthorization:
    """The most important property of this whole surface: a regular,
    non-admin user must be refused everywhere, not just on some routes."""

    def test_non_admin_cannot_list_users(self, client, auth_headers):
        resp = client.get("/admin/users", headers=auth_headers)
        assert resp.status_code == 403

    def test_non_admin_cannot_deactivate(self, client, auth_headers, test_user):
        resp = client.post(f"/admin/users/{test_user['user_id']}/deactivate", headers=auth_headers)
        assert resp.status_code == 403

    def test_non_admin_cannot_view_audit_log(self, client, auth_headers):
        resp = client.get("/admin/audit-log", headers=auth_headers)
        assert resp.status_code == 403

    def test_non_admin_cannot_view_overview(self, client, auth_headers):
        resp = client.get("/admin/overview", headers=auth_headers)
        assert resp.status_code == 403

    def test_unauthenticated_cannot_list_users(self, client):
        resp = client.get("/admin/users")
        assert resp.status_code == 401

    def test_admin_can_list_users(self, client, admin_headers):
        resp = client.get("/admin/users", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1


class TestAdminEmailsAutoPromotion:
    def test_matching_email_is_promoted_at_signup(self, admin_user):
        # The admin_user fixture itself asserts is_admin=True in the
        # signup response -- this test exists to make that assertion
        # visible as its own named test rather than buried in a fixture.
        assert admin_user["email"] == "admin@test.example.com"

    def test_non_matching_email_is_not_promoted(self, test_user):
        assert test_user["email"] != "admin@test.example.com"

    def test_regular_user_me_shows_is_admin_false(self, client, test_user, auth_headers):
        resp = client.get("/me", headers=auth_headers)
        assert resp.json()["is_admin"] is False

    def test_admin_user_me_shows_is_admin_true(self, client, admin_user, admin_headers):
        resp = client.get("/me", headers=admin_headers)
        assert resp.json()["is_admin"] is True


class TestDeactivation:
    def test_deactivate_locks_the_user_out(self, client, db, admin_headers, test_user, auth_headers):
        resp = client.post(f"/admin/users/{test_user['user_id']}/deactivate", headers=admin_headers)
        assert resp.status_code == 200

        # The deactivated user's existing token must stop working
        # immediately (revoke_all_refresh_tokens_for_user handles
        # refresh; is_active check in get_current_user handles the
        # still-valid access token).
        me_resp = client.get("/me", headers=auth_headers)
        assert me_resp.status_code == 403

    def test_deactivated_user_cannot_log_in(self, client, admin_headers, test_user):
        client.post(f"/admin/users/{test_user['user_id']}/deactivate", headers=admin_headers)
        login_resp = client.post("/auth/login", json={
            "email": test_user["email"], "password": test_user["password"],
        })
        assert login_resp.status_code >= 400

    def test_reactivate_restores_access(self, client, admin_headers, test_user):
        client.post(f"/admin/users/{test_user['user_id']}/deactivate", headers=admin_headers)
        client.post(f"/admin/users/{test_user['user_id']}/reactivate", headers=admin_headers)

        login_resp = client.post("/auth/login", json={
            "email": test_user["email"], "password": test_user["password"],
        })
        assert login_resp.status_code == 200

    def test_admin_cannot_deactivate_self(self, client, admin_headers, admin_user):
        resp = client.post(f"/admin/users/{admin_user['user_id']}/deactivate", headers=admin_headers)
        assert resp.status_code == 400

    def test_deactivate_nonexistent_user_404s(self, client, admin_headers):
        resp = client.post("/admin/users/999999/deactivate", headers=admin_headers)
        assert resp.status_code == 404


class TestRevokeSessions:
    def test_revoke_sessions_invalidates_refresh_token(self, client, admin_headers, test_user):
        resp = client.post(f"/admin/users/{test_user['user_id']}/revoke-sessions", headers=admin_headers)
        assert resp.status_code == 200

        refresh_resp = client.post("/auth/refresh", json={"refresh_token": test_user["refresh_token"]})
        assert refresh_resp.status_code >= 400

    def test_revoke_sessions_does_not_deactivate(self, client, admin_headers, test_user):
        """Revoking sessions and deactivating are deliberately separate
        actions -- forcing a re-login is not the same as locking someone
        out permanently."""
        client.post(f"/admin/users/{test_user['user_id']}/revoke-sessions", headers=admin_headers)
        login_resp = client.post("/auth/login", json={
            "email": test_user["email"], "password": test_user["password"],
        })
        assert login_resp.status_code == 200


class TestAuditLog:
    def test_deactivate_is_logged(self, client, admin_headers, admin_user, test_user):
        client.post(f"/admin/users/{test_user['user_id']}/deactivate", headers=admin_headers)

        log_resp = client.get("/admin/audit-log", headers=admin_headers)
        assert log_resp.status_code == 200
        entries = log_resp.json()["entries"]
        assert any(
            e["action"] == "deactivate_user" and e["target_email"] == test_user["email"]
            for e in entries
        )
        assert any(e["admin_email"] == admin_user["email"] for e in entries)

    def test_revoke_sessions_is_logged(self, client, admin_headers, test_user):
        client.post(f"/admin/users/{test_user['user_id']}/revoke-sessions", headers=admin_headers)
        log_resp = client.get("/admin/audit-log", headers=admin_headers)
        entries = log_resp.json()["entries"]
        assert any(e["action"] == "revoke_sessions" for e in entries)


class TestOverview:
    def test_overview_counts_are_sane(self, client, admin_headers, test_user):
        resp = client.get("/admin/overview", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        # admin_user + test_user = at least 2 users
        assert body["total_users"] >= 2
        assert body["active_users"] >= 1
        assert body["admin_users"] >= 1


class TestUserDetail:
    def test_get_user_detail(self, client, admin_headers, test_user):
        resp = client.get(f"/admin/users/{test_user['user_id']}", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == test_user["email"]
        assert "counts" in body
        assert "usage_today" in body

    def test_get_nonexistent_user_404s(self, client, admin_headers):
        resp = client.get("/admin/users/999999", headers=admin_headers)
        assert resp.status_code == 404