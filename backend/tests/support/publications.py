"""Publications of an invented transcript, as a collector sends one: each
helper gives a part of the call, and `whole` the call, validated."""

from datetime import timedelta
from typing import Any

from app.schemas.publication import PublicationSchema
from tests.support.transcripts import CAMP, OPUS, STARTED, SUB_AGENT


def hook_run(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "command": "signal_activity.sh",
        "duration_ms": 151,
        "failed": False,
        "prevented_end": False,
    }
    return values | overrides


def prompt(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "received_at": STARTED.isoformat(),
        "source": "person",
        "characters": 212,
    }
    return values | overrides


def launch(**overrides: Any) -> dict[str, Any]:
    """A Launch under Claude Code 2.1.317, with no Prompt."""
    values: dict[str, Any] = {
        "started_at": STARTED.isoformat(),
        "components": [{"component": "claude-code", "version": "2.1.317"}],
    }
    return values | overrides


def compaction(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "at": (STARTED + timedelta(minutes=8)).isoformat(),
        "trigger": "auto",
        "tokens_before": 160_000,
    }
    return values | overrides


def call(place: int, **overrides: Any) -> dict[str, Any]:
    """The Call at `place` in the file, its `message_id` named for it."""
    values: dict[str, Any] = {
        "message_id": f"msg_{place:04}",
        "completed_at": (STARTED + timedelta(minutes=place)).isoformat(),
        "model": OPUS,
        "tokens": {
            "input": 1_204,
            "cache_write_1h": 3_310,
            "cache_read": 48_112,
            "output": 2_870,
        },
    }
    return values | overrides


def whole(**overrides: Any) -> PublicationSchema:
    """A main thread's publication with nothing in it; the overrides give it
    its Launches, Compactions and Calls."""
    values: dict[str, Any] = {
        "session_id": CAMP,
        "file_size": 48_112,
        "file_modified_at": (STARTED + timedelta(minutes=12)).isoformat(),
        "collector": {"version": "1.0.0"},
        "working_directory": "/work/RecipeBox",
    }
    return PublicationSchema.model_validate(values | overrides)


def sub_agent(**overrides: Any) -> PublicationSchema:
    """A publication of a sub-agent's thread of the main thread's session."""
    values: dict[str, Any] = {
        "agent_id": SUB_AGENT,
        "agent_type": "Explore",
        "description": "Find where the recipes are scaled",
    }
    return whole(**values | overrides)
