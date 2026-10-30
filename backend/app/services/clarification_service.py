"""The clarification run (design 3 §6.4; F52.2, D059; DB decision 63): when the
pre-ruling pass's job ends having asked its writer, the questions go to the
writer together, as one work item resuming the worker's conversation, and the
writer's reply, the run's turn's final text, is recorded on the run.

The run is placed at the end of the pass's last turn, `idle` or `failed`; a
Stop places none (DB 254). It waits at the gate while another Session runs or
starts on the conversation, the run's continuation after its documents close
among them, which waits for it in turn (DB 183; `start_gate.carried`).

A document's clarification is read from the run, never stored (DB 257): the
pass's questions on its blocks, and each asked block's part of the reply, the
text under the heading the run's first turn asked for it.
"""

import re
import uuid
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.engine.views import ViewService
from app.models import (
    Block,
    ClarificationRun,
    Document,
    Item,
    Project,
    Turn,
    Work,
    WriterQuestion,
)
from app.models import Session as AgentSession
from app.models.reference import WorkTrigger

if TYPE_CHECKING:
    from app.services.session_start_service import SessionStartService

TITLE = "Clarify {names}"
"""The clarification run's title: the asked documents' file names (design 3
§6.4)."""

ASKS = "Pilot asks about {path}:"
"""The head of an asked document's questions in the run's first turn."""

ANSWER = (
    "Answer each under a heading per block id ({headings}); register nothing,"
    " start nothing; then end your turn."
)
"""The close of the run's first turn (design 3 §6.4)."""

_FENCE = re.compile(r" {0,3}(?P<marker>`{3,}|~{3,})(?P<info>.*)")
_HEADING = re.compile(
    r" {0,3}(?P<marks>#{1,6})(?:[ \t]+(?P<text>.*?))?(?:[ \t]+#+)?[ \t]*"
)
"""CommonMark's fence and ATX heading, as pilot-dsl's reader takes them."""


@dataclass(frozen=True)
class Asked:
    """One Writer Question as the clarification run puts it: the asked
    Block's document by its registered path and its item, the Block by its
    id and its local id, the question verbatim and when it was asked."""

    path: str
    item_id: uuid.UUID
    block_id: int
    local_id: str
    question: str
    asked_at: datetime


@dataclass(frozen=True)
class Clarification:
    """One pass's Writer Questions on one Document and the reply of the run
    that clarifies the pass (DB 257): the questions in the Document's order,
    the heading the run asked each Block's answer under, by the Block's id,
    the reply and its end, none until the run's turn ends with one, and each
    asked Block's part of it that the reply keeps."""

    questions: tuple[Asked, ...]
    headings: Mapping[int, str]
    reply: str | None
    replied_at: datetime | None
    parts: Mapping[int, str]

    @property
    def item_id(self) -> uuid.UUID:
        return self.questions[0].item_id

    @property
    def asked_at(self) -> datetime:
        """When the pass first asked about the Document."""
        return min(each.asked_at for each in self.questions)

    @property
    def split(self) -> bool:
        """Whether the reply kept the asked shape on the Document, every
        asked Block's part found: shown per Block, else whole (DB 257)."""
        return self.reply is not None and all(
            each.block_id in self.parts for each in self.questions
        )


def asked(db: Session, pass_id: uuid.UUID) -> list[Asked]:
    """The Writer Questions the Turns of the job `pass_id` asked, grouped by
    document in timeline order and by Block in its document's order."""
    return [each for _, each in _asked(db, Turn.session_id == pass_id)]


def _asked(db: Session, where: ColumnElement[bool]) -> list[tuple[uuid.UUID, Asked]]:
    """The Writer Questions of the Turns `where` selects, each with its
    pass, grouped by document in timeline order and by Block in its
    document's order."""
    rows = db.execute(
        select(
            Turn.session_id,
            Document.source_path,
            Item.id,
            Block.id,
            Block.local_id,
            WriterQuestion.question,
            WriterQuestion.asked_at,
        )
        .select_from(WriterQuestion)
        .join(Turn, Turn.id == WriterQuestion.turn_id)
        .join(Block, Block.id == WriterQuestion.block_id)
        .join(Document, Document.id == Block.document_id)
        .join(Item, Item.id == Document.id)
        .where(where)
        .order_by(Item.seq, Block.position)
    ).all()
    questions = []
    for pass_id, path, item_id, block_id, local_id, question, asked_at in rows:
        # A Writer Question is asked about a registered document's Block.
        assert path is not None
        questions.append(
            (pass_id, Asked(path, item_id, block_id, local_id, question, asked_at))
        )
    return questions


def of_pass(db: Session, pass_id: uuid.UUID) -> list[Clarification]:
    """The clarification of each Document the job `pass_id` asked about, in
    timeline order; none where it asked nothing."""
    return _per_document(
        asked(db, pass_id),
        db.scalars(
            select(ClarificationRun).where(ClarificationRun.pass_id == pass_id)
        ).one_or_none(),
    )


def on_documents(
    db: Session, document_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, list[Clarification]]:
    """The clarifications of each of the Documents, by its id: one per pass
    whose Turns asked about its Blocks, in the order first asked; a Document
    whose writer is asked nothing is left out. Each reads its pass's every
    question, whose headings span the documents the pass asked about."""
    passes = (
        select(Turn.session_id)
        .join(WriterQuestion, WriterQuestion.turn_id == Turn.id)
        .join(Block, Block.id == WriterQuestion.block_id)
        .where(Block.document_id.in_(document_ids))
    )
    by_pass: dict[uuid.UUID, list[Asked]] = {}
    for pass_id, each in _asked(db, Turn.session_id.in_(passes)):
        by_pass.setdefault(pass_id, []).append(each)
    runs = {
        run.pass_id: run
        for run in db.scalars(
            select(ClarificationRun).where(ClarificationRun.pass_id.in_(by_pass))
        )
    }
    wanted = set(document_ids)
    found: dict[uuid.UUID, list[Clarification]] = {}
    for pass_id, questions in by_pass.items():
        for clarification in _per_document(questions, runs.get(pass_id)):
            if clarification.item_id in wanted:
                found.setdefault(clarification.item_id, []).append(clarification)
    for clarifications in found.values():
        clarifications.sort(key=lambda each: each.asked_at)
    return found


def _per_document(
    questions: Sequence[Asked], run: ClarificationRun | None
) -> list[Clarification]:
    """One pass's `questions`, grouped by document, as each document's
    clarification, with the reply of `run`, the run that clarifies the pass,
    none before its placement."""
    asked_headings = headings(questions)
    reply = None if run is None else run.reply
    found = {} if reply is None else reply_parts(reply, asked_headings)
    documents: dict[uuid.UUID, list[Asked]] = {}
    for each in questions:
        documents.setdefault(each.item_id, []).append(each)
    return [
        Clarification(
            questions=tuple(mine),
            headings={each.block_id: asked_headings[each.block_id] for each in mine},
            reply=reply,
            replied_at=None if run is None else run.replied_at,
            parts={
                each.block_id: found[each.block_id]
                for each in mine
                if each.block_id in found
            },
        )
        for mine in documents.values()
    ]


def reply_parts(reply: str, asked_headings: Mapping[int, str]) -> dict[int, str]:
    """Each asked Block's part of `reply`, by the Block's id (DB 257): the
    lines under the heading `asked_headings` gives it, to the next heading of
    the same or a higher level outside a fence, its blank lines at either
    end left out. A Block whose heading the reply does not keep, at its
    level and with its text, or keeps with nothing under it, is left out; a
    heading kept twice is read where it first stands."""
    wanted: dict[tuple[int, str], int] = {}
    for asked_id, asked_heading in asked_headings.items():
        parsed = _heading(asked_heading)
        # `headings` gives each Block an ATX heading.
        assert parsed is not None
        wanted[(parsed[0], " ".join(parsed[1].split()))] = asked_id
    lines = reply.splitlines()
    found: list[tuple[int, int, str]] = []
    fence: str | None = None
    for index, line in enumerate(lines):
        if fence is not None:
            if re.fullmatch(
                rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", line
            ):
                fence = None
            continue
        opening = _FENCE.fullmatch(line)
        if opening is not None and not (
            opening["marker"].startswith("`") and "`" in opening["info"]
        ):
            fence = opening["marker"]
            continue
        heading = _heading(line)
        if heading is not None:
            found.append((index, *heading))
    split: dict[int, str] = {}
    for position, (index, level, text) in enumerate(found):
        block_id = wanted.get((level, " ".join(text.split())))
        if block_id is None or block_id in split:
            continue
        end = next(
            (later for later, under, _ in found[position + 1 :] if under <= level),
            len(lines),
        )
        under = lines[index + 1 : end]
        while under and not under[0].strip():
            under.pop(0)
        while under and not under[-1].strip():
            under.pop()
        if under:
            split[block_id] = "\n".join(under)
    return split


def _heading(line: str) -> tuple[int, str] | None:
    """An ATX heading's level and text; an empty one is no heading."""
    match = _HEADING.fullmatch(line)
    if match is None or not match["text"] or not match["text"].strip():
        return None
    return len(match["marks"]), match["text"].strip()


def headings(questions: Sequence[Asked]) -> dict[int, str]:
    """The heading the run's first Turn asks the writer to answer each asked
    Block under, by the Block's id: `## <local id>`, or `## <path> <local id>`
    where another asked document has a Block of that local id, so that each
    heading names one Block (DB 257)."""
    shared = {
        local_id
        for local_id, count in Counter(each.local_id for each in questions).items()
        if count > 1
    }
    return {
        each.block_id: (
            f"## {each.path} {each.local_id}"
            if each.local_id in shared
            else f"## {each.local_id}"
        )
        for each in questions
    }


def message(questions: Sequence[Asked]) -> str:
    """The run's first Turn (design 3 §6.4): the questions grouped by document
    and Block, then how to answer them."""
    parts = []
    path = None
    for each in questions:
        if each.path != path:
            if path is not None:
                parts.append("")
            path = each.path
            parts.append(ASKS.format(path=path))
        parts.append(f"- {each.local_id}: {each.question}")
    parts.append("")
    parts.append(
        ANSWER.format(
            headings=", ".join(
                f"`{heading}`" for heading in headings(questions).values()
            )
        )
    )
    return "\n".join(parts)


def title(questions: Sequence[Asked]) -> str:
    """The run's title, naming the asked documents by their files' names in
    their order, as the timeline names a registered document."""
    names = [
        PurePosixPath(path).name
        for path in dict.fromkeys(each.path for each in questions)
    ]
    if len(names) == 1:
        return TITLE.format(names=names[0])
    return TITLE.format(names=f"{', '.join(names[:-1])} and {names[-1]}")


class ClarificationService:
    """Places a pass's clarification run and records the writer's reply, in
    the turn end's transaction."""

    def __init__(
        self,
        db: Session,
        session_start_service: "SessionStartService",
        view_service: ViewService,
    ) -> None:
        self.db = db
        self.session_start_service = session_start_service
        self.view_service = view_service

    def pass_ended(self, session: AgentSession) -> None:
        """The job `session` ended, `idle` or `failed` — at its last turn's
        end, at the reading that decided its quota wall missed, or at its
        continuation's failed start — in the caller's transaction, which holds
        its project's row exclusively: a pass, the job after a worker's turn,
        whose Turns asked the writer has every question put to the writer by
        one clarification run placed now, on the conversation of the run
        whose turn it took (DB 254). A stopped end never reaches it."""
        work = self.db.get_one(Work, session.id)
        if work.trigger_code is not WorkTrigger.WORKER_TURN_ENDED:
            return
        questions = asked(self.db, session.id)
        if not questions:
            return
        # The job after a worker's turn names the run.
        assert work.trigger_item_id is not None
        self.session_start_service.clarify(
            self.db,
            self.db.get_one(Project, session.project_id),
            session.id,
            work.trigger_item_id,
            title(questions),
            message(questions),
        )

    def replied(self, session: AgentSession, reply: str | None, at: datetime) -> None:
        """The worker's run `session` at a turn's end `at` with no error, done
        or halted, in the caller's transaction: a clarification run's reply,
        its turn's final text, recorded with `at` (DB 255), the asked
        documents' screens told; a turn that ended with no text leaves it
        none, and a reply recorded is never replaced, by a nudge's turn
        among others."""
        run = self.db.get(ClarificationRun, session.id)
        if run is None or not reply or run.reply is not None:
            return
        run.reply = reply
        run.replied_at = at
        self.view_service.timeline_moved(self.db.get_one(Project, session.project_id))
