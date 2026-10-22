"""The record's own writes: a person's answer, Done on an action, undo, Done
on a document, Read and Reviewed (design 1 §6.4, F32.4)."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from flask import Flask
from psycopg.errors import LockNotAvailable
from sqlalchemy import select
from sqlalchemy import text as sql
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged, TreeHashMoved
from app.engine.paths import sha256_hex
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.extensions import db
from app.models import (
    Block,
    Document,
    DocumentVersion,
    Environment,
    Item,
    PlanTask,
    Project,
    User,
)
from app.models.reference import (
    AnswerChannel,
    SessionState,
    TaskStatus,
    UserKind,
    VersionCause,
)
from app.services.container import ServiceContainer
from tests.support.fake_sidecar import FakeSidecar

DECISION = """---
title: Which tent?
---

```decision id=D1
options:
  - Dome
  - Tunnel
recommend: Dome
```
"""

ACTION = """---
title: Put the key into OpenBao
---

```action id=A1
```
"""

ACTION_WITH_OPTIONS = """---
title: Try the fix
---

```action id=A1
options:
  - Works
  - Doesn't
```
"""

QUESTION_DRAFT = """---
title: Badges
---

```question id=Q1
default: Blue
```
"""

TWO_ASKS = """---
title: Camp plan
---

```decision id=D1
options:
  - Dome
  - Tunnel
```

```question id=Q1
default: The lake
```
"""

PRE_RULED = """---
title: Camp plan
---

```decision id=D1
options:
  - Dome
  - Tunnel
answer: deferred
by: agent
at: 2026-10-12T09:30:00Z
to: plan
note: Decide at the site.
```

```question id=Q1
default: The lake
```
"""

RECOMMENDED = """---
title: Camp plan
---

```decision id=D1
options:
  - Dome
  - Tunnel
recommend: Dome
```

```decision id=D2
proposal: Cook on the fire.
```

```decision id=C1
type: confirmation
because: rider
proposal: Book the site.
```

```question id=Q1
default: The lake
```

```action id=A1
done: 2026-10-12T11:00:00Z
by: ada
```
"""

UNREADY = """---
title: Camp chores
---

```question id=Q1
```

```action id=A1
```

```question id=Q2
default: The lake
```
"""

SETTLED = """---
title: Camp plan
---

```decision id=D1
options:
  - Dome
  - Tunnel
answer: Dome
by: agent
at: 2026-10-12T09:30:00Z
```

```question id=Q1
answer: deferred
by: agent
at: 2026-10-12T09:30:00Z
to: plan
```
"""

NOTICE = "---\ntitle: The palette\n---\n\nBlue and green.\n"


def _z(moment: datetime | None) -> str:
    assert moment is not None
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bear(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    project_session: models.Session,
    kind: str,
    title: str,
    text: str,
) -> tuple[Item, Document]:
    item = container.document_service().bear_item(
        project, kind, title, project_session, text
    )
    return item, session.get_one(Document, item.id)


def _block(session: DbSession, document: Document, local_id: str) -> Block:
    return session.scalars(
        select(Block).where(
            Block.document_id == document.id, Block.local_id == local_id
        )
    ).one()


def _versions(
    session: DbSession, document: Document
) -> list[tuple[int, VersionCause, str]]:
    return [
        (version.number, version.cause_code, version.text)
        for version in session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.number)
        )
    ]


def _agent(session: DbSession) -> User:
    return session.scalars(select(User).where(User.handle == "agent")).one()


def _task(
    session: DbSession, project: Project, task_id: str, *, removed: bool = False
) -> PlanTask:
    task = PlanTask(
        project_id=project.id,
        task_id=task_id,
        position=None if removed else 1,
        title=f"Task {task_id}",
        status_code=TaskStatus.PENDING,
        removed_at=datetime.now(UTC) if removed else None,
    )
    session.add(task)
    session.flush()
    return task


def _done(item: Item) -> tuple[datetime | None, str | None, uuid.UUID | None]:
    return item.done_at, item.done_cause_code, item.done_by_user_id


def _textless(
    session: DbSession,
    project: Project,
    project_session: models.Session,
    kind: str,
    seq: int = 1,
) -> Item:
    """An open item of `kind`, a work or wait item, which has no Document."""
    item = Item(
        project_id=project.id,
        seq=seq,
        kind_code=kind,
        title="Build the camp",
        created_by_session_id=project_session.id,
    )
    session.add(item)
    session.flush()
    return item


class TestRecordServiceAnswer:
    def test_a_persons_answer_is_spliced_and_published(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )
        before = datetime.now(UTC).replace(microsecond=0)

        container.record_service().answer(
            document, "D1", person, "Tunnel", note="Room for six."
        )

        block = _block(session, document, "D1")
        assert block.answered_at is not None
        assert before <= block.answered_at <= datetime.now(UTC)
        assert document.published_text == DECISION.replace(
            "recommend: Dome\n",
            "recommend: Dome\nanswer: Tunnel\nby: ada\n"
            f"at: {_z(block.answered_at)}\nnote: Room for six.\n",
        )
        assert document.published_hash == sha256_hex(document.published_text)
        assert (block.answer, block.answered_by_user_id, block.note) == (
            "Tunnel",
            person.id,
            "Room for six.",
        )
        assert block.via_code is AnswerChannel.APP
        assert _versions(session, document) == [(1, VersionCause.BORN, DECISION)]

    def test_a_one_ask_items_answer_is_its_done(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )

        container.record_service().answer(document, "D1", person, "Tunnel")

        assert _done(item) == (
            _block(session, document, "D1").answered_at,
            "answered",
            person.id,
        )

    def test_the_opening_has_no_block_to_answer(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
    ) -> None:
        opening = container.document_service().bear_opening(
            project, "Which tent?", person, DECISION
        )
        document = session.get_one(Document, opening.id)

        with pytest.raises(RecordNotFoundException) as missing:
            container.record_service().answer(document, "D1", person, "Tunnel")

        assert missing.value.message == f"Block {document.id}/D1 was not found"
        assert document.published_text == DECISION
        assert _done(opening) == (None, None, None)

    def test_an_answer_in_a_document_leaves_the_item_open(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp plan",
            TWO_ASKS,
        )

        container.record_service().answer(document, "D1", person, "Dome")

        assert _done(item) == (None, None, None)
        assert item.kind_code == "document"
        assert _block(session, document, "D1").answer == "Dome"

    @pytest.mark.parametrize(
        ("via", "line"),
        [
            (AnswerChannel.APP, ""),
            (AnswerChannel.CHAT, "via: chat\n"),
            (AnswerChannel.RECOMMENDED, "via: recommended\n"),
            (AnswerChannel.AUTOPILOT, "via: autopilot\n"),
        ],
    )
    def test_every_answer_channel_is_written(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        via: AnswerChannel,
        line: str,
    ) -> None:
        draft = container.document_service().bear_draft(project, QUESTION_DRAFT)

        container.record_service().answer(draft, "Q1", person, "Green", via=via)

        block = _block(session, draft, "Q1")
        assert draft.published_text == QUESTION_DRAFT.replace(
            "default: Blue\n",
            f"default: Blue\nanswer: Green\nby: ada\nat: {_z(block.answered_at)}\n"
            + line,
        )
        assert block.via_code is via

    def test_an_answer_replaces_pilots_with_its_to_and_note(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp plan",
            PRE_RULED,
        )

        container.record_service().answer(document, "D1", person, "Tunnel")

        block = _block(session, document, "D1")
        assert document.published_text == PRE_RULED.replace(
            "answer: deferred\nby: agent\nat: 2026-10-12T09:30:00Z\nto: plan\n"
            "note: Decide at the site.\n",
            f"answer: Tunnel\nby: ada\nat: {_z(block.answered_at)}\n",
        )
        assert (block.answer, block.note, block.deferred_to_task_id) == (
            "Tunnel",
            None,
            None,
        )

    def test_an_answer_replaces_a_persons_while_the_item_is_open(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp plan",
            TWO_ASKS,
        )
        records = container.record_service()
        records.answer(document, "D1", person, "Dome", note="Lighter.")

        records.answer(document, "D1", person, "Tunnel")

        block = _block(session, document, "D1")
        assert document.published_text == TWO_ASKS.replace(
            "  - Tunnel\n",
            f"  - Tunnel\nanswer: Tunnel\nby: ada\nat: {_z(block.answered_at)}\n",
        )

    @pytest.mark.parametrize("to", ["t1", "plan"])
    def test_a_deferral_names_a_task_in_the_plan_or_the_plan(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        to: str,
    ) -> None:
        _task(session, project, "t1")
        draft = container.document_service().bear_draft(project, QUESTION_DRAFT)

        container.record_service().answer(
            draft, "Q1", person, "deferred", via=AnswerChannel.CHAT, to=to
        )

        block = _block(session, draft, "Q1")
        assert draft.published_text == QUESTION_DRAFT.replace(
            "default: Blue\n",
            "default: Blue\nanswer: deferred\nby: ada\n"
            f"at: {_z(block.answered_at)}\nvia: chat\nto: {to}\n",
        )
        assert block.deferred_to_task_id == (None if to == "plan" else to)

    @pytest.mark.parametrize(
        ("answer", "to", "cause"),
        [
            pytest.param(
                "deferred",
                "t9",
                "`to: t9` names neither `plan` nor a task in the plan",
                id="no-task",
            ),
            pytest.param(
                "deferred",
                "gone",
                "`to: gone` names neither `plan` nor a task in the plan",
                id="removed-task",
            ),
            pytest.param(
                "deferred",
                "elsewhere",
                "`to: elsewhere` names neither `plan` nor a task in the plan",
                id="another-projects-task",
            ),
            pytest.param("deferred", None, "`deferred` names no `to`", id="no-to"),
            pytest.param(
                "Green", "t1", "`to` goes with `deferred` alone", id="to-not-deferred"
            ),
            pytest.param("  ", None, "the answer is blank", id="blank"),
        ],
    )
    def test_an_answer_the_record_cannot_hold_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        answer: str,
        to: str | None,
        cause: str,
    ) -> None:
        _task(session, project, "t1")
        _task(session, project, "gone", removed=True)
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        _task(session, other, "elsewhere")
        draft = container.document_service().bear_draft(project, QUESTION_DRAFT)

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().answer(
                draft, "Q1", person, answer, via=AnswerChannel.CHAT, to=to
            )

        assert refused.value.cause == cause
        assert draft.published_text == QUESTION_DRAFT

    def test_values_are_written_trimmed_and_a_blank_note_is_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
    ) -> None:
        draft = container.document_service().bear_draft(project, QUESTION_DRAFT)

        container.record_service().answer(draft, "Q1", person, "  Green ", note=" ")

        block = _block(session, draft, "Q1")
        assert draft.published_text == QUESTION_DRAFT.replace(
            "default: Blue\n",
            f"default: Blue\nanswer: Green\nby: ada\nat: {_z(block.answered_at)}\n",
        )

    def test_pilot_answers_in_the_file(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        draft = container.document_service().bear_draft(project, QUESTION_DRAFT)

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().answer(draft, "Q1", _agent(session), "Green")

        assert refused.value.cause == "Pilot answers in the file, `by: agent`"
        assert draft.published_text == QUESTION_DRAFT

    def test_an_answer_to_a_done_item_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )
        records = container.record_service()
        records.answer(document, "D1", person, "Tunnel")
        answered = document.published_text

        with pytest.raises(InvalidOperationException) as refused:
            records.answer(document, "D1", person, "Dome")

        assert refused.value.cause == "the item is done"
        assert document.published_text == answered

    def test_a_block_the_document_lacks_is_not_found(
        self, container: ServiceContainer, project: Project, person: User
    ) -> None:
        draft = container.document_service().bear_draft(project, QUESTION_DRAFT)

        with pytest.raises(RecordNotFoundException) as missing:
            container.record_service().answer(draft, "Q2", person, "Green")

        assert missing.value.message == f"Block {draft.id}/Q2 was not found"

    def test_an_action_without_options_is_done_not_answered(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "action",
            "Put the key into OpenBao",
            ACTION,
        )
        records = container.record_service()

        with pytest.raises(InvalidOperationException) as refused:
            records.answer(document, "A1", person, "Stored it")
        assert refused.value.cause == "an action without options is done, not answered"

        records.answer(
            document, "A1", person, "deferred", via=AnswerChannel.CHAT, to="plan"
        )
        block = _block(session, document, "A1")
        assert (block.answer, block.done_at) == ("deferred", None)
        assert _done(item) == (block.answered_at, "answered", person.id)


class TestRecordServiceDoneAction:
    def test_done_writes_done_and_by_with_the_paste_back(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "action",
            "Put the key into OpenBao",
            ACTION,
        )

        container.record_service().done_action(
            document, "A1", person, note="Stored under secret/camp."
        )

        block = _block(session, document, "A1")
        assert document.published_text == ACTION.replace(
            "```action id=A1\n",
            f"```action id=A1\ndone: {_z(block.done_at)}\nby: ada\n"
            "note: Stored under secret/camp.\n",
        )
        assert (block.answer, block.answered_by_user_id) == (None, person.id)
        assert _done(item) == (block.done_at, "answered", person.id)

    def test_the_opening_has_no_action_to_mark_done(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
    ) -> None:
        opening = container.document_service().bear_opening(
            project, "Put the key into OpenBao", person, ACTION
        )
        document = session.get_one(Document, opening.id)

        with pytest.raises(RecordNotFoundException):
            container.record_service().done_action(document, "A1", person)

        assert document.published_text == ACTION
        assert _done(opening) == (None, None, None)

    def test_an_action_in_a_document_leaves_the_item_open(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp chores",
            UNREADY,
        )

        container.record_service().done_action(document, "A1", person)

        assert _block(session, document, "A1").done_at is not None
        assert _done(item) == (None, None, None)

    def test_an_action_with_options_is_answered_with_one(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "action",
            "Try the fix",
            ACTION_WITH_OPTIONS,
        )
        records = container.record_service()

        with pytest.raises(InvalidOperationException) as refused:
            records.done_action(document, "A1", person)
        assert refused.value.cause == (
            "an action with options is answered with one of them"
        )

        records.answer(document, "A1", person, "Works", note="Fixed.")
        block = _block(session, document, "A1")
        assert block.answer == "Works"
        assert _done(item) == (block.answered_at, "answered", person.id)

    def test_done_on_a_block_that_is_no_action_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().done_action(document, "D1", person)

        assert refused.value.cause == "block D1 is a decision, not an action"
        assert document.published_text == DECISION

    def test_pilot_settles_an_action_in_the_file(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "action",
            "Put the key into OpenBao",
            ACTION,
        )

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().done_action(document, "A1", _agent(session))

        assert refused.value.cause == "Pilot settles an action in the file"

    def test_done_on_a_done_item_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "action",
            "Put the key into OpenBao",
            ACTION,
        )
        records = container.record_service()
        records.done_action(document, "A1", person)

        with pytest.raises(InvalidOperationException) as refused:
            records.done_action(document, "A1", person)

        assert refused.value.cause == "the item is done"


class TestRecordServiceUndo:
    def test_undo_clears_a_one_ask_items_answer(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )
        records = container.record_service()
        records.answer(document, "D1", person, "Tunnel", note="Room for six.")

        records.undo(item)

        assert _done(item) == (None, None, None)
        assert document.published_text == DECISION
        assert _block(session, document, "D1").answer is None

    def test_undo_of_an_actions_done_clears_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "action",
            "Put the key into OpenBao",
            ACTION,
        )
        records = container.record_service()
        records.done_action(document, "A1", person, note="Stored.")

        records.undo(item)

        assert _done(item) == (None, None, None)
        assert document.published_text == ACTION

    def test_undo_restores_no_answer_of_pilots(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        pre_ruled = DECISION.replace(
            "recommend: Dome\n",
            "recommend: Dome\nanswer: Dome\nby: agent\nat: 2026-10-12T09:30:00Z\n",
        )
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            pre_ruled,
        )
        records = container.record_service()
        records.answer(document, "D1", person, "Tunnel")

        records.undo(item)

        assert document.published_text == DECISION

    def test_undo_of_a_mark_leaves_the_text(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "notice",
            "The palette",
            NOTICE,
        )
        records = container.record_service()
        records.read(item, person)
        published_at = document.published_at

        records.undo(item)

        assert _done(item) == (None, None, None)
        assert (document.published_text, document.published_at) == (
            NOTICE,
            published_at,
        )

    def test_undo_of_a_done_document_keeps_its_answers_and_version(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp plan",
            RECOMMENDED,
        )
        records = container.record_service()
        records.done(item, person)
        done = document.published_text

        records.undo(item)

        assert _done(item) == (None, None, None)
        assert document.published_text == done
        assert [cause for _, cause, _ in _versions(session, document)] == [
            VersionCause.BORN,
            VersionCause.DONE,
        ]

    def test_undo_of_pilots_settled_document_is_offered(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp plan",
            SETTLED,
        )
        records = container.record_service()
        records.done(item, _agent(session))

        records.undo(item)

        assert _done(item) == (None, None, None)
        assert document.published_text == SETTLED

    def test_undo_is_refused_once_a_session_took_the_item(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )
        records = container.record_service()
        records.answer(document, "D1", person, "Tunnel")
        answered = document.published_text
        item.consumed_at = datetime.now(UTC)
        item.consumed_session_id = project_session.id
        session.flush()

        with pytest.raises(InvalidOperationException) as refused:
            records.undo(item)

        assert refused.value.cause == "a session has taken the item's answers"
        assert item.done_cause_code == "answered"
        assert document.published_text == answered

    def test_undo_is_refused_where_the_done_cause_offers_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item, _ = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )
        item.done_at = datetime.now(UTC)
        item.done_cause_code = "finished"
        session.flush()

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().undo(item)

        assert refused.value.cause == "an item done as finished offers no undo"
        assert item.done_cause_code == "finished"

    def test_undo_is_refused_on_an_item_not_done(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item, _ = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().undo(item)

        assert refused.value.cause == "the item is not done"

    def test_undo_is_not_offered_on_work(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        work = Item(
            project_id=project.id,
            seq=1,
            kind_code="work",
            title="Build the camp",
            created_by_session_id=project_session.id,
            done_at=datetime.now(UTC),
            done_cause_code="turn_ended",
        )
        session.add(work)
        session.flush()

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().undo(work)

        assert refused.value.cause == "a work item offers no undo"


class TestRecordServiceOffersUndo:
    """`offers_undo` reads `undo`'s own rule (DB 164, F14.1)."""

    def _decision(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> tuple[Item, Document]:
        return _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )

    def test_an_answered_item_offers_undo(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = self._decision(session, container, project, project_session)
        records = container.record_service()
        records.answer(document, "D1", person, "Tunnel")

        assert records.offers_undo(item) is True

    def test_an_item_a_session_took_offers_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = self._decision(session, container, project, project_session)
        records = container.record_service()
        records.answer(document, "D1", person, "Tunnel")
        item.consumed_at = datetime.now(UTC)
        item.consumed_session_id = project_session.id
        session.flush()

        assert records.offers_undo(item) is False

    def test_an_item_done_by_a_cause_that_offers_none_offers_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item, _ = self._decision(session, container, project, project_session)
        item.done_at = datetime.now(UTC)
        item.done_cause_code = "finished"
        session.flush()

        assert container.record_service().offers_undo(item) is False

    def test_an_open_item_offers_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item, _ = self._decision(session, container, project, project_session)

        assert container.record_service().offers_undo(item) is False

    def test_work_offers_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        work = Item(
            project_id=project.id,
            seq=1,
            kind_code="work",
            title="Build the camp",
            created_by_session_id=project_session.id,
            done_at=datetime.now(UTC),
            done_cause_code="marked",
        )
        session.add(work)
        session.flush()

        assert container.record_service().offers_undo(work) is False


class TestRecordServiceDone:
    def test_done_records_the_recommendations_and_cuts_a_version(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp plan",
            RECOMMENDED,
        )

        container.record_service().done(item, person)

        at = _z(item.done_at)
        recommended = RECOMMENDED
        for after, answer in [
            ("recommend: Dome\n", "Dome"),
            ("proposal: Cook on the fire.\n", "Agree"),
            ("proposal: Book the site.\n", "Yes"),
            ("default: The lake\n", "The lake"),
        ]:
            recommended = recommended.replace(
                after,
                f"{after}answer: {answer}\nby: ada\nat: {at}\nvia: recommended\n",
            )
        assert document.published_text == recommended
        assert _done(item) == (item.done_at, "marked", person.id)
        assert _versions(session, document) == [
            (1, VersionCause.BORN, RECOMMENDED),
            (2, VersionCause.DONE, recommended),
        ]
        assert [
            (block.local_id, block.via_code)
            for block in session.scalars(
                select(Block)
                .where(Block.document_id == document.id)
                .order_by(Block.position)
            )
        ] == [
            ("D1", AnswerChannel.RECOMMENDED),
            ("D2", AnswerChannel.RECOMMENDED),
            ("C1", AnswerChannel.RECOMMENDED),
            ("Q1", AnswerChannel.RECOMMENDED),
            ("A1", AnswerChannel.APP),
        ]

    def test_done_with_every_block_answered_leaves_the_text(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp plan",
            SETTLED,
        )
        published_at = document.published_at

        container.record_service().done(item, person)

        assert (document.published_text, document.published_at) == (
            SETTLED,
            published_at,
        )
        assert _done(item) == (item.done_at, "marked", person.id)
        assert _versions(session, document) == [
            (1, VersionCause.BORN, SETTLED),
            (2, VersionCause.DONE, SETTLED),
        ]

    def test_done_is_refused_while_a_block_has_neither(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp chores",
            UNREADY,
        )

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().done(item, person)

        assert refused.value.cause == (
            "these blocks have neither an answer nor a recommendation: Q1, A1"
        )
        assert document.published_text == UNREADY
        assert _done(item) == (None, None, None)
        assert len(_versions(session, document)) == 1

    def test_pilots_done_settles_a_document_answered_whole(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp plan",
            SETTLED,
        )
        agent = _agent(session)

        container.record_service().done(item, agent)

        assert _done(item) == (item.done_at, "settled", agent.id)
        assert document.published_text == SETTLED
        assert [cause for _, cause, _ in _versions(session, document)] == [
            VersionCause.BORN,
            VersionCause.DONE,
        ]

    def test_pilots_done_records_no_recommendation(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp plan",
            RECOMMENDED,
        )

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().done(item, _agent(session))

        assert refused.value.cause == (
            "Pilot marks done only a document it settled whole, and these blocks"
            " are unanswered: D1, D2, C1, Q1"
        )
        assert document.published_text == RECOMMENDED

    def test_done_is_refused_on_an_item_that_is_no_document(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, _ = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().done(item, person)

        assert refused.value.cause == "a decision item is not done by Done"

    @pytest.mark.parametrize("kind", ["work", "card_wait"])
    def test_done_is_refused_on_an_item_without_text(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        kind: str,
    ) -> None:
        item = _textless(session, project, project_session, kind)

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().done(item, person)

        assert refused.value.cause == f"a {kind} item is not done by Done"
        assert _done(item) == (None, None, None)

    def test_done_on_a_done_document_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp plan",
            SETTLED,
        )
        records = container.record_service()
        records.done(item, person)

        with pytest.raises(InvalidOperationException) as refused:
            records.done(item, person)

        assert refused.value.cause == "the item is done"
        assert len(_versions(session, document)) == 2


class TestRecordServiceMarks:
    @pytest.mark.parametrize(
        ("kind", "mark"), [("notice", "read"), ("review", "reviewed")]
    )
    def test_a_mark_is_the_items_and_leaves_the_text(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        kind: str,
        mark: str,
    ) -> None:
        item, document = _bear(
            session, container, project, project_session, kind, "The palette", NOTICE
        )
        published_at = document.published_at
        before = datetime.now(UTC).replace(microsecond=0)

        getattr(container.record_service(), mark)(item, person)

        assert item.done_at is not None
        assert before <= item.done_at <= datetime.now(UTC)
        assert _done(item) == (item.done_at, "marked", person.id)
        assert (document.published_text, document.published_at) == (
            NOTICE,
            published_at,
        )
        assert len(_versions(session, document)) == 1

    @pytest.mark.parametrize(
        ("kind", "mark", "cause"),
        [
            ("review", "read", "a review item is not marked Read"),
            ("notice", "reviewed", "a notice item is not marked Reviewed"),
            ("decision", "read", "a decision item is not marked Read"),
        ],
    )
    def test_a_mark_of_another_kind_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        kind: str,
        mark: str,
        cause: str,
    ) -> None:
        text = DECISION if kind == "decision" else NOTICE
        item, _ = _bear(
            session, container, project, project_session, kind, "The palette", text
        )

        with pytest.raises(InvalidOperationException) as refused:
            getattr(container.record_service(), mark)(item, person)

        assert refused.value.cause == cause
        assert _done(item) == (None, None, None)

    @pytest.mark.parametrize(
        ("kind", "mark", "cause"),
        [
            ("work", "read", "a work item is not marked Read"),
            ("card_wait", "reviewed", "a card_wait item is not marked Reviewed"),
        ],
    )
    def test_a_mark_on_an_item_without_text_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        kind: str,
        mark: str,
        cause: str,
    ) -> None:
        item = _textless(session, project, project_session, kind)

        with pytest.raises(InvalidOperationException) as refused:
            getattr(container.record_service(), mark)(item, person)

        assert refused.value.cause == cause
        assert _done(item) == (None, None, None)

    @pytest.mark.parametrize("mark", ["read", "reviewed"])
    def test_pilot_marks_no_read_or_reviewed(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        mark: str,
    ) -> None:
        kind = "notice" if mark == "read" else "review"
        item, _ = _bear(
            session, container, project, project_session, kind, "The palette", NOTICE
        )

        with pytest.raises(InvalidOperationException) as refused:
            getattr(container.record_service(), mark)(item, _agent(session))

        assert refused.value.cause == (
            "Pilot marks done only a document it settled whole"
        )

    def test_a_mark_on_a_done_item_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, _ = _bear(
            session,
            container,
            project,
            project_session,
            "notice",
            "The palette",
            NOTICE,
        )
        records = container.record_service()
        records.read(item, person)

        with pytest.raises(InvalidOperationException) as refused:
            records.read(item, person)

        assert refused.value.cause == "the item is done"


FINISH = datetime(2026, 10, 19, 15, 0, 1, 250000, tzinfo=UTC)
"""Finish's instant, kept whole by the close."""


class TestRecordServiceCloseUnanswered:
    def test_every_open_item_but_the_opening_is_done_unanswered(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        documents = container.document_service()
        opening = documents.bear_opening(project, "Camp", person, "Let's camp.\n")
        decision, _ = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )
        notice, _ = _bear(
            session, container, project, project_session, "notice", "Palette", NOTICE
        )
        work = _textless(session, project, project_session, "work", seq=4)
        wait = _textless(session, project, project_session, "timed_wait", seq=5)
        records = container.record_service()
        records.read(notice, person)
        read = _done(notice)

        records.close_unanswered(project, person, FINISH)

        assert [_done(item) for item in (decision, work, wait)] == [
            (FINISH, "finished", person.id)
        ] * 3
        assert _done(notice) == read
        assert _done(opening) == (None, None, None)

    def test_the_text_is_untouched(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        _, document = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )
        versions = _versions(session, document)

        container.record_service().close_unanswered(project, person, FINISH)

        assert document.published_text == DECISION
        assert _versions(session, document) == versions

    def test_a_closed_item_offers_no_undo(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, _ = _bear(
            session, container, project, project_session, "notice", "Palette", NOTICE
        )
        records = container.record_service()
        records.close_unanswered(project, person, FINISH)

        with pytest.raises(InvalidOperationException) as refused:
            records.undo(item)

        assert refused.value.cause == "an item done as finished offers no undo"

    def test_another_projects_items_stay_open(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        item, _ = _bear(
            session, container, project, project_session, "notice", "Palette", NOTICE
        )

        container.record_service().close_unanswered(other, person, FINISH)

        assert _done(item) == (None, None, None)

    def test_the_close_moves_the_timeline_once(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        for title in ("Palette", "Badges"):
            _bear(session, container, project, project_session, "notice", title, NOTICE)
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            container.record_service().close_unanswered(project, person, FINISH)

        assert engine_events == [
            TreeHashMoved(
                f"draft-{project.number}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
        ]

    def test_with_nothing_open_nothing_moves(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        person: User,
    ) -> None:
        with scoped_session(container):
            container.record_service().close_unanswered(project, person, FINISH)

        assert engine_events == []


class TestRecordServiceEvents:
    def test_an_answer_moves_its_path_and_the_timeline_and_modifies_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            container.record_service().answer(document, "D1", person, "Tunnel")
            assert engine_events == []

        assert document.published_text is not None
        assert engine_events == [
            TreeHashMoved(
                f"draft-{project.number}/items/1-which-tent.md",
                sha256_hex(document.published_text),
            ),
            ProjectChanged(project.id),
            TreeHashMoved(
                f"draft-{project.number}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
        ]

    def test_an_answer_in_a_document_moves_its_path_and_its_project(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp plan",
            TWO_ASKS,
        )
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            container.record_service().answer(document, "D1", person, "Dome")

        assert document.published_text is not None
        assert engine_events == [
            TreeHashMoved(
                f"draft-{project.number}/items/1-camp-plan.md",
                sha256_hex(document.published_text),
            ),
            ProjectChanged(project.id),
        ]

    @pytest.mark.parametrize("write", ["read", "undo"])
    def test_a_mark_and_its_undo_move_the_timeline_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
        write: str,
    ) -> None:
        item, _ = _bear(
            session,
            container,
            project,
            project_session,
            "notice",
            "The palette",
            NOTICE,
        )
        records = container.record_service()
        if write == "undo":
            records.read(item, person)
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            if write == "undo":
                records.undo(item)
            else:
                records.read(item, person)

        assert engine_events == [
            TreeHashMoved(
                f"draft-{project.number}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
        ]

    def test_done_moves_its_path_and_the_timeline(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "document",
            "Camp plan",
            RECOMMENDED,
        )
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            container.record_service().done(item, person)

        assert document.published_text is not None
        assert engine_events == [
            TreeHashMoved(
                f"draft-{project.number}/items/1-camp-plan.md",
                sha256_hex(document.published_text),
            ),
            ProjectChanged(project.id),
            TreeHashMoved(
                f"draft-{project.number}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
        ]

    def test_the_timeline_shows_the_done(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )

        container.record_service().answer(document, "D1", person, "Tunnel")

        shown = json.loads(container.view_service().timeline(project).text)
        assert shown["items"][0]["done"] == {
            "at": _z(item.done_at),
            "cause": "answered",
            "by": "ada",
        }


class TestRecordServiceSequences:
    """Design 1 §5.8's second sequence and the held case of §5.2, through the
    fake sidecar."""

    def test_a_record_write_reaches_the_file(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, DECISION
            )
        fake_sidecar.drain()
        path = f"draft-{project.number}/items/1-which-tent.md"
        document = session.get_one(Document, item.id)

        with scoped_session(container):
            container.record_service().answer(document, "D1", person, "Tunnel")

        assert fake_sidecar.drain() == [path, f"draft-{project.number}/timeline.json"]
        assert fake_sidecar.text(path) == document.published_text

        with scoped_session(container):
            container.record_service().undo(item)

        assert fake_sidecar.drain() == [path, f"draft-{project.number}/timeline.json"]
        assert fake_sidecar.text(path) == DECISION

    def test_a_write_while_held_rides_the_next_clean_save(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "document", "Camp plan", project_session, TWO_ASKS
            )
        fake_sidecar.drain()
        path = f"draft-{project.number}/items/1-camp-plan.md"
        broken = TWO_ASKS + "\n```question id=Q2\n"
        fake_sidecar.save(path, broken)
        assert container.tree_service().held_path(path)
        document = session.get_one(Document, item.id)

        with scoped_session(container):
            container.record_service().answer(document, "D1", person, "Dome")

        answered = document.published_text
        assert answered is not None
        assert "answer: Dome\nby: ada\n" in answered
        assert fake_sidecar.drain() == []
        assert container.tree_service().read(path).content == broken.encode()

        fixed = TWO_ASKS.replace("# Camp plan\n", "# Camp plan\n\nRain is due.\n")
        answer = fake_sidecar.save(path, fixed)

        merged = answered.replace("# Camp plan\n", "# Camp plan\n\nRain is due.\n")
        assert not container.tree_service().held_path(path)
        assert answer.content == merged.encode()
        assert fake_sidecar.text(path) == merged
        assert document.published_text == merged


ENVIRONMENT_ID = "example-env-1"


def _committed_items(app: Flask) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A draft project with a decision and a notice, committed: the
    person's id and the two items'."""
    container = app.container
    with scoped_session(container) as session:
        person = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        session.add(person)
        session.flush()
        project = Project(created_by_user_id=person.id)
        session.add(project)
        session.add(Environment(id=ENVIRONMENT_ID, name="Example-1", exempt=False))
        session.flush()
        run = models.Session(
            project_id=project.id,
            environment_id=ENVIRONMENT_ID,
            kind_code="work",
            cwd="/work/Example",
            token_hash="1" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(run)
        session.flush()
        documents = container.document_service()
        decision = documents.bear_item(
            project, "decision", "Which tent?", run, DECISION
        )
        notice = documents.bear_item(project, "notice", "The palette", run, NOTICE)
        return person.id, decision.id, notice.id


class TestRecordServiceRowLock:
    """A record write and an ingest of one document never interleave (TD
    §8.5)."""

    @pytest.mark.parametrize("write", ["answer", "read"])
    def test_a_write_waits_for_the_documents_row(
        self, committed_app: Flask, write: str
    ) -> None:
        person_id, decision_id, notice_id = _committed_items(committed_app)
        item_id = decision_id if write == "answer" else notice_id
        container = committed_app.container
        with committed_app.app_context():
            engine = db.engine

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM documents WHERE id = :id FOR KEY SHARE"),
                {"id": item_id},
            )
            with (
                pytest.raises(OperationalError) as raised,
                scoped_session(container) as session,
            ):
                session.execute(sql("SET LOCAL lock_timeout = '200ms'"))
                records = container.record_service()
                person = session.get_one(User, person_id)
                if write == "answer":
                    records.answer(
                        session.get_one(Document, item_id), "D1", person, "Tunnel"
                    )
                else:
                    records.read(session.get_one(Item, item_id), person)
            holder.rollback()

        assert isinstance(raised.value.orig, LockNotAvailable)
        with scoped_session(container) as session:
            assert session.get_one(Item, item_id).done_at is None
            assert session.get_one(Document, decision_id).published_text == DECISION

    def test_the_close_waits_for_an_open_items_document_row(
        self, committed_app: Flask
    ) -> None:
        person_id, decision_id, notice_id = _committed_items(committed_app)
        container = committed_app.container
        with committed_app.app_context():
            engine = db.engine

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM documents WHERE id = :id FOR KEY SHARE"),
                {"id": notice_id},
            )
            with (
                pytest.raises(OperationalError) as raised,
                scoped_session(container) as session,
            ):
                session.execute(sql("SET LOCAL lock_timeout = '200ms'"))
                person = session.get_one(User, person_id)
                project = session.get_one(
                    Project, session.get_one(Item, notice_id).project_id
                )
                container.record_service().close_unanswered(project, person, FINISH)
            holder.rollback()

        assert isinstance(raised.value.orig, LockNotAvailable)
        with scoped_session(container) as session:
            assert [
                session.get_one(Item, item_id).done_at
                for item_id in (decision_id, notice_id)
            ] == [None, None]
