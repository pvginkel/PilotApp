"""The dev stack's seed: an invented record, which `cli load-test-data` loads
into the dev database and into the seed every Playwright worker clones.

Documents, the record's writes and the plan go through the engine's own
operations, so the seed is a record the engine could have produced. The rows
the engine does not write (people, projects with their members and
transitions, an environment and the session that added the items, an
attachment) are written through the models. Every name and text in it is
invented: this repository is public.
"""

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine.documents import DocumentService
from app.engine.plan import PlanService
from app.engine.record import RecordService
from app.engine.views import utc_time
from app.exceptions import InvalidOperationException
from app.models import (
    Attachment,
    Block,
    Document,
    Environment,
    Item,
    ItemAttachment,
    PlanNote,
    PlanTask,
    Project,
    ProjectMember,
    ProjectTransition,
    User,
)
from app.models import Session as AgentSession
from app.models.reference import (
    AnswerChannel,
    AttachmentSource,
    ProjectState,
    SessionState,
    TransitionKind,
    UserKind,
)

SLUG = "recipe-box"
"""The open project's slug; the draft beside it has none."""

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


class TestDataService:
    def __init__(
        self,
        db: Session,
        document_service: DocumentService,
        record_service: RecordService,
        plan_service: PlanService,
    ) -> None:
        self.db = db
        self.document_service = document_service
        self.record_service = record_service
        self.plan_service = plan_service

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
        self.db.add_all(
            [
                ProjectMember(project_id=recipes.id, user_id=ben.id, joined_at=now),
                ProjectTransition(
                    project_id=recipes.id,
                    kind_code=TransitionKind.OPENED,
                    at=now,
                    by_user_id=ada.id,
                ),
            ]
        )
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

        self._save_plan(recipes, [*TASKS, REMOVED_TASK], {})

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

        self._attach(decision, session, environment, now)

        self._save_plan(
            recipes,
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

    def _attach(
        self,
        item: Item,
        session: AgentSession,
        environment: Environment,
        now: datetime,
    ) -> None:
        """The layout sketches, a file of `session`'s, hung on `item`."""
        attachment = Attachment(
            project_id=item.project_id,
            batch=1,
            title="Layout sketches",
            filename="layout-sketches.md",
            content_type="text/markdown",
            size=len(SKETCHES),
            sha256=hashlib.sha256(SKETCHES).hexdigest(),
            content=SKETCHES,
            source_code=AttachmentSource.FILE,
            source_environment_id=environment.id,
            source_path="/work/RecipeBox/notes/layout-sketches.md",
            copied_at=now,
            created_by_session_id=session.id,
        )
        self.db.add(attachment)
        self.db.flush()
        self.db.add(
            ItemAttachment(
                item_id=item.id,
                attachment_id=attachment.id,
                position=1,
                attached_at=now,
            )
        )
        self.db.flush()

    def _save_plan(
        self,
        project: Project,
        tasks: list[tuple[str, str, str]],
        notes: dict[str | None, list[dict[str, Any]]],
    ) -> None:
        """Save `plan.json` as the agent would, `notes` by task id, the
        plan's own under none: a task left out is removed."""
        plan = {
            "ticket": "RB-12",
            "repo": "recipe-box",
            "tasks": [
                {
                    "id": task_id,
                    "title": title,
                    "status": status,
                    "notes": notes.get(task_id, []),
                }
                for task_id, title, status in tasks
            ],
            "notes": notes.get(None, []),
        }
        faults = self.plan_service.save(project, json.dumps(plan).encode())
        if faults:
            raise InvalidOperationException(
                f"seed the plan of project {project.slug}",
                "; ".join(fault.message for fault in faults),
            )

    def _count(self, model: Any, *where: Any) -> int:
        return (
            self.db.scalar(select(func.count()).select_from(model).where(*where)) or 0
        )


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
