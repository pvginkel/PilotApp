"""A tool call's Effects (F41; DB §2.3 Effect, assertions 133 to 142, 160,
215, 216): each change a session's call made to the record, placed in its
Session's list by one `server` record of the Turn the call ran in, written
under the Session's lock (design 2 §10).

The record's payload is the effect's line as shown and the call's tool-use
id, which Claude Code sends with every MCP `tools/call` as
`_meta["claudecode/toolUseId"]`, so that a client puts the line on its call.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Effect, SessionRecord, Turn
from app.models.reference import EffectKind, RecordKind
from app.services.session_record_service import SessionRecordService

logger = logging.getLogger(__name__)

EFFECT = "effect"
"""The `type` of the `server` record that places a call's Effects."""

TOOL_USE_ID_HEADER = "Tool-Use-Id"
"""The header in which Pilot's MCP server passes a call's tool-use id to the
tools' routes."""


@dataclass(frozen=True)
class EffectLine:
    """An effect's line as shown, "<verb> · <label>" (F41)."""

    verb: str
    label: str
    """What the call changed, by title as it stood."""
    item_id: uuid.UUID | None = None
    """The item the line goes to."""
    block_id: str | None = None
    """The block in it the line goes to, by its id `<item id>/<local id>`
    (TD §4.9), or `project.md/<local id>` for an ask of a draft, which has no
    item."""


@dataclass(frozen=True)
class Change:
    """One change a call made to the record, named as its Effect names it (DB
    assertion 160)."""

    kind: EffectKind
    item_id: uuid.UUID | None = None
    block_id: int | None = None
    attachment_id: uuid.UUID | None = None


class EffectService:
    """Writes a call's Effects in the caller's transaction."""

    def __init__(
        self, db: Session, session_record_service: SessionRecordService
    ) -> None:
        self.db = db
        self.records = session_record_service

    def record(
        self,
        session_id: uuid.UUID,
        tool_use_id: str | None,
        line: EffectLine,
        changes: Sequence[Change],
    ) -> SessionRecord | None:
        """The call's `changes`, each an Effect of the Session's Turn in
        flight, placed by one `server` record of it carrying `line` and
        `tool_use_id`, the Session's row locked until the transaction ends.

        A call that changed nothing records nothing. Neither does one that
        finds the Session with no Turn in flight, a bearer used outside its
        turn: its changes stand without their Effects.

        Returns:
            The record that places the Effects; None where none were written

        Raises:
            RecordNotFoundException: No Session has the id
        """
        if not changes:
            return None
        self.records.lock_session(session_id)
        turn_id = self.db.scalar(
            select(Turn.id)
            .where(Turn.session_id == session_id, Turn.ended_at.is_(None))
            .order_by(Turn.seq.desc())
            .limit(1)
        )
        if turn_id is None:
            logger.warning(
                "Session %s changed the record with no turn in flight: %s · %s,"
                " no effect recorded",
                session_id,
                line.verb,
                line.label,
            )
            return None
        record = self.records.append(
            session_id,
            RecordKind.SERVER,
            payload=_payload(tool_use_id, line),
            turn_id=turn_id,
        )
        self.db.add_all(
            Effect(
                turn_id=turn_id,
                record_id=record.id,
                kind_code=change.kind,
                item_id=change.item_id,
                block_id=change.block_id,
                attachment_id=change.attachment_id,
            )
            for change in changes
        )
        self.db.flush()
        return record


def _payload(tool_use_id: str | None, line: EffectLine) -> dict[str, Any]:
    effect: dict[str, str] = {"verb": line.verb, "label": line.label}
    if line.item_id is not None:
        effect["itemId"] = str(line.item_id)
    if line.block_id is not None:
        effect["blockId"] = line.block_id
    return {"type": EFFECT, "toolUseId": tool_use_id, "effect": effect}
