"""`pilot-store`, the brain's tools (TD §4.5, F86): the gate that admits a
chat's or a job's Session while its turn runs, and the seven tools that act on
its project, each call that changed the record writing its Effect (F41) and
`ask_writer` its Writer Question (DB decision 59)."""

import functools
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from dependency_injector import providers
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.attachments import MAX_CALL_FILES, MAX_CALL_SIZE, copied
from app.engine.bus import EngineEvent, ProjectChanged
from app.engine.claims import standing
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    InvalidOperationException,
    RecordNotFoundException,
)
from app.models import (
    Attachment,
    Block,
    Chat,
    ClaimAssignment,
    Document,
    Effect,
    Environment,
    Item,
    ItemAttachment,
    PlanTask,
    Project,
    ProjectTransition,
    Turn,
    User,
    Work,
    WriterQuestion,
)
from app.models.reference import (
    AnswerChannel,
    ChatKind,
    EffectKind,
    ProjectState,
    RecordKind,
    SessionState,
    TaskStatus,
    TransitionKind,
    UserKind,
    WorkTrigger,
)
from app.schemas.pilot_store import AddItemRequestSchema
from app.schemas.timeline import HeldReason
from app.services.container import ServiceContainer
from app.services.controller_client import FILE_SIZE_CAP, ControllerClient
from app.services.controller_outage import ControllerOutage
from app.services.pilot_server import token_hash
from app.services.pilot_store_service import (
    PASS_QUESTIONS_TOTAL,
    Brain,
    PilotStoreService,
)
from app.services.session_record_service import read_records
from app.services.session_start_service import SessionStartService
from app.services.start_gate import Held
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.fake_controller import ServedFakeController
from tests.support.starts import configured_starts
from tests.support.supervisor import Supervise, metric_value

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

DRAFT = """---
title: Camp
slug: camp
---

```question id=Q1
default: The lake
```
"""

REGISTERED = "/work/Example/docs/survey.md"

CUT_OVER = """Two actions for the cut-over.

```action id=A1
answer: Pilot does it
by: agent
at: 2026-10-12T09:30:00Z
note: Rotating the CI token, its own work item
```

```action id=A2
```

```decision id=D1
options:
  - Dome
  - Tunnel
```
"""

ONE_BLOCK_SETTLED = """```question id=Q1
answer: deferred
by: agent
at: 2026-10-12T09:30:00Z
to: plan
```
"""

ONE_BLOCK_CLAIMED = """```action id=A1
answer: Pilot does it
by: agent
at: 2026-10-12T09:30:00Z
```
"""

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


def _chat(
    db: DbSession, run: models.Session, kind: ChatKind = ChatKind.DEFINITION
) -> models.Session:
    """`run` a chat of its project, its draft's definition chat by default."""
    db.add(
        Chat(
            id=run.id,
            project_id=run.project_id,
            session_kind_code="chat",
            kind_code=kind,
        )
    )
    db.flush()
    return run


def _draft_block(db: DbSession, draft: Document, local_id: str) -> Block:
    return db.scalars(
        select(Block).where(Block.document_id == draft.id, Block.local_id == local_id)
    ).one()


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


def _plan_task(project: Project, task_id: str) -> PlanTask:
    return PlanTask(
        project_id=project.id,
        task_id=task_id,
        position=1,
        title="The camp",
        status_code=TaskStatus.PENDING,
    )


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

    @pytest.mark.usefixtures("placing")
    def test_the_answer_to_a_one_ask_item_is_its_done_and_places_the_job_after_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        """A close the chat records on a person's behalf is theirs (DB
        decision 45)."""
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
        assert _jobs_after(session, item) == [WorkTrigger.ITEM_DONE]

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


class TestPilotStoreServiceAnswerDraft:
    """In a draft's definition chat, `answer` takes the draft's asks by
    `project.md/<local id>` (F47.4, F42.1); nowhere else."""

    def test_in_its_definition_chat_the_drafts_ask_is_answered_into_project_md(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        draft = container.document_service().bear_draft(project, DRAFT)
        run = _chat(session, _brain(session, project, environment))

        line = _service(container).answer(
            _admitted(run),
            "project.md/Q1",
            "The lake",
            "ada",
            note="By the water, for the swim.",
            to=None,
            tool_use_id=TOOL_USE_ID,
        )

        block = _draft_block(session, draft, "Q1")
        assert (
            block.answer,
            block.answered_by_user_id,
            block.via_code,
            block.note,
        ) == ("The lake", person.id, AnswerChannel.CHAT, "By the water, for the swim.")
        assert draft.published_text is not None
        assert "answer: The lake\nby: ada\n" in draft.published_text
        assert project.state_code is ProjectState.DRAFT
        assert (line.verb, line.label) == ("Answered", "Q1 · Camp")
        assert _effect_record(session, run) == {
            "type": "effect",
            "toolUseId": TOOL_USE_ID,
            "effect": {
                "verb": "Answered",
                "label": "Q1 · Camp",
                "blockId": "project.md/Q1",
            },
        }
        [effect] = _effects(session)
        assert (effect.kind_code, effect.block_id, effect.item_id) == (
            EffectKind.ANSWERED,
            block.id,
            None,
        )

    def test_a_draft_with_no_title_is_named_by_its_file(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        container.document_service().bear_draft(project, "```question id=Q1\n```\n")
        run = _chat(session, _brain(session, project, environment))

        line = _service(container).answer(
            _admitted(run),
            "project.md/Q1",
            "The lake",
            "ada",
            note=None,
            to=None,
            tool_use_id=TOOL_USE_ID,
        )

        assert line.label == "Q1 · project.md"

    def test_answering_it_again_replaces_the_answer(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = container.document_service().bear_draft(project, DRAFT)
        run = _chat(session, _brain(session, project, environment))
        answer = functools.partial(
            _service(container).answer,
            _admitted(run),
            "project.md/Q1",
            person="ada",
            note=None,
            to=None,
            tool_use_id=None,
        )

        answer(value="The lake")
        answer(value="The forest")

        assert _draft_block(session, draft, "Q1").answer == "The forest"
        assert len(_effects(session)) == 2

    @pytest.mark.parametrize(
        "kind",
        [
            pytest.param(ChatKind.PROJECT, id="the project's chat"),
            pytest.param(ChatKind.DEFINITION, id="its definition chat past Create"),
        ],
    )
    def test_past_create_no_chat_answers_the_drafts_ask(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        kind: ChatKind,
    ) -> None:
        draft = container.document_service().bear_draft(project, DRAFT)
        run = _chat(session, _brain(session, project, environment), kind)
        _opened(session, project)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).answer(
                _admitted(run),
                "project.md/Q1",
                "The lake",
                "ada",
                note=None,
                to=None,
                tool_use_id=TOOL_USE_ID,
            )

        assert refused.value.message == (
            "Cannot answer block project.md/Q1 because `project.md` takes answers"
            " in its draft's definition chat alone"
        )
        assert _draft_block(session, draft, "Q1").answer is None
        assert _effects(session) == []

    def test_a_job_answers_no_ask_of_the_draft(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = container.document_service().bear_draft(project, DRAFT)
        run = _brain(session, project, environment, "job")

        with pytest.raises(InvalidOperationException):
            _service(container).answer(
                _admitted(run),
                "project.md/Q1",
                "The lake",
                "ada",
                note=None,
                to=None,
                tool_use_id=TOOL_USE_ID,
            )

        assert _draft_block(session, draft, "Q1").answer is None

    def test_an_ask_the_draft_does_not_hold_is_not_found_by_its_name(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        container.document_service().bear_draft(project, DRAFT)
        run = _chat(session, _brain(session, project, environment))

        with pytest.raises(RecordNotFoundException) as refused:
            _service(container).answer(
                _admitted(run),
                "project.md/Q9",
                "The lake",
                "ada",
                note=None,
                to=None,
                tool_use_id=TOOL_USE_ID,
            )

        assert refused.value.message == "Block project.md/Q9 was not found"
        assert _effects(session) == []

    def test_the_record_refuses_an_answer_of_an_archived_draft(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = container.document_service().bear_draft(project, DRAFT)
        run = _chat(session, _brain(session, project, environment))
        project.archived = True
        session.flush()

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).answer(
                _admitted(run),
                "project.md/Q1",
                "The lake",
                "ada",
                note=None,
                to=None,
                tool_use_id=TOOL_USE_ID,
            )

        assert refused.value.message.endswith("because its project is archived")
        assert _draft_block(session, draft, "Q1").answer is None
        assert _effects(session) == []


class TestPilotStoreServiceMark:
    @pytest.mark.usefixtures("placing")
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
        assert _jobs_after(session, item) == [WorkTrigger.ITEM_DONE]

    @pytest.mark.parametrize(
        ("kind", "title", "text", "mark", "verb", "jobs"),
        [
            ("notice", "The lake is open", NOTICE, "read", "Marked read", []),
            (
                "review",
                "Camp survey",
                REVIEW,
                "reviewed",
                "Marked reviewed",
                [WorkTrigger.ITEM_DONE],
            ),
        ],
    )
    @pytest.mark.usefixtures("placing")
    def test_read_and_reviewed_are_the_persons_mark_a_notices_read_starting_no_job(
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
        jobs: list[WorkTrigger],
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, kind, title, text)

        line = _service(container).mark(_admitted(run), item.id, mark, "ada", None)

        assert (item.done_cause_code, item.done_by_user_id) == ("marked", person.id)
        assert (line.verb, line.label) == (verb, title)
        assert _jobs_after(session, item) == jobs

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
        assert _jobs_after(session, item) == []

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

    def test_without_for_done_takes_a_registered_document_of_one_block_settled(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment, ONE_BLOCK_SETTLED)
        assert item.kind_code == "question"

        line = _service(container).mark(
            _admitted(run), item.id, "done", None, TOOL_USE_ID
        )

        assert (item.done_cause_code, item.done_by_user_id) == (
            "settled",
            _pilot(session).id,
        )
        assert (line.verb, line.label) == ("Marked done", "survey.md")

    def test_without_for_an_action_claimed_and_not_yet_done_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment, ONE_BLOCK_CLAIMED)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).mark(_admitted(run), item.id, "done", None, None)

        assert refused.value.message.endswith(
            "Pilot marks done only a document it settled whole, and these blocks"
            " are unanswered: A1"
        )
        assert item.done_at is None
        assert _effects(session) == []


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

    def test_a_job_of_pilots_own_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """A job has no Resume, so a job Pilot stopped never goes on (F26.3)."""
        run = _brain(session, project, environment)
        job = models.Session(
            project_id=project.id,
            kind_code="job",
            cwd="/work/PilotProjects",
            token_hash=token_hash(f"job-{uuid.uuid4()}"),
            state_code=SessionState.RUNNING,
        )
        session.add(job)
        session.flush()
        container.record_service().place_work(
            project, job, "Deciding what is next", trigger=WorkTrigger.SETUP
        )

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).stop_work(_admitted(run), job.id, TOOL_USE_ID)

        assert refused.value.message == (
            "Cannot stop Deciding what is next because it is Pilot's own work"
        )
        assert job.state_code is SessionState.RUNNING
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


ELSEWHERE = "example-elsewhere"
"""An environment of the fleet Pilot has not touched."""

DESIGN = "/work/Elsewhere/design"

REPO = "example/Example"

BRIEF = "Rename the badge."


def _added(**fields: Any) -> AddItemRequestSchema:
    return AddItemRequestSchema.model_validate(fields)


def _document_text(db: DbSession, item: Item) -> str | None:
    return db.get_one(Document, item.id).published_text


def _attachments(db: DbSession, item: Item) -> list[Attachment]:
    return list(
        db.scalars(
            select(Attachment)
            .join(ItemAttachment, ItemAttachment.attachment_id == Attachment.id)
            .where(ItemAttachment.item_id == item.id)
            .order_by(ItemAttachment.position)
        )
    )


def _elsewhere(fake_controller: ServedFakeController) -> None:
    """The environment elsewhere, holding a design folder of two files."""
    fake_controller.add_environment(ELSEWHERE, name="Elsewhere-1")
    fake_controller.put_file(ELSEWHERE, f"{DESIGN}/README.md", b"# The design\n")
    fake_controller.put_file(ELSEWHERE, f"{DESIGN}/data/model.md", b"The model.\n")


@pytest.fixture
def starts(container: ServiceContainer, supervise: Supervise) -> SessionStartService:
    """The start on a controller, its loops never run, on a slot of one work
    item per project."""
    return configured_starts(container, supervise, project_max=1)


@pytest.fixture
def placing(container: ServiceContainer, starts: SessionStartService) -> None:
    """The container's start the configured one, through which a person's
    close of an item of Pilot's own places the job after it."""
    container.session_start_service.override(providers.Object(starts))


def _jobs_after(db: DbSession, item: Item) -> list[WorkTrigger | None]:
    """The triggers of the jobs placed after the item's close."""
    return list(
        db.scalars(select(Work.trigger_code).where(Work.trigger_item_id == item.id))
    )


def _starting(
    container: ServiceContainer, starts: SessionStartService
) -> PilotStoreService:
    """The service on `starts`, its work items' start written and never run."""
    service: PilotStoreService = container.pilot_store_service(
        session_start_service=starts
    )
    return service


class TestPilotStoreServiceAddProse:
    def test_a_prose_item_is_born_with_its_title_and_facts_its_path_answered(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        session.add(_plan_task(project, "keys"))
        run = _brain(session, project, environment)

        added = _service(container).add_item(
            _admitted(run),
            _added(
                kind="action",
                title="Put the v4 key into OpenBao",
                step="keys",
                urgent=True,
                summary="The importer needs it.",
                **{"for": "ada"},
            ),
            TOOL_USE_ID,
        )
        clear_after_commit_callbacks()

        item = added.item
        assert added.path == (
            f"/work/Projects/draft-{project.number}/items/1-put-the-v4-key-into-openbao.md"
        )
        assert (added.state, added.held) == (None, None)
        assert _document_text(session, item) == (
            "---\n"
            "title: Put the v4 key into OpenBao\n"
            "step: keys\n"
            "urgent: true\n"
            "for: ada\n"
            "summary: The importer needs it.\n"
            "---\n"
        )
        assert (
            item.kind_code,
            item.title,
            item.plan_task_id,
            item.urgent,
            item.for_user_id,
            item.created_by_session_id,
        ) == ("action", "Put the v4 key into OpenBao", "keys", True, person.id, run.id)
        assert (added.line.verb, added.line.label) == (
            "Added",
            "Action · Put the v4 key into OpenBao",
        )
        assert _effect_record(session, run) == {
            "type": "effect",
            "toolUseId": TOOL_USE_ID,
            "effect": {
                "verb": "Added",
                "label": "Action · Put the v4 key into OpenBao",
                "itemId": str(item.id),
            },
        }
        [effect] = _effects(session)
        assert (effect.kind_code, effect.item_id) == (EffectKind.ADDED, item.id)

    def test_its_markdowns_own_title_stands_and_its_blocks_give_its_kind(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)

        added = _service(container).add_item(
            _admitted(run),
            _added(kind="document", title="Tent", markdown=DECISION),
            TOOL_USE_ID,
        )
        clear_after_commit_callbacks()

        assert _document_text(session, added.item) == DECISION
        assert (added.item.kind_code, added.item.title) == ("decision", "Which tent?")
        assert added.path is not None and added.path.endswith("/items/1-tent.md")
        assert added.line.label == "Decision · Which tent?"

    def test_markdown_with_no_front_matter_title_takes_the_calls(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)

        added = _service(container).add_item(
            _admitted(run),
            _added(kind="notice", title="The lake", markdown="It is open.\n"),
            TOOL_USE_ID,
        )
        clear_after_commit_callbacks()

        assert _document_text(session, added.item) == (
            "---\ntitle: The lake\n---\nIt is open.\n"
        )

    def test_markdown_titled_by_its_first_heading_alone_is_born_with_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)

        added = _service(container).add_item(
            _admitted(run), _added(kind="notice", markdown=NOTICE), TOOL_USE_ID
        )
        clear_after_commit_callbacks()

        assert _document_text(session, added.item) == (
            "---\ntitle: The lake is open\n---\n# The lake is open\n"
        )
        assert added.item.title == "The lake is open"

    @pytest.mark.parametrize(
        ("fields", "faults"),
        [
            pytest.param(
                {"markdown": "It is open.\n"},
                "the item has no title: give it `title` in the front matter or a"
                " first heading",
                id="no-title",
            ),
            pytest.param(
                {"title": "Camp", "markdown": "```decision id=D1\noptions: [\n```\n"},
                "line 5: block D1: the body is not a YAML mapping: while parsing a"
                " flow node, expected the node content, but found '<stream end>'",
                id="does-not-parse",
            ),
            pytest.param(
                {"title": "Camp", "step": "nowhere", "for": "zed"},
                "line 3: front matter: `step: nowhere` names no task of the"
                " project; line 4: front matter: `for: zed` names no handle",
                id="against-the-record",
            ),
        ],
    )
    def test_a_text_with_a_fault_is_refused_with_each_and_nothing_minted(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        fields: dict[str, str],
        faults: str,
    ) -> None:
        run = _brain(session, project, environment)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).add_item(
                _admitted(run), _added(kind="notice", **fields), TOOL_USE_ID
            )

        assert refused.value.message == (
            f"Cannot add a notice item because its text holds faults: {faults}"
        )
        assert session.scalars(select(Item)).all() == []
        assert _effects(session) == []

    @pytest.mark.parametrize(
        ("kind", "markdown", "fault"),
        [
            pytest.param(
                "decision",
                DECISION.replace(
                    "recommend: Dome\n",
                    "answer: Tunnel\nby: ada\nat: 2026-10-26T10:00:00Z\n",
                ),
                "line 10: block D1: `by: ada` is ada's answer, which the record"
                " does not hold",
                id="answered",
            ),
            pytest.param(
                "action",
                "# Pitch the tent\n\n```action id=A1\nby: ada\n"
                "done: 2026-10-26T10:00:00Z\n```\n",
                "line 4: block A1: `by: ada` is ada's answer, which the record"
                " does not hold",
                id="done",
            ),
        ],
    )
    def test_a_persons_answer_in_the_text_is_refused_and_nothing_minted(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
        kind: str,
        markdown: str,
        fault: str,
    ) -> None:
        run = _brain(session, project, environment)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).add_item(
                _admitted(run), _added(kind=kind, markdown=markdown), TOOL_USE_ID
            )

        assert refused.value.message == (
            f"Cannot add a {kind} item because its text holds faults: {fault}"
        )
        assert session.scalars(select(Item)).all() == []
        assert _effects(session) == []

    def test_the_agents_own_answer_in_the_text_is_born(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)

        added = _service(container).add_item(
            _admitted(run),
            _added(kind="document", markdown=SETTLED_PLAN),
            TOOL_USE_ID,
        )
        clear_after_commit_callbacks()

        assert _document_text(session, added.item) == SETTLED_PLAN

    @pytest.mark.parametrize(
        ("fields", "cause"),
        [
            pytest.param(
                {"kind": "question"},
                "it has no title: give `title`, or `markdown` that gives one",
                id="no-title-or-markdown",
            ),
            pytest.param(
                {
                    "kind": "question",
                    "title": "Which lake?",
                    "repo": REPO,
                    "brief": BRIEF,
                },
                "a question item takes no `repo`, `brief`",
                id="work-fields",
            ),
            pytest.param(
                {"kind": "card_wait", "title": "MD-8 done"},
                "Pilot takes no waits yet",
                id="card-wait",
            ),
            pytest.param(
                {"kind": "timed_wait", "title": "Tomorrow"},
                "Pilot takes no waits yet",
                id="timed-wait",
            ),
        ],
    )
    def test_an_item_its_kind_does_not_take_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        fields: dict[str, str],
        cause: str,
    ) -> None:
        run = _brain(session, project, environment)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).add_item(_admitted(run), _added(**fields), TOOL_USE_ID)

        assert refused.value.message == (
            f"Cannot add a {fields['kind']} item because {cause}"
        )
        assert session.scalars(select(Item)).all() == []


class TestPilotStoreServiceAddWork:
    def test_a_work_item_is_started_on_add_its_brief_followed_by_pilots_trailer(
        self,
        session: DbSession,
        container: ServiceContainer,
        starts: SessionStartService,
        project: Project,
        environment: Environment,
    ) -> None:
        opened = _opened(session, project)
        opened.autopilot = True
        session.add(_plan_task(opened, "badge"))
        container.document_service().bear_handbook(opened, "Badges are round.\n")
        run = _brain(session, opened, environment)

        added = _starting(container, starts).add_item(
            _admitted(run),
            _added(
                kind="work",
                title="Renaming the badge",
                repo=REPO,
                cwd="/work/Example",
                brief=BRIEF,
                step="badge",
                agent="reviewer",
                model="sonnet",
                reasoning_effort="high",
            ),
            TOOL_USE_ID,
        )
        clear_after_commit_callbacks()

        work = session.get_one(Work, added.item.id)
        started = session.get_one(models.Session, added.item.id)
        assert (added.path, added.state, added.held) == (None, "starting", None)
        assert (added.item.kind_code, added.item.title, added.item.plan_task_id) == (
            "work",
            "Renaming the badge",
            "badge",
        )
        assert (work.repo, work.autopilot) == (REPO, True)
        assert (
            started.state_code,
            started.cwd,
            started.agent,
            started.model,
            started.reasoning_effort,
        ) == (SessionState.STARTING, "/work/Example", "reviewer", "sonnet", "high")
        [turn] = session.scalars(select(Turn).where(Turn.session_id == started.id))
        assert turn.message == (
            "Rename the badge.\n\n"
            "From Pilot:\n"
            '- This work item serves plan task badge "The camp": write `step: badge`'
            " into the front matter of every document you register.\n"
            "- Auto pilot is on: the grants above hold for this session.\n"
            "- The project's handbook:\n"
            "Badges are round.\n"
        )
        assert added.line.label == "Work · Renaming the badge"
        [effect] = _effects(session)
        assert (effect.kind_code, effect.item_id) == (EffectKind.ADDED, added.item.id)

    @pytest.mark.parametrize(
        ("paused", "reason"),
        [(True, HeldReason.PAUSED), (False, HeldReason.CONTROLLER_UNREACHABLE)],
    )
    def test_a_start_the_gate_holds_answers_held_and_why(
        self,
        session: DbSession,
        container: ServiceContainer,
        starts: SessionStartService,
        controller_outage: ControllerOutage,
        project: Project,
        environment: Environment,
        paused: bool,
        reason: HeldReason,
    ) -> None:
        project.paused = paused
        session.flush()
        if not paused:
            controller_outage.call_unanswered()
        run = _brain(session, project, environment)

        added = _starting(container, starts).add_item(
            _admitted(run),
            _added(
                kind="work",
                title="Renaming the badge",
                repo=REPO,
                cwd="/work/Example",
                brief=BRIEF,
            ),
            TOOL_USE_ID,
        )
        clear_after_commit_callbacks()

        assert (added.state, added.held) == ("held", Held(reason))
        assert session.get_one(models.Session, added.item.id).state_code == (
            SessionState.HELD
        )

    def test_a_start_held_for_the_slot_answers_its_count(
        self,
        session: DbSession,
        container: ServiceContainer,
        starts: SessionStartService,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        service = _starting(container, starts)
        work = _added(
            kind="work",
            title="Renaming the badge",
            repo=REPO,
            cwd="/work/Example",
            brief=BRIEF,
        )
        service.add_item(_admitted(run), work, TOOL_USE_ID)

        added = service.add_item(_admitted(run), work, TOOL_USE_ID)
        clear_after_commit_callbacks()

        assert (added.state, added.held) == ("held", Held(HeldReason.SLOT, 1))

    @pytest.mark.parametrize(
        ("fields", "cause"),
        [
            pytest.param(
                {"title": "Renaming the badge", "repo": REPO},
                "a work item needs `cwd`, `brief`",
                id="missing",
            ),
            pytest.param(
                {
                    "title": "Renaming the badge",
                    "repo": REPO,
                    "cwd": "/work/Example",
                    "brief": BRIEF,
                    "markdown": "Rename it.\n",
                    "urgent": True,
                },
                "a work item takes no `markdown`, `urgent`",
                id="prose-fields",
            ),
        ],
    )
    def test_a_work_item_short_of_what_it_needs_or_with_prose_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        starts: SessionStartService,
        project: Project,
        environment: Environment,
        fields: dict[str, Any],
        cause: str,
    ) -> None:
        run = _brain(session, project, environment)

        with pytest.raises(InvalidOperationException) as refused:
            _starting(container, starts).add_item(
                _admitted(run), _added(kind="work", **fields), TOOL_USE_ID
            )

        assert refused.value.message == f"Cannot add a work item because {cause}"
        assert session.scalars(select(Item)).all() == []

    def test_a_task_not_in_the_plan_is_not_found_and_nothing_started(
        self,
        session: DbSession,
        container: ServiceContainer,
        starts: SessionStartService,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)

        with pytest.raises(RecordNotFoundException) as refused:
            _starting(container, starts).add_item(
                _admitted(run),
                _added(
                    kind="work",
                    title="Renaming the badge",
                    repo=REPO,
                    cwd="/work/Example",
                    brief=BRIEF,
                    step="nowhere",
                ),
                TOOL_USE_ID,
            )

        assert refused.value.message == f"Plan task {project.id}/nowhere was not found"
        assert session.scalars(select(Item)).all() == []

    def test_a_finished_project_refuses_the_start(
        self,
        session: DbSession,
        container: ServiceContainer,
        starts: SessionStartService,
        project: Project,
        environment: Environment,
    ) -> None:
        _opened(session, project).state_code = ProjectState.FINISHED
        session.flush()
        run = _brain(session, project, environment)

        with pytest.raises(InvalidOperationException) as refused:
            _starting(container, starts).add_item(
                _admitted(run),
                _added(
                    kind="work",
                    title="Renaming the badge",
                    repo=REPO,
                    cwd="/work/Example",
                    brief=BRIEF,
                ),
                TOOL_USE_ID,
            )

        assert refused.value.message == (
            f"Cannot place a work item of {REPO} because its project is finished"
        )
        assert _effects(session) == []

    def test_a_work_item_is_named_for_the_claimed_actions_it_does(
        self,
        session: DbSession,
        container: ServiceContainer,
        starts: SessionStartService,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment, "job")
        document = _registered(session, container, project, environment, CUT_OVER)

        added = _starting(container, starts).add_item(
            _admitted(run),
            _added(
                kind="work",
                title="Rotating the CI token",
                repo=REPO,
                cwd="/work/Example",
                brief=BRIEF,
                claims=[f"{document.id}/A1", f"{document.id}/A2"],
            ),
            TOOL_USE_ID,
        )
        clear_after_commit_callbacks()

        assert _claims(session) == [
            (added.item.id, _block(session, document, "A1").id),
            (added.item.id, _block(session, document, "A2").id),
        ]
        assert _block(session, document, "A1").answer == "Pilot does it"

    def test_a_retrys_work_item_names_the_block_again_the_earlier_kept(
        self,
        session: DbSession,
        container: ServiceContainer,
        starts: SessionStartService,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment, "job")
        document = _registered(session, container, project, environment, CUT_OVER)
        service = _starting(container, starts)

        def rotating(title: str) -> Item:
            return service.add_item(
                _admitted(run),
                _added(
                    kind="work",
                    title=title,
                    repo=REPO,
                    cwd="/work/Example",
                    brief=BRIEF,
                    claims=[f"{document.id}/A1"],
                ),
                TOOL_USE_ID,
            ).item

        first = rotating("Rotating the CI token and the runners")
        retry = rotating("Rotating the CI token")
        clear_after_commit_callbacks()

        a1 = _block(session, document, "A1").id
        assert sorted(_claims(session)) == sorted([(first.id, a1), (retry.id, a1)])
        assert session.execute(standing()).all() == [(a1, retry.id)]

    @pytest.mark.parametrize(
        ("claim", "refusal"),
        [
            pytest.param(
                "D1",
                InvalidOperationException,
                id="no-action",
            ),
            pytest.param("A9", RecordNotFoundException, id="no-block"),
        ],
    )
    def test_a_claim_the_record_refuses_starts_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        starts: SessionStartService,
        project: Project,
        environment: Environment,
        claim: str,
        refusal: type[Exception],
    ) -> None:
        run = _brain(session, project, environment, "job")
        document = _registered(session, container, project, environment, CUT_OVER)

        with pytest.raises(refusal):
            _starting(container, starts).add_item(
                _admitted(run),
                _added(
                    kind="work",
                    title="Rotating the CI token",
                    repo=REPO,
                    cwd="/work/Example",
                    brief=BRIEF,
                    claims=[f"{document.id}/{claim}"],
                ),
                TOOL_USE_ID,
            )

        assert session.scalars(select(Work)).all() == []
        assert _claims(session) == []
        assert _effects(session) == []

    def test_a_prose_item_takes_no_claims(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment, "job")
        document = _registered(session, container, project, environment, CUT_OVER)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).add_item(
                _admitted(run),
                _added(kind="notice", title="Rotating", claims=[f"{document.id}/A1"]),
                TOOL_USE_ID,
            )

        assert refused.value.message == (
            "Cannot add a notice item because a notice item takes no `claims`"
        )


def _claims(db: DbSession) -> list[tuple[uuid.UUID, int]]:
    """Every Claim Assignment, its Work's and its Block's ids."""
    return [
        (claim.work_id, claim.block_id)
        for claim in db.scalars(
            select(ClaimAssignment).order_by(
                ClaimAssignment.work_id, ClaimAssignment.block_id
            )
        )
    ]


class TestPilotStoreServiceAddItemAttachments:
    def test_attachments_made_and_outside_material_hang_in_their_order(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _elsewhere(fake_controller)
        run = _brain(session, project, environment)
        sketch = _bear(container, project, run, "notice", "Sketches", NOTICE)
        [made] = container.attach_service().attach(
            sketch,
            run,
            [copied("sketch.md", "/work/PilotProjects/sketch.md", b"# Sketch\n")],
            environment_id=environment.id,
        )

        added = _service(container).add_item(
            _admitted(run),
            _added(
                kind="decision",
                markdown=DECISION,
                attachments=[f"{ELSEWHERE}:{DESIGN}/README.md", str(made.id)],
            ),
            TOOL_USE_ID,
        )
        clear_after_commit_callbacks()

        copy, again = _attachments(session, added.item)
        assert again.id == made.id
        assert (
            copy.title,
            copy.filename,
            copy.source_environment_id,
            copy.source_path,
            copy.created_by_session_id,
        ) == ("The design", "README.md", ELSEWHERE, f"{DESIGN}/README.md", run.id)
        assert session.get(Environment, ELSEWHERE) is not None
        assert [
            (e.kind_code, e.item_id, e.attachment_id) for e in _effects(session)
        ] == [
            (EffectKind.ADDED, added.item.id, None),
            (EffectKind.ATTACHED, None, copy.id),
            (EffectKind.ATTACHED, None, made.id),
        ]
        assert added.line.label == "Decision · Which tent?"

    def test_an_attachment_of_another_project_is_not_found_and_nothing_minted(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        other = _other_project(session, person)
        theirs_run = _brain(session, other, environment, token="their-token")
        notice = _bear(container, other, theirs_run, "notice", "Theirs", NOTICE)
        [theirs] = container.attach_service().attach(
            notice,
            theirs_run,
            [copied("a.md", "/work/PilotProjects/a.md", b"A")],
            environment_id=environment.id,
        )
        run = _brain(session, project, environment)

        with pytest.raises(RecordNotFoundException) as refused:
            _service(container).add_item(
                _admitted(run),
                _added(kind="notice", markdown=NOTICE, attachments=[str(theirs.id)]),
                TOOL_USE_ID,
            )

        assert refused.value.message == f"Attachment {theirs.id} was not found"
        assert (
            session.scalars(select(Item).where(Item.project_id == project.id)).all()
            == []
        )

    def test_material_that_cannot_be_copied_is_refused_and_nothing_minted(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _elsewhere(fake_controller)
        run = _brain(session, project, environment)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).add_item(
                _admitted(run),
                _added(
                    kind="notice",
                    markdown=NOTICE,
                    attachments=[f"{ELSEWHERE}:{DESIGN}/gone.md"],
                ),
                TOOL_USE_ID,
            )

        assert refused.value.message == (
            "Cannot add a notice item because the controller answered 404"
            f" not-found: no such file or directory: '{DESIGN}/gone.md'"
        )
        assert session.scalars(select(Item)).all() == []
        assert session.scalars(select(Attachment)).all() == []


class TestPilotStoreServiceAddItemCaps:
    def test_sources_over_the_calls_cap_of_files_together_are_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        fake_controller.add_environment(ELSEWHERE)
        for number in range(MAX_CALL_FILES):
            fake_controller.put_file(ELSEWHERE, f"{DESIGN}/{number}.md", b"x")
        fake_controller.put_file(ELSEWHERE, "/work/Elsewhere/one.md", b"x")
        run = _brain(session, project, environment)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).add_item(
                _admitted(run),
                _added(
                    kind="notice",
                    markdown=NOTICE,
                    attachments=[
                        f"{ELSEWHERE}:{DESIGN}",
                        f"{ELSEWHERE}:/work/Elsewhere/one.md",
                    ],
                ),
                TOOL_USE_ID,
            )

        assert refused.value.cause == (
            f"its material is {MAX_CALL_FILES + 1} files, over the"
            f" {MAX_CALL_FILES}-file cap of one call"
        )
        assert session.scalars(select(Item)).all() == []

    def test_sources_over_the_calls_cap_of_bytes_together_are_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        fake_controller.add_environment(ELSEWHERE)
        for number in range(MAX_CALL_SIZE // FILE_SIZE_CAP):
            fake_controller.put_file(
                ELSEWHERE, f"{DESIGN}/{number}.bin", bytes(FILE_SIZE_CAP)
            )
        fake_controller.put_file(ELSEWHERE, "/work/Elsewhere/one.md", b"x")
        run = _brain(session, project, environment)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).add_item(
                _admitted(run),
                _added(
                    kind="notice",
                    markdown=NOTICE,
                    attachments=[
                        f"{ELSEWHERE}:{DESIGN}",
                        f"{ELSEWHERE}:/work/Elsewhere/one.md",
                    ],
                ),
                TOOL_USE_ID,
            )

        assert refused.value.cause == (
            f"its material is over the {MAX_CALL_SIZE}-byte cap of one call"
        )
        assert session.scalars(select(Attachment)).all() == []


class TestPilotStoreServiceAttachFile:
    def test_a_file_is_copied_from_its_environment_and_hung_on_to(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _elsewhere(fake_controller)
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "decision", "Which tent?", DECISION)

        attached = _service(container).attach_file(
            _admitted(run), f"{ELSEWHERE}:{DESIGN}/README.md", item.id, TOOL_USE_ID
        )
        clear_after_commit_callbacks()

        [attachment] = attached.attachments
        assert _attachments(session, item) == [attachment]
        assert (
            attachment.title,
            attachment.source_environment_id,
            attachment.source_path,
            attachment.created_by_session_id,
        ) == ("The design", ELSEWHERE, f"{DESIGN}/README.md", run.id)
        assert session.get_one(Environment, ELSEWHERE).name == "Elsewhere-1"
        assert (attached.line.verb, attached.line.label) == ("Attached", "The design")
        assert _effect_record(session, run)["effect"] == {
            "verb": "Attached",
            "label": "The design",
            "itemId": str(item.id),
        }
        [effect] = _effects(session)
        assert (effect.kind_code, effect.attachment_id) == (
            EffectKind.ATTACHED,
            attachment.id,
        )

    def test_a_folder_is_one_batch_one_attachment_per_file(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _elsewhere(fake_controller)
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "decision", "Which tent?", DECISION)

        attached = _service(container).attach_file(
            _admitted(run), f"{ELSEWHERE}:{DESIGN}", item.id, TOOL_USE_ID
        )
        clear_after_commit_callbacks()

        assert [
            (attachment.batch, attachment.filename)
            for attachment in attached.attachments
        ] == [(1, "README.md"), (1, "data/model.md")]
        assert attached.line.label == "design, 2 files"
        assert len(_effects(session)) == 2

    def test_without_to_it_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).attach_file(
                _admitted(run), f"{ELSEWHERE}:{DESIGN}", None, TOOL_USE_ID
            )

        assert refused.value.message == (
            f"Cannot attach {ELSEWHERE}:{DESIGN} because it names no item to hang"
            " on: give `to`"
        )

    def test_without_to_in_a_drafts_definition_chat_it_hangs_on_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _elsewhere(fake_controller)
        run = _chat(session, _brain(session, project, environment))

        attached = _service(container).attach_file(
            _admitted(run), f"{ELSEWHERE}:{DESIGN}", None, TOOL_USE_ID
        )
        clear_after_commit_callbacks()

        assert [
            (attachment.project_id, attachment.batch, attachment.filename)
            for attachment in attached.attachments
        ] == [(project.id, 1, "README.md"), (project.id, 1, "data/model.md")]
        assert session.scalars(select(ItemAttachment)).all() == []
        assert _effect_record(session, run)["effect"] == {
            "verb": "Attached",
            "label": "design, 2 files",
        }
        assert [
            (effect.kind_code, effect.attachment_id) for effect in _effects(session)
        ] == [
            (EffectKind.ATTACHED, attachment.id) for attachment in attached.attachments
        ]

    @pytest.mark.parametrize(
        "kind",
        [
            pytest.param(ChatKind.PROJECT, id="the project's chat"),
            pytest.param(ChatKind.DEFINITION, id="its definition chat past Create"),
        ],
    )
    def test_without_to_past_create_it_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        kind: ChatKind,
    ) -> None:
        run = _chat(session, _brain(session, project, environment), kind)
        _opened(session, project)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).attach_file(
                _admitted(run), f"{ELSEWHERE}:{DESIGN}", None, TOOL_USE_ID
            )

        assert refused.value.message.endswith("it names no item to hang on: give `to`")
        assert session.scalars(select(Attachment)).all() == []

    def test_a_to_of_another_project_is_not_found(
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
            _brain(session, other, environment, token="their-token"),
            "notice",
            "Theirs",
            NOTICE,
        )
        run = _brain(session, project, environment)

        with pytest.raises(RecordNotFoundException) as refused:
            _service(container).attach_file(
                _admitted(run), f"{ELSEWHERE}:{DESIGN}", theirs.id, TOOL_USE_ID
            )

        assert refused.value.message == f"Item {theirs.id} was not found"

    def test_an_environment_the_controller_does_not_have_is_not_found(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "notice", "The lake", NOTICE)

        with pytest.raises(RecordNotFoundException) as refused:
            _service(container).attach_file(
                _admitted(run), f"{ELSEWHERE}:{DESIGN}", item.id, TOOL_USE_ID
            )

        assert refused.value.message == f"Environment {ELSEWHERE} was not found"
        assert session.get(Environment, ELSEWHERE) is None

    def test_a_file_the_controller_refuses_is_refused_and_nothing_attached(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _elsewhere(fake_controller)
        run = _brain(session, project, environment)
        item = _bear(container, project, run, "notice", "The lake", NOTICE)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).attach_file(
                _admitted(run), f"{ELSEWHERE}:/etc/passwd", item.id, TOOL_USE_ID
            )

        assert refused.value.message == (
            f"Cannot attach {ELSEWHERE}:/etc/passwd because the controller answered"
            " 403 path-outside-work: the path is outside the environment's /work;"
            " '/etc/passwd' leaves /work; only absolute paths under /work are"
            " reachable"
        )
        assert session.scalars(select(Attachment)).all() == []
        assert _effects(session) == []
