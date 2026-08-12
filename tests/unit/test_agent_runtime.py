"""Behavior tests for the OpenAI Agents SDK runtime boundary."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from project_recovery.agent_runtime import AgentEvent, AgentRuntime
from project_recovery.config import Settings
from project_recovery.costs import calculate_cost


def _settings() -> Settings:
    return Settings(
        openai_api_key="sk-test-secret",
        openai_vector_store_id="vs_only",
        database_url="postgresql+asyncpg://user:password@example.test/db",
        app_session_secret="session-secret",
        chainlit_auth_secret="chainlit-secret",
        environment="test",
    )


class FakeConversations:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(id="conv_provider_123")


class FakeOpenAI:
    def __init__(self) -> None:
        self.conversations = FakeConversations()


class FakeChatRepository:
    def __init__(self) -> None:
        self.thread_id = uuid4()
        self.created: list[dict[str, object]] = []
        self.messages: list[dict[str, object]] = []

    async def create_thread(self, **kwargs: object) -> SimpleNamespace:
        self.created.append(kwargs)
        return SimpleNamespace(id=self.thread_id, **kwargs)

    async def append_message(self, **kwargs: object) -> SimpleNamespace:
        self.messages.append(kwargs)
        return SimpleNamespace(id=uuid4(), **kwargs)


class FakeTelemetryRepository:
    def __init__(self) -> None:
        self.prompt_run_id = uuid4()
        self.started: list[dict[str, object]] = []
        self.finished: list[tuple[UUID, dict[str, object]]] = []
        self.tools: list[dict[str, object]] = []

    async def start_prompt_run(self, **kwargs: object) -> SimpleNamespace:
        self.started.append(kwargs)
        return SimpleNamespace(id=self.prompt_run_id)

    async def finish_prompt_run(self, prompt_run_id: UUID, **kwargs: object) -> None:
        self.finished.append((prompt_run_id, kwargs))

    async def record_tool_run(self, **kwargs: object) -> SimpleNamespace:
        self.tools.append(kwargs)
        return SimpleNamespace(id=uuid4())


class FakeSession:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


@dataclass
class FakeStreamResult:
    events: list[object]
    final_output: str = "Grounded answer"
    last_response_id: str | None = "resp_123"
    run_loop_exception: Exception | None = None

    def __post_init__(self) -> None:
        self.trace = SimpleNamespace(trace_id="trace_sdk_value")
        self.context_wrapper = SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=100,
                input_tokens_details=SimpleNamespace(cached_tokens=25),
                output_tokens=40,
                total_tokens=140,
            )
        )

    async def stream_events(self):
        for event in self.events:
            yield event


class FakeRunner:
    def __init__(self, result: FakeStreamResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def run_streamed(self, agent: object, input: str, **kwargs: object) -> FakeStreamResult:
        self.calls.append({"agent": agent, "input": input, **kwargs})
        return self.result


class CapturingSpan:
    def __init__(self, name: str, data: dict[str, object] | None) -> None:
        self.name = name
        self.data = data

    def set_output(self, output: object) -> None:
        del output

    def set_error(self, error: object) -> None:
        del error


class SpanRecorder:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.parents: list[object | None] = []

    @contextmanager
    def __call__(
        self,
        name: str,
        data: dict[str, object] | None = None,
        parent: object | None = None,
    ):
        self.names.append(name)
        self.parents.append(parent)
        yield CapturingSpan(name, data)


def _text_event(delta: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="raw_response_event",
        data=SimpleNamespace(type="response.output_text.delta", delta=delta),
    )


def _file_search_event() -> SimpleNamespace:
    raw_item = SimpleNamespace(
        id="fs_1",
        type="file_search_call",
        status="completed",
        queries=["retention policy"],
        results=[
            SimpleNamespace(
                file_id="file_1",
                filename="guide.pdf",
                score=0.91,
                text="Relevant excerpt",
            )
        ],
    )
    return SimpleNamespace(
        type="run_item_stream_event",
        name="tool_called",
        item=SimpleNamespace(raw_item=raw_item),
    )


@pytest.mark.asyncio
async def test_start_conversation_uses_provider_conversation_and_persists_id() -> None:
    client = FakeOpenAI()
    chats = FakeChatRepository()
    runtime = AgentRuntime(
        settings=_settings(),
        chat_repository=chats,
        telemetry_repository=FakeTelemetryRepository(),
        openai_client=client,
    )

    conversation = await runtime.start_conversation(
        user_id=uuid4(),
        chainlit_thread_id="thread_123",
    )

    assert client.conversations.calls == [{"items": []}]
    assert chats.created[0]["openai_conversation_id"] == "conv_provider_123"
    assert chats.created[0]["settings"] == {
        "model": "gpt-5.6-terra",
        "reasoning_effort": "medium",
    }
    assert conversation.id == chats.thread_id


@pytest.mark.asyncio
async def test_stream_turn_configures_agent_trace_session_usage_and_file_search() -> None:
    events = [_text_event("Grounded "), _text_event("answer"), _file_search_event()]
    runner = FakeRunner(FakeStreamResult(events))
    client = FakeOpenAI()
    chats = FakeChatRepository()
    telemetry = FakeTelemetryRepository()
    spans = SpanRecorder()
    emitted: list[AgentEvent] = []
    runtime = AgentRuntime(
        settings=_settings(),
        chat_repository=chats,
        telemetry_repository=telemetry,
        openai_client=client,
        runner=runner,
        session_factory=FakeSession,
        span_factory=spans,
        trace_id_factory=lambda: "trace_requested_123",
    )
    conversation = SimpleNamespace(
        id=chats.thread_id,
        openai_conversation_id="conv_provider_123",
    )

    summary = await runtime.stream_turn(
        conversation=conversation,
        user_id=uuid4(),
        prompt="What is the retention policy?",
        emit=emitted.append,
    )

    assert [event.delta for event in emitted if event.kind == "text_delta"] == [
        "Grounded ",
        "answer",
    ]
    call = runner.calls[0]
    agent = call["agent"]
    assert agent.model == "gpt-5.6-terra"
    assert agent.model_settings.reasoning.effort == "medium"
    assert agent.model_settings.extra_args == {
        "safety_identifier": str(telemetry.started[0]["user_id"])
    }
    assert agent.tools[0].vector_store_ids == ["vs_only"]
    assert agent.tools[0].max_num_results == 5
    run_config = call["run_config"]
    assert run_config.tracing_disabled is False
    assert run_config.trace_include_sensitive_data is False
    assert run_config.workflow_name == "Project Recovery Chat"
    assert run_config.trace_id == "trace_requested_123"
    assert run_config.group_id == str(conversation.id)
    assert run_config.trace_metadata == {
        "conversation_id": str(conversation.id),
        "user_id": str(telemetry.started[0]["user_id"]),
        "model": "gpt-5.6-terra",
        "environment": "test",
    }
    assert "email" not in str(run_config.trace_metadata).lower()
    assert "retention policy" not in str(run_config.trace_metadata).lower()
    assert FakeSession.calls[-1] == {
        "conversation_id": "conv_provider_123",
        "openai_client": client,
    }
    assert "conversation_id" not in call
    assert summary.final_output == "Grounded answer"
    assert summary.provider_response_id == "resp_123"
    assert summary.trace_id == "trace_requested_123"
    assert (summary.input_tokens, summary.cached_tokens, summary.output_tokens) == (100, 25, 40)
    assert summary.total_tokens == 140
    assert summary.estimated_cost_usd == Decimal("0.000635")
    assert telemetry.tools[0]["tool_name"] == "file_search"
    assert telemetry.tools[0]["result_count"] == 1
    assert telemetry.tools[0]["arguments"] == {"queries": ["retention policy"]}
    assert telemetry.finished[-1][1]["status"] == "completed"
    assert {message["role"] for message in chats.messages} == {"user", "assistant"}
    assert spans.names == [
        "application_persistence",
        "knowledge_lookup_normalization",
        "application_persistence",
    ]
    assert spans.parents == [runner.result.trace, runner.result.trace, runner.result.trace]


@pytest.mark.asyncio
async def test_invalid_policy_is_rejected_before_provider_or_runner() -> None:
    client = FakeOpenAI()
    runner = FakeRunner(FakeStreamResult([]))
    runtime = AgentRuntime(
        settings=_settings(),
        chat_repository=FakeChatRepository(),
        telemetry_repository=FakeTelemetryRepository(),
        openai_client=client,
        runner=runner,
        session_factory=FakeSession,
    )
    conversation = SimpleNamespace(id=uuid4(), openai_conversation_id="conv_provider_123")

    with pytest.raises(ValueError, match="model"):
        await runtime.stream_turn(
            conversation=conversation,
            user_id=uuid4(),
            prompt="hello",
            model="not-a-model",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="reasoning"):
        await runtime.stream_turn(
            conversation=conversation,
            user_id=uuid4(),
            prompt="hello",
            reasoning_effort="xhigh",  # type: ignore[arg-type]
        )

    assert client.conversations.calls == []
    assert runner.calls == []


@pytest.mark.asyncio
async def test_provider_failure_finishes_prompt_run_as_failed() -> None:
    provider_error = RuntimeError("provider down sk-test-secret")
    runner = FakeRunner(FakeStreamResult([], run_loop_exception=provider_error))
    telemetry = FakeTelemetryRepository()
    spans = SpanRecorder()
    runtime = AgentRuntime(
        settings=_settings(),
        chat_repository=FakeChatRepository(),
        telemetry_repository=telemetry,
        openai_client=FakeOpenAI(),
        runner=runner,
        session_factory=FakeSession,
        span_factory=spans,
        trace_id_factory=lambda: "trace_failure",
    )

    with pytest.raises(RuntimeError, match="provider down"):
        await runtime.stream_turn(
            conversation=SimpleNamespace(id=uuid4(), openai_conversation_id="conv_provider_123"),
            user_id=uuid4(),
            prompt="hello",
        )

    finish = telemetry.finished[-1][1]
    assert finish["status"] == "failed"
    assert "sk-test-secret" not in str(finish["error_message"])


def test_costs_use_current_model_rates_and_unknowns_are_unpriced() -> None:
    assert calculate_cost("gpt-5.6-luna", 100, 25, 40) == Decimal("0.000064")
    assert calculate_cost("gpt-5.6-terra", 100, 25, 40) == Decimal("0.000635")
    assert calculate_cost("gpt-5.6-sol", 100, 25, 40) == Decimal("0.001588")
    assert calculate_cost("unknown", 100, 25, 40) is None
    assert calculate_cost("gpt-5.6-terra", 10, 11, 1) is None
