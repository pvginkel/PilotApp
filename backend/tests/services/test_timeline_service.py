"""A project's timeline as a screen draws it, and the items waiting on a
person (F8, F12, F13, F18, F31, F78, F1.4)."""

import uuid
from datetime import UTC, datetime
from typing import Any, get_args

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.paths import tree_path
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import (
    Document,
    DoneCause,
    Environment,
    Item,
    ItemKind,
    PlanTask,
    Project,
    ProjectTransition,
    SaveError,
    User,
)
from app.models.reference import ErrorKind, SessionState, TransitionKind
from app.schemas.testing_record import InventedProjectCreateSchema
from app.schemas.timeline import DoneCauseCode, ItemKindCode
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.timeline_service import Badge

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
    **values: Any,
) -> Item:
    """A work item, one identity with its session (DB decision 3)."""
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
    return work


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
