"""A project's timeline as a screen draws it, and the items waiting on a
person (F8, F12, F13, F18, F31, F78, F1.4)."""

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app import models
from app.app_config import HaltSetting
from app.engine.paths import tree_path
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import (
    Attachment,
    Block,
    ClaimAssignment,
    ClarificationRun,
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
    SessionRecord,
    Turn,
    UsageReading,
    User,
    Wait,
    WaitFiring,
    WindowShare,
    Work,
    WriterQuestion,
)
from app.models.reference import (
    AnswerChannel,
    AttachmentSource,
    ChatKind,
    DocumentRole,
    EffectKind,
    ErrorKind,
    ProgressState,
    RecordKind,
    SessionState,
    TransitionKind,
    UsageWindow,
    VersionCause,
    WorkTrigger,
)
from app.schemas.pilot_work import ProgressStepRequestSchema, ProgressStepSchema
from app.schemas.testing_record import InventedFileSchema, InventedProjectCreateSchema
from app.schemas.timeline import (
    AttachmentSchema,
    DoneCauseCode,
    HeldReason,
    ItemKindCode,
    RetriedSchema,
    StopCause,
)
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.controller_outage import ControllerOutage
from app.services.effect_service import Change, EffectLine
from app.services.pilot_work_service import Worker
from app.services.relay_service import ENVIRONMENT_STOPPED
from app.services.session_record_service import SessionRecordService
from app.services.start_gate import WorkSlots
from app.services.timeline_service import Badge, work_status
from app.services.usage_halts import UsageHalts
from app.services.wait_service import ReportedTransition
from tests.support.chats import ChatWriter, open_chat
from tests.support.store_updates import hold, lift, stopped_job
from tests.support.turns import end_turns, turn_in_flight
from tests.support.working_on import Camp

ENVIRONMENT_CAUSES = [
    StopCause.ENVIRONMENT_STOPPED,
    StopCause.ENVIRONMENT_DELETING,
    StopCause.ENVIRONMENT_GONE,
    StopCause.ENVIRONMENT_ERROR,
]
"""The causes of a stop made elsewhere, which its `server` record holds."""

SLOTS = WorkSlots(work_max=3, project_max=3)
HALTS = UsageHalts(
    week_limit=0.9,
    week_allowance=0.05,
    week_second_limit=0.98,
    five_hour_limit=0.75,
    week_halt=HaltSetting.COOPERATIVE_STOP,
    five_hour_halt=HaltSetting.COOPERATIVE_STOP,
)
"""The slot of the defaults: the work items these tests place leave it room."""

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

CLAIM = "answer: Pilot does it\nby: agent\nat: 2026-10-12T09:30:00Z\n"

CLAIMED_ONLY = f"""```decision id=D1
options:
  - Dome
  - Tunnel
answer: Dome
by: agent
at: 2026-10-12T09:30:00Z
```

```action id=A1
{CLAIM}```

```action id=A2
{CLAIM}```
"""

CLAIMED_AND_OPEN = f"""```action id=A1
{CLAIM}```

```action id=A2
```
"""

SETTLED_BY_PILOT = """```decision id=D1
options:
  - Dome
  - Tunnel
answer: Dome
by: agent
at: 2026-10-12T09:30:00Z
```
"""

DONE_BY_PILOT = f"""```action id=A1
{CLAIM}```

```action id=A2
done: 2026-10-12T10:30:00Z
by: agent
note: Rotated
```
"""

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
    environment: Environment | None,
    state: SessionState = SessionState.IDLE,
) -> models.Session:
    """A work session of `project`, in `environment` or, while its start has
    provided none, in no environment."""
    run = models.Session(
        project_id=project.id,
        environment_id=None if environment is None else environment.id,
        kind_code="work",
        cwd="/work/Camp",
        token_hash=uuid.uuid4().hex * 2,
        state_code=state,
    )
    session.add(run)
    session.flush()
    return run


def _worker(work: Item, environment: Environment) -> Worker:
    """The work item's session, as its bearer names it to `pilot-work`."""
    return Worker(work.id, work.project_id, environment.id, work.id)


def _step(
    code: str, label: str, state: ProgressState | None = None
) -> ProgressStepRequestSchema:
    return ProgressStepRequestSchema(code=code, label=label, state=state)


def _work(
    session: DbSession,
    project: Project,
    environment: Environment | None,
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


def _job(
    session: DbSession,
    project: Project,
    environment: Environment,
    state: SessionState,
    created_at: datetime | None = None,
) -> Item:
    """The setup, a job of Pilot's own in the store, in `state`, created at
    `created_at` or now."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="job",
        cwd="/work/PilotProjects",
        token_hash=uuid.uuid4().hex * 2,
        state_code=state,
        created_at=created_at or datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    job = Item(
        id=run.id,
        project_id=project.id,
        seq=_next_seq(session, project),
        kind_code="work",
        title="Setting up the project",
        created_by_session_id=run.id,
    )
    session.add(job)
    session.flush()
    session.add(
        Work(
            id=run.id,
            project_id=project.id,
            session_kind_code="job",
            trigger_code=WorkTrigger.SETUP,
            autopilot=False,
        )
    )
    session.flush()
    return job


def _retried(session: DbSession, job: Item, retry: Item) -> None:
    session.get_one(Work, job.id).retried_by_id = retry.id
    session.flush()


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


def _stop_record(
    container: ServiceContainer,
    session: DbSession,
    run: models.Session,
    cause: StopCause,
) -> None:
    """The `server` record that ended the Session's turn 1, its environment
    stopped under it for `cause`."""
    turn = _turn(session, run, 1)
    SessionRecordService(
        session, container.session_stream_service(), container.view_service()
    ).append(
        run.id,
        RecordKind.SERVER,
        payload={"type": ENVIRONMENT_STOPPED, "cause": cause, "reason": "invented"},
        turn_id=turn.id,
    )
    session.flush()


def _hard_stopped(
    session: DbSession, project: Project, environment: Environment
) -> Item:
    """A work item a usage halt's hard stop stopped: by Pilot, its nudge owed
    (DB 269)."""
    stopped = _work(session, project, environment, SessionState.STOPPED)
    run = session.get_one(models.Session, stopped.id)
    run.stopped_at = run.nudge_owed_at = datetime(2026, 10, 24, 9, 5, tzinfo=UTC)
    run.stopped_by_user_id = _pilot(session).id
    session.flush()
    return stopped


def _halted_end(session: DbSession, project: Project, environment: Environment) -> Item:
    """A work item whose turn ended under a cooperative usage halt or its
    project's pause: `idle`, open, its nudge owed (DB 232)."""
    halted = _work(session, project, environment, SessionState.IDLE)
    run = session.get_one(models.Session, halted.id)
    run.nudge_owed_at = datetime(2026, 10, 24, 9, 5, tzinfo=UTC)
    session.flush()
    return halted


def _usage(session: DbSession, *, week: float, five_hour: float) -> None:
    """A fresh Usage Reading recorded now with these shares."""
    now = datetime.now(UTC)
    reading = UsageReading(taken_at=now, received_at=now, stale=False)
    session.add(reading)
    session.flush()
    session.add_all(
        WindowShare(
            reading_id=reading.id,
            window_code=window,
            share=share,
            resets_at=now + timedelta(days=1),
        )
        for window, share in (
            (UsageWindow.SEVEN_DAY, week),
            (UsageWindow.FIVE_HOUR, five_hour),
        )
    )
    session.flush()


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
    session.add(
        Wait(
            id=wait.id,
            kind_code="timed_wait",
            due_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
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
    """A clean save of the item's file by `run` in its turn, which it is then
    writing."""
    turn_in_flight(session, run)
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


ASKED = datetime(2026, 9, 24, 14, 2, tzinfo=UTC)
REPLIED = datetime(2026, 9, 24, 14, 21, tzinfo=UTC)


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
                    "in_chat": None,
                    "done": None,
                    "claim": None,
                    "held": None,
                    "deferral": None,
                    "writer_asked": False,
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
            "asks_under_autopilot": False,
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

        _opening, finished, _question = _items(container, project)
        with pytest.raises(InvalidOperationException) as refused:
            container.record_service().undo(item)
        transition(ADA, project.id, TransitionKind.REOPENED)
        _opening, reopened, _question = _items(container, project)

        assert finished["done"]["undo"] is False
        assert refused.value.cause == "the project is finished"
        assert item.done_cause_code == "answered"
        assert reopened["done"]["undo"] is True

    def test_finish_makes_a_done_line_of_every_item_but_the_opening_then_asks(
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

        opening, notice, question = timeline.model_dump(mode="json")["items"]
        assert opening["done"] is None
        assert (question["kind"], question["title"], question["done"]) == (
            "archive_question",
            "Archive the project?",
            None,
        )
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

    def test_a_registered_document_awaiting_its_read_has_no_text_and_says_so(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        work = _work(session, project, environment, SessionState.RUNNING)
        container.document_service().register(
            project,
            session.get_one(models.Session, work.id),
            "/work/Camp/docs/refinement.md",
        )

        _opening, _work_item, line = _items(container, project)

        assert (line["kind"], line["title"], line["file_name"]) == (
            "review",
            None,
            "refinement.md",
        )
        assert line["awaiting_read"] is True
        facts = ("body", "summary", "word_count", "read_minutes", "edited_at")
        assert [line[key] for key in facts] == [None] * 5
        assert (line["done"], line["concept"], line["writing"]) == (None, False, False)

    def _questioned(
        self, container: ServiceContainer, db: DbSession, environment: Environment
    ) -> tuple[Project, Item, models.Session]:
        """A registered document whose writer a pass asked about Q3 and then
        Q1, Q2 left unasked."""
        project = _make(container)
        run = _run(db, project, environment)
        container.record_service().place_work(project, run, "Writing the refinement")
        documents = container.document_service()
        item = documents.register(project, run, "/work/Camp/docs/refinement.md").item
        documents.publish_read(
            db.get_one(Document, item.id),
            "```question id=Q1\n```\n\n```question id=Q2\n```\n\n"
            "```question id=Q3\n```\n",
            run.id,
        )
        job = models.Session(
            project_id=project.id,
            kind_code="job",
            cwd="/work/PilotProjects",
            token_hash="9" * 64,
            state_code=SessionState.IDLE,
        )
        db.add(job)
        db.flush()
        container.record_service().place_work(
            project,
            job,
            "Pre-ruling docs/2",
            trigger=WorkTrigger.WORKER_TURN_ENDED,
            trigger_item_id=run.id,
        )
        turn = Turn(session_id=job.id, seq=1, message="Pre-rule.", started_at=ASKED)
        db.add(turn)
        db.flush()
        for local_id, question, at in (
            ("Q3", "Which lake?", ASKED),
            ("Q1", "Which site?", datetime(2026, 9, 24, 14, 3, tzinfo=UTC)),
        ):
            db.add(
                WriterQuestion(
                    turn_id=turn.id,
                    block_id=db.scalars(
                        select(Block.id).where(
                            Block.document_id == item.id, Block.local_id == local_id
                        )
                    ).one(),
                    question=question,
                    asked_at=at,
                )
            )
        db.flush()
        return project, item, job

    def _replied(
        self,
        container: ServiceContainer,
        db: DbSession,
        project: Project,
        environment: Environment,
        job: models.Session,
        reply: str,
    ) -> None:
        clarifying = _run(db, project, environment)
        container.record_service().place_work(
            project, clarifying, "Clarify refinement.md"
        )
        db.add(
            ClarificationRun(
                id=clarifying.id, pass_id=job.id, reply=reply, replied_at=REPLIED
            )
        )
        db.flush()

    def test_before_the_reply_its_clarification_holds_the_questions(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        """From the asking on, the document's clarification holds the
        questions, and each asked block says its writer was asked (DB 257)."""
        project, item, _ = self._questioned(container, session, environment)

        line = next(
            each for each in _items(container, project) if each["id"] == str(item.id)
        )

        assert line["clarifications"] == [
            {
                "asked_at": "2026-09-24T14:02:00Z",
                "questions": [
                    {
                        "block": "Q1",
                        "question": "Which site?",
                        "asked_at": "2026-09-24T14:03:00Z",
                        "heading": "## Q1",
                        "reply": None,
                    },
                    {
                        "block": "Q3",
                        "question": "Which lake?",
                        "asked_at": "2026-09-24T14:02:00Z",
                        "heading": "## Q3",
                        "reply": None,
                    },
                ],
                "reply": None,
                "replied_at": None,
                "split": False,
            }
        ]
        assert [
            (part["block"]["id"], part["block"]["writer_asked"])
            for part in line["body"]
            if part["type"] == "block"
        ] == [("Q1", True), ("Q2", False), ("Q3", True)]

    def test_a_reply_that_kept_the_headings_splits_per_block(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project, item, job = self._questioned(container, session, environment)
        reply = "## Q1\nThe north shore.\n\n## Q3\nLake Ilm."
        self._replied(container, session, project, environment, job, reply)

        line = next(
            each for each in _items(container, project) if each["id"] == str(item.id)
        )

        [clarification] = line["clarifications"]
        assert [each["reply"] for each in clarification["questions"]] == [
            "The north shore.",
            "Lake Ilm.",
        ]
        assert (
            clarification["reply"],
            clarification["replied_at"],
            clarification["split"],
        ) == (reply, "2026-09-24T14:21:00Z", True)
        document = container.timeline_service().item_document(item.id)
        assert (
            document.model_dump(mode="json")["clarifications"] == line["clarifications"]
        )

    def test_a_reply_that_did_not_keep_them_shows_whole(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project, item, job = self._questioned(container, session, environment)
        reply = "## Q1\nThe north shore, and the lake is Ilm."
        self._replied(container, session, project, environment, job, reply)

        line = next(
            each for each in _items(container, project) if each["id"] == str(item.id)
        )

        [clarification] = line["clarifications"]
        assert [each["reply"] for each in clarification["questions"]] == [
            "The north shore, and the lake is Ilm.",
            None,
        ]
        assert (clarification["reply"], clarification["split"]) == (reply, False)

    def test_an_item_whose_writer_was_asked_nothing_has_no_clarification(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        documents = container.document_service()
        item = documents.register(project, run, "/work/Camp/docs/survey.md").item
        documents.publish_read(
            session.get_one(Document, item.id), "```question id=Q1\n```\n", run.id
        )

        lines = _items(container, project)

        assert [line["clarifications"] for line in lines] == [[], []]
        [part] = [part for part in lines[1]["body"] if part["type"] == "block"]
        assert part["block"]["writer_asked"] is False

    def test_a_registered_document_whose_read_failed_has_no_text_and_awaits_nothing(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        # Ruling D1: its line keeps its file's name, and Reviewed closes it.
        project = _make(container)
        run = _run(session, project, environment)
        documents = container.document_service()
        item = documents.register(project, run, "/work/Camp/docs/refinement.md").item
        documents.fail_read(session.get_one(Document, item.id))

        _opening, line = _items(container, project)

        assert (line["kind"], line["title"], line["file_name"]) == (
            "review",
            None,
            "refinement.md",
        )
        assert (line["awaiting_read"], line["body"], line["done"]) == (
            False,
            None,
            None,
        )
        read = _read(container, item)
        assert (read["body"], read["awaiting_read"]) == (None, False)

    def test_no_item_but_a_registered_document_awaiting_its_read_awaits_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        person = session.scalars(select(User).where(User.handle == "ada")).one()
        documents = container.document_service()
        documents.bear_item(project, "notice", "Palette", run, "Blue.\n")
        closed = documents.register(project, run, "/work/Camp/docs/closed.md").item
        container.record_service().close_unanswered(project, person, datetime.now(UTC))
        _work(session, project, environment, SessionState.RUNNING)

        items = _items(container, project)

        assert [item["awaiting_read"] for item in items] == [False] * 4
        assert items[2]["id"] == str(closed.id)

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

    def test_a_save_after_its_turn_ended_is_edited_at_once_and_written_by_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        """Its own `turn` Version, cut at the save, gives the document its
        Edited time, and it shows no dots (P-103's ruling)."""
        project = _make(container)
        run = _run(session, project, environment)
        item = _bear(container, project, run, "notice", "Opens in May", NOTICE)
        turn_in_flight(session, run)
        end_turns(session, run)
        document = _document(session, item)

        container.ingest_service().ingest(
            tree_path(project, document.path),
            NOTICE_LATER.encode(),
            container.tree_service().hash(project, document),
            environment,
            run,
        )

        line = _items(container, project)[1]
        (turn,) = _versions(session, item, VersionCause.TURN)
        assert turn.session_id == run.id
        assert (line["writing"], datetime.fromisoformat(line["edited_at"])) == (
            False,
            turn.created_at,
        )

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
        assert timeline.unhung_attachments == []

    def test_a_drafts_material_hangs_on_no_item_by_batch_and_file_name(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container, state="draft", environment_id=environment.id)
        source = f"{environment.id}:{_session_of(session, project).cwd}"
        data = container.test_data_service()
        sketch, notes = data.attach_to_draft(
            project.id,
            [_file("sketch.md", b"# Sketch\n"), _file("notes.txt", b"Bring boots.")],
        )
        (photo,) = data.attach_to_draft(
            project.id, [_file("map.png", b"PNG", "image/png")]
        )

        timeline = container.timeline_service().timeline(project.id)

        assert timeline.items == []
        assert timeline.unhung_attachments == [
            _attachment(notes, "text/markdown", 12, 1, source),
            _attachment(sketch, "text/markdown", 9, 1, source),
            _attachment(photo, "image/png", 3, 2, source),
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
            "pilots_own": False,
            "held_reason": None,
            "held_running": None,
            "stopped_at": None,
            "stopped_by": None,
            "stopped_cause": None,
            "nudge_owed": False,
            "retried": None,
            "progress": [],
        }

    def test_a_job_is_pilots_own_work(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        """F26.3, F59.1: its line shows no environment chip and no Stop /
        Resume, though its session runs in the store."""
        project = _make(container)
        run = _run(session, project, environment, SessionState.RUNNING)
        run.kind_code = "job"
        session.flush()
        container.record_service().place_work(
            project, run, "Setting up the project", trigger=WorkTrigger.SETUP
        )
        _work(session, project, environment, SessionState.RUNNING)

        _opening, job, worker = container.timeline_service().timeline(project.id).items

        assert job.work is not None and worker.work is not None
        assert (job.work.pilots_own, worker.work.pilots_own) == (True, False)
        assert job.work.environment is not None

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


def _wait_run(
    container: ServiceContainer,
    session: DbSession,
    project: Project,
    wait: Item,
    state: SessionState,
) -> Work:
    """A run of `wait` in `state`, which took its pending firings."""
    job = models.Session(
        project_id=project.id,
        kind_code="job",
        cwd="/work/PilotProjects",
        token_hash=uuid.uuid4().hex * 2,
        state_code=state,
        turns=1,
    )
    session.add(job)
    session.flush()
    work = container.record_service().place_work(
        project,
        job,
        "Checking the wait",
        trigger=WorkTrigger.WAIT_FIRED,
        trigger_item_id=wait.id,
    )
    session.execute(
        update(WaitFiring)
        .where(WaitFiring.wait_id == wait.id, WaitFiring.job_id.is_(None))
        .values(job_id=work.id)
    )
    session.flush()
    return work


_NIGHT_SHIFT = ReportedTransition(
    card="SR-4",
    from_state="In Progress",
    to_state="Done",
    at=datetime(2026, 10, 12, 1, 12, tzinfo=UTC),
    by="pieter",
)


@pytest.mark.usefixtures("person")
class TestWaits:
    """A wait as its card, its line and its button draw it (F27)."""

    def test_a_card_wait_with_its_lists_its_firings_and_its_button(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        waits = container.wait_service()
        wait = waits.add_card_wait(
            project,
            run,
            "The night shift takes SR-1 and SR-4",
            ["SR-1", "SR-4"],
            ["Done", "Won't fix"],
            None,
        )
        assert waits.fire_transition(_NIGHT_SHIFT) == 1
        _wait_run(container, session, project, wait, SessionState.IDLE)
        waits.request(wait, person)

        _opening, entry, _run_line = _items(container, project)

        [first, second] = session.scalars(
            select(WaitFiring)
            .where(WaitFiring.wait_id == wait.id)
            .order_by(WaitFiring.seq)
        )
        assert (entry["created_at"], entry["done"]) == (
            wait.created_at.isoformat().replace("+00:00", "Z"),
            None,
        )
        assert entry["wait"] == {
            "cards": ["SR-1", "SR-4"],
            "states": ["Done", "Won't fix"],
            "due_at": None,
            "firings": [
                {
                    "seq": 1,
                    "cause": "transition",
                    "fired_at": _stamp(first.fired_at),
                    "transition": {
                        "card": "SR-4",
                        "from_state": "In Progress",
                        "to_state": "Done",
                        "at": "2026-10-12T01:12:00Z",
                        "by": "pieter",
                    },
                    "requested_by": None,
                    "outcome": "left_open",
                },
                {
                    "seq": 2,
                    "cause": "requested",
                    "fired_at": _stamp(second.fired_at),
                    "transition": None,
                    "requested_by": ADA_USER,
                    "outcome": "pilots_turn",
                },
            ],
            "request": {
                "label": "Check now",
                "open": False,
                "refusal": "Pilot is checking",
            },
            "note": None,
        }

    def test_a_timed_wait_with_its_due_time_and_its_button(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        due = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=7)
        container.wait_service().add_timed_wait(
            project, run, "ESO refreshes", due, None
        )

        _opening, entry = _items(container, project)

        assert entry["wait"] == {
            "cards": None,
            "states": None,
            "due_at": _stamp(due),
            "firings": [],
            "request": {"label": "Skip wait", "open": True, "refusal": None},
            "note": None,
        }

    def test_a_done_wait_has_the_note_its_close_wrote_and_takes_no_request(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        waits = container.wait_service()
        wait = waits.add_card_wait(
            project, run, "SR-4 is done", ["SR-4"], ["Done"], None
        )
        assert waits.fire_transition(_NIGHT_SHIFT) == 1
        work = _wait_run(container, session, project, wait, SessionState.RUNNING)
        note = "SR-4 read Done at 09:40; the rollout goes on"

        waits.close(
            project, session.get_one(Wait, wait.id), _pilot(session), work.id, note
        )

        _opening, entry, _run_line = _items(container, project)
        assert (entry["done"]["cause"], entry["done"]["by"], entry["done"]["undo"]) == (
            "marked",
            PILOT,
            False,
        )
        assert (
            entry["wait"]["note"],
            entry["wait"]["request"],
            [firing["outcome"] for firing in entry["wait"]["firings"]],
        ) == (
            note,
            {"label": "Check now", "open": False, "refusal": "the wait is done"},
            ["closed"],
        )

    def test_every_other_item_has_no_wait(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        _bear(container, project, run, "notice", "Bring boots", NOTICE)
        _work(session, project, environment, SessionState.RUNNING)

        assert [entry["wait"] for entry in _items(container, project)] == [None] * 3


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


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

        found = work_status(
            session,
            [work.id, no_work.id, notice.id, uuid.uuid4()],
            unreachable=False,
            halts=HALTS,
            slots=SLOTS,
        )

        assert list(found) == [work.id]
        assert found[work.id].state == SessionState.RUNNING

    def test_no_ids_read_nothing(self, session: DbSession) -> None:
        assert (
            work_status(session, [], unreachable=False, halts=HALTS, slots=SLOTS) == {}
        )

    def test_each_work_item_carries_its_own_steps_in_order(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        """F145.1: the list its session published, each step's code, label
        and state, in order; one that published none lists none."""
        project = _make(container)
        first, second, quiet = (
            _work(session, project, environment, SessionState.RUNNING) for _ in range(3)
        )
        publish = container.pilot_work_service().set_progress
        publish(
            _worker(first, environment),
            [
                _step("P1.code", "P1 · code", ProgressState.DONE),
                _step("test", "Test", ProgressState.ACTIVE),
                _step("docs", "Docs"),
            ],
        )
        publish(_worker(second, environment), [_step("write", "Write")])

        found = work_status(
            session,
            [first.id, second.id, quiet.id],
            unreachable=False,
            halts=HALTS,
            slots=SLOTS,
        )

        assert found[first.id].progress == [
            ProgressStepSchema(
                code="P1.code", label="P1 · code", state=ProgressState.DONE
            ),
            ProgressStepSchema(code="test", label="Test", state=ProgressState.ACTIVE),
            ProgressStepSchema(code="docs", label="Docs", state=ProgressState.PENDING),
        ]
        assert found[second.id].progress == [
            ProgressStepSchema(code="write", label="Write", state=ProgressState.PENDING)
        ]
        assert found[quiet.id].progress == []

    def test_a_list_emptied_lists_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        work = _work(session, project, environment, SessionState.RUNNING)
        publish = container.pilot_work_service().set_progress
        publish(_worker(work, environment), [_step("test", "Test")])

        publish(_worker(work, environment), [])

        assert container.timeline_service().work(work.id).progress == []

    def test_a_retried_job_names_the_job_its_retry_placed_and_the_press(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        """D2, the ruling on Q3: its line says it was retried, by which job;
        the retry's line is not retried."""
        project = _make(container)
        failed = _job(session, project, environment, SessionState.FAILED)
        pressed = datetime(2026, 10, 28, 9, 30, tzinfo=UTC)
        retry = _job(session, project, environment, SessionState.HELD, pressed)
        _retried(session, failed, retry)

        found = work_status(
            session, [failed.id, retry.id], unreachable=False, halts=HALTS, slots=SLOTS
        )

        assert found[failed.id].retried == RetriedSchema(id=retry.id, at=pressed)
        assert found[failed.id].state is SessionState.FAILED
        assert found[retry.id].retried is None

    @pytest.mark.parametrize(
        "state", [SessionState.HELD, SessionState.STOPPED, SessionState.FAILED]
    )
    def test_one_whose_start_provided_no_environment_yet_has_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        state: SessionState,
    ) -> None:
        """Held before its take, stopped there, or failed on a refused create
        (DB 107)."""
        project = _make(container)
        placed = _work(session, project, None, state)
        running = _work(session, project, environment, SessionState.RUNNING)

        found = work_status(
            session,
            [placed.id, running.id],
            unreachable=False,
            halts=HALTS,
            slots=SLOTS,
        )

        assert found[placed.id].state == state
        assert found[placed.id].environment is None
        assert found[running.id].environment is not None

    def test_the_env_chip_names_the_environment_as_its_row_stands(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        idle = _work(session, project, environment, SessionState.IDLE)
        environment.name = environment.id
        session.flush()

        found = work_status(
            session, [idle.id], unreachable=False, halts=HALTS, slots=SLOTS
        )[idle.id]

        assert found.environment is not None
        assert (found.environment.id, found.environment.name) == (
            environment.id,
            environment.id,
        )

    @pytest.mark.parametrize(
        ("work_max", "project_max", "running"),
        [
            # Across every project, or the project's own.
            (2, 3, 2),
            (3, 1, 1),
        ],
    )
    def test_a_held_one_waiting_for_a_slot_counts_the_work_items_that_fill_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        work_max: int,
        project_max: int,
        running: int,
    ) -> None:
        """F143.4: "Waiting for a slot · N running"."""
        project = _make(container)
        _work(session, project, environment, SessionState.RUNNING)
        _work(
            session, _make(container, name="Site"), environment, SessionState.STARTING
        )
        held = _work(session, project, environment, SessionState.HELD)

        found = work_status(
            session,
            [held.id],
            unreachable=False,
            halts=HALTS,
            slots=WorkSlots(work_max=work_max, project_max=project_max),
        )[held.id]

        assert (found.held_reason, found.held_running) == (HeldReason.SLOT, running)

    @pytest.mark.parametrize(
        ("paused", "unreachable", "reason"),
        [
            (True, False, HeldReason.PAUSED),
            (False, True, HeldReason.CONTROLLER_UNREACHABLE),
            (True, True, HeldReason.PAUSED),
            # The gate open, its release on the way.
            (False, False, None),
        ],
    )
    def test_a_held_one_says_why_the_gate_holds_it_as_it_reads_now(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        paused: bool,
        unreachable: bool,
        reason: HeldReason | None,
    ) -> None:
        project = _make(container)
        project.paused = paused
        held = _work(session, project, environment, SessionState.HELD)
        running = _work(session, project, environment, SessionState.RUNNING)

        found = work_status(
            session,
            [held.id, running.id],
            unreachable=unreachable,
            halts=HALTS,
            slots=SLOTS,
        )

        assert found[held.id].held_reason == reason
        assert found[held.id].held_running is None
        assert found[running.id].held_reason is None

    @pytest.mark.parametrize("by_a_person", [True, False])
    def test_a_stopped_one_says_when_and_by_whom(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
        by_a_person: bool,
    ) -> None:
        project = _make(container)
        stopped = _work(session, project, environment, SessionState.STOPPED)
        run = session.get_one(models.Session, stopped.id)
        run.stopped_at = datetime(2026, 10, 24, 9, 5, tzinfo=UTC)
        run.stopped_by_user_id = person.id if by_a_person else None
        session.flush()

        work = work_status(
            session, [stopped.id], unreachable=False, halts=HALTS, slots=SLOTS
        )[stopped.id]

        assert work.stopped_at == datetime(2026, 10, 24, 9, 5, tzinfo=UTC)
        assert (work.stopped_by is not None and work.stopped_by.handle) == (
            "ada" if by_a_person else False
        )

    def test_one_no_longer_stopped_says_nothing_of_its_last_stop(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        """A Resume keeps the stop's facts on the Session (DB s-15)."""
        project = _make(container)
        held = _work(session, project, environment, SessionState.HELD)
        run = session.get_one(models.Session, held.id)
        run.stopped_at = datetime(2026, 10, 24, 9, 5, tzinfo=UTC)
        run.stopped_by_user_id = person.id
        session.flush()

        work = work_status(
            session, [held.id], unreachable=False, halts=HALTS, slots=SLOTS
        )[held.id]

        assert (work.stopped_at, work.stopped_by) == (None, None)

    @pytest.mark.parametrize("cause", ENVIRONMENT_CAUSES)
    def test_one_its_environment_stopped_names_the_cause(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        cause: StopCause,
    ) -> None:
        project = _make(container)
        stopped = _work(session, project, environment, SessionState.STOPPED)
        run = session.get_one(models.Session, stopped.id)
        run.stopped_at = datetime(2026, 10, 24, 9, 5, tzinfo=UTC)
        _stop_record(container, session, run, cause)

        work = work_status(
            session, [stopped.id], unreachable=False, halts=HALTS, slots=SLOTS
        )[stopped.id]

        assert (work.stopped_cause, work.stopped_by) == (cause, None)

    def test_one_a_person_stopped_first_names_no_cause(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        """Its environment then stopped under the turn its Stop let run out."""
        project = _make(container)
        stopped = _work(session, project, environment, SessionState.STOPPED)
        run = session.get_one(models.Session, stopped.id)
        run.stopped_by_user_id = person.id
        _stop_record(container, session, run, StopCause.ENVIRONMENT_STOPPED)

        work = work_status(
            session, [stopped.id], unreachable=False, halts=HALTS, slots=SLOTS
        )[stopped.id]

        assert work.stopped_cause is None

    def test_one_interrupted_elsewhere_names_no_cause(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        """Its last record is its turn's `result`, after an earlier stop's."""
        project = _make(container)
        stopped = _work(session, project, environment, SessionState.STOPPED)
        run = session.get_one(models.Session, stopped.id)
        _stop_record(container, session, run, StopCause.ENVIRONMENT_GONE)
        turn = _turn(session, run, 2)
        SessionRecordService(
            session, container.session_stream_service(), container.view_service()
        ).append(
            run.id,
            RecordKind.RESULT,
            payload={"turn": 1, "interrupted": True},
            turn_id=turn.id,
            raw_offset=120,
            controller_session="claude-2",
        )

        work = work_status(
            session, [stopped.id], unreachable=False, halts=HALTS, slots=SLOTS
        )[stopped.id]

        assert work.stopped_cause is None

    def test_one_no_longer_stopped_names_no_cause(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        held = _work(session, project, environment, SessionState.HELD)
        run = session.get_one(models.Session, held.id)
        _stop_record(container, session, run, StopCause.ENVIRONMENT_STOPPED)

        work = work_status(
            session, [held.id], unreachable=False, halts=HALTS, slots=SLOTS
        )[held.id]

        assert work.stopped_cause is None

    @pytest.mark.parametrize(
        ("week", "five_hour", "cause"),
        [
            (0.95, 0.1, StopCause.WEEK_HALT),
            (0.5, 0.8, StopCause.FIVE_HOUR_HALT),
            (0.95, 0.8, StopCause.WEEK_HALT),
            (0.5, 0.1, StopCause.USAGE_LIMIT),
        ],
    )
    def test_one_the_hard_stop_stopped_names_the_halt_that_holds_now(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        week: float,
        five_hour: float,
        cause: StopCause,
    ) -> None:
        """Decision 66 keeps no cause: the window is read at display, the
        week's first, as a held start's is; neither once both lifted."""
        project = _make(container)
        stopped = _hard_stopped(session, project, environment)
        _usage(session, week=week, five_hour=five_hour)

        work = work_status(
            session, [stopped.id], unreachable=False, halts=HALTS, slots=SLOTS
        )[stopped.id]

        assert work.stopped_cause == cause
        assert work.stopped_by is not None
        assert (work.stopped_by.kind, work.stopped_by.handle) == ("agent", "agent")
        assert work.stopped_at == datetime(2026, 10, 24, 9, 5, tzinfo=UTC)

    def test_one_pilot_stopped_through_its_tool_names_no_cause(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        """The brain's `stop_work`: by Pilot, no nudge owed."""
        project = _make(container)
        stopped = _hard_stopped(session, project, environment)
        session.get_one(models.Session, stopped.id).nudge_owed_at = None
        _usage(session, week=0.95, five_hour=0.1)

        work = work_status(
            session, [stopped.id], unreachable=False, halts=HALTS, slots=SLOTS
        )[stopped.id]

        assert work.stopped_cause is None
        assert work.stopped_by is not None and work.stopped_by.kind == "agent"

    @pytest.mark.parametrize("lifted", [False, True], ids=["standing", "lifted"])
    def test_a_job_the_stores_update_stopped_names_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        lifted: bool,
    ) -> None:
        """By Pilot within the update, derived from its stop (DB 280); once
        lifted, its retry beside it."""
        project = _make(container)
        update = hold(session)
        job = stopped_job(container, session, project, datetime.now(UTC))
        if lifted:
            retry = _job(session, project, environment, SessionState.HELD)
            _retried(session, session.get_one(Item, job.id), retry)
            lift(session, update)

        work = work_status(
            session, [job.id], unreachable=False, halts=HALTS, slots=SLOTS
        )[job.id]

        assert work.stopped_cause == StopCause.STORE_UPDATE
        assert work.stopped_at == job.stopped_at
        assert work.stopped_by is not None and work.stopped_by.kind == "agent"
        assert (work.retried is not None) is lifted

    def test_a_job_pilot_stopped_outside_an_update_or_at_a_finish_names_no_cause(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        project = _make(container)
        before = stopped_job(container, session, project, datetime.now(UTC))
        update = hold(session)
        finished = stopped_job(container, session, project, datetime.now(UTC))
        line = session.get_one(Item, finished.id)
        line.done_at, line.done_cause_code = finished.stopped_at, "finished"
        lift(session, update)
        after = stopped_job(container, session, project, datetime.now(UTC))

        found = work_status(
            session,
            [before.id, finished.id, after.id],
            unreachable=False,
            halts=HALTS,
            slots=SLOTS,
        )

        assert [found[job.id].stopped_cause for job in (before, finished, after)] == [
            None,
            None,
            None,
        ]

    @pytest.mark.parametrize(
        ("week", "five_hour", "paused", "reason"),
        [
            (0.95, 0.1, False, HeldReason.WEEK_HALT),
            (0.5, 0.8, False, HeldReason.FIVE_HOUR_HALT),
            (0.95, 0.8, True, HeldReason.WEEK_HALT),
            (0.5, 0.1, True, HeldReason.PAUSED),
            (0.5, 0.1, False, None),
        ],
        ids=["the week's", "the five-hour", "a halt and the pause", "paused", "none"],
    )
    def test_one_ended_under_a_halt_or_the_pause_says_what_holds_its_nudge_now(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        week: float,
        five_hour: float,
        paused: bool,
        reason: HeldReason | None,
    ) -> None:
        """Decision 66 keeps no cause: read at display as a held start's
        halt and pause are, the halt first; neither the outage nor the slot
        holds a nudge, the gate's to hold once it is sent."""
        project = _make(container)
        project.paused = paused
        halted = _halted_end(session, project, environment)
        _usage(session, week=week, five_hour=five_hour)

        work = work_status(
            session, [halted.id], unreachable=True, halts=HALTS, slots=SLOTS
        )[halted.id]

        assert (work.state, work.nudge_owed) == (SessionState.IDLE, True)
        assert work.held_reason == reason
        assert work.held_running is None
        assert (work.stopped_at, work.stopped_cause) == (None, None)

    def test_only_a_nudge_owed_marks_a_work_item(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        """A done run's idle Session and a stop no halt made owe none; the
        hard stop's does."""
        project = _make(container)
        project.paused = True
        done = _work(
            session,
            project,
            environment,
            SessionState.IDLE,
            done_at=datetime.now(UTC),
            done_cause_code="turn_ended",
        )
        hard_stopped = _hard_stopped(session, project, environment)
        _usage(session, week=0.95, five_hour=0.1)

        found = work_status(
            session,
            [done.id, hard_stopped.id],
            unreachable=False,
            halts=HALTS,
            slots=SLOTS,
        )

        assert (found[done.id].nudge_owed, found[done.id].held_reason) == (
            False,
            None,
        )
        assert (
            found[hard_stopped.id].nudge_owed,
            found[hard_stopped.id].held_reason,
        ) == (True, None)

    @pytest.mark.parametrize("paused", [False, True], ids=["halted", "paused"])
    def test_one_finish_closed_while_its_nudge_was_owed_owes_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        paused: bool,
    ) -> None:
        """Its nudge never goes to a done item: its done line stands for it,
        as for any run done."""
        project = _make(container)
        project.paused = paused
        halted = _halted_end(session, project, environment)
        person = session.scalars(select(User).where(User.handle == "ada")).one()
        container.record_service().close_unanswered(project, person, datetime.now(UTC))
        _usage(session, week=0.95, five_hour=0.1)

        work = work_status(
            session, [halted.id], unreachable=False, halts=HALTS, slots=SLOTS
        )[halted.id]

        assert (work.state, work.nudge_owed, work.held_reason) == (
            SessionState.IDLE,
            False,
            None,
        )

    def test_the_service_reads_one_work_item(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        controller_outage: ControllerOutage,
    ) -> None:
        project = _make(container)
        held = _work(session, project, environment, SessionState.HELD)
        controller_outage.call_unanswered()

        work = container.timeline_service().work(held.id)

        assert (work.state, work.held_reason) == (
            SessionState.HELD,
            HeldReason.CONTROLLER_UNREACHABLE,
        )

    def test_the_service_finds_no_work_item_of_another_kind(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment, SessionState.RUNNING)

        with pytest.raises(RecordNotFoundException):
            container.timeline_service().work(run.id)

    def test_the_timeline_reads_the_outage_as_it_stands(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        controller_outage: ControllerOutage,
    ) -> None:
        project = _make(container)
        _work(session, project, environment, SessionState.HELD)
        controller_outage.call_unanswered()

        _opening, item = container.timeline_service().timeline(project.id).items

        assert item.work is not None
        assert item.work.held_reason == HeldReason.CONTROLLER_UNREACHABLE


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


KIT = """# Camp kit

```decision id=D1
options:
  - Dome
  - Tunnel
```

```decision id=D2
options:
  - Gas
  - Wood
```
"""


def _answered_in_chat(
    container: ServiceContainer,
    run: models.Session,
    document: Document,
    local_id: str,
    person: User,
    value: str,
) -> SessionRecord:
    """`person`'s answer `value` to the block, recorded as the brain's
    `answer` records it in the Turn of `run` in flight: through the chat,
    its Effect placed by a `server` record of `run`'s."""
    container.record_service().answer(
        document, local_id, person, value, via=AnswerChannel.CHAT, note="Said so."
    )
    block = (
        container.db_session()
        .scalars(
            select(Block).where(
                Block.document_id == document.id, Block.local_id == local_id
            )
        )
        .one()
    )
    record = container.effect_service().record(
        run.id,
        f"toolu-{uuid.uuid4().hex}",
        EffectLine("Answered", f"{local_id} · {value}"),
        [Change(EffectKind.ANSWERED, block_id=block.id)],
    )
    assert record is not None
    return record


def _registered(
    container: ServiceContainer,
    session: DbSession,
    project: Project,
    run: models.Session,
    name: str,
    text: str,
) -> Item:
    """A document `run` registered as `<name>.md`, read at its run's end."""
    documents = container.document_service()
    item = documents.register(project, run, f"/work/Camp/docs/{name}.md").item
    documents.publish_read(_document(session, item), text, run.id)
    return item


def _blocks(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The entry's blocks by their local ids."""
    return {
        part["block"]["id"]: part["block"]
        for part in entry["body"]
        if part["type"] == "block"
    }


@pytest.mark.usefixtures("person")
class TestClaims:
    """An action Pilot claimed and has not done, and the work item its latest
    naming gives it to, by its title and its address (F21.6; DB 260)."""

    def test_a_claimed_action_names_the_work_item_of_its_latest_naming(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        document = _registered(
            container, session, project, run, "cut-over", DONE_BY_PILOT
        )
        first = _work(session, project, environment, SessionState.FAILED)
        retry = _work(session, project, environment, SessionState.RUNNING)
        retry.title = "Rotating the CI token"
        blocks = {
            block.local_id: block.id
            for block in session.scalars(
                select(Block).where(Block.document_id == document.id)
            )
        }
        session.add_all(
            [
                ClaimAssignment(work_id=first.id, block_id=blocks["A1"]),
                ClaimAssignment(work_id=first.id, block_id=blocks["A2"]),
                ClaimAssignment(work_id=retry.id, block_id=blocks["A1"]),
            ]
        )
        session.flush()

        line = next(
            entry
            for entry in _items(container, project)
            if entry["id"] == str(document.id)
        )

        for read in (_blocks(line), _blocks(_read(container, document))):
            assert read["A1"]["claim"] == {
                "work": {"id": str(retry.id), "title": "Rotating the CI token"},
                "undone": False,
            }
            assert read["A1"]["answer"] == "Pilot does it"
            assert read["A2"]["claim"] is None

    def test_a_claim_no_work_item_is_named_for_names_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        run = _run(session, project, environment)
        document = _registered(
            container, session, project, run, "cut-over", CLAIMED_AND_OPEN
        )

        blocks = _blocks(_read(container, document))

        assert blocks["A1"]["claim"] == {"work": None, "undone": False}
        assert blocks["A2"]["claim"] is None


_PITCH = "# Where do we pitch?\n\n```question id=Q1\n```\n"
"""A question, the document's one block: what a research checks a fact for,
or what a run asks the person."""

_SURVEY = "# The survey\n\nNine of ten want the lake.\n"
"""A document with no block: a report."""

_CUT_OVER = """# The cut-over

```action id=A1
answer: Pilot does it
by: agent
at: 2026-11-02T09:00:00Z
```
"""
"""An action the pass claimed, the document's one block."""

_TWO_QUESTIONS = """# The trip

```question id=Q1
```

```question id=Q2
```
"""
"""Two questions: a research checks a fact for one of them."""


_CHECKLIST = """# Release checklist

## Push the tag

```action id=A1
answer: Pilot does it
by: agent
at: 2026-11-02T09:00:00Z
```

## Announce it

```action id=A2
```
"""
"""An action the pass claimed in its own section, beside one that waits on the
person."""


def _entry(camp: Camp, item: Item) -> dict[str, Any]:
    """The item's entry on its project's timeline."""
    return next(
        entry
        for entry in _items(camp.container, camp.project)
        if entry["id"] == str(item.id)
    )


def _link(item: Item | models.Session, title: str) -> dict[str, Any]:
    return {"id": str(item.id), "title": title}


def _pilots(
    doing: str,
    work: dict[str, Any] | None,
    pulse: bool,
    asked_in: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"doing": doing, "work": work, "pulse": pulse, "asked_in": asked_in}


class TestPilotsWork:
    """What Pilot does on an item that is Pilot's, the work its line goes to
    and whether it pulses, and per block what holds it and whether the
    hand-back left a claim undone (F13.7, F21.6, F31.7; DB 295, 296), as the
    reading reads them (`working_on`)."""

    @pytest.fixture
    def camp(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> Camp:
        return Camp(container, session)

    def test_a_registered_document_carries_its_read_awaited_then_its_pass(
        self, camp: Camp
    ) -> None:
        run = camp.worker()
        survey = camp.registered(run, read=False)
        building = _link(run, "Building the camp")

        assert _entry(camp, survey)["pilots_work"] == _pilots(
            "awaiting_run", building, False
        )

        camp.container.document_service().publish_read(
            camp.session.get_one(Document, survey.id), _SURVEY, run.id
        )
        camp.ended(run)
        job = camp.job_after(run, SessionState.HELD)

        assert _entry(camp, survey)["pilots_work"] == _pilots(
            "pre_ruling", _link(job, "Pre-ruling"), True
        )

        camp.ended(job)

        assert _entry(camp, survey)["pilots_work"] is None

    def test_while_its_pass_asks_the_writer_it_links_no_work(self, camp: Camp) -> None:
        run = camp.worker(conversation="conversation-1")
        pitch = camp.registered(run, _PITCH)
        camp.ended(run)
        job = camp.job_after(run)
        camp.ask_writer(job, pitch, "Q1")
        camp.ended(job)
        camp.clarification(job, run, SessionState.RUNNING)

        assert _entry(camp, pitch)["pilots_work"] == _pilots(
            "asking_writer", None, True
        )

    def test_a_held_claim_carries_its_hold_until_its_work_hands_it_back_undone(
        self, camp: Camp, person: User
    ) -> None:
        writer = camp.worker()
        cut_over = camp.registered(writer, _CUT_OVER)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        doing = camp.worker(conversation="conversation-2")
        camp.claim(cut_over, "A1", doing)
        building = _link(doing, "Building the camp")

        for read in (_entry(camp, cut_over), _read(camp.container, cut_over)):
            assert read["pilots_work"] == _pilots("doing", building, True)
            assert _blocks(read)["A1"]["held"] == {
                "doing": "doing",
                "work": building,
                "pulse": True,
                "asked_in": None,
            }
            assert _blocks(read)["A1"]["claim"] == {"work": building, "undone": False}

        camp.stopped(doing, by=person)

        for read in (_entry(camp, cut_over), _read(camp.container, cut_over)):
            assert read["pilots_work"] is None
            assert _blocks(read)["A1"]["held"] is None
            assert _blocks(read)["A1"]["claim"] == {"work": building, "undone": True}

    def test_while_the_run_waits_on_the_person_it_carries_the_document_they_answer(
        self, camp: Camp
    ) -> None:
        writer = camp.worker()
        cut_over = camp.registered(writer, _CUT_OVER)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        doing = camp.worker(conversation="conversation-2")
        camp.claim(cut_over, "A1", doing)
        question = camp.registered(doing, _PITCH)
        camp.ended(doing)
        camp.ended(camp.job_after(doing))
        building = _link(doing, "Building the camp")
        asked_in = _link(question, "Where do we pitch?")

        entry = _entry(camp, cut_over)

        assert entry["pilots_work"] == _pilots(
            "waiting_on_answer", building, False, asked_in
        )
        assert _blocks(entry)["A1"]["held"] == {
            "doing": "waiting_on_answer",
            "work": building,
            "pulse": False,
            "asked_in": asked_in,
        }
        assert _entry(camp, question)["pilots_work"] is None

    def test_a_researched_block_is_held_in_a_document_that_is_the_persons(
        self, camp: Camp
    ) -> None:
        writer = camp.worker()
        trip = camp.registered(writer, _TWO_QUESTIONS)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        checking = camp.worker(SessionState.IDLE, conversation="conversation-2")
        camp.research(trip, "Q1", checking)

        entry = _entry(camp, trip)

        assert entry["pilots_work"] is None
        assert {
            local_id: block["held"] for local_id, block in _blocks(entry).items()
        } == {
            "Q1": {
                "doing": "researching",
                "work": _link(checking, "Building the camp"),
                "pulse": False,
                "asked_in": None,
            },
            "Q2": None,
        }

    def test_a_document_of_a_run_that_waits_on_the_person_offers_its_cancel(
        self, camp: Camp
    ) -> None:
        writer = camp.worker()
        checklist = camp.registered(writer, _CHECKLIST)
        trip = camp.registered(writer, _TWO_QUESTIONS)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        doing = camp.worker(conversation="conversation-2")
        camp.claim(checklist, "A1", doing)
        camp.research(trip, "Q2", doing)
        question = camp.registered(doing, _PITCH)
        survey = camp.registered(doing, _SURVEY)
        camp.ended(doing)
        camp.ended(camp.job_after(doing))
        cancel = {
            "takes_back": [
                {
                    "document": _link(checklist, "Release checklist"),
                    "block": "A1",
                    "heading": "Push the tag",
                    "kind": "action",
                    "research": False,
                },
                {
                    "document": _link(trip, "The trip"),
                    "block": "Q2",
                    "heading": None,
                    "kind": "question",
                    "research": True,
                },
            ]
        }

        for read in (_entry(camp, question), _read(camp.container, question)):
            assert read["cancel"] == cancel
        assert _entry(camp, survey)["cancel"] == cancel
        assert _entry(camp, checklist)["cancel"] is None

        camp.container.item_service().cancel(ADA, survey.id)

        for each in (question, survey):
            entry = _entry(camp, each)
            assert entry["cancel"] is None
            assert entry["done"] == {
                "at": entry["done"]["at"],
                "cause": "cancelled",
                "by": ADA_USER,
                "undo": False,
            }
        blocks = _blocks(_entry(camp, checklist))
        assert blocks["A1"]["held"] is None
        assert blocks["A1"]["claim"] == {
            "work": _link(doing, "Building the camp"),
            "undone": True,
        }
        assert _blocks(_entry(camp, trip))["Q2"]["held"] is None

    def test_no_cancel_is_offered_while_the_run_goes_on(self, camp: Camp) -> None:
        writer = camp.worker()
        cut_over = camp.registered(writer, _CUT_OVER)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        doing = camp.worker(conversation="conversation-2")
        camp.claim(cut_over, "A1", doing)
        question = camp.registered(doing, _PITCH)
        survey = camp.registered(doing, _SURVEY)
        camp.ended(doing)
        pass_ = camp.job_after(doing)
        camp.ask_writer(pass_, question, "Q1")
        camp.ended(pass_)
        camp.clarification(pass_, doing)

        assert _entry(camp, survey)["pilots_work"] is None
        assert _entry(camp, survey)["cancel"] is None


@pytest.mark.usefixtures("person")
class TestInTheChat:
    """Where a block's answer given in the chat was recorded, which *In the
    chat* goes to (F42.3; DB Effect)."""

    def test_a_block_answered_in_the_chat_has_the_record_of_its_latest_answer(
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
            "document",
            "Camp kit",
            KIT,
        )
        chat = open_chat(session, project)
        writer = ChatWriter(session, container.session_record_service(), chat)
        writer.message(person, "Dome.")
        _answered_in_chat(
            container, chat, _document(session, item), "D1", person, "Dome"
        )
        writer.message(person, "Tunnel after all.")
        latest = _answered_in_chat(
            container, chat, _document(session, item), "D1", person, "Tunnel"
        )
        container.record_service().answer(_document(session, item), "D2", person, "Gas")

        blocks = _blocks(_items(container, project)[1])

        assert blocks["D1"]["via"] == "chat"
        assert blocks["D1"]["in_chat"] == {"chat": str(chat.id), "seq": latest.seq}
        assert (blocks["D2"]["via"], blocks["D2"]["in_chat"]) == ("app", None)

    def test_an_answer_from_the_app_after_the_chats_has_no_place_in_it(
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
            "document",
            "Camp kit",
            KIT,
        )
        chat = open_chat(session, project)
        ChatWriter(session, container.session_record_service(), chat).message(
            person, "Dome."
        )
        _answered_in_chat(
            container, chat, _document(session, item), "D1", person, "Dome"
        )
        container.record_service().answer(
            _document(session, item), "D1", person, "Tunnel"
        )

        block = _blocks(_items(container, project)[1])["D1"]

        assert (block["answer"], block["via"], block["in_chat"]) == (
            "Tunnel",
            "app",
            None,
        )

    def test_an_answer_whose_latest_effect_ran_in_no_chat_has_no_place_in_it(
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
            "document",
            "Camp kit",
            KIT,
        )
        chat = open_chat(session, project)
        ChatWriter(session, container.session_record_service(), chat).message(
            person, "Dome."
        )
        _answered_in_chat(
            container, chat, _document(session, item), "D1", person, "Dome"
        )
        job = models.Session(
            project_id=project.id,
            kind_code="job",
            cwd="/work/PilotProjects",
            token_hash=uuid.uuid4().hex * 2,
            state_code=SessionState.RUNNING,
        )
        session.add(job)
        session.flush()
        session.add(
            Turn(
                session_id=job.id,
                seq=1,
                message="Settle.",
                started_at=datetime.now(UTC),
            )
        )
        session.flush()
        _answered_in_chat(
            container, job, _document(session, item), "D1", person, "Tunnel"
        )

        block = _blocks(_items(container, project)[1])["D1"]

        assert (block["answer"], block["via"], block["in_chat"]) == (
            "Tunnel",
            "chat",
            None,
        )

    def test_the_item_document_carries_it_too(
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
        chat = open_chat(session, project)
        ChatWriter(session, container.session_record_service(), chat).message(
            person, "Tunnel."
        )
        record = _answered_in_chat(
            container, chat, _document(session, item), "D1", person, "Tunnel"
        )

        (block,) = _blocks(_read(container, item)).values()

        assert block["in_chat"] == {"chat": str(chat.id), "seq": record.seq}

    def test_a_drafts_block_answered_in_its_definition_chat_has_its_place(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        project = _make(container, state="draft", name="Camp")
        draft = session.scalars(
            select(Document).where(
                Document.project_id == project.id,
                Document.role_code == DocumentRole.DRAFT,
            )
        ).one()
        container.document_service().publish(draft, KIT)
        chat = open_chat(session, project, kind=ChatKind.DEFINITION)
        ChatWriter(session, container.session_record_service(), chat).message(
            person, "Tunnel."
        )
        record = _answered_in_chat(container, chat, draft, "D1", person, "Tunnel")

        body = container.timeline_service().project_document(
            project.id, DocumentRole.DRAFT
        )

        blocks = _blocks(body.model_dump(mode="json"))
        assert blocks["D1"]["in_chat"] == {"chat": str(chat.id), "seq": record.seq}
        assert blocks["D2"]["in_chat"] is None


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

    def test_a_registered_document_awaiting_its_read_reads_with_no_body(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        project = _make(container)
        work = _work(session, project, environment, SessionState.RUNNING)
        item = (
            container.document_service()
            .register(
                project,
                session.get_one(models.Session, work.id),
                "/work/Camp/docs/refinement.md",
            )
            .item
        )

        read = _read(container, item)

        assert read == {**_items(container, project)[2], "project_id": str(project.id)}
        assert (read["body"], read["awaiting_read"]) == (None, True)

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

    def test_a_registered_document_waits_only_once_every_read_of_its_run_is_made(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        # None takes a close before its turn-end read (review 7), and the
        # pass over them all is placed with the run's last.
        project = _make(container)
        run = _run(session, project, environment)
        documents = container.document_service()
        awaiting, read, failed = (
            documents.register(project, run, f"/work/Camp/docs/{name}.md").item
            for name in ("awaiting", "read", "failed")
        )
        assert self._badges(container, person, project) == {}

        documents.publish_read(_document(session, read), "Read me.\n", run.id)
        documents.fail_read(_document(session, failed))

        assert self._badges(container, person, project) == {}

        documents.publish_read(_document(session, awaiting), "Read me.\n", run.id)

        assert self._badges(container, person, project) == {project.id: Badge(3, False)}

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

    def test_a_stopped_or_failed_work_item_waits_and_a_running_or_held_one_does_not(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        project = _make(container)
        _work(session, project, environment, SessionState.STOPPED, urgent=True)
        _work(session, project, environment, SessionState.FAILED)
        for state in (
            SessionState.RUNNING,
            SessionState.IDLE,
            SessionState.STARTING,
            # A held start waits on nobody (UC; F141.5).
            SessionState.HELD,
        ):
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

    def test_a_work_item_the_hard_stop_stopped_waits_on_no_one(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        """DB 225, 269: its nudge resumes it; one Pilot stopped through its
        tool, no nudge owed, waits."""
        project = _make(container)
        _hard_stopped(session, project, environment)
        assert self._badges(container, person, project) == {}

        tooled = _hard_stopped(session, project, environment)
        session.get_one(models.Session, tooled.id).nudge_owed_at = None
        session.flush()
        assert self._badges(container, person, project) == {project.id: Badge(1, False)}

    def test_a_work_item_or_a_job_dead_at_the_quota_wall_waits_on_no_one(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        """DB 225, 232 (V25): while its nudge is owed; once a reading decides
        the wall missed, it waits on the person as any failed one."""
        project = _make(container)
        walled = [
            _work(session, project, environment, SessionState.FAILED),
            _job(session, project, environment, SessionState.FAILED),
        ]
        for item in walled:
            session.get_one(models.Session, item.id).nudge_owed_at = datetime(
                2026, 10, 30, 9, 5, tzinfo=UTC
            )
        session.flush()
        assert self._badges(container, person, project) == {}
        assert [
            work.nudge_owed
            for work in work_status(
                session,
                [item.id for item in walled],
                unreachable=False,
                halts=HALTS,
                slots=SLOTS,
            ).values()
        ] == [True, True]

        for item in walled:
            session.get_one(models.Session, item.id).nudge_owed_at = None
        session.flush()
        assert self._badges(container, person, project) == {project.id: Badge(2, False)}

    def test_a_work_item_ended_under_a_halt_or_the_pause_waits_on_no_one(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        """DB 232: open, its nudge carries it on once nothing holds it."""
        project = _make(container)
        project.paused = True
        _halted_end(session, project, environment)

        assert self._badges(container, person, project) == {}

    def test_a_failed_or_stopped_job_waits_until_it_is_retried(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        """D2: the badge counts the job until its Retry, so a stall shows;
        then its retry, once it fails in turn."""
        project = _make(container)
        failed = _job(session, project, environment, SessionState.FAILED)
        _job(session, project, environment, SessionState.STOPPED)
        assert self._badges(container, person, project) == {project.id: Badge(2, False)}

        retry = _job(session, project, environment, SessionState.HELD)
        _retried(session, failed, retry)
        assert self._badges(container, person, project) == {project.id: Badge(1, False)}

        session.get_one(models.Session, retry.id).state_code = SessionState.FAILED
        session.flush()
        assert self._badges(container, person, project) == {project.id: Badge(2, False)}

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

    def test_a_document_waits_unless_a_run_holds_its_every_open_block(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        """A claim is the person's but while a run holds it (DB 262, 296):
        `held` counts no document whose open blocks are all held, and every
        other, a claim no work item is named for among them (P-106)."""
        project = _make(container)
        run = _run(session, project, environment)
        held = _registered(container, session, project, run, "held", CLAIMED_ONLY)
        _registered(container, session, project, run, "claimed", CLAIMED_ONLY)
        another = _registered(
            container, session, project, run, "another", CLAIMED_AND_OPEN
        )
        _registered(container, session, project, run, "settled", SETTLED_BY_PILOT)
        doing = _work(session, project, environment, SessionState.RUNNING)
        session.add_all(
            ClaimAssignment(work_id=doing.id, block_id=block.id)
            for block in session.scalars(
                select(Block).where(
                    Block.document_id.in_([held.id, another.id]),
                    Block.local_id.in_(["A1", "A2"]),
                )
            )
        )
        session.flush()

        assert self._badges(container, person, project) == {project.id: Badge(3, False)}

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
