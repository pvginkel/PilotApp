"""A project's timeline as a screen draws it, and the items waiting on a
person (F8, F12, F13, F18, F31, F78, F1.4)."""

import base64
import uuid
from datetime import UTC, datetime
from typing import Any, get_args

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.paths import tree_path
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import (
    Attachment,
    Document,
    DocumentVersion,
    DoneCause,
    Environment,
    Item,
    ItemAttachment,
    ItemKind,
    PlanTask,
    Project,
    ProjectTransition,
    SaveError,
    Turn,
    User,
    Work,
)
from app.models.reference import (
    AttachmentSource,
    DocumentRole,
    ErrorKind,
    SessionState,
    TransitionKind,
    VersionCause,
)
from app.schemas.testing_record import InventedFileSchema, InventedProjectCreateSchema
from app.schemas.timeline import AttachmentSchema, DoneCauseCode, ItemKindCode
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.timeline_service import Badge, work_status

ADA = AuthContext(
    subject="subject-ada", email=None, name="Ada Example", roles={"editor"}
)
"""The `person` fixture, signed in."""

ADA_USER = {
    "kind": "person",
    "handle": "ada",
    "name": "Ada Example",
    "initials": "AE",
    "avatar_slot": 1,
}
BEN_USER = {
    "kind": "person",
    "handle": "ben",
    "name": "Ben Example",
    "initials": "BE",
    "avatar_slot": 2,
}
PILOT = {
    "kind": "agent",
    "handle": "agent",
    "name": "Pilot",
    "initials": "P",
    "avatar_slot": None,
}

DECISION = """---
title: Which tent?
step: build
---

# Which tent?

The dome stands up in five minutes.

```decision id=D1
options:
  - Dome: up in five minutes
  - Tunnel
recommend: Dome
check: The tent is in the car.
```

Pick before the weekend.
"""

CONFIRMATION = """---
title: Book the site
---

```decision id=C1
type: confirmation
because: rider
proposal: Book the lakeside pitch.
```
"""

QUESTION = """---
title: Where do we camp?
---

```question id=Q1
default: By the lake
```
"""

ACTION = """---
title: Pack the stove
---

```action id=A1
```
"""

NOTICE = "---\ntitle: The site opens in May\n---\n\nThe site opens in May.\n"

DEFERRED = """---
title: Camp plan
---

```decision id=D1
proposal: Cook on the fire.
answer: deferred
by: agent
at: 2026-10-12T09:30:00Z
to: build
note: Decide once the camp is built.
```

```decision id=D2
proposal: Bring a lantern.
answer: deferred
by: ada
at: 2026-10-12T09:31:00Z
to: plan
```

```question id=Q1
default: Two nights
answer: deferred
by: ada
at: 2026-10-12T09:32:00Z
to: ship
```
"""

TWO_ASKS = """---
title: Camp plan
---

```decision id=D1
proposal: Cook on the fire.
```

```question id=Q1
default: Two nights
```
"""

SETTLED = """---
title: Which stove?
---

```decision id=D1
options:
  - Gas
  - Wood
answer: Gas
by: agent
at: 2026-10-12T09:30:00Z
via: autopilot
note: Gas was on the list.
```
"""


NOTICE_LATER = "---\ntitle: The site opens in May\n---\n\nThe site opens on 1 May.\n"

CAMP_KIT = """---
title: Camp kit
summary: What we bring, and the stove.
---

# Camp kit

What we bring.

## Which stove?

```decision id=D1
options:
  - Gas
  - Wood
answer: Gas
by: agent
at: 2026-10-12T09:30:00Z
```
"""
"""Its own count past the front matter, whatever collapses: `# Camp kit` 3,
the prose 3, the heading 3, the fence's lines 2, 1, 2, 2 and 1, its answer
lines left out."""


def _make(container: ServiceContainer, **spec: Any) -> Project:
    spec.setdefault("members", ["ada"])
    spec.setdefault("name", "Camp")
    return container.test_data_service().project(
        InventedProjectCreateSchema.model_validate(spec)
    )


def _run(
    session: DbSession,
    project: Project,
    environment: Environment,
    state: SessionState = SessionState.IDLE,
) -> models.Session:
    """A work session of `project`."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="work",
        cwd="/work/Camp",
        token_hash=uuid.uuid4().hex * 2,
        state_code=state,
    )
    session.add(run)
    session.flush()
    return run


def _work(
    session: DbSession,
    project: Project,
    environment: Environment,
    state: SessionState,
    *,
    autopilot: bool = False,
    **values: Any,
) -> Item:
    """A work item, its Item, its Session and its Work one identity (DB
    decision 3), its Work briefed under `autopilot`."""
    run = _run(session, project, environment, state)
    work = Item(
        id=run.id,
        project_id=project.id,
        seq=_next_seq(session, project),
        kind_code="work",
        title="Build the camp",
        created_by_session_id=run.id,
        **values,
    )
    session.add(work)
    session.flush()
    session.add(
        Work(
            id=run.id,
            project_id=project.id,
            session_kind_code="work",
            autopilot=autopilot,
        )
    )
    session.flush()
    return work


def _turn(
    session: DbSession, run: models.Session, seq: int, error: str | None = None
) -> Turn:
    turn = Turn(
        session_id=run.id,
        seq=seq,
        message="Build the camp",
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        error=error,
    )
    session.add(turn)
    session.flush()
    return turn


def _wait(session: DbSession, project: Project, run: models.Session) -> Item:
    wait = Item(
        project_id=project.id,
        seq=_next_seq(session, project),
        kind_code="timed_wait",
        title="The site opens",
        created_by_session_id=run.id,
    )
    session.add(wait)
    session.flush()
    return wait


def _next_seq(session: DbSession, project: Project) -> int:
    return (
        max(
            session.scalars(select(Item.seq).where(Item.project_id == project.id)),
            default=0,
        )
        + 1
    )


def _bear(
    container: ServiceContainer,
    project: Project,
    run: models.Session,
    kind: str,
    title: str,
    text: str,
) -> Item:
    return container.document_service().bear_item(project, kind, title, run, text)


def _document(session: DbSession, item: Item) -> Document:
    return session.get_one(Document, item.id)


def _save(
    container: ServiceContainer,
    session: DbSession,
    project: Project,
    item: Item,
    environment: Environment,
    run: models.Session,
    text: str,
) -> None:
    """A clean save of the item's file by `run`, which it is then writing."""
    document = _document(session, item)
    ingested = container.ingest_service().ingest(
        tree_path(project, document.path),
        text.encode(),
        container.tree_service().hash(project, document),
        environment,
        run,
    )
    assert not ingested.held, ingested.faults


def _versions(
    session: DbSession, item: Item, cause: VersionCause
) -> list[DocumentVersion]:
    return list(
        session.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == item.id,
                DocumentVersion.cause_code == cause,
            )
            .order_by(DocumentVersion.number)
        )
    )


def _causes(session: DbSession, item: Item) -> list[VersionCause]:
    return list(
        session.scalars(
            select(DocumentVersion.cause_code)
            .where(DocumentVersion.document_id == item.id)
            .order_by(DocumentVersion.number)
        )
    )


def _session_of(session: DbSession, project: Project) -> models.Session:
    return session.scalars(
        select(models.Session).where(models.Session.project_id == project.id)
    ).one()


def _file(
    filename: str, content: bytes, content_type: str = "text/markdown"
) -> InventedFileSchema:
    return InventedFileSchema.model_validate(
        {
            "title": filename.split(".")[0].capitalize(),
            "filename": filename,
            "content_type": content_type,
            "content": base64.b64encode(content).decode(),
        }
    )


def _attachment(
    attachment: Attachment, content_type: str, size: int, batch: int, source: str
) -> AttachmentSchema:
    """What the timeline says of `attachment`, a file `_file` made, copied from
    the folder `source` names."""
    return AttachmentSchema(
        id=attachment.id,
        title=attachment.filename.split(".")[0].capitalize(),
        filename=attachment.filename,
        content_type=content_type,
        size=size,
        batch=batch,
        copied_at=attachment.copied_at,
        source=f"{source}/{attachment.filename}",
    )


def _items(container: ServiceContainer, project: Project) -> list[dict[str, Any]]:
    timeline = container.timeline_service().timeline(project.id)
    items: list[dict[str, Any]] = timeline.model_dump(mode="json")["items"]
    return items


def _ben(container: ServiceContainer) -> User:
    return container.test_data_service().person("ben", "Ben Example")


class TestReferenceCodes:
    def test_the_kinds_are_item_kinds(self, session: DbSession) -> None:
        assert set(get_args(ItemKindCode)) == set(
            session.scalars(select(ItemKind.code))
        )

    def test_the_causes_are_done_causes(self, session: DbSession) -> None:
        assert set(get_args(DoneCauseCode)) == set(
            session.scalars(select(DoneCause.code))
        )


@pytest.mark.usefixtures("person")
class TestTimeline:
    def test_an_unknown_project_is_not_found(self, container: ServiceContainer) -> None:
        with pytest.raises(RecordNotFoundException):
            container.timeline_service().timeline(uuid.uuid4())

    def test_a_draft_has_an_empty_timeline(self, container: ServiceContainer) -> None:
        project = _make(container, state="draft")

        timeline = container.timeline_service().timeline(project.id)

        assert timeline.finished_at is None
        assert timeline.items == []

    def test_every_item_in_order_with_its_line(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        _ben(container)
        project = _make(
            container,
            tasks=[{"id": "build", "title": "Build the camp", "status": "pending"}],
        )
        run = _run(session, project, environment)
        opening = session.scalars(
            select(Item).where(Item.project_id == project.id, Item.seq == 1)
        ).one()
        decision = _bear(container, project, run, "decision", "Which tent?", DECISION)
        notice = _bear(
            container,
            project,
            run,
            "notice",
            "Bring boots",
            "---\ntitle: Bring boots\nurgent: true\nfor: ben\n---\n\nIt rains.\n",
        )
        work = _work(session, project, environment, SessionState.RUNNING)
        wait = _wait(session, project, run)

        items = _items(container, project)

        line = ("id", "seq", "kind", "form", "title", "step", "urgent", "for_user")
        assert [{key: item[key] for key in line} for item in items] == [
            {
                "id": str(opening.id),
                "seq": 1,
                "kind": "opening",
                "form": "prose",
                "title": "Camp",
                "step": None,
                "urgent": False,
                "for_user": None,
            },
            {
                "id": str(decision.id),
                "seq": 2,
                "kind": "decision",
                "form": "prose",
                "title": "Which tent?",
                "step": {"id": "build", "title": "Build the camp"},
                "urgent": False,
                "for_user": None,
            },
            {
                "id": str(notice.id),
                "seq": 3,
                "kind": "notice",
                "form": "prose",
                "title": "Bring boots",
                "step": None,
                "urgent": True,
                "for_user": BEN_USER,
            },
            {
                "id": str(work.id),
                "seq": 4,
                "kind": "work",
                "form": "work",
                "title": "Build the camp",
                "step": None,
                "urgent": False,
                "for_user": None,
            },
            {
                "id": str(wait.id),
                "seq": 5,
                "kind": "timed_wait",
                "form": "wait",
                "title": "The site opens",
                "step": None,
                "urgent": False,
                "for_user": None,
            },
        ]
        assert [datetime.fromisoformat(item["created_at"]) for item in items] == [
            entry.created_at for entry in (opening, decision, notice, work, wait)
        ]
        assert [
            (item["done"], item["concept"], item["file_name"]) for item in items
        ] == [(None, False, None)] * 5
        assert [item["body"] is None for item in items] == [
            True,
            False,
            False,
            True,
            True,
        ]
        assert [item["work"] is None for item in items] == [
            True,
            True,
            True,
            False,
            True,
        ]

    def test_the_opening_is_its_authors_words_verbatim(
        self, container: ServiceContainer
    ) -> None:
        _ben(container)
        words = "Look at this:\n\n```decision id=D1\noptions:\n  - Dome\n"
        project = _make(container, members=["ben", "ada"], opening=words)

        (opening,) = _items(container, project)

        assert opening["author"] == BEN_USER
        assert opening["words"] == words
        assert opening["body"] is None

    def test_a_prose_items_text_as_drawn(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(
            container,
            tasks=[{"id": "build", "title": "Build the camp", "status": "pending"}],
        )
        _bear(
            container,
            project,
            _run(session, project, environment),
            "decision",
            "Which tent?",
            DECISION,
        )

        _opening, item = _items(container, project)

        assert item["author"] is None
        assert item["words"] is None
        assert item["body"] == [
            {
                "type": "prose",
                "markdown": "The dome stands up in five minutes.",
                "section": None,
            },
            {
                "type": "block",
                "block": {
                    "id": "D1",
                    "kind": "decision",
                    "confirmation": False,
                    "because": None,
                    "proposal": None,
                    "default": None,
                    "check": "The tent is in the car.",
                    "options": [
                        {
                            "label": "Dome",
                            "text": "up in five minutes",
                            "recommended": True,
                        },
                        {"label": "Tunnel", "text": None, "recommended": False},
                    ],
                    "answer": None,
                    "by": None,
                    "at": None,
                    "note": None,
                    "via": None,
                    "done": None,
                    "deferral": None,
                    "section": None,
                },
            },
            {"type": "prose", "markdown": "Pick before the weekend.", "section": None},
        ]

    def test_a_block_s_own_section_is_carried_with_the_text(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        _bear(
            container,
            project,
            _run(session, project, environment),
            "document",
            "Camp kit",
            "# Camp kit\n\nWhat we bring.\n\n"
            "## Which tent?\n\nThe dome is quick.\n\n"
            "```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n"
            "answer: Dome\nby: agent\nat: 2026-10-12T09:30:00Z\nnote: It is quick.\n"
            "```\n\n"
            "Pitched by noon.\n\n"
            "## Food\n\n```question id=Q1\n```\n\n```question id=Q2\n```\n",
        )

        _opening, item = _items(container, project)

        assert [
            {key: part[key] for key in ("type", "markdown", "section") if key in part}
            for part in item["body"]
        ] == [
            {"type": "prose", "markdown": "What we bring.", "section": None},
            {
                "type": "prose",
                "markdown": "## Which tent?\n\nThe dome is quick.",
                "section": "D1",
            },
            {"type": "block"},
            {"type": "prose", "markdown": "Pitched by noon.", "section": "D1"},
            {"type": "prose", "markdown": "## Food", "section": None},
            {"type": "block"},
            {"type": "block"},
        ]
        assert [
            (part["block"]["id"], part["block"]["section"])
            for part in item["body"]
            if part["type"] == "block"
        ] == [("D1", {"heading": "Which tent?"}), ("Q1", None), ("Q2", None)]

    def test_a_confirmation_names_its_reason_and_a_question_its_default(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        _bear(container, project, run, "decision", "Book the site", CONFIRMATION)
        _bear(container, project, run, "question", "Where do we camp?", QUESTION)

        _opening, confirmation, question = _items(container, project)

        assert confirmation["kind"] == "confirmation"
        (part,) = confirmation["body"]
        assert part["block"]["confirmation"] is True
        assert part["block"]["proposal"] == "Book the lakeside pitch."
        assert part["block"]["because"] == {
            "code": "rider",
            "name": "Rider",
            "description": (
                "A push with riders, other commits going out with it, asked only"
                " while auto pilot is off."
            ),
        }
        (part,) = question["body"]
        assert (part["block"]["kind"], part["block"]["default"]) == (
            "question",
            "By the lake",
        )

    def test_a_persons_answer_and_its_done_line(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(
            container,
            tasks=[{"id": "build", "title": "Build the camp", "status": "pending"}],
        )
        item = _bear(
            container,
            project,
            _run(session, project, environment),
            "decision",
            "Which tent?",
            DECISION,
        )
        container.record_service().answer(
            _document(session, item), "D1", person, "Tunnel", note="More room."
        )

        _opening, line = _items(container, project)

        block = line["body"][1]["block"]
        assert (block["answer"], block["by"], block["note"], block["via"]) == (
            "Tunnel",
            ADA_USER,
            "More room.",
            "app",
        )
        assert datetime.fromisoformat(block["at"]) == item.done_at
        assert datetime.fromisoformat(line["done"]["at"]) == item.done_at
        assert line["done"] == {
            "at": line["done"]["at"],
            "cause": "answered",
            "by": ADA_USER,
            "undo": True,
        }

    def test_a_block_pilot_settled_is_pilots(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        _bear(
            container,
            project,
            _run(session, project, environment),
            "decision",
            "Which stove?",
            SETTLED,
        )

        _opening, item = _items(container, project)

        block = item["body"][0]["block"]
        assert (
            block["answer"],
            block["by"],
            block["at"],
            block["via"],
            block["note"],
        ) == ("Gas", PILOT, "2026-10-12T09:30:00Z", "autopilot", "Gas was on the list.")

    def test_an_action_marked_done_has_its_time_and_paste_back(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        item = _bear(
            container,
            project,
            _run(session, project, environment),
            "action",
            "Pack the stove",
            ACTION,
        )
        container.record_service().done_action(
            _document(session, item), "A1", person, note="Packed, with two gas cans."
        )

        _opening, line = _items(container, project)

        block = line["body"][0]["block"]
        assert (block["answer"], block["by"], block["note"]) == (
            None,
            ADA_USER,
            "Packed, with two gas cans.",
        )
        assert datetime.fromisoformat(block["done"]) == item.done_at

    def test_a_deferral_names_its_task_live_a_removed_tasks_last(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(
            container,
            tasks=[
                {"id": "build", "title": "Build the camp", "status": "pending"},
                {"id": "ship", "title": "Strike the camp", "status": "pending"},
            ],
        )
        _bear(
            container,
            project,
            _run(session, project, environment),
            "document",
            "Camp plan",
            DEFERRED,
        )
        session.get_one(PlanTask, (project.id, "build")).title = "Pitch the camp"
        removed = session.get_one(PlanTask, (project.id, "ship"))
        removed.position, removed.removed_at = None, datetime.now(UTC)
        session.flush()

        _opening, item = _items(container, project)

        assert [part["block"]["deferral"] for part in item["body"]] == [
            {"to": "build", "title": "Pitch the camp"},
            {"to": "plan", "title": None},
            {"to": "ship", "title": "Strike the camp"},
        ]
        assert [part["block"]["by"] for part in item["body"]] == [
            PILOT,
            ADA_USER,
            ADA_USER,
        ]

    def test_undo_is_offered_until_a_session_takes_the_answer(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "question", "Where?", QUESTION)
        container.record_service().answer(
            _document(session, item), "Q1", person, "The hill"
        )
        item.consumed_at = datetime.now(UTC)
        item.consumed_session_id = run.id
        session.flush()

        _opening, line = _items(container, project)

        assert line["done"]["undo"] is False

    def test_undo_is_refused_while_the_project_is_finished(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "question", "Where?", QUESTION)
        container.record_service().answer(
            _document(session, item), "Q1", person, "The hill"
        )
        transition = container.project_service().transition
        transition(ADA, project.id, TransitionKind.FINISHED)

        _opening, finished = _items(container, project)
        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().undo(item)
        transition(ADA, project.id, TransitionKind.REOPENED)
        _opening, reopened = _items(container, project)

        assert finished["done"]["undo"] is False
        assert refused.value.cause == "the project is finished"
        assert item.done_cause_code == "answered"
        assert reopened["done"]["undo"] is True

    def test_finish_makes_a_done_line_of_every_item_but_the_opening(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        _bear(container, project, run, "notice", "Opens in May", NOTICE)
        container.project_service().transition(ADA, project.id, TransitionKind.FINISHED)

        timeline = container.timeline_service().timeline(project.id)

        opening, notice = timeline.model_dump(mode="json")["items"]
        assert opening["done"] is None
        assert notice["done"] == {
            "at": notice["done"]["at"],
            "cause": "finished",
            "by": ADA_USER,
            "undo": False,
        }
        assert timeline.finished_at is not None
        assert datetime.fromisoformat(notice["done"]["at"]) == timeline.finished_at

    def test_a_work_item_done_at_its_turns_end_was_done_by_no_one(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        done_at = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
        _work(
            session,
            project,
            environment,
            SessionState.IDLE,
            done_at=done_at,
            done_cause_code="turn_ended",
        )

        _opening, work = _items(container, project)

        assert datetime.fromisoformat(work["done"]["at"]) == done_at
        assert work["done"] == {
            "at": work["done"]["at"],
            "cause": "turn_ended",
            "by": None,
            "undo": False,
        }

    def test_an_item_whose_latest_save_is_held_is_a_concept_as_last_published(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "question", "Where?", QUESTION)
        other = _bear(container, project, run, "notice", "Opens in May", NOTICE)
        document = _document(session, item)
        published = container.timeline_service().timeline(project.id).items[1].body
        ingested = container.ingest_service().ingest(
            tree_path(project, document.path),
            b"---\ntitle: Where?\n---\n```question id=Q1\ndefault: The hill\n",
            document.published_hash,
            environment,
            run,
        )
        assert ingested.held

        _opening, concept, clean = _items(container, project)

        assert concept["concept"] is True
        assert concept["body"] == [part.model_dump(mode="json") for part in published]
        assert (clean["id"], clean["concept"]) == (str(other.id), False)

    def test_a_reverted_save_error_on_its_path_makes_no_concept(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "question", "Where?", QUESTION)
        session.add(
            SaveError(
                environment_id=environment.id,
                path=tree_path(project, _document(session, item).path),
                kind_code=ErrorKind.REVERTED,
                line=5,
                message="block Q1 reverted: answered by a person",
            )
        )
        session.flush()

        _opening, line = _items(container, project)

        assert line["concept"] is False

    def test_a_registered_document_without_a_title_shows_its_file_name(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        item = _bear(
            container,
            project,
            _run(session, project, environment),
            "review",
            "refinement",
            "",
        )
        document = _document(session, item)
        document.source_environment_id = environment.id
        document.source_path = "/work/Camp/docs/refinement.md"
        container.document_service().publish(document, "The camp's refinement.\n")

        _opening, line = _items(container, project)

        assert (line["title"], line["file_name"]) == (None, "refinement.md")
        assert line["body"] == [
            {"type": "prose", "markdown": "The camp's refinement.", "section": None}
        ]

    def test_the_opening_work_and_waits_say_nothing_of_a_text(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        _work(session, project, environment, SessionState.RUNNING)
        _wait(session, project, run)

        items = _items(container, project)

        facts = ("summary", "word_count", "read_minutes", "writing", "edited_at")
        assert [
            ([item[key] for key in facts], item["attachments"]) for item in items
        ] == [([None, None, None, False, None], [])] * 3

    def test_a_documents_summary_and_its_own_count(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        _bear(
            container,
            project,
            _run(session, project, environment),
            "document",
            "Camp kit",
            CAMP_KIT,
        )

        _opening, item = _items(container, project)

        assert (item["summary"], item["word_count"], item["read_minutes"]) == (
            "What we bring, and the stove.",
            17,
            1,
        )
        assert item["body"][2]["block"]["section"] == {"heading": "Which stove?"}

    def test_a_persons_answers_and_done_leave_its_own_count(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "document", "Camp plan", TWO_ASKS)
        _opening, born = _items(container, project)
        container.record_service().answer(
            _document(session, item),
            "Q1",
            person,
            "Three nights, since the forecast is dry until Sunday evening",
            note="Ben agrees.",
        )
        _opening, answered = _items(container, project)
        container.record_service().done(item, person)

        _opening, done = _items(container, project)

        assert [line["word_count"] for line in (answered, done)] == [
            born["word_count"]
        ] * 2

    @pytest.mark.parametrize(
        ("words", "minutes"),
        [(0, 1), (1, 1), (344, 1), (345, 2), (574, 2), (575, 3)],
    )
    def test_a_reviews_reading_time_is_its_words_at_230_a_minute_half_up(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        words: int,
        minutes: int,
    ) -> None:
        project = _make(container)
        _bear(
            container,
            project,
            _run(session, project, environment),
            "review",
            "Long read",
            "---\ntitle: Long read\n---\n\n" + " ".join(["word"] * words) + "\n",
        )

        _opening, item = _items(container, project)

        assert (item["word_count"], item["read_minutes"]) == (words, minutes)

    def test_pilot_writes_a_document_from_its_save_to_its_turns_end(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "notice", "Opens in May", NOTICE)
        born = _items(container, project)[1]["writing"]

        _save(container, session, project, item, environment, run, NOTICE_LATER)
        saved = _items(container, project)[1]["writing"]
        container.document_service().turn_ended(run)
        ended = _items(container, project)[1]["writing"]

        assert (born, saved, ended) == (False, True, False)

    def test_a_document_only_born_or_changed_by_no_turn_is_not_edited(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "question", "Where?", QUESTION)
        container.record_service().answer(
            _document(session, item), "Q1", person, "By the hill"
        )

        _opening, line = _items(container, project)

        assert line["edited_at"] is None

    def test_edited_is_the_latest_turn_to_change_the_text_after_its_first(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "document", "Camp plan", TWO_ASKS)
        documents = container.document_service()
        for note in ("Pack light.", "Pack lighter."):
            _save(
                container,
                session,
                project,
                item,
                environment,
                run,
                TWO_ASKS.replace("```question", f"{note}\n\n```question"),
            )
            documents.turn_ended(run)
        container.record_service().done(item, person)
        first, second = _versions(session, item, VersionCause.TURN)
        first.created_at = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
        second.created_at = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
        (done,) = _versions(session, item, VersionCause.DONE)
        done.created_at = datetime(2026, 10, 12, 11, 0, tzinfo=UTC)
        session.flush()

        _opening, line = _items(container, project)

        assert datetime.fromisoformat(line["edited_at"]) == second.created_at

    def test_a_document_born_without_text_is_edited_from_its_second_turn(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "notice", "Opens in May", "")
        documents = container.document_service()
        _save(container, session, project, item, environment, run, NOTICE)
        documents.turn_ended(run)
        first = _items(container, project)[1]["edited_at"]

        _save(container, session, project, item, environment, run, NOTICE_LATER)
        documents.turn_ended(run)
        second = _items(container, project)[1]["edited_at"]

        (_, turn) = _versions(session, item, VersionCause.TURN)
        assert _causes(session, item) == [
            VersionCause.BORN,
            VersionCause.TURN,
            VersionCause.TURN,
        ]
        assert first is None
        assert datetime.fromisoformat(second) == turn.created_at

    def test_an_item_carries_its_attachments_in_their_order_work_included(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container, environment_id=environment.id)
        source = f"{environment.id}:{_session_of(session, project).cwd}"
        data = container.test_data_service()
        notice = data.item(project.id, "notice", "Opens in May", NOTICE)
        work = _work(session, project, environment, SessionState.RUNNING)
        sketch, photo = data.attach(
            notice.id,
            [_file("sketch.md", b"# Sketch\n"), _file("map.png", b"PNG", "image/png")],
        )
        (notes,) = data.attach(
            notice.id, [_file("notes.txt", b"Bring boots.", "text/plain")]
        )
        (log,) = data.attach(work.id, [_file("build.log", b"ok", "text/plain")])

        timeline = container.timeline_service().timeline(project.id)

        assert [item.attachments for item in timeline.items] == [
            [],
            [
                _attachment(sketch, "text/markdown", 9, 1, source),
                _attachment(photo, "image/png", 3, 1, source),
                _attachment(notes, "text/plain", 12, 2, source),
            ],
            [_attachment(log, "text/plain", 2, 3, source)],
        ]

    def test_an_items_attachments_go_by_their_position_not_the_order_they_were_hung_in(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container, environment_id=environment.id)
        source = f"{environment.id}:{_session_of(session, project).cwd}"
        data = container.test_data_service()
        notice = data.item(project.id, "notice", "Opens in May", NOTICE)
        sketch, photo = data.attach(
            notice.id,
            [_file("sketch.md", b"# Sketch\n"), _file("map.png", b"PNG", "image/png")],
        )
        (notes,) = data.attach(
            notice.id, [_file("notes.txt", b"Bring boots.", "text/plain")]
        )
        session.flush()
        # The file hung last moves to the front, its row written last of the
        # three: only the order by position puts it first.
        session.execute(
            update(ItemAttachment)
            .where(
                ItemAttachment.item_id == notice.id,
                ItemAttachment.attachment_id == notes.id,
            )
            .values(position=0)
        )

        timeline = container.timeline_service().timeline(project.id)

        assert [item.attachments for item in timeline.items] == [
            [],
            [
                _attachment(notes, "text/plain", 12, 2, source),
                _attachment(sketch, "text/markdown", 9, 1, source),
                _attachment(photo, "image/png", 3, 1, source),
            ],
        ]

    def test_the_copy_of_the_draft_has_no_source(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        project = _make(container)
        opening = session.scalars(
            select(Item).where(Item.project_id == project.id)
        ).one()
        copy = Attachment(
            project_id=project.id,
            batch=1,
            title="Camp",
            filename="project.md",
            content_type="text/markdown",
            source_code=AttachmentSource.DRAFT,
            copied_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
        )
        container.attachment_store().put(copy, b"# Camp\n")
        session.add(
            ItemAttachment(
                item_id=opening.id,
                attachment_id=copy.id,
                position=1,
                attached_at=copy.copied_at,
            )
        )
        session.flush()

        (line,) = container.timeline_service().timeline(project.id).items

        assert [(a.id, a.source) for a in line.attachments] == [(copy.id, None)]

    def test_a_finished_project_has_the_time_of_its_latest_finish(
        self, container: ServiceContainer
    ) -> None:
        project = _make(container, state="finished")

        timeline = container.timeline_service().timeline(project.id)

        assert timeline.finished_at is not None
        assert timeline.finished_at == project.created_at

    def test_a_project_finished_again_has_the_time_of_its_second_finish(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        project = _make(container)
        transition = container.project_service().transition
        transition(ADA, project.id, TransitionKind.FINISHED)
        transition(ADA, project.id, TransitionKind.REOPENED)
        transition(ADA, project.id, TransitionKind.FINISHED)
        first, second = session.scalars(
            select(ProjectTransition.at)
            .where(
                ProjectTransition.project_id == project.id,
                ProjectTransition.kind_code == TransitionKind.FINISHED,
            )
            .order_by(ProjectTransition.at)
        ).all()

        timeline = container.timeline_service().timeline(project.id)

        assert first < second
        assert timeline.finished_at == second

    def test_a_reopened_project_has_no_finish(
        self, container: ServiceContainer, person: User
    ) -> None:
        project = _make(container)
        transition = container.project_service().transition
        transition(ADA, project.id, TransitionKind.FINISHED)
        transition(ADA, project.id, TransitionKind.REOPENED)

        timeline = container.timeline_service().timeline(project.id)

        assert timeline.finished_at is None

    def test_a_work_item_carries_its_session_as_its_line_and_head_show_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        work = _work(session, project, environment, SessionState.RUNNING)
        run = session.get_one(models.Session, work.id)
        run.started_at = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
        run.current_line = {
            "state": "working",
            "since": "2026-10-24T09:01:00+00:00",
            "step": {"tool": "Read", "input": {"file_path": "/work/Camp/plan.json"}},
        }
        session.flush()

        _opening, item = container.timeline_service().timeline(project.id).items

        assert item.work is not None
        assert item.work.model_dump() == {
            "state": SessionState.RUNNING,
            "current_line": {
                "state": "working",
                "since": datetime(2026, 10, 24, 9, 1, tzinfo=UTC),
                "step": {
                    "tool": "Read",
                    "input": {"file_path": "/work/Camp/plan.json"},
                },
                "agent": None,
                "text": None,
            },
            "environment": {"id": environment.id, "name": "Example-1"},
            "started_at": datetime(2026, 10, 24, 9, 0, tzinfo=UTC),
            "error": None,
            "autopilot": False,
        }

    def test_a_work_item_coming_up_has_the_servers_words_and_no_start_yet(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        work = _work(session, project, environment, SessionState.STARTING)
        session.get_one(models.Session, work.id).current_line = {
            "state": "starting",
            "since": "2026-10-24T09:00:00+00:00",
            "text": "Starting Example-1…",
        }
        session.flush()

        _opening, item = container.timeline_service().timeline(project.id).items

        assert item.work is not None
        assert (item.work.state, item.work.started_at) == (SessionState.STARTING, None)
        assert item.work.current_line is not None
        assert item.work.current_line.model_dump() == {
            "state": "starting",
            "since": datetime(2026, 10, 24, 9, 0, tzinfo=UTC),
            "step": None,
            "agent": None,
            "text": "Starting Example-1…",
        }

    def test_a_line_waiting_on_a_sub_agent_names_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        work = _work(session, project, environment, SessionState.RUNNING)
        call = {"subagent_type": "Explore", "description": "Survey the tent makers"}
        session.get_one(models.Session, work.id).current_line = {
            "state": "waiting",
            "since": "2026-10-24T09:00:00+00:00",
            "step": {"tool": "Task", "input": call},
            "agent": {"type": "Explore", "description": "Survey the tent makers"},
        }
        session.flush()

        _opening, item = container.timeline_service().timeline(project.id).items

        assert item.work is not None and item.work.current_line is not None
        line = item.work.current_line
        assert line.state == "waiting"
        assert line.step is not None
        assert (line.step.tool, line.step.input) == ("Task", call)
        assert line.agent is not None
        assert (line.agent.type, line.agent.description) == (
            "Explore",
            "Survey the tent makers",
        )

    def test_a_work_item_between_turns_has_no_line(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        _work(session, project, environment, SessionState.STOPPED)

        _opening, item = container.timeline_service().timeline(project.id).items

        assert item.work is not None
        assert (item.work.state, item.work.current_line) == (SessionState.STOPPED, None)

    def test_a_failed_start_has_the_sessions_error(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        work = _work(session, project, environment, SessionState.FAILED)
        run = session.get_one(models.Session, work.id)
        run.error = "The environment limit is reached"
        _turn(session, run, 1)

        _opening, item = container.timeline_service().timeline(project.id).items

        assert item.work is not None
        assert item.work.error == "The environment limit is reached"

    def test_a_failed_turn_has_its_latest_turns_error(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        work = _work(session, project, environment, SessionState.FAILED)
        run = session.get_one(models.Session, work.id)
        _turn(session, run, 1, "An earlier turn's error")
        _turn(session, run, 2, "The tests failed.")
        other = _work(session, project, environment, SessionState.FAILED)
        _turn(session, session.get_one(models.Session, other.id), 1, "Its own error")

        _opening, item, other_item = (
            container.timeline_service().timeline(project.id).items
        )

        assert item.work is not None and other_item.work is not None
        assert (item.work.error, other_item.work.error) == (
            "The tests failed.",
            "Its own error",
        )

    @pytest.mark.parametrize(
        "state", [SessionState.STOPPED, SessionState.IDLE, SessionState.RUNNING]
    )
    def test_an_item_that_is_not_failed_has_no_error(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        state: SessionState,
    ) -> None:
        project = _make(container)
        work = _work(session, project, environment, state)
        run = session.get_one(models.Session, work.id)
        run.error = "A start's error"
        _turn(session, run, 1, "A turn's error")

        _opening, item = container.timeline_service().timeline(project.id).items

        assert item.work is not None
        assert item.work.error is None

    def test_a_work_item_keeps_the_switch_it_was_briefed_under(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        _work(session, project, environment, SessionState.RUNNING, autopilot=True)
        _work(session, project, environment, SessionState.RUNNING)

        _opening, briefed_on, briefed_off = (
            container.timeline_service().timeline(project.id).items
        )

        assert project.autopilot is False
        assert briefed_on.work is not None and briefed_off.work is not None
        assert (briefed_on.work.autopilot, briefed_off.work.autopilot) == (True, False)


@pytest.mark.usefixtures("person")
class TestWorkStatus:
    def test_only_the_work_items_among_the_ids(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        work = _work(session, project, environment, SessionState.RUNNING)
        no_work = _run(session, project, environment, SessionState.RUNNING)
        notice = _bear(container, project, no_work, "notice", "The site", NOTICE)

        found = work_status(session, [work.id, no_work.id, notice.id, uuid.uuid4()])

        assert list(found) == [work.id]
        assert found[work.id].state == SessionState.RUNNING

    def test_no_ids_read_nothing(self, session: DbSession) -> None:
        assert work_status(session, []) == {}


CAMP_PLAN = """---
title: Camp plan
summary: Food and nights.
---

Before the weekend.

```decision id=D1
proposal: Cook on the fire.
```

```question id=Q1
default: Two nights
```
"""

PILOTS_WHOLE = """---
title: Camp plan
summary: Food and nights.
---

```decision id=D1
proposal: Cook on the fire.
answer: Agree
by: agent
at: 2026-10-12T09:30:00Z
```

```question id=Q1
default: Two nights
answer: deferred
by: agent
at: 2026-10-12T09:31:00Z
to: plan
```
"""
"""A document Pilot settled and deferred whole, which Pilot marks Done."""

_TEXT_KEYS = ("title", "summary", "body", "word_count", "read_minutes")
"""What an item document reads from its text."""


def _pilot(session: DbSession) -> User:
    return session.scalars(select(User).where(User.handle == "agent")).one()


def _revised(session: DbSession, item: Item) -> str:
    """The item's published text, retitled, summarised anew and grown a line."""
    published = _document(session, item).published_text
    assert published is not None
    return (
        published.replace("title: Camp plan", "title: Camp plan, revised")
        .replace("summary: Food and nights.", "summary: Food, nights and a lantern.")
        .replace("```question", "Bring a lantern.\n\n```question")
    )


def _read(container: ServiceContainer, item: Item) -> dict[str, Any]:
    read: dict[str, Any] = (
        container.timeline_service().item_document(item.id).model_dump(mode="json")
    )
    return read


def _text_of(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: entry[key] for key in _TEXT_KEYS}


@pytest.mark.usefixtures("person")
class TestItemDocument:
    def test_an_unknown_item_is_not_found(self, container: ServiceContainer) -> None:
        item_id = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as raised:
            container.timeline_service().item_document(item_id)

        assert raised.value.message == f"Document of item {item_id} was not found"

    def test_work_and_a_wait_have_no_document(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        work = _work(session, project, environment, SessionState.RUNNING)
        wait = _wait(session, project, session.get_one(models.Session, work.id))

        for item in (work, wait):
            with pytest.raises(RecordNotFoundException) as raised:
                container.timeline_service().item_document(item.id)
            assert raised.value.message == f"Document of item {item.id} was not found"

    def test_an_open_document_reads_as_its_timeline_entry_with_its_project(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container, environment_id=environment.id)
        data = container.test_data_service()
        item = data.item(project.id, "document", "Camp kit", CAMP_KIT)
        data.attach(item.id, [_file("sketch.md", b"# Sketch\n")])
        data.save(item.id, CAMP_KIT.replace("What we bring.", "What we pack."))

        read = _read(container, item)

        assert read == {**_items(container, project)[1], "project_id": str(project.id)}
        assert (read["writing"], len(read["attachments"])) == (True, 1)
        assert [
            part["block"]["section"] for part in read["body"] if part["type"] == "block"
        ] == [{"heading": "Which stove?"}]

    def test_the_opening_reads_its_words_verbatim(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        project = _make(container, opening="Let's camp.\n")
        opening = session.scalars(
            select(Item).where(Item.project_id == project.id)
        ).one()

        read = _read(container, opening)

        assert (read["kind"], read["words"], read["body"]) == (
            "opening",
            "Let's camp.\n",
            None,
        )

    def test_a_document_done_by_a_person_reads_as_done_fixed_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "document", "Camp plan", CAMP_PLAN)
        container.record_service().done(item, person)
        at_done = _items(container, project)[1]

        _save(
            container, session, project, item, environment, run, _revised(session, item)
        )
        read = _read(container, item)

        (done,) = _versions(session, item, VersionCause.DONE)
        assert _text_of(read) == _text_of(at_done)
        assert (read["title"], read["summary"]) == ("Camp plan", "Food and nights.")
        assert [part["type"] for part in read["body"]] == ["prose", "block", "block"]
        assert read["done"] == {**at_done["done"], "undo": True}
        assert "Bring a lantern." in _document(session, item).published_text
        assert "Bring a lantern." not in done.text
        assert _items(container, project)[1]["title"] == "Camp plan, revised"

    def test_a_document_pilot_marked_done_reads_as_done_fixed_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "document", "Camp plan", PILOTS_WHOLE)
        container.record_service().done(item, _pilot(session))
        at_done = _items(container, project)[1]

        _save(
            container, session, project, item, environment, run, _revised(session, item)
        )
        read = _read(container, item)

        assert _text_of(read) == _text_of(at_done)
        assert (read["done"]["cause"], read["done"]["by"]) == ("settled", PILOT)
        assert _items(container, project)[1]["summary"] == (
            "Food, nights and a lantern."
        )

    def test_done_again_after_undo_reads_as_the_second_done(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "document", "Camp plan", CAMP_PLAN)
        record = container.record_service()
        record.done(item, person)
        record.undo(item)
        record.answer(_document(session, item), "Q1", person, "Three nights")
        record.done(item, person)
        at_done = _items(container, project)[1]

        _save(
            container, session, project, item, environment, run, _revised(session, item)
        )
        read = _read(container, item)

        assert len(_versions(session, item, VersionCause.DONE)) == 2
        assert _text_of(read) == _text_of(at_done)
        assert read["body"][2]["block"]["answer"] == "Three nights"

    def test_a_document_undone_then_closed_by_finish_reads_as_last_published(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "document", "Camp plan", CAMP_PLAN)
        record = container.record_service()
        record.done(item, person)
        record.undo(item)
        record.answer(_document(session, item), "Q1", person, "Three nights")
        container.project_service().transition(ADA, project.id, TransitionKind.FINISHED)

        read = _read(container, item)

        assert read["done"]["cause"] == "finished"
        assert _text_of(read) == _text_of(_items(container, project)[1])
        assert read["body"][2]["block"]["answer"] == "Three nights"

    @pytest.mark.parametrize(
        ("kind", "text", "mark"),
        [
            pytest.param("question", QUESTION, "answer", id="one-ask answered"),
            pytest.param("notice", NOTICE, "read", id="notice read"),
            pytest.param("review", NOTICE, "reviewed", id="review reviewed"),
            pytest.param("question", QUESTION, "finish", id="closed by finish"),
        ],
    )
    def test_an_item_done_otherwise_reads_as_last_published(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
        kind: str,
        text: str,
        mark: str,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, kind, "Opens in May", text)
        record = container.record_service()
        if mark == "answer":
            record.answer(_document(session, item), "Q1", person, "By the hill")
        elif mark == "read":
            record.read(item, person)
        elif mark == "reviewed":
            record.reviewed(item, person)
        else:
            container.project_service().transition(
                ADA, project.id, TransitionKind.FINISHED
            )

        read = _read(container, item)

        assert read["done"] is not None
        assert _versions(session, item, VersionCause.DONE) == []
        assert read == {**_items(container, project)[1], "project_id": str(project.id)}


@pytest.mark.usefixtures("person")
class TestProjectDocument:
    def test_an_unknown_project_is_not_found(self, container: ServiceContainer) -> None:
        project_id = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as raised:
            container.timeline_service().project_document(
                project_id, DocumentRole.HANDBOOK
            )

        assert raised.value.message == f"Project {project_id} was not found"

    def test_a_draft_has_its_draft_and_no_handbook(
        self, container: ServiceContainer
    ) -> None:
        project = _make(container, state="draft", name="Camp")
        timelines = container.timeline_service()

        draft = timelines.project_document(project.id, DocumentRole.DRAFT)
        with pytest.raises(RecordNotFoundException) as raised:
            timelines.project_document(project.id, DocumentRole.HANDBOOK)

        assert draft.model_dump() == {"title": "Camp", "body": [], "writing": False}
        assert raised.value.message == f"Handbook of project {project.id} was not found"

    def test_the_handbook_born_at_create_reads_empty(
        self, container: ServiceContainer
    ) -> None:
        project = _make(container)

        handbook = container.timeline_service().project_document(
            project.id, DocumentRole.HANDBOOK
        )

        assert handbook.model_dump() == {"title": None, "body": [], "writing": False}

    @pytest.mark.parametrize("role", list(DocumentRole))
    def test_a_save_reads_as_drawn_written_by_pilot_until_its_turn_ends(
        self,
        container: ServiceContainer,
        environment: Environment,
        role: DocumentRole,
    ) -> None:
        project = _make(container, environment_id=environment.id)
        text = "# Camp\n\nKeep the stove dry.\n\n## Gear\n\nTwo tents.\n"
        data = container.test_data_service()
        data.save_project_document(project.id, role, text)
        timelines = container.timeline_service()

        saved = timelines.project_document(project.id, role).model_dump()
        data.end_turn(project.id)
        ended = timelines.project_document(project.id, role).model_dump()

        assert saved == {
            "title": "Camp",
            "body": [
                {
                    "type": "prose",
                    "markdown": "Keep the stove dry.\n\n## Gear\n\nTwo tents.",
                    "section": None,
                }
            ],
            "writing": True,
        }
        assert ended == {**saved, "writing": False}

    def test_its_blocks_read_with_their_answers(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        project = _make(container, state="draft", name="Camp")
        draft = session.scalars(
            select(Document).where(
                Document.project_id == project.id,
                Document.role_code == DocumentRole.DRAFT,
            )
        ).one()
        container.document_service().publish(
            draft,
            "# Camp\n\nThe dome stands up in five minutes.\n\n"
            "```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n\n"
            "Pick before the weekend.\n",
        )
        container.record_service().answer(draft, "D1", person, "Tunnel")

        (prose, block, after) = (
            container.timeline_service()
            .project_document(project.id, DocumentRole.DRAFT)
            .body
        )

        assert prose.model_dump() == {
            "type": "prose",
            "markdown": "The dome stands up in five minutes.",
            "section": None,
        }
        answered = block.model_dump(mode="json")["block"]
        assert (answered["answer"], answered["by"]) == ("Tunnel", ADA_USER)
        assert after.model_dump()["markdown"] == "Pick before the weekend."

    def test_a_held_save_reads_as_last_published(
        self, container: ServiceContainer, environment: Environment
    ) -> None:
        project = _make(container, environment_id=environment.id)
        data = container.test_data_service()
        data.save_project_document(
            project.id, DocumentRole.HANDBOOK, "# Camp\n\nTwo tents.\n"
        )

        ingested = data.save_project_document(
            project.id, DocumentRole.HANDBOOK, "```decision id=D1\nnope: 1\n```\n"
        )

        assert ingested.held
        handbook = container.timeline_service().project_document(
            project.id, DocumentRole.HANDBOOK
        )
        assert [part.model_dump()["markdown"] for part in handbook.body] == [
            "Two tents."
        ]


@pytest.mark.usefixtures("person")
class TestBadges:
    def _badges(
        self, container: ServiceContainer, person: User | None, *projects: Project
    ) -> dict[uuid.UUID, Badge]:
        return container.timeline_service().badges(
            person, [project.id for project in projects]
        )

    def test_the_open_prose_items_but_the_opening_wait(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(
            container,
            tasks=[{"id": "build", "title": "Build the camp", "status": "pending"}],
        )
        run = _run(session, project, environment)
        _bear(container, project, run, "decision", "Which tent?", DECISION)
        _bear(container, project, run, "question", "Where?", QUESTION)
        _bear(container, project, run, "action", "Pack the stove", ACTION)
        _bear(container, project, run, "decision", "Book the site", CONFIRMATION)
        _bear(container, project, run, "document", "Camp plan", TWO_ASKS)
        _bear(container, project, run, "review", "Refinement", "Read me.\n")

        assert self._badges(container, person, project) == {project.id: Badge(6, False)}

    def test_a_done_item_waits_on_no_one(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "question", "Where?", QUESTION)
        container.record_service().answer(
            _document(session, item), "Q1", person, "The hill"
        )

        assert self._badges(container, person, project) == {}

    def test_a_notice_waits_only_when_it_is_urgent(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        _bear(container, project, run, "notice", "Opens in May", NOTICE)
        assert self._badges(container, person, project) == {}

        _bear(
            container,
            project,
            run,
            "notice",
            "Storm",
            "---\ntitle: Storm\nurgent: true\n---\n\nA storm comes.\n",
        )

        assert self._badges(container, person, project) == {project.id: Badge(1, True)}

    def test_an_item_for_another_person_waits_on_them_alone(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        ben = _ben(container)
        project = _make(container)
        run = _run(session, project, environment)
        _bear(
            container,
            project,
            run,
            "question",
            "Your boots?",
            "---\ntitle: Your boots?\nfor: ben\n---\n```question id=Q1\n```\n",
        )
        _bear(
            container,
            project,
            run,
            "question",
            "Your tent?",
            "---\ntitle: Your tent?\nfor: ada\n---\n```question id=Q1\n```\n",
        )

        assert self._badges(container, person, project) == {project.id: Badge(1, False)}
        assert self._badges(container, ben, project) == {project.id: Badge(1, False)}

    def test_before_the_handle_an_item_for_anyone_waits_on_others(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        _bear(container, project, run, "question", "Where?", QUESTION)
        _bear(
            container,
            project,
            run,
            "question",
            "Your tent?",
            "---\ntitle: Your tent?\nfor: ada\n---\n```question id=Q1\n```\n",
        )

        assert self._badges(container, None, project) == {project.id: Badge(1, False)}

    def test_a_stopped_or_failed_work_item_waits_and_a_running_one_does_not(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        _work(session, project, environment, SessionState.STOPPED, urgent=True)
        _work(session, project, environment, SessionState.FAILED)
        for state in (SessionState.RUNNING, SessionState.IDLE, SessionState.STARTING):
            _work(session, project, environment, state)
        _work(
            session,
            project,
            environment,
            SessionState.STOPPED,
            done_at=datetime.now(UTC),
            done_cause_code="finished",
        )

        assert self._badges(container, person, project) == {project.id: Badge(2, True)}

    def test_a_wait_waits_on_no_one(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        _wait(session, project, _run(session, project, environment))

        assert self._badges(container, person, project) == {}

    def test_each_project_counts_its_own(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        camp = _make(container)
        hike = _make(container, name="Hike")
        quiet = _make(container, name="Quiet")
        run = _run(session, camp, environment)
        _bear(container, camp, run, "question", "Where?", QUESTION)
        _bear(container, camp, run, "action", "Pack the stove", ACTION)
        _bear(
            container,
            hike,
            _run(session, hike, environment),
            "question",
            "Which trail?",
            "---\ntitle: Which trail?\nurgent: true\n---\n```question id=Q1\n```\n",
        )

        assert self._badges(container, person, camp, hike, quiet) == {
            camp.id: Badge(2, False),
            hike.id: Badge(1, True),
        }
