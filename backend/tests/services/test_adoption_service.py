"""The adopted Project of a group: made the first time the group is named,
by the stage's service user, found again by the group's key, renamed with
its group, and made once however many name the group at once (F152.8)."""

import uuid
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.database import scoped_session
from app.engine.bus import EngineEvent, ManifestChanged, ProjectChanged
from app.exceptions import NoServiceUserException
from app.models import (
    Document,
    DocumentVersion,
    Project,
    ProjectMember,
    ProjectTransition,
    User,
)
from app.models.reference import (
    DocumentRole,
    ProjectState,
    TransitionKind,
    UserKind,
    VersionCause,
)
from app.services.adoption_service import (
    ADOPTION_LOCK,
    AdoptionService,
    draft_text,
    group_faults,
)
from app.services.container import ServiceContainer
from tests.support.adoption import FIRST_MENUS
from tests.support.database import writes
from tests.support.locks import in_thread, lock_waits, turn_holders
from tests.support.supervisor import wait_until

NAME = "Recipe box: the first menus"
SUMMARY = "The menus Ada wrote by hand.\n\nThey came before the recipe box."
TEXT = (
    "---\n"
    "title: 'Recipe box: the first menus'\n"
    "---\n"
    "\n"
    "The menus Ada wrote by hand.\n"
    "\n"
    "They came before the recipe box.\n"
)


@pytest.fixture
def adoption(container: ServiceContainer) -> AdoptionService:
    return container.adoption_service()


def _draft(db: DbSession, project_id: uuid.UUID) -> Document:
    return db.scalars(select(Document).where(Document.project_id == project_id)).one()


def _count(db: DbSession, entity: type[Any]) -> int:
    return db.scalar(select(func.count()).select_from(entity)) or 0


class TestDraftText:
    def test_the_name_is_its_title_and_the_summary_its_body(self) -> None:
        assert draft_text(NAME, SUMMARY) == TEXT

    @pytest.mark.parametrize("summary", ["", "  \n"])
    def test_a_group_with_no_summary_has_its_title_alone(self, summary: str) -> None:
        assert draft_text("The first menus", summary) == (
            "---\ntitle: The first menus\n---\n"
        )

    def test_the_space_around_a_summary_is_not_its_text(self) -> None:
        assert draft_text(NAME, f"\n{SUMMARY}\n\n") == TEXT


class TestGroupFaults:
    @pytest.mark.parametrize(
        "summary",
        ["", SUMMARY, "---\ntitle: Another\n---", "```\nrecipes/menus.md\n```"],
        ids=["none", "prose", "a front matter of its own", "a fence that is no ask"],
    )
    def test_a_name_and_a_summary_that_read_back_have_none(self, summary: str) -> None:
        assert group_faults(NAME, summary) == []

    @pytest.mark.parametrize(
        "name",
        [" The first menus", "The first menus ", " ", "The first\nmenus"],
        ids=["space before", "space after", "blank", "two lines"],
    )
    def test_a_name_that_is_no_one_line_of_words_is_one(self, name: str) -> None:
        assert group_faults(name, SUMMARY) == [
            "the group's `name` is not one line of words with no space around them"
        ]

    def test_a_summary_with_an_ask_is_one(self) -> None:
        ask = "```question id=Q1\ndefault: Stew\n```\n\nWhich menu came first?"

        assert group_faults(NAME, ask) == ["the group's `summary` holds an ask"]

    def test_a_summary_that_does_not_parse_is_named_with_its_fault(self) -> None:
        found = group_faults(NAME, "```decision id=D1\nnope\n```")

        assert found == [
            "the group's `summary` holds an ask",
            "the group's `summary` does not read as a document's text: line 6: block"
            " D1: the body is not a YAML mapping",
        ]


class TestBorn:
    def test_a_group_no_project_holds_gets_its_adopted_project(
        self, session: DbSession, adoption: AdoptionService, service_user: User
    ) -> None:
        project = session.get_one(Project, adoption.adopt(FIRST_MENUS, NAME, SUMMARY))

        assert (project.state_code, project.archived) == (ProjectState.ADOPTED, True)
        assert project.adopted_group == FIRST_MENUS
        assert (project.slug, project.name) == (None, NAME)
        assert (project.autopilot, project.paused) == (False, False)
        assert project.created_by_user_id == service_user.id

    def test_it_is_born_by_one_adopted_transition_of_the_service_users(
        self, session: DbSession, adoption: AdoptionService, service_user: User
    ) -> None:
        """DB 170, 584."""
        project = session.get_one(Project, adoption.adopt(FIRST_MENUS, NAME, SUMMARY))

        (born,) = session.scalars(
            select(ProjectTransition).where(ProjectTransition.project_id == project.id)
        ).all()
        assert (born.kind_code, born.by_user_id, born.at) == (
            TransitionKind.ADOPTED,
            service_user.id,
            project.created_at,
        )

    def test_it_has_no_member(
        self, session: DbSession, adoption: AdoptionService, service_user: User
    ) -> None:
        """DB 584: not the people who join the projects a call starts."""
        joiner = User(
            kind_code=UserKind.PERSON,
            subject="subject-ben",
            handle="ben",
            name="Ben Example",
            avatar_slot=2,
            join_calls=True,
        )
        session.add(joiner)
        session.flush()

        adoption.adopt(FIRST_MENUS, NAME, SUMMARY)

        assert _count(session, ProjectMember) == 0

    def test_its_one_document_is_its_draft_with_the_name_and_the_summary(
        self, session: DbSession, adoption: AdoptionService, service_user: User
    ) -> None:
        """DB 150."""
        draft = _draft(session, adoption.adopt(FIRST_MENUS, NAME, SUMMARY))

        assert (draft.role_code, draft.path) == (DocumentRole.DRAFT, "project.md")
        assert draft.published_text == TEXT
        (version,) = session.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == draft.id)
        ).all()
        assert (version.number, version.cause_code, version.text) == (
            1,
            VersionCause.BORN,
            TEXT,
        )

    def test_the_project_list_is_told_and_the_stores_tree_is_not(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        service_user: User,
    ) -> None:
        with scoped_session(container):
            project_id = container.adoption_service().adopt(FIRST_MENUS, NAME, SUMMARY)

        assert ProjectChanged(project_id) in engine_events
        assert ManifestChanged() not in engine_events

    def test_it_is_born_by_the_first_service_user_the_stage_made(
        self, session: DbSession, adoption: AdoptionService, service_user: User
    ) -> None:
        later = User(
            kind_code=UserKind.SERVICE,
            subject="subject-another-fleet",
            handle="another-fleet",
            name="Another fleet",
            created_at=service_user.created_at.replace(year=2027),
        )
        earlier = User(
            kind_code=UserKind.SERVICE,
            subject="subject-first-fleet",
            handle="first-fleet",
            name="The first fleet",
            created_at=service_user.created_at.replace(year=2025),
        )
        session.add_all([later, earlier])
        session.flush()

        project = session.get_one(Project, adoption.adopt(FIRST_MENUS, NAME, SUMMARY))

        assert project.created_by_user_id == earlier.id

    def test_a_stage_with_no_service_user_is_refused_and_nothing_is_written(
        self, session: DbSession, adoption: AdoptionService, person: User
    ) -> None:
        with writes(session) as wrote, pytest.raises(NoServiceUserException) as raised:
            adoption.adopt(FIRST_MENUS, NAME, SUMMARY)

        assert raised.value.message == (
            "Cannot make the adopted project of the group 'recipe-box-first-menus'"
            " because the stage has no service user to make it"
        )
        assert raised.value.error_code == "NO_SERVICE_USER"
        assert wrote == {}


class TestFoundAgain:
    def test_a_group_named_again_is_its_project_and_nothing_is_written(
        self, session: DbSession, adoption: AdoptionService, service_user: User
    ) -> None:
        project_id = adoption.adopt(FIRST_MENUS, NAME, SUMMARY)

        with writes(session) as wrote:
            again = adoption.adopt(FIRST_MENUS, NAME, SUMMARY)

        assert again == project_id
        assert wrote == {}

    def test_another_group_gets_a_project_of_its_own(
        self, session: DbSession, adoption: AdoptionService, service_user: User
    ) -> None:
        first = adoption.adopt(FIRST_MENUS, NAME, SUMMARY)

        second = adoption.adopt("bike-log-first-rides", NAME, SUMMARY)

        assert second != first
        assert sorted(session.scalars(select(Project.adopted_group))) == [
            "bike-log-first-rides",
            FIRST_MENUS,
        ]

    def test_a_renamed_group_renames_its_project(
        self, session: DbSession, adoption: AdoptionService, service_user: User
    ) -> None:
        project_id = adoption.adopt(FIRST_MENUS, NAME, SUMMARY)

        again = adoption.adopt(FIRST_MENUS, "The first menus", SUMMARY)

        assert again == project_id
        assert _count(session, Project) == 1
        assert session.get_one(Project, project_id).name == "The first menus"
        assert _draft(session, project_id).published_text == draft_text(
            "The first menus", SUMMARY
        )

    def test_a_changed_summary_is_its_projects_text_and_its_name_stays(
        self, session: DbSession, adoption: AdoptionService, service_user: User
    ) -> None:
        project_id = adoption.adopt(FIRST_MENUS, NAME, SUMMARY)

        adoption.adopt(FIRST_MENUS, NAME, "The menus, as Ben now tells it.")

        assert session.get_one(Project, project_id).name == NAME
        assert _draft(session, project_id).published_text == draft_text(
            NAME, "The menus, as Ben now tells it."
        )

    def test_a_rename_keeps_the_project_as_it_was_born(
        self, session: DbSession, adoption: AdoptionService, service_user: User
    ) -> None:
        """Nothing follows its one transition (DB 170), and its one document
        keeps its one version, the text it was born with."""
        project_id = adoption.adopt(FIRST_MENUS, NAME, SUMMARY)

        adoption.adopt(FIRST_MENUS, "The first menus", SUMMARY)

        assert _count(session, ProjectTransition) == 1
        assert _count(session, Document) == 1
        assert session.scalars(select(DocumentVersion.text)).all() == [TEXT]
        project = session.get_one(Project, project_id)
        assert (project.state_code, project.archived) == (ProjectState.ADOPTED, True)

    def test_a_rename_is_told_to_the_project_list(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        service_user: User,
    ) -> None:
        with scoped_session(container):
            project_id = container.adoption_service().adopt(FIRST_MENUS, NAME, SUMMARY)
        engine_events.clear()

        with scoped_session(container):
            container.adoption_service().adopt(FIRST_MENUS, "The first menus", SUMMARY)

        assert ProjectChanged(project_id) in engine_events

    def test_a_group_found_again_needs_no_service_user(
        self, session: DbSession, adoption: AdoptionService, service_user: User
    ) -> None:
        project_id = adoption.adopt(FIRST_MENUS, NAME, SUMMARY)
        service_user.kind_code = UserKind.PERSON
        service_user.avatar_slot = 3
        session.flush()

        assert adoption.adopt(FIRST_MENUS, "The first menus", SUMMARY) == project_id


class TestTurns:
    """Two that first name one group at once make one Project: the second
    waits for the first, and finds what it committed."""

    def test_a_group_first_named_twice_at_once_is_one_project(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        with scoped_session(container) as db:
            db.add(
                User(
                    kind_code=UserKind.SERVICE,
                    subject="subject-fleet",
                    handle="fleet",
                    name="KubeCoder fleet",
                )
            )

        def adopted_second() -> uuid.UUID:
            with scoped_session(container):
                return container.adoption_service().adopt(
                    FIRST_MENUS, "The first menus", SUMMARY
                )

        with scoped_session(container):
            first = container.adoption_service().adopt(FIRST_MENUS, NAME, SUMMARY)
            assert len(turn_holders(container, ADOPTION_LOCK)) == 1
            second = in_thread(adopted_second)
            wait_until(lambda: lock_waits(container) == 1, "the second's turn waiting")

        assert second.result() == first
        with scoped_session(container) as db:
            assert db.execute(select(Project.id, Project.name)).all() == [
                (first, "The first menus")
            ]
            assert _count(db, ProjectTransition) == 1
