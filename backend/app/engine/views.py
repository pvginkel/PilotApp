"""The read-only views rendered from the rows: `reference.json` at the tree's
root, and `timeline.json` and `chat.md` in every project's folder (DB
decisions 34 and 49, TD §7.1.1, design 1 §8, design 3 §10)."""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.bus import EngineBus, ProjectChanged, TreeHashMoved
from app.engine.paths import (
    CHAT,
    TIMELINE,
    attachment_path,
    folder,
    sha256_hex,
    tree_path,
)
from app.models import (
    Attachment,
    Chat,
    ConfirmationReason,
    Document,
    Item,
    ItemAttachment,
    ItemKind,
    Project,
    User,
)
from app.models import Session as AgentSession
from app.models.reference import ChatKind, RecordKind, TaskStatus
from app.services.current_line import TOOL_BLOCKS
from app.services.effect_service import EFFECT
from app.services.people_service import AGENT_HANDLE
from app.services.session_record_service import StoredRecord, read_records
from app.services.start_gate import CHAT_KIND

READONLY = (
    "a projection of the record; an edit is reverted"
    " — the timeline is edited through the tools"
)
"""Each view's top-level `readonly` line (design 1 §8); `chat.md` opens with
it as an HTML comment."""

_RECORD_PAGE = 500
"""The records one read of a chat's takes, in order."""


@dataclass(frozen=True)
class Rendering:
    """A view's text, and the hash of its bytes computed on render."""

    text: str
    hash: str


@dataclass(frozen=True)
class ListedChat:
    """A chat of a project, and when it opened: its Session's creation."""

    chat: Chat
    opened_at: datetime


@dataclass(frozen=True)
class _Said:
    """One paragraph of a chat in `chat.md`: a person's message, by their
    handle, or Pilot's, by none: a text block or an effect's line."""

    place: tuple[int, int, int]
    author: str | None
    at: datetime
    text: str


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
            select(Item, Document.path, Document.summary, Document.published_hash)
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
                for item, _, _, _ in rows
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
                    _item(
                        item,
                        # A registered document before its text has no file.
                        None if published_hash is None else path,
                        summary,
                        handles,
                        hung.get(item.id, []),
                    )
                    for item, path, summary, published_hash in rows
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
        """Tell the bus the project's timeline has a new hash, and that what
        its screens show moved, once the transaction commits."""
        self.engine_bus.emit(
            TreeHashMoved(tree_path(project, TIMELINE), self.timeline(project).hash)
        )
        self.engine_bus.emit(ProjectChanged(project.id))

    def chat(self, project: Project) -> Rendering:
        """The project's chats as `chat.md` gives them (design 3 §10): in
        their order (`project_chats`), each under its opening stamp and
        ending with its close's, or "Open"; in each, a person's messages
        from the `send` records, their words verbatim, and Pilot's text,
        the main thread's `assistant` text blocks alone, with each effect's
        line where its call ran, every record read through the one read
        function."""
        paragraphs = [f"<!-- {READONLY} -->"]
        for listed in project_chats(self.db, project.id):
            paragraphs.append(f"## Chat · opened {utc_time(listed.opened_at)}")
            paragraphs.extend(self._conversation(listed.chat.id))
            closed = listed.chat.closed_at
            paragraphs.append(
                "Open" if closed is None else f"Closed {utc_time(closed)}"
            )
        text = "\n\n".join(paragraphs) + "\n"
        return Rendering(text, sha256_hex(text))

    def recorded(self, session: AgentSession, kind: RecordKind, payload: Any) -> None:
        """A record of `kind` carrying `payload` was written for `session`:
        tell the bus once the transaction commits that its project's
        `chat.md` has a new hash, when the Session is a chat's and the file
        shows the record."""
        if session.kind_code == CHAT_KIND and shows_in_chat(kind, payload):
            self.chat_moved(self.db.get_one(Project, session.project_id))

    def chat_moved(self, project: Project) -> None:
        """Tell the bus the project's `chat.md` has a new hash, once the
        transaction commits."""
        self.engine_bus.emit(
            TreeHashMoved(tree_path(project, CHAT), self.chat(project).hash)
        )

    def chats_moved(self, project: Project) -> None:
        """A chat of the project opened or closed: tell the bus `chat.md` has
        a new hash and that what the project's screens show moved, once the
        transaction commits (F80.2's chat)."""
        self.chat_moved(project)
        self.engine_bus.emit(ProjectChanged(project.id))

    def _conversation(self, session_id: uuid.UUID) -> list[str]:
        """The chat's paragraphs in their order, each run of Pilot's and each
        person's message under its author's handle and its first stamp. An
        effect stands after the `assistant` record that made its call, else
        in its own record's place."""
        said: list[_Said] = []
        calls: dict[str, int] = {}
        for stored in self._every(session_id, RecordKind.CLAUDE, "assistant"):
            record = stored.record
            calls.update(dict.fromkeys(_calls(record.payload), record.seq))
            said.extend(
                _Said((record.seq, 0, record.seq), None, record.at, text)
                for text in pilot_text(record.payload)
            )
        for stored in self._every(session_id, RecordKind.SEND):
            record = stored.record
            # A `send`'s Turn has its person and their words (`ck_turns_words`).
            assert stored.author is not None and stored.words is not None
            said.append(
                _Said(
                    (record.seq, 0, record.seq),
                    stored.author,
                    record.at,
                    stored.words.rstrip("\n"),
                )
            )
        for stored in self._every(session_id, RecordKind.SERVER, EFFECT):
            record = stored.record
            call = record.payload.get("toolUseId")
            effect = record.payload["effect"]
            said.append(
                _Said(
                    (
                        calls.get(call, record.seq) if call else record.seq,
                        1,
                        record.seq,
                    ),
                    None,
                    record.at,
                    f"{effect['verb']} · {effect['label']}",
                )
            )
        paragraphs: list[str] = []
        speaking: str | None = None
        for line in sorted(said, key=lambda line: line.place):
            author = AGENT_HANDLE if line.author is None else line.author
            if line.author is not None or speaking != AGENT_HANDLE:
                paragraphs.append(f"**{author}** · {utc_time(line.at)}")
            speaking = author
            paragraphs.append(line.text)
        return paragraphs

    def _every(
        self, session_id: uuid.UUID, kind: RecordKind, payload_type: str | None = None
    ) -> Iterator[StoredRecord]:
        """Every record of the Session of `kind`, whose payload's `type` is
        `payload_type` when given, in order, a page at a time."""
        after = 0
        while True:
            page = read_records(
                self.db,
                session_id,
                after=after,
                kind=kind,
                payload_type=payload_type,
                limit=_RECORD_PAGE,
            )
            yield from page
            if len(page) < _RECORD_PAGE:
                return
            after = page[-1].record.seq

    def _handles(self, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        return dict(
            self.db.execute(
                select(User.id, User.handle).where(User.id.in_(user_ids))
            ).all()
        )


def project_chats(db: Session, project_id: uuid.UUID) -> list[ListedChat]:
    """The project's chats in their order (F40.3): the definition chat first,
    where one exists, then the project's chats in the order they opened."""
    return [
        ListedChat(chat, opened_at)
        for chat, opened_at in db.execute(
            select(Chat, AgentSession.created_at)
            .join(AgentSession, AgentSession.id == Chat.id)
            .where(Chat.project_id == project_id)
            .order_by(
                (Chat.kind_code == ChatKind.DEFINITION).desc(),
                AgentSession.created_at,
                Chat.id,
            )
        )
    ]


def pilot_text(payload: Any) -> list[str]:
    """Pilot's words in a `claude` record's line: a main-thread `assistant`
    line's text blocks, a blank one left out; none in any other line, a
    sub-agent's included."""
    return [
        block["text"].strip("\n")
        for block in _main_thread_blocks(payload)
        if block.get("type") == "text"
        and isinstance(block.get("text"), str)
        and block["text"].strip()
    ]


def shows_in_chat(kind: RecordKind, payload: Any) -> bool:
    """Whether `chat.md` shows a record of `kind` carrying `payload`, or
    places an effect by it: a person's message, an effect, Pilot's text and
    a main-thread tool call."""
    match kind:
        case RecordKind.SEND:
            return True
        case RecordKind.SERVER:
            return isinstance(payload, dict) and payload.get("type") == EFFECT
        case RecordKind.CLAUDE:
            return bool(pilot_text(payload) or _calls(payload))
        case RecordKind.RESULT:
            return False


def _main_thread_blocks(payload: Any) -> list[dict[str, Any]]:
    """The content blocks of a main-thread `assistant` line; none for any
    other line."""
    if (
        not isinstance(payload, dict)
        or payload.get("type") != "assistant"
        or payload.get("parent_tool_use_id")
    ):
        return []
    message = payload.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _calls(payload: Any) -> list[str]:
    """The tool-use ids of a main-thread `assistant` line's tool calls."""
    return [
        block["id"]
        for block in _main_thread_blocks(payload)
        if block.get("type") in TOOL_BLOCKS and isinstance(block.get("id"), str)
    ]


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
