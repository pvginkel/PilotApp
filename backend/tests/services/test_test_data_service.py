"""The dev stack's seed: an invented record, written through the engine's own
operations where the engine writes it (slice 002 P9)."""

import base64
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pilot_dsl as dsl
import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.app import App
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged, TreeHashMoved
from app.engine.tree import TreeDocument, TreeFile, TreePlan
from app.exceptions import (
    InvalidOperationException,
    RecordNotFoundException,
    ResourceConflictException,
    ValidationException,
)
from app.models import (
    Attachment,
    Block,
    Document,
    DocumentVersion,
    Effect,
    Environment,
    Item,
    ItemAttachment,
    ItemKind,
    PlanTask,
    Project,
    ProjectMember,
    ProjectTransition,
    Turn,
    User,
    WriterQuestion,
)
from app.models.reference import (
    AnswerChannel,
    AttachmentSource,
    DocumentRole,
    ProjectState,
    SessionState,
    TaskStatus,
    TransitionKind,
    UserKind,
    VersionCause,
)
from app.schemas.testing_record import (
    OPENING_WORDS,
    InventedFileSchema,
    InventedProjectCreateSchema,
    InventedWriterQuestionSchema,
)
from app.services import test_data_service
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.session_record_service import read_records
from app.startup import load_test_data_hook
from tests.support.chats import ChatWriter, open_chat
from tests.support.fake_controller import ServedFakeController


@pytest.fixture
def counts(container: ServiceContainer) -> dict[str, int]:
    """The seed, loaded into the test's database."""
    return container.test_data_service().load_all()


def _project(session: DbSession, slug: str | None) -> Project:
    return session.scalars(
        select(Project).where(
            Project.slug.is_(None) if slug is None else Project.slug == slug
        )
    ).one()


def _user(session: DbSession, handle: str) -> User:
    return session.scalars(select(User).where(User.handle == handle)).one()


def _items(session: DbSession, project: Project) -> list[Item]:
    return list(
        session.scalars(
            select(Item).where(Item.project_id == project.id).order_by(Item.seq)
        )
    )


def _item(session: DbSession, title: str) -> Item:
    return session.scalars(select(Item).where(Item.title == title)).one()


def _block(session: DbSession, item: Item, local_id: str) -> Block:
    return session.scalars(
        select(Block).where(Block.document_id == item.id, Block.local_id == local_id)
    ).one()


def _transitions(
    session: DbSession, project: Project
) -> list[tuple[TransitionKind, uuid.UUID]]:
    return [
        (transition.kind_code, transition.by_user_id)
        for transition in session.scalars(
            select(ProjectTransition)
            .where(ProjectTransition.project_id == project.id)
            .order_by(ProjectTransition.at, ProjectTransition.id)
        )
    ]


def _members(session: DbSession, project: Project) -> list[uuid.UUID]:
    """The open memberships' people, in the order they joined."""
    return list(
        session.scalars(
            select(ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project.id, ProjectMember.left_at.is_(None)
            )
            .order_by(ProjectMember.joined_at, ProjectMember.id)
        )
    )


def _plan(container: ServiceContainer, project: Project) -> dict[str, Any]:
    plan: dict[str, Any] = json.loads(container.plan_service().render(project).text)
    return plan


class TestTestDataService:
    def test_load_all_counts_the_rows_it_seeded(self, counts: dict[str, int]) -> None:
        assert counts == {
            "users": 2,
            "projects": 4,
            "items": 11,
            "documents": 18,
            "blocks": 13,
            "plan tasks": 10,
            "plan notes": 3,
            "attachments": 1,
        }

    def test_two_people_who_sign_in(
        self, counts: dict[str, int], session: DbSession
    ) -> None:
        people = session.scalars(
            select(User).where(User.kind_code == UserKind.PERSON).order_by(User.handle)
        ).all()

        assert [(user.handle, user.subject, user.avatar_slot) for user in people] == [
            ("ada", "example-ada", 1),
            ("ben", "example-ben", 2),
        ]

    def test_a_draft_project_with_its_draft(
        self, counts: dict[str, int], session: DbSession
    ) -> None:
        garden = _project(session, None)
        ada = _user(session, "ada")
        draft = session.scalars(
            select(Document).where(Document.project_id == garden.id)
        ).one()

        assert garden.state_code is ProjectState.DRAFT
        assert garden.name == "Garden planner"
        assert garden.created_by_user_id == ada.id
        assert draft.role_code is DocumentRole.DRAFT
        assert dsl.parse(draft.published_text or "").blocks[0].local_id == "Q1"
        assert _items(session, garden) == []
        assert (
            session.scalars(
                select(ProjectTransition.id).where(
                    ProjectTransition.project_id == garden.id
                )
            ).all()
            == []
        )
        assert [
            (member.user_id, member.joined_at)
            for member in session.scalars(
                select(ProjectMember).where(ProjectMember.project_id == garden.id)
            )
        ] == [(ada.id, garden.created_at)]

    def test_an_open_project_with_its_draft_handbook_and_members(
        self, counts: dict[str, int], session: DbSession
    ) -> None:
        recipes = _project(session, test_data_service.SLUG)
        ada, ben = _user(session, "ada"), _user(session, "ben")

        assert recipes.state_code is ProjectState.OPEN
        assert recipes.name == "Recipe box"
        assert (recipes.ticket, recipes.repo) == ("RB-12", "recipe-box")
        assert {
            document.role_code: document.path
            for document in session.scalars(
                select(Document).where(Document.project_id == recipes.id)
            )
        } == {DocumentRole.DRAFT: "project.md", DocumentRole.HANDBOOK: "handbook.md"}
        assert [
            (transition.kind_code, transition.by_user_id)
            for transition in session.scalars(
                select(ProjectTransition).where(
                    ProjectTransition.project_id == recipes.id
                )
            )
        ] == [(TransitionKind.OPENED, ada.id)]
        members = {
            member.user_id: member.joined_at
            for member in session.scalars(
                select(ProjectMember).where(ProjectMember.project_id == recipes.id)
            )
        }
        assert members.keys() == {ada.id, ben.id}
        assert members[ada.id] == recipes.created_at

    def test_a_finished_project_with_its_history(
        self, counts: dict[str, int], container: ServiceContainer, session: DbSession
    ) -> None:
        bikes = _project(session, test_data_service.FINISHED_SLUG)
        ada, ben = _user(session, "ada"), _user(session, "ben")

        assert (bikes.name, bikes.state_code, bikes.archived, bikes.autopilot) == (
            "Bike repair log",
            ProjectState.FINISHED,
            False,
            False,
        )
        assert (bikes.ticket, bikes.repo) == ("BL-3", "bike-log")
        assert _transitions(session, bikes) == [
            (TransitionKind.OPENED, ben.id),
            (TransitionKind.AUTOPILOT_ON, ben.id),
            (TransitionKind.FINISHED, ben.id),
            (TransitionKind.AUTOPILOT_OFF, ben.id),
        ]
        assert _members(session, bikes) == [ben.id, ada.id]
        assert {task["status"] for task in _plan(container, bikes)["tasks"]} == {"done"}
        assert [item.kind_code for item in _items(session, bikes)] == ["opening"]

    def test_an_archived_project_as_it_was_left(
        self, counts: dict[str, int], container: ServiceContainer, session: DbSession
    ) -> None:
        album = _project(session, test_data_service.ARCHIVED_SLUG)
        ada = _user(session, "ada")

        assert (album.name, album.state_code, album.archived) == (
            "Photo album",
            ProjectState.OPEN,
            True,
        )
        assert _transitions(session, album) == [
            (TransitionKind.OPENED, ada.id),
            (TransitionKind.ARCHIVED, ada.id),
        ]
        assert _members(session, album) == [ada.id]
        assert [
            (task["id"], task["status"]) for task in _plan(container, album)["tasks"]
        ] == [("sort", "in_progress"), ("caption", "pending")]

    def test_prose_items_of_every_kind(
        self, counts: dict[str, int], session: DbSession
    ) -> None:
        recipes = _project(session, test_data_service.SLUG)
        items = _items(session, recipes)
        run = session.scalars(select(models.Session)).one()

        assert [item.kind_code for item in items] == [
            "opening",
            "decision",
            "confirmation",
            "question",
            "action",
            "notice",
            "document",
            "document",
            "review",
        ]
        assert {item.kind_code for item in items} == set(
            session.scalars(select(ItemKind.code).where(ItemKind.form == "prose"))
        )
        assert items[0].created_by_user_id == _user(session, "ada").id
        assert {item.created_by_session_id for item in items[1:]} == {run.id}
        assert run.environment_id == test_data_service.ENVIRONMENT_ID
        assert session.get_one(Environment, run.environment_id).exempt is False
        assert [session.get_one(Document, item.id).path for item in items[1:3]] == [
            "items/2-which-layout-for-a-recipe-card.md",
            "items/3-delete-the-scanned-duplicates.md",
        ]
        confirmation = items[2]
        assert confirmation.urgent
        assert confirmation.for_user_id == _user(session, "ada").id
        assert confirmation.plan_task_id == "import"

    def test_blocks_unanswered_answered_deferred_and_done(
        self, counts: dict[str, int], session: DbSession
    ) -> None:
        agent, ada, ben = (_user(session, h) for h in ("agent", "ada", "ben"))
        import_plan = _item(session, "How to import the remaining cards")

        def state(item: Item, local_id: str) -> tuple[Any, ...]:
            block = _block(session, item, local_id)
            return (
                block.answer,
                block.answered_by_user_id,
                block.via_code,
                block.deferred_to_task_id,
                block.done_at is not None,
            )

        assert state(_item(session, "Delete the scanned duplicates?"), "C1") == (
            None,
            None,
            None,
            None,
            False,
        )
        assert state(import_plan, "D1") == (None, None, None, None, False)
        assert state(import_plan, "A1") == (None, None, None, None, False)
        # Pilot's answer and Pilot's deferral are written in the born text.
        assert state(_item(session, "Which units do the recipes use?"), "Q1") == (
            "Both, as written",
            agent.id,
            None,
            None,
            False,
        )
        assert state(import_plan, "Q2") == ("deferred", agent.id, None, None, False)
        assert "to: plan" in (
            session.get_one(Document, import_plan.id).published_text or ""
        )
        assert state(_item(session, "Which layout for a recipe card?"), "D1") == (
            "One column",
            ben.id,
            AnswerChannel.APP,
            None,
            False,
        )
        assert state(import_plan, "Q1") == (
            "Photograph it; Ben reads most of them",
            ada.id,
            AnswerChannel.CHAT,
            None,
            False,
        )
        assert state(import_plan, "D2") == (
            "deferred",
            ben.id,
            AnswerChannel.APP,
            "launch",
            False,
        )
        action = _block(
            session, _item(session, "Put the card scanner on the kitchen desk"), "A1"
        )
        assert (
            action.done_at is not None,
            action.answered_by_user_id,
            action.note,
        ) == (
            True,
            ada.id,
            "It is on the desk, plugged in.",
        )

    def test_items_done_through_the_records_writes(
        self, counts: dict[str, int], session: DbSession
    ) -> None:
        recipes = _project(session, test_data_service.SLUG)
        ada, ben = _user(session, "ada"), _user(session, "ben")
        photo_storage = _item(session, "Storing recipe photos")

        assert {
            item.title: (item.done_cause_code, item.done_by_user_id)
            for item in _items(session, recipes)
            if item.done_at is not None
        } == {
            "Which layout for a recipe card?": ("answered", ben.id),
            "Put the card scanner on the kitchen desk": ("answered", ada.id),
            "Twenty cards typed up": ("marked", ada.id),
            "Storing recipe photos": ("marked", ada.id),
        }
        assert [
            (block.local_id, block.answer, block.via_code)
            for block in session.scalars(
                select(Block)
                .where(Block.document_id == photo_storage.id)
                .order_by(Block.position)
            )
        ] == [
            ("D1", "In object storage", AnswerChannel.RECOMMENDED),
            ("Q1", "2 MB", AnswerChannel.RECOMMENDED),
            ("A1", None, AnswerChannel.APP),
        ]
        assert session.scalars(
            select(DocumentVersion.cause_code)
            .where(DocumentVersion.document_id == photo_storage.id)
            .order_by(DocumentVersion.number)
        ).all() == [VersionCause.BORN, VersionCause.DONE]

    def test_its_times_are_the_runs(
        self, counts: dict[str, int], session: DbSession
    ) -> None:
        # No invented date: an answer's `at` and an action's `done` are the
        # clock's when the seed ran.
        moments = [
            moment
            for row in session.execute(select(Block.answered_at, Block.done_at))
            for moment in row
            if moment is not None
        ]

        assert len(moments) == 9
        assert all(
            abs(datetime.now(UTC) - moment) < timedelta(minutes=1) for moment in moments
        )

    def test_the_plan_has_tasks_in_every_status_and_one_removed(
        self, counts: dict[str, int], container: ServiceContainer, session: DbSession
    ) -> None:
        recipes = _project(session, test_data_service.SLUG)
        plan = _plan(container, recipes)
        spike = session.get_one(PlanTask, (recipes.id, "spike"))

        assert [(task["id"], task["status"]) for task in plan["tasks"]] == [
            ("scope", "done"),
            ("model", "done"),
            ("build", "in_progress"),
            ("import", "pending"),
            ("launch", "pending"),
        ]
        assert {task["status"] for task in plan["tasks"]} == set(TaskStatus)
        assert spike.removed_at is not None

    def test_the_plans_notes_name_items_blocks_a_deferred_one_among_them(
        self, counts: dict[str, int], container: ServiceContainer, session: DbSession
    ) -> None:
        recipes = _project(session, test_data_service.SLUG)
        plan = _plan(container, recipes)
        decision = _item(session, "Which layout for a recipe card?")
        import_plan = _item(session, "How to import the remaining cards")
        notes = {
            note["id"]: (task["id"], note["refs"])
            for task in plan["tasks"]
            for note in task["notes"]
        } | {note["id"]: (None, note["refs"]) for note in plan["notes"]}

        assert notes == {
            "card-layout": ("build", [f"{decision.id}/D1"]),
            "card-photos": ("launch", [f"{import_plan.id}/D2"]),
            "print-view": (None, [f"{import_plan.id}/Q2"]),
        }
        assert _block(session, import_plan, "D2").deferred_to_task_id == "launch"
        assert _block(session, import_plan, "Q2").answer == dsl.DEFERRED

    def test_an_attachment_hangs_on_an_item(
        self, counts: dict[str, int], container: ServiceContainer, session: DbSession
    ) -> None:
        recipes = _project(session, test_data_service.SLUG)
        attachment = session.scalars(select(Attachment)).one()
        hung = session.scalars(select(ItemAttachment)).one()
        timeline = json.loads(container.view_service().timeline(recipes).text)
        decision = next(
            item
            for item in timeline["items"]
            if item["title"] == "Which layout for a recipe card?"
        )

        assert hung.attachment_id == attachment.id
        assert attachment.source_code is AttachmentSource.FILE
        assert attachment.size == len(container.attachment_store().get(attachment))
        assert decision["attachments"] == [
            {"id": str(attachment.id), "path": "attachments/1/layout-sketches.md"}
        ]
        assert timeline["attachments"][0]["source"] == (
            "example-recipes-1:/work/RecipeBox/notes/layout-sketches.md"
        )

    def test_every_seeded_file_saves_back_clean(
        self, counts: dict[str, int], container: ServiceContainer, session: DbSession
    ) -> None:
        # A record the engine could have produced: the agent saving back each
        # file it reads raises no fault and changes nothing.
        environment = session.get_one(Environment, test_data_service.ENVIRONMENT_ID)
        tree = container.tree_service()
        saved: list[str] = []
        # An archived project's folder is out of the tree.
        for project in session.scalars(
            select(Project).where(Project.archived.is_(False))
        ):
            for path, tree_hash in tree.hashes(project).items():
                if not isinstance(tree.resolve(path), TreeDocument | TreePlan):
                    continue
                answer = container.ingest_service().ingest(
                    path, tree.read(path).content, tree_hash, environment, None
                )
                assert (answer.held, answer.faults, answer.stale, answer.content) == (
                    False,
                    (),
                    False,
                    None,
                ), path
                saved.append(path)

        assert len(saved) == 18

    def test_a_plan_with_a_fault_seeds_nothing(
        self,
        app: Flask,
        session: DbSession,
        container: ServiceContainer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        assert isinstance(app, App)
        monkeypatch.setattr(
            test_data_service, "TASKS", [("scope", "Agree the scope", "finished")]
        )

        # `cli load-test-data`'s hook: the people, the projects and their
        # documents are written before the plan faults.
        with pytest.raises(InvalidOperationException) as raised:
            load_test_data_hook(app)

        assert raised.value.operation == "seed the plan of project recipe-box"
        assert "`status: finished` is not pending, in_progress or done" in (
            raised.value.cause
        )
        assert (
            session.scalars(select(User).where(User.kind_code == UserKind.PERSON)).all()
            == []
        )
        assert session.scalars(select(Project)).all() == []


DECISION_TEXT = """```decision id=D1
options:
  - Dome
  - Tunnel
```
"""


def _spec(**spec: Any) -> InventedProjectCreateSchema:
    spec.setdefault("members", ["ada"])
    return InventedProjectCreateSchema.model_validate(spec)


class TestPerson:
    def test_a_person_takes_the_lowest_free_slot(
        self, container: ServiceContainer, person: User
    ) -> None:
        ben = container.test_data_service().person("ben", "Ben Example")

        assert (ben.kind_code, ben.handle, ben.name, ben.avatar_slot) == (
            UserKind.PERSON,
            "ben",
            "Ben Example",
            2,
        )
        assert ben.subject is not None and ben.subject.startswith("invented-")

    def test_without_a_name_the_handle_is_the_name(
        self, container: ServiceContainer
    ) -> None:
        assert container.test_data_service().person("ben", None).name == "ben"

    def test_the_handle_steps_refusals_hold(
        self, container: ServiceContainer, person: User
    ) -> None:
        service = container.test_data_service()

        with pytest.raises(ValidationException):
            service.person("Ben", None)
        with pytest.raises(InvalidOperationException) as taken:
            service.person("ada", None)
        with pytest.raises(InvalidOperationException) as pilots:
            service.person("agent", None)

        assert taken.value.cause == "another person has it"
        assert pilots.value.cause == "it is Pilot's"


class TestEnvironment:
    def test_an_environment_pilot_has_touched(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        container.test_data_service().environment("example-env-2", "Example-2")

        environment = session.get_one(Environment, "example-env-2")
        assert (environment.name, environment.exempt) == ("Example-2", False)

    def test_an_id_taken_is_refused(
        self, container: ServiceContainer, environment: Environment
    ) -> None:
        with pytest.raises(ResourceConflictException):
            container.test_data_service().environment(environment.id, "Again")


@pytest.mark.usefixtures("person")
class TestProject:
    @pytest.mark.parametrize(
        ("standing", "kinds"),
        [
            ({"state": "draft"}, []),
            ({"state": "open"}, [TransitionKind.OPENED]),
            (
                {"state": "finished"},
                [TransitionKind.OPENED, TransitionKind.FINISHED],
            ),
            (
                {"state": "open", "autopilot": True},
                [TransitionKind.OPENED, TransitionKind.AUTOPILOT_ON],
            ),
            (
                {"state": "open", "paused": True},
                [TransitionKind.OPENED, TransitionKind.PAUSED],
            ),
            (
                {"state": "open", "paused": True, "archived": True},
                [TransitionKind.OPENED, TransitionKind.PAUSED, TransitionKind.ARCHIVED],
            ),
            ({"state": "draft", "archived": True}, [TransitionKind.ARCHIVED]),
            (
                {"state": "finished", "archived": True},
                [
                    TransitionKind.OPENED,
                    TransitionKind.FINISHED,
                    TransitionKind.ARCHIVED,
                ],
            ),
        ],
    )
    def test_the_transitions_lead_to_the_standing(
        self,
        container: ServiceContainer,
        session: DbSession,
        standing: dict[str, Any],
        kinds: list[TransitionKind],
    ) -> None:
        ada = _user(session, "ada")

        project = container.test_data_service().project(_spec(name="Made", **standing))

        assert _transitions(session, project) == [(kind, ada.id) for kind in kinds]
        assert (
            project.state_code.value,
            project.archived,
            project.autopilot,
            project.paused,
        ) == (
            standing["state"],
            standing.get("archived", False),
            standing.get("autopilot", False),
            standing.get("paused", False),
        )
        assert (project.slug is None) == (standing["state"] == "draft")

    def test_the_members_in_order_the_first_its_creator(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        service = container.test_data_service()
        ben = service.person("ben", "Ben Example")
        ada = _user(session, "ada")

        project = service.project(_spec(members=["ben", "ada"]))

        assert _members(session, project) == [ben.id, ada.id]
        assert project.created_by_user_id == ben.id

    def test_the_draft_is_titled_by_the_name(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        service = container.test_data_service()

        named = service.project(_spec(name="Recipe box", state="draft"))
        unnamed = service.project(_spec(state="draft"))

        assert (named.name, unnamed.name) == ("Recipe box", None)
        assert (
            session.scalars(
                select(Document.published_text).where(Document.project_id == named.id)
            ).one()
            == "# Recipe box\n"
        )

    def test_the_plan_with_its_steps_and_notes(
        self, container: ServiceContainer
    ) -> None:
        project = container.test_data_service().project(
            _spec(
                ticket="RB-12",
                repo="pvginkel/RecipeBox",
                tasks=[
                    {"id": "scope", "title": "Agree the scope", "status": "done"},
                    {
                        "id": "build",
                        "title": "Build it",
                        "status": "in_progress",
                        "notes": [{"id": "n1", "summary": "S", "content": "C"}],
                    },
                ],
                notes=[{"id": "print", "summary": "Print", "content": "Later"}],
            )
        )
        plan = _plan(container, project)

        assert (plan["ticket"], plan["repo"]) == ("RB-12", "pvginkel/RecipeBox")
        assert [
            (task["id"], task["status"], [note["id"] for note in task["notes"]])
            for task in plan["tasks"]
        ] == [("scope", "done", []), ("build", "in_progress", ["n1"])]
        assert [note["id"] for note in plan["notes"]] == ["print"]

    def test_open_items_are_notices_a_session_added(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = container.test_data_service().project(
            _spec(open_items=2, environment_id=environment.id)
        )
        run = session.scalars(
            select(models.Session).where(models.Session.project_id == project.id)
        ).one()

        assert [
            (item.kind_code, item.title, item.done_at, item.created_by_session_id)
            for item in _items(session, project)
        ] == [
            ("opening", "New project", None, None),
            ("notice", "Notice 1", None, run.id),
            ("notice", "Notice 2", None, run.id),
        ]
        assert run.environment_id == environment.id

    def test_past_the_draft_the_first_member_wrote_its_opening(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        service = container.test_data_service()
        ben = service.person("ben", "Ben Example")
        words = "Let's camp.\n\n```decision id=D1\nnope: 1\n```\n\n```question id=Q1\n"

        project = service.project(
            _spec(name="Camp", members=["ben", "ada"], opening=words)
        )

        [opening] = _items(session, project)
        assert (
            opening.kind_code,
            opening.title,
            opening.created_by_user_id,
            opening.created_by_session_id,
            session.get_one(Document, opening.id).published_text,
        ) == ("opening", "Camp", ben.id, None, words)
        assert session.scalars(select(Block)).all() == []

    @pytest.mark.parametrize(
        ("spec", "title"),
        [({"name": "Camp"}, "Camp"), ({}, "New project")],
    )
    def test_the_opening_is_titled_by_the_name(
        self,
        container: ServiceContainer,
        session: DbSession,
        spec: dict[str, Any],
        title: str,
    ) -> None:
        project = container.test_data_service().project(_spec(**spec))

        [opening] = _items(session, project)
        assert (
            opening.title,
            session.get_one(Document, opening.id).published_text,
        ) == (title, OPENING_WORDS)

    @pytest.mark.parametrize(
        ("state", "roles"),
        [
            ("draft", [DocumentRole.DRAFT]),
            ("open", [DocumentRole.DRAFT, DocumentRole.HANDBOOK]),
            ("finished", [DocumentRole.DRAFT, DocumentRole.HANDBOOK]),
        ],
    )
    def test_past_the_draft_its_handbook_is_born_empty(
        self,
        container: ServiceContainer,
        session: DbSession,
        state: str,
        roles: list[DocumentRole],
    ) -> None:
        project = container.test_data_service().project(_spec(name="Camp", state=state))

        documents = session.scalars(
            select(Document)
            .where(Document.project_id == project.id)
            .order_by(Document.role_code)
        ).all()
        assert [document.role_code for document in documents] == roles
        assert [
            (document.path, document.published_text)
            for document in documents
            if document.role_code is DocumentRole.HANDBOOK
        ] == ([("handbook.md", "")] if state != "draft" else [])

    def test_a_draft_has_no_opening(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        project = container.test_data_service().project(
            _spec(name="Camp", state="draft", opening="Let's camp.")
        )

        assert _items(session, project) == []

    @pytest.mark.parametrize(
        ("spec", "message"),
        [
            (
                {"state": "finished", "autopilot": True},
                "Cannot make the project because a finished project has auto pilot off",
            ),
            (
                {"state": "draft", "paused": True},
                "Cannot make the project because only an open project is paused",
            ),
            (
                {"state": "finished", "paused": True},
                "Cannot make the project because only an open project is paused",
            ),
            (
                {"members": ["ada", "ada"]},
                "Cannot make the project because a member is named twice",
            ),
            (
                {"open_items": 1},
                "Cannot make the project because its open items need a session's"
                " environment, and no environment_id is given",
            ),
            (
                {"ticket": "not a ticket"},
                "Cannot make the project because its plan has a fault:"
                " `ticket: not a ticket` is not a ticket id",
            ),
        ],
    )
    def test_a_spec_out_of_the_record_is_refused(
        self,
        container: ServiceContainer,
        session: DbSession,
        spec: dict[str, Any],
        message: str,
    ) -> None:
        with pytest.raises(ValidationException) as raised:
            container.test_data_service().project(_spec(**spec))

        assert raised.value.message == message

    @pytest.mark.parametrize(
        ("spec", "message"),
        [
            ({"members": ["nobody"]}, "Person nobody was not found"),
            ({"members": ["agent"]}, "Person agent was not found"),
            ({"environment_id": "nowhere"}, "Environment nowhere was not found"),
        ],
    )
    def test_what_is_not_on_the_record_is_not_found(
        self, container: ServiceContainer, spec: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(RecordNotFoundException) as raised:
            container.test_data_service().project(_spec(**spec))

        assert raised.value.message == message


@pytest.fixture
def camp(
    container: ServiceContainer, person: User, environment: Environment
) -> Project:
    """An open project with its session in `environment`."""
    return container.test_data_service().project(
        _spec(name="Camp", environment_id=environment.id)
    )


def _session_of(session: DbSession, project: Project) -> models.Session:
    return session.scalars(
        select(models.Session).where(models.Session.project_id == project.id)
    ).one()


class TestItem:
    def test_the_projects_session_adds_it_with_its_title(
        self, container: ServiceContainer, session: DbSession, camp: Project
    ) -> None:
        item = container.test_data_service().item(
            camp.id, "decision", "Which tent?", DECISION_TEXT
        )

        assert (
            item.project_id,
            item.kind_code,
            item.title,
            item.seq,
            item.created_by_session_id,
        ) == (camp.id, "decision", "Which tent?", 2, _session_of(session, camp).id)
        assert session.get_one(Document, item.id).published_text == (
            "---\ntitle: Which tent?\n---\n" + DECISION_TEXT
        )
        assert _block(session, item, "D1").kind_code == "decision"

    def test_the_session_started_last_adds_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        camp: Project,
        environment: Environment,
    ) -> None:
        first = _session_of(session, camp)
        later = models.Session(
            project_id=camp.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Camp",
            token_hash=uuid.uuid4().hex * 2,
            state_code=first.state_code,
            started_at=first.started_at + timedelta(minutes=5),
        )
        session.add(later)
        session.flush()

        item = container.test_data_service().item(
            camp.id, "notice", "Palette", "Blue.\n"
        )

        assert item.created_by_session_id == later.id

    def test_an_unknown_project_is_not_found(self, container: ServiceContainer) -> None:
        project_id = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as raised:
            container.test_data_service().item(project_id, "notice", "N", "Hi")

        assert raised.value.message == f"Project {project_id} was not found"

    def test_a_project_without_a_session_is_refused(
        self, container: ServiceContainer, person: User
    ) -> None:
        project = container.test_data_service().project(_spec())

        with pytest.raises(InvalidOperationException) as raised:
            container.test_data_service().item(project.id, "notice", "N", "Hi")

        assert raised.value.message == (
            f"Cannot add an item to project {project.id} because the project has "
            "no session: make it with an environment_id"
        )

    @pytest.mark.parametrize("kind", ["opening", "work"])
    def test_a_kind_pilot_does_not_add_is_refused(
        self, container: ServiceContainer, camp: Project, kind: str
    ) -> None:
        with pytest.raises(InvalidOperationException):
            container.test_data_service().item(camp.id, kind, "N", "Hi")

    def test_a_text_with_a_fault_is_refused(
        self, container: ServiceContainer, session: DbSession, camp: Project
    ) -> None:
        with pytest.raises(InvalidOperationException):
            container.test_data_service().item(
                camp.id, "decision", "N", "```decision id=D1\nnope: 1\n```\n"
            )

        assert len(_items(session, camp)) == 1


class TestSave:
    @pytest.fixture
    def notice(self, container: ServiceContainer, camp: Project) -> Item:
        return container.test_data_service().item(
            camp.id, "notice", "Palette", "Blue and green.\n"
        )

    def test_a_save_with_a_fault_is_held(
        self,
        container: ServiceContainer,
        session: DbSession,
        camp: Project,
        notice: Item,
    ) -> None:
        document = session.get_one(Document, notice.id)
        published = document.published_text

        ingested = container.test_data_service().save(notice.id, "Red.\n")

        assert (ingested.held, [fault.message for fault in ingested.faults]) == (
            True,
            [
                "the item has no title: give it `title` in the front matter"
                " or a first heading"
            ],
        )
        assert container.tree_service().held(camp, document)
        assert (document.published_text, document.ingested_text) == (
            published,
            "Red.\n",
        )

    def test_a_clean_save_is_published_by_the_session(
        self,
        container: ServiceContainer,
        session: DbSession,
        camp: Project,
        notice: Item,
    ) -> None:
        text = "---\ntitle: Palette\n---\nRed.\n"

        ingested = container.test_data_service().save(notice.id, text)

        assert (ingested.held, ingested.faults, ingested.stale) == (False, (), False)
        document = session.get_one(Document, notice.id)
        assert document.published_text == text
        version = session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.id.desc())
            .limit(1)
        ).one()
        assert version.session_id == _session_of(session, camp).id

    def test_a_save_after_a_held_one_is_on_its_hash(
        self, container: ServiceContainer, notice: Item
    ) -> None:
        service = container.test_data_service()
        service.save(notice.id, "Red.\n")

        ingested = service.save(notice.id, "---\ntitle: Palette\n---\nRed.\n")

        assert (ingested.held, ingested.stale) == (False, False)

    def test_an_unknown_item_is_not_found(self, container: ServiceContainer) -> None:
        item_id = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as raised:
            container.test_data_service().save(item_id, "Red.")

        assert raised.value.message == f"Item {item_id} was not found"

    def test_an_archived_projects_item_is_not_found(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        environment: Environment,
    ) -> None:
        project = container.test_data_service().project(
            _spec(archived=True, environment_id=environment.id)
        )
        [opening] = _items(session, project)

        with pytest.raises(RecordNotFoundException):
            container.test_data_service().save(opening.id, "Red.")

    def test_a_project_without_a_session_is_refused(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        project = container.test_data_service().project(_spec())
        [opening] = _items(session, project)

        with pytest.raises(InvalidOperationException) as raised:
            container.test_data_service().save(opening.id, "Red.")

        assert raised.value.message == (
            f"Cannot save item {opening.id} because the project has no session: "
            "make it with an environment_id"
        )


class TestEndTurn:
    @pytest.fixture
    def notice(self, container: ServiceContainer, camp: Project) -> Item:
        return container.test_data_service().item(
            camp.id, "notice", "Palette", "Blue and green.\n"
        )

    def test_the_sessions_documents_are_written_no_longer_and_versioned(
        self,
        container: ServiceContainer,
        session: DbSession,
        camp: Project,
        notice: Item,
    ) -> None:
        service = container.test_data_service()
        service.save(notice.id, "---\ntitle: Palette\n---\nRed.\n")
        document = session.get_one(Document, notice.id)
        assert document.writing_session_id == _session_of(session, camp).id

        service.end_turn(camp.id)

        assert (document.writing_session_id, document.writing_since) == (None, None)
        assert session.execute(
            select(DocumentVersion.cause_code, DocumentVersion.session_id)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.number)
        ).all() == [
            (VersionCause.BORN, _session_of(session, camp).id),
            (VersionCause.TURN, _session_of(session, camp).id),
        ]

    def test_a_turn_that_saved_nothing_cuts_no_version(
        self,
        container: ServiceContainer,
        session: DbSession,
        camp: Project,
        notice: Item,
    ) -> None:
        container.test_data_service().end_turn(camp.id)

        assert session.scalars(
            select(DocumentVersion.cause_code).where(
                DocumentVersion.document_id == notice.id
            )
        ).all() == [VersionCause.BORN]

    def test_an_unknown_project_is_not_found(self, container: ServiceContainer) -> None:
        project_id = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as raised:
            container.test_data_service().end_turn(project_id)

        assert raised.value.message == f"Project {project_id} was not found"

    def test_a_project_without_a_session_is_refused(
        self, container: ServiceContainer, person: User
    ) -> None:
        project = container.test_data_service().project(_spec())

        with pytest.raises(InvalidOperationException) as raised:
            container.test_data_service().end_turn(project.id)

        assert raised.value.message == (
            f"Cannot end a turn of project {project.id} because the project has no "
            "session: make it with an environment_id"
        )


@pytest.mark.parametrize("role", list(DocumentRole))
class TestSaveProjectDocument:
    def _document(
        self, session: DbSession, project: Project, role: DocumentRole
    ) -> Document:
        return session.scalars(
            select(Document).where(
                Document.project_id == project.id, Document.role_code == role
            )
        ).one()

    def test_a_clean_save_is_published_by_the_session(
        self,
        container: ServiceContainer,
        session: DbSession,
        camp: Project,
        role: DocumentRole,
    ) -> None:
        ingested = container.test_data_service().save_project_document(
            camp.id, role, "# Camp\n\nTwo tents.\n"
        )

        assert (ingested.held, ingested.faults, ingested.stale) == (False, (), False)
        document = self._document(session, camp, role)
        assert document.published_text == "# Camp\n\nTwo tents.\n"
        assert document.writing_session_id == _session_of(session, camp).id

    def test_a_save_with_a_fault_is_held(
        self,
        container: ServiceContainer,
        session: DbSession,
        camp: Project,
        role: DocumentRole,
    ) -> None:
        document = self._document(session, camp, role)
        published = document.published_text

        ingested = container.test_data_service().save_project_document(
            camp.id, role, "# Camp\n\n```decision id=D1\nnope: 1\n```\n"
        )

        assert ingested.held
        assert container.tree_service().held(camp, document)
        assert document.published_text == published

    def test_an_unknown_project_is_not_found(
        self, container: ServiceContainer, role: DocumentRole
    ) -> None:
        project_id = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as raised:
            container.test_data_service().save_project_document(
                project_id, role, "# Camp\n"
            )

        assert raised.value.message == f"Project {project_id} was not found"

    def test_an_archived_projects_document_is_not_found(
        self,
        container: ServiceContainer,
        person: User,
        environment: Environment,
        role: DocumentRole,
    ) -> None:
        project = container.test_data_service().project(
            _spec(archived=True, environment_id=environment.id)
        )

        with pytest.raises(RecordNotFoundException):
            container.test_data_service().save_project_document(
                project.id, role, "# Camp\n"
            )

    def test_a_project_without_a_session_is_refused(
        self, container: ServiceContainer, person: User, role: DocumentRole
    ) -> None:
        project = container.test_data_service().project(_spec())

        with pytest.raises(InvalidOperationException) as raised:
            container.test_data_service().save_project_document(
                project.id, role, "# Camp\n"
            )

        assert raised.value.message == (
            f"Cannot save the {role.value} of project {project.id} because the "
            "project has no session: make it with an environment_id"
        )


def test_a_drafts_handbook_is_not_found(
    container: ServiceContainer, person: User, environment: Environment
) -> None:
    project = container.test_data_service().project(
        _spec(state="draft", environment_id=environment.id)
    )

    with pytest.raises(RecordNotFoundException) as raised:
        container.test_data_service().save_project_document(
            project.id, DocumentRole.HANDBOOK, "# Camp\n"
        )

    assert raised.value.message == f"Handbook of project {project.id} was not found"


SETTLED_WHOLE = """```decision id=D1
proposal: Cook on the fire.
answer: Agree
by: agent
at: 2026-10-20T09:00:00Z
```

```question id=Q1
default: Two nights
answer: deferred
by: agent
at: 2026-10-20T09:01:00Z
to: plan
```
"""


class TestMarkDone:
    def test_pilot_marks_a_document_it_settled_whole_done(
        self, container: ServiceContainer, session: DbSession, camp: Project
    ) -> None:
        service = container.test_data_service()
        item = service.item(camp.id, "document", "Camp plan", SETTLED_WHOLE)

        service.mark_done(item.id)

        assert (item.done_cause_code, item.done_by_user_id) == (
            "settled",
            _user(session, "agent").id,
        )
        assert session.scalars(
            select(DocumentVersion.cause_code)
            .where(DocumentVersion.document_id == item.id)
            .order_by(DocumentVersion.number)
        ).all() == [VersionCause.BORN, VersionCause.DONE]

    def test_a_document_with_a_block_unanswered_is_refused(
        self, container: ServiceContainer, camp: Project
    ) -> None:
        service = container.test_data_service()
        item = service.item(
            camp.id,
            "document",
            "Camp plan",
            SETTLED_WHOLE.replace("answer: Agree\nby: agent\n", "").replace(
                "at: 2026-10-20T09:00:00Z\n", ""
            ),
        )

        with pytest.raises(InvalidOperationException) as raised:
            service.mark_done(item.id)

        assert raised.value.cause == (
            "Pilot marks done only a document it settled whole, and these blocks "
            "are unanswered: D1"
        )
        assert item.done_at is None

    def test_an_unknown_item_is_not_found(self, container: ServiceContainer) -> None:
        item_id = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as raised:
            container.test_data_service().mark_done(item_id)

        assert raised.value.message == f"Item {item_id} was not found"

    def test_a_project_without_a_session_is_refused(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        project = container.test_data_service().project(_spec())
        [opening] = _items(session, project)

        with pytest.raises(InvalidOperationException) as raised:
            container.test_data_service().mark_done(opening.id)

        assert raised.value.message == (
            f"Cannot mark item {opening.id} done because the project has no "
            "session: make it with an environment_id"
        )


def _file(filename: str, content: bytes, content_type: str = "text/markdown") -> Any:
    return InventedFileSchema.model_validate(
        {
            "title": "Sketch",
            "filename": filename,
            "content_type": content_type,
            "content": base64.b64encode(content).decode(),
        }
    )


def _hung(session: DbSession, item: Item) -> list[tuple[int, int, str]]:
    """The item's attachments in order: position, batch and filename."""
    return [
        (position, batch, filename)
        for position, batch, filename in session.execute(
            select(ItemAttachment.position, Attachment.batch, Attachment.filename)
            .join(Attachment, Attachment.id == ItemAttachment.attachment_id)
            .where(ItemAttachment.item_id == item.id)
            .order_by(ItemAttachment.position)
        )
    ]


class TestAttach:
    @pytest.fixture
    def notice(self, container: ServiceContainer, camp: Project) -> Item:
        return container.test_data_service().item(
            camp.id, "notice", "Palette", "Blue and green.\n"
        )

    def test_the_projects_session_copies_them_through_the_store(
        self,
        container: ServiceContainer,
        session: DbSession,
        camp: Project,
        notice: Item,
        environment: Environment,
    ) -> None:
        [attachment] = container.test_data_service().attach(
            notice.id, [_file("sketch.png", b"\x89PNG", "image/png")]
        )

        project_session = _session_of(session, camp)
        assert (
            attachment.title,
            attachment.filename,
            attachment.content_type,
            attachment.size,
            attachment.sha256,
            attachment.source_code,
            attachment.source_environment_id,
            attachment.source_path,
            attachment.created_by_session_id,
        ) == (
            "Sketch",
            "sketch.png",
            "image/png",
            4,
            hashlib.sha256(b"\x89PNG").hexdigest(),
            AttachmentSource.FILE,
            environment.id,
            f"{project_session.cwd}/sketch.png",
            project_session.id,
        )
        assert container.attachment_store().get(attachment) == b"\x89PNG"

    def test_one_call_is_one_batch_the_projects_next_after_the_items_own(
        self,
        container: ServiceContainer,
        session: DbSession,
        camp: Project,
        notice: Item,
    ) -> None:
        service = container.test_data_service()
        other = service.item(camp.id, "notice", "Tents", "Dome.\n")

        service.attach(notice.id, [_file("a.md", b"A"), _file("b.md", b"B")])
        service.attach(notice.id, [_file("a.md", b"C")])
        service.attach(other.id, [_file("c.md", b"D")])

        assert _hung(session, notice) == [
            (1, 1, "a.md"),
            (2, 1, "b.md"),
            (3, 2, "a.md"),
        ]
        assert _hung(session, other) == [(1, 3, "c.md")]

    def test_the_stores_tree_holds_them_and_the_timeline_lists_them(
        self, container: ServiceContainer, camp: Project, notice: Item
    ) -> None:
        [attachment] = container.test_data_service().attach(
            notice.id, [_file("sketch.md", b"# Sketch\n")]
        )

        path = f"{camp.slug}/attachments/1/sketch.md"
        assert container.tree_service().read(path) == TreeFile(
            b"# Sketch\n", hashlib.sha256(b"# Sketch\n").hexdigest()
        )
        timeline = json.loads(container.view_service().timeline(camp).text)
        [item] = [entry for entry in timeline["items"] if entry["title"] == "Palette"]
        assert item["attachments"] == [
            {"id": str(attachment.id), "path": "attachments/1/sketch.md"}
        ]

    def test_their_paths_and_the_timeline_move_after_the_commit(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        person: User,
        environment: Environment,
    ) -> None:
        with scoped_session(container):
            service = container.test_data_service()
            project = service.project(_spec(name="Camp", environment_id=environment.id))
            notice = service.item(project.id, "notice", "Palette", "Blue.\n")
            attachments = service.attach(
                notice.id, [_file("a.md", b"A"), _file("b.md", b"B")]
            )
            moved = [
                TreeHashMoved(
                    f"{project.slug}/attachments/1/{attachment.filename}",
                    attachment.sha256,
                )
                for attachment in attachments
            ] + [
                TreeHashMoved(
                    f"{project.slug}/timeline.json",
                    container.view_service().timeline(project).hash,
                ),
                ProjectChanged(project.id),
            ]
            assert engine_events == []

        assert [event for event in moved if event not in engine_events] == []

    def test_an_unknown_item_is_not_found(self, container: ServiceContainer) -> None:
        item_id = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as raised:
            container.test_data_service().attach(item_id, [_file("a.md", b"A")])

        assert raised.value.message == f"Item {item_id} was not found"

    def test_a_project_without_a_session_is_refused(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        project = container.test_data_service().project(_spec())
        [opening] = _items(session, project)

        with pytest.raises(InvalidOperationException) as raised:
            container.test_data_service().attach(opening.id, [_file("a.md", b"A")])

        assert raised.value.message == (
            f"Cannot attach files to item {opening.id} because the project has no "
            "session: make it with an environment_id"
        )
        assert session.scalars(select(Attachment)).all() == []

    def test_a_file_over_16_mib_is_refused_and_none_kept(
        self, container: ServiceContainer, session: DbSession, notice: Item
    ) -> None:
        over = 16 * 1024 * 1024 + 1

        with pytest.raises(ValidationException) as raised:
            container.test_data_service().attach(
                notice.id, [_file("a.md", b"A"), _file("big.bin", bytes(over))]
            )

        assert raised.value.message == (
            f"big.bin is {over} bytes, over the 16777216-byte cap"
        )
        assert session.scalars(select(Attachment)).all() == []


REGISTERED = "/work/Camp/docs/refinement.md"


class TestRegisterDocument:
    @pytest.fixture
    def work_item(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> models.Session:
        """A work item's Session running in an environment the fake holds,
        where its worker wrote the document's file."""
        fake_controller.add_environment(environment.id, status="running")
        fake_controller.put_file(environment.id, REGISTERED, b"# Two sites\n")
        run = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Camp",
            token_hash="2" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(run)
        session.flush()
        container.record_service().place_work(
            project, run, "Building the camp", repo="example/Camp"
        )
        return run

    def test_the_work_items_session_registers_it_as_its_worker_does(
        self,
        session: DbSession,
        container: ServiceContainer,
        work_item: models.Session,
    ) -> None:
        service = container.test_data_service()

        registration = service.register_document(work_item.id, REGISTERED, None)

        assert registration.minted
        item = registration.item
        assert (item.kind_code, item.created_by_session_id) == ("review", work_item.id)
        document = session.get_one(Document, item.id)
        assert (document.source_environment_id, document.source_path) == (
            work_item.environment_id,
            REGISTERED,
        )
        again = service.register_document(work_item.id, REGISTERED, None)
        assert (again.item.id, again.minted) == (item.id, False)

    def test_an_item_that_is_no_work_item_is_not_found(
        self, container: ServiceContainer, item: Item
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            container.test_data_service().register_document(item.id, REGISTERED, None)

    def test_a_work_item_with_no_environment_yet_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        work_item: models.Session,
    ) -> None:
        work_item.environment_id = None
        session.flush()

        with pytest.raises(InvalidOperationException) as raised:
            container.test_data_service().register_document(
                work_item.id, REGISTERED, None
            )

        assert raised.value.cause == f"work item {work_item.id} has no environment yet"

    def test_a_file_that_cannot_be_registered_is_refused(
        self, container: ServiceContainer, work_item: models.Session
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            container.test_data_service().register_document(
                work_item.id, "/work/Camp/missing.md", None
            )

        assert raised.value.cause.startswith("the controller answered 404")

    def test_a_tool_use_id_names_the_effect_in_the_turn_in_flight(
        self,
        session: DbSession,
        container: ServiceContainer,
        work_item: models.Session,
    ) -> None:
        session.add(
            Turn(
                session_id=work_item.id,
                seq=1,
                message="Build the camp.",
                started_at=datetime.now(UTC),
            )
        )
        session.flush()

        container.test_data_service().register_document(
            work_item.id, REGISTERED, "toolu_01"
        )

        [record] = read_records(session, work_item.id, limit=10)
        assert record.record.payload["toolUseId"] == "toolu_01"


SURVEY = "/work/Camp/docs/survey.md"


class TestAttachAsWorker:
    @pytest.fixture
    def work_item(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> models.Session:
        """A work item's Session running in an environment the fake holds,
        its brief in flight, where its worker wrote a file."""
        fake_controller.add_environment(environment.id, status="running")
        fake_controller.put_file(environment.id, SURVEY, b"# Sites\n")
        run = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Camp",
            token_hash="2" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(run)
        session.flush()
        container.record_service().place_work(
            project, run, "Building the camp", repo="example/Camp"
        )
        session.add(
            Turn(
                session_id=run.id,
                seq=1,
                message="Build the camp.",
                started_at=datetime.now(UTC),
            )
        )
        session.flush()
        return run

    def test_the_file_is_attached_as_the_worker_attaches_it_with_its_effect(
        self,
        session: DbSession,
        container: ServiceContainer,
        work_item: models.Session,
    ) -> None:
        [attachment] = container.test_data_service().attach_as_worker(
            work_item.id, SURVEY, None, "toolu_01"
        )

        assert (attachment.source_path, attachment.title) == (SURVEY, "Sites")
        assert session.scalars(
            select(ItemAttachment.item_id).where(
                ItemAttachment.attachment_id == attachment.id
            )
        ).all() == [work_item.id]
        [record] = read_records(session, work_item.id, limit=10)
        assert record.record.payload == {
            "type": "effect",
            "toolUseId": "toolu_01",
            "effect": {
                "verb": "Attached",
                "label": "Sites",
                "itemId": str(work_item.id),
            },
        }

    def test_an_item_that_is_no_work_item_is_not_found(
        self, container: ServiceContainer, item: Item
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            container.test_data_service().attach_as_worker(item.id, SURVEY, None, None)

    def test_a_work_item_with_no_environment_yet_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        work_item: models.Session,
    ) -> None:
        work_item.environment_id = None
        session.flush()

        with pytest.raises(InvalidOperationException) as raised:
            container.test_data_service().attach_as_worker(
                work_item.id, SURVEY, None, None
            )

        assert raised.value.cause == f"work item {work_item.id} has no environment yet"


QUESTIONED = "```question id=Q1\n```\n\n```question id=Q2\n```\n"


class TestAskWriter:
    @pytest.fixture
    def document(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> Item:
        """A document a worker registered, read at its run's end."""
        run = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Camp",
            token_hash="2" * 64,
            state_code=SessionState.IDLE,
        )
        session.add(run)
        session.flush()
        documents = container.document_service()
        item = documents.register(project, run, REGISTERED).item
        documents.publish_read(session.get_one(Document, item.id), QUESTIONED, run.id)
        return item

    def test_the_questions_are_asked_in_one_ended_turn_of_a_job_placed_for_them(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        document: Item,
    ) -> None:
        asked = container.test_data_service().ask_writer(
            document.id,
            [
                InventedWriterQuestionSchema(block="Q2", question="Which lake?"),
                InventedWriterQuestionSchema(block="Q1", question="Which site?"),
            ],
        )

        assert asked == ["Q1", "Q2"]
        [job] = session.scalars(
            select(models.Session).where(models.Session.kind_code == "job")
        )
        assert (job.project_id, job.state_code, job.environment_id) == (
            project.id,
            SessionState.IDLE,
            None,
        )
        [turn] = session.scalars(select(Turn).where(Turn.session_id == job.id))
        assert (turn.author_user_id, turn.ended_at) == (None, turn.started_at)
        assert [
            (question.turn_id, question.question)
            for question in session.scalars(
                select(WriterQuestion).order_by(WriterQuestion.id)
            )
        ] == [(turn.id, "Which lake?"), (turn.id, "Which site?")]

    def test_an_unknown_item_is_not_found(self, container: ServiceContainer) -> None:
        with pytest.raises(RecordNotFoundException):
            container.test_data_service().ask_writer(
                uuid.uuid4(),
                [InventedWriterQuestionSchema(block="Q1", question="Which?")],
            )

    def test_a_block_the_pass_may_not_ask_about_is_refused(
        self,
        container: ServiceContainer,
        person: User,
        document: Item,
    ) -> None:
        container.record_service().answer(
            container.db_session().get_one(Document, document.id), "Q1", person, "Here"
        )

        with pytest.raises(InvalidOperationException) as raised:
            container.test_data_service().ask_writer(
                document.id,
                [InventedWriterQuestionSchema(block="Q1", question="Which?")],
            )

        assert raised.value.cause == "block Q1 is answered"


class TestAnswerInChat:
    def _chat(
        self, container: ServiceContainer, camp: Project, person: User
    ) -> tuple[models.Session, ChatWriter]:
        """The project's chat open, a message of `person`'s in flight."""
        session = container.db_session()
        chat = open_chat(session, camp)
        writer = ChatWriter(session, container.session_record_service(), chat)
        writer.message(person, "The dome.")
        chat.state_code = SessionState.RUNNING
        session.flush()
        return chat, writer

    def test_the_answer_is_recorded_through_the_chat_its_effect_in_the_turn_in_flight(
        self,
        container: ServiceContainer,
        session: DbSession,
        camp: Project,
        person: User,
    ) -> None:
        item = container.test_data_service().item(
            camp.id, "decision", "Which tent?", DECISION_TEXT
        )
        chat, writer = self._chat(container, camp, person)

        line = container.test_data_service().answer_in_chat(
            camp.id,
            f"{item.id}/D1",
            "Dome",
            "ada",
            note="It stands up in five minutes.",
            to=None,
            tool_use_id="toolu_01",
        )

        assert (line.verb, line.label, line.block_id) == (
            "Answered",
            "D1 · Which tent?",
            f"{item.id}/D1",
        )
        block = _block(session, item, "D1")
        assert block.via_code == AnswerChannel.CHAT
        [effect] = session.scalars(select(Effect).where(Effect.block_id == block.id))
        assert writer.turn is not None
        assert effect.turn_id == writer.turn.id
        [record] = [
            stored.record
            for stored in read_records(session, chat.id, limit=10)
            if stored.record.kind_code == "server"
        ]
        assert (effect.record_id, record.payload["toolUseId"]) == (
            record.id,
            "toolu_01",
        )

    def test_an_unknown_project_is_not_found(self, container: ServiceContainer) -> None:
        with pytest.raises(RecordNotFoundException):
            container.test_data_service().answer_in_chat(
                uuid.uuid4(),
                "x/D1",
                "Dome",
                "ada",
                note=None,
                to=None,
                tool_use_id=None,
            )

    def test_a_project_with_no_chat_open_is_refused(
        self, container: ServiceContainer, camp: Project
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            container.test_data_service().answer_in_chat(
                camp.id, "x/D1", "Dome", "ada", note=None, to=None, tool_use_id=None
            )

        assert raised.value.cause == "the project has no chat open"

    def test_a_chat_with_no_turn_in_flight_is_refused(
        self, container: ServiceContainer, camp: Project, person: User
    ) -> None:
        chat, _ = self._chat(container, camp, person)
        chat.state_code = SessionState.IDLE

        with pytest.raises(InvalidOperationException) as raised:
            container.test_data_service().answer_in_chat(
                camp.id, "x/D1", "Dome", "ada", note=None, to=None, tool_use_id=None
            )

        assert raised.value.cause == "its chat has no turn in flight"
