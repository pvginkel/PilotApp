"""The record's own writes: a person's answer, Done on an action, undo, Done
on a document, Read and Reviewed (design 1 §6.4, F32.4); a work item's place
and its done at its turn's end (DB Work, decision 44); the close that continues
a run whose documents are all closed (decision 44; reviews 1 and 3); and the
close of an item of Pilot's own that places the job after it, which its Undo
withdraws before its brief (DB decision 45; F14.1; V24, V29)."""

import json
import uuid
from datetime import UTC, datetime

import pilot_dsl
import pytest
from dependency_injector import providers
from flask import Flask
from psycopg.errors import LockNotAvailable
from sqlalchemy import select
from sqlalchemy import text as sql
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged, TreeHashMoved, WriteBackOwed
from app.engine.paths import sha256_hex, tree_path
from app.engine.record import (
    autopilot_may_take,
    owes_write_back,
    resume_message,
    write_back_owed,
)
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
    Turn,
    User,
    Work,
)
from app.models.reference import (
    AnswerChannel,
    ProjectState,
    SessionState,
    TaskStatus,
    TransitionKind,
    UserKind,
    VersionCause,
    WorkTrigger,
)
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.job_service import NEXT_TITLE
from app.services.session_scope import STORE_REPO
from app.services.timeline_service import waiting_on
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.fake_sidecar import FakeSidecar
from tests.support.locks import in_thread, lock_waits
from tests.support.starts import configured_starts
from tests.support.supervisor import Supervise, wait_until

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

CLAIMED = """---
title: Cut-over plan
---

```decision id=D1
options:
  - Dome
  - Tunnel
answer: Dome
by: agent
at: 2026-10-12T09:30:00Z
```

```action id=A1
answer: Pilot does it
by: agent
at: 2026-10-12T09:30:00Z
note: Rotating the CI token
```
"""

CLAIMED_ACTION = """---
title: Rotate the CI token
---

```action id=A1
answer: Pilot does it
by: agent
at: 2026-10-12T09:30:00Z
```
"""

SETTLED_ONE_BLOCK = {
    "answered": """---
title: Which tent?
---

```decision id=D1
options:
  - Dome
  - Tunnel
answer: Dome
by: agent
at: 2026-10-12T09:30:00Z
```
""",
    "deferred": """---
title: Where to camp?
---

```question id=Q1
answer: deferred
by: agent
at: 2026-10-12T09:30:00Z
to: plan
```
""",
    "claimed-and-done": """---
title: Rotate the CI token
---

```action id=A1
done: 2026-10-12T10:30:00Z
by: agent
note: Rotated; the runners took the new token
```
""",
}


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


def _writer_without_the_block(
    monkeypatch: pytest.MonkeyPatch, writer: str, local_id: str
) -> None:
    """The DSL's `writer` handed the text with block `local_id` gone, which
    the engine's own look-up of the block keeps from it: its real refusal."""
    real = getattr(pilot_dsl, writer)
    monkeypatch.setattr(
        pilot_dsl,
        writer,
        lambda text, *args, **kwargs: real(
            text.replace(f"id={local_id}", "id=Z9"), *args, **kwargs
        ),
    )


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

    def test_a_refusal_of_the_writer_is_an_invalid_operation(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        monkeypatch: pytest.MonkeyPatch,
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
        _writer_without_the_block(monkeypatch, "write_answer", "D1")

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().answer(document, "D1", person, "Tunnel")

        assert refused.value.message == (
            "Cannot write an answer into block D1 because the text has no block D1"
        )
        assert document.published_text == DECISION


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

    def test_a_refusal_of_the_writer_is_an_invalid_operation(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, document = _bear(
            session,
            container,
            project,
            project_session,
            "action",
            "Put the key into OpenBao",
            ACTION,
        )
        _writer_without_the_block(monkeypatch, "write_done", "A1")

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().done_action(document, "A1", person)

        assert refused.value.message == (
            "Cannot mark block A1 done because the text has no block A1"
        )
        assert document.published_text == ACTION

    def test_a_persons_done_on_an_action_pilot_claimed_closes_it_as_any_done(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _registered(
            session, container, project, project_session, CLAIMED_ACTION
        )

        with scoped_session(container):
            container.record_service().done_action(
                document, "A1", person, note="Rotated it myself"
            )

        assert _done(item) == (item.done_at, "answered", person.id)
        [block] = pilot_dsl.parse(document.published_text or "").blocks
        assert (block.done, block.by, block.answer, block.note) == (
            item.done_at,
            "ada",
            None,
            "Rotated it myself",
        )
        assert not block.claimed
        assert _owed_events(engine_events) == [WriteBackOwed(project_session.id)]


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

    def test_a_refusal_of_the_writer_is_an_invalid_operation(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        monkeypatch: pytest.MonkeyPatch,
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
        _writer_without_the_block(monkeypatch, "clear_answer", "D1")

        with pytest.raises(InvalidOperationException) as refused:
            records.undo(item)

        assert refused.value.message == (
            "Cannot undo the answer of block D1 because the text has no block D1"
        )
        assert document.published_text == answered


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

    def test_pilots_done_is_refused_while_an_action_it_claimed_is_not_done(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item, document = _registered(
            session, container, project, project_session, CLAIMED
        )

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().done(item, _agent(session))

        assert refused.value.cause == (
            "Pilot marks done only a document it settled whole, and these blocks"
            " are unanswered: A1"
        )
        assert _done(item) == (None, None, None)
        assert document.published_text == CLAIMED

    def test_a_persons_done_is_refused_while_a_claimed_action_has_no_recommendation(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, _ = _registered(session, container, project, project_session, CLAIMED)

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().done(item, person)

        assert refused.value.cause == (
            "these blocks have neither an answer nor a recommendation: A1"
        )

    @pytest.mark.parametrize(
        ("settled", "kind"),
        [
            ("answered", "decision"),
            ("deferred", "question"),
            ("claimed-and-done", "action"),
        ],
    )
    def test_pilots_done_takes_a_registered_document_of_one_block_it_settled(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        settled: str,
        kind: str,
    ) -> None:
        run = _ended_run(container, project, project_session)
        item, document = _registered(
            session, container, project, run, SETTLED_ONE_BLOCK[settled]
        )
        assert item.kind_code == kind
        agent = _agent(session)

        with scoped_session(container):
            container.record_service().done(item, agent)

        assert _done(item) == (item.done_at, "settled", agent.id)
        assert _owed_events(engine_events) == [WriteBackOwed(run.id)]
        (continuation,) = _continuations(session, project)
        assert continuation.trigger_item_id == item.id
        assert item.consumed_session_id == continuation.id

    def test_pilots_done_is_refused_on_a_one_block_document_still_claimed(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item, _ = _registered(
            session, container, project, project_session, CLAIMED_ACTION
        )

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().done(item, _agent(session))

        assert refused.value.cause == (
            "Pilot marks done only a document it settled whole, and these blocks"
            " are unanswered: A1"
        )

    def test_a_one_block_item_not_registered_or_a_persons_done_is_refused_by_kind(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        pilots, _ = _bear(
            session,
            container,
            project,
            project_session,
            "decision",
            "Which tent?",
            SETTLED_ONE_BLOCK["answered"],
        )
        registered, _ = _registered(
            session,
            container,
            project,
            project_session,
            SETTLED_ONE_BLOCK["deferred"],
        )
        records = container.record_service()

        with pytest.raises(InvalidOperationException) as not_registered:
            records.done(pilots, _agent(session))
        with pytest.raises(InvalidOperationException) as a_persons:
            records.done(registered, person)

        assert not_registered.value.cause == "a decision item is not done by Done"
        assert a_persons.value.cause == "a question item is not done by Done"


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


_AWAITING = (
    "its file has not been read yet: it is read at the end of the turn that"
    " registered it"
)


class TestRecordServiceAwaitingRead:
    """A registered document takes no close before its read at the end of the
    turn that registered it (review 7); Finish's close still takes it."""

    @pytest.mark.parametrize(
        ("close", "operation"),
        [
            ("reviewed", "mark {path} Reviewed"),
            ("read", "mark {path} Read"),
            ("done", "mark {path} done"),
            ("answer", "answer block D1 of {path}"),
            ("done_action", "mark action A1 of {path} done"),
        ],
    )
    def test_every_close_is_refused_with_the_reason(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        close: str,
        operation: str,
    ) -> None:
        item = (
            container.document_service()
            .register(project, project_session, "/work/Example/refinement.md")
            .item
        )
        document = session.get_one(Document, item.id)
        records = container.record_service()

        with pytest.raises(InvalidOperationException) as refused:
            if close == "answer":
                records.answer(document, "D1", person, "Dome")
            elif close == "done_action":
                records.done_action(document, "A1", person)
            else:
                getattr(records, close)(item, person)

        path = f"draft-{project.number}/inbox/1-refinement.md"
        assert refused.value.operation == operation.format(path=path)
        assert refused.value.cause == _AWAITING
        assert _done(item) == (None, None, None)
        assert document.published_text is None

    def test_finishs_close_takes_it_and_it_awaits_nothing_more(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item = (
            container.document_service()
            .register(project, project_session, "/work/Example/refinement.md")
            .item
        )
        records = container.record_service()

        records.close_unanswered(project, person, FINISH)

        assert _done(item) == (FINISH, "finished", person.id)
        with pytest.raises(InvalidOperationException) as refused:
            records.reviewed(item, person)
        assert refused.value.cause == "the item is done"
        assert session.get_one(Document, item.id).published_text is None


class TestRecordServiceArchived:
    """An archived project takes Bring back alone (D012): its items take no
    close and no Undo, each refused naming the archive."""

    @pytest.mark.parametrize(
        ("close", "kind", "text", "operation"),
        [
            ("answer", "decision", DECISION, "answer block D1 of {path}"),
            ("done_action", "action", ACTION, "mark action A1 of {path} done"),
            ("done", "document", RECOMMENDED, "mark {path} done"),
            ("read", "notice", NOTICE, "mark {path} Read"),
            ("reviewed", "review", NOTICE, "mark {path} Reviewed"),
        ],
    )
    def test_every_close_is_refused_naming_the_archive(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        close: str,
        kind: str,
        text: str,
        operation: str,
    ) -> None:
        item, document = _bear(
            session, container, project, project_session, kind, "Camp", text
        )
        project.archived = True
        session.flush()
        records = container.record_service()

        with pytest.raises(InvalidOperationException) as refused:
            if close == "answer":
                records.answer(document, "D1", person, "Dome")
            elif close == "done_action":
                records.done_action(document, "A1", person)
            else:
                getattr(records, close)(item, person)

        path = tree_path(project, document.path)
        assert refused.value.operation == operation.format(path=path)
        assert refused.value.cause == "its project is archived"
        assert _done(item) == (None, None, None)
        assert document.published_text == text

    def test_undo_is_refused_naming_the_archive_and_not_offered(
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
        project.archived = True
        session.flush()

        assert records.offers_undo(item) is False
        with pytest.raises(InvalidOperationException) as refused:
            records.undo(item)

        assert refused.value.operation == f"undo item {item.id}"
        assert refused.value.cause == "its project is archived"
        assert item.done_cause_code == "answered"


class TestRecordServiceFailedRead:
    """A registered document whose read failed has no text and no block, and
    closes with Reviewed, as any document with none (ruling D1)."""

    @pytest.fixture
    def failed(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> Item:
        documents = container.document_service()
        item = documents.register(
            project, project_session, "/work/Example/refinement.md"
        ).item
        documents.fail_read(session.get_one(Document, item.id))
        return item

    def test_reviewed_closes_it_and_undo_reopens_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        person: User,
        failed: Item,
    ) -> None:
        records = container.record_service()

        records.reviewed(failed, person)

        assert _done(failed)[1:] == ("marked", person.id)
        assert records.offers_undo(failed)
        records.undo(failed)
        assert _done(failed) == (None, None, None)
        assert session.get_one(Document, failed.id).published_text is None

    @pytest.mark.parametrize(
        ("close", "cause"),
        [
            ("read", "a review item is not marked Read"),
            ("done", "a review item is not done by Done"),
        ],
    )
    def test_a_close_its_kind_does_not_take_is_refused(
        self,
        container: ServiceContainer,
        person: User,
        failed: Item,
        close: str,
        cause: str,
    ) -> None:
        with pytest.raises(InvalidOperationException) as refused:
            getattr(container.record_service(), close)(failed, person)

        assert refused.value.cause == cause
        assert _done(failed) == (None, None, None)

    @pytest.mark.parametrize("close", ["answer", "done_action"])
    def test_it_has_no_block_to_answer(
        self,
        session: DbSession,
        container: ServiceContainer,
        person: User,
        failed: Item,
        close: str,
    ) -> None:
        document = session.get_one(Document, failed.id)
        records = container.record_service()

        with pytest.raises(RecordNotFoundException):
            if close == "answer":
                records.answer(document, "D1", person, "Dome")
            else:
                records.done_action(document, "A1", person)

        assert _done(failed) == (None, None, None)
        assert document.published_text is None


REGISTERED_PATH = "/work/Example/refinement.md"


def _registered(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    project_session: models.Session,
    text: str,
    path: str = REGISTERED_PATH,
) -> tuple[Item, Document]:
    """A document `project_session` registered, read at the end of its run."""
    documents = container.document_service()
    item = documents.register(project, project_session, path).item
    document = session.get_one(Document, item.id)
    documents.publish_read(document, text, project_session.id)
    return item, document


def _owed_events(events: list[EngineEvent]) -> list[EngineEvent]:
    return [event for event in events if isinstance(event, WriteBackOwed)]


class TestRecordServiceWriteBackOwed:
    """A close of a registered document owes its text, the answers in it, to
    its file once it commits (F65.1); Finish's close owes none (review 4)."""

    @pytest.mark.parametrize(
        ("text", "close"),
        [
            pytest.param(RECOMMENDED, "done", id="done"),
            pytest.param(DECISION, "answer", id="the-answer-that-closes-it"),
            pytest.param(ACTION, "done_action", id="the-done-that-closes-it"),
            pytest.param(NOTICE, "reviewed", id="reviewed"),
        ],
    )
    def test_a_close_owes_its_write_back_once_it_commits(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
        text: str,
        close: str,
    ) -> None:
        item, document = _registered(session, container, project, project_session, text)
        records = container.record_service()

        with scoped_session(container):
            if close == "answer":
                records.answer(document, "D1", person, "Tunnel")
            elif close == "done_action":
                records.done_action(document, "A1", person)
            else:
                getattr(records, close)(item, person)
            assert _owed_events(engine_events) == []

        assert item.done_at is not None
        assert owes_write_back(item, document)
        assert _owed_events(engine_events) == [WriteBackOwed(project_session.id)]

    def test_an_answer_that_leaves_it_open_owes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _registered(
            session, container, project, project_session, TWO_ASKS
        )

        with scoped_session(container):
            container.record_service().answer(document, "D1", person, "Dome")

        assert not owes_write_back(item, document)
        assert _owed_events(engine_events) == []

    def test_finishs_close_owes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item, document = _registered(
            session, container, project, project_session, DECISION
        )

        with scoped_session(container):
            container.record_service().close_unanswered(project, person, FINISH)

        assert item.done_cause_code == "finished"
        assert not owes_write_back(item, document)
        assert _owed_events(engine_events) == []

    def test_a_document_whose_read_failed_owes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        documents = container.document_service()
        item = documents.register(project, project_session, REGISTERED_PATH).item
        document = session.get_one(Document, item.id)
        documents.fail_read(document)

        with scoped_session(container):
            container.record_service().reviewed(item, person)

        assert item.done_at is not None
        assert not owes_write_back(item, document)
        assert _owed_events(engine_events) == []

    def test_a_document_pilot_added_owes_nothing(
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
            container.record_service().answer(document, "D1", person, "Tunnel")

        assert item.done_at is not None
        assert not owes_write_back(item, document)
        assert _owed_events(engine_events) == []

    @pytest.mark.parametrize("outcome", ["wrote_back", "refuse_write_back"])
    def test_undo_clears_its_write_back_and_its_next_close_owes_it_again(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
        outcome: str,
    ) -> None:
        item, document = _registered(
            session, container, project, project_session, DECISION
        )
        records = container.record_service()
        records.answer(document, "D1", person, "Tunnel")
        getattr(container.document_service(), outcome)(document)
        assert not owes_write_back(item, document)

        records.undo(item)

        assert (document.written_back_at, document.write_back_refused_at) == (
            None,
            None,
        )
        assert not owes_write_back(item, document)
        with scoped_session(container):
            records.answer(document, "D1", person, "Dome")
        assert owes_write_back(item, document)
        assert _owed_events(engine_events) == [WriteBackOwed(project_session.id)]

    def test_the_querys_condition_names_the_documents_owed(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        records = container.record_service()
        documents = container.document_service()
        made: list[tuple[Item, Document]] = []
        for number in range(5):
            made.append(
                _registered(
                    session,
                    container,
                    project,
                    project_session,
                    DECISION,
                    f"/work/Example/doc-{number}.md",
                )
            )
        (owed, _), (_, written), (_, refused) = made[:3]
        for _, document in made[:3]:
            records.answer(document, "D1", person, "Tunnel")
        documents.wrote_back(written)
        documents.refuse_write_back(refused)
        # The fourth stays open; Finish closes it, and the fifth with it.
        records.answer(made[4][1], "D1", person, "Dome")
        records.undo(made[4][0])
        records.close_unanswered(project, person, FINISH)

        named = session.scalars(
            select(Document.id)
            .join(Item, Item.id == Document.id)
            .where(write_back_owed())
        ).all()

        assert named == [owed.id]
        assert [owes_write_back(item, document) for item, document in made] == [
            True,
            False,
            False,
            False,
            False,
        ]


SURVEY_PATH = "/work/Example/survey.md"
CONTINUED = (
    "Your documents were answered and written back in place: {paths}."
    " Read the answers and continue."
)


def _ended_run(
    container: ServiceContainer, project: Project, run: models.Session
) -> models.Session:
    """`run` placed as a work item whose run ended on its conversation, its
    work item done at its turn's end (decision 44)."""
    run.conversation_id = "conv-1"
    run.state_code = SessionState.IDLE
    records = container.record_service()
    records.place_work(project, run, "Refining the camp", repo="example/Example")
    records.work_done(run.id, datetime.now(UTC))
    return run


def _continuations(session: DbSession, project: Project) -> list[Work]:
    """The project's work items that continue a run (decision 44)."""
    return list(
        session.scalars(
            select(Work)
            .where(Work.project_id == project.id, Work.trigger_item_id.is_not(None))
            .execution_options(populate_existing=True)
        )
    )


def _first_message(session: DbSession, work: Work) -> str:
    (turn,) = session.scalars(select(Turn).where(Turn.session_id == work.id))
    return turn.message


class TestRecordServiceRelease:
    """The close that leaves no document of a work item's ended run open
    continues its conversation as a new work item in its transaction, every
    document of the run consumed by it, its Undo gone (decision 44; review 1;
    V11, V13)."""

    def test_the_last_close_continues_the_run_and_consumes_its_documents(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        run = _ended_run(container, project, project_session)
        decision, document = _registered(session, container, project, run, DECISION)
        survey, _ = _registered(session, container, project, run, NOTICE, SURVEY_PATH)
        records = container.record_service()
        records.answer(document, "D1", person, "Tunnel")
        assert _continuations(session, project) == []
        assert records.offers_undo(decision)

        records.reviewed(survey, person)

        (work,) = _continuations(session, project)
        item = session.get_one(Item, work.id)
        continuation = session.get_one(models.Session, work.id)
        assert (item.kind_code, item.title, item.seq) == (
            "work",
            "Refining the camp",
            survey.seq + 1,
        )
        assert item.created_by_session_id == continuation.id
        assert item.done_at is None
        assert (work.trigger_item_id, work.trigger_code, work.repo) == (
            survey.id,
            None,
            "example/Example",
        )
        assert (
            continuation.kind_code,
            continuation.environment_id,
            continuation.conversation_id,
            continuation.cwd,
        ) == ("work", run.environment_id, "conv-1", run.cwd)
        assert _first_message(session, work) == CONTINUED.format(
            paths=f"{REGISTERED_PATH}, {SURVEY_PATH}"
        )
        for each in (decision, survey):
            assert each.consumed_session_id == continuation.id
            assert each.consumed_at is not None
            assert not records.offers_undo(each)
        with pytest.raises(InvalidOperationException) as refused:
            records.undo(decision)
        assert refused.value.cause == "a session has taken the item's answers"

    @pytest.mark.parametrize(
        ("text", "close"),
        [
            pytest.param(RECOMMENDED, "done", id="done"),
            pytest.param(DECISION, "answer", id="the-answer-that-closes-it"),
            pytest.param(ACTION, "done_action", id="the-done-that-closes-it"),
            pytest.param(NOTICE, "reviewed", id="reviewed"),
        ],
    )
    def test_each_close_of_the_last_document_continues_the_run(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        text: str,
        close: str,
    ) -> None:
        run = _ended_run(container, project, project_session)
        item, document = _registered(session, container, project, run, text)
        records = container.record_service()

        if close == "answer":
            records.answer(document, "D1", person, "Tunnel")
        elif close == "done_action":
            records.done_action(document, "A1", person)
        else:
            getattr(records, close)(item, person)

        (work,) = _continuations(session, project)
        assert work.trigger_item_id == item.id
        assert item.consumed_session_id == work.id

    def test_a_document_whose_read_failed_is_named_could_not_be_read(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        run = _ended_run(container, project, project_session)
        _, document = _registered(session, container, project, run, DECISION)
        documents = container.document_service()
        unread = documents.register(project, run, SURVEY_PATH).item
        documents.fail_read(session.get_one(Document, unread.id))
        records = container.record_service()
        records.answer(document, "D1", person, "Tunnel")

        records.reviewed(unread, person)

        (work,) = _continuations(session, project)
        assert _first_message(session, work) == (
            CONTINUED.format(paths=REGISTERED_PATH)
            + f"\nCould not be read: {SURVEY_PATH}."
        )
        assert unread.consumed_session_id == work.id

    def test_with_every_read_failed_its_message_names_them_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        run = _ended_run(container, project, project_session)
        documents = container.document_service()
        unread = documents.register(project, run, SURVEY_PATH).item
        documents.fail_read(session.get_one(Document, unread.id))

        container.record_service().reviewed(unread, person)

        (work,) = _continuations(session, project)
        assert _first_message(session, work) == f"Could not be read: {SURVEY_PATH}."

    def test_an_answer_that_leaves_the_last_document_open_continues_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        run = _ended_run(container, project, project_session)
        item, document = _registered(session, container, project, run, TWO_ASKS)

        container.record_service().answer(document, "D1", person, "Dome")

        assert _continuations(session, project) == []
        assert item.consumed_at is None

    def test_a_run_not_ended_continues_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        container.record_service().place_work(
            project, project_session, "Refining the camp", repo="example/Example"
        )
        item, document = _registered(
            session, container, project, project_session, DECISION
        )

        container.record_service().answer(document, "D1", person, "Tunnel")

        assert item.done_at is not None
        assert _continuations(session, project) == []
        assert item.consumed_at is None

    def test_finishs_close_continues_nothing_nor_does_a_later_close(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        # Review 4: Finish's close ends the round trip.
        run = _ended_run(container, project, project_session)
        decision, document = _registered(session, container, project, run, DECISION)
        survey, _ = _registered(session, container, project, run, NOTICE, SURVEY_PATH)
        records = container.record_service()
        records.answer(document, "D1", person, "Tunnel")

        records.close_unanswered(project, person, FINISH)
        records.undo(decision)
        records.answer(document, "D1", person, "Dome")

        assert survey.done_cause_code == "finished"
        assert _continuations(session, project) == []
        assert (decision.consumed_at, survey.consumed_at) == (None, None)

    def test_the_consumption_moves_the_project_once_it_commits(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        run = _ended_run(container, project, project_session)
        item, _ = _registered(session, container, project, run, NOTICE)
        clear_after_commit_callbacks()

        with scoped_session(container):
            container.record_service().reviewed(item, person)
            assert engine_events == []

        assert item.consumed_at is not None
        assert ProjectChanged(project.id) in engine_events

    def test_in_an_archived_project_the_last_close_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        run = _ended_run(container, project, project_session)
        item, _ = _registered(session, container, project, run, NOTICE)
        project.archived = True
        session.flush()

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().reviewed(item, person)

        # Refused as every close there is (D012), before it would continue.
        path = tree_path(project, session.get_one(Document, item.id).path)
        assert refused.value.operation == f"mark {path} Reviewed"
        assert refused.value.cause == "its project is archived"
        assert _continuations(session, project) == []


class TestRecordServiceRetryWriteBacks:
    """A Resume of a continuation owes again the write-backs the controller
    refused of the documents it carries (F125)."""

    def test_the_refused_write_backs_it_carries_are_owed_again(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        run = _ended_run(container, project, project_session)
        item, document = _registered(session, container, project, run, NOTICE)
        # Another run's document, refused: no continuation carries it.
        other = models.Session(
            project_id=project.id,
            environment_id=run.environment_id,
            kind_code="work",
            cwd="/work/Example",
            token_hash="2" * 64,
            state_code=SessionState.IDLE,
        )
        session.add(other)
        session.flush()
        _, elsewhere = _registered(session, container, project, other, NOTICE)
        records = container.record_service()
        records.reviewed(item, person)
        records.reviewed(session.get_one(Item, elsewhere.id), person)
        documents = container.document_service()
        documents.refuse_write_back(document)
        documents.refuse_write_back(elsewhere)
        (work,) = _continuations(session, project)
        clear_after_commit_callbacks()

        with scoped_session(container):
            records.retry_write_backs(work.id)

        assert document.write_back_refused_at is None
        assert owes_write_back(item, document)
        assert elsewhere.write_back_refused_at is not None
        assert _owed_events(engine_events) == [WriteBackOwed(run.id)]

    def test_with_none_refused_it_changes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        run = _ended_run(container, project, project_session)
        item, document = _registered(session, container, project, run, NOTICE)
        container.record_service().reviewed(item, person)
        container.document_service().wrote_back(document)
        (work,) = _continuations(session, project)
        clear_after_commit_callbacks()

        with scoped_session(container):
            container.record_service().retry_write_backs(work.id)

        assert document.written_back_at is not None
        assert _owed_events(engine_events) == []


class TestResumeMessage:
    def test_it_names_the_documents_written_back_then_those_not_read(self) -> None:
        assert resume_message(["/work/a.md", "/work/b.md"], ["/work/c.md"]) == (
            "Your documents were answered and written back in place: /work/a.md,"
            " /work/b.md. Read the answers and continue.\n"
            "Could not be read: /work/c.md."
        )

    def test_each_line_only_when_it_names_one(self) -> None:
        assert resume_message(["/work/a.md"], []) == (
            "Your documents were answered and written back in place: /work/a.md."
            " Read the answers and continue."
        )
        assert resume_message([], ["/work/c.md", "/work/d.md"]) == (
            "Could not be read: /work/c.md, /work/d.md."
        )


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

    def test_undo_waits_for_the_projects_row(self, committed_app: Flask) -> None:
        person_id, decision_id, _ = _committed_items(committed_app)
        container = committed_app.container
        with scoped_session(container) as session:
            container.record_service().answer(
                session.get_one(Document, decision_id),
                "D1",
                session.get_one(User, person_id),
                "Tunnel",
            )
            project_id = session.get_one(Item, decision_id).project_id
        with committed_app.app_context():
            engine = db.engine

        # What Finish and Reopen hold while they change the project's state.
        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR NO KEY UPDATE"),
                {"id": project_id},
            )
            with (
                pytest.raises(OperationalError) as raised,
                scoped_session(container) as session,
            ):
                session.execute(sql("SET LOCAL lock_timeout = '200ms'"))
                container.record_service().undo(session.get_one(Item, decision_id))
            holder.rollback()

        assert isinstance(raised.value.orig, LockNotAvailable)
        with scoped_session(container) as session:
            assert session.get_one(Item, decision_id).done_cause_code == "answered"

    @pytest.mark.parametrize("write", ["answer", "read"])
    def test_a_close_waits_for_the_projects_row(
        self, committed_app: Flask, write: str
    ) -> None:
        person_id, decision_id, notice_id = _committed_items(committed_app)
        item_id = decision_id if write == "answer" else notice_id
        container = committed_app.container
        with scoped_session(container) as session:
            project_id = session.get_one(Item, item_id).project_id
        with committed_app.app_context():
            engine = db.engine

        # What Archive holds while it changes the project's standing (D012).
        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR NO KEY UPDATE"),
                {"id": project_id},
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


ADA = AuthContext(
    subject="subject-ada", email=None, name="Ada Example", roles={"editor"}
)
"""The person `_committed_run` commits, signed in."""


def _committed_run(
    app: Flask, documents: int
) -> tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    """An open project whose work item's run ended, with `documents`
    decisions it registered, each read at its end, committed: the person's
    id, the project's and the documents'."""
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
        project = Project(
            created_by_user_id=person.id, state_code=ProjectState.OPEN, slug="camp"
        )
        session.add(project)
        session.add(Environment(id=ENVIRONMENT_ID, name="Example-1", exempt=False))
        session.flush()
        run = models.Session(
            project_id=project.id,
            environment_id=ENVIRONMENT_ID,
            kind_code="work",
            cwd="/work/Example",
            token_hash="1" * 64,
            state_code=SessionState.IDLE,
        )
        session.add(run)
        session.flush()
        _ended_run(container, project, run)
        items = [
            _registered(
                session, container, project, run, DECISION, f"/work/Example/{n}.md"
            )[0].id
            for n in range(documents)
        ]
        return person.id, project.id, items


def _answered(
    container: ServiceContainer, person_id: uuid.UUID, item_id: uuid.UUID
) -> bool:
    """The person's answer that closes the decision, committed; False when
    Finish closed it first."""
    with scoped_session(container) as session:
        try:
            container.record_service().answer(
                session.get_one(Document, item_id),
                "D1",
                session.get_one(User, person_id),
                "Tunnel",
            )
        except InvalidOperationException as refused:
            assert refused.cause == "the item is done"
            return False
        return True


def _undone(container: ServiceContainer, item_id: uuid.UUID) -> bool:
    """The Undo of the item, committed; False when a continuation consumed
    it first."""
    with scoped_session(container) as session:
        try:
            container.record_service().undo(session.get_one(Item, item_id))
        except InvalidOperationException as refused:
            assert refused.cause == "a session has taken the item's answers"
            return False
        return True


def _committed_continuations(container: ServiceContainer) -> list[Work]:
    with scoped_session(container) as session:
        return list(
            session.scalars(select(Work).where(Work.trigger_item_id.is_not(None)))
        )


class TestRecordServiceReleaseLocks:
    """A close of a registered document takes its project's row first, in
    the start's lock order, so it serialises with Finish, an Undo and another
    close (review 3; V22)."""

    @pytest.mark.parametrize(
        "held",
        [
            pytest.param("FOR SHARE", id="an-undos"),
            pytest.param("FOR NO KEY UPDATE", id="finishs"),
            pytest.param("FOR UPDATE", id="another-closes"),
        ],
    )
    def test_it_waits_for_the_projects_row_before_it_locks_the_documents(
        self, committed_app: Flask, held: str
    ) -> None:
        person_id, project_id, (item_id,) = _committed_run(committed_app, 1)
        container = committed_app.container
        with committed_app.app_context():
            engine = db.engine

        with engine.connect() as holder:
            holder.execute(
                sql(f"SELECT id FROM projects WHERE id = :id {held}"),
                {"id": project_id},
            )
            close = in_thread(lambda: _answered(container, person_id, item_id))
            wait_until(lambda: lock_waits(container) == 1, "the close waiting")
            with engine.connect() as other:
                other.execute(
                    sql("SELECT id FROM documents WHERE id = :id FOR UPDATE NOWAIT"),
                    {"id": item_id},
                )
                other.rollback()
            holder.rollback()

        assert close.result()
        (work,) = _committed_continuations(container)
        with scoped_session(container) as session:
            assert session.get_one(Item, item_id).consumed_session_id == work.id

    def test_two_closes_of_the_runs_last_documents_place_one_continuation(
        self, committed_app: Flask
    ) -> None:
        person_id, project_id, items = _committed_run(committed_app, 2)
        container = committed_app.container
        with committed_app.app_context():
            engine = db.engine

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR SHARE"),
                {"id": project_id},
            )
            closes = [
                in_thread(
                    lambda item_id=item_id: _answered(container, person_id, item_id)
                )
                for item_id in items
            ]
            wait_until(lambda: lock_waits(container) == 2, "both closes waiting")
            holder.rollback()

        assert [close.result() for close in closes] == [True, True]
        (work,) = _committed_continuations(container)
        with scoped_session(container) as session:
            assert [
                session.get_one(Item, item_id).consumed_session_id for item_id in items
            ] == [work.id, work.id]

    def test_the_last_close_and_finish_at_once_neither_deadlock_nor_continue_both(
        self, committed_app: Flask
    ) -> None:
        person_id, project_id, (item_id,) = _committed_run(committed_app, 1)
        container = committed_app.container
        with committed_app.app_context():
            engine = db.engine

        def finish() -> None:
            with scoped_session(container):
                container.project_service().transition(
                    ADA, project_id, TransitionKind.FINISHED
                )

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR SHARE"),
                {"id": project_id},
            )
            close = in_thread(lambda: _answered(container, person_id, item_id))
            finished = in_thread(finish)
            wait_until(lambda: lock_waits(container) == 2, "both waiting")
            holder.rollback()

        answered = close.result()
        finished.result()
        continuations = _committed_continuations(container)
        with scoped_session(container) as session:
            item = session.get_one(Item, item_id)
            if answered:
                # The close went first: Finish stopped its continuation and
                # closed its work item.
                (work,) = continuations
                assert item.consumed_session_id == work.id
                assert (
                    session.get_one(models.Session, work.id).state_code
                    == SessionState.STOPPED
                )
                assert session.get_one(Item, work.id).done_cause_code == "finished"
            else:
                assert continuations == []
                assert item.done_cause_code == "finished"

    def test_an_undo_and_the_last_close_at_once_never_continue_a_reopened_run(
        self, committed_app: Flask
    ) -> None:
        person_id, project_id, (first, last) = _committed_run(committed_app, 2)
        container = committed_app.container
        assert _answered(container, person_id, first)
        with committed_app.app_context():
            engine = db.engine

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR NO KEY UPDATE"),
                {"id": project_id},
            )
            undo = in_thread(lambda: _undone(container, first))
            close = in_thread(lambda: _answered(container, person_id, last))
            wait_until(lambda: lock_waits(container) == 2, "both waiting")
            holder.rollback()

        undone = undo.result()
        assert close.result()
        continuations = _committed_continuations(container)
        with scoped_session(container) as session:
            reopened = session.get_one(Item, first)
            if undone:
                assert continuations == []
                assert reopened.done_at is None
            else:
                (work,) = continuations
                assert reopened.consumed_session_id == work.id


def _work_session(
    session: DbSession, project: Project, environment: Environment
) -> models.Session:
    """A work Session of `project` whose start is written, with no Item yet."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="work",
        cwd="/work/Example",
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.STARTING,
    )
    session.add(run)
    session.flush()
    return run


class TestRecordServicePlaceWork:
    def test_the_item_its_work_and_its_session_are_one_id(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        environment: Environment,
    ) -> None:
        _bear(session, container, project, project_session, "notice", "Palette", NOTICE)
        run = _work_session(session, project, environment)

        work = container.record_service().place_work(project, run, "Renaming the badge")

        item = session.get_one(Item, run.id)
        assert work.id == item.id == run.id
        assert (item.project_id, item.seq, item.kind_code, item.title) == (
            project.id,
            2,
            "work",
            "Renaming the badge",
        )
        assert item.plan_task_id is None
        # Created by its own Session (DB Work), not the project's.
        assert (item.created_by_session_id, item.created_by_user_id) == (run.id, None)
        assert _done(item) == (None, None, None)
        assert (work.project_id, work.session_kind_code) == (project.id, "work")
        assert (work.trigger_code, work.trigger_item_id) == (None, None)
        assert session.get(Document, item.id) is None

    @pytest.mark.parametrize("autopilot", [True, False])
    def test_the_work_keeps_the_switchs_setting_it_was_placed_under(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        autopilot: bool,
    ) -> None:
        project.autopilot = autopilot
        session.flush()
        run = _work_session(session, project, environment)

        work = container.record_service().place_work(project, run, "Renaming")
        project.autopilot = not autopilot
        session.flush()

        assert session.get_one(Work, work.id, populate_existing=True).autopilot is (
            autopilot
        )

    def test_it_works_on_a_task_of_the_plan(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _task(session, project, "build")
        run = _work_session(session, project, environment)

        container.record_service().place_work(project, run, "Building", "build")

        assert session.get_one(Item, run.id).plan_task_id == "build"

    @pytest.mark.parametrize("removed", [False, True], ids=["unknown", "removed"])
    def test_a_task_not_in_the_plan_is_not_found(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        removed: bool,
    ) -> None:
        if removed:
            _task(session, project, "build", removed=True)
        run = _work_session(session, project, environment)

        with pytest.raises(RecordNotFoundException) as raised:
            container.record_service().place_work(project, run, "Building", "build")

        assert raised.value.message == (f"Plan task {project.id}/build was not found")
        assert session.get(Item, run.id) is None
        assert session.get(Work, run.id) is None

    def test_its_place_moves_the_timeline(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        run = _work_session(session, project, environment)

        with scoped_session(container):
            container.record_service().place_work(project, run, "Renaming")
            assert engine_events == []

        assert engine_events == [
            TreeHashMoved(
                f"draft-{project.number}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
        ]
        timeline = json.loads(container.view_service().timeline(project).text)
        assert [(item["kind"], item["title"]) for item in timeline["items"]] == [
            ("work", "Renaming")
        ]


class TestRecordServiceWorkDone:
    AT = datetime(2026, 10, 23, 9, 30, 0, tzinfo=UTC)

    def test_the_item_is_done_at_its_turns_end_by_no_one(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _work_session(session, project, environment)
        records = container.record_service()
        records.place_work(project, run, "Renaming")

        records.work_done(run.id, self.AT)

        item = session.get_one(Item, run.id)
        assert _done(item) == (self.AT, "turn_ended", None)
        assert not records.offers_undo(item)

    def test_an_item_finish_closed_first_stays_closed(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        run = _work_session(session, project, environment)
        records = container.record_service()
        records.place_work(project, run, "Renaming")
        records.close_unanswered(project, person, FINISH)

        records.work_done(run.id, self.AT)

        assert _done(session.get_one(Item, run.id)) == (
            FINISH,
            "finished",
            person.id,
        )

    def test_its_done_moves_the_timeline(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        run = _work_session(session, project, environment)
        with scoped_session(container):
            container.record_service().place_work(project, run, "Renaming")
        engine_events.clear()

        with scoped_session(container):
            container.record_service().work_done(run.id, self.AT)

        assert engine_events == [
            TreeHashMoved(
                f"draft-{project.number}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
        ]
        (entry,) = json.loads(container.view_service().timeline(project).text)["items"]
        assert entry["done"] == {"at": _z(self.AT), "cause": "turn_ended", "by": None}

    def test_it_waits_for_the_items_row(self, committed_app: Flask) -> None:
        """What Finish's close holds while it closes the open items."""
        person_id, _, _ = _committed_items(committed_app)
        container = committed_app.container
        with scoped_session(container) as session:
            project = session.scalars(select(Project)).one()
            environment = session.get_one(Environment, ENVIRONMENT_ID)
            run = _work_session(session, project, environment)
            container.record_service().place_work(project, run, "Renaming")
            run_id = run.id
        with committed_app.app_context():
            engine = db.engine

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM items WHERE id = :id FOR UPDATE"), {"id": run_id}
            )
            with (
                pytest.raises(OperationalError) as raised,
                scoped_session(container) as session,
            ):
                session.execute(sql("SET LOCAL lock_timeout = '200ms'"))
                container.record_service().work_done(run_id, self.AT)
            holder.rollback()

        assert isinstance(raised.value.orig, LockNotAvailable)
        with scoped_session(container) as session:
            assert session.get_one(Item, run_id).done_at is None


REVIEW = "---\ntitle: The camp survey\n---\n\nThe lake and the forest compared.\n"


def _brain(db: DbSession, project: Project) -> models.Session:
    """A chat of the project's: a session of Pilot's own, handed
    `pilot-store`, which adds items."""
    chat = models.Session(
        project_id=project.id,
        kind_code="chat",
        cwd=STORE_REPO,
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.RUNNING,
    )
    db.add(chat)
    db.flush()
    return chat


def _jobs_after(db: DbSession, item: Item) -> list[models.Session]:
    """The jobs placed after the item's closes, in the order placed."""
    return list(
        db.scalars(
            select(models.Session)
            .join(Work, Work.id == models.Session.id)
            .join(Item, Item.id == Work.id)
            .where(
                Work.trigger_code == WorkTrigger.ITEM_DONE,
                Work.trigger_item_id == item.id,
            )
            .order_by(Item.seq)
            .execution_options(populate_existing=True)
        )
    )


@pytest.fixture
def opened(session: DbSession, project: Project) -> Project:
    """`project` open, with its slug."""
    project.state_code = ProjectState.OPEN
    project.slug = "camp"
    session.flush()
    return project


@pytest.fixture
def placing(container: ServiceContainer, supervise: Supervise) -> None:
    """The container's start on a controller, its loops never run, through
    which a close places the job after it."""
    container.session_start_service.override(
        providers.Object(configured_starts(container, supervise))
    )


@pytest.mark.usefixtures("placing")
class TestRecordServiceItemDone:
    """A person's close of an item of Pilot's own places one job after it,
    its trigger item the item, in the close's transaction (DB decision 45;
    F59; V01, V24)."""

    @pytest.mark.parametrize(
        ("kind", "text", "close"),
        [
            pytest.param("decision", DECISION, "answer", id="answered"),
            pytest.param("action", ACTION, "done_action", id="an-actions-done"),
            pytest.param("document", RECOMMENDED, "done", id="a-documents-done"),
            pytest.param("review", REVIEW, "reviewed", id="a-reviews-reviewed"),
        ],
    )
    def test_a_persons_close_places_the_job_after_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        person: User,
        kind: str,
        text: str,
        close: str,
    ) -> None:
        item, document = _bear(
            session, container, opened, _brain(session, opened), kind, "Camp", text
        )
        records = container.record_service()

        match close:
            case "answer":
                records.answer(document, "D1", person, "Tunnel")
            case "done_action":
                records.done_action(document, "A1", person)
            case "done":
                records.done(item, person)
            case "reviewed":
                records.reviewed(item, person)

        (job,) = _jobs_after(session, item)
        line = session.get_one(Item, job.id)
        assert (job.kind_code, line.title, line.kind_code) == (
            "job",
            NEXT_TITLE,
            "work",
        )
        assert line.seq == item.seq + 1

    def test_the_chats_answer_on_a_persons_behalf_is_theirs(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            opened,
            _brain(session, opened),
            "decision",
            "Which tent?",
            DECISION,
        )

        container.record_service().answer(
            document, "D1", person, "Tunnel", via=AnswerChannel.CHAT
        )

        assert len(_jobs_after(session, item)) == 1

    def test_a_notices_read_and_pilots_own_done_place_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        person: User,
    ) -> None:
        brain = _brain(session, opened)
        notice, _ = _bear(
            session, container, opened, brain, "notice", "Palette", NOTICE
        )
        settled, _ = _bear(
            session, container, opened, brain, "document", "Camp plan", SETTLED
        )
        records = container.record_service()

        records.read(notice, person)
        records.done(settled, _agent(session))

        assert (notice.done_cause_code, settled.done_cause_code) == (
            "marked",
            "settled",
        )
        assert _jobs_after(session, notice) == _jobs_after(session, settled) == []

    def test_an_answer_that_leaves_the_item_open_places_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        person: User,
    ) -> None:
        item, document = _bear(
            session,
            container,
            opened,
            _brain(session, opened),
            "document",
            "Camp plan",
            TWO_ASKS,
        )

        container.record_service().answer(document, "D1", person, "Tunnel")

        assert item.done_at is None
        assert _jobs_after(session, item) == []

    def test_an_item_a_workers_session_added_places_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        item, document = _bear(
            session,
            container,
            opened,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )

        container.record_service().answer(document, "D1", person, "Tunnel")

        assert item.done_cause_code == "answered"
        assert _jobs_after(session, item) == []

    def test_finishs_close_places_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        person: User,
    ) -> None:
        item, _ = _bear(
            session,
            container,
            opened,
            _brain(session, opened),
            "decision",
            "Which tent?",
            DECISION,
        )

        container.record_service().close_unanswered(opened, person, FINISH)

        assert item.done_cause_code == "finished"
        assert _jobs_after(session, item) == []


@pytest.mark.usefixtures("placing")
class TestRecordServiceItemDoneUndo:
    """The item keeps Undo until its job's brief goes out, which consumes
    it; an Undo before then withdraws the job (F14.1; V29)."""

    @pytest.fixture
    def paused(self, session: DbSession, opened: Project) -> Project:
        opened.paused = True
        session.flush()
        return opened

    def _answered(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
    ) -> Item:
        item, document = _bear(
            session,
            container,
            project,
            _brain(session, project),
            "decision",
            "Which tent?",
            DECISION,
        )
        container.record_service().answer(document, "D1", person, "Tunnel")
        return item

    def test_once_its_brief_went_out_the_item_is_consumed_and_takes_no_undo(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        person: User,
    ) -> None:
        """Placed in an idle project, the job is briefed at once, in the
        close's transaction."""
        item = self._answered(session, container, opened, person)
        (job,) = _jobs_after(session, item)
        records = container.record_service()

        assert (job.state_code, job.turns) == (SessionState.STARTING, 1)
        assert (item.consumed_session_id, item.consumed_at) == (
            job.id,
            job.turn_started_at,
        )
        assert records.offers_undo(item) is False
        with pytest.raises(InvalidOperationException) as refused:
            records.undo(item)
        assert refused.value.cause == "a session has taken the item's answers"

    def test_while_its_job_is_held_the_item_keeps_undo(
        self,
        session: DbSession,
        container: ServiceContainer,
        paused: Project,
        person: User,
    ) -> None:
        item = self._answered(session, container, paused, person)
        (job,) = _jobs_after(session, item)

        assert (job.state_code, job.turns) == (SessionState.HELD, 0)
        assert item.consumed_at is None
        assert container.record_service().offers_undo(item) is True

    def test_an_undo_withdraws_the_held_job_which_never_starts(
        self,
        session: DbSession,
        container: ServiceContainer,
        paused: Project,
        person: User,
    ) -> None:
        item = self._answered(session, container, paused, person)
        (job,) = _jobs_after(session, item)
        records = container.record_service()

        records.undo(item)

        (job,) = _jobs_after(session, item)
        line = session.get_one(Item, job.id)
        assert item.done_at is None
        assert _block(session, session.get_one(Document, item.id), "D1").answer is None
        assert (job.state_code, job.turns, job.stopped_by_user_id) == (
            SessionState.STOPPED,
            0,
            None,
        )
        assert (line.done_cause_code, line.done_by_user_id) == ("withdrawn", None)
        assert line.done_at == job.stopped_at
        assert records.offers_undo(line) is False
        assert session.scalars(
            select(Item.id).where(Item.project_id == paused.id, waiting_on(person))
        ).all() == [item.id]

    def test_the_items_next_close_places_another_job(
        self,
        session: DbSession,
        container: ServiceContainer,
        paused: Project,
        person: User,
    ) -> None:
        item = self._answered(session, container, paused, person)
        records = container.record_service()
        records.undo(item)

        records.answer(session.get_one(Document, item.id), "D1", person, "Dome")

        withdrawn, placed = _jobs_after(session, item)
        assert (withdrawn.state_code, placed.state_code) == (
            SessionState.STOPPED,
            SessionState.HELD,
        )
        assert session.get_one(Item, placed.id).done_at is None

    def test_an_undo_of_an_item_with_no_job_withdraws_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        paused: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        item, document = _bear(
            session,
            container,
            paused,
            project_session,
            "decision",
            "Which tent?",
            DECISION,
        )
        records = container.record_service()
        records.answer(document, "D1", person, "Tunnel")

        records.undo(item)

        assert item.done_at is None
        assert _jobs_after(session, item) == []


def _committed_pilots(
    app: Flask, supervise: Supervise, items: int, *, paused: bool = False
) -> tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    """An open project, `paused` or not, with `items` decisions its chat
    added, committed, the app's start on a controller: the person's id, the
    project's and the decisions'."""
    container = app.container
    container.session_start_service.override(
        providers.Object(configured_starts(container, supervise))
    )
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
        project = Project(
            created_by_user_id=person.id,
            state_code=ProjectState.OPEN,
            slug="camp",
            paused=paused,
        )
        session.add(project)
        session.flush()
        brain = _brain(session, project)
        documents = container.document_service()
        decisions = [
            documents.bear_item(project, "decision", f"Tent {n}?", brain, DECISION).id
            for n in range(items)
        ]
        return person.id, project.id, decisions


def _committed_jobs(container: ServiceContainer) -> list[models.Session]:
    """The jobs after a close, in the order placed."""
    with scoped_session(container) as session:
        return list(
            session.scalars(
                select(models.Session)
                .join(Work, Work.id == models.Session.id)
                .join(Item, Item.id == Work.id)
                .where(Work.trigger_code == WorkTrigger.ITEM_DONE)
                .order_by(Item.seq)
            )
        )


class TestRecordServiceItemDoneLocks:
    """A close of an item takes its project's row exclusively from the
    start, so two closes never both upgrade a shared hold; the Undo locks
    the job before it reads the item, so it and the brief never both take
    effect (the ruling on plan review r1 A1; V24, V29)."""

    def test_two_closes_in_one_project_at_once_both_commit_each_with_its_job(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        person_id, project_id, items = _committed_pilots(committed_app, supervise, 2)
        container = committed_app.container
        with committed_app.app_context():
            engine = db.engine

        # An Undo's hold, which both closes would share were theirs shared.
        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR SHARE"),
                {"id": project_id},
            )
            closes = [
                in_thread(
                    lambda item_id=item_id: _answered(container, person_id, item_id)
                )
                for item_id in items
            ]
            wait_until(lambda: lock_waits(container) == 2, "both closes waiting")
            holder.rollback()

        assert [close.result() for close in closes] == [True, True]
        jobs = _committed_jobs(container)
        with scoped_session(container) as session:
            assert sorted(
                session.get_one(Work, job.id).trigger_item_id for job in jobs
            ) == sorted(items)
        assert sorted(job.state_code for job in jobs) == sorted(
            [SessionState.STARTING, SessionState.HELD]
        )

    def test_an_items_close_waits_for_an_undos_hold(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        person_id, project_id, (item_id,) = _committed_pilots(
            committed_app, supervise, 1
        )
        container = committed_app.container
        with committed_app.app_context():
            engine = db.engine

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR SHARE"),
                {"id": project_id},
            )
            with (
                pytest.raises(OperationalError) as raised,
                scoped_session(container) as session,
            ):
                session.execute(sql("SET LOCAL lock_timeout = '200ms'"))
                container.record_service().answer(
                    session.get_one(Document, item_id),
                    "D1",
                    session.get_one(User, person_id),
                    "Tunnel",
                )
            holder.rollback()

        assert isinstance(raised.value.orig, LockNotAvailable)
        assert _committed_jobs(container) == []

    def test_an_undo_waiting_for_the_job_finds_it_briefed_and_is_refused(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        """The job's lock taken first, the Undo reads the item as the brief
        left it: consumed."""
        person_id, _, (item_id,) = _committed_pilots(
            committed_app, supervise, 1, paused=True
        )
        container = committed_app.container
        assert _answered(container, person_id, item_id)
        (job,) = _committed_jobs(container)
        with committed_app.app_context():
            engine = db.engine

        # The release's transaction, as it briefs the job: its Session locked,
        # moved to `starting` with its first Turn, the item consumed.
        with engine.connect() as release:
            release.execute(
                sql("SELECT id FROM sessions WHERE id = :id FOR UPDATE"),
                {"id": job.id},
            )
            undo = in_thread(lambda: _undone(container, item_id))
            wait_until(lambda: lock_waits(container) == 1, "the Undo waiting")
            release.execute(
                sql(
                    "UPDATE sessions SET state_code = 'starting', turns = 1"
                    " WHERE id = :id"
                ),
                {"id": job.id},
            )
            release.execute(
                sql(
                    "UPDATE items SET consumed_at = now(), consumed_session_id = :job"
                    " WHERE id = :id"
                ),
                {"id": item_id, "job": job.id},
            )
            release.commit()

        assert undo.result() is False
        with scoped_session(container) as session:
            item = session.get_one(Item, item_id)
            assert (item.done_cause_code, item.consumed_session_id) == (
                "answered",
                job.id,
            )

    def test_an_undo_that_takes_the_job_first_withdraws_it_before_any_brief(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        person_id, _, (item_id,) = _committed_pilots(
            committed_app, supervise, 1, paused=True
        )
        container = committed_app.container
        assert _answered(container, person_id, item_id)

        assert _undone(container, item_id)

        (job,) = _committed_jobs(container)
        with scoped_session(container) as session:
            assert session.get_one(Item, item_id).consumed_at is None
            assert session.get_one(Item, job.id).done_cause_code == "withdrawn"
        assert (job.state_code, job.turns) == (SessionState.STOPPED, 0)


PUSH = """---
title: Push the release
---

```decision id=C1
type: confirmation
because: auto-pilot-off
proposal: Push the release.
```
"""


def _pushed_because(because: str) -> str:
    """`PUSH`, asked on `because`."""
    return PUSH.replace("because: auto-pilot-off", f"because: {because}")


CAMP_CHECKS = """---
title: Camp checks
---

```decision id=C1
type: confirmation
because: rider
proposal: Push with the map fix riding along.
```

```decision id=D1
proposal: Cook on the fire.
```

```decision id=C2
type: confirmation
because: standing-grant
proposal: Keep the deploy key past the project.
```

```decision id=C3
type: confirmation
because: auto-pilot-off
proposal: Tag the release.
answer: No
by: agent
at: 2026-10-12T09:30:00Z
note: The tag waits for the map.
```
"""


def _answer(
    block: Block,
) -> tuple[str | None, uuid.UUID | None, AnswerChannel | None]:
    return block.answer, block.answered_by_user_id, block.via_code


class TestAutopilotMayTake:
    """The open confirmations the switch answers, read from `because` (F4.2,
    F4.4; DB decision 58)."""

    def test_the_open_confirmations_whose_reason_the_switch_answers_in_order(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        project_session: models.Session,
    ) -> None:
        checks = _bear(
            session,
            container,
            opened,
            project_session,
            "document",
            "Camp checks",
            CAMP_CHECKS,
        )[1]
        bear = {
            because: _bear(
                session,
                container,
                opened,
                project_session,
                "decision",
                "Push the release",
                _pushed_because(because),
            )[1]
            for because in ("auto-pilot-off", "irreversible", "rider")
        }
        closed = _bear(
            session,
            container,
            opened,
            project_session,
            "decision",
            "Push the release",
            PUSH,
        )[0]
        closed.done_at = datetime.now(UTC)
        closed.done_cause_code = "finished"
        session.flush()

        assert session.execute(autopilot_may_take(opened)).all() == [
            (checks.id, "C1"),
            (bear["auto-pilot-off"].id, "C1"),
            (bear["rider"].id, "C1"),
        ]

    def test_another_projects_are_not_the_projects(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        _bear(
            session,
            container,
            opened,
            project_session,
            "decision",
            "Push the release",
            PUSH,
        )
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()

        assert session.execute(autopilot_may_take(other)).all() == []


class TestRecordServiceAutopilotYes:
    """The switch's Yes answers each open confirmation it would have taken as
    the person's Yes, through `autopilot`, each answer doing what a person's
    does (F4.2; DB decisions 7, 58; V02)."""

    def test_it_answers_each_as_the_persons_yes_through_autopilot(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        checks_item, checks = _bear(
            session,
            container,
            opened,
            project_session,
            "document",
            "Camp checks",
            CAMP_CHECKS,
        )
        push_item, push = _bear(
            session,
            container,
            opened,
            project_session,
            "decision",
            "Push the release",
            PUSH,
        )
        before = datetime.now(UTC).replace(microsecond=0)

        container.record_service().autopilot_yes(opened, person)

        yes = ("Yes", person.id, AnswerChannel.AUTOPILOT)
        assert _answer(_block(session, push, "C1")) == yes
        assert _answer(_block(session, checks, "C1")) == yes
        answered_at = _block(session, push, "C1").answered_at
        assert answered_at is not None
        assert before <= answered_at <= datetime.now(UTC)
        assert push.published_text == PUSH.replace(
            "proposal: Push the release.\n",
            "proposal: Push the release.\nanswer: Yes\nby: ada\n"
            f"at: {_z(answered_at)}\nvia: autopilot\n",
        )
        assert _done(push_item) == (answered_at, "answered", person.id)
        assert _done(checks_item) == (None, None, None)

    def test_a_kept_reason_another_ask_and_an_answered_one_are_left_as_they_are(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        _, checks = _bear(
            session,
            container,
            opened,
            project_session,
            "document",
            "Camp checks",
            CAMP_CHECKS,
        )
        kept = {
            because: _bear(
                session,
                container,
                opened,
                project_session,
                "decision",
                "Push the release",
                _pushed_because(because),
            )
            for because in (
                "irreversible",
                "product-hold",
                "self-approval",
                "standing-grant",
            )
        }

        container.record_service().autopilot_yes(opened, person)

        for item, document in kept.values():
            assert _answer(_block(session, document, "C1")) == (None, None, None)
            assert item.done_at is None
        assert _answer(_block(session, checks, "D1")) == (None, None, None)
        assert _answer(_block(session, checks, "C2")) == (None, None, None)
        assert _answer(_block(session, checks, "C3"))[0] == "No"
        assert _block(session, checks, "C3").answered_by_user_id == _agent(session).id

    def test_with_none_open_it_writes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        _, document = _bear(
            session,
            container,
            opened,
            project_session,
            "decision",
            "Push the release",
            _pushed_because("irreversible"),
        )

        container.record_service().autopilot_yes(opened, person)

        assert _versions(session, document) == [
            (1, VersionCause.BORN, _pushed_because("irreversible"))
        ]

    @pytest.mark.usefixtures("placing")
    def test_an_item_of_pilots_own_places_the_job_after_each_yes(
        self,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        person: User,
    ) -> None:
        brain = _brain(session, opened)
        pushed = [
            _bear(
                session,
                container,
                opened,
                brain,
                "decision",
                "Push the release",
                _pushed_because(because),
            )[0]
            for because in ("auto-pilot-off", "rider")
        ]

        container.record_service().autopilot_yes(opened, person)

        jobs = [_jobs_after(session, item) for item in pushed]
        assert [len(each) for each in jobs] == [1, 1]
        assert [session.get_one(Item, job.id).seq for (job,) in jobs] == [
            pushed[-1].seq + 1,
            pushed[-1].seq + 2,
        ]

    def test_a_registered_documents_yes_owes_its_write_back_and_continues_its_run(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        run = _ended_run(container, project, project_session)
        item, document = _registered(session, container, project, run, PUSH)

        container.record_service().autopilot_yes(project, person)

        assert _done(item)[1:] == ("answered", person.id)
        assert owes_write_back(item, document)
        (work,) = _continuations(session, project)
        assert item.consumed_session_id == work.id
        assert _first_message(session, work) == CONTINUED.format(paths=REGISTERED_PATH)


def _work_item(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    title: str = "Rotating the CI token",
) -> Work:
    """A worker's run placed as a work item of `project`."""
    run = models.Session(
        project_id=project.id,
        kind_code="work",
        cwd="/work/Example",
        token_hash=f"hash-{uuid.uuid4()}",
        state_code=SessionState.RUNNING,
    )
    session.add(run)
    session.flush()
    return container.record_service().place_work(
        project, run, title, repo="example/Example"
    )


class TestRecordServiceClaims:
    """The claimed actions a work item is named for at its `add_item`: open
    actions of registered documents of its project (DB 261), one Claim
    Assignment each, never changed (DB 260; decision 64)."""

    def test_open_actions_a_claim_among_them_are_given_to_the_work_item(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        claimed, _ = _registered(session, container, project, project_session, CLAIMED)
        unclaimed, _ = _registered(
            session, container, project, project_session, ACTION, SURVEY_PATH
        )
        records = container.record_service()
        blocks = records.claimable(
            project, [f"{unclaimed.id}/A1", f"{claimed.id}/A1"], "add a work item"
        )
        work = _work_item(session, container, project)

        records.give(project, work, blocks)

        assert [(block.document_id, block.local_id) for block in blocks] == [
            (unclaimed.id, "A1"),
            (claimed.id, "A1"),
        ]
        assert sorted(
            session.scalars(
                select(models.ClaimAssignment.block_id).where(
                    models.ClaimAssignment.work_id == work.id
                )
            )
        ) == sorted(block.id for block in blocks)

    def test_with_none_named_nothing_is_given(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
    ) -> None:
        records = container.record_service()
        work = _work_item(session, container, project)

        records.give(project, work, records.claimable(project, [], "add a work item"))

        assert session.scalars(select(models.ClaimAssignment)).all() == []

    @pytest.mark.parametrize(
        ("name", "cause"),
        [
            pytest.param(
                "decision",
                "block D1 of {path} is a decision, not an action",
                id="no-action",
            ),
            pytest.param(
                "done",
                "action A1 of {path} is answered",
                id="action-done",
            ),
            pytest.param(
                "deferred",
                "action A1 of {path} is answered",
                id="action-deferred",
            ),
            pytest.param("twice", "it names action A1 of {path} twice", id="twice"),
        ],
    )
    def test_a_block_that_is_no_open_action_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        name: str,
        cause: str,
    ) -> None:
        texts = {
            "decision": CLAIMED,
            "done": SETTLED_ONE_BLOCK["claimed-and-done"],
            "deferred": (
                "```action id=A1\nanswer: deferred\nby: agent\n"
                "at: 2026-10-12T09:30:00Z\nto: plan\n```\n"
            ),
            "twice": ACTION,
        }
        item, document = _registered(
            session, container, project, project_session, texts[name]
        )
        local_id = "D1" if name == "decision" else "A1"
        named = [f"{item.id}/{local_id}"]
        if name == "twice":
            named.append(f"{str(item.id).upper()}/A1")

        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().claimable(project, named, "add a work item")

        assert refused.value.message == (
            "Cannot add a work item because "
            + cause.format(path=tree_path(project, document.path))
        )

    def test_an_item_no_registered_document_done_or_unread_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        pilots, _ = _bear(
            session,
            container,
            project,
            project_session,
            "action",
            "Rotate the CI token",
            ACTION,
        )
        done, done_document = _registered(
            session, container, project, project_session, ACTION
        )
        container.record_service().done_action(done_document, "A1", person)
        unread = (
            container.document_service()
            .register(project, project_session, SURVEY_PATH)
            .item
        )
        records = container.record_service()

        refusals = []
        for item in (pilots, done, unread):
            with pytest.raises(InvalidOperationException) as refused:
                records.claimable(project, [f"{item.id}/A1"], "add a work item")
            refusals.append(refused.value.cause)

        assert refusals == [
            f"item {pilots.id} is no registered document: Pilot claims an action"
            " of a worker's document",
            f"{tree_path(project, done_document.path)} is done",
            "its file has not been read yet: it is read at the end of the turn"
            " that registered it",
        ]

    def test_an_item_of_another_project_or_a_block_it_lacks_is_not_found(
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
        mine, _ = _registered(session, container, project, project_session, ACTION)
        records = container.record_service()

        with pytest.raises(RecordNotFoundException) as not_theirs:
            records.claimable(other, [f"{mine.id}/A1"], "add a work item")
        with pytest.raises(RecordNotFoundException) as no_block:
            records.claimable(project, [f"{mine.id}/A9"], "add a work item")

        assert not_theirs.value.message == f"Item {mine.id} was not found"
        assert no_block.value.message == f"Block {mine.id}/A9 was not found"
