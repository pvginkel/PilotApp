"""/api/people/self/app-pages: a page's first beat, its beats after and its
away (F147; DB 312)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppPage, Project, User
from app.models.reference import UserKind
from app.services.app_page_service import EXPIRY_SECONDS

PAGES = "/api/people/self/app-pages"


def _sign_in(
    client: FlaskClient,
    subject: str = "subject-ada",
    roles: tuple[str, ...] = ("editor",),
) -> None:
    response = client.post(
        "/api/testing/auth/session",
        json={
            "subject": subject,
            "name": "Ada Example",
            "email": "ada@example.com",
            "roles": list(roles),
        },
    )
    assert response.status_code == 201


def _error(response: Any) -> str:
    return response.get_json()["error"]


def _bea(session: Session) -> User:
    bea = User(
        kind_code=UserKind.PERSON,
        subject="subject-bea",
        handle="bea",
        name="Bea Example",
        avatar_slot=2,
    )
    session.add(bea)
    session.flush()
    return bea


def _page(session: Session, person: User, beat_at: datetime | None = None) -> AppPage:
    page = AppPage(
        user_id=person.id,
        project_id=None,
        beat_at=beat_at or datetime.now(UTC) - timedelta(seconds=30),
    )
    session.add(page)
    session.flush()
    return page


def _pages(session: Session) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]]:
    session.expire_all()
    return [
        (page.id, page.user_id, page.project_id)
        for page in session.scalars(select(AppPage).order_by(AppPage.beat_at))
    ]


class TestBeginPage:
    def test_the_first_beat_writes_the_page_and_answers_its_id(
        self, client: FlaskClient, session: Session, person: User, project: Project
    ) -> None:
        _sign_in(client)

        response = client.post(PAGES, json={"project_id": str(project.id)})

        assert response.status_code == 201
        page_id = uuid.UUID(response.get_json()["id"])
        assert _pages(session) == [(page_id, person.id, project.id)]

    def test_a_page_showing_no_project(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client)

        response = client.post(PAGES, json={"project_id": None})

        assert response.status_code == 201
        assert _pages(session) == [
            (uuid.UUID(response.get_json()["id"]), person.id, None)
        ]

    def test_an_unknown_project_is_not_found(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client)
        unknown = uuid.uuid4()

        response = client.post(PAGES, json={"project_id": str(unknown)})

        assert response.status_code == 404
        assert _error(response) == f"Project {unknown} was not found"
        assert _pages(session) == []

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({}, id="missing"),
            pytest.param({"project_id": "camp"}, id="not-a-uuid"),
        ],
    )
    def test_a_body_with_no_project_id_is_refused(
        self, client: FlaskClient, session: Session, person: User, body: object
    ) -> None:
        _sign_in(client)

        assert client.post(PAGES, json=body).status_code == 400
        assert _pages(session) == []

    def test_before_the_handle_it_is_refused(
        self, client: FlaskClient, session: Session
    ) -> None:
        _sign_in(client, subject="subject-new")

        response = client.post(PAGES, json={"project_id": None})

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot beat a page of Pilot because you have not chosen your handle yet"
        )
        assert _pages(session) == []

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client, roles=())

        assert client.post(PAGES, json={"project_id": None}).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.post(PAGES, json={"project_id": None}).status_code == 401


class TestBeatPage:
    def test_a_beat_sets_when_it_beat_and_the_project_it_shows(
        self, client: FlaskClient, session: Session, person: User, project: Project
    ) -> None:
        _sign_in(client)
        page = _page(session, person, datetime.now(UTC) - timedelta(seconds=60))
        began = datetime.now(UTC)

        response = client.put(
            f"{PAGES}/{page.id}", json={"project_id": str(project.id)}
        )

        assert response.status_code == 204
        session.expire_all()
        beat = session.get_one(AppPage, page.id)
        assert beat.project_id == project.id
        assert beat.beat_at >= began

    def test_a_page_whose_beat_counts_for_nothing_has_ended(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client)
        page = _page(
            session, person, datetime.now(UTC) - timedelta(seconds=EXPIRY_SECONDS)
        )

        response = client.put(f"{PAGES}/{page.id}", json={"project_id": None})

        assert response.status_code == 404
        assert _error(response) == f"App Page {page.id} was not found"

    def test_another_persons_page_is_not_found(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client)
        bea = _bea(session)
        page = _page(session, bea)
        # The refusal rolls the request back to the test's last commit.
        session.commit()

        response = client.put(f"{PAGES}/{page.id}", json={"project_id": None})

        assert response.status_code == 404
        assert _pages(session) == [(page.id, bea.id, None)]

    def test_an_unknown_project_is_not_found(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client)
        page = _page(session, person)
        unknown = uuid.uuid4()

        response = client.put(f"{PAGES}/{page.id}", json={"project_id": str(unknown)})

        assert response.status_code == 404
        assert _error(response) == f"Project {unknown} was not found"

    def test_a_body_with_no_project_id_is_refused(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client)
        page = _page(session, person)

        assert client.put(f"{PAGES}/{page.id}", json={}).status_code == 400

    def test_before_the_handle_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client, subject="subject-new")

        response = client.put(f"{PAGES}/{uuid.uuid4()}", json={"project_id": None})

        assert response.status_code == 409

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client, roles=())
        page = _page(session, person)

        response = client.put(f"{PAGES}/{page.id}", json={"project_id": None})

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.put(f"{PAGES}/{uuid.uuid4()}", json={"project_id": None})

        assert response.status_code == 401


class TestLeavePage:
    def test_the_away_deletes_the_page(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client)
        stays = _page(session, person)
        page = _page(session, person)

        response = client.post(f"{PAGES}/{page.id}/away")

        assert response.status_code == 204
        assert _pages(session) == [(stays.id, person.id, None)]

    def test_a_beacons_away_is_taken(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client)
        page = _page(session, person)

        # `navigator.sendBeacon(url)` posts with no body; with a string, as
        # text/plain.
        response = client.post(
            f"{PAGES}/{page.id}/away", data="", content_type="text/plain;charset=UTF-8"
        )

        assert response.status_code == 204
        assert _pages(session) == []

    def test_another_persons_page_stays(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client)
        bea = _bea(session)
        page = _page(session, bea)

        response = client.post(f"{PAGES}/{page.id}/away")

        assert response.status_code == 204
        assert _pages(session) == [(page.id, bea.id, None)]

    def test_a_page_that_has_ended_is_nothing_to_delete(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client)

        assert client.post(f"{PAGES}/{uuid.uuid4()}/away").status_code == 204

    def test_before_the_handle_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client, subject="subject-new")

        response = client.post(f"{PAGES}/{uuid.uuid4()}/away")

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot send a page's away because you have not chosen your handle yet"
        )

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client, roles=())
        page = _page(session, person)

        assert client.post(f"{PAGES}/{page.id}/away").status_code == 403
        assert len(_pages(session)) == 1

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.post(f"{PAGES}/{uuid.uuid4()}/away").status_code == 401
