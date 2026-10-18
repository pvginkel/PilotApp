"""The dev stack's seed: an invented record, written through the engine's own
operations where the engine writes it (slice 002 P9)."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.app import App
from app.engine import dsl
from app.engine.tree import TreeDocument, TreePlan
from app.exceptions import InvalidOperationException
from app.models import (
    Attachment,
    Block,
    Document,
    DocumentVersion,
    Environment,
    Item,
    ItemAttachment,
    ItemKind,
    PlanTask,
    Project,
    ProjectMember,
    ProjectTransition,
    User,
)
from app.models.reference import (
    AnswerChannel,
    AttachmentSource,
    DocumentRole,
    ProjectState,
    TaskStatus,
    TransitionKind,
    UserKind,
    VersionCause,
)
from app.services import test_data_service
from app.services.container import ServiceContainer
from app.startup import load_test_data_hook


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


def _plan(container: ServiceContainer, project: Project) -> dict[str, Any]:
    plan: dict[str, Any] = json.loads(container.plan_service().render(project).text)
    return plan


class TestTestDataService:
    def test_load_all_counts_the_rows_it_seeded(self, counts: dict[str, int]) -> None:
        assert counts == {
            "users": 2,
            "projects": 2,
            "items": 9,
            "documents": 12,
            "blocks": 13,
            "plan tasks": 6,
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
        assert attachment.size == len(attachment.content)
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
        for project in session.scalars(select(Project)):
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

        assert len(saved) == 14

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
