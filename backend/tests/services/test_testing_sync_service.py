"""What the sync's testing endpoints set off: a person's answer written into
the file the store holds, and the `manifest` event."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ManifestChanged, TreeHashMoved
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Document, Project, User
from app.services.container import ServiceContainer

DECISION = """# Which tent?

```decision id=D1
options:
  - Dome
  - Tunnel
recommend: Dome
```
"""


def _bear_item(
    container: ServiceContainer, project: Project, session: models.Session
) -> str:
    with scoped_session(container):
        container.document_service().bear_item(
            project, "decision", "Which tent?", session, DECISION
        )
    return f"draft-{project.number}/items/1-which-tent.md"


class TestTestingSyncService:
    def test_answer_writes_the_persons_answer_into_the_file(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        engine_events: list[EngineEvent],
    ) -> None:
        path = _bear_item(container, project, project_session)
        engine_events.clear()

        with scoped_session(container):
            file = container.testing_sync_service().answer(
                path, "D1", "Tunnel", person.handle
            )

        document = session.scalars(
            select(Document).where(Document.path == "items/1-which-tent.md")
        ).one()
        assert document.published_text is not None
        assert "answer: Tunnel\nby: ada\n" in document.published_text
        assert file == container.tree_service().read(path)
        assert file.content == document.published_text.encode()
        assert TreeHashMoved(path, file.hash) in engine_events

    def test_answer_refuses_a_path_that_is_no_document(
        self, container: ServiceContainer, project: Project, person: User
    ) -> None:
        service = container.testing_sync_service()

        for path in (f"draft-{project.number}/plan.json", "reference.json"):
            with pytest.raises(RecordNotFoundException, match=f"Document {path}"):
                service.answer(path, "D1", "Tunnel", person.handle)
        with pytest.raises(RecordNotFoundException, match="Path draft-9/notes.md"):
            service.answer("draft-9/notes.md", "D1", "Tunnel", person.handle)

    def test_answer_refuses_a_handle_no_user_has(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session)

        with pytest.raises(RecordNotFoundException, match="User grace"):
            container.testing_sync_service().answer(path, "D1", "Tunnel", "grace")

    def test_answer_is_refused_as_the_record_refuses_it(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        path = _bear_item(container, project, project_session)

        with pytest.raises(InvalidOperationException, match="the answer is blank"):
            container.testing_sync_service().answer(path, "D1", " ", person.handle)

    def test_announce_manifest_raises_the_manifest_event_once_committed(
        self, container: ServiceContainer, engine_events: list[EngineEvent]
    ) -> None:
        with scoped_session(container):
            container.testing_sync_service().announce_manifest()
            assert engine_events == []

        assert engine_events == [ManifestChanged()]
