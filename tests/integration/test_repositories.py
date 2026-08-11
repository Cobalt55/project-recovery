"""PostgreSQL integration coverage for the persistence repository boundaries."""

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from project_recovery.db import Database
from project_recovery.repositories.chat import ChatRepository
from project_recovery.repositories.knowledge import KnowledgeRepository
from project_recovery.repositories.telemetry import TelemetryRepository
from project_recovery.repositories.users import UserRepository

POSTGRES_IMAGE = "postgres:16"
POSTGRES_PASSWORD = "test-password-only"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Run the suite against one disposable PostgreSQL 16 database."""
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for PostgreSQL integration tests")

    port = _free_port()
    name = f"project-recovery-test-{uuid4().hex}"
    start = subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            "--publish",
            f"127.0.0.1:{port}:5432",
            "--env",
            "POSTGRES_DB=project_recovery_test",
            "--env",
            "POSTGRES_USER=project_recovery",
            "--env",
            f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
            POSTGRES_IMAGE,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    container_id = start.stdout.strip()
    url = (
        "postgresql+asyncpg://project_recovery:"
        f"{POSTGRES_PASSWORD}@127.0.0.1:{port}/project_recovery_test"
    )

    async def wait_for_postgres() -> None:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                connection = await asyncpg.connect(
                    host="127.0.0.1",
                    port=port,
                    user="project_recovery",
                    password=POSTGRES_PASSWORD,
                    database="project_recovery_test",
                )
            except (OSError, asyncpg.PostgresError):
                await asyncio.sleep(0.5)
            else:
                await connection.close()
                return
        raise RuntimeError("disposable PostgreSQL container did not become ready")

    try:
        asyncio.run(wait_for_postgres())
        environment = os.environ | {"DATABASE_URL": url}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
            env=environment,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "base"],
            check=True,
            env=environment,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
            env=environment,
            capture_output=True,
            text=True,
        )
        yield url
    finally:
        subprocess.run(["docker", "stop", container_id], check=False, capture_output=True)


@pytest_asyncio.fixture
async def database(postgres_url: str) -> AsyncIterator[Database]:
    database = Database(postgres_url)
    try:
        yield database
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_repositories_persist_and_retrieve_related_records(database: Database):
    """A complete chat interaction remains queryable through its repositories."""
    users = UserRepository(database.session())
    chats = ChatRepository(database.session())
    telemetry = TelemetryRepository(database.session())
    knowledge = KnowledgeRepository(database.session())

    user = await users.create(
        email="operator@example.test",
        display_name="Operator",
        password_hash="hash",
        roles=["admin"],
        force_password_change=True,
    )
    conversation = await chats.create_thread(
        user_id=user.id,
        chainlit_thread_id="thread-1",
        openai_conversation_id="conversation-1",
        settings={"model": "gpt-5.6-terra"},
    )
    message = await chats.append_message(
        conversation_id=conversation.id,
        role="user",
        content="What changed?",
        provider_response_id=None,
    )
    prompt_run = await telemetry.start_prompt_run(
        user_id=user.id,
        conversation_id=conversation.id,
        trace_id="trace-1",
        model="gpt-5.6-terra",
        requested_reasoning_effort="medium",
        effective_reasoning_effort="medium",
        prompt="What changed?",
    )
    await telemetry.finish_prompt_run(
        prompt_run.id,
        status="completed",
        latency_ms=42,
        input_tokens=4,
        cached_tokens=0,
        output_tokens=7,
        total_tokens=11,
        estimated_cost="0.01",
    )
    tool_run = await telemetry.record_tool_run(
        user_id=user.id,
        conversation_id=conversation.id,
        prompt_run_id=prompt_run.id,
        trace_id="trace-1",
        tool_name="file_search",
        tool_type="hosted",
        status="completed",
        duration_ms=3,
        result_count=1,
        result_summary="One matching resource",
        arguments={"query": "changed"},
        output={"Authorization": "Bearer must-not-persist"},
    )
    feedback = await chats.record_feedback(
        user_id=user.id,
        conversation_id=conversation.id,
        message_id=message.id,
        rating=1,
        comment="Helpful",
        context_snapshot={"prompt": "What changed?"},
        model="gpt-5.6-terra",
        trace_id="trace-1",
        tool_summary="file_search",
    )
    exception = await telemetry.record_exception(
        request_path="/chat?token=must-not-persist",
        user_id=user.id,
        exception_type="RuntimeError",
        message="unexpected failure",
        stack_trace="traceback",
        context={"authorization": "Bearer must-not-persist"},
    )
    resource = await knowledge.create_queued(
        name="guide.md",
        content_type="text/markdown",
        byte_size=42,
        category="Guides",
        description="A short guide",
        metadata={"source": "upload"},
    )

    assert (await users.get_by_email("operator@example.test")).id == user.id
    assert [thread.id for thread in await chats.list_user_threads(user.id, 0, 10)] == [
        conversation.id
    ]
    assert (await chats.get_message(message.id)).content == "What changed?"
    assert (await telemetry.get_prompt_run(prompt_run.id)).status == "completed"
    stored_tool_run = await telemetry.get_tool_run(tool_run.id)
    assert stored_tool_run.output["Authorization"] == "[REDACTED]"
    assert (await chats.get_feedback(feedback.id)).rating == 1
    stored_exception = await telemetry.get_exception(exception.id)
    assert stored_exception.context["authorization"] == "[REDACTED]"
    assert stored_exception.request_path == "/chat"
    assert (await knowledge.get(resource.id)).status == "queued"


@pytest.mark.asyncio
async def test_knowledge_transition_requires_the_expected_current_status(database: Database):
    """Concurrent ingestion workers cannot overwrite an already-transitioned resource."""
    knowledge = KnowledgeRepository(database.session())
    resource = await knowledge.create_queued(
        name="reference.txt",
        content_type="text/plain",
        byte_size=2,
        category=None,
        description=None,
        metadata={},
    )

    transitioned = await knowledge.transition(resource.id, "queued", "processing")
    stale_transition = await knowledge.transition(resource.id, "queued", "ready")

    assert transitioned is True
    assert stale_transition is False
    assert (await knowledge.get(resource.id)).status == "processing"
