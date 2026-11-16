"""`pilot-work`'s routes (TD §4.5, F85): the REST calls Pilot's MCP server
makes for a worker session's tools, under the session's bearer, outside `/api/`
(review 2), pinned as the surface they are, a work item's progress among them
(F85.3, F85.4), a step's why with it (DB 327), and its debrief (F85.5; DB 323
to 329), with its subject and whether it completes it (DB 608)."""

import uuid
from datetime import UTC, datetime

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import (
    Attachment,
    DebriefEntry,
    Document,
    Effect,
    Environment,
    Item,
    ItemAttachment,
    ProgressStep,
    Project,
    Turn,
    Work,
)
from app.models.reference import ProgressState, SessionState, TurnCause
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.pilot_server import token_hash
from app.services.session_record_service import read_records
from tests.support.fake_controller import ServedFakeController, client_of

DOCUMENTS = "/tools/pilot-work/documents"

ATTACHMENTS = "/tools/pilot-work/attachments"

PROGRESS = "/tools/pilot-work/progress"

DEBRIEF = "/tools/pilot-work/debrief"

TOKEN = "worker-token"

PATH = "/work/Example/docs/refinement.md"

TEXT = "Two options for the camp.\n\n```question id=Q1\n```\n"


def _bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _session(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    environment: Environment,
    kind: str = "work",
    state: SessionState = SessionState.RUNNING,
) -> models.Session:
    """A Session of `kind` whose bearer is `TOKEN`, running unless `state`
    says otherwise; a work one with its Work."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code=kind,
        cwd="/work/Example",
        token_hash=token_hash(TOKEN),
        state_code=state,
    )
    session.add(run)
    session.flush()
    if kind == "work":
        container.record_service().place_work(project, run, "Refining the camp")
    return run


def _file(fake_controller: ServedFakeController, environment: Environment) -> None:
    fake_controller.add_environment(environment.id)
    fake_controller.put_file(environment.id, PATH, TEXT.encode())


class TestPilotWorkRoutes:
    def test_the_surface_is_five_routes_outside_the_api(self, app: Flask) -> None:
        routes = sorted(
            (rule.rule, sorted(rule.methods - {"HEAD", "OPTIONS"}))
            for rule in app.url_map.iter_rules()
            if rule.endpoint.startswith("pilot_work.")
        )

        assert routes == [
            (ATTACHMENTS, ["POST"]),
            (DEBRIEF, ["POST"]),
            (DOCUMENTS, ["POST"]),
            (PROGRESS, ["PATCH"]),
            (PROGRESS, ["PUT"]),
        ]

    def test_the_routes_are_outside_the_oidc_gate(
        self,
        oidc_app: Flask,
        oidc_client: FlaskClient,
        session: DbSession,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        assert oidc_app.container.config().oidc_enabled
        client_of(oidc_app.container, fake_controller)
        _session(session, oidc_app.container, project, environment)
        _file(fake_controller, environment)

        response = oidc_client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 201


class TestRegisterDocument:
    """`POST /tools/pilot-work/documents`: `register_document(path)`."""

    def test_a_file_registered_is_201_with_its_items_id(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        _file(fake_controller, environment)

        response = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 201
        body = response.get_json()
        assert list(body) == ["id"]
        item = session.get_one(Item, uuid.UUID(body["id"]))
        assert (item.project_id, item.kind_code, item.created_by_session_id) == (
            project.id,
            "review",
            run.id,
        )
        assert session.get_one(Document, item.id).source_path == PATH

    def test_the_path_registered_again_is_200_with_the_same_id(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment)
        _file(fake_controller, environment)
        first = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        again = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert again.status_code == 200
        assert again.get_json() == first.get_json()

    @pytest.mark.parametrize(
        ("headers", "error"),
        [
            ({}, "Cannot call pilot-work because the request carries no bearer"),
            (
                _bearer("an-unknown-token"),
                "Cannot call pilot-work because no session has the request's bearer",
            ),
        ],
    )
    def test_no_bearer_or_an_unknown_one_is_401(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        headers: dict[str, str],
        error: str,
    ) -> None:
        _session(session, container, project, environment)

        response = client.post(DOCUMENTS, json={"path": PATH}, headers=headers)

        assert response.status_code == 401
        assert response.get_json()["error"] == error

    def test_a_session_that_is_not_a_work_items_is_403(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment, kind="chat")

        response = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 403
        assert response.get_json()["error"] == (
            f"Cannot call pilot-work because session {run.id} is a chat session,"
            " not a work item's"
        )

    def test_a_stopped_session_is_403_and_mints_nothing(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(
            session, container, project, environment, state=SessionState.STOPPED
        )
        _file(fake_controller, environment)

        response = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 403
        assert response.get_json()["error"] == (
            f"Cannot call pilot-work because session {run.id} has no turn running"
        )
        assert session.scalars(select(Document)).all() == []

    def test_the_gate_answers_before_the_body_is_read(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        response = client.post(DOCUMENTS, json={"paths": [PATH]})

        assert response.status_code == 401

    @pytest.mark.parametrize("body", [{}, {"path": ""}, {"path": PATH, "to": "x"}])
    def test_a_body_that_is_not_a_path_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        body: dict[str, str],
    ) -> None:
        _session(session, container, project, environment)

        response = client.post(DOCUMENTS, json=body, headers=_bearer())

        assert response.status_code == 400

    def test_a_file_that_cannot_be_registered_is_409_with_the_reason(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, b"```question id=Q1\n")

        response = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 409
        error = response.get_json()["error"]
        assert error.startswith(
            f"Cannot register document {PATH} because its text holds faults: line 1: "
        )

    def test_a_controller_that_cannot_read_the_environment_is_502(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment)
        _file(fake_controller, environment)
        fake_controller.unreadable(environment.id)

        response = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 502
        assert "503 environment-unreadable" in response.get_json()["error"]


class TestAttachFile:
    """`POST /tools/pilot-work/attachments`: `attach_file(path, to?)`."""

    def test_a_folder_attached_is_201_with_its_attachments_ids(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, "/work/Example/out/a.md", b"# A\n")
        fake_controller.put_file(environment.id, "/work/Example/out/b/c.md", b"C")

        response = client.post(
            ATTACHMENTS, json={"path": "/work/Example/out"}, headers=_bearer()
        )

        assert response.status_code == 201
        body = response.get_json()
        assert list(body) == ["ids"]
        attachments = [
            session.get_one(Attachment, uuid.UUID(id_)) for id_ in body["ids"]
        ]
        assert [
            (attachment.filename, attachment.source_path, attachment.batch)
            for attachment in attachments
        ] == [
            ("a.md", "/work/Example/out/a.md", 1),
            ("b/c.md", "/work/Example/out/b/c.md", 1),
        ]
        assert {attachment.created_by_session_id for attachment in attachments} == {
            run.id
        }

    def test_to_names_the_item_they_hang_on(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment)
        _file(fake_controller, environment)
        registered = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())
        to = registered.get_json()["id"]

        response = client.post(
            ATTACHMENTS, json={"path": PATH, "to": to}, headers=_bearer()
        )

        assert response.status_code == 201
        [attachment_id] = response.get_json()["ids"]
        hung = session.scalars(
            select(ItemAttachment.attachment_id).where(
                ItemAttachment.item_id == uuid.UUID(to)
            )
        ).all()
        assert hung == [uuid.UUID(attachment_id)]

    def test_an_item_not_of_the_sessions_project_is_404(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment)
        _file(fake_controller, environment)
        to = uuid.uuid4()

        response = client.post(
            ATTACHMENTS, json={"path": PATH, "to": str(to)}, headers=_bearer()
        )

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Item {to} was not found"

    def test_no_bearer_is_401(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment)

        response = client.post(ATTACHMENTS, json={"path": PATH})

        assert response.status_code == 401
        assert response.get_json()["error"] == (
            "Cannot call pilot-work because the request carries no bearer"
        )

    def test_a_session_that_is_not_a_work_items_is_403(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment, kind="chat")

        response = client.post(ATTACHMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 403

    def test_a_session_whose_turn_has_ended_is_403_and_attaches_nothing(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(
            session, container, project, environment, state=SessionState.IDLE
        )
        _file(fake_controller, environment)

        response = client.post(ATTACHMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 403
        assert response.get_json()["error"] == (
            f"Cannot call pilot-work because session {run.id} has no turn running"
        )
        assert session.scalars(select(Attachment)).all() == []

    @pytest.mark.parametrize(
        "body",
        [{}, {"path": ""}, {"path": PATH, "to": "x"}, {"path": PATH, "as": "x"}],
    )
    def test_a_body_that_is_not_a_path_and_an_item_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        body: dict[str, str],
    ) -> None:
        _session(session, container, project, environment)

        response = client.post(ATTACHMENTS, json=body, headers=_bearer())

        assert response.status_code == 400

    def test_a_file_that_cannot_be_copied_is_409_with_the_reason(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)

        response = client.post(ATTACHMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot attach {PATH} because the controller answered 404 not-found:"
            f" no such file or directory: {PATH!r}"
        )

    def test_a_controller_that_cannot_read_the_environment_is_502(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment)
        _file(fake_controller, environment)
        fake_controller.unreadable(environment.id)

        response = client.post(ATTACHMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 502
        assert "503 environment-unreadable" in response.get_json()["error"]


def _steps(session: DbSession, run: models.Session) -> list[tuple[str, str, str]]:
    return [
        (step.code, step.label, step.state_code)
        for step in session.scalars(
            select(ProgressStep)
            .where(ProgressStep.work_id == run.id)
            .order_by(ProgressStep.position)
        )
    ]


_PUBLISHED = {
    "steps": [
        {"code": "P1.code", "label": "P1 · the client", "state": "done"},
        {"code": "P1.review", "label": "P1 · review", "state": "active"},
        {"code": "test", "label": "Test"},
    ]
}

_ANSWERED = {
    "steps": [
        {"code": "P1.code", "label": "P1 · the client", "state": "done", "why": None},
        {"code": "P1.review", "label": "P1 · review", "state": "active", "why": None},
        {"code": "test", "label": "Test", "state": "pending", "why": None},
    ]
}

_WHY = "The reviewer found the migration's downgrade left the column"


class TestSetProgress:
    """`PUT /tools/pilot-work/progress`: `set_progress(steps)`."""

    def test_the_list_replaced_is_200_with_the_list_as_it_stands(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)

        response = client.put(PROGRESS, json=_PUBLISHED, headers=_bearer())

        assert response.status_code == 200
        assert response.get_json() == _ANSWERED
        assert _steps(session, run) == [
            ("P1.code", "P1 · the client", ProgressState.DONE),
            ("P1.review", "P1 · review", ProgressState.ACTIVE),
            ("test", "Test", ProgressState.PENDING),
        ]

    def test_no_steps_remove_the_list(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        client.put(PROGRESS, json=_PUBLISHED, headers=_bearer())

        response = client.put(PROGRESS, json={"steps": []}, headers=_bearer())

        assert response.status_code == 200
        assert response.get_json() == {"steps": []}
        assert _steps(session, run) == []

    def test_a_steps_why_stands_as_the_last_call_gave_it(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 327: taken on any step, answered with the list, and a step given
        without one has none."""
        run = _session(session, container, project, environment)
        given = {
            "steps": [
                {"code": "P1.code", "label": "P1 · code", "state": "done"},
                {"code": "P1.code-2", "label": "P1 · code 2", "why": _WHY},
            ]
        }

        published = client.put(PROGRESS, json=given, headers=_bearer())
        given["steps"][1].pop("why")
        republished = client.put(PROGRESS, json=given, headers=_bearer())

        assert published.status_code == 200
        assert [step["why"] for step in published.get_json()["steps"]] == [None, _WHY]
        assert republished.status_code == 200
        assert [step["why"] for step in republished.get_json()["steps"]] == [
            None,
            None,
        ]
        assert [
            step.why
            for step in session.scalars(
                select(ProgressStep).where(ProgressStep.work_id == run.id)
            )
        ] == [None, None]

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"steps": [{"code": "", "label": "Test"}]},
            {"steps": [{"code": "c" * 65, "label": "Test"}]},
            {"steps": [{"code": "test", "label": ""}]},
            {"steps": [{"code": "test", "label": "l" * 121}]},
            {"steps": [{"code": "test", "label": "Test", "state": "failed"}]},
            {"steps": [{"code": "test", "label": "Test", "why": ""}]},
            {"steps": [{"code": "test", "label": "Test", "why": "w" * 121}]},
            {"steps": [{"code": f"s{n}", "label": "Step"} for n in range(101)]},
            {"steps": [{"code": "test", "label": "Test", "note": "x"}]},
        ],
        ids=[
            "no-steps",
            "empty-code",
            "long-code",
            "empty-label",
            "long-label",
            "state",
            "empty-why",
            "long-why",
            "long-list",
            "extra-field",
        ],
    )
    def test_a_body_that_is_not_a_list_of_steps_is_400_and_changes_nothing(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        body: dict[str, object],
    ) -> None:
        run = _session(session, container, project, environment)
        client.put(PROGRESS, json=_PUBLISHED, headers=_bearer())

        response = client.put(PROGRESS, json=body, headers=_bearer())

        assert response.status_code == 400
        assert len(_steps(session, run)) == 3

    def test_the_limits_themselves_are_taken(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        steps = [
            {"code": f"{n:064d}", "label": "l" * 120, "why": "w" * 120}
            for n in range(100)
        ]

        response = client.put(PROGRESS, json={"steps": steps}, headers=_bearer())

        assert response.status_code == 200
        assert len(_steps(session, run)) == 100

    def test_a_repeated_code_is_409_with_the_reason_and_changes_nothing(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        client.put(PROGRESS, json=_PUBLISHED, headers=_bearer())
        repeated = {
            "steps": [{"code": "test", "label": "Test"}, {"code": "test", "label": "T"}]
        }

        response = client.put(PROGRESS, json=repeated, headers=_bearer())

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot set the progress of work item {run.id} because code test is"
            " repeated"
        )
        assert len(_steps(session, run)) == 3

    def test_no_bearer_is_401(self, client: FlaskClient) -> None:
        response = client.put(PROGRESS, json=_PUBLISHED)

        assert response.status_code == 401

    @pytest.mark.parametrize(
        ("kind", "state", "error"),
        [
            ("chat", SessionState.RUNNING, "is a chat session, not a work item's"),
            ("work", SessionState.STOPPED, "has no turn running"),
        ],
        ids=["chat", "stopped"],
    )
    def test_a_session_that_is_not_a_running_work_items_is_403_and_lists_nothing(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        kind: str,
        state: SessionState,
        error: str,
    ) -> None:
        run = _session(session, container, project, environment, kind, state)

        response = client.put(PROGRESS, json=_PUBLISHED, headers=_bearer())

        assert response.status_code == 403
        assert response.get_json()["error"] == (
            f"Cannot call pilot-work because session {run.id} {error}"
        )
        assert session.scalars(select(ProgressStep)).all() == []


SUBJECT = "Slice 058 · The search page"

_DEBRIEF = {
    "debrief": "It went well, if slowly: the second review was worth it.",
    "entries": [
        {
            "section": "P1 · The client",
            "round": 1,
            "role": "code-writer",
            "duration": 2400,
            "words": "The client came out cleanly.",
        },
        {
            "section": "P1 · The client",
            "round": 2,
            "role": "code-writer",
            "duration": 600,
            "why": _WHY,
        },
        {
            "section": "Completion check",
            "round": 1,
            "role": "sweep",
            "duration": 0,
            "passed": False,
        },
    ],
}

_STORED = [
    (
        1,
        "P1 · The client",
        1,
        "code-writer",
        2400,
        "The client came out cleanly.",
        None,
        None,
    ),
    (2, "P1 · The client", 2, "code-writer", 600, None, None, _WHY),
    (3, "Completion check", 1, "sweep", 0, None, False, None),
]


def _entries(session: DbSession, run: models.Session) -> list[tuple[object, ...]]:
    return [
        (
            entry.position,
            entry.section,
            entry.round,
            entry.role,
            entry.duration,
            entry.words,
            entry.passed,
            entry.why,
        )
        for entry in session.scalars(
            select(DebriefEntry)
            .where(DebriefEntry.work_id == run.id)
            .order_by(DebriefEntry.position)
        )
    ]


def _debriefed(session: DbSession, run: models.Session) -> str | None:
    session.expire_all()
    return session.get_one(Work, run.id).debrief


def _subject(session: DbSession, run: models.Session) -> tuple[str | None, bool | None]:
    """The Work's debrief subject and whether its debrief completes it."""
    session.expire_all()
    work = session.get_one(Work, run.id)
    return work.debrief_subject, work.debrief_completes


def _entry(**overrides: object) -> dict[str, object]:
    """An entry inside every limit, with `overrides`; one given None goes."""
    entry: dict[str, object] = {
        "section": "P1 · The client",
        "round": 1,
        "role": "code-writer",
        "duration": 60,
    }
    entry.update(overrides)
    return {name: value for name, value in entry.items() if value is not None}


class TestRegisterDebrief:
    """`POST /tools/pilot-work/debrief`: `register_debrief(debrief, entries)`."""

    def test_the_debrief_stored_is_201_with_the_number_of_its_entries(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)

        response = client.post(DEBRIEF, json=_DEBRIEF, headers=_bearer())

        assert response.status_code == 201
        assert response.get_json() == {"entries": 3}
        assert _debriefed(session, run) == _DEBRIEF["debrief"]
        assert _entries(session, run) == _STORED
        assert _subject(session, run) == (None, True)

    @pytest.mark.parametrize(
        ("fields", "stored"),
        [
            ({"subject": SUBJECT}, (SUBJECT, True)),
            ({"subject": SUBJECT, "completes": False}, (SUBJECT, False)),
            ({"subject": SUBJECT, "completes": True}, (SUBJECT, True)),
            ({"subject": None, "completes": True}, (None, True)),
        ],
        ids=["subject", "not-completing", "completing", "none-completing"],
    )
    def test_its_subject_and_whether_it_completes_it_are_stored_as_given(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        fields: dict[str, object],
        stored: tuple[str | None, bool],
    ) -> None:
        """DB 608: compared whole, so stored as given; completes true where
        the call gives none."""
        run = _session(session, container, project, environment)

        response = client.post(DEBRIEF, json=_DEBRIEF | fields, headers=_bearer())

        assert response.status_code == 201
        assert _subject(session, run) == stored

    def test_a_second_call_is_409_with_the_reason_and_changes_nothing(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 324: a work item is debriefed once."""
        run = _session(session, container, project, environment)
        client.post(DEBRIEF, json=_DEBRIEF, headers=_bearer())

        response = client.post(
            DEBRIEF,
            json={
                "debrief": "Another account.",
                "entries": [_entry()],
                "subject": SUBJECT,
                "completes": False,
            },
            headers=_bearer(),
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot register the debrief of work item {run.id} because it has"
            " its debrief already"
        )
        assert _debriefed(session, run) == _DEBRIEF["debrief"]
        assert _entries(session, run) == _STORED
        assert _subject(session, run) == (None, True)

    @pytest.mark.parametrize(
        "body",
        [
            {"entries": [_entry()]},
            {"debrief": "", "entries": [_entry()]},
            {"debrief": "   ", "entries": [_entry()]},
            {"debrief": "\n", "entries": [_entry()]},
            {"debrief": "d" * 16_001, "entries": [_entry()]},
            {"debrief": "Fine."},
            {"debrief": "Fine.", "entries": []},
            {"debrief": "Fine.", "entries": [_entry()] * 501},
            {"debrief": "Fine.", "entries": [_entry(section="")]},
            {"debrief": "Fine.", "entries": [_entry(section="s" * 121)]},
            {"debrief": "Fine.", "entries": [_entry(round=0)]},
            {"debrief": "Fine.", "entries": [_entry(round=1.5)]},
            {"debrief": "Fine.", "entries": [_entry(round="2")]},
            {"debrief": "Fine.", "entries": [_entry(round=True)]},
            {"debrief": "Fine.", "entries": [_entry(role="")]},
            {"debrief": "Fine.", "entries": [_entry(role="r" * 65)]},
            {"debrief": "Fine.", "entries": [_entry(duration=-1)]},
            {"debrief": "Fine.", "entries": [_entry(duration=2**31)]},
            {"debrief": "Fine.", "entries": [_entry(words="")]},
            {"debrief": "Fine.", "entries": [_entry(words="w" * 4_001)]},
            {"debrief": "Fine.", "entries": [_entry(passed="yes")]},
            {"debrief": "Fine.", "entries": [_entry(words="Fine.", passed=True)]},
            {"debrief": "Fine.", "entries": [_entry(why="")]},
            {"debrief": "Fine.", "entries": [_entry(why="w" * 121)]},
            {"debrief": "Fine.", "entries": [_entry(verdict="good")]},
            {"debrief": "Fine.", "entries": [_entry()], "verdict": "good"},
            {"debrief": "Fine.", "entries": [_entry()], "subject": ""},
            {"debrief": "Fine.", "entries": [_entry()], "subject": "  "},
            {"debrief": "Fine.", "entries": [_entry()], "subject": "s" * 121},
            {"debrief": "Fine.", "entries": [_entry()], "subject": 58},
            {"debrief": "Fine.", "entries": [_entry()], "completes": False},
            {
                "debrief": "Fine.",
                "entries": [_entry()],
                "subject": None,
                "completes": False,
            },
            {"debrief": "Fine.", "entries": [_entry()], "completes": None},
            {"debrief": "Fine.", "entries": [_entry()], "completes": "false"},
            {"debrief": "Fine.", "entries": [_entry()], "completes": 0},
        ],
        ids=[
            "no-debrief",
            "empty-debrief",
            "blank-debrief",
            "newline-debrief",
            "long-debrief",
            "no-entries",
            "empty-entries",
            "long-entries",
            "empty-section",
            "long-section",
            "round-0",
            "round-fraction",
            "round-text",
            "round-bool",
            "empty-role",
            "long-role",
            "negative-duration",
            "huge-duration",
            "empty-words",
            "long-words",
            "passed-text",
            "words-and-passed",
            "empty-why",
            "long-why",
            "entry-extra-field",
            "extra-field",
            "empty-subject",
            "blank-subject",
            "long-subject",
            "subject-number",
            "not-completing-without-subject",
            "not-completing-with-none",
            "completes-none",
            "completes-text",
            "completes-number",
        ],
    )
    def test_a_body_outside_the_limits_is_400_and_stores_nothing(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        body: dict[str, object],
    ) -> None:
        run = _session(session, container, project, environment)

        response = client.post(DEBRIEF, json=body, headers=_bearer())

        assert response.status_code == 400
        assert _debriefed(session, run) is None
        assert _entries(session, run) == []

    def test_a_body_with_faults_names_each(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 325: refused with the reason, each fault named."""
        _session(session, container, project, environment)
        body = {
            "debrief": "",
            "entries": [
                _entry(),
                _entry(role="r" * 65, duration=-1),
                _entry(words="Fine.", passed=True),
            ],
        }

        response = client.post(DEBRIEF, json=body, headers=_bearer())

        assert response.status_code == 400
        assert [fault["loc"] for fault in response.get_json()] == [
            ["debrief"],
            ["entries", 1, "role"],
            ["entries", 1, "duration"],
            ["entries", 2],
        ]

    def test_completes_false_without_a_subject_says_why(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 608: refused with the reason."""
        _session(session, container, project, environment)

        response = client.post(
            DEBRIEF, json=_DEBRIEF | {"completes": False}, headers=_bearer()
        )

        assert response.status_code == 400
        assert [fault["msg"] for fault in response.get_json()] == [
            "Value error, a debrief that does not complete names its subject"
        ]

    def test_the_limits_themselves_are_taken(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        longest = _entry(
            section="s" * 120,
            role="r" * 64,
            duration=2**31 - 1,
            words="w" * 4_000,
            why="w" * 120,
        )
        least = _entry(duration=0, passed=True)
        body = {
            "debrief": "d" * 16_000,
            "entries": [longest] * 499 + [least],
            "subject": "s" * 120,
        }

        response = client.post(DEBRIEF, json=body, headers=_bearer())

        assert response.status_code == 201
        assert response.get_json() == {"entries": 500}
        assert len(_entries(session, run)) == 500
        assert _subject(session, run) == ("s" * 120, True)

    def test_no_bearer_is_401(self, client: FlaskClient) -> None:
        response = client.post(DEBRIEF, json=_DEBRIEF)

        assert response.status_code == 401

    @pytest.mark.parametrize(
        ("kind", "state", "error"),
        [
            ("chat", SessionState.RUNNING, "is a chat session, not a work item's"),
            ("job", SessionState.RUNNING, "is a job session, not a work item's"),
            ("work", SessionState.IDLE, "has no turn running"),
        ],
        ids=["chat", "job", "turn-ended"],
    )
    def test_a_session_that_is_not_a_running_work_items_is_403_and_stores_nothing(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        kind: str,
        state: SessionState,
        error: str,
    ) -> None:
        """DB 323: only a work item's own Session gives its debrief, while
        its turn runs; a job gives none."""
        run = _session(session, container, project, environment, kind, state)

        response = client.post(DEBRIEF, json=_DEBRIEF, headers=_bearer())

        assert response.status_code == 403
        assert response.get_json()["error"] == (
            f"Cannot call pilot-work because session {run.id} {error}"
        )
        assert session.scalars(select(DebriefEntry)).all() == []
        assert session.scalars(select(Work.debrief)).all() == [None] * len(
            session.scalars(select(Work.id)).all()
        )


class TestSetProgressStep:
    """`PATCH /tools/pilot-work/progress`: `set_progress_step(code, state)`."""

    def test_the_steps_state_set_is_200_with_the_list_as_it_stands(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        client.put(PROGRESS, json=_PUBLISHED, headers=_bearer())

        response = client.patch(
            PROGRESS, json={"code": "P1.review", "state": "done"}, headers=_bearer()
        )

        assert response.status_code == 200
        assert [step["state"] for step in response.get_json()["steps"]] == [
            "done",
            "done",
            "pending",
        ]
        assert _steps(session, run)[1] == (
            "P1.review",
            "P1 · review",
            ProgressState.DONE,
        )

    def test_a_code_not_on_the_list_is_404_and_changes_nothing(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        client.put(PROGRESS, json=_PUBLISHED, headers=_bearer())

        response = client.patch(
            PROGRESS, json={"code": "docs", "state": "active"}, headers=_bearer()
        )

        assert response.status_code == 404
        assert response.get_json()["error"] == "Progress step docs was not found"
        assert [state for _, _, state in _steps(session, run)] == [
            ProgressState.DONE,
            ProgressState.ACTIVE,
            ProgressState.PENDING,
        ]

    @pytest.mark.parametrize(
        "body",
        [
            {"code": "test"},
            {"code": "test", "state": "skipped"},
            {"code": "", "state": "done"},
            {"state": "done"},
        ],
        ids=["no-state", "state", "empty-code", "no-code"],
    )
    def test_a_body_that_is_not_a_code_and_a_state_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        body: dict[str, str],
    ) -> None:
        run = _session(session, container, project, environment)
        client.put(PROGRESS, json=_PUBLISHED, headers=_bearer())

        response = client.patch(PROGRESS, json=body, headers=_bearer())

        assert response.status_code == 400
        assert _steps(session, run)[2][2] == ProgressState.PENDING

    def test_no_bearer_is_401(self, client: FlaskClient) -> None:
        response = client.patch(PROGRESS, json={"code": "test", "state": "done"})

        assert response.status_code == 401

    def test_a_session_whose_turn_has_ended_is_403_and_changes_nothing(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        client.put(PROGRESS, json=_PUBLISHED, headers=_bearer())
        run.state_code = SessionState.IDLE
        session.flush()

        response = client.patch(
            PROGRESS, json={"code": "test", "state": "active"}, headers=_bearer()
        )

        assert response.status_code == 403
        assert _steps(session, run)[2][2] == ProgressState.PENDING


class TestTheProgressRecordsNothing:
    """Neither progress call nor the debrief's records an Effect or a line of
    the server's in the session's records, its turn in flight (F145.4; DB
    289, 328)."""

    def test_neither_call_writes_an_effect_or_a_record(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        session.add(
            Turn(
                session_id=run.id,
                seq=1,
                message="Refine the camp.",
                started_at=datetime.now(UTC),
                cause_code=TurnCause.BRIEF,
            )
        )
        session.flush()
        tool_use = {"Tool-Use-Id": "toolu_01ABC"}

        published = client.put(PROGRESS, json=_PUBLISHED, headers=_bearer() | tool_use)
        moved = client.patch(
            PROGRESS,
            json={"code": "test", "state": "active"},
            headers=_bearer() | tool_use,
        )

        assert (published.status_code, moved.status_code) == (200, 200)
        assert read_records(session, run.id, limit=10) == []
        assert session.scalars(select(Effect)).all() == []

    def test_the_debrief_writes_no_effect_or_record(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        session.add(
            Turn(
                session_id=run.id,
                seq=1,
                message="Refine the camp.",
                started_at=datetime.now(UTC),
                cause_code=TurnCause.BRIEF,
            )
        )
        session.flush()

        response = client.post(
            DEBRIEF, json=_DEBRIEF, headers=_bearer() | {"Tool-Use-Id": "toolu_01ABC"}
        )

        assert response.status_code == 201
        assert read_records(session, run.id, limit=10) == []
        assert session.scalars(select(Effect)).all() == []


class TestTheToolUseId:
    """The `Tool-Use-Id` header Pilot's MCP server passes names the call in
    its effect's record (F41)."""

    def _turn_in_flight(self, session: DbSession, run: models.Session) -> None:
        session.add(
            Turn(
                session_id=run.id,
                seq=1,
                message="Refine the camp.",
                started_at=datetime.now(UTC),
                cause_code=TurnCause.BRIEF,
            )
        )
        session.flush()

    def test_a_registration_names_its_call(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        self._turn_in_flight(session, run)
        _file(fake_controller, environment)

        response = client.post(
            DOCUMENTS,
            json={"path": PATH},
            headers=_bearer() | {"Tool-Use-Id": "toolu_01ABC"},
        )

        assert response.status_code == 201
        [record] = read_records(session, run.id, limit=10)
        assert record.record.payload == {
            "type": "effect",
            "toolUseId": "toolu_01ABC",
            "effect": {
                "verb": "Registered",
                "label": "inbox/2",
                "itemId": response.get_json()["id"],
            },
        }

    def test_an_attachment_without_the_header_names_no_call(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        self._turn_in_flight(session, run)
        _file(fake_controller, environment)

        response = client.post(ATTACHMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 201
        [record] = read_records(session, run.id, limit=10)
        assert record.record.payload["toolUseId"] is None
        assert record.record.payload["effect"]["verb"] == "Attached"
