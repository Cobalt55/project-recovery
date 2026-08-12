"""Opt-in live smoke test for the OpenAI Agents SDK runtime."""

from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from openai import AsyncOpenAI

from project_recovery.agent_runtime import AgentRuntime
from project_recovery.config import Settings

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OPENAI_LIVE_TESTS") != "1",
    reason="set RUN_OPENAI_LIVE_TESTS=1 for the disposable provider smoke test",
)


@pytest.mark.asyncio
async def test_live_runtime_creates_conversation_response_and_trace() -> None:
    """Create and clean up one disposable provider Conversation."""

    api_key = os.environ.get("OPENAI_API_KEY")
    vector_store_id = os.environ.get("OPENAI_VECTOR_STORE_ID")
    if not api_key or not vector_store_id:
        pytest.skip("OPENAI_API_KEY and OPENAI_VECTOR_STORE_ID are required")

    class LiveChats:
        def __init__(self) -> None:
            self.provider_conversation_id: str | None = None
            self.conversation_id = uuid4()

        async def create_thread(self, **kwargs: object) -> SimpleNamespace:
            self.provider_conversation_id = str(kwargs["openai_conversation_id"])
            return SimpleNamespace(id=self.conversation_id, **kwargs)

        async def append_message(self, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(id=uuid4(), **kwargs)

    class LiveTelemetry:
        async def start_prompt_run(self, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(id=uuid4(), **kwargs)

        async def finish_prompt_run(self, prompt_run_id: object, **kwargs: object) -> None:
            del prompt_run_id, kwargs

        async def record_tool_run(self, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(id=uuid4(), **kwargs)

    settings = Settings(
        openai_api_key=api_key,
        openai_vector_store_id=vector_store_id,
        database_url="postgresql+asyncpg://unused:unused@localhost/unused",
        app_session_secret="live-test-session-placeholder",
        chainlit_auth_secret="live-test-chainlit-placeholder",
        environment="live-test",
    )
    client = AsyncOpenAI(api_key=api_key)
    chats = LiveChats()
    runtime = AgentRuntime(
        settings=settings,
        chat_repository=chats,
        telemetry_repository=LiveTelemetry(),
        openai_client=client,
    )
    conversation = None
    try:
        conversation = await runtime.start_conversation(
            user_id=uuid4(), chainlit_thread_id=f"live-{uuid4()}"
        )
        summary = await runtime.stream_turn(
            conversation=conversation,
            user_id=uuid4(),
            prompt="Reply with exactly: live runtime ready",
        )
        assert summary.final_output
        assert summary.provider_response_id
        assert summary.trace_id.startswith("trace_")
    finally:
        if chats.provider_conversation_id:
            await client.conversations.delete(chats.provider_conversation_id)
        await client.close()
