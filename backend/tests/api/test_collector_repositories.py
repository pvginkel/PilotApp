"""The collector's routes of the Repositories and the Files (F152.11, F158.4,
F158.5): `GET /api/collector/repositories`, `POST /api/collector/commits`,
`GET /api/collector/files` and `PUT /api/collector/classes`, each answer
pinned under the collector's bearer and the protocol's version."""

from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from werkzeug.test import TestResponse

from app.models import Commit, File, FileClass, Repository
from app.services.container import ServiceContainer
from app.services.publication_service import (
    COLLECTOR_PROTOCOL_MAX,
    COLLECTOR_PROTOCOL_MIN,
    PublicationService,
)
from tests.support.database import writes
from tests.support.labels import declared
from tests.support.publications import (
    call,
    collector_headers,
    commit,
    file_edit,
    tool_call,
    whole,
)
from tests.support.repositories import (
    MADE_AT,
    READ_AT,
    WHOLE,
    change,
    file_class,
    read_commit,
    repository_read,
)

REPOSITORIES = "/api/collector/repositories"
COMMITS = "/api/collector/commits"
FILES = "/api/collector/files"
CLASSES = "/api/collector/classes"


def _read_body(*commits: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return repository_read(*commits, **overrides).model_dump(mode="json")


@pytest.fixture
def held(container: ServiceContainer, session: DbSession) -> None:
    """The invented checkout's commit held from its call, and its recipe
    edited, the File Class `recipe` declared."""
    declared(session, FileClass, "recipe", counted=True)
    publications: PublicationService = container.publication_service()
    publications.publish(
        whole(
            repository="RecipeBox",
            calls=[
                call(
                    1,
                    tool_calls=[
                        tool_call(1, commits=[commit()]),
                        tool_call(
                            2,
                            tool="Edit",
                            first_argument="stew.md",
                            file_edits=[file_edit()],
                        ),
                    ],
                )
            ],
        )
    )


def _refused(
    client: FlaskClient, headers: dict[str, str]
) -> list[tuple[str, TestResponse]]:
    return [
        (REPOSITORIES, client.get(REPOSITORIES, headers=headers)),
        (COMMITS, client.post(COMMITS, json=_read_body(), headers=headers)),
        (FILES, client.get(FILES, headers=headers)),
        (CLASSES, client.put(CLASSES, json={"classes": []}, headers=headers)),
    ]


class TestGate:
    def test_each_route_without_the_bearer_is_401(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        headers = collector_headers()
        del headers["Authorization"]

        with writes(session) as wrote:
            answers = _refused(client, headers)

        assert [(url, answer.status_code) for url, answer in answers] == [
            (REPOSITORIES, 401),
            (COMMITS, 401),
            (FILES, 401),
            (CLASSES, 401),
        ]
        assert wrote == {}

    def test_each_route_in_a_version_outside_the_range_is_426(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        headers = {**collector_headers(), "X-Pilot-Collector-Protocol": "3"}

        with writes(session) as wrote:
            answers = _refused(client, headers)

        assert {answer.status_code for _, answer in answers} == {426}
        assert {
            (answer.json["min"], answer.json["max"])
            for _, answer in answers
            if answer.json is not None
        } == {(COLLECTOR_PROTOCOL_MIN, COLLECTOR_PROTOCOL_MAX)}
        assert wrote == {}


class TestRepositories:
    @pytest.mark.usefixtures("held")
    def test_each_repository_is_answered_with_every_hash_a_read_gave(
        self, client: FlaskClient
    ) -> None:
        assert (
            client.post(
                COMMITS, json=_read_body(read_commit()), headers=collector_headers()
            ).status_code
            == 204
        )

        response = client.get(REPOSITORIES, headers=collector_headers())

        assert response.status_code == 200
        assert response.json == {
            "repositories": [{"name": "RecipeBox", "read": [WHOLE]}]
        }


class TestCommits:
    @pytest.mark.usefixtures("held")
    def test_a_read_is_204_and_completes_the_held_commit(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        response = client.post(
            COMMITS, json=_read_body(read_commit()), headers=collector_headers()
        )

        assert (response.status_code, response.data) == (204, b"")
        row = session.scalars(select(Commit)).one()
        assert (row.sha, row.made_at, row.lines_read_at, row.tool_call_id is None) == (
            WHOLE,
            MADE_AT,
            READ_AT,
            False,
        )

    @pytest.mark.usefixtures("held")
    def test_a_call_not_of_its_shape_is_400_with_every_field_named(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        body = _read_body(read_commit())
        body["commits"][0] |= {"sha": "3f9a2c1", "parents": []}
        del body["read_at"]

        with writes(session) as wrote:
            response = client.post(COMMITS, json=body, headers=collector_headers())

        assert response.status_code == 400
        assert {tuple(fault["loc"]) for fault in response.json} == {
            ("read_at",),
            ("commits", 0, "sha"),
            ("commits", 0, "parents"),
        }
        assert wrote == {}

    @pytest.mark.usefixtures("held")
    def test_a_call_that_contradicts_itself_is_400_with_every_fault_named(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        body = _read_body(
            read_commit(files=[change(), change()]),
            read_commit(subject="Plan"),
            repository="RecipeBoxSpecs",
        )

        with writes(session) as wrote:
            response = client.post(COMMITS, json=body, headers=collector_headers())

        assert response.status_code == 400
        assert response.json["code"] == "VALIDATION_FAILED"
        assert response.json["error"] == (
            "Cannot take the read of repository RecipeBoxSpecs because"
            " Pilot holds no such repository;"
            f" the commit `{WHOLE}` changes the file `recipes/stew.md` twice;"
            f" the commit `{WHOLE}` is given twice"
        )
        assert wrote == {}

    def test_a_body_over_the_cap_is_413(
        self,
        session: DbSession,
        app: Flask,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setitem(app.config, "MAX_CONTENT_LENGTH", 64)

        with writes(session) as wrote:
            response = client.post(
                COMMITS, json=_read_body(read_commit()), headers=collector_headers()
            )

        assert response.status_code == 413
        assert wrote == {}


class TestFiles:
    @pytest.mark.usefixtures("held")
    def test_every_file_is_answered_by_its_repository_and_path(
        self, client: FlaskClient
    ) -> None:
        response = client.get(FILES, headers=collector_headers())

        assert response.status_code == 200
        assert response.json == {
            "files": [{"repository": "RecipeBox", "path": "recipes/stew.md"}]
        }

    @pytest.mark.usefixtures("held")
    def test_with_unclassed_a_classed_file_is_left_out(
        self, client: FlaskClient
    ) -> None:
        assert (
            client.put(
                CLASSES, json={"classes": [file_class()]}, headers=collector_headers()
            ).status_code
            == 204
        )

        response = client.get(f"{FILES}?unclassed=true", headers=collector_headers())

        assert response.status_code == 200
        assert response.json == {"files": []}

    def test_an_unclassed_that_is_no_boolean_is_400(self, client: FlaskClient) -> None:
        response = client.get(f"{FILES}?unclassed=maybe", headers=collector_headers())

        assert response.status_code == 400


class TestClasses:
    @pytest.mark.usefixtures("held")
    def test_the_classes_are_204_and_held(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        response = client.put(
            CLASSES, json={"classes": [file_class()]}, headers=collector_headers()
        )

        assert (response.status_code, response.data) == (204, b"")
        assert session.scalars(select(File.class_code)).all() == ["recipe"]

    @pytest.mark.usefixtures("held")
    def test_a_call_naming_what_pilot_does_not_hold_is_400_with_every_fault(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        body = {
            "classes": [
                file_class(path="recipes/pie.md"),
                file_class(file_class="printout"),
            ]
        }

        with writes(session) as wrote:
            response = client.put(CLASSES, json=body, headers=collector_headers())

        assert response.status_code == 400
        assert response.json["error"] == (
            "Cannot take the files' classes because the file `recipes/pie.md` of"
            " `RecipeBox`: Pilot holds no such file;"
            " `file_class` `printout`: no value the labeller declares"
        )
        assert wrote == {}

    def test_a_call_not_of_its_shape_is_400(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        session.add(Repository(name="RecipeBox"))
        session.flush()
        body = {"classes": [file_class(path="/work/RecipeBox/x", counted=True)]}

        response = client.put(CLASSES, json=body, headers=collector_headers())

        assert response.status_code == 400
        assert {tuple(fault["loc"]) for fault in response.json} == {
            ("classes", 0, "path"),
            ("classes", 0, "counted"),
        }
