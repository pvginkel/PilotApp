"""The clarification run (design 3 §6.4; F52.2, D059; DB decision 63): when the
pre-ruling pass's job ends having asked its writer, the questions go to the
writer together, as one work item resuming the worker's conversation, and the
writer's reply, the run's turn's final text, is recorded on the run.

The run is placed at the end of the pass's last turn, `idle` or `failed`; a
Stop places none (DB 254). It waits at the gate while another Session runs or
starts on the conversation, the run's continuation after its documents close
among them, which waits for it in turn (DB 183; `start_gate.carried`).
"""

import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

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
from app.services.session_start_service import SessionStartService

TITLE = "Clarify {paths}"
"""The clarification run's title: the asked documents' paths (design 3 §6.4)."""

ASKS = "Pilot asks about {path}:"
"""The head of an asked document's questions in the run's first turn."""

ANSWER = (
    "Answer each under a heading per block id ({headings}); register nothing,"
    " start nothing; then end your turn."
)
"""The close of the run's first turn (design 3 §6.4)."""


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


def asked(db: Session, pass_id: uuid.UUID) -> list[Asked]:
    """The Writer Questions the Turns of the job `pass_id` asked, grouped by
    document in timeline order and by Block in its document's order."""
    rows = db.execute(
        select(
            Document.source_path,
            Item.id,
            Block.id,
            Block.local_id,
            WriterQuestion.question,
            WriterQuestion.asked_at,
        )
        .join(Turn, Turn.id == WriterQuestion.turn_id)
        .join(Block, Block.id == WriterQuestion.block_id)
        .join(Document, Document.id == Block.document_id)
        .join(Item, Item.id == Document.id)
        .where(Turn.session_id == pass_id)
        .order_by(Item.seq, Block.position)
    ).all()
    questions = []
    for path, item_id, block_id, local_id, question, asked_at in rows:
        # A Writer Question is asked about a registered document's Block.
        assert path is not None
        questions.append(Asked(path, item_id, block_id, local_id, question, asked_at))
    return questions


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
    """The run's title, naming the asked documents' paths in their order."""
    paths = list(dict.fromkeys(each.path for each in questions))
    if len(paths) == 1:
        return TITLE.format(paths=paths[0])
    return TITLE.format(paths=f"{', '.join(paths[:-1])} and {paths[-1]}")


class ClarificationService:
    """Places a pass's clarification run and records the writer's reply, in
    the turn end's transaction."""

    def __init__(self, db: Session, session_start_service: SessionStartService) -> None:
        self.db = db
        self.session_start_service = session_start_service

    def pass_ended(self, session: AgentSession) -> None:
        """The job `session` ended at its last turn's end, `idle` or `failed`,
        in the caller's transaction, which holds its project's row
        exclusively: a pass, the job after a worker's turn, whose Turns asked
        the writer has every question put to the writer by one clarification
        run placed now, on the conversation of the run whose turn it took (DB
        254). A stopped end never reaches it."""
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
        """The worker's run `session` done at its turn's end `at`, in the
        caller's transaction: a clarification run's reply, its turn's final
        text, recorded with `at` (DB 255); a turn that ended with no text
        leaves it none."""
        run = self.db.get(ClarificationRun, session.id)
        if run is None or not reply:
            return
        run.reply = reply
        run.replied_at = at
