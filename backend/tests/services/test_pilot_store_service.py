"""`pilot-store`, the brain's tools (TD §4.5, F86): the gate that admits a
chat's or a job's Session while its turn runs, and the five tools that act on
its project, each call that changed the record writing its Effect (F41) and
`ask_writer` its Writer Question (DB decision 59)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    InvalidOperationException,
    RecordNotFoundException,
)
from app.models import (
    Block,
    Document,
    Effect,
    Environment,
    Item,
    Project,
    ProjectTransition,
    Turn,
    User,
    WriterQuestion,
)
from app.models.reference import (
    AnswerChannel,
    EffectKind,
    ProjectState,
    RecordKind,
    SessionState,
    TransitionKind,
    UserKind,
)
from app.services.container import ServiceContainer
from app.services.pilot_server import token_hash
from app.services.pilot_store_service import (
    PASS_QUESTIONS_TOTAL,
    Brain,
    PilotStoreService,
)
from app.services.session_record_service import read_records
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.supervisor import metric_value

TOKEN = "brain-token"

TOOL_USE_ID = "toolu_01"

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

CAMP_PLAN = """---
title: Camp plan
---

```decision id=D1
options:
  - Dome
  - Tunnel
recommend: Dome
```

```question id=Q1
default: The lake
```
"""

SETTLED_PLAN = """---
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
answer: The lake
by: agent
at: 2026-10-12T09:30:00Z
```
"""

NOTICE = "# The lake is open\n"

REVIEW = """---
title: Camp survey
---

The lake and the forest compared.
"""

REGISTERED = "/work/Example/docs/survey.md"

REGISTERED_TEXT = """Two asks about the camp.

```question id=Q1
```

```question id=Q2
```

```decision id=D1
options:
  - Dome
  - Tunnel
```
"""


def _brain(
    db: DbSession,
    project: Project,
    environment: Environment,
    kind: str = "chat",
    *,
    state: SessionState = SessionState.RUNNING,
    token: str = TOKEN,
) -> models.Session:
    """A Session of `kind` whose bearer is `token`, its one Turn in flight."""
    now = datetime.now(UTC)
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code=kind,
        cwd="/work/PilotProjects",
        token_hash=token_hash(token),
        state_code=state,
        turns=1,
        turn_started_at=now,
    )
    db.add(run)
    db.flush()
    db.add(Turn(session_id=run.id, seq=1, message="Go on.", started_at=now))
    db.flush()
    return run


def _admitted(run: models.Session) -> Brain:
    return Brain(run.id, run.project_id, run.kind_code)


def _service(container: ServiceContainer) -> PilotStoreService:
    service: PilotStoreService = container.pilot_store_service()
    return service


def _bear(
    container: ServiceContainer,
    project: Project,
    run: models.Session,
    kind: str,
    title: str,
    text: str,
) -> Item:
    return container.document_service().bear_item(project, kind, title, run, text)


def _block(db: DbSession, item: Item, local_id: str) -> Block:
    return db.scalars(
        select(Block).where(Block.document_id == item.id, Block.local_id == local_id)
    ).one()


def _registered(
    db: DbSession,
    container: ServiceContainer,
    project: Project,
    environment: Environment,
    text: str = REGISTERED_TEXT,
) -> Item:
    """A document a worker registered, read at its run's end."""
    worker = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="work",
        cwd="/work/Example",
        token_hash=token_hash("worker-token"),
        state_code=SessionState.IDLE,
    )
    db.add(worker)
    db.flush()
    documents = container.document_service()
    item = documents.register(project, worker, REGISTERED).item
    documents.publish_read(db.get_one(Document, item.id), text, worker.id)
    return item


def _work(
    db: DbSession,
    container: ServiceContainer,
    project: Project,
    state: SessionState = SessionState.RUNNING,
) -> models.Session:
    """A work item's Session in `state`, its brief its Turn."""
    now = datetime.now(UTC)
    run = models.Session(
        project_id=project.id,
        kind_code="work",
        cwd="/work/Example",
        token_hash=token_hash(f"work-{uuid.uuid4()}"),
        state_code=state,
        turns=1,
        turn_started_at=now,
    )
    db.add(run)
    db.flush()
    db.add(Turn(session_id=run.id, seq=1, message="Pitch it.", started_at=now))
    container.record_service().place_work(project, run, "Pitching the tent")
    return run


def _other_project(db: DbSession, person: User) -> Project:
    other = Project(created_by_user_id=person.id)
    db.add(other)
    db.flush()
    return other


def _opened(db: DbSession, project: Project) -> Project:
    project.state_code = ProjectState.OPEN
    project.slug = "camp"
    project.name = "Camp"
    db.flush()
    return project


def _pilot(db: DbSession) -> User:
    return db.scalars(select(User).where(User.kind_code == UserKind.AGENT)).one()


def _effects(db: DbSession) -> list[Effect]:
    return list(db.scalars(select(Effect).order_by(Effect.id)))


def _effect_record(db: DbSession, run: models.Session) -> Any:
    """The payload of the Session's one record, its call's effect."""
    [stored] = read_records(db, run.id, limit=10)
    assert (stored.record.kind_code, stored.turn) == (RecordKind.SERVER, 1)
    return stored.record.payload


class TestPilotStoreServiceAdmit:
    @pytest.mark.parametrize("kind", ["chat", "job"])
    def test_a_chats_or_a_jobs_bearer_names_its_session_while_its_turn_runs(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        kind: str,
    ) -> None:
        run = _brain(session, project, environment, kind)
        _brain(session, project, environment, kind, token="another-token")

        brain = _service(container).admit(f"Bearer {TOKEN}")

        assert brain == Brain(run.id, project.id, kind)

    @pytest.mark.parametrize(
        ("authorization", "message"),
        [
            (None, "Cannot call pilot-store because the request carries no bearer"),
            (
                f"bearer {TOKEN}",
                "Cannot call pilot-store because the request carries no bearer",
            ),
            (
                "Bearer an-unknown-token",
                "Cannot call pilot-store because no session has the request's bearer",
            ),
        ],
    )
    def test_no_bearer_or_one_no_session_has_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        authorization: str | None,
        message: str,
    ) -> None:
        _brain(session, project, environment)

        with pytest.raises(AuthenticationException) as refused:
            _service(container).admit(authorization)

        assert refused.value.message == message

    def test_a_work_items_bearer_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment, "work")

        with pytest.raises(AuthorizationException) as refused:
            _service(container).admit(f"Bearer {TOKEN}")

        assert refused.value.message == (
            f"Cannot call pilot-store because session {run.id} is a work session,"
            " not a chat's or a job's"
        )

    @pytest.mark.parametrize(
        "state",
        [
            SessionState.HELD,
            SessionState.STARTING,
            SessionState.IDLE,
            SessionState.STOPPED,
            SessionState.ENDED,
            SessionState.FAILED,
        ],
    )
    def test_a_session_whose_turn_does_not_run_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        state: SessionState,
    ) -> None:
        run = _brain(session, project, environment, state=state)

        with pytest.raises(AuthorizationException) as refused:
            _service(container).admit(f"Bearer {TOKEN}")

        assert refused.value.message == (
            f"Cannot call pilot-store because session {run.id} has no turn running"
        )


class TestPilotStoreServiceAnswer:
    def test_the_answer_is_the_persons_through_the_chat_and_its_effect_the_calls(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "document", "Camp plan", CAMP_PLAN)

        line = _service(container).answer(
            _admitted(run),
            f"{item.id}/D1",
            "Dome",
            "ada",
            note="The dome, it stands up in five minutes.",
            to=None,
            tool_use_id=TOOL_USE_ID,
        )

        block = _block(session, item, "D1")
        assert (
            block.answer,
            block.answered_by_user_id,
            block.via_code,
            block.note,
        ) == (
            "Dome",
            person.id,
            AnswerChannel.CHAT,
            "The dome, it stands up in five minutes.",
        )
        assert item.done_at is None
        assert (line.verb, line.label) == ("Answered", "D1 · Camp plan")
        payload = _effect_record(session, run)
        assert payload == {
            "type": "effect",
            "toolUseId": TOOL_USE_ID,
            "effect": {
                "verb": "Answered",
                "label": "D1 · Camp plan",
                "itemId": str(item.id),
                "blockId": f"{item.id}/D1",
            },
        }
        [effect] = _effects(session)
        assert (effect.kind_code, effect.block_id, effect.item_id) == (
            EffectKind.ANSWERED,
            block.id,
            None,
        )

    def test_the_answer_to_a_one_ask_item_is_its_done(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "decision", "Which tent?", DECISION)

        _service(container).answer(
            _admitted(run),
            f"{item.id}/D1",
            "Tunnel",
            "ada",
            note=None,
            to=None,
            tool_use_id=None,
        )

        assert (item.done_cause_code, item.done_by_user_id) == ("answered", person.id)
        assert _effect_record(session, run)["toolUseId"] is None

    def test_a_deferral_the_person_asks_for_is_recorded_with_its_to(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "document", "Camp plan", CAMP_PLAN)

        _service(container).answer(
            _admitted(run),
            f"{item.id}/Q1",
            "deferred",
            "ada",
            note="Ask again at the site.",
            to="plan",
            tool_use_id=TOOL_USE_ID,
        )

        block = _block(session, item, "Q1")
        assert (block.answer, block.via_code) == ("deferred", AnswerChannel.CHAT)

    def test_a_registered_document_with_no_title_is_named_by_its_file(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _registered(session, container, project, environment)
        assert item.title is None

        line = _service(container).answer(
            _admitted(run),
            f"{item.id}/Q1",
            "The lake",
            "ada",
            note=None,
            to=None,
            tool_use_id=TOOL_USE_ID,
        )

        assert line.label == "Q1 · survey.md"

    def test_a_block_of_another_projects_item_is_not_found(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        other = _other_project(session, person)
        theirs = _bear(
            container,
            other,
            _brain(session, other, environment, token="theirs"),
            "decision",
            "Which tent?",
            DECISION,
        )
        run = _brain(session, project, environment)

        with pytest.raises(RecordNotFoundException) as refused:
            _service(container).answer(
                _admitted(run),
                f"{theirs.id}/D1",
                "Dome",
                "ada",
                note=None,
                to=None,
                tool_use_id=TOOL_USE_ID,
            )

        assert refused.value.message == f"Item {theirs.id} was not found"
        assert _block(session, theirs, "D1").answer is None

    def test_a_block_of_an_item_with_no_text_is_not_found(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        work = _work(session, container, project)

        with pytest.raises(RecordNotFoundException) as refused:
            _service(container).answer(
                _admitted(run),
                f"{work.id}/D1",
                "Dome",
                "ada",
                note=None,
                to=None,
                tool_use_id=TOOL_USE_ID,
            )

        assert refused.value.message == f"Block {work.id}/D1 was not found"

    def test_a_block_its_document_does_not_hold_is_not_found(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "decision", "Which tent?", DECISION)

        with pytest.raises(RecordNotFoundException) as refused:
            _service(container).answer(
                _admitted(run),
                f"{item.id}/D9",
                "Dome",
                "ada",
                note=None,
                to=None,
                tool_use_id=TOOL_USE_ID,
            )

        assert refused.value.message == f"Block {item.id}/D9 was not found"

    @pytest.mark.parametrize("handle", ["nobody", "agent"])
    def test_a_handle_no_person_has_is_not_found_and_nothing_is_recorded(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        handle: str,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "decision", "Which tent?", DECISION)

        with pytest.raises(RecordNotFoundException) as refused:
            _service(container).answer(
                _admitted(run),
                f"{item.id}/D1",
                "Dome",
                handle,
                note=None,
                to=None,
                tool_use_id=TOOL_USE_ID,
            )

        assert refused.value.message == f"Person {handle} was not found"
        assert _block(session, item, "D1").answer is None
        assert _effects(session) == []

    def test_an_answer_the_record_refuses_records_no_effect(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "document", "Camp plan", CAMP_PLAN)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).answer(
                _admitted(run),
                f"{item.id}/D1",
                "deferred",
                "ada",
                note=None,
                to=None,
                tool_use_id=TOOL_USE_ID,
            )

        assert refused.value.message.endswith("because `deferred` names no `to`")
        assert _effects(session) == []
        assert read_records(session, run.id, limit=10) == []


class TestPilotStoreServiceMark:
    def test_done_for_a_person_takes_the_recommendations_and_is_their_mark(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "document", "Camp plan", CAMP_PLAN)

        line = _service(container).mark(
            _admitted(run), item.id, "done", "ada", TOOL_USE_ID
        )

        assert (item.done_cause_code, item.done_by_user_id) == ("marked", person.id)
        assert _block(session, item, "D1").answer == "Dome"
        assert (line.verb, line.label) == ("Marked done", "Camp plan")
        assert _effect_record(session, run)["effect"] == {
            "verb": "Marked done",
            "label": "Camp plan",
            "itemId": str(item.id),
        }
        [effect] = _effects(session)
        assert (effect.kind_code, effect.item_id) == (EffectKind.MARKED, item.id)

    @pytest.mark.parametrize(
        ("kind", "title", "text", "mark", "verb"),
        [
            ("notice", "The lake is open", NOTICE, "read", "Marked read"),
            ("review", "Camp survey", REVIEW, "reviewed", "Marked reviewed"),
        ],
    )
    def test_read_and_reviewed_are_the_persons_mark(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
        kind: str,
        title: str,
        text: str,
        mark: Any,
        verb: str,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, kind, title, text)

        line = _service(container).mark(_admitted(run), item.id, mark, "ada", None)

        assert (item.done_cause_code, item.done_by_user_id) == ("marked", person.id)
        assert (line.verb, line.label) == (verb, title)

    def test_without_for_done_is_pilots_on_a_document_it_settled_whole(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "document", "Camp plan", SETTLED_PLAN)

        line = _service(container).mark(
            _admitted(run), item.id, "done", None, TOOL_USE_ID
        )

        assert (item.done_cause_code, item.done_by_user_id) == (
            "settled",
            _pilot(session).id,
        )
        assert (line.verb, line.label) == ("Marked done", "Camp plan")

    def test_without_for_a_document_not_settled_whole_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "document", "Camp plan", CAMP_PLAN)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).mark(_admitted(run), item.id, "done", None, None)

        assert refused.value.message.endswith(
            "Pilot marks done only a document it settled whole, and these blocks"
            " are unanswered: D1, Q1"
        )
        assert _effects(session) == []

    @pytest.mark.parametrize("mark", ["read", "reviewed"])
    def test_without_for_read_and_reviewed_are_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        mark: Any,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "notice", "The lake is open", NOTICE)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).mark(_admitted(run), item.id, mark, None, None)

        assert refused.value.message == (
            f"Cannot mark item {item.id} {mark} because Pilot's own mark is Done, on"
            " a document it settled whole: Read and Reviewed are a person's, named"
            " by `for`"
        )
        assert item.done_at is None

    def test_a_mark_its_kind_does_not_take_is_the_records_refusal(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "decision", "Which tent?", DECISION)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).mark(_admitted(run), item.id, "read", "ada", None)

        assert refused.value.message.endswith("a decision item is not marked Read")
        assert _effects(session) == []

    def test_an_item_of_another_project_and_a_handle_no_person_has_are_not_found(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        other = _other_project(session, person)
        theirs = _bear(
            container,
            other,
            _brain(session, other, environment, token="theirs"),
            "notice",
            "The lake is open",
            NOTICE,
        )
        run = _brain(session, project, environment)
        mine = _bear(container, project, run, "notice", "The lake is open", NOTICE)
        service = _service(container)

        with pytest.raises(RecordNotFoundException) as not_mine:
            service.mark(_admitted(run), theirs.id, "read", "ada", None)
        with pytest.raises(RecordNotFoundException) as no_person:
            service.mark(_admitted(run), mine.id, "read", "nobody", None)

        assert not_mine.value.message == f"Item {theirs.id} was not found"
        assert no_person.value.message == "Person nobody was not found"


class TestPilotStoreServiceStopWork:
    @pytest.mark.parametrize("state", [SessionState.RUNNING, SessionState.HELD])
    def test_a_work_items_session_is_stopped_by_pilot(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        state: SessionState,
    ) -> None:
        run = _brain(session, project, environment)
        work = _work(session, container, project, state)

        line = _service(container).stop_work(_admitted(run), work.id, TOOL_USE_ID)
        clear_after_commit_callbacks()

        assert (work.state_code, work.stopped_by_user_id) == (
            SessionState.STOPPED,
            _pilot(session).id,
        )
        assert (line.verb, line.label) == ("Stopped", "Pitching the tent")
        assert _effect_record(session, run)["effect"] == {
            "verb": "Stopped",
            "label": "Pitching the tent",
            "itemId": str(work.id),
        }
        [effect] = _effects(session)
        assert (effect.kind_code, effect.item_id) == (EffectKind.STOPPED, work.id)

    def test_an_item_that_is_no_work_item_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "decision", "Which tent?", DECISION)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).stop_work(_admitted(run), item.id, TOOL_USE_ID)

        assert refused.value.message == (
            "Cannot stop Which tent? because it is no work item"
        )

    def test_a_work_item_whose_turn_has_ended_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        work = _work(session, container, project, SessionState.IDLE)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).stop_work(_admitted(run), work.id, TOOL_USE_ID)

        assert refused.value.message == (
            "Cannot stop Pitching the tent because its turn has ended"
        )
        assert _effects(session) == []

    def test_a_work_item_of_another_project_is_not_found(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        other = _other_project(session, person)
        theirs = _work(session, container, other)
        run = _brain(session, project, environment)

        with pytest.raises(RecordNotFoundException) as refused:
            _service(container).stop_work(_admitted(run), theirs.id, TOOL_USE_ID)

        assert refused.value.message == f"Item {theirs.id} was not found"
        assert theirs.state_code == SessionState.RUNNING


class TestPilotStoreServiceFinish:
    def test_the_project_is_finished_by_pilot_its_effect_written_before_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _opened(session, project)
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "notice", "The lake is open", NOTICE)
        pilot = _pilot(session)

        line = _service(container).finish(_admitted(run), TOOL_USE_ID)
        clear_after_commit_callbacks()

        assert project.state_code == ProjectState.FINISHED
        [transition] = session.scalars(
            select(ProjectTransition).where(
                ProjectTransition.kind_code == TransitionKind.FINISHED
            )
        )
        assert transition.by_user_id == pilot.id
        assert (item.done_cause_code, item.done_by_user_id) == ("finished", pilot.id)
        assert (run.state_code, run.stopped_by_user_id) == (
            SessionState.STOPPED,
            pilot.id,
        )
        assert (line.verb, line.label) == ("Finished", "Camp")
        assert _effect_record(session, run) == {
            "type": "effect",
            "toolUseId": TOOL_USE_ID,
            "effect": {"verb": "Finished", "label": "Camp"},
        }
        [effect] = _effects(session)
        assert (effect.kind_code, effect.item_id, effect.block_id) == (
            EffectKind.FINISHED,
            None,
            None,
        )
        [turn] = session.scalars(select(Turn).where(Turn.session_id == run.id))
        assert turn.ended_at is None

    @pytest.mark.parametrize(
        ("state", "cause"),
        [
            (ProjectState.DRAFT, "it is a draft"),
            (ProjectState.FINISHED, "it is finished already"),
        ],
    )
    def test_a_draft_or_a_finished_project_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        state: ProjectState,
        cause: str,
    ) -> None:
        if state is ProjectState.FINISHED:
            _opened(session, project).state_code = state
        run = _brain(session, project, environment)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).finish(_admitted(run), TOOL_USE_ID)

        assert refused.value.message.endswith(f"because {cause}")
        assert run.state_code == SessionState.RUNNING


class TestPilotStoreServiceAskWriter:
    def test_a_jobs_question_is_recorded_with_its_turn_and_counted(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        job = _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment)
        counted = metric_value(PASS_QUESTIONS_TOTAL, project=str(project.id))
        service = _service(container)

        first = service.ask_writer(
            _admitted(job), item.id, f"{item.id}/Q2", "Which lake? The north one?"
        )
        second = service.ask_writer(
            _admitted(job), item.id, f"{item.id}/Q1", "What does 'the site' mean?"
        )

        assert (first, second) == (["Q2"], ["Q1", "Q2"])
        [turn] = session.scalars(select(Turn).where(Turn.session_id == job.id))
        assert [
            (question.turn_id, question.block_id, question.question)
            for question in session.scalars(
                select(WriterQuestion).order_by(WriterQuestion.id)
            )
        ] == [
            (turn.id, _block(session, item, "Q2").id, "Which lake? The north one?"),
            (turn.id, _block(session, item, "Q1").id, "What does 'the site' mean?"),
        ]
        assert metric_value(PASS_QUESTIONS_TOTAL, project=str(project.id)) == (
            counted + 2
        )
        assert _effects(session) == []
        assert read_records(session, job.id, limit=10) == []

    def test_the_timeline_moves_once_the_question_commits(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        job = _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment)
        brain, item_id, project_id = _admitted(job), item.id, project.id
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            _service(container).ask_writer(brain, item_id, f"{item_id}/Q1", "Which?")

        assert ProjectChanged(project_id) in engine_events

    def test_a_chats_question_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        chat = _brain(session, project, environment, "chat")
        item = _registered(session, container, project, environment)

        with pytest.raises(AuthorizationException) as refused:
            _service(container).ask_writer(
                _admitted(chat), item.id, f"{item.id}/Q1", "Which?"
            )

        assert refused.value.message == (
            f"Cannot ask the writer about block {item.id}/Q1 because session"
            f" {chat.id} is a chat session: the pre-ruling pass, a job's, asks"
        )

    def test_a_blank_question_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        job = _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).ask_writer(
                _admitted(job), item.id, f"{item.id}/Q1", "  \n"
            )

        assert refused.value.message.endswith("because the question is blank")

    def test_a_document_pilot_added_is_no_registered_document(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        job = _brain(session, project, environment, "job")
        item = _bear(container, project, job, "decision", "Which tent?", DECISION)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).ask_writer(
                _admitted(job), item.id, f"{item.id}/D1", "Which?"
            )

        assert refused.value.message.endswith(
            f"because item {item.id} is no registered document"
        )

    def test_a_block_of_another_document_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        job = _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment)
        other = _bear(container, project, job, "decision", "Which tent?", DECISION)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).ask_writer(
                _admitted(job), item.id, f"{other.id}/D1", "Which?"
            )

        assert refused.value.message.endswith(
            f"because it is no block of document {item.id}"
        )

    def test_a_block_the_document_does_not_hold_is_not_found(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        job = _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment)

        with pytest.raises(RecordNotFoundException) as refused:
            _service(container).ask_writer(
                _admitted(job), item.id, f"{item.id}/Q9", "Which?"
            )

        assert refused.value.message == f"Block {item.id}/Q9 was not found"

    def test_an_answered_block_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        job = _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment)
        container.record_service().answer(
            session.get_one(Document, item.id), "Q1", person, "The lake"
        )

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).ask_writer(
                _admitted(job), item.id, f"{item.id}/Q1", "Which?"
            )

        assert refused.value.message.endswith("because block Q1 is answered")

    def test_a_block_asked_about_already_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        job = _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment)
        service = _service(container)
        service.ask_writer(_admitted(job), item.id, f"{item.id}/Q1", "Which?")

        with pytest.raises(InvalidOperationException) as refused:
            service.ask_writer(_admitted(job), item.id, f"{item.id}/Q1", "And?")

        assert refused.value.message.endswith(
            "because its writer was asked about block Q1 already"
        )

    def test_a_done_document_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        job = _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment)
        container.record_service().close_unanswered(
            _opened(session, project), person, datetime.now(UTC)
        )

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).ask_writer(
                _admitted(job), item.id, f"{item.id}/Q1", "Which?"
            )

        assert refused.value.message.endswith("because the document is done")

    def test_a_document_of_another_project_is_not_found(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        other = _other_project(session, person)
        theirs = _registered(session, container, other, environment)
        job = _brain(session, project, environment, "job")

        with pytest.raises(RecordNotFoundException) as refused:
            _service(container).ask_writer(
                _admitted(job), theirs.id, f"{theirs.id}/Q1", "Which?"
            )

        assert refused.value.message == f"Item {theirs.id} was not found"

    def test_a_job_whose_turn_has_ended_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        job = _brain(session, project, environment, "job")
        for turn in session.scalars(select(Turn).where(Turn.session_id == job.id)):
            turn.ended_at = datetime.now(UTC)
        item = _registered(session, container, project, environment)

        with pytest.raises(AuthorizationException) as refused:
            _service(container).ask_writer(
                _admitted(job), item.id, f"{item.id}/Q1", "Which?"
            )

        assert refused.value.message == (
            f"Cannot call pilot-store because session {job.id} has no turn running"
        )
        assert list(session.scalars(select(WriterQuestion))) == []
