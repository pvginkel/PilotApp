"""The notification each member of a project should see (F94.1, F94.2,
F94.5; DB 224 to 226; D145): the asks that wait on them alone, plain."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Environment, Item, Project, ProjectMember, User, Work
from app.models.reference import SessionState
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.container import ServiceContainer
from app.services.standing_notification_service import StandingNotification
from app.services.web_push import Push

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


def _decision(
    container: ServiceContainer,
    session: DbSession,
    project: Project,
    environment: Environment,
    title: str = "Which tent?",
) -> Item:
    """A decision the project's session adds, which waits on its members."""
    return _bear(
        container,
        project,
        _run(session, project, environment),
        "decision",
        title,
        DECISION,
    )


@pytest.mark.usefixtures("person")
class TestWhoShouldSeeOne:
    def test_a_member_sees_what_waits_on_them(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        tent = _decision(container, session, project, environment)

        assert _should_see(container, session, project) == {
            "ada": StandingNotification(
                tag=str(project.id),
                title="Camp",
                body="Which tent?",
                url=f"{_timeline(container, project)}/items/{tent.id}",
                items=frozenset({tent.id}),
            )
        }

    def test_with_nothing_waiting_on_the_member_they_see_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        # A plan step in progress, a notice, a wait and a running work item
        # wait on no one (F23.2, F27.5): none of them makes a notification.
        project = _make(
            container,
            tasks=[{"id": "t1", "title": "Pitch the tent", "status": "in_progress"}],
            paused=True,
        )
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

        assert _should_see(container, session, project) == {"ada": None}

    def test_every_open_member_sees_it_whatever_their_browsers(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        """Ben has no browser subscribed: whether a push reaches one is the
        reconcile's."""
        _ben(container)
        project = _make(container, members=["ada", "ben"])
        tent = _decision(container, session, project, environment)

        seen = _should_see(container, session, project)

        assert seen["ada"] is not None and seen["ada"].items == {tent.id}
        assert seen["ben"] == seen["ada"]

    def test_an_archived_project_shows_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        _decision(container, session, project, environment)
        project.archived = True
        session.flush()

        assert _should_see(container, session, project) == {"ada": None}

    def test_a_closed_membership_shows_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        ben = _ben(container)
        project = _make(container, members=["ada", "ben"])
        _decision(container, session, project, environment)
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
        assert _should_see(container, session, project) == {"ada": None}

        container.test_data_service().item(
            project.id, "question", "Where?", QUESTION, by_pilot=True
        )

        seen = _seen(container, session, project)

        assert (seen.title, seen.body) == ("New project", "Where?")

    def test_a_finished_projects_archive_question_waits_on_its_members(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        # F5.6: the nudge to archive; "Finished" is not said.
        project = _make(container, state="finished")
        question = container.document_service().bear_archive_question(project)

        assert _seen(container, session, project) == StandingNotification(
            tag=str(project.id),
            title="Camp",
            body="Archive the project?",
            url=f"{_timeline(container, project)}/items/{question.id}",
            items=frozenset({question.id}),
        )

    def test_only_the_memberships_asked_for_are_answered(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        _ben(container)
        project = _make(container, members=["ada", "ben"])
        _decision(container, session, project, environment)
        ada = session.scalars(
            select(ProjectMember).where(ProjectMember.user_id == person.id)
        ).one()

        seen = container.standing_notification_service().should_see(project, [ada])

        assert list(seen) == [ada.id]


@pytest.mark.usefixtures("person")
class TestWhatWaits:
    def test_an_urgent_notice_and_a_stopped_work_item_wait_on_the_member(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        _work(session, project, environment, SessionState.STOPPED)
        assert _seen(container, session, project).body == "Build the camp"

        _bear(
            container,
            project,
            _run(session, project, environment),
            "notice",
            "Storm",
            "A storm comes.\n",
            urgent="true",
        )
        assert _seen(container, session, project).body == "Storm, +1"

    def test_an_item_for_one_member_waits_on_them_alone_and_is_not_counted_for_another(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        _ben(container)
        project = _make(container, members=["ada", "ben"])
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

        seen = _should_see(container, session, project)

        assert seen["ada"] is None
        assert seen["ben"] is not None and seen["ben"].body == "Your boots?"

        _bear(container, project, run, "decision", "Which tent?", DECISION)
        seen = _should_see(container, session, project)

        assert seen["ada"] is not None and seen["ada"].body == "Which tent?"
        assert seen["ben"] is not None and seen["ben"].body == "Which tent?, +1"

    def test_a_document_whose_claims_a_running_work_item_holds_waits_on_no_one(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        """Pilot's while every open block is held (DB 225, 296); once the
        work item doing them failed, the person's (F94.5)."""
        project = _make(container)
        run = _run(session, project, environment)
        documents = container.document_service()
        item = documents.register(project, run, "/work/Camp/docs/claimed.md").item
        documents.publish_read(
            session.get_one(models.Document, item.id), CLAIMED_ONLY, run.id
        )
        doing = _work(session, project, environment, SessionState.RUNNING)
        session.add_all(
            models.ClaimAssignment(work_id=doing.id, block_id=block.id)
            for block in session.scalars(
                select(models.Block).where(models.Block.document_id == item.id)
            )
        )
        session.flush()

        assert _should_see(container, session, project) == {"ada": None}

        session.get_one(models.Session, doing.id).state_code = SessionState.FAILED
        session.flush()

        assert _seen(container, session, project).body == "Build the camp, +1"


@pytest.mark.usefixtures("person")
class TestMessage:
    def test_the_latest_ask_first_and_a_count_of_the_others(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(
            container,
            tasks=[{"id": "t1", "title": "Pitch the tent", "status": "in_progress"}],
        )
        run = _run(session, project, environment)
        _wait(session, project, environment, "The site opens")
        _work(session, project, environment, SessionState.RUNNING)
        for title in ("Where?", "Which stove?", "Which tent?"):
            _bear(container, project, run, "question", title, QUESTION)

        # No plan step, no status line, nothing running and no open wait.
        assert _seen(container, session, project).body == "Which tent?, +2"

    def test_a_pause_changes_nothing(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container, paused=True)
        _decision(container, session, project, environment)

        assert _seen(container, session, project).body == "Which tent?"

    def test_an_untitled_item_reads_by_its_kind(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        _decision(container, session, project, environment)
        _work(session, project, environment, SessionState.STOPPED, None)

        assert _seen(container, session, project).body == "Work, +1"

    def test_the_records_texts_read_as_they_are_written(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        """Plain text, with no Markdown escape (V12)."""
        project = _make(container, name="Camp *2026*")
        _work(
            session,
            project,
            environment,
            SessionState.STOPPED,
            "1. Set up `ci` & [deploy]_now_, 2) ship",
        )

        seen = _seen(container, session, project)

        assert seen.title == "Camp *2026*"
        assert seen.body == "1. Set up `ci` & [deploy]_now_, 2) ship"

    def test_a_long_title_is_cut_and_the_text_left_to_the_push(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        """The push's payload cuts its body to fit (`Push.payload`), which
        the title's cut leaves room for."""
        project = _make(container, name="N" * 300)
        _work(session, project, environment, SessionState.STOPPED, "x" * 5000)

        seen = _seen(container, session, project)

        assert seen.title == "N" * 249 + "…"
        assert seen.body == "x" * 5000


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
        decision = _bear(container, project, run, "decision", "Which tent?", DECISION)
        assert (
            _seen(container, session, project).url
            == f"{_timeline(container, project)}/items/{decision.id}"
        )

        _bear(container, project, run, "question", "Where?", QUESTION)
        assert _seen(container, session, project).url == _timeline(container, project)


class TestPush:
    def test_an_alert_renotifies_and_an_update_does_not(self) -> None:
        notification = StandingNotification(
            tag="the-project",
            title="Camp",
            body="Which tent?, +1",
            url="https://pilot.example.com/projects/the-project",
            items=frozenset({uuid.uuid4(), uuid.uuid4()}),
        )

        assert notification.push(alert=True) == Push(
            title="Camp",
            body="Which tent?, +1",
            tag="the-project",
            url="https://pilot.example.com/projects/the-project",
            renotify=True,
        )
        assert notification.push(alert=False).renotify is False
