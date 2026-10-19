"""The sync's testing endpoints: what the live proof of the sync sets off
inside the running server, refused outside testing mode."""

import pytest
from dependency_injector import providers
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.config import Stage
from app.database import scoped_session
from app.models import Document, Project, User
from app.services.container import ServiceContainer
from tests.support.fake_sidecar import FakeSidecar

DECISION = """# Which tent?

```decision id=D1
options:
  - Dome
  - Tunnel
recommend: Dome
```
"""

ANSWER = "/api/testing/sync/answer"

MANIFEST = "/api/testing/sync/manifest"


def _bear_item(
    container: ServiceContainer, project: Project, session: models.Session
) -> str:
    with scoped_session(container):
        container.document_service().bear_item(
            project, "decision", "Which tent?", session, DECISION
        )
    return f"draft-{project.number}/items/1-which-tent.md"


def _body(path: str, **changes: str) -> dict[str, str]:
    return {"path": path, "block": "D1", "answer": "Tunnel", "user": "ada", **changes}


class TestTestingSyncGuard:
    @pytest.mark.parametrize("url", [ANSWER, MANIFEST])
    @pytest.mark.parametrize(
        "changes",
        [{"flask_env": "development"}, {"stage": Stage("prd")}],
        ids=["development", "prd"],
    )
    def test_every_endpoint_is_refused_outside_testing_mode(
        self,
        container: ServiceContainer,
        client: FlaskClient,
        url: str,
        changes: dict[str, object],
    ) -> None:
        settings = container.config().model_copy(update=changes)
        container.config.override(providers.Object(settings))

        response = client.post(url, json=_body("reference.json"))

        assert response.status_code == 400
        assert response.json["code"] == "ROUTE_NOT_AVAILABLE"


class TestTestingSyncAnswer:
    """`POST /api/testing/sync/answer`."""

    def test_the_answer_is_written_into_the_file_and_streamed(
        self,
        session: DbSession,
        container: ServiceContainer,
        client: FlaskClient,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        path = _bear_item(container, project, project_session)
        fake_sidecar.drain()

        response = client.post(ANSWER, json=_body(path))

        assert response.status_code == 200
        document = session.scalars(
            select(Document).where(Document.path == "items/1-which-tent.md")
        ).one()
        assert document.published_text is not None
        assert "answer: Tunnel\nby: ada\n" in document.published_text
        assert response.json == {
            "path": path,
            "hash": container.tree_service().read(path).hash,
        }
        assert fake_sidecar.drain() == [path, f"draft-{project.number}/timeline.json"]
        assert fake_sidecar.text(path) == document.published_text

    def test_a_path_that_is_no_document_is_404(
        self, client: FlaskClient, project: Project, person: User
    ) -> None:
        for path in (f"draft-{project.number}/plan.json", "draft-9/notes.md"):
            response = client.post(ANSWER, json=_body(path))

            assert response.status_code == 404
            assert response.json["code"] == "RECORD_NOT_FOUND"

    def test_a_handle_no_user_has_is_404(
        self,
        container: ServiceContainer,
        client: FlaskClient,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session)

        response = client.post(ANSWER, json=_body(path, user="grace"))

        assert response.status_code == 404
        assert "User grace" in response.json["error"]

    def test_an_answer_the_record_refuses_is_409(
        self,
        container: ServiceContainer,
        client: FlaskClient,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        path = _bear_item(container, project, project_session)

        response = client.post(ANSWER, json=_body(path, answer=" "))

        assert response.status_code == 409
        assert response.json["code"] == "INVALID_OPERATION"

    def test_a_body_without_its_fields_is_400(self, client: FlaskClient) -> None:
        response = client.post(ANSWER, json={"path": "reference.json"})

        assert response.status_code == 400


class TestTestingSyncManifest:
    """`POST /api/testing/sync/manifest`."""

    def test_the_manifest_event_reaches_the_stream(
        self, client: FlaskClient, fake_sidecar: FakeSidecar
    ) -> None:
        response = client.post(MANIFEST)

        assert response.status_code == 204
        assert fake_sidecar.tree == {}
        # The sidecar reconciles on `manifest`: the root's `reference.json`
        # is written down.
        assert fake_sidecar.drain() == []
        assert set(fake_sidecar.tree) == {"reference.json"}
