"""
Integration test for DELETE /profile/me (backend/api/profile.py).

Creates real data across both directly user_id-owned tables (via the
actual API, so this also incidentally exercises those endpoints) and
the three indirectly-scoped tables that needed special handling in the
deletion code (ConversationMessage, ProjectLink, ReminderFired), then
verifies every single row is actually gone after deletion -- not just
that the endpoint returned 200.
"""

from datetime import datetime, timezone

from backend.database.models import (
    User, Note, Reminder, ReminderFired, Goal, Project, ProjectLink,
    Conversation, ConversationMessage, Document,
)


class TestAccountDeletionRequiresPassword:
    def test_wrong_password_rejected(self, client, test_user, auth_headers):
        resp = client.request(
            "DELETE", "/profile/me",
            headers=auth_headers,
            json={"password": "totally-wrong-password"},
        )
        assert resp.status_code == 400

    def test_wrong_password_deletes_nothing(self, client, db, test_user, auth_headers):
        client.request(
            "DELETE", "/profile/me",
            headers=auth_headers,
            json={"password": "totally-wrong-password"},
        )
        # The account must still exist after a failed deletion attempt.
        assert db.query(User).filter(User.id == test_user["user_id"]).first() is not None

    def test_requires_auth(self, client):
        resp = client.request("DELETE", "/profile/me", json={"password": "whatever"})
        assert resp.status_code == 401


class TestAccountDeletionCascade:
    def test_full_cascade_deletes_everything(self, client, db, test_user, auth_headers):
        uid = test_user["user_id"]

        # ── Directly user_id-owned tables, created via the real API ──
        note_resp = client.post("/notes", json={"title": "Test note", "body": "content"}, headers=auth_headers)
        assert note_resp.status_code == 200, note_resp.text

        reminder_resp = client.post(
            "/reminders",
            json={"title": "Test reminder", "dueAt": "2026-12-31T10:00:00Z"},
            headers=auth_headers,
        )
        assert reminder_resp.status_code == 200, reminder_resp.text
        reminder_id = reminder_resp.json()["id"]

        goal_resp = client.post("/goals", json={"title": "Test goal"}, headers=auth_headers)
        assert goal_resp.status_code == 200, goal_resp.text

        # ── Indirectly-scoped tables (no user_id column of their own) --
        # inserted directly, since these are the trickiest part of the
        # deletion logic to get right and the ones most worth verifying
        # explicitly rather than trusting API coverage alone.
        reminder_row = db.query(Reminder).filter(Reminder.id == reminder_id).first()
        db.add(ReminderFired(reminder_id=reminder_row.id, fired_at=datetime.now(timezone.utc)))

        conversation = Conversation(user_id=uid, title="Test conversation", created_at=datetime.now(timezone.utc))
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        db.add(ConversationMessage(conversation_id=conversation.id, role="user", content="hello", created_at=datetime.now(timezone.utc)))

        project = Project(user_id=uid, name="Test project", status="active")
        db.add(project)
        db.commit()
        db.refresh(project)
        db.add(ProjectLink(project_id=project.id, entity_type="note", entity_id=1))

        document = Document(
            user_id=uid, filename="test.pdf", size_bytes=100,
            status="processed", uploaded_at=datetime.now(timezone.utc),
            file_data=b"%PDF-1.3 fake content",
        )
        db.add(document)

        db.commit()

        # Capture plain ID values now, before deletion -- re-accessing
        # attributes on these ORM objects (conversation.id, project.id)
        # AFTER their rows are deleted and the session is expired would
        # trigger a reload attempt against a row that no longer exists
        # (ObjectDeletedError), rather than testing anything meaningful.
        conversation_id = conversation.id
        project_id = project.id

        # Sanity check: everything actually got created before we try to
        # delete it -- otherwise this test would "pass" even if none of
        # this setup worked.
        assert db.query(Note).filter(Note.user_id == uid).count() == 1
        assert db.query(Reminder).filter(Reminder.user_id == uid).count() == 1
        assert db.query(Goal).filter(Goal.user_id == uid).count() == 1
        assert db.query(ReminderFired).filter(ReminderFired.reminder_id == reminder_id).count() == 1
        assert db.query(Conversation).filter(Conversation.user_id == uid).count() == 1
        assert db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).count() == 1
        assert db.query(Project).filter(Project.user_id == uid).count() == 1
        assert db.query(ProjectLink).filter(ProjectLink.project_id == project_id).count() == 1
        assert db.query(Document).filter(Document.user_id == uid).count() == 1

        # ── The actual deletion ──
        resp = client.request(
            "DELETE", "/profile/me",
            headers=auth_headers,
            json={"password": test_user["password"]},
        )
        assert resp.status_code == 200, resp.text

        # ── Verify every single row is actually gone ──
        db.expire_all()
        assert db.query(User).filter(User.id == uid).first() is None
        assert db.query(Note).filter(Note.user_id == uid).count() == 0
        assert db.query(Reminder).filter(Reminder.user_id == uid).count() == 0
        assert db.query(Goal).filter(Goal.user_id == uid).count() == 0
        assert db.query(ReminderFired).filter(ReminderFired.reminder_id == reminder_id).count() == 0
        assert db.query(Conversation).filter(Conversation.user_id == uid).count() == 0
        assert db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).count() == 0
        assert db.query(Project).filter(Project.user_id == uid).count() == 0
        assert db.query(ProjectLink).filter(ProjectLink.project_id == project_id).count() == 0
        assert db.query(Document).filter(Document.user_id == uid).count() == 0

    def test_deleted_account_token_stops_working(self, client, db, test_user, auth_headers):
        """Verifies the claim made in profile.py's docstring: since
        get_current_user() re-queries the DB on every request, a still
        cryptographically-valid JWT for a deleted user must immediately
        stop working -- not just eventually, on next expiry."""
        client.request(
            "DELETE", "/profile/me",
            headers=auth_headers,
            json={"password": test_user["password"]},
        )
        resp = client.get("/me", headers=auth_headers)
        assert resp.status_code == 401

    def test_deletion_does_not_affect_other_users(self, client, db, auth_headers, test_user):
        """One user deleting their account must never touch another
        user's data -- the classic multi-tenant isolation bug to guard
        against explicitly, not just assume the WHERE clauses are right."""
        other_resp = client.post("/auth/signup", json={
            "name": "Other User", "email": "other@example.com", "password": "other-password-123",
        })
        other_token = other_resp.json()["tokens"]["access_token"]
        other_headers = {"Authorization": f"Bearer {other_token}"}

        client.post("/notes", json={"title": "Other user's note", "body": "x"}, headers=other_headers)

        # Delete the FIRST user's account.
        resp = client.request(
            "DELETE", "/profile/me",
            headers=auth_headers,
            json={"password": test_user["password"]},
        )
        assert resp.status_code == 200

        # The other user's account and data must be completely untouched.
        me_resp = client.get("/me", headers=other_headers)
        assert me_resp.status_code == 200

        notes_resp = client.get("/notes", headers=other_headers)
        assert notes_resp.status_code == 200
        assert len(notes_resp.json()) == 1
