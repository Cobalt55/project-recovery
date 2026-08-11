"""Bounded, redacted operational telemetry persistence queries."""

import hashlib
from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_recovery.models import ExceptionLog, PromptRun, ToolRun, utc_now
from project_recovery.repositories._safety import (
    bounded_text,
    page_limit,
    page_offset,
    redact_text,
    sanitize_metadata,
)


class TelemetryRepository:
    """Persist indefinitely retained, sanitized telemetry records."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def start_prompt_run(
        self,
        *,
        user_id: UUID | None,
        conversation_id: UUID,
        trace_id: str,
        model: str,
        requested_reasoning_effort: str,
        effective_reasoning_effort: str,
        prompt: str,
        metadata: dict[str, object] | None = None,
    ) -> PromptRun:
        run = PromptRun(
            user_id=user_id,
            conversation_id=conversation_id,
            trace_id=trace_id[:255],
            model=model[:128],
            requested_reasoning_effort=requested_reasoning_effort[:16],
            effective_reasoning_effort=effective_reasoning_effort[:16],
            status="started",
            prompt=redact_text(prompt, 16000),
            metadata_json=sanitize_metadata(metadata),
        )
        async with self._sessions() as session:
            session.add(run)
            await session.commit()
            await session.refresh(run)
        return run

    async def finish_prompt_run(
        self,
        prompt_run_id: UUID,
        *,
        status: str,
        latency_ms: int | None,
        input_tokens: int | None,
        cached_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        estimated_cost: Decimal | str | None,
        provider_response_id: str | None = None,
        error_message: str | None = None,
    ) -> PromptRun | None:
        async with self._sessions() as session:
            run = await session.get(PromptRun, prompt_run_id)
            if run is None:
                return None
            run.status = status[:32]
            run.latency_ms = latency_ms
            run.input_tokens = input_tokens
            run.cached_tokens = cached_tokens
            run.output_tokens = output_tokens
            run.total_tokens = total_tokens
            run.estimated_cost = Decimal(estimated_cost) if estimated_cost is not None else None
            run.provider_response_id = bounded_text(provider_response_id, 255)
            run.error_message = redact_text(error_message, 2000)
            run.finished_at = utc_now()
            await session.commit()
            await session.refresh(run)
            return run

    async def get_prompt_run(self, prompt_run_id: UUID) -> PromptRun | None:
        async with self._sessions() as session:
            return await session.get(PromptRun, prompt_run_id)

    async def record_tool_run(
        self,
        *,
        user_id: UUID | None,
        conversation_id: UUID,
        prompt_run_id: UUID | None,
        trace_id: str,
        tool_name: str,
        tool_type: str,
        status: str,
        duration_ms: int | None,
        result_count: int | None,
        result_summary: str | None,
        arguments: dict[str, object] | None,
        output: dict[str, object] | None,
    ) -> ToolRun:
        run = ToolRun(
            user_id=user_id,
            conversation_id=conversation_id,
            prompt_run_id=prompt_run_id,
            trace_id=trace_id[:255],
            tool_name=tool_name[:128],
            tool_type=tool_type[:64],
            status=status[:32],
            duration_ms=duration_ms,
            result_count=result_count,
            result_summary=redact_text(result_summary, 2000),
            arguments=sanitize_metadata(arguments),
            output=sanitize_metadata(output),
        )
        async with self._sessions() as session:
            session.add(run)
            await session.commit()
            await session.refresh(run)
        return run

    async def get_tool_run(self, tool_run_id: UUID) -> ToolRun | None:
        async with self._sessions() as session:
            return await session.get(ToolRun, tool_run_id)

    async def record_exception(
        self,
        *,
        request_path: str,
        user_id: UUID | None,
        exception_type: str,
        message: str,
        stack_trace: str | None,
        context: dict[str, object] | None,
    ) -> ExceptionLog:
        sanitized_path = request_path.split("?", 1)[0][:2048]
        fingerprint = hashlib.sha256(f"{exception_type}:{sanitized_path}".encode()).hexdigest()
        async with self._sessions() as session:
            now = utc_now()
            entry = (
                insert(ExceptionLog)
                .values(
                    user_id=user_id,
                    fingerprint=fingerprint,
                    request_path=sanitized_path,
                    exception_type=exception_type[:255],
                    message=redact_text(message, 4000),
                    stack_trace=redact_text(stack_trace, 32000),
                    context=sanitize_metadata(context),
                    occurrence_count=1,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_exception_logs_group",
                    set_={
                        "occurrence_count": ExceptionLog.occurrence_count + 1,
                        "last_seen_at": now,
                    },
                )
                .returning(ExceptionLog.id)
            )
            exception_id = await session.scalar(entry)
            await session.commit()
            return await session.get_one(ExceptionLog, exception_id)

    async def get_exception(self, exception_id: UUID) -> ExceptionLog | None:
        async with self._sessions() as session:
            return await session.get(ExceptionLog, exception_id)

    async def list_prompt_runs(self, offset: int, limit: int) -> Sequence[PromptRun]:
        statement = (
            select(PromptRun)
            .order_by(PromptRun.started_at.desc())
            .offset(page_offset(offset))
            .limit(page_limit(limit))
        )
        async with self._sessions() as session:
            return (await session.scalars(statement)).all()

    async def list_tool_runs(self, offset: int, limit: int) -> Sequence[ToolRun]:
        statement = (
            select(ToolRun)
            .order_by(ToolRun.created_at.desc())
            .offset(page_offset(offset))
            .limit(page_limit(limit))
        )
        async with self._sessions() as session:
            return (await session.scalars(statement)).all()

    async def list_exceptions(self, offset: int, limit: int) -> Sequence[ExceptionLog]:
        statement = (
            select(ExceptionLog)
            .order_by(ExceptionLog.last_seen_at.desc())
            .offset(page_offset(offset))
            .limit(page_limit(limit))
        )
        async with self._sessions() as session:
            return (await session.scalars(statement)).all()
