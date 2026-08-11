"""Schema-level invariants for durable persistence."""

from project_recovery.models import Conversation, PromptRun


def test_conversations_have_no_expiry_column():
    """History is durable and a retention field would violate that contract."""
    assert "expires_at" not in Conversation.__table__.columns


def test_prompt_runs_link_trace_and_conversation():
    """Prompt telemetry remains attributable to its conversation and trace."""
    assert {"conversation_id", "trace_id", "model", "status"} <= {
        column.name for column in PromptRun.__table__.columns
    }
