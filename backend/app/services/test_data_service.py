"""The invented record: the dev stack's seed, which `cli load-test-data`
loads into the dev database and into the seed every Playwright worker clones,
and the people, environments, projects, items, agent saves and Pilot's marks
a spec or the dev stage's deployed check makes through `/api/testing/`
(TEST-6, D027).

Documents, attachments, the record's writes and the plan go through the
engine's own operations, so the seed is a record the engine could have
produced. The rows the engine does not write (people, projects with their
members and transitions, an environment and the session that added the items)
are written through the models. Every name and text in it is
invented: this repository is public.
"""

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine.attachments import AttachService, Copy
from app.engine.documents import DocumentService, Registration
from app.engine.ingest import Ingested, IngestService
from app.engine.paths import tree_path
from app.engine.plan import PlanService
from app.engine.record import WORK, RecordService
from app.engine.tree import TreeService
from app.engine.views import utc_time
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
    Environment,
    Item,
    PlanNote,
    PlanTask,
    Project,
    ProjectMember,
    ProjectTransition,
    Turn,
    User,
)
from app.models import Session as AgentSession
from app.models.reference import (
    AnswerChannel,
    DocumentRole,
    ProjectState,
    SessionState,
    TransitionKind,
    UserKind,
)
from app.schemas.testing_record import (
    InventedFileSchema,
    InventedProjectCreateSchema,
    InventedWriterQuestionSchema,
)
from app.services.auth_service import AuthContext
from app.services.people_service import PeopleService
from app.services.pilot_store_service import JOB, Brain, PilotStoreService
from app.services.pilot_work_service import PilotWorkService, Worker
from app.services.session_scope import STORE_REPO

SLUG = "recipe-box"
"""The open project's slug; the draft beside it has none."""

FINISHED_SLUG = "bike-log"
ARCHIVED_SLUG = "photo-album"

ENVIRONMENT_ID = "example-recipes-1"

GARDEN_DRAFT = """# Garden planner

A planting calendar for the allotment: what to sow when, and where each bed
stands in its rotation.

What should the calendar remind you of?

```question id=Q1
default: Sowing and watering
```
"""

RECIPE_DRAFT = """---
slug: recipe-box
---

# Recipe box

One shared box for the family's recipes, typed up from the old cards and
searchable on a phone in the kitchen.

## What it must do

- Show a recipe as a card, readable at arm's length.
- Find a recipe by its name or by what is in the fridge.
- Let each of us add recipes and fix them.
"""

HANDBOOK = """# Handbook

How the recipe box is worked on.

- The code is in the `recipe-box` repository; `main` deploys.
- A recipe is a Markdown file, one per card.
- Ask before deleting a recipe someone typed up.
"""

OPENING = """# Recipe box

Grandma's recipe cards are fading, and only one of us can read her
handwriting. Let's type them up into something we can all search and add to.
"""

DECISION = """---
step: build
summary: How a recipe card is laid out on a phone.
---

# Which layout for a recipe card?

The sketches are attached. Two columns fit a tablet; one column reads better
on a phone.

```decision id=D1
options:
  - One column: ingredients above the method
  - Two columns: ingredients beside the method
recommend: One column
```
"""

CONFIRMATION = """---
step: import
urgent: true
for: ada
---

# Delete the scanned duplicates?

Eleven cards were scanned twice. The duplicates take up space and confuse
the search.

```decision id=C1
type: confirmation
because: irreversible
proposal: Delete the eleven duplicate scans
```
"""

# `{at}` is the seed's run: Pilot's answers carry the clock's time.
QUESTION = """# Which units do the recipes use?

Grandma wrote ounces and cups; the newer cards use grams.

```question id=Q1
default: Both, as written
answer: Both, as written
by: agent
at: {at}
```
"""

ACTION = """---
step: import
---

# Put the card scanner on the kitchen desk

The import needs the scanner beside the card box for an afternoon.

```action id=A1
```
"""

NOTICE = """---
summary: The first twenty cards are typed up.
---

# Twenty cards typed up

The breakfast section is in the box: twenty recipes, each checked against
its card.
"""

IMPORT_PLAN = """---
step: import
summary: How the remaining cards get into the box.
---

# How to import the remaining cards

About two hundred cards are left, in six sections.

## Who types

```decision id=D1
options:
  - Everyone takes a section
  - One of us types, the others check
recommend: Everyone takes a section
```

## Faded cards

What to do with a card nobody can read at a glance?

```question id=Q1
default: Photograph it and type it later
```

## Card photos

```decision id=D2
options:
  - Keep the photo beside each recipe
  - Drop the photos once typed
```

## Print view

Should the box print a recipe as a card?

```question id=Q2
answer: deferred
to: plan
by: agent
at: {at}
```

## Sorting

Sort the cards into their six sections before anyone starts.

```action id=A1
```
"""

PHOTO_STORAGE = """---
step: model
summary: Where recipe photos live, and how big one may be.
---

# Storing recipe photos

```decision id=D1
options:
  - In the repository
  - In object storage
recommend: In object storage
```

How large may one photo be?

```question id=Q1
default: 2 MB
```

Create the bucket for the photos.

```action id=A1
```
"""

REVIEW = """---
step: build
summary: The recipe card page, ready for a read-through.
---

# Review the recipe card page

The card page follows the one-column layout. Read a few recipes on your
phone, in the kitchen, and say what is hard to read.
"""

SKETCHES = b"""# Layout sketches

One column: the ingredients, then the method, in one scroll.

Two columns: the ingredients on the left, the method on the right.
"""

TASKS = [
    ("scope", "Agree what the box must do", "done"),
    ("model", "Model recipes and photos", "done"),
    ("build", "Build the recipe card page", "in_progress"),
    ("import", "Import the old cards", "pending"),
    ("launch", "Hand the box to the family", "pending"),
]

REMOVED_TASK = ("spike", "Try a static site generator", "pending")

BIKES_DRAFT = """---
slug: bike-log
---

# Bike repair log

What was fixed on which bike, and when each chain was last oiled.
"""

BIKES_HANDBOOK = """# Handbook

- The code is in the `bike-log` repository.
"""

BIKES_OPENING = """# Bike repair log

The notebook in the shed is full. Let's keep the repairs somewhere we can
search.
"""

BIKES_TASKS = [
    ("page", "Build the log's page", "done"),
    ("notebook", "Type up the shed notebook", "done"),
]

ALBUM_DRAFT = """---
slug: photo-album
---

# Photo album

The scanned family photos, sorted by year and captioned.
"""

ALBUM_HANDBOOK = """# Handbook

- The code is in the `photo-album` repository.
"""

ALBUM_OPENING = """# Photo album

The scans sit in one folder with camera names. Let's sort them by year.
"""

ALBUM_TASKS = [
    ("sort", "Sort the scans by year", "in_progress"),
    ("caption", "Caption the photos", "pending"),
]

NOTICE_TEXT = "# {title}\n"
"""An open item a spec asks for: a notice, open until read."""

PASS_BRIEF = "An invented pre-ruling pass, made for a test."
"""The one Turn of the job's Session a spec's pass asks the writer in."""


class TestDataService:
    def __init__(
        self,
        db: Session,
        document_service: DocumentService,
        record_service: RecordService,
        plan_service: PlanService,
        people_service: PeopleService,
        ingest_service: IngestService,
        tree_service: TreeService,
        attach_service: AttachService,
        pilot_work_service: PilotWorkService,
        pilot_store_service: PilotStoreService,
    ) -> None:
        self.db = db
        self.document_service = document_service
        self.record_service = record_service
        self.plan_service = plan_service
        self.people_service = people_service
        self.ingest_service = ingest_service
        self.tree_service = tree_service
        self.attach_service = attach_service
        self.pilot_work_service = pilot_work_service
        self.pilot_store_service = pilot_store_service

    def load_all(self) -> dict[str, int]:
        """Seed the record into an empty database, in the caller's
        transaction, and return how many rows of each kind it holds."""
        # The transaction's time, the one the rows' server defaults take.
        now = self.db.scalar(select(func.now()))
        assert now is not None
        ada = self._person("ada", "Ada Example", 1)
        ben = self._person("ben", "Ben Example", 2)

        garden = self._project(ada, None, now)
        self.document_service.bear_draft(garden, GARDEN_DRAFT)

        recipes = self._project(ada, SLUG, now)
        self.db.add(ProjectMember(project_id=recipes.id, user_id=ben.id, joined_at=now))
        self._transitions(recipes, ada, now, TransitionKind.OPENED)
        self.document_service.bear_draft(recipes, RECIPE_DRAFT)
        self.document_service.bear_handbook(recipes, HANDBOOK)
        environment = Environment(id=ENVIRONMENT_ID, name="Recipes-1", exempt=False)
        self.db.add(environment)
        self.db.flush()
        session = AgentSession(
            project_id=recipes.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/RecipeBox",
            token_hash=hashlib.sha256(b"example recipe box session").hexdigest(),
            state_code=SessionState.IDLE,
            started_at=now,
        )
        self.db.add(session)
        self.db.flush()

        self._save_plan(recipes, "RB-12", "recipe-box", [*TASKS, REMOVED_TASK], {})

        stamp = utc_time(now)
        self.document_service.bear_opening(recipes, "Recipe box", ada, OPENING)
        decision = self._item(recipes, session, "decision", DECISION)
        self._item(recipes, session, "confirmation", CONFIRMATION)
        self._item(recipes, session, "question", QUESTION.format(at=stamp))
        action = self._item(recipes, session, "action", ACTION)
        notice = self._item(recipes, session, "notice", NOTICE)
        import_plan = self._item(
            recipes, session, "document", IMPORT_PLAN.format(at=stamp)
        )
        photo_storage = self._item(recipes, session, "document", PHOTO_STORAGE)
        self._item(recipes, session, "review", REVIEW)

        self.record_service.answer(self._document(decision), "D1", ben, "One column")
        self.record_service.done_action(
            self._document(action), "A1", ada, note="It is on the desk, plugged in."
        )
        self.record_service.read(notice, ada)
        self.record_service.answer(
            self._document(import_plan),
            "Q1",
            ada,
            "Photograph it; Ben reads most of them",
            via=AnswerChannel.CHAT,
        )
        self.record_service.answer(
            self._document(import_plan), "D2", ben, "deferred", to="launch"
        )
        self.record_service.done_action(self._document(photo_storage), "A1", ada)
        self.record_service.done(photo_storage, ada)

        self.attach_service.attach(
            decision,
            session,
            [
                Copy(
                    "Layout sketches",
                    "layout-sketches.md",
                    "text/markdown",
                    SKETCHES,
                    "/work/RecipeBox/notes/layout-sketches.md",
                )
            ],
            environment_id=environment.id,
        )

        self._save_plan(
            recipes,
            "RB-12",
            "recipe-box",
            TASKS,
            {
                "build": [
                    _note(
                        "card-layout",
                        "Cards are one column",
                        "Ben chose one column, the ingredients above the method.",
                        decision,
                        "D1",
                    )
                ],
                "launch": [
                    _note(
                        "card-photos",
                        "Keep the card photos or drop them, at the launch",
                        "Ben deferred whether a card's photo stays beside its recipe.",
                        import_plan,
                        "D2",
                    )
                ],
                None: [
                    _note(
                        "print-view",
                        "A print view is the plan's question",
                        "No task covers printing a recipe yet.",
                        import_plan,
                        "Q2",
                    )
                ],
            },
        )

        bikes = self._project(ben, FINISHED_SLUG, now)
        self.db.add(ProjectMember(project_id=bikes.id, user_id=ada.id, joined_at=now))
        self.document_service.bear_draft(bikes, BIKES_DRAFT)
        self.document_service.bear_handbook(bikes, BIKES_HANDBOOK)
        self.document_service.bear_opening(bikes, "Bike repair log", ben, BIKES_OPENING)
        self._save_plan(bikes, "BL-3", "bike-log", BIKES_TASKS, {})
        # Finish turns auto pilot off at its instant, by its person (DB 171).
        self._transitions(
            bikes,
            ben,
            now,
            TransitionKind.OPENED,
            TransitionKind.AUTOPILOT_ON,
            TransitionKind.FINISHED,
            TransitionKind.AUTOPILOT_OFF,
        )
        bikes.state_code = ProjectState.FINISHED

        album = self._project(ada, ARCHIVED_SLUG, now)
        self.document_service.bear_draft(album, ALBUM_DRAFT)
        self.document_service.bear_handbook(album, ALBUM_HANDBOOK)
        self.document_service.bear_opening(album, "Photo album", ada, ALBUM_OPENING)
        self._save_plan(album, "PA-1", "photo-album", ALBUM_TASKS, {})
        self._transitions(
            album, ada, now, TransitionKind.OPENED, TransitionKind.ARCHIVED
        )
        album.archived = True
        self.db.flush()

        return {
            "users": self._count(User, User.kind_code == UserKind.PERSON),
            "projects": self._count(Project),
            "items": self._count(Item),
            "documents": self._count(Document),
            "blocks": self._count(Block),
            "plan tasks": self._count(PlanTask),
            "plan notes": self._count(PlanNote),
            "attachments": self._count(Attachment),
        }

    def person(self, handle: str, name: str | None) -> User:
        """A person on the record as the handle step puts one, under a
        subject no one signs in with; the handle is the name without one.

        Raises:
            ValidationException: the handle is not lower-case letters, digits
                and hyphens.
            InvalidOperationException: the handle is Pilot's or another
                person's.
        """
        return self.people_service.choose_handle(
            AuthContext(
                subject=f"invented-{uuid.uuid4()}", email=None, name=name, roles=set()
            ),
            handle,
        )

    def environment(self, environment_id: str, name: str) -> Environment:
        """An environment Pilot has touched.

        Raises:
            ResourceConflictException: an environment has the id.
        """
        if self.db.get(Environment, environment_id) is not None:
            raise ResourceConflictException("Environment", environment_id)
        environment = Environment(id=environment_id, name=name, exempt=False)
        self.db.add(environment)
        self.db.flush()
        return environment

    def project(self, spec: InventedProjectCreateSchema) -> Project:
        """A project in the standing `spec` gives, made now by its first
        member: the transitions to that standing, its members in order, its
        draft titled by its name and its plan; past the draft, its handbook,
        born empty as Create project bears it (F129.2), and its opening, the
        first member's words verbatim, titled by its name; with an
        environment, a session there that adds its open items, notices.

        Raises:
            ValidationException: a finished project with auto pilot on, a
                paused project that is not open, a member named twice, open
                items without an environment, or a plan with a fault.
            RecordNotFoundException: a member is no person, or no environment
                has the id.
        """
        operation = "make the project"
        if spec.state is ProjectState.FINISHED and spec.autopilot:
            raise ValidationException(
                f"Cannot {operation} because a finished project has auto pilot off"
            )
        if spec.paused and spec.state is not ProjectState.OPEN:
            raise ValidationException(
                f"Cannot {operation} because only an open project is paused"
            )
        if len(set(spec.members)) < len(spec.members):
            raise ValidationException(
                f"Cannot {operation} because a member is named twice"
            )
        if spec.open_items and spec.environment_id is None:
            raise ValidationException(
                f"Cannot {operation} because its open items need a session's "
                "environment, and no environment_id is given"
            )
        people = [self._invented_member(handle) for handle in spec.members]
        environment = None
        if spec.environment_id is not None:
            environment = self.db.get(Environment, spec.environment_id)
            if environment is None:
                raise RecordNotFoundException("Environment", spec.environment_id)

        now = self.db.scalar(select(func.now()))
        assert now is not None
        project_id = uuid.uuid4()
        draft = spec.state is ProjectState.DRAFT
        project = Project(
            id=project_id,
            slug=None if draft else f"project-{project_id.hex[:12]}",
            state_code=spec.state,
            archived=spec.archived,
            autopilot=spec.autopilot,
            paused=spec.paused,
            created_by_user_id=people[0].id,
            created_at=now,
        )
        self.db.add(project)
        self.db.flush()
        for person in people:
            self.db.add(
                ProjectMember(project_id=project.id, user_id=person.id, joined_at=now)
            )
            # One flush each: at one instant, the ids keep the joining order.
            self.db.flush()
        kinds = [
            kind
            for kind, written in (
                (TransitionKind.OPENED, not draft),
                (TransitionKind.FINISHED, spec.state is ProjectState.FINISHED),
                (TransitionKind.AUTOPILOT_ON, spec.autopilot),
                (TransitionKind.PAUSED, spec.paused),
                (TransitionKind.ARCHIVED, spec.archived),
            )
            if written
        ]
        self._transitions(project, people[0], now, *kinds)
        self.document_service.bear_draft(
            project, "" if spec.name is None else f"# {spec.name}\n"
        )
        faults = self.plan_service.save(
            project,
            _plan_json(
                spec.ticket,
                spec.repo,
                [
                    {
                        "id": task.id,
                        "title": task.title,
                        "status": task.status.value,
                        "notes": [note.model_dump() for note in task.notes],
                    }
                    for task in spec.tasks
                ],
                [note.model_dump() for note in spec.notes],
            ),
        )
        if faults:
            raise ValidationException(
                f"Cannot {operation} because its plan has a fault: "
                + "; ".join(fault.message for fault in faults)
            )
        if not draft:
            self.document_service.bear_handbook(project)
            self.document_service.bear_opening(
                project,
                "New project" if spec.name is None else spec.name,
                people[0],
                spec.opening,
            )
        if environment is not None:
            session = self._session(project, environment, now)
            for number in range(1, spec.open_items + 1):
                title = f"Notice {number}"
                self.document_service.bear_item(
                    project, "notice", title, session, NOTICE_TEXT.format(title=title)
                )
        return project

    def item(self, project_id: uuid.UUID, kind: str, title: str, text: str) -> Item:
        """A prose item of `kind` the project's session adds with `title` and
        `text`, born through the engine's `bear_item`.

        Raises:
            RecordNotFoundException: no project has the id.
            InvalidOperationException: the project has no session, or the text
                holds a fault.
        """
        project = self.db.get(Project, project_id)
        if project is None:
            raise RecordNotFoundException("Project", str(project_id))
        session = self._session_of(project, f"add an item to project {project.id}")
        return self.document_service.bear_item(project, kind, title, session, text)

    def save(self, item_id: uuid.UUID, text: str) -> Ingested:
        """An agent's save of the item's file by the project's session, on the
        tree's current hash, through the ingest the store's sync calls: held
        on a fault, else merged and published.

        Raises:
            RecordNotFoundException: no item has the id, or its project is
                archived, so the store does not sync its file.
            InvalidOperationException: the project has no session.
        """
        item = self.db.get(Item, item_id)
        if item is None:
            raise RecordNotFoundException("Item", str(item_id))
        project = self.db.get_one(Project, item.project_id)
        document = self.db.get_one(Document, item.id)
        session = self._session_of(project, f"save item {item.id}")
        return self._ingest(project, document, session, text)

    def save_project_document(
        self, project_id: uuid.UUID, role: DocumentRole, text: str
    ) -> Ingested:
        """An agent's save of the project's draft or handbook by the project's
        session, on the tree's current hash, through the ingest the store's
        sync calls: held on a fault, else merged and published.

        Raises:
            RecordNotFoundException: no project has the id, it has no
                document of the role, as a draft has no handbook, or it is
                archived, so the store does not sync its file.
            InvalidOperationException: the project has no session.
        """
        project = self.db.get(Project, project_id)
        if project is None:
            raise RecordNotFoundException("Project", str(project_id))
        document = self.db.scalars(
            select(Document).where(
                Document.project_id == project.id, Document.role_code == role
            )
        ).one_or_none()
        if document is None:
            raise RecordNotFoundException(
                f"{role.value.capitalize()} of project", str(project.id)
            )
        session = self._session_of(
            project, f"save the {role.value} of project {project.id}"
        )
        return self._ingest(project, document, session, text)

    def mark_done(self, item_id: uuid.UUID) -> None:
        """Pilot's Done on a document it settled or deferred whole, by the
        project's session, as its `mark` takes it: a `done` Version cut and
        the item done by Pilot, its cause `settled` (F65.2, F86.3).

        Raises:
            RecordNotFoundException: no item has the id.
            InvalidOperationException: the project has no session, or the
                record refuses the Done: the item is no document, it is
                done, or a block of it is unanswered.
        """
        item = self.db.get(Item, item_id)
        if item is None:
            raise RecordNotFoundException("Item", str(item_id))
        project = self.db.get_one(Project, item.project_id)
        self._session_of(project, f"mark item {item.id} done")
        pilot = self.db.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).one()
        self.record_service.done(item, pilot)

    def end_turn(self, project_id: uuid.UUID) -> None:
        """The turn of the project's session ended, as the relay ends it for
        the documents: the writing columns of those it was saving cleared and
        told to the browsers, a `turn` Version cut of each whose published
        text moved since its last Version (design 1 §7).

        Raises:
            RecordNotFoundException: no project has the id.
            InvalidOperationException: the project has no session.
        """
        project = self.db.get(Project, project_id)
        if project is None:
            raise RecordNotFoundException("Project", str(project_id))
        session = self._session_of(project, f"end a turn of project {project.id}")
        self.document_service.turn_ended(session)

    def register_document(
        self, item_id: uuid.UUID, path: str, tool_use_id: str | None
    ) -> Registration:
        """The document the work item's session wrote at `path` in its
        environment, registered as its worker registers it (F85.1, ruling
        D1): the file read through the controller and parsed now, its text
        read at the end of its run; a minted one the call `tool_use_id`'s
        effect while the session's turn is in flight.

        Raises:
            RecordNotFoundException: no work item has the id.
            InvalidOperationException: its start has given its session no
                environment yet, or the file cannot be registered, as
                `PilotWorkService.register_document` refuses it.
            ExternalServiceException: the controller did not answer, or
                refused for a reason of its own.
        """
        worker = self._worker(item_id, f"register document {path}")
        return self.pilot_work_service.register_document(worker, path, tool_use_id)

    def attach_as_worker(
        self,
        item_id: uuid.UUID,
        path: str,
        to: uuid.UUID | None,
        tool_use_id: str | None,
    ) -> list[Attachment]:
        """The file or the folder the work item's session wrote at `path` in
        its environment, attached as its worker attaches it (F85.2): copied
        through the controller now and hung on the item `to` names, else on
        the work item, the call `tool_use_id`'s effect while the session's
        turn is in flight.

        Raises:
            RecordNotFoundException: no work item has the id, or `to` names no
                item of its project.
            InvalidOperationException: its start has given its session no
                environment yet, or a file cannot be copied, as
                `PilotWorkService.attach_file` refuses it.
            ExternalServiceException: the controller did not answer, or
                refused for a reason of its own.
        """
        worker = self._worker(item_id, f"attach {path}")
        return self.pilot_work_service.attach_file(worker, path, to, tool_use_id)

    def ask_writer(
        self, item_id: uuid.UUID, questions: Sequence[InventedWriterQuestionSchema]
    ) -> list[str]:
        """The pre-ruling pass's `questions` to the writer of the registered
        document, each about a block of it by its local id, asked as its
        `ask_writer` asks them (F86.8): in the one Turn of a job's Session of
        the item's project placed for the pass, the server's, ended once they
        are asked, the Session idle with nothing started.

        Returns:
            The local ids of the document's blocks its writer is asked about

        Raises:
            RecordNotFoundException: no item has the id, or its document has no
                such block.
            InvalidOperationException: the item is no registered document or
                is done, or a block is answered or was asked about already.
        """
        item = self.db.get(Item, item_id)
        if item is None:
            raise RecordNotFoundException("Item", str(item_id))
        now = self.db.scalar(select(func.now()))
        assert now is not None
        session = AgentSession(
            project_id=item.project_id,
            kind_code=JOB,
            cwd=STORE_REPO,
            token_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
            state_code=SessionState.RUNNING,
            turns=1,
            turn_started_at=now,
        )
        self.db.add(session)
        self.db.flush()
        turn = Turn(session_id=session.id, seq=1, message=PASS_BRIEF, started_at=now)
        self.db.add(turn)
        self.db.flush()
        brain = Brain(session.id, session.project_id, JOB)
        asked: list[str] = []
        for asking in questions:
            asked = self.pilot_store_service.ask_writer(
                brain, item.id, f"{item.id}/{asking.block}", asking.question
            )
        turn.ended_at = now
        session.state_code = SessionState.IDLE
        session.turn_ended_at = now
        self.db.flush()
        return asked

    def attach(
        self, item_id: uuid.UUID, files: Sequence[InventedFileSchema]
    ) -> list[Attachment]:
        """`files` hung on the item, copied from the session's working folder
        by the project's session in one call: one batch, the project's next,
        after the item's attachments.

        Raises:
            ValidationException: a file is over 16 MiB.
            RecordNotFoundException: no item has the id.
            InvalidOperationException: the project has no session.
        """
        item = self.db.get(Item, item_id)
        if item is None:
            raise RecordNotFoundException("Item", str(item_id))
        project = self.db.get_one(Project, item.project_id)
        session = self._session_of(project, f"attach files to item {item.id}")
        # A spec makes the project's sessions with an environment_id.
        assert session.environment_id is not None
        return self.attach_service.attach(
            item,
            session,
            [
                Copy(
                    file.title,
                    file.filename,
                    file.content_type,
                    file.content,
                    f"{session.cwd}/{file.filename}",
                )
                for file in files
            ],
            environment_id=session.environment_id,
        )

    def _ingest(
        self, project: Project, document: Document, session: AgentSession, text: str
    ) -> Ingested:
        return self.ingest_service.ingest(
            tree_path(project, document.path),
            text.encode(),
            self.tree_service.hash(project, document),
            self.db.get_one(Environment, session.environment_id),
            session,
        )

    def _worker(self, item_id: uuid.UUID, operation: str) -> Worker:
        """The work item's Session, as its bearer names it to `pilot-work`."""
        item = self.db.get(Item, item_id)
        if item is None or item.kind_code != WORK:
            raise RecordNotFoundException("Work item", str(item_id))
        session = self.db.get_one(AgentSession, item.id)
        if session.environment_id is None:
            raise InvalidOperationException(
                operation, f"work item {item.id} has no environment yet"
            )
        return Worker(session.id, session.project_id, session.environment_id, item.id)

    def _session_of(self, project: Project, operation: str) -> AgentSession:
        """The project's session started last."""
        session = self.db.scalars(
            select(AgentSession)
            .where(AgentSession.project_id == project.id)
            .order_by(AgentSession.started_at.desc().nulls_last(), AgentSession.id)
            .limit(1)
        ).first()
        if session is None:
            raise InvalidOperationException(
                operation,
                "the project has no session: make it with an environment_id",
            )
        return session

    def _invented_member(self, handle: str) -> User:
        person = self.db.scalars(
            select(User).where(User.handle == handle, User.kind_code == UserKind.PERSON)
        ).first()
        if person is None:
            raise RecordNotFoundException("Person", handle)
        return person

    def _session(
        self, project: Project, environment: Environment, now: datetime
    ) -> AgentSession:
        """An idle work session of `project` in `environment`."""
        session = AgentSession(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Invented",
            token_hash=hashlib.sha256(project.id.bytes).hexdigest(),
            state_code=SessionState.IDLE,
            started_at=now,
        )
        self.db.add(session)
        self.db.flush()
        return session

    def _transitions(
        self, project: Project, by: User, at: datetime, *kinds: TransitionKind
    ) -> None:
        """The transitions of `kinds`, in their order, at one instant."""
        for kind in kinds:
            self.db.add(
                ProjectTransition(
                    project_id=project.id, kind_code=kind, at=at, by_user_id=by.id
                )
            )
            # One flush each: at one instant, the ids keep `kinds`' order.
            self.db.flush()

    def _person(self, handle: str, name: str, avatar_slot: int) -> User:
        user = User(
            kind_code=UserKind.PERSON,
            subject=f"example-{handle}",
            handle=handle,
            name=name,
            email=f"{handle}@example.com",
            avatar_slot=avatar_slot,
        )
        self.db.add(user)
        self.db.flush()
        return user

    def _project(self, creator: User, slug: str | None, now: datetime) -> Project:
        """A project `creator` made at `now`, with the creator's membership
        (DB 156); open with `slug`, else a draft."""
        project = Project(
            slug=slug,
            state_code=ProjectState.DRAFT if slug is None else ProjectState.OPEN,
            created_by_user_id=creator.id,
            created_at=now,
        )
        self.db.add(project)
        self.db.flush()
        self.db.add(
            ProjectMember(project_id=project.id, user_id=creator.id, joined_at=now)
        )
        return project

    def _item(
        self, project: Project, session: AgentSession, kind: str, text: str
    ) -> Item:
        """A prose item `session` added, titled by its text's heading."""
        title = next(line[2:] for line in text.splitlines() if line.startswith("# "))
        return self.document_service.bear_item(project, kind, title, session, text)

    def _document(self, item: Item) -> Document:
        return self.db.get_one(Document, item.id)

    def _save_plan(
        self,
        project: Project,
        ticket: str,
        repo: str,
        tasks: list[tuple[str, str, str]],
        notes: dict[str | None, list[dict[str, Any]]],
    ) -> None:
        """Save `plan.json` as the agent would, `notes` by task id, the
        plan's own under none: a task left out is removed."""
        plan = _plan_json(
            ticket,
            repo,
            [
                {
                    "id": task_id,
                    "title": title,
                    "status": status,
                    "notes": notes.get(task_id, []),
                }
                for task_id, title, status in tasks
            ],
            notes.get(None, []),
        )
        faults = self.plan_service.save(project, plan)
        if faults:
            raise InvalidOperationException(
                f"seed the plan of project {project.slug}",
                "; ".join(fault.message for fault in faults),
            )

    def _count(self, model: Any, *where: Any) -> int:
        return (
            self.db.scalar(select(func.count()).select_from(model).where(*where)) or 0
        )


def _plan_json(
    ticket: str | None,
    repo: str | None,
    tasks: list[dict[str, Any]],
    notes: list[dict[str, Any]],
) -> bytes:
    """A save of `plan.json`: the ticket, the repo, the tasks with their
    notes, and the plan's own notes."""
    return json.dumps(
        {"ticket": ticket, "repo": repo, "tasks": tasks, "notes": notes}
    ).encode()


def _note(
    note_id: str, summary: str, content: str, item: Item, local_id: str
) -> dict[str, Any]:
    """An open note naming block `local_id` of `item` (TD §4.9)."""
    return {
        "id": note_id,
        "summary": summary,
        "content": content,
        "refs": [f"{item.id}/{local_id}"],
    }
