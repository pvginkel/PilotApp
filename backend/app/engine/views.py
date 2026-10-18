"""The read-only views rendered from the rows: `reference.json` at the tree's
root and `timeline.json` in every project's folder (DB decision 34, TD
§7.1.1, design 1 §8)."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.bus import EngineBus, TreeHashMoved
from app.engine.paths import TIMELINE, attachment_path, folder, sha256_hex, tree_path
from app.models import (
    Attachment,
    ConfirmationReason,
    Document,
    Item,
    ItemAttachment,
    ItemKind,
    Project,
    User,
)
from app.models.reference import TaskStatus

READONLY = (
    "a projection of the record; an edit is reverted"
    " — the timeline is edited through the tools"
)
"""Each view's top-level `readonly` line (design 1 §8)."""


@dataclass(frozen=True)
class Rendering:
    """A view's text, and the hash of its bytes computed on render."""

    text: str
    hash: str


class ViewService:
    def __init__(self, db: Session, engine_bus: EngineBus) -> None:
        self.db = db
        self.engine_bus = engine_bus

    def confirmation_reasons(self) -> list[ConfirmationReason]:
        """The reasons in `reference.json`'s order, which a fault naming them
        prints."""
        return list(
            self.db.scalars(
                select(ConfirmationReason).order_by(ConfirmationReason.code)
            )
        )

    def reference(self) -> Rendering:
        """The reference values the agent writes from a closed list."""
        kinds = self.db.scalars(select(ItemKind).order_by(ItemKind.code))
        return render_json(
            {
                "readonly": READONLY,
                "confirmation_reasons": [
                    {
                        "code": reason.code,
                        "name": reason.name,
                        "description": reason.description,
                        "asks_under_autopilot": reason.asks_under_autopilot,
                    }
                    for reason in self.confirmation_reasons()
                ],
                "item_kinds": [
                    {"code": kind.code, "name": kind.name, "form": kind.form}
                    for kind in kinds
                ],
                "task_statuses": [status.value for status in TaskStatus],
            }
        )

    def timeline(self, project: Project) -> Rendering:
        """The project's timeline: the project's state, its items in order,
        and its attachments, in the files' vocabulary."""
        rows = self.db.execute(
            select(Item, Document.path, Document.summary)
            .outerjoin(Document, Document.id == Item.id)
            .where(Item.project_id == project.id)
            .order_by(Item.seq)
        ).all()
        attachments = list(
            self.db.scalars(
                select(Attachment)
                .where(Attachment.project_id == project.id)
                .order_by(Attachment.batch, Attachment.filename)
            )
        )
        hung: dict[uuid.UUID, list[dict[str, str]]] = {}
        for item_id, attachment in self.db.execute(
            select(ItemAttachment.item_id, Attachment)
            .join(Attachment, Attachment.id == ItemAttachment.attachment_id)
            .where(Attachment.project_id == project.id)
            .order_by(ItemAttachment.position)
        ):
            hung.setdefault(item_id, []).append(_attachment_ref(attachment))
        handles = self._handles(
            {
                user_id
                for item, _, _ in rows
                for user_id in (item.for_user_id, item.done_by_user_id)
                if user_id is not None
            }
        )
        return render_json(
            {
                "readonly": READONLY,
                "project": {
                    "id": str(project.id),
                    "folder": folder(project),
                    "name": project.name,
                    "state": project.state_code.value,
                    "archived": project.archived,
                    "autopilot": project.autopilot,
                },
                "items": [
                    _item(item, path, summary, handles, hung.get(item.id, []))
                    for item, path, summary in rows
                ],
                "attachments": [
                    {
                        **_attachment_ref(attachment),
                        "title": attachment.title,
                        "source": _source(attachment),
                    }
                    for attachment in attachments
                ],
            }
        )

    def timeline_moved(self, project: Project) -> None:
        """Tell the bus the project's timeline has a new hash, once the
        transaction commits."""
        self.engine_bus.emit(
            TreeHashMoved(tree_path(project, TIMELINE), self.timeline(project).hash)
        )

    def _handles(self, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        return dict(
            self.db.execute(
                select(User.id, User.handle).where(User.id.in_(user_ids))
            ).all()
        )


def render_json(data: dict[str, Any]) -> Rendering:
    """A file of the tree rendered from the rows: two-space indent, and a
    newline."""
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return Rendering(text, sha256_hex(text))


def _item(
    item: Item,
    path: str | None,
    summary: str | None,
    handles: dict[uuid.UUID, str],
    attachments: list[dict[str, str]],
) -> dict[str, Any]:
    done = None
    if item.done_at is not None:
        done = {
            "at": utc_time(item.done_at),
            "cause": item.done_cause_code,
            "by": None
            if item.done_by_user_id is None
            else handles[item.done_by_user_id],
        }
    return {
        "id": str(item.id),
        "seq": item.seq,
        "kind": item.kind_code,
        "title": item.title,
        "path": path,
        "step": item.plan_task_id,
        "urgent": item.urgent,
        "for": None if item.for_user_id is None else handles[item.for_user_id],
        "summary": summary,
        "created_at": utc_time(item.created_at),
        "done": done,
        "attachments": attachments,
    }


def _attachment_ref(attachment: Attachment) -> dict[str, str]:
    return {"id": str(attachment.id), "path": attachment_path(attachment)}


def _source(attachment: Attachment) -> str | None:
    """`<environment>:<path>` (DB decision 37); none for the draft's copy."""
    if attachment.source_path is None:
        return None
    return f"{attachment.source_environment_id}:{attachment.source_path}"


def utc_time(moment: datetime) -> str:
    """A time as the files write it: UTC, to the second."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
