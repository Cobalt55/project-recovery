"""Knowledge routes remain admin-only, CSRF-protected, and bounded."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from project_recovery.admin.shell import AppServices
from project_recovery.app import create_app
from project_recovery.auth.sessions import CurrentUser
from project_recovery.config import Settings


class FakeDatabase:
    async def ping(self):
        return True

    async def close(self):
        return None


class FakeAuth:
    async def current_user(self, token):
        if token not in {"admin", "member"}:
            return None
        return CurrentUser(
            user_id=uuid4(),
            email=f"{token}@example.test",
            roles=("admin",) if token == "admin" else ("user",),
            force_password_change=False,
        )

    async def validate_csrf(self, token, csrf):
        return token == "admin" and csrf == "csrf"


class FakeKnowledge:
    def __init__(self):
        self.resource = SimpleNamespace(
            id=uuid4(),
            name="guide.txt",
            content_type="text/plain",
            byte_size=5,
            category="Guides",
            description="Safe guide",
            status="ready",
            error_message=None,
            updated_at=datetime(2026, 8, 12, tzinfo=UTC),
        )
        self.queued = []
        self.deleted = []

    async def recover_stale(self):
        return 0

    async def list_page(self, **kwargs):
        assert kwargs["limit"] <= 100
        return [self.resource]

    async def queue_upload(self, **kwargs):
        self.queued.append(kwargs)
        self.resource.status = "queued"
        return self.resource

    async def ingest(self, resource_id):
        self.resource.status = "ready"

    async def retry(self, resource_id):
        return False

    async def delete(self, resource_id):
        self.deleted.append(resource_id)
        return True


def test_knowledge_page_upload_and_delete_controls() -> None:
    knowledge = FakeKnowledge()
    settings = Settings(
        openai_api_key="sk-test",
        openai_vector_store_id="vs-test",
        database_url="postgresql+asyncpg://u:p@example.test/db",
        app_session_secret="app-secret",
        chainlit_auth_secret="chat-secret",
        environment="test",
    )
    services = AppServices(
        database=FakeDatabase(),
        auth=FakeAuth(),  # type: ignore[arg-type]
        users=SimpleNamespace(),  # type: ignore[arg-type]
        knowledge=knowledge,
    )
    client = TestClient(create_app(settings, services))
    client.cookies.set("project_recovery_session", "member")
    assert client.get("/admin/knowledge").status_code == 403

    client.cookies.set("project_recovery_session", "admin")
    page = client.get("/admin/knowledge")
    assert page.status_code == 200
    assert "Knowledge" in page.text
    assert "Organizational Knowledge" not in page.text
    assert client.get("/admin/knowledge/status").status_code == 200
    assert (
        client.post(
            "/admin/knowledge",
            files={"upload": ("guide.txt", b"safe", "text/plain")},
            data={"csrf_token": "wrong"},
        ).status_code
        == 403
    )
    uploaded = client.post(
        "/admin/knowledge",
        files={"upload": ("guide.txt", b"safe", "text/plain")},
        data={"csrf_token": "csrf", "category": "Guides"},
    )
    assert uploaded.status_code == 202
    assert knowledge.queued[0]["content"] == b"safe"
    assert (
        client.post(
            f"/admin/knowledge/{knowledge.resource.id}/delete",
            data={"csrf_token": "csrf"},
        ).status_code
        == 400
    )
    deleted = client.post(
        f"/admin/knowledge/{knowledge.resource.id}/delete",
        data={"csrf_token": "csrf", "confirm": "delete"},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert knowledge.deleted == [knowledge.resource.id]
