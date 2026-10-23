"""Project, Project Member and Project Transition: what a row must hold."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Project, ProjectMember, ProjectTransition, User
from app.models.reference import ProjectState, TransitionKind
from tests.support.database import violated_constraint


class TestProject:
    def test_a_new_project_is_a_draft(self, session: Session, project: Project) -> None:
        session.refresh(project)

        assert project.state_code == ProjectState.DRAFT
        assert project.slug is None
        assert project.name is None
        assert project.archived is False
        assert project.autopilot is False
        assert project.paused is False
        assert project.created_at is not None

    def test_the_database_makes_a_new_project_a_draft(
        self, session: Session, person: User
    ) -> None:
        """The revision's server defaults, which the model's own hide."""
        row = session.execute(
            text(
                "INSERT INTO projects (id, created_by_user_id) VALUES (:id, :user)"
                " RETURNING state_code, archived, autopilot, paused"
            ),
            {"id": uuid.uuid4(), "user": person.id},
        ).one()

        assert tuple(row) == ("draft", False, False, False)

    def test_numbers_count_up(self, session: Session, person: User) -> None:
        first = Project(created_by_user_id=person.id)
        second = Project(created_by_user_id=person.id)
        session.add_all([first, second])
        session.flush()

        assert second.number == first.number + 1

    def test_a_draft_has_no_slug(self, session: Session, project: Project) -> None:
        project.slug = "fix-the-client"

        assert violated_constraint(session) == "ck_projects_draft_slug"

    def test_an_opened_project_has_a_slug(
        self, session: Session, project: Project
    ) -> None:
        project.state_code = ProjectState.OPEN

        assert violated_constraint(session) == "ck_projects_draft_slug"

    def test_an_opened_project_keeps_its_slug(
        self, session: Session, project: Project
    ) -> None:
        project.state_code = ProjectState.OPEN
        project.slug = "fix-the-client"
        session.flush()
        project.state_code = ProjectState.FINISHED
        session.flush()

        assert project.slug == "fix-the-client"

    # Each breaks one rule: a capital, then an underscore.
    @pytest.mark.parametrize("slug", ["Fix-the-client", "fix_the_client"])
    def test_a_slug_is_lower_case_letters_digits_and_hyphens(
        self, session: Session, project: Project, slug: str
    ) -> None:
        project.state_code = ProjectState.OPEN
        project.slug = slug

        assert violated_constraint(session) == "ck_projects_slug"

    def test_a_slug_is_never_a_draft_folder(
        self, session: Session, project: Project
    ) -> None:
        project.state_code = ProjectState.OPEN
        project.slug = "draft-3"

        assert violated_constraint(session) == "ck_projects_slug"

    def test_a_slug_is_unique(self, session: Session, person: User) -> None:
        session.add_all(
            Project(
                created_by_user_id=person.id,
                state_code=ProjectState.OPEN,
                slug="fix-the-client",
            )
            for _ in range(2)
        )

        assert violated_constraint(session) == "projects_slug_key"


class TestProjectMember:
    def test_a_user_has_one_open_membership_of_a_project(
        self, session: Session, project: Project, person: User
    ) -> None:
        now = datetime.now(UTC)
        session.add_all(
            ProjectMember(project_id=project.id, user_id=person.id, joined_at=now)
            for _ in range(2)
        )

        assert violated_constraint(session) == "uq_project_members_open"

    def test_a_user_who_left_rejoins_as_a_new_membership(
        self, session: Session, project: Project, person: User
    ) -> None:
        joined = datetime(2026, 10, 1, 9, tzinfo=UTC)
        left = datetime(2026, 10, 1, 17, tzinfo=UTC)
        rejoined = datetime(2026, 10, 3, 9, tzinfo=UTC)
        session.add_all(
            [
                ProjectMember(
                    project_id=project.id,
                    user_id=person.id,
                    joined_at=joined,
                    left_at=left,
                ),
                ProjectMember(
                    project_id=project.id, user_id=person.id, joined_at=rejoined
                ),
            ]
        )
        session.flush()

        memberships = session.scalars(
            select(ProjectMember.left_at).where(ProjectMember.user_id == person.id)
        ).all()
        assert sorted(memberships, key=lambda left_at: left_at is None) == [left, None]


class TestProjectTransition:
    def test_a_transition_is_written(
        self, session: Session, project: Project, person: User
    ) -> None:
        transition = ProjectTransition(
            project_id=project.id,
            kind_code=TransitionKind.AUTOPILOT_ON,
            at=datetime.now(UTC),
            by_user_id=person.id,
        )
        session.add(transition)
        session.flush()

        assert transition.id is not None

    def test_a_pause_and_a_resume_are_transitions(
        self, session: Session, project: Project, person: User
    ) -> None:
        paused_at = datetime(2026, 10, 23, 9, tzinfo=UTC)
        resumed_at = datetime(2026, 10, 23, 10, tzinfo=UTC)
        session.add_all(
            ProjectTransition(
                project_id=project.id, kind_code=kind, at=at, by_user_id=person.id
            )
            for kind, at in (
                (TransitionKind.PAUSED, paused_at),
                (TransitionKind.RESUMED, resumed_at),
            )
        )
        session.flush()

        kinds = session.scalars(
            select(ProjectTransition.kind_code)
            .where(ProjectTransition.project_id == project.id)
            .order_by(ProjectTransition.at)
        ).all()
        assert kinds == [TransitionKind.PAUSED, TransitionKind.RESUMED]
