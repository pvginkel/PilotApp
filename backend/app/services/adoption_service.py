"""The adopted Project of a group of slices run before Pilot (F152.8; DB
decision 79 points 25 and 38; assertions 150, 170, 177, 582 and 584).

Pilot makes it the first time a publication names the group on a main
thread, and finds it again by the group's key. It is born archived by its
one `adopted` Project Transition, the stage's service user's as its creator
is, with no Project Member and no slug. Its one document is its draft,
`project.md`, which holds the group's name, its title, and its summary, and
nothing else: a group renamed, or summarised otherwise, has its Project's
draft published again as the group now stands, the Project's name with it.
Nothing removes one.

The writes of one group take turns under an advisory lock of the group's
key, so that two publications that first name a group at once make one
Project. A publication takes it after its conversation's turn
(`launch_placement.conversation_turn`), and nothing takes the two the other
way round.
"""

import uuid
from datetime import UTC, datetime

import pilot_dsl as dsl
from sqlalchemy import Integer, cast, func, literal, select
from sqlalchemy.orm import Session

from app.engine.bus import EngineBus, ProjectChanged
from app.engine.documents import DocumentService, listed
from app.exceptions import NoServiceUserException
from app.models import Document, Project, ProjectTransition, User
from app.models.reference import (
    DocumentRole,
    ProjectState,
    TransitionKind,
    UserKind,
)
from app.services.advisory_turn import turn_key

ADOPTION_LOCK = 253
"""The first key of a group's turn (`advisory_turn`); the second is drawn
from the group's key."""


def draft_text(name: str, summary: str) -> str:
    """An adopted Project's `project.md`: the group's name its title, in the
    front matter, and the group's summary its body."""
    text = dsl.with_title("", name)
    body = summary.strip()
    return f"{text}\n{body}\n" if body else text


def group_faults(name: str, summary: str) -> list[str]:
    """Why a group's name and summary make no `project.md` that holds them
    and nothing else, each in a line."""
    parsed = dsl.parse(draft_text(name, summary))
    found: list[str] = []
    if parsed.title != name or len(name.splitlines()) != 1:
        found.append(
            "the group's `name` is not one line of words with no space around them"
        )
    if parsed.blocks:
        found.append("the group's `summary` holds an ask")
    if parsed.faults:
        found.append(
            "the group's `summary` does not read as a document's text: "
            + listed(parsed.faults)
        )
    return found


class AdoptionService:
    def __init__(
        self, db: Session, document_service: DocumentService, engine_bus: EngineBus
    ) -> None:
        self.db = db
        self.document_service = document_service
        self.engine_bus = engine_bus

    def adopt(self, key: str, name: str, summary: str) -> uuid.UUID:
        """The id of the adopted Project of the group `key`, its
        `project.md` holding `name` and `summary`: made where no Project
        holds the group, else the one that does, its draft published again
        where the group's name or summary changed. The group's turn is held
        until the caller's transaction ends. `name` and `summary` have no
        fault (`group_faults`).

        Raises:
            NoServiceUserException: no Project holds the group and the stage
                has no service user; nothing is written.
        """
        self.db.execute(
            select(
                func.pg_advisory_xact_lock(
                    cast(literal(ADOPTION_LOCK), Integer),
                    cast(literal(turn_key(key.encode())), Integer),
                )
            )
        )
        text = draft_text(name, summary)
        project = self.db.scalars(
            select(Project).where(Project.adopted_group == key)
        ).one_or_none()
        if project is None:
            return self._bear(key, text).id
        draft = self.db.scalars(
            select(Document).where(
                Document.project_id == project.id,
                Document.role_code == DocumentRole.DRAFT,
            )
        ).one()
        if draft.published_text != text:
            self.document_service.publish(draft, text)
        return project.id

    def _bear(self, key: str, text: str) -> Project:
        """The group's adopted Project, born now by the stage's service
        user: the first made where the stage holds several."""
        service_user = self.db.scalars(
            select(User)
            .where(User.kind_code == UserKind.SERVICE)
            .order_by(User.created_at, User.id)
            .limit(1)
        ).one_or_none()
        if service_user is None:
            raise NoServiceUserException(key)
        at = datetime.now(UTC)
        project = Project(
            state_code=ProjectState.ADOPTED,
            archived=True,
            adopted_group=key,
            created_by_user_id=service_user.id,
            created_at=at,
        )
        self.db.add(project)
        self.db.flush()
        self.db.add(
            ProjectTransition(
                project_id=project.id,
                kind_code=TransitionKind.ADOPTED,
                at=at,
                by_user_id=service_user.id,
            )
        )
        self.db.flush()
        self.document_service.bear_draft(project, text)
        self.engine_bus.emit(ProjectChanged(project.id))
        return project
