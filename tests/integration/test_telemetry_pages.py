"""Admin-only operational telemetry page contracts."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from project_recovery.admin.shell import AppServices
from project_recovery.app import create_app
from project_recovery.auth.sessions import CurrentUser
from project_recovery.config import Settings


class FakeDatabase:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class FakeAuth:
    async def current_user(self, token: str) -> CurrentUser | None:
        if token not in {"admin", "member"}:
            return None
        return CurrentUser(
            user_id=uuid4(),
            email=f"{token}@example.test",
            roles=("admin",) if token == "admin" else ("user",),
            force_password_change=False,
        )

    async def validate_csrf(self, token: str, csrf: str) -> bool:
        return token in {"admin", "member"} and csrf == "csrf"


class FakeUsers:
    pass


class FakeTelemetry:
    def __init__(self) -> None:
        now = datetime(2026, 8, 12, tzinfo=UTC)
        self.prompt_runs = [
            SimpleNamespace(
                id=uuid4(),
                user_id=uuid4(),
                conversation_id=uuid4(),
                trace_id="trace-safe",
                model="gpt-5.6-terra",
                requested_reasoning_effort="medium",
                effective_reasoning_effort="medium",
                status="completed",
                prompt="password=must-not-render",
                latency_ms=420,
                input_tokens=100,
                cached_tokens=20,
                output_tokens=40,
                total_tokens=140,
                estimated_cost=Decimal("0.000672"),
                started_at=now,
            )
        ]
        self.tool_runs = [
            SimpleNamespace(
                id=uuid4(),
                trace_id="trace-safe",
                tool_name="file_search",
                tool_type="hosted_file_search",
                status="completed",
                duration_ms=25,
                result_count=1,
                result_summary="Found one guide",
                arguments={"authorization": "Bearer must-not-render"},
                output={"results": [{"filename": "guide.pdf"}]},
                created_at=now,
            )
        ]
        self.exceptions = [
            SimpleNamespace(
                id=uuid4(),
                exception_type="RuntimeError",
                request_path="/chat",
                message="api_key=must-not-render",
                occurrence_count=2,
                fingerprint="safe-fingerprint",
                stack_trace="token=must-not-render",
                context={"cookie": "must-not-render", "correlation_id": "corr-safe"},
                first_seen_at=now,
                last_seen_at=now,
            )
        ]
        self.limits: list[int] = []
        self.recorded_exceptions: list[dict[str, object]] = []

    async def list_prompt_runs(self, offset: int, limit: int):
        del offset
        self.limits.append(limit)
        return self.prompt_runs

    async def list_tool_runs(self, offset: int, limit: int):
        del offset
        self.limits.append(limit)
        return self.tool_runs

    async def list_exceptions(self, offset: int, limit: int):
        del offset
        self.limits.append(limit)
        return self.exceptions

    async def usage_summary(self, since: datetime | None):
        del since
        return {
            "overview": {
                "requests": 3,
                "users": 2,
                "conversations": 2,
                "input_tokens": 300,
                "cached_tokens": 50,
                "output_tokens": 120,
                "total_tokens": 420,
                "average_latency_ms": 350,
                "estimated_cost": Decimal("0.004321"),
                "unpriced_count": 1,
            },
            "models": [
                {
                    "model": "gpt-5.6-terra",
                    "requests": 3,
                    "input_tokens": 300,
                    "cached_tokens": 50,
                    "output_tokens": 120,
                    "total_tokens": 420,
                    "estimated_cost": Decimal("0.004321"),
                    "unpriced_count": 1,
                }
            ],
        }

    async def record_exception(self, **values: object) -> None:
        self.recorded_exceptions.append(values)


class FakeChats:
    def __init__(self) -> None:
        now = datetime(2026, 8, 12, tzinfo=UTC)
        self.feedback = [
            SimpleNamespace(
                id=uuid4(),
                user_id=uuid4(),
                conversation_id=uuid4(),
                message_id=uuid4(),
                rating=1,
                comment="Helpful",
                context_snapshot={"password": "must-not-render", "prompt": "Safe prompt"},
                model="gpt-5.6-terra",
                trace_id="trace-safe",
                tool_summary="file_search",
                created_at=now,
            )
        ]
        self.limits: list[int] = []

    async def list_feedback(self, offset: int, limit: int):
        del offset
        self.limits.append(limit)
        return self.feedback


def _client() -> tuple[TestClient, FakeTelemetry, FakeChats]:
    settings = Settings(
        openai_api_key="sk-test",
        openai_vector_store_id="vs-test",
        database_url="postgresql+asyncpg://u:p@example.test/db",
        app_session_secret="application-secret",
        chainlit_auth_secret="chainlit-secret",
        environment="test",
    )
    telemetry = FakeTelemetry()
    chats = FakeChats()
    services = AppServices(
        database=FakeDatabase(),
        auth=FakeAuth(),  # type: ignore[arg-type]
        users=FakeUsers(),  # type: ignore[arg-type]
        telemetry=telemetry,
        chats=chats,
    )
    return TestClient(create_app(settings, services)), telemetry, chats


def test_all_telemetry_pages_are_admin_only_bounded_and_redacted() -> None:
    client, telemetry, chats = _client()
    paths = (
        "/admin/prompt-runs",
        "/admin/chat-feedback",
        "/admin/model-usage?window=30d",
        "/admin/exceptions",
        "/admin/tool-use",
    )

    client.cookies.set("project_recovery_session", "member")
    for path in paths:
        assert client.get(path).status_code == 403

    client.cookies.set("project_recovery_session", "admin")
    responses = [client.get(path) for path in paths]

    assert all(response.status_code == 200 for response in responses)
    combined = "\n".join(response.text for response in responses)
    assert "trace-safe" in combined
    assert "gpt-5.6-terra" in combined
    assert "0.004321" in combined
    assert "must-not-render" not in combined
    assert "[REDACTED]" in combined
    assert all(limit <= 100 for limit in telemetry.limits + chats.limits)
    assert client.get("/admin/model-usage?window=invalid").status_code == 400
    assert client.get("/admin/prompt-runs/export").status_code in {404, 422}


def test_activity_pages_keep_exact_timestamps_and_support_bounded_navigation() -> None:
    """Operational records stay compact while exact identifiers remain available on demand."""

    client, telemetry, _ = _client()
    client.cookies.set("project_recovery_session", "admin")

    prompt_response = client.get("/admin/prompt-runs?offset=100&limit=100")
    tool_response = client.get("/admin/tool-use?offset=100&limit=100")

    assert prompt_response.status_code == tool_response.status_code == 200
    for content in (prompt_response.text, tool_response.text):
        assert '<time datetime="2026-08-12T00:00:00+00:00">' in content
        assert 'data-copy-value="trace-safe"' in content
        assert "Previous" in content
        assert "limit=100" in content
    assert telemetry.limits[-2:] == [101, 101]


def test_unhandled_exception_is_recorded_without_leaking_the_api_key() -> None:
    client, telemetry, _ = _client()

    @client.app.get("/test-only-failure")
    async def fail() -> None:
        raise RuntimeError("api_key=sk-test")

    client = TestClient(client.app, raise_server_exceptions=False)
    response = client.get("/test-only-failure")

    assert response.status_code == 500
    assert telemetry.recorded_exceptions
    stored = str(telemetry.recorded_exceptions[0])
    assert "sk-test" not in stored
    assert "[REDACTED]" in stored
