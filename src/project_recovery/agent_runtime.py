"""OpenAI Agents SDK runtime with durable Conversations and linked telemetry."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from time import monotonic
from types import TracebackType
from typing import Any, Protocol, cast
from uuid import UUID

from agents import (
    Agent,
    FileSearchTool,
    ModelSettings,
    OpenAIConversationsSession,
    RunConfig,
    Runner,
    custom_span,
    gen_trace_id,
)
from openai import AsyncOpenAI
from openai.types.shared import Reasoning

from project_recovery.config import (
    ALLOWED_MODELS,
    ALLOWED_REASONING_EFFORTS,
    ModelId,
    ReasoningEffort,
    Settings,
)
from project_recovery.costs import calculate_cost
from project_recovery.repositories._safety import redact_text

GENERIC_ASSISTANT_INSTRUCTIONS = """You are the Project Recovery Assistant.
Be concise, neutral, and helpful. Use shared Knowledge when it is relevant.
Distinguish sourced facts from inference, and say when the available material
does not support a confident answer. Never invent customer or organization context.
"""


class ConversationLike(Protocol):
    """Application conversation fields required by the runtime."""

    id: UUID
    openai_conversation_id: str


class PromptRunLike(Protocol):
    """Prompt-run identity required after telemetry creation."""

    id: UUID


class ChatRepositoryLike(Protocol):
    async def create_thread(self, **kwargs: object) -> ConversationLike: ...

    async def append_message(self, **kwargs: object) -> object: ...


class TelemetryRepositoryLike(Protocol):
    async def start_prompt_run(self, **kwargs: object) -> PromptRunLike: ...

    async def finish_prompt_run(self, prompt_run_id: UUID, **kwargs: object) -> object | None: ...

    async def record_tool_run(self, **kwargs: object) -> object: ...


class SpanLike(Protocol):
    def __enter__(self) -> object: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


EmitCallback = Callable[["AgentEvent"], object | Awaitable[object]]
SpanFactory = Callable[..., SpanLike]


@dataclass(frozen=True)
class AgentEvent:
    """A provider-independent event suitable for the Chainlit adapter."""

    kind: str
    delta: str | None = None
    data: dict[str, object] | None = None


@dataclass(frozen=True)
class RunSummary:
    """Normalized completed-run result."""

    final_output: str
    provider_response_id: str | None
    trace_id: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: Decimal | None


class AgentRuntime:
    """Run one focused agent while linking provider and application state."""

    def __init__(
        self,
        *,
        settings: Settings,
        chat_repository: ChatRepositoryLike,
        telemetry_repository: TelemetryRepositoryLike,
        openai_client: Any | None = None,
        runner: Any = Runner,
        session_factory: Any = OpenAIConversationsSession,
        span_factory: SpanFactory = custom_span,
        trace_id_factory: Callable[[], str] = gen_trace_id,
    ) -> None:
        self._settings = settings
        self._chats = chat_repository
        self._telemetry = telemetry_repository
        self._client = openai_client or AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value()
        )
        self._runner = runner
        self._session_factory = session_factory
        self._span = span_factory
        self._trace_id_factory = trace_id_factory

    async def start_conversation(
        self,
        *,
        user_id: UUID,
        chainlit_thread_id: str,
        model: ModelId | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> ConversationLike:
        """Create and persist one durable provider Conversation."""

        selected_model, selected_effort = self._policy(model, reasoning_effort)
        provider_conversation = await self._client.conversations.create(items=[])
        with self._span(
            "application_persistence",
            data={"operation": "create_conversation"},
        ):
            return await self._chats.create_thread(
                user_id=user_id,
                chainlit_thread_id=chainlit_thread_id,
                openai_conversation_id=provider_conversation.id,
                settings={
                    "model": selected_model,
                    "reasoning_effort": selected_effort,
                },
            )

    async def stream_turn(
        self,
        *,
        conversation: ConversationLike,
        user_id: UUID,
        prompt: str,
        model: ModelId | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        emit: EmitCallback | None = None,
    ) -> RunSummary:
        """Stream one turn through a durable OpenAI Conversation."""

        selected_model, selected_effort = self._policy(model, reasoning_effort)
        trace_id = self._trace_id_factory()
        agent = Agent(
            name="Project Recovery Assistant",
            instructions=GENERIC_ASSISTANT_INSTRUCTIONS,
            model=selected_model,
            model_settings=ModelSettings(
                reasoning=Reasoning(effort=selected_effort),
                extra_args={"safety_identifier": str(user_id)},
            ),
            tools=[
                FileSearchTool(
                    vector_store_ids=[self._settings.openai_vector_store_id],
                    max_num_results=5,
                )
            ],
        )
        run_config = RunConfig(
            tracing_disabled=not self._settings.tracing_enabled,
            trace_include_sensitive_data=self._settings.trace_include_sensitive_data,
            workflow_name="Project Recovery Chat",
            trace_id=trace_id,
            group_id=str(conversation.id),
            trace_metadata={
                "conversation_id": str(conversation.id),
                "user_id": str(user_id),
                "model": selected_model,
                "environment": self._settings.environment,
            },
        )
        session = self._session_factory(
            conversation_id=conversation.openai_conversation_id,
            openai_client=self._client,
        )
        prompt_run = await self._telemetry.start_prompt_run(
            user_id=user_id,
            conversation_id=conversation.id,
            trace_id=trace_id,
            model=selected_model,
            requested_reasoning_effort=selected_effort,
            effective_reasoning_effort=selected_effort,
            prompt=prompt,
            metadata={"environment": self._settings.environment},
        )
        started = monotonic()
        result: Any | None = None
        seen_tool_calls: set[str] = set()
        try:
            result = self._runner.run_streamed(
                agent,
                input=prompt,
                session=session,
                run_config=run_config,
            )
            # Streaming runs execute in a background task, so their trace does
            # not become the caller's current context. Parent application
            # spans explicitly to the returned SDK trace.
            trace_parent = getattr(result, "trace", None)
            with self._span(
                "application_persistence",
                data={"operation": "persist_user_message"},
                parent=trace_parent,
            ):
                await self._chats.append_message(
                    conversation_id=conversation.id,
                    role="user",
                    content=prompt,
                    provider_response_id=None,
                )
            async for event in result.stream_events():
                normalized = await self._normalize_event(
                    event=event,
                    user_id=user_id,
                    conversation_id=conversation.id,
                    prompt_run_id=prompt_run.id,
                    trace_id=trace_id,
                    trace_parent=trace_parent,
                    seen_tool_calls=seen_tool_calls,
                )
                for item in normalized:
                    await self._emit(emit, item)
            if result.run_loop_exception is not None:
                raise result.run_loop_exception

            usage = result.context_wrapper.usage
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            input_details = getattr(usage, "input_tokens_details", None)
            cached_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            total_tokens = int(
                getattr(usage, "total_tokens", input_tokens + output_tokens)
                or input_tokens + output_tokens
            )
            estimated_cost = calculate_cost(
                selected_model, input_tokens, cached_tokens, output_tokens
            )
            final_output = str(result.final_output or "")
            provider_response_id = cast(str | None, getattr(result, "last_response_id", None))
            with self._span(
                "application_persistence",
                data={"operation": "persist_assistant_message"},
                parent=trace_parent,
            ):
                await self._chats.append_message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=final_output,
                    provider_response_id=provider_response_id,
                )
            await self._safe_finish(
                prompt_run.id,
                status="completed",
                latency_ms=int((monotonic() - started) * 1000),
                input_tokens=input_tokens,
                cached_tokens=cached_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                estimated_cost=estimated_cost,
                provider_response_id=provider_response_id,
                error_message=None,
            )
            return RunSummary(
                final_output=final_output,
                provider_response_id=provider_response_id,
                trace_id=trace_id,
                input_tokens=input_tokens,
                cached_tokens=cached_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost,
            )
        except Exception as error:
            await self._safe_finish(
                prompt_run.id,
                status="failed",
                latency_ms=int((monotonic() - started) * 1000),
                input_tokens=None,
                cached_tokens=None,
                output_tokens=None,
                total_tokens=None,
                estimated_cost=None,
                provider_response_id=None,
                error_message=self._redact_error(error),
            )
            raise

    async def _normalize_event(
        self,
        *,
        event: object,
        user_id: UUID,
        conversation_id: UUID,
        prompt_run_id: UUID,
        trace_id: str,
        trace_parent: object | None,
        seen_tool_calls: set[str],
    ) -> list[AgentEvent]:
        event_type = getattr(event, "type", None)
        data = getattr(event, "data", None)
        if (
            event_type == "raw_response_event"
            and getattr(data, "type", None) == "response.output_text.delta"
        ):
            return [AgentEvent(kind="text_delta", delta=str(getattr(data, "delta", "")))]
        if event_type != "run_item_stream_event":
            return []
        item = getattr(event, "item", None)
        raw_item = getattr(item, "raw_item", None)
        if getattr(raw_item, "type", None) != "file_search_call":
            return []
        tool_call_id = str(getattr(raw_item, "id", "file_search"))
        if tool_call_id in seen_tool_calls:
            return []
        seen_tool_calls.add(tool_call_id)
        queries = [str(value) for value in (getattr(raw_item, "queries", None) or [])]
        raw_results = list(getattr(raw_item, "results", None) or [])
        results = [
            {
                "file_id": str(getattr(result, "file_id", "")),
                "filename": str(getattr(result, "filename", "")),
                "score": float(getattr(result, "score", 0.0) or 0.0),
                "text": str(getattr(result, "text", ""))[:2000],
            }
            for result in raw_results[:20]
        ]
        with self._span(
            "knowledge_lookup_normalization",
            data={"tool_call_id": tool_call_id, "result_count": len(results)},
            parent=trace_parent,
        ):
            await self._telemetry.record_tool_run(
                user_id=user_id,
                conversation_id=conversation_id,
                prompt_run_id=prompt_run_id,
                trace_id=trace_id,
                tool_name="file_search",
                tool_type="hosted_file_search",
                status=str(getattr(raw_item, "status", "completed")),
                duration_ms=None,
                result_count=len(results),
                result_summary=", ".join(
                    str(result["filename"]) for result in results if result["filename"]
                )[:2000],
                arguments={"queries": queries},
                output={"results": results},
            )
        return [
            AgentEvent(
                kind="tool",
                data={
                    "tool_name": "file_search",
                    "status": str(getattr(raw_item, "status", "completed")),
                    "result_count": len(results),
                },
            )
        ]

    async def _safe_finish(self, prompt_run_id: UUID, **kwargs: object) -> None:
        try:
            await self._telemetry.finish_prompt_run(prompt_run_id, **kwargs)
        except Exception:
            # A telemetry outage must not discard a successful provider response.
            return

    def _redact_error(self, error: Exception) -> str:
        redacted = redact_text(str(error), 2000) or ""
        api_key = self._settings.openai_api_key.get_secret_value()
        if api_key:
            redacted = redacted.replace(api_key, "[REDACTED]")
        return redacted

    @staticmethod
    async def _emit(callback: EmitCallback | None, event: AgentEvent) -> None:
        if callback is None:
            return
        result = callback(event)
        if inspect.isawaitable(result):
            await result

    def _policy(
        self,
        model: ModelId | None,
        reasoning_effort: ReasoningEffort | None,
    ) -> tuple[ModelId, ReasoningEffort]:
        selected_model = model or self._settings.default_model
        selected_effort = reasoning_effort or self._settings.default_reasoning_effort
        if selected_model not in ALLOWED_MODELS:
            raise ValueError("unsupported model")
        if selected_effort not in ALLOWED_REASONING_EFFORTS:
            raise ValueError("unsupported reasoning effort")
        return selected_model, selected_effort


__all__ = [
    "AgentEvent",
    "AgentRuntime",
    "GENERIC_ASSISTANT_INSTRUCTIONS",
    "RunSummary",
]
