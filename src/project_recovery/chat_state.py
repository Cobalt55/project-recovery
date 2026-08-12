"""Process-local dependency handoff for Chainlit's filesystem-loaded module."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ChatDependencies:
    """Dependencies shared by the mounted callbacks and data layer."""

    auth: Any
    users: Any
    chats: Any
    runtime: Any
    attachment_root: Path


_dependencies: ChatDependencies | None = None


def configure_chat(dependencies: ChatDependencies) -> None:
    """Configure the single mounted Chainlit application."""
    global _dependencies
    _dependencies = dependencies


def get_chat_dependencies() -> ChatDependencies:
    """Return configured chat dependencies or fail before serving traffic."""
    if _dependencies is None:
        raise RuntimeError("chat dependencies are not configured")
    return _dependencies


__all__ = ["ChatDependencies", "configure_chat", "get_chat_dependencies"]
