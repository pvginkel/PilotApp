"""Rows of an invented transcript, for tests of what the record holds of
one. Each helper adds its row and flushes, so the row has its id."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session as DbSession

from app.models import (
    Call,
    Compaction,
    CompactionTrigger,
    Component,
    ComponentVersion,
    Launch,
    Model,
    Prompt,
    PromptSource,
    Tool,
    ToolCall,
    Transcript,
)

STARTED = datetime(2026, 11, 12, 9, 30, tzinfo=UTC)
CAMP = "0b5e3c1a-7d42-4f6e-9a18-2c4d6e8f0a1b"
"""Claude Code's id of an invented main thread."""
OTHER = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
"""Claude Code's id of another."""
SUB_AGENT = "a4f1c09e2b7d3e586"
"""Claude Code's id of an invented sub-agent."""
OPUS = "claude-opus-4-5"
HAIKU = "claude-haiku-4-5-20251001"


def _added[Row](db: DbSession, row: Row) -> Row:
    db.add(row)
    db.flush()
    return row


def reference[Row](db: DbSession, entity: type[Row], code: str, **facts: Any) -> Row:
    """The reference entity's row of `code`, written where the test has not
    met it yet, as a publication writes one."""
    row = db.get(entity, code)
    if row is None:
        row = _added(db, entity(code=code, name=code, **facts))
    return row


def component_version(
    db: DbSession, component: str = "collector", version: str = "1.0.0"
) -> ComponentVersion:
    reference(db, Component, component)
    return _added(db, ComponentVersion(component_code=component, version=version))


def transcript(
    db: DbSession, read_under: ComponentVersion, **overrides: Any
) -> Transcript:
    """A main thread, published whole; `agent_id` makes it a sub-agent's."""
    values: dict[str, Any] = {
        "session_id": CAMP,
        "working_directory": "/work/RecipeBox",
        "file_size": 48_112,
        "file_modified_at": STARTED + timedelta(minutes=12),
        "collected_at": STARTED + timedelta(minutes=13),
        "replayed_size": 48_112,
        "read_under_id": read_under.id,
    }
    values.update(overrides)
    return _added(db, Transcript(**values))


def launch(db: DbSession, thread: Transcript, **overrides: Any) -> Launch:
    values: dict[str, Any] = {"transcript_id": thread.id, "started_at": STARTED}
    values.update(overrides)
    return _added(db, Launch(**values))


def prompt(db: DbSession, start: Launch, **overrides: Any) -> Prompt:
    reference(db, PromptSource, "person")
    values: dict[str, Any] = {
        "transcript_id": start.transcript_id,
        "launch_id": start.id,
        "received_at": STARTED,
        "source_code": "person",
        "characters": 212,
    }
    values.update(overrides)
    return _added(db, Prompt(**values))


def compaction(db: DbSession, thread: Transcript, **overrides: Any) -> Compaction:
    reference(db, CompactionTrigger, "auto")
    values: dict[str, Any] = {
        "transcript_id": thread.id,
        "at": STARTED + timedelta(minutes=8),
        "trigger_code": "auto",
        "tokens_before": 160_000,
    }
    values.update(overrides)
    return _added(db, Compaction(**values))


def call(db: DbSession, thread: Transcript, position: int, **overrides: Any) -> Call:
    """The Transcript's Call at `position`, its `message_id` named for it."""
    reference(db, Model, OPUS)
    values: dict[str, Any] = {
        "transcript_id": thread.id,
        "message_id": f"msg_{position:04}",
        "position": position,
        "completed_at": STARTED + timedelta(minutes=position),
        "model_code": OPUS,
        "input_tokens": 1_204,
        "cache_write_5m_tokens": 0,
        "cache_write_1h_tokens": 3_310,
        "cache_read_tokens": 48_112,
        "output_tokens": 2_870,
    }
    values.update(overrides)
    return _added(db, Call(**values))


def tool_call(db: DbSession, request: Call, **overrides: Any) -> ToolCall:
    reference(db, Tool, "Bash")
    values: dict[str, Any] = {
        "transcript_id": request.transcript_id,
        "call_id": request.id,
        "tool_use_id": "toolu_0001",
        "tool_code": "Bash",
        "requested_at": request.completed_at,
        "failed": False,
        "interrupted": False,
    }
    values.update(overrides)
    return _added(db, ToolCall(**values))
