"""The standing notification each member of a project should see (F94.1,
F94.2, F94.5; DB 224 to 226)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Environment, Item, Project, ProjectMember, User, Work
from app.models.reference import NotificationPriority, SessionState
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.container import ServiceContainer
from app.services.standing_notification_service import StandingNotification

DECISION = """```decision id=D1
options:
  - Dome
  - Tunnel
```
"""

QUESTION = "```question id=Q1\n```\n"

CLAIM = "answer: Pilot does it\nby: agent\nat: 2026-10-12T09:30:00Z\n"

CLAIMED_ONLY = f"""```action id=A1
{CLAIM}```

```action id=A2
{CLAIM}```
"""
"""A document whose open blocks are all actions Pilot claimed (DB 262)."""


def _make(container: ServiceContainer, **spec: Any) -> Project:
    spec.setdefault("members", ["ada"])
    spec.setdefault("name", "Camp")
    return container.test_data_service().project(
        InventedProjectCreateSchema.model_validate(spec)
    )


def _ben(container: ServiceContainer) -> User:
    return container.test_data_service().person("ben", "Ben Example")


def _token(container: ServiceContainer, session: DbSession, *people: User) -> None:
    cipher = container.notification_token_cipher()
    for person in people:
        person.notification_token = cipher.seal(f"token-of-{person.handle}")
    session.flush()


def _should_see(
    container: ServiceContainer, session: DbSession, project: Project
) -> dict[str, StandingNotification | None]:
    """What each membership of `project` should see, by its person's handle."""
    memberships = session.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project.id)
    ).all()
    seen = container.standing_notification_service().should_see(project, memberships)
    return {
        session.get_one(User, membership.user_id).handle: seen[membership.id]
        for membership in memberships
    }


def _seen(
    container: ServiceContainer,
    session: DbSession,
    project: Project,
    handle: str = "ada",
) -> StandingNotification:
    notification = _should_see(container, session, project)[handle]
    assert notification is not None
    return notification


def _timeline(container: ServiceContainer, project: Project) -> str:
    return f"{container.config().baseurl}/projects/{project.id}"


def _run(
    session: DbSession,
    project: Project,
    environment: Environment,
    state: SessionState = SessionState.IDLE,
) -> models.Session:
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


def _next_seq(session: DbSession, project: Project) -> int:
    seqs = session.scalars(select(Item.seq).where(Item.project_id == project.id))
    return max(seqs, default=0) + 1


def _work(
    session: DbSession,
    project: Project,
    environment: Environment,
    state: SessionState,
    title: str | None = "Build the camp",
) -> Item:
    """A work item, its Item, its Session and its Work one identity (DB
    decision 3)."""
    run = _run(session, project, environment, state)
    work = Item(
        id=run.id,
        project_id=project.id,
        seq=_next_seq(session, project),
        kind_code="work",
        title=title,
        created_by_session_id=run.id,
    )
    session.add(work)
    session.flush()
    session.add(
        Work(
            id=run.id, project_id=project.id, session_kind_code="work", autopilot=False
        )
    )
    session.flush()
    return work


def _wait(
    session: DbSession, project: Project, environment: Environment, title: str | None
) -> Item:
    run = _run(session, project, environment)
    wait = Item(
        project_id=project.id,
        seq=_next_seq(session, project),
        kind_code="timed_wait",
        title=title,
        created_by_session_id=run.id,
    )
    session.add(wait)
    session.flush()
    return wait


def _bear(
    container: ServiceContainer,
    project: Project,
    run: models.Session,
    kind: str,
    title: str,
    text: str,
    **front_matter: str,
) -> Item:
    """A prose item `run` added, `title` and `front_matter` in its text's."""
    header = "".join(f"{key}: {value}\n" for key, value in front_matter.items())
    return container.document_service().bear_item(
        project, kind, title, run, f"---\ntitle: {title}\n{header}---\n\n{text}"
    )


@pytest.mark.usefixtures("person")
class TestWhoShouldSeeOne:
    def test_a_member_holding_a_token_sees_the_projects_standing(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        project = _make(container)
        _token(container, session, person)

        assert _should_see(container, session, project) == {
            "ada": StandingNotification(
                sequence_id=str(project.id),
                priority=NotificationPriority.MIN,
                title="Camp",
                message="Not started",
                url=_timeline(container, project),
            )
        }

    def test_a_member_without_a_token_sees_none(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        ben = _ben(container)
        project = _make(container, members=["ada", "ben"])
        _token(container, session, ben)

        seen = _should_see(container, session, project)

        assert seen["ada"] is None
        assert seen["ben"] is not None

    def test_an_archived_project_shows_none(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        project = _make(container, archived=True)
        _token(container, session, person)

        assert _should_see(container, session, project) == {"ada": None}

    def test_a_closed_membership_shows_none(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        ben = _ben(container)
        project = _make(container, members=["ada", "ben"])
        _token(container, session, person, ben)
        session.scalars(
            select(ProjectMember).where(ProjectMember.user_id == ben.id)
        ).one().left_at = datetime.now(UTC)
        session.flush()

        seen = _should_see(container, session, project)

        assert seen["ada"] is not None
        assert seen["ben"] is None

    def test_a_draft_holds_one_titled_as_its_tab_until_its_draft_names_it(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        project = _make(container, state="draft", name=None)
        _token(container, session, person)

        seen = _seen(container, session, project)

        assert (seen.title, seen.message) == ("New project", "Draft")

    def test_a_finished_project_holds_one(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        project = _make(container, state="finished")
        _token(container, session, person)

        assert _seen(container, session, project).message == "Finished"

    def test_only_the_memberships_asked_for_are_answered(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        ben = _ben(container)
        project = _make(container, members=["ada", "ben"])
        _token(container, session, person, ben)
        ada = session.scalars(
            select(ProjectMember).where(ProjectMember.user_id == person.id)
        ).one()

        seen = container.standing_notification_service().should_see(project, [ada])

        assert list(seen) == [ada.id]


@pytest.mark.usefixtures("person")
class TestPriority:
    def test_min_while_nothing_waits_on_the_member(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        # A notice, a wait and a running work item wait on no one (F23.2,
        # F27.5).
        project = _make(container)
        _token(container, session, person)
        _bear(
            container,
            project,
            _run(session, project, environment),
            "notice",
            "Opens in May",
            "The site opens in May.\n",
        )
        _wait(session, project, environment, "The site opens")
        _work(session, project, environment, SessionState.RUNNING)

        assert _seen(container, session, project).priority is NotificationPriority.MIN

    def test_default_while_an_item_waits_on_the_member(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        _token(container, session, person)
        _work(session, project, environment, SessionState.STOPPED)

        assert (
            _seen(container, session, project).priority is NotificationPriority.DEFAULT
        )

    def test_high_while_an_urgent_one_does_an_urgent_notice_included(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        _token(container, session, person)
        run = _run(session, project, environment)
        _bear(container, project, run, "decision", "Which tent?", DECISION)
        _bear(
            container,
            project,
            run,
            "notice",
            "Storm",
            "A storm comes.\n",
            urgent="true",
        )

        assert _seen(container, session, project).priority is NotificationPriority.HIGH

    def test_an_item_for_one_member_waits_on_them_alone(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        ben = _ben(container)
        project = _make(container, members=["ada", "ben"])
        _token(container, session, person, ben)
        _bear(
            container,
            project,
            _run(session, project, environment),
            "question",
            "Your boots?",
            QUESTION,
            urgent="true",
            **{"for": "ben"},
        )

        seen = _should_see(container, session, project)

        assert seen["ada"] is not None and seen["ben"] is not None
        assert (seen["ada"].priority, seen["ada"].message) == (
            NotificationPriority.MIN,
            "Not started · 1 waiting on ben",
        )
        assert (seen["ben"].priority, seen["ben"].message) == (
            NotificationPriority.HIGH,
            "Not started · Question waiting: Your boots?",
        )

    def test_a_pause_changes_the_text_and_not_the_priority(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        # F141.6: a paused project with an item waiting still waits on you.
        project = _make(container, paused=True)
        _token(container, session, person)
        _bear(
            container,
            project,
            _run(session, project, environment),
            "decision",
            "Which tent?",
            DECISION,
        )

        seen = _seen(container, session, project)

        assert (seen.priority, seen.message) == (
            NotificationPriority.DEFAULT,
            "Not started · Paused · Decision waiting: Which tent?",
        )

    def test_a_finished_projects_archive_question_waits_on_its_members(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        # F5.6: the nudge to archive.
        project = _make(container, state="finished")
        _token(container, session, person)
        question = container.document_service().bear_archive_question(project)

        assert _seen(container, session, project) == StandingNotification(
            sequence_id=str(project.id),
            priority=NotificationPriority.DEFAULT,
            title="Camp",
            message="Finished · Archive question waiting: Archive the project?",
            url=f"{_timeline(container, project)}/items/{question.id}",
        )

    def test_a_document_whose_open_blocks_are_all_claimed_waits_on_no_one(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        _token(container, session, person)
        run = _run(session, project, environment)
        documents = container.document_service()
        item = documents.register(project, run, "/work/Camp/docs/claimed.md").item
        documents.publish_read(
            session.get_one(models.Document, item.id), CLAIMED_ONLY, run.id
        )

        assert _seen(container, session, project).priority is NotificationPriority.MIN


@pytest.mark.usefixtures("person")
class TestMessage:
    @pytest.mark.parametrize(
        ("statuses", "reading"),
        [
            (["pending", "pending"], "Not started"),
            (["done", "pending"], "1 of 2 done"),
            (["done", "done"], "All steps done"),
            (["done", "in_progress", "pending"], "Pack the stove"),
            (["in_progress", "in_progress"], "Pitch the tent, …"),
        ],
    )
    def test_an_open_projects_status_line_is_its_step_reading(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        statuses: list[str],
        reading: str,
    ) -> None:
        titles = ["Pitch the tent", "Pack the stove", "Light the fire"]
        project = _make(
            container,
            tasks=[
                {"id": f"t{index}", "title": titles[index], "status": status}
                for index, status in enumerate(statuses)
            ],
        )
        _token(container, session, person)

        assert _seen(container, session, project).message == reading

    def test_what_runs(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        _token(container, session, person)
        _work(session, project, environment, SessionState.RUNNING)
        assert (
            _seen(container, session, project).message
            == "Not started · Running: Build the camp"
        )

        _work(session, project, environment, SessionState.RUNNING, "Pack up")
        assert _seen(container, session, project).message == "Not started · 2 running"

    def test_what_waits_on_the_member_and_on_others(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        ben = _ben(container)
        project = _make(container, members=["ada", "ben"])
        _token(container, session, person)
        run = _run(session, project, environment)
        _bear(container, project, run, "decision", "Which tent?", DECISION)
        assert (
            _seen(container, session, project).message
            == "Not started · Decision waiting: Which tent?"
        )

        _bear(container, project, run, "question", "Where?", QUESTION)
        _work(session, project, environment, SessionState.FAILED)
        for title in ("Your boots?", "Your hat?"):
            _bear(
                container, project, run, "question", title, QUESTION, **{"for": "ben"}
            )
        assert ben.handle == "ben"
        assert (
            _seen(container, session, project).message
            == "Not started · 3 waiting · 2 waiting on ben"
        )

    def test_the_open_waits(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        _token(container, session, person)
        _wait(session, project, environment, "The site opens")
        assert (
            _seen(container, session, project).message
            == "Not started · Waiting for: The site opens"
        )

        _wait(session, project, environment, None)
        assert (
            _seen(container, session, project).message == "Not started · 2 waits open"
        )

    def test_untitled_items_read_by_their_kind(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        _token(container, session, person)
        _wait(session, project, environment, None)
        _work(session, project, environment, SessionState.RUNNING, None)
        _work(session, project, environment, SessionState.STOPPED, None)

        assert (
            _seen(container, session, project).message
            == "Not started · Running · Work waiting · Timed wait open"
        )

    def test_the_records_texts_read_as_their_words_in_the_markdown(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        project = _make(
            container,
            name="Camp *2026*",
            tasks=[
                {
                    "id": "ci",
                    "title": "1. Set up `ci` & [deploy]_now_, 2) ship",
                    "status": "in_progress",
                }
            ],
        )
        _token(container, session, person)

        seen = _seen(container, session, project)

        assert seen.title == "Camp *2026*"
        assert seen.message == r"1\. Set up \`ci\` \& \[deploy\]\_now\_, 2\) ship"

    def test_the_fields_stay_within_the_bridges_limits(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        project = _make(
            container,
            name="N" * 300,
            tasks=[{"id": "long", "title": "\\" * 5000, "status": "in_progress"}],
        )
        _token(container, session, person)

        seen = _seen(container, session, project)

        assert seen.title == "N" * 249 + "…"
        # The cut ends on whole escapes, so no backslash escapes the "…".
        assert seen.message == "\\" * 4094 + "…"


@pytest.mark.usefixtures("person")
class TestUrl:
    def test_the_one_item_waiting_on_the_member_else_the_timeline(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        _ben(container)
        project = _make(container, members=["ada", "ben"])
        _token(container, session, person)
        run = _run(session, project, environment)
        _bear(
            container,
            project,
            run,
            "question",
            "Your boots?",
            QUESTION,
            **{"for": "ben"},
        )
        assert _seen(container, session, project).url == _timeline(container, project)

        decision = _bear(container, project, run, "decision", "Which tent?", DECISION)
        assert (
            _seen(container, session, project).url
            == f"{_timeline(container, project)}/items/{decision.id}"
        )

        _bear(container, project, run, "question", "Where?", QUESTION)
        assert _seen(container, session, project).url == _timeline(container, project)
