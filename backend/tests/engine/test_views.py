"""The read-only views: `reference.json` and `timeline.json`, their shapes
pinned, each with its hash computed on render."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged, TreeHashMoved
from app.engine.views import READONLY, Rendering
from app.models import (
    Attachment,
    Document,
    Environment,
    Item,
    ItemAttachment,
    PlanTask,
    Project,
    User,
)
from app.models.reference import AttachmentSource, ProjectState, TaskStatus
from app.services.container import ServiceContainer

_CONTENT = b"# Palette\n\nThe two colours compared.\n"


def _json(rendering: Rendering) -> Any:
    """The view's data, after checking its text is the data's one rendering
    and its hash that text's."""
    data = json.loads(rendering.text)
    assert rendering.text == json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    assert rendering.hash == hashlib.sha256(rendering.text.encode()).hexdigest()
    return data


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 12, hour, minute, tzinfo=UTC)


def _attachment(
    project: Project, batch: int, filename: str, **values: Any
) -> Attachment:
    return Attachment(
        project_id=project.id,
        batch=batch,
        title="Palette",
        filename=filename,
        content_type="text/markdown",
        size=len(_CONTENT),
        sha256=hashlib.sha256(_CONTENT).hexdigest(),
        content=_CONTENT,
        copied_at=_at(9),
        **values,
    )


class TestViewService:
    def test_reference_lists_decision_34s_values(
        self, container: ServiceContainer
    ) -> None:
        assert _json(container.view_service().reference()) == {
            "readonly": READONLY,
            "confirmation_reasons": [
                {
                    "code": "auto-pilot-off",
                    "name": "Auto pilot off",
                    "description": (
                        "A granted act (a push that deploys, a prd apply or"
                        " promotion, an operator action Pilot can run), asked"
                        " only while auto pilot is off."
                    ),
                    "asks_under_autopilot": False,
                },
                {
                    "code": "irreversible",
                    "name": "Irreversible",
                    "description": (
                        "An irreversible act, of the kept column: asked under"
                        " auto pilot too."
                    ),
                    "asks_under_autopilot": True,
                },
                {
                    "code": "product-hold",
                    "name": "Product hold",
                    "description": (
                        "A product hold, of the kept column: asked under auto pilot too."
                    ),
                    "asks_under_autopilot": True,
                },
                {
                    "code": "rider",
                    "name": "Rider",
                    "description": (
                        "A push with riders, other commits going out with it,"
                        " asked only while auto pilot is off."
                    ),
                    "asks_under_autopilot": False,
                },
                {
                    "code": "self-approval",
                    "name": "Self-approval",
                    "description": (
                        "Self-approval, of the kept column: asked under auto pilot too."
                    ),
                    "asks_under_autopilot": True,
                },
            ],
            "item_kinds": [
                {"code": "action", "name": "Action", "form": "prose"},
                {"code": "card_wait", "name": "Card wait", "form": "wait"},
                {"code": "confirmation", "name": "Confirmation", "form": "prose"},
                {"code": "decision", "name": "Decision", "form": "prose"},
                {"code": "document", "name": "Document", "form": "prose"},
                {"code": "notice", "name": "Notice", "form": "prose"},
                {"code": "opening", "name": "Opening", "form": "prose"},
                {"code": "question", "name": "Question", "form": "prose"},
                {"code": "review", "name": "Review", "form": "prose"},
                {"code": "timed_wait", "name": "Timed wait", "form": "wait"},
                {"code": "work", "name": "Work", "form": "work"},
            ],
            "task_statuses": ["pending", "in_progress", "done"],
        }

    def test_the_confirmation_reasons_are_in_references_order(
        self, container: ServiceContainer
    ) -> None:
        views = container.view_service()
        reference = _json(views.reference())

        assert [reason.code for reason in views.confirmation_reasons()] == [
            reason["code"] for reason in reference["confirmation_reasons"]
        ]

    def test_a_drafts_timeline_has_no_items(
        self, container: ServiceContainer, project: Project
    ) -> None:
        assert _json(container.view_service().timeline(project)) == {
            "readonly": READONLY,
            "project": {
                "id": str(project.id),
                "folder": f"draft-{project.number}",
                "name": None,
                "state": "draft",
                "archived": False,
                "autopilot": False,
            },
            "items": [],
            "attachments": [],
        }

    def test_the_timeline_shows_items_in_the_files_vocabulary(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        project.slug = "badge-colours"
        project.state_code = ProjectState.OPEN
        project.name = "Badge colours"
        project.autopilot = True
        session.add(
            PlanTask(
                project_id=project.id,
                task_id="pick",
                position=1,
                title="Pick a colour",
                status_code=TaskStatus.PENDING,
            )
        )
        session.flush()
        opening = Item(
            project_id=project.id,
            seq=1,
            kind_code="opening",
            title="Badge colours",
            created_by_user_id=person.id,
            created_at=_at(9),
        )
        decision = Item(
            project_id=project.id,
            seq=2,
            kind_code="decision",
            title="Which colour for the badge?",
            plan_task_id="pick",
            urgent=True,
            for_user_id=person.id,
            created_by_session_id=project_session.id,
            created_at=_at(9, 30),
            done_at=_at(10),
            done_cause_code="answered",
            done_by_user_id=person.id,
        )
        session.add_all([opening, decision])
        session.flush()
        session.add_all(
            [
                Document(id=opening.id, path="items/1-badge-colours.md"),
                Document(
                    id=decision.id,
                    path="items/2-which-colour-for-the-badge.md",
                    summary="Blue or green.",
                ),
            ]
        )
        draft_copy = _attachment(
            project, 1, "project.md", source_code=AttachmentSource.DRAFT
        )
        survey = _attachment(
            project,
            2,
            "survey/colours.md",
            source_code=AttachmentSource.FILE,
            source_environment_id=environment.id,
            source_path="/work/Example/colours.md",
            created_by_session_id=project_session.id,
        )
        session.add_all([draft_copy, survey])
        session.flush()
        session.add_all(
            [
                ItemAttachment(
                    item_id=opening.id,
                    attachment_id=draft_copy.id,
                    position=1,
                    attached_at=_at(9),
                ),
                ItemAttachment(
                    item_id=decision.id,
                    attachment_id=survey.id,
                    position=1,
                    attached_at=_at(9, 30),
                ),
            ]
        )
        session.flush()

        assert _json(container.view_service().timeline(project)) == {
            "readonly": READONLY,
            "project": {
                "id": str(project.id),
                "folder": "badge-colours",
                "name": "Badge colours",
                "state": "open",
                "archived": False,
                "autopilot": True,
            },
            "items": [
                {
                    "id": str(opening.id),
                    "seq": 1,
                    "kind": "opening",
                    "title": "Badge colours",
                    "path": "items/1-badge-colours.md",
                    "step": None,
                    "urgent": False,
                    "for": None,
                    "summary": None,
                    "created_at": "2026-10-12T09:00:00Z",
                    "done": None,
                    "attachments": [
                        {"id": str(draft_copy.id), "path": "attachments/1/project.md"}
                    ],
                },
                {
                    "id": str(decision.id),
                    "seq": 2,
                    "kind": "decision",
                    "title": "Which colour for the badge?",
                    "path": "items/2-which-colour-for-the-badge.md",
                    "step": "pick",
                    "urgent": True,
                    "for": "ada",
                    "summary": "Blue or green.",
                    "created_at": "2026-10-12T09:30:00Z",
                    "done": {
                        "at": "2026-10-12T10:00:00Z",
                        "cause": "answered",
                        "by": "ada",
                    },
                    "attachments": [
                        {
                            "id": str(survey.id),
                            "path": "attachments/2/survey/colours.md",
                        }
                    ],
                },
            ],
            "attachments": [
                {
                    "id": str(draft_copy.id),
                    "path": "attachments/1/project.md",
                    "title": "Palette",
                    "source": None,
                },
                {
                    "id": str(survey.id),
                    "path": "attachments/2/survey/colours.md",
                    "title": "Palette",
                    "source": "example-env-1:/work/Example/colours.md",
                },
            ],
        }

    def test_an_items_attachments_keep_their_order_on_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        item: Item,
    ) -> None:
        first = _attachment(project, 2, "b.md", source_code=AttachmentSource.DRAFT)
        second = _attachment(project, 1, "a.md", source_code=AttachmentSource.DRAFT)
        session.add_all([first, second])
        session.flush()
        session.add_all(
            [
                ItemAttachment(
                    item_id=item.id,
                    attachment_id=second.id,
                    position=2,
                    attached_at=_at(9),
                ),
                ItemAttachment(
                    item_id=item.id,
                    attachment_id=first.id,
                    position=1,
                    attached_at=_at(9),
                ),
            ]
        )
        session.flush()

        timeline = _json(container.view_service().timeline(project))

        assert [a["path"] for a in timeline["items"][0]["attachments"]] == [
            "attachments/2/b.md",
            "attachments/1/a.md",
        ]
        assert [a["path"] for a in timeline["attachments"]] == [
            "attachments/1/a.md",
            "attachments/2/b.md",
        ]

    def test_a_done_line_without_a_person_names_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        item: Item,
    ) -> None:
        item.done_at = _at(10)
        item.done_cause_code = "turn_ended"
        session.flush()

        timeline = _json(container.view_service().timeline(project))

        assert timeline["items"][0]["done"] == {
            "at": "2026-10-12T10:00:00Z",
            "cause": "turn_ended",
            "by": None,
        }
        assert timeline["items"][0]["path"] is None

    def test_timeline_moved_tells_the_bus_after_the_commit(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
    ) -> None:
        views = container.view_service()
        with scoped_session(container):
            views.timeline_moved(project)
            assert engine_events == []

        assert engine_events == [
            TreeHashMoved(
                f"draft-{project.number}/timeline.json", views.timeline(project).hash
            ),
            ProjectChanged(project.id),
        ]
