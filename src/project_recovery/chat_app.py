"""Chainlit callbacks for the generic Project Recovery chat experience."""
# mypy: disable-error-code="no-untyped-call"

from __future__ import annotations

import re
from http.cookies import SimpleCookie
from typing import Any, cast
from uuid import UUID

import chainlit as cl
from chainlit.input_widget import Select
from chainlit.types import ThreadDict
from chainlit.user import User as ChainlitUser
from starlette.datastructures import Headers

from project_recovery.agent_runtime import AgentEvent
from project_recovery.chainlit_data import ChainlitDataLayer
from project_recovery.chat_state import get_chat_dependencies
from project_recovery.config import (
    ALLOWED_MODELS,
    ALLOWED_REASONING_EFFORTS,
    ModelId,
    ReasoningEffort,
)

MODEL_WIDGET_ID = "Model"
REASONING_WIDGET_ID = "Reasoning"
SESSION_COOKIE = "project_recovery_session"


def validate_chat_settings(values: dict[str, Any]) -> tuple[ModelId, ReasoningEffort] | None:
    """Normalize only the approved model and reasoning policy."""
    model = values.get(MODEL_WIDGET_ID)
    effort = values.get(REASONING_WIDGET_ID)
    if model not in ALLOWED_MODELS or effort not in ALLOWED_REASONING_EFFORTS:
        return None
    return cast(ModelId, model), cast(ReasoningEffort, effort)


def _session_principal() -> str | None:
    try:
        user = cl.user_session.get("user")
    except Exception:
        return None
    return user.identifier if isinstance(user, ChainlitUser) else None


def _current_user_id() -> UUID:
    principal = _session_principal()
    if principal is None:
        raise PermissionError("authentication is required")
    return UUID(principal)


def _chainlit_user(user: Any) -> ChainlitUser:
    return ChainlitUser(
        identifier=str(user.id),
        display_name=user.display_name,
        metadata={"roles": list(user.roles)},
    )


@cl.data_layer
def data_layer() -> ChainlitDataLayer:
    dependencies = get_chat_dependencies()
    return ChainlitDataLayer(
        chats=dependencies.chats,
        users=dependencies.users,
        attachment_root=dependencies.attachment_root,
        principal_provider=_session_principal,
        runtime=dependencies.runtime,
    )


@cl.header_auth_callback
async def authenticate_header(headers: Headers) -> ChainlitUser | None:
    """Exchange the existing opaque application session for a Chainlit user."""
    cookies = SimpleCookie()
    cookies.load(headers.get("cookie", ""))
    morsel = cookies.get(SESSION_COOKIE)
    if morsel is None:
        return None
    dependencies = get_chat_dependencies()
    current = await dependencies.auth.current_user(morsel.value)
    if current is None or current.force_password_change:
        return None
    user = await dependencies.users.get(current.user_id)
    return _chainlit_user(user) if user is not None and user.is_active else None


@cl.password_auth_callback
async def authenticate(username: str, password: str) -> ChainlitUser | None:
    """Provide a direct-chat fallback while keeping raw app tokens out of JWT metadata."""
    dependencies = get_chat_dependencies()
    login = await dependencies.auth.login(username, password)
    if login is None:
        return None
    try:
        user = await dependencies.users.get_by_email(username)
        if user is None or not user.is_active or user.force_password_change:
            return None
        return _chainlit_user(user)
    finally:
        # The Chainlit JWT is the direct-login credential. Revoke the unused
        # application bearer session immediately so no orphan token remains.
        await dependencies.auth.logout(login.session_token)


async def _ensure_conversation() -> Any:
    dependencies = get_chat_dependencies()
    user = await dependencies.users.get(_current_user_id())
    if user is None or not user.is_active or user.force_password_change:
        raise PermissionError("authentication is required")
    thread_id = cl.context.session.thread_id
    conversation = await dependencies.chats.get_thread_by_chainlit_id(thread_id)
    if conversation is not None:
        if conversation.user_id != _current_user_id():
            raise PermissionError("thread is unavailable")
        return conversation
    personal = await dependencies.users.get_settings(_current_user_id())
    model = personal.get("model", "gpt-5.6-terra")
    effort = personal.get("reasoning_effort", "medium")
    validated = validate_chat_settings({MODEL_WIDGET_ID: model, REASONING_WIDGET_ID: effort}) or (
        "gpt-5.6-terra",
        "medium",
    )
    return await dependencies.runtime.start_conversation(
        user_id=_current_user_id(),
        chainlit_thread_id=thread_id,
        model=validated[0],
        reasoning_effort=validated[1],
    )


async def _send_settings(conversation: Any) -> None:
    current = {
        MODEL_WIDGET_ID: str(conversation.settings.get("model", "gpt-5.6-terra")),
        REASONING_WIDGET_ID: str(conversation.settings.get("reasoning_effort", "medium")),
    }
    validated = validate_chat_settings(current) or ("gpt-5.6-terra", "medium")
    cl.user_session.set("conversation", conversation)
    cl.user_session.set(MODEL_WIDGET_ID, validated[0])
    cl.user_session.set(REASONING_WIDGET_ID, validated[1])
    widgets: list[Any] = [
        Select(
            id=MODEL_WIDGET_ID,
            label="Model",
            values=list(ALLOWED_MODELS),
            initial_value=validated[0],
            description="Terra is the balanced default; Luna is faster and Sol is deepest.",
        ),
        Select(
            id=REASONING_WIDGET_ID,
            label="Reasoning",
            values=list(ALLOWED_REASONING_EFFORTS),
            initial_value=validated[1],
            description="Choose how much reasoning to use for this chat.",
        ),
    ]
    await cl.ChatSettings(widgets).send()


@cl.on_chat_start
async def on_chat_start() -> None:
    conversation = await _ensure_conversation()
    await _send_settings(conversation)


@cl.on_settings_update
async def on_settings_update(values: dict[str, Any]) -> None:
    existing = {
        MODEL_WIDGET_ID: cl.user_session.get(MODEL_WIDGET_ID, "gpt-5.6-terra"),
        REASONING_WIDGET_ID: cl.user_session.get(REASONING_WIDGET_ID, "medium"),
    }
    existing.update(values)
    validated = validate_chat_settings(existing)
    if validated is None:
        await cl.Message(content="Those chat settings are not available.").send()
        return
    conversation = cl.user_session.get("conversation") or await _ensure_conversation()
    settings = dict(conversation.settings or {})
    settings.update({"model": validated[0], "reasoning_effort": validated[1]})
    updated = await get_chat_dependencies().chats.update_settings(conversation.id, settings)
    if updated is not None:
        cl.user_session.set("conversation", updated)
    cl.user_session.set(MODEL_WIDGET_ID, validated[0])
    cl.user_session.set(REASONING_WIDGET_ID, validated[1])


@cl.on_message
async def on_message(message: cl.Message) -> None:
    dependencies = get_chat_dependencies()
    conversation = cl.user_session.get("conversation") or await _ensure_conversation()
    model = cl.user_session.get(MODEL_WIDGET_ID, "gpt-5.6-terra")
    effort = cl.user_session.get(REASONING_WIDGET_ID, "medium")
    validated = validate_chat_settings({MODEL_WIDGET_ID: model, REASONING_WIDGET_ID: effort})
    if validated is None:
        await cl.Message(content="The selected chat settings are not available.").send()
        return
    reply = cl.Message(content="")
    citation_names: list[str] = []

    async def emit(event: AgentEvent) -> None:
        if event.kind == "text_delta" and event.delta:
            await reply.stream_token(event.delta)
        if event.kind == "tool" and event.data:
            files = event.data.get("files")
            if isinstance(files, list):
                for file in files:
                    if isinstance(file, dict) and isinstance(file.get("filename"), str):
                        safe_name = re.sub(
                            r"[^A-Za-z0-9 _().-]",
                            "",
                            file["filename"],
                        ).strip()
                        if safe_name and safe_name not in citation_names:
                            citation_names.append(safe_name[:255])

    try:
        summary = await dependencies.runtime.stream_turn(
            conversation=conversation,
            user_id=_current_user_id(),
            prompt=message.content,
            model=validated[0],
            reasoning_effort=validated[1],
            emit=emit,
            persist_messages=False,
        )
        if not reply.content:
            reply.content = summary.final_output
        if citation_names:
            reply.content += "\n\nSources: " + ", ".join(citation_names)
        await reply.update()
    except Exception:
        reply.content = "I’m sorry, I couldn’t complete that response. Please try again."
        await reply.update()


@cl.on_chat_resume
async def on_chat_resume(thread: ThreadDict) -> None:
    dependencies = get_chat_dependencies()
    user = await dependencies.users.get(_current_user_id())
    if user is None or not user.is_active or user.force_password_change:
        raise PermissionError("authentication is required")
    conversation = await dependencies.chats.get_thread_by_chainlit_id(thread["id"])
    if conversation is None or conversation.user_id != _current_user_id():
        raise PermissionError("thread is unavailable")
    await _send_settings(conversation)


__all__ = [
    "MODEL_WIDGET_ID",
    "REASONING_WIDGET_ID",
    "authenticate",
    "authenticate_header",
    "on_chat_resume",
    "on_chat_start",
    "on_message",
    "on_settings_update",
    "validate_chat_settings",
]
