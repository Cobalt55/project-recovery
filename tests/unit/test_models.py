"""Schema-level invariants for durable persistence."""

import json

from project_recovery.models import ChatFeedback, Conversation, MessageAttachment, PromptRun
from project_recovery.repositories._safety import MAX_CONTEXT_BYTES, sanitize_metadata


def test_conversations_have_no_expiry_column():
    """History is durable and a retention field would violate that contract."""
    assert "expires_at" not in Conversation.__table__.columns


def test_prompt_runs_link_trace_and_conversation():
    """Prompt telemetry remains attributable to its conversation and trace."""
    assert {"conversation_id", "trace_id", "model", "status"} <= {
        column.name for column in PromptRun.__table__.columns
    }


def test_sanitized_metadata_has_a_real_serialized_byte_bound():
    """Large numeric/nested structures cannot evade the persisted context budget."""
    metadata = {f"value-{index}": 10**1000 for index in range(100)}
    metadata["nested"] = {str(index): list(range(1_000)) for index in range(100)}

    sanitized = sanitize_metadata(metadata)

    assert len(json.dumps(sanitized, separators=(",", ":")).encode("utf-8")) <= MAX_CONTEXT_BYTES


def test_message_children_cannot_reference_another_conversation():
    """The database enforces message/conversation consistency for chat children."""
    expected = {"message_id", "conversation_id"}
    for model in (MessageAttachment, ChatFeedback):
        composite_foreign_keys = [
            constraint
            for constraint in model.__table__.foreign_key_constraints
            if {column.name for column in constraint.columns} == expected
        ]
        assert len(composite_foreign_keys) == 1
        assert composite_foreign_keys[0].referred_table.name == "messages"
