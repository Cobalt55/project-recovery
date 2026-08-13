"""Request-local identity bridge for Chainlit HTTP feedback actions."""

from contextvars import ContextVar, Token

_feedback_http_principal: ContextVar[str | None] = ContextVar(
    "project_recovery_feedback_http_principal", default=None
)


def current_feedback_http_principal() -> str | None:
    """Return the identity validated for the current mounted feedback request."""
    return _feedback_http_principal.get()


def bind_feedback_http_principal(principal: str) -> Token[str | None]:
    """Bind an already-authenticated application user until the request completes."""
    return _feedback_http_principal.set(principal)


def clear_feedback_http_principal(token: Token[str | None]) -> None:
    """Restore the caller's context after the mounted request has completed."""
    _feedback_http_principal.reset(token)


__all__ = [
    "bind_feedback_http_principal",
    "clear_feedback_http_principal",
    "current_feedback_http_principal",
]
