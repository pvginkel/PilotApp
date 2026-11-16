"""Publications of an invented transcript, as a collector sends one: each
helper gives a part of the call, and `whole` the call, validated, `appended`
one of the file once it grew; `collector_headers` the headers it is sent
under."""

from datetime import timedelta
from typing import Any

from app.schemas.publication import PublicationSchema
from app.services.publication_service import COLLECTOR_PROTOCOL_MAX
from tests.support.transcripts import CAMP, OPUS, STARTED, SUB_AGENT

COLLECTOR_TOKEN = "an-invented-collector-token"
"""The collector's bearer the test app is set with."""

SPAWNING = "toolu_0031"
"""The `tool_use_id` of the call that started the invented sub-agent."""


def collector_headers() -> dict[str, str]:
    """The headers every call of a collector's carries."""
    return {
        "Authorization": f"Bearer {COLLECTOR_TOKEN}",
        "X-Pilot-Collector-Protocol": str(COLLECTOR_PROTOCOL_MAX),
    }


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


def tool_call(place: int, **overrides: Any) -> dict[str, Any]:
    """The Tool Call at `place` among the file's, its `tool_use_id` named for
    it: a Bash command that returned within the minute."""
    requested = STARTED + timedelta(minutes=place)
    values: dict[str, Any] = {
        "tool_use_id": f"toolu_{place:04}",
        "tool": "Bash",
        "first_argument": "ls recipes",
        "requested_at": requested.isoformat(),
        "returned_at": (requested + timedelta(seconds=4)).isoformat(),
        "failed": False,
        "interrupted": False,
        "result_characters": 1_180,
    }
    return values | overrides


def event(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "kind": "api_error",
        "is_error": True,
        "at": (STARTED + timedelta(minutes=2, seconds=11)).isoformat(),
        "detail": "529",
    }
    return values | overrides


def context_part(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {"kind": "system_prompt", "characters": 9_100}
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


def builds_on(**overrides: Any) -> dict[str, Any]:
    """What an appended call builds on: the file as `whole` gives it."""
    values: dict[str, Any] = {
        "file_size": 48_112,
        "file_modified_at": (STARTED + timedelta(minutes=12)).isoformat(),
        "collector": "1.0.0",
    }
    return values | overrides


def appended(
    *,
    call: int = 1,
    launch: int = 1,
    prompt: int = 1,
    compaction: int = 1,
    **overrides: Any,
) -> PublicationSchema:
    """An appended publication of `whole`'s file, grown since: built on the
    file as `whole` gives it, with the boundary at those places; the
    overrides give it what it carries from there on, and `builds_on` what
    else it builds on."""
    values: dict[str, Any] = {
        "file_size": 61_000,
        "file_modified_at": (STARTED + timedelta(minutes=30)).isoformat(),
        "appended": {
            "builds_on": overrides.pop("builds_on", builds_on()),
            "boundary": {
                "call": call,
                "launch": launch,
                "prompt": prompt,
                "compaction": compaction,
            },
        },
    }
    return whole(**values | overrides)


def sub_agent(**overrides: Any) -> PublicationSchema:
    """A publication of a sub-agent's thread of the main thread's session."""
    values: dict[str, Any] = {
        "agent_id": SUB_AGENT,
        "agent_type": "Explore",
        "description": "Find where the recipes are scaled",
        "spawned_by": SPAWNING,
    }
    return whole(**values | overrides)
