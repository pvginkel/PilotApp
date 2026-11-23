"""/api/dashboard/catalogue, what a view of the dashboard may name, a part
at a call (F154.4), with what the dashboard stores (F155);
/api/dashboard/address, a view's state checked and written back in its
normal form (F159); /api/dashboard/rows, a view's rows (F154.1);
/api/dashboard/series and /api/dashboard/series/events, a view's series and
its events strip (F163.3, F164.6); /api/dashboard/lanes, a view's lanes
(F164.6); /api/dashboard/items and a conversation's calls, a view's items
(F165); /api/dashboard/counts/attributes and
/api/dashboard/counts/quick-filters, a view's two counts, each started as a
task whose events reach the caller's stream alone (F154.6); and
/api/dashboard/values, an attribute's values for a filter's pane."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from queue import Empty
from typing import Any

import pytest
from dependency_injector import providers
from flask import Flask
from flask.testing import FlaskClient
from pilot_collection.reading import ReadingSchema
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard.bounds import Bounds
from app.dashboard.views import VIEWS
from app.database import scoped_session
from app.models import (
    Component,
    CustomRatio,
    Environment,
    EventKind,
    Project,
    QuickFilter,
    SavedView,
    User,
)
from app.models.reference import Origin, SessionState, UserKind
from app.services.container import ServiceContainer
from app.services.sse_connection_manager import SSEConnection
from tests.support import transcripts
from tests.support.dashboard import Record, record
from tests.support.fake_collector import ServedFakeCollector
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.transcripts import OPUS, STARTED, reference

CATALOGUE = "/api/dashboard/catalogue"
SAVED_AT = datetime(2026, 11, 20, 9, 30, tzinfo=UTC)


def _part(client: FlaskClient, part: str) -> dict[str, Any]:
    response = client.get(CATALOGUE, query_string={"part": part})
    assert response.status_code == 200
    body: dict[str, Any] = response.get_json()
    return body


def _by_key(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {entry["key"]: entry for entry in entries}


class TestGetCatalogue:
    def test_a_part_carries_its_own_fields_and_the_others_null(
        self, client: FlaskClient
    ) -> None:
        fields = {
            "dimensions": {"dimensions", "markers"},
            "measures": {"facts", "figures", "aggregates", "grains", "ratios"},
            "time": {"ranges", "zone", "sitting_gap_seconds"},
            "stored": {"saved_views", "quick_filters", "custom_ratios"},
        }

        for part, own in fields.items():
            body = _part(client, part)

            assert body["part"] == part
            assert {key for key, value in body.items() if value is not None} == own | {
                "part"
            }
            assert set(body) == {"part"}.union(*fields.values())

    def test_the_dimensions(self, client: FlaskClient) -> None:
        dimensions = _by_key(_part(client, "dimensions")["dimensions"])

        assert dimensions["project"] == {
            "key": "project",
            "label": "Project",
            "group": "part",
            "line": (
                "The project a Session of Pilot's worked, or the adopted one a "
                "thread is of"
            ),
            "null": "(No project)",
            "facts": ["call", "turn", "event"],
            "values": None,
            "one": "project",
            "many": "projects",
            "next": "psession",
            "next_null": "sitting",
            "base": None,
            "focus": True,
            "unit": None,
        }
        assert dimensions["session_start"]["base"] == "psession"
        assert {
            key: one["unit"]
            for key, one in dimensions.items()
            if one["group"] == "time"
        } == {"qweek": "quota_week", "day": "day", "weekday": None, "hod": None}
        assert [key for key, one in dimensions.items() if one["focus"]] == [
            "project",
            "psession",
        ]
        assert dimensions["miss"]["values"] == [
            {
                "code": "1",
                "name": "Cache miss",
                "line": None,
                "position": None,
                "is_error": None,
            },
            {
                "code": "0",
                "name": "No miss",
                "line": None,
                "position": None,
                "is_error": None,
            },
        ]
        assert {dimension["group"] for dimension in dimensions.values()} == {
            "part",
            "attribute",
            "time",
            "order",
        }

    def test_the_event_kinds_say_which_are_errors(
        self, client: FlaskClient, session: DbSession
    ) -> None:
        reference(session, EventKind, "api_error", is_error=True)

        dimensions = _by_key(_part(client, "dimensions")["dimensions"])

        errors = {
            kind["code"]
            for kind in dimensions["event_kind"]["values"]
            if kind["is_error"]
        }
        assert errors == {
            "api_error",
            "hook_error",
            "max_tokens",
            "model_fallback",
            "refusal",
        }

    def test_a_components_version_is_a_dimension(
        self, client: FlaskClient, session: DbSession
    ) -> None:
        session.add(Component(code="claude-code", name="Claude Code"))
        session.flush()

        dimensions = _by_key(_part(client, "dimensions")["dimensions"])

        assert dimensions["claude_code_version"]["label"] == "Claude Code version"
        assert dimensions["claude_code_version"]["facts"] == ["call", "event"]

    def test_a_components_version_is_a_kind_of_marker(
        self, client: FlaskClient, session: DbSession, container: ServiceContainer
    ) -> None:
        assert _part(client, "dimensions")["markers"] == []
        session.add(Component(code="claude-code", name="Claude Code"))
        session.flush()
        container.catalogue_service().drop()

        assert _part(client, "dimensions")["markers"] == [
            {
                "key": "claude_code_version",
                "label": "Claude Code version",
                "line": "Where a version of Claude Code was first seen",
                "dimension": "claude_code_version",
            }
        ]

    def test_the_measures(self, client: FlaskClient) -> None:
        body = _part(client, "measures")

        assert body["facts"] == [
            {"key": "call", "label": "Calls", "counts": "calls", "grain": "call"},
            {
                "key": "turn",
                "label": "Pilot turns",
                "counts": "turns",
                "grain": "pturn",
            },
            {"key": "event", "label": "Events", "counts": "events", "grain": "event"},
        ]
        figures = _by_key(body["figures"])
        assert figures["tokens"] == {
            "key": "tokens",
            "label": "Tokens",
            "fact": "call",
            "line": (
                "The tokens a Call counts: read fresh, written to the cache, "
                "read from it and written by the model"
            ),
            "format": "tokens",
            "aggregate": "sum",
            "aggregates": ["sum", "median", "mean", "max", "p90"],
            "token_kinds": ["input", "cache_write", "cache_read", "output"],
            "stacks": True,
        }
        assert figures["calls"]["aggregates"][-1] == "count"
        assert figures["reported_cost"]["fact"] == "turn"
        assert [aggregate["key"] for aggregate in body["aggregates"]] == [
            "sum",
            "median",
            "mean",
            "max",
            "p90",
            "count",
        ]
        grains = _by_key(body["grains"])
        assert grains["conversation"] == {
            "key": "conversation",
            "one": "conversation",
            "many": "conversations",
            "figures": ["calls", "cost", "tokens", "misses", "miss_cost", "ctx"],
            "shows": [],
        }
        assert grains["call"]["shows"] == [
            "model",
            "effort",
            "miss",
            "miss_cause",
            "rewind",
            "compaction",
            "estimate",
        ]
        assert grains["event"]["shows"] == ["event_kind", "event_error"]
        assert body["ratios"] == [
            {
                "key": "overhead",
                "label": "Overhead ratio",
                "line": (
                    "The cost of Pilot's chats, jobs and runs over the cost of "
                    "its work items; what ran outside Pilot is in neither"
                ),
                "format": "share",
                "numerator": "cost.sum(source=chat|pilot)",
                "denominator": "cost.sum(source=work)",
                "origin": None,
            },
            {
                "key": "miss_share",
                "label": "Miss-cost share",
                "line": "The cost of the cache misses over the cost of all",
                "format": "share",
                "numerator": "miss_cost.sum",
                "denominator": "cost.sum",
                "origin": None,
            },
            {
                "key": "per_call",
                "label": "Cost per call",
                "line": "The cost over the number of Calls",
                "format": "usd",
                "numerator": "cost.sum",
                "denominator": "calls.count",
                "origin": None,
            },
        ]

    def test_an_items_figures_and_dimensions_are_the_catalogues(
        self, client: FlaskClient
    ) -> None:
        body = _part(client, "measures")
        figures = _by_key(body["figures"])
        dimensions = _by_key(_part(client, "dimensions")["dimensions"])

        for grain in body["grains"]:
            assert set(grain["figures"]) <= set(figures), grain["key"]
            assert set(grain["shows"]) <= set(dimensions), grain["key"]

    def test_the_time(self, client: FlaskClient) -> None:
        body = _part(client, "time")

        assert body["zone"] == "Europe/Amsterdam"
        assert body["sitting_gap_seconds"] == 14400
        assert body["ranges"][0] == {
            "key": "today",
            "label": "Today",
            "line": "Today, from midnight",
        }
        assert [range_["key"] for range_ in body["ranges"]] == [
            "today",
            "d2",
            "d7",
            "qw",
            "lqw",
            "l2",
            "l4",
            "l8",
            "all",
        ]

    def test_what_it_stores(self, client: FlaskClient, session: DbSession) -> None:
        session.add(
            SavedView(
                origin_code=Origin.PERSON,
                name="Projects",
                state="t=d7&by=model&m=cost.sum&col=none",
                saved_at=SAVED_AT,
            )
        )
        session.flush()

        body = _part(client, "stored")

        views = body["saved_views"]
        assert [(view["system"], view["name"]) for view in views] == [
            (True, "Projects"),
            (True, "Where the week went"),
            (True, "Work types"),
            (False, "Projects"),
        ]
        assert {key: value for key, value in views[0].items() if key != "saved_at"} == {
            "id": views[0]["id"],
            "system": True,
            "origin": "pilot",
            "key": "projects",
            "name": "Projects",
            "address": "#dash/" + VIEWS[0].state,
            "note": VIEWS[0].note,
        }
        assert views[-1]["origin"] == "person"
        assert views[-1]["key"] is None
        assert views[-1]["address"] == "#dash/t=d7&by=model&m=cost.sum&col=none"
        assert views[-1]["saved_at"] == "2026-11-20T09:30:00Z"
        quick_filters = _by_key(body["quick_filters"])
        assert list(quick_filters) == [
            "compactions",
            "expensive",
            "misses",
            "outliers",
            "past_ttl",
        ]
        assert {
            key: value
            for key, value in quick_filters["past_ttl"].items()
            if key not in ("id", "saved_at")
        } == {
            "key": "past_ttl",
            "label": "Waits past the cache TTL",
            "condition": "past_ttl:1",
            "marks": False,
            "amount": "miss_cost",
            "note": (
                "The Calls that waited longer than the cache their predecessor "
                "wrote lives; the amount is the cost of those that missed it"
            ),
            "offered": True,
        }
        assert body["custom_ratios"] == []

    def test_a_stored_ratio_is_a_measure_with_its_origin(
        self, client: FlaskClient, session: DbSession
    ) -> None:
        session.add(
            CustomRatio(
                origin_code=Origin.PERSON,
                key="person_per_turn",
                name="Cost per turn",
                numerator="reported_cost.sum",
                denominator="turns.count",
                saved_at=SAVED_AT,
            )
        )
        session.flush()

        ratios = _part(client, "measures")["ratios"]

        assert ratios[-1] == {
            "key": "person_per_turn",
            "label": "Cost per turn",
            "line": None,
            "format": "usd",
            "numerator": "reported_cost.sum",
            "denominator": "turns.count",
            "origin": "person",
        }

    def test_what_it_stores_that_no_longer_reads_is_listed_not_offered(
        self, client: FlaskClient, session: DbSession
    ) -> None:
        """A row the catalogue leaves out still holds its key and its name, so
        that the screen shows it, and anyone may remove a person's."""
        session.add_all(
            [
                CustomRatio(
                    origin_code=Origin.PERSON,
                    key="person_per_crate",
                    name="Cost per crate",
                    numerator="cost.sum",
                    denominator="crates.count",
                    saved_at=SAVED_AT,
                ),
                QuickFilter(
                    code="crates",
                    label="Crates",
                    condition="crate:1",
                    marks=False,
                    saved_at=datetime.now(UTC),
                ),
            ]
        )
        session.flush()

        body = _part(client, "stored")

        assert [(one["key"], one["offered"]) for one in body["custom_ratios"]] == [
            ("person_per_crate", False)
        ]
        assert body["quick_filters"][-1]["key"] == "crates"
        assert not body["quick_filters"][-1]["offered"]
        assert all(one["offered"] for one in body["quick_filters"][:-1])
        ratios = [ratio["key"] for ratio in _part(client, "measures")["ratios"]]
        assert "person_per_crate" not in ratios

    @pytest.mark.parametrize("query", [{}, {"part": "views"}, {"part": ""}])
    def test_no_part_or_one_it_has_not_is_refused(
        self, client: FlaskClient, query: dict[str, str]
    ) -> None:
        assert client.get(CATALOGUE, query_string=query).status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert client.get(CATALOGUE, query_string={"part": "time"}).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert (
            oidc_client.get(CATALOGUE, query_string={"part": "time"}).status_code == 401
        )


ADDRESS = "/api/dashboard/address"


class TestGetAddress:
    def test_it_answers_the_normal_form_its_look_and_its_notes(
        self, client: FlaskClient
    ) -> None:
        response = client.get(
            ADDRESS, query_string={"state": "m=cost&m=r:gone&rel=1&by=psession"}
        )

        assert response.status_code == 200
        assert response.get_json() == {
            "address": "#dash/t=qw&by=psession&m=cost.sum&col=none&rel=1",
            "look": ["rel=1"],
            "notes": [
                'm=r:gone: no ratio has the key "gone", so the measure is dropped.'
            ],
        }

    def test_an_address_is_read_as_its_state(self, client: FlaskClient) -> None:
        body = client.get(
            ADDRESS, query_string={"state": "#dash/t=all&by=model"}
        ).get_json()

        assert body["address"] == "#dash/t=all&by=model&m=cost.sum&col=none"

    def test_it_fixes_the_time_on_request(self, client: FlaskClient) -> None:
        body = client.get(
            ADDRESS, query_string={"state": "t=lqw", "fix_time": "true"}
        ).get_json()

        assert body["address"].startswith("#dash/t=wk,")
        assert body["address"].endswith("&by=project&m=cost.sum&col=none")

    def test_it_fills_in_an_entry(self, client: FlaskClient) -> None:
        key = "5b0e6a4c-2f4a-4d7e-9b1e-0c3f0c7c1a2b"

        body = client.get(
            ADDRESS, query_string={"state": f"f=project:{key}"}
        ).get_json()

        assert body["address"] == (
            f"#dash/t=all&by=psession&m=cost.sum&m=misses.sum"
            f"&dr=project:{key}@project&col=none&f=project:{key}"
        )

    def test_a_state_with_faults_is_refused_with_its_text(
        self, client: FlaskClient
    ) -> None:
        response = client.get(ADDRESS, query_string={"state": "by=phases&rel=2"})

        assert response.status_code == 400
        body = response.get_json()
        assert body["code"] == "STATE_REFUSED"
        assert body["error"].splitlines() == [
            "Cannot read the view because its state has 2 faults.",
            '- by=phases: "phases" is no dimension. By takes a part or an '
            "attribute; the catalogue's dimensions list them.",
            '- rel=2: "2" is no switch. rel takes 1.',
            "A By reads by=<dimension>, as in by=project.",
            "Relative reads rel=1, as in rel=1.",
        ]

    def test_a_number_no_double_holds_is_refused(self, client: FlaskClient) -> None:
        response = client.get(ADDRESS, query_string={"state": "z=nan,1"})

        assert response.status_code == 400
        assert response.get_json()["code"] == "STATE_REFUSED"

    def test_no_state_is_refused(self, client: FlaskClient) -> None:
        assert client.get(ADDRESS).status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert client.get(ADDRESS, query_string={"state": ""}).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(ADDRESS, query_string={"state": ""}).status_code == 401


ROWS = "/api/dashboard/rows"


@pytest.fixture
def worked(
    session: DbSession, person: User, project: Project, project_session: models.Session
) -> Record:
    return record(session, person, project, project_session)


class TestGetRows:
    def test_it_answers_the_rows_with_their_address(
        self, client: FlaskClient, worked: Record
    ) -> None:
        response = client.get(
            ROWS,
            query_string={
                "state": "t=c,2026-11-12,2026-11-13&m=cost.sum&m=turns.count"
                "&col=model&rel=1"
            },
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["address"] == (
            "#dash/t=c,2026-11-12,2026-11-13&by=project&m=cost.sum&m=turns.count"
            "&col=model&rel=1"
        )
        assert (body["look"], body["notes"]) == (["rel=1"], [])
        assert body["zone"] == "Europe/Amsterdam"
        assert body["window"] == [
            {"start": "2026-11-11T23:00:00Z", "end": "2026-11-13T23:00:00Z"}
        ]
        assert body["by"] == {"key": "project", "label": "Project", "group": "part"}
        assert [
            (measure["key"], measure["aggregate"], measure["stacks"])
            for measure in body["measures"]
        ] == [("cost.sum", "sum", True), ("turns.count", "count", False)]
        assert body["color"]["key"] == "model"
        assert [value["key"] for value in body["color"]["values"]] == [OPUS, None]
        assert body["all"]["n"] == [6, 2]
        assert body["rows"][0] == {
            "key": str(worked.project.id),
            "label": "Recipe box",
            "focus": False,
            "values": [2.6, 2.0],
            "n": [5, 2],
            "split": [[1.85, 0.75], None],
            "marks": None,
            "marked": False,
        }
        assert body["rows"][1]["key"] is None
        assert body["total_rows"] == 2
        assert body["sort"] == {"direction": "desc", "column": "cost.sum"}
        assert [measure["stand_in"] for measure in body["measures"]] == [None, None]

    def test_a_marked_chip_marks_rows_and_their_parts(
        self, client: FlaskClient, worked: Record
    ) -> None:
        body = client.get(
            ROWS, query_string={"state": "t=all&by=psession&c=~miss:1"}
        ).get_json()

        rows = {row["key"]: row for row in body["rows"]}
        assert rows[str(worked.work.id)]["marked"] is True
        assert rows[str(worked.work.id)]["marks"] == [1.0]
        assert rows[str(worked.chat.id)]["marks"] == [0.0]
        assert body["all"]["marks"] == [1.0]

    def test_a_time_key_is_an_instant(
        self, client: FlaskClient, worked: Record
    ) -> None:
        body = client.get(ROWS, query_string={"state": "t=all&by=sitting"}).get_json()

        assert [row["key"] for row in body["rows"]] == [
            None,
            "2026-11-13T09:30:00Z",
        ]

    def test_a_state_with_faults_is_refused_with_its_text(
        self, client: FlaskClient
    ) -> None:
        response = client.get(ROWS, query_string={"state": "by=phases"})

        assert response.status_code == 400
        assert response.get_json()["code"] == "STATE_REFUSED"

    def test_a_view_past_the_engines_bounds_is_refused_with_why(
        self, client: FlaskClient, session: DbSession, worked: Record
    ) -> None:
        session.execute(
            text(
                """
                INSERT INTO calls (transcript_id, message_id, position, completed_at,
                    model_code, input_tokens, cache_write_5m_tokens,
                    cache_write_1h_tokens, cache_read_tokens, output_tokens, cost)
                SELECT :thread, 'msg_many_' || n, 100 + n, :at, :model, 1, 0, 0, 0,
                    1, n * 0.001
                FROM generate_series(1, 5000) AS n
                """
            ),
            {"thread": worked.thread.id, "at": STARTED, "model": OPUS},
        )
        session.execute(text("SET LOCAL work_mem = '64kB'"))
        session.execute(text("SET LOCAL temp_file_limit = '64kB'"))

        response = client.get(
            ROWS, query_string={"state": "t=all&by=call&m=cost.median"}
        )

        assert response.status_code == 409
        body = response.get_json()
        assert body["code"] == "QUERY_TEMP_FILE_LIMIT"
        assert body["error"] == (
            "Cannot answer the dashboard's view because a statement needed more "
            "temporary disk than the database allows one: a shorter time range or "
            "a narrower scope reads less"
        )

    def test_no_state_is_refused(self, client: FlaskClient) -> None:
        assert client.get(ROWS).status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert client.get(ROWS, query_string={"state": ""}).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(ROWS, query_string={"state": ""}).status_code == 401


SERIES = "/api/dashboard/series"
EVENTS = "/api/dashboard/series/events"


def _many_calls(db: DbSession, worked: Record) -> None:
    db.execute(
        text(
            """
            INSERT INTO calls (transcript_id, message_id, position, completed_at,
                model_code, input_tokens, cache_write_5m_tokens,
                cache_write_1h_tokens, cache_read_tokens, output_tokens, cost)
            SELECT :thread, 'msg_many_' || n, 100 + n, :at, :model, 1, 0, 0, 0,
                1, n * 0.001
            FROM generate_series(1, 5000) AS n
            """
        ),
        {"thread": worked.thread.id, "at": STARTED, "model": OPUS},
    )


class TestGetSeries:
    def test_it_answers_the_points_and_the_panels_with_their_address(
        self, client: FlaskClient, worked: Record
    ) -> None:
        response = client.get(
            SERIES,
            query_string={
                "state": "t=all&p=time,day&m=cost.sum&m=cost.max.conversation&rel=1"
            },
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["address"] == (
            "#dash/t=all&by=project&p=time,day&m=cost.sum&m=cost.max.conversation"
            "&col=none&rel=1"
        )
        assert (body["look"], body["notes"]) == (["rel=1"], [])
        assert (body["zone"], body["window"], body["presentation"]) == (
            "Europe/Amsterdam",
            None,
            "time",
        )
        assert body["by"] == {"key": "day", "label": "Day", "group": "time"}
        assert body["roll"] == {"read": 10, "before": 15}
        assert body["points"][0] == {
            "key": "2026-11-12",
            "label": None,
            "focus": False,
            "values": [2.6, 1.75],
            "n": [5, 2],
            "split": None,
            "marks": None,
            "marked": False,
            "axis": None,
            "starts_at": "2026-11-11T23:00:00Z",
            "ends_at": "2026-11-12T23:00:00Z",
        }
        assert body["total_points"] == 2
        assert body["off_axis"] is None
        column, items = body["measures"]
        assert (column["key"], column["kind"], column["band"], column["dots"]) == (
            "cost.sum",
            "column",
            None,
            None,
        )
        assert (items["kind"], items["outliers"], items["before"], items["cut"]) == (
            "items",
            [],
            0,
            False,
        )
        assert items["band"] == [None, None, None]
        assert items["dots"][0] == {
            "point": 0,
            "key": str(worked.thread.id),
            "label": None,
            "value": 1.75,
            "at": "2026-11-12T09:31:00Z",
            "focus": False,
        }
        assert body["markers"] == []

    def test_a_band_and_a_marker_carry_their_numbers_and_times(
        self, client: FlaskClient, session: DbSession, worked: Record
    ) -> None:
        later = transcripts.component_version(session, "claude-code", "2.1.318")
        start = transcripts.launch(
            session, worked.loose, started_at=STARTED + timedelta(days=1)
        )
        session.add(
            models.LaunchComponent(
                launch_id=start.id,
                component_version_id=later.id,
                component_code="claude-code",
            )
        )
        worked.calls[4].launch_id = start.id
        worked.chat.created_at = worked.work.created_at + timedelta(hours=1)
        session.flush()

        body = client.get(
            SERIES, query_string={"state": "t=all&by=psession&p=order&roll=1,1"}
        ).get_json()

        assert body["by"]["key"] == "session_start"
        assert [point["key"] for point in body["points"]] == [
            str(worked.work.id),
            str(worked.chat.id),
        ]
        assert body["measures"][0]["band"] == [
            None,
            {"first": 1.85, "median": 1.85, "third": 1.85},
        ]
        body = client.get(SERIES, query_string={"state": "t=all&p=time,day"}).get_json()
        assert body["markers"] == [
            {
                "kind": "claude_code_version",
                "value": "2.1.318",
                "before": "2.1.317",
                "at": "2026-11-13T09:30:00Z",
            }
        ]

    def test_a_view_with_no_series_is_refused_with_its_text(
        self, client: FlaskClient
    ) -> None:
        response = client.get(SERIES, query_string={"state": "t=all&by=project"})

        assert response.status_code == 400
        body = response.get_json()
        assert body["code"] == "STATE_REFUSED"
        assert body["error"].splitlines()[1].startswith("- p=rows: the view draws rows")

    def test_a_view_past_the_engines_bounds_is_refused_with_why(
        self, client: FlaskClient, session: DbSession, worked: Record
    ) -> None:
        _many_calls(session, worked)
        session.execute(text("SET LOCAL work_mem = '64kB'"))
        session.execute(text("SET LOCAL temp_file_limit = '64kB'"))

        response = client.get(
            SERIES, query_string={"state": "t=all&p=time,day&m=cost.median"}
        )

        assert response.status_code == 409
        assert response.get_json()["code"] == "QUERY_TEMP_FILE_LIMIT"

    def test_no_state_is_refused(self, client: FlaskClient) -> None:
        assert client.get(SERIES).status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert client.get(SERIES, query_string={"state": "p=time"}).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert (
            oidc_client.get(SERIES, query_string={"state": "p=time"}).status_code == 401
        )


class TestGetSeriesEvents:
    def test_it_answers_each_points_events_by_kind(
        self, client: FlaskClient, worked: Record
    ) -> None:
        response = client.get(
            EVENTS, query_string={"state": "t=all&p=time,day&ev=-cache_miss"}
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["address"] == (
            "#dash/t=all&by=project&p=time,day&m=cost.sum&col=none&ev=-cache_miss"
        )
        assert (body["look"], body["notes"]) == (["ev=-cache_miss"], [])
        assert body["by"] == {"key": "day", "label": "Day", "group": "time"}
        assert body["kinds"][0] == {
            "key": "api_error",
            "label": "api_error",
            "is_error": True,
            "total": 1,
        }
        assert [kind["is_error"] for kind in body["kinds"]] == [True] * 4 + [False] * 6
        assert body["buckets"] == [
            {"key": "2026-11-12", "counts": [1] * 10, "errors": 4}
        ]
        assert body["refused"] is None
        assert (body["zone"], body["window"]) == ("Europe/Amsterdam", None)

    def test_a_view_with_no_series_is_refused_with_its_text(
        self, client: FlaskClient
    ) -> None:
        response = client.get(EVENTS, query_string={"state": "p=lanes&by=call"})

        assert response.status_code == 400
        assert response.get_json()["code"] == "STATE_REFUSED"

    def test_a_strip_past_the_engines_bounds_is_refused_with_why(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        worked: Record,
    ) -> None:
        bounds = Bounds(timeout_seconds=0.2, at_once=1, pool=5)
        bind = session.get_bind()
        assert not isinstance(bind, Engine)
        other = DbSession(bind=bind.engine)
        try:
            with (
                container.dashboard_bounds.override(providers.Object(bounds)),
                bounds.read(other),
            ):
                response = client.get(EVENTS, query_string={"state": "p=time"})
        finally:
            other.close()

        assert response.status_code == 409
        assert response.get_json()["code"] == "QUERY_BUSY"

    def test_no_state_is_refused(self, client: FlaskClient) -> None:
        assert client.get(EVENTS).status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert client.get(EVENTS, query_string={"state": "p=time"}).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert (
            oidc_client.get(EVENTS, query_string={"state": "p=time"}).status_code == 401
        )


LANES = "/api/dashboard/lanes"
ITEMS = "/api/dashboard/items"


def _calls_path(thread: object) -> str:
    return f"/api/dashboard/conversations/{thread}/calls"


def _busy(
    client: FlaskClient,
    container: ServiceContainer,
    session: DbSession,
    path: str,
    state: str,
) -> Any:
    """The answer to a read while the engine's one slot is held."""
    bounds = Bounds(timeout_seconds=0.2, at_once=1, pool=5)
    bind = session.get_bind()
    assert not isinstance(bind, Engine)
    other = DbSession(bind=bind.engine)
    try:
        with (
            container.dashboard_bounds.override(providers.Object(bounds)),
            bounds.read(other),
        ):
            return client.get(path, query_string={"state": state})
    finally:
        other.close()


class TestGetLanes:
    def test_it_answers_each_lane_its_waits_and_its_events(
        self, client: FlaskClient, worked: Record
    ) -> None:
        response = client.get(LANES, query_string={"state": "t=all&p=lanes&z=1,2"})

        assert response.status_code == 200
        body = response.get_json()
        assert body["address"] == (
            "#dash/t=all&by=project&p=lanes&m=cost.sum&col=none&z=1,2"
        )
        assert (body["look"], body["notes"]) == (["z=1,2"], [])
        assert body["by"] == {"key": "project", "label": "Project", "group": "part"}
        assert (body["total_lanes"], body["wait_seconds"], body["resolution"]) == (
            2,
            60.0,
            None,
        )
        assert (body["starts_at"], body["ends_at"]) == (
            "2026-11-12T09:31:00Z",
            "2026-11-13T09:30:00Z",
        )
        assert body["weeks"] == ["2026-11-12T10:00:00Z"]
        assert body["kinds"][0] == {
            "key": "api_error",
            "label": "api_error",
            "is_error": True,
            "total": 1,
        }
        lane = body["lanes"][0]
        assert (lane["key"], lane["label"], lane["values"]) == (
            str(worked.project.id),
            "Recipe box",
            [2.6],
        )
        assert (lane["starts_at"], lane["ends_at"]) == (
            "2026-11-12T09:31:00Z",
            "2026-11-12T11:33:00Z",
        )
        assert lane["waits"][0] == {
            "starts_at": "2026-11-12T09:31:00Z",
            "ends_at": "2026-11-12T09:32:00Z",
            "conversation": str(worked.thread.id),
            "call": worked.calls[1].id,
            "past_ttl": False,
            "n": 1,
        }
        error = lane["events"][0]
        assert error == {
            "at": "2026-11-12T09:31:30Z",
            "kind": "api_error",
            "is_error": True,
            "key": error["key"],
            "conversation": str(worked.thread.id),
            "call": worked.calls[0].id,
            "cost": 0.5,
            "detail": {
                "qualifier": "529",
                "tool": None,
                "characters": None,
                "denial": None,
                "command": None,
                "trigger": None,
                "model": None,
            },
            "n": 1,
        }
        assert error["key"].startswith("api_error:")

    def test_a_view_not_in_lanes_is_refused_with_its_text(
        self, client: FlaskClient
    ) -> None:
        response = client.get(LANES, query_string={"state": "p=table"})

        assert response.status_code == 400
        body = response.get_json()
        assert body["code"] == "STATE_REFUSED"
        assert body["error"].splitlines()[1] == (
            "- p=table: the view draws a table, and only a view in lanes has lanes. "
            "Lanes take p=lanes, with a By that is a part."
        )

    def test_lanes_past_the_engines_bounds_are_refused_with_why(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        worked: Record,
    ) -> None:
        response = _busy(client, container, session, LANES, "p=lanes")

        assert response.status_code == 409
        assert response.get_json()["code"] == "QUERY_BUSY"

    def test_no_state_is_refused(self, client: FlaskClient) -> None:
        assert client.get(LANES).status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert client.get(LANES, query_string={"state": "p=lanes"}).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert (
            oidc_client.get(LANES, query_string={"state": "p=lanes"}).status_code == 401
        )


class TestGetItems:
    def test_it_answers_the_items_of_the_row_selected_with_their_columns(
        self, client: FlaskClient, worked: Record
    ) -> None:
        response = client.get(
            ITEMS,
            query_string={
                "state": f"t=all&d=items&sel={worked.project.id}&ig=conversation"
            },
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["address"] == (
            "#dash/t=all&by=project&m=cost.sum&col=none&d=items"
            f"&sel={worked.project.id}&ig=conversation"
        )
        assert body["look"] == ["d=items"]
        assert body["grain"]["key"] == "conversation"
        assert body["by"] == {"key": "project", "label": "Project", "group": "part"}
        assert body["selected"] == {"key": str(worked.project.id)}
        assert body["opened"] is None
        assert body["figures"][2] == {
            "key": "tokens",
            "label": "Tokens",
            "format": "tokens",
            "kinds": ["input", "cache_write", "cache_read", "output"],
        }
        assert body["shows"] == []
        assert body["total"] == 3
        assert body["items"][0] == {
            "key": str(worked.thread.id),
            "label": None,
            "first": "2026-11-12T09:31:00Z",
            "last": "2026-11-12T09:33:00Z",
            "values": [3.0, 1.75, 166_488.0, 1.0, 1.0, 52_626.0],
            "kinds": [
                None,
                None,
                [3_612.0, 9_930.0, 144_336.0, 8_610.0],
                None,
                None,
                None,
            ],
            "shown": [],
            "focus": False,
            "conversation": None,
            "session": None,
            "turn_seq": None,
            "call": None,
            "detail": None,
        }

    def test_a_call_carries_what_it_shows_and_an_event_its_detail(
        self, client: FlaskClient, worked: Record
    ) -> None:
        calls = client.get(ITEMS, query_string={"state": "t=all&ig=call"}).get_json()
        events = client.get(ITEMS, query_string={"state": "t=all&ig=event"}).get_json()

        assert [dimension["key"] for dimension in calls["shows"]][:2] == [
            "model",
            "effort",
        ]
        first = calls["items"][0]
        assert (first["key"], first["call"], first["session"], first["turn_seq"]) == (
            worked.calls[0].id,
            worked.calls[0].id,
            str(worked.work.id),
            1,
        )
        assert first["shown"][:2] == [
            {"key": OPUS, "label": OPUS},
            {"key": "high", "label": None},
        ]
        assert events["items"][0]["detail"]["qualifier"] == "529"
        assert events["items"][0]["shown"] == [
            {"key": "api_error", "label": "api_error"},
            {"key": 1, "label": "Error"},
        ]

    def test_a_state_with_faults_is_refused_with_its_text(
        self, client: FlaskClient
    ) -> None:
        response = client.get(ITEMS, query_string={"state": "it=event,a%2Cb"})

        assert response.status_code == 400
        assert response.get_json()["code"] == "STATE_REFUSED"

    def test_items_past_the_engines_bounds_are_refused_with_why(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        worked: Record,
    ) -> None:
        response = _busy(client, container, session, ITEMS, "ig=call")

        assert response.status_code == 409
        assert response.get_json()["code"] == "QUERY_BUSY"

    def test_no_state_is_refused(self, client: FlaskClient) -> None:
        assert client.get(ITEMS).status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert client.get(ITEMS, query_string={"state": "t=qw"}).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(ITEMS, query_string={"state": "t=qw"}).status_code == 401


class TestGetConversationCalls:
    def test_it_answers_every_call_with_its_events_and_whether_the_view_holds_it(
        self, client: FlaskClient, worked: Record
    ) -> None:
        response = client.get(
            _calls_path(worked.thread.id), query_string={"state": "t=all&c=miss:1"}
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["address"] == "#dash/t=all&by=project&m=cost.sum&c=miss:1&col=none"
        assert body["conversation"] == str(worked.thread.id)
        assert body["total"] == 3
        assert [call["position"] for call in body["calls"]] == [1, 2, 3]
        assert [call["in_scope"] for call in body["calls"]] == [False, False, True]
        second = body["calls"][1]
        # waited, took
        assert second["values"][3:] == [30.0, 30.0]
        assert second["kinds"][1] == [1_204.0, 3_310.0, 48_112.0, 2_870.0]
        assert [event["kind"] for event in second["events"]] == [
            "denied",
            "max_tokens",
            "model_fallback",
            "past_ttl",
            "rewind",
        ]
        fallback = second["events"][2]
        assert (fallback["label"], fallback["is_error"], fallback["at"]) == (
            "Model fallback",
            True,
            "2026-11-12T09:32:00Z",
        )
        assert fallback["detail"]["model"] == OPUS
        assert fallback["key"] == f"model_fallback:{worked.calls[1].id}"

    @pytest.mark.usefixtures("worked")
    def test_a_thread_the_record_does_not_hold_is_not_found(
        self, client: FlaskClient
    ) -> None:
        response = client.get(
            _calls_path("0b5e3c1a-7d42-4f6e-9a18-2c4d6e8f0a1b"),
            query_string={"state": "t=all"},
        )

        assert response.status_code == 404
        assert response.get_json()["code"] == "RECORD_NOT_FOUND"

    def test_a_state_with_faults_is_refused_with_its_text(
        self, client: FlaskClient, worked: Record
    ) -> None:
        response = client.get(
            _calls_path(worked.thread.id), query_string={"state": "t=never"}
        )

        assert response.status_code == 400
        assert response.get_json()["code"] == "STATE_REFUSED"

    def test_calls_past_the_engines_bounds_are_refused_with_why(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        worked: Record,
    ) -> None:
        response = _busy(
            client, container, session, _calls_path(worked.thread.id), "t=all"
        )

        assert response.status_code == 409
        assert response.get_json()["code"] == "QUERY_BUSY"

    def test_no_state_is_refused(self, client: FlaskClient, worked: Record) -> None:
        assert client.get(_calls_path(worked.thread.id)).status_code == 400

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, worked: Record
    ) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert (
            client.get(
                _calls_path(worked.thread.id), query_string={"state": "t=all"}
            ).status_code
            == 403
        )


def _reading_path(thread: object, route: str = "") -> str:
    return f"/api/dashboard/conversations/{thread}/reading{route}"


def _thread_reading(after: list[dict[str, Any]]) -> ReadingSchema:
    """A reading of the record's thread, each of its three Calls answered."""
    at = STARTED + timedelta(minutes=1)
    return ReadingSchema.model_validate(
        {
            "session_id": transcripts.CAMP,
            "agent_id": None,
            "file_size": 48_112,
            "file_modified_at": STARTED + timedelta(minutes=12),
            "calls": [
                {
                    "message_id": f"msg_{position:04}",
                    "received": [
                        {"kind": "user", "at": at, "writer": "person", "text": asked}
                    ],
                    "sent": [
                        {
                            "kind": "tool_call",
                            "at": at,
                            "tool_use_id": f"toolu_{position:02}",
                            "tool": "Bash",
                            "input": {"command": "make soup"},
                            "started": None,
                            "result": None,
                        }
                    ],
                }
                for position, asked in enumerate(
                    ("Halve the soup", "Now for two", "And the bread?"), start=1
                )
            ],
            "after": after,
        }
    )


@pytest.mark.usefixtures("readings_service")
class TestGetConversationReading:
    def test_it_answers_a_batch_of_calls_with_their_blocks_cut(
        self,
        client: FlaskClient,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        long = "a" * 1_501
        fake_collector.serve(
            _thread_reading(
                after=[
                    {
                        "kind": "user",
                        "at": STARTED + timedelta(minutes=4),
                        "writer": "person",
                        "text": long,
                    }
                ]
            )
        )
        third = worked.calls[2].id

        response = client.get(
            _reading_path(worked.thread.id),
            query_string={
                "state": f"t=all&it=conversation,{worked.thread.id}&call={third}"
            },
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["address"] == (
            "#dash/t=all&by=project&m=cost.sum&col=none"
            f"&it=conversation,{worked.thread.id}&call={third}"
        )
        assert (body["status"], body["why"], body["conversation"]) == (
            "served",
            None,
            str(worked.thread.id),
        )
        assert (body["total"], body["held"], body["stopped"]) == (3, 3, False)
        assert (body["batches"], body["batch"]) == ([0], 0)
        assert body["characters"] == 1_501 + 3 * len("make soup") + len(
            "Halve the soupNow for twoAnd the bread?"
        )
        assert body["whole"] is True
        assert [call["call"] for call in body["calls"]] == [
            call.id for call in worked.calls[:3]
        ]
        first = body["calls"][0]
        assert first["held"] is True
        assert first["received"] == [
            {
                "block": {
                    "kind": "user",
                    "at": "2026-11-12T09:31:00Z",
                    "writer": "person",
                    "text": "Halve the soup",
                },
                "length": None,
            }
        ]
        assert first["sent"][0]["block"]["input"] == {"command": "make soup"}
        (line,) = body["calls"][2]["after"]
        assert (len(line["block"]["text"]), line["length"]) == (1_500, 1_501)

    def test_it_answers_the_batch_asked(
        self,
        client: FlaskClient,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.serve(_thread_reading(after=[]))

        response = client.get(
            _reading_path(worked.thread.id),
            query_string={"state": "t=all", "batch": 1},
        )

        assert response.status_code == 200
        assert (response.get_json()["batch"], response.get_json()["calls"]) == (1, [])

    def test_a_transcript_gone_from_the_home_is_an_answer_of_its_own(
        self,
        client: FlaskClient,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        response = client.get(
            _reading_path(worked.thread.id), query_string={"state": "t=all"}
        )

        assert response.status_code == 200
        body = response.get_json()
        assert (body["status"], body["batches"], body["batch"], body["calls"]) == (
            "gone",
            [],
            None,
            [],
        )
        assert (body["characters"], body["whole"]) == (None, None)

    def test_a_refused_read_says_why(
        self,
        client: FlaskClient,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.refuse("unreadable")

        response = client.get(
            _reading_path(worked.thread.id), query_string={"state": "t=all"}
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "refused"
        assert body["why"].startswith("the collector answered 500")

    def test_it_answers_the_full_texts_in_one_answer(
        self,
        client: FlaskClient,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        long = "a" * 1_501
        fake_collector.serve(
            _thread_reading(
                after=[
                    {"kind": "user", "at": STARTED, "writer": "person", "text": long}
                ]
            )
        )

        response = client.get(
            _reading_path(worked.thread.id, "/texts"), query_string={"state": "t=all"}
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["whole"] is True
        assert [
            (text["call"], text["part"], text["index"], text["block"]["text"])
            for text in body["texts"]
        ] == [(worked.calls[2].id, "after", 0, long)]

    def test_it_answers_one_block_whole(
        self,
        client: FlaskClient,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.serve(_thread_reading(after=[]))
        fake_collector.too_large(transcripts.CAMP)

        response = client.get(
            _reading_path(worked.thread.id, "/block"),
            query_string={
                "state": "t=all",
                "call": worked.calls[2].id,
                "part": "after",
                "index": 0,
            },
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["whole"] is False
        assert (body["block"]["call"], body["block"]["part"]) == (
            worked.calls[2].id,
            "after",
        )
        assert len(body["block"]["block"]["text"]) == 3_000_000

    def test_a_block_the_reading_lacks_is_not_found(
        self,
        client: FlaskClient,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.serve(_thread_reading(after=[]))

        response = client.get(
            _reading_path(worked.thread.id, "/block"),
            query_string={
                "state": "t=all",
                "call": worked.calls[0].id,
                "part": "after",
                "index": 0,
            },
        )

        assert response.status_code == 404
        assert response.get_json()["code"] == "RECORD_NOT_FOUND"

    @pytest.mark.usefixtures("worked")
    @pytest.mark.parametrize("route", ["", "/texts", "/block"])
    def test_a_thread_the_record_does_not_hold_is_not_found(
        self, client: FlaskClient, route: str
    ) -> None:
        response = client.get(
            _reading_path("0b5e3c1a-7d42-4f6e-9a18-2c4d6e8f0a1b", route),
            query_string={"state": "t=all", "call": 1, "part": "sent", "index": 0},
        )

        assert response.status_code == 404
        assert response.get_json()["code"] == "RECORD_NOT_FOUND"

    @pytest.mark.parametrize("route", ["", "/texts", "/block"])
    def test_a_state_with_faults_is_refused_with_its_text(
        self, client: FlaskClient, worked: Record, route: str
    ) -> None:
        response = client.get(
            _reading_path(worked.thread.id, route),
            query_string={
                "state": "t=never",
                "call": worked.calls[0].id,
                "part": "sent",
                "index": 0,
            },
        )

        assert response.status_code == 400
        assert response.get_json()["code"] == "STATE_REFUSED"

    def test_a_block_with_no_place_is_refused(
        self, client: FlaskClient, worked: Record
    ) -> None:
        response = client.get(
            _reading_path(worked.thread.id, "/block"),
            query_string={"state": "t=all", "part": "elsewhere", "index": -1},
        )

        assert response.status_code == 400

    def test_a_read_past_the_engines_bounds_is_refused_with_why(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        worked: Record,
    ) -> None:
        response = _busy(
            client, container, session, _reading_path(worked.thread.id), "t=all"
        )

        assert response.status_code == 409
        assert response.get_json()["code"] == "QUERY_BUSY"

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient, worked: Record
    ) -> None:
        assert (
            oidc_client.get(
                _calls_path(worked.thread.id), query_string={"state": "t=all"}
            ).status_code
            == 401
        )


ATTRIBUTE_COUNTS = "/api/dashboard/counts/attributes"
QUICK_FILTER_COUNTS = "/api/dashboard/counts/quick-filters"
VALUES = "/api/dashboard/values"


@pytest.fixture
def committed(committed_app: Flask) -> Flask:
    """An app on a database of its own holding `record`'s record, committed,
    so that a task's thread reads it on a session of its own while the
    request that started it ends on another."""
    with scoped_session(committed_app.container) as db:
        person = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        db.add(person)
        db.flush()
        project = Project(created_by_user_id=person.id)
        environment = Environment(
            id=STORE_ENVIRONMENT_ID,
            name="Example-1",
            exempt=False,
            last_seen_at=datetime.now(UTC),
        )
        db.add_all([project, environment])
        db.flush()
        work = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Example",
            token_hash="1" * 64,
            state_code=SessionState.RUNNING,
        )
        db.add(work)
        db.flush()
        record(db, person, project, work)
    return committed_app


@pytest.fixture
def streams(committed: Flask) -> Iterator[dict[str, SSEConnection]]:
    """On the committed app, a stream of ada's, who asks, and one of ben's."""
    manager = committed.container.sse_connection_manager()
    opened = {
        subject: manager.on_connect(f"{subject}-1", subject)
        for subject in ("ada", "ben")
    }
    yield opened
    for connection in opened.values():
        manager.on_disconnect(connection)


def _sign_in(client: FlaskClient, subject: str) -> None:
    response = client.post(
        "/api/testing/auth/session", json={"subject": subject, "roles": ["editor"]}
    )
    assert response.status_code == 201, response.get_json()


def _task_events(connection: SSEConnection, task_id: str) -> list[dict[str, Any]]:
    """The task's events on the stream, up to its end."""
    events: list[dict[str, Any]] = []
    while not events or events[-1]["event_type"] not in (
        "task_completed",
        "task_failed",
    ):
        frame = connection.next_frame(timeout=30)
        assert frame is not None
        envelope = json.loads(frame.removeprefix("data: "))
        if (
            envelope["type"] == "task_event"
            and envelope["payload"]["task_id"] == task_id
        ):
            events.append(envelope["payload"])
    return events


def _queued(connection: SSEConnection) -> list[str]:
    frames = []
    while True:
        try:
            frame = connection.next_frame(timeout=0)
        except Empty:
            return frames
        assert frame is not None
        frames.append(frame)


class TestStartAttributeCounts:
    def test_it_answers_at_once_and_the_counts_come_to_the_caller_alone(
        self, committed: Flask, streams: dict[str, SSEConnection]
    ) -> None:
        client = committed.test_client()
        _sign_in(client, "ada")

        response = client.post(
            ATTRIBUTE_COUNTS, query_string={"state": "t=all&b=gone&rel=1"}
        )

        assert response.status_code == 202
        body = response.get_json()
        assert (body["address"], body["look"], body["status"]) == (
            "#dash/t=all&by=project&m=cost.sum&col=none&rel=1",
            ["rel=1"],
            "pending",
        )
        assert body["notes"] == [
            'b=gone: no quick filter has the key "gone", so it is dropped.'
        ]
        events = _task_events(streams["ada"], body["task_id"])
        assert [event["event_type"] for event in events] == [
            "task_started",
            "progress_update",
            "progress_update",
            "task_completed",
        ]
        assert events[2]["data"]["data"] == {
            "counts": [
                {"dimension": "event_kind", "count": 10},
                {"dimension": "event_error", "count": 2},
            ]
        }
        counts = {
            count["dimension"]: count["count"] for count in events[3]["data"]["counts"]
        }
        assert (counts["project"], counts["conversation"], counts["call"]) == (2, 4, 6)
        assert _queued(streams["ben"]) == []

    def test_a_state_with_faults_is_refused_with_its_text(
        self, client: FlaskClient
    ) -> None:
        response = client.post(ATTRIBUTE_COUNTS, query_string={"state": "by=phases"})

        assert response.status_code == 400
        assert response.get_json()["code"] == "STATE_REFUSED"

    def test_an_entrys_read_past_the_engines_bounds_is_refused(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        worked: Record,
    ) -> None:
        response = _busy_post(
            client,
            container,
            session,
            ATTRIBUTE_COUNTS,
            f"f=project:{worked.project.id}",
        )

        assert response.status_code == 409
        assert response.get_json()["code"] == "QUERY_BUSY"

    def test_no_state_is_refused(self, client: FlaskClient) -> None:
        assert client.post(ATTRIBUTE_COUNTS).status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert (
            client.post(ATTRIBUTE_COUNTS, query_string={"state": ""}).status_code == 403
        )

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert (
            oidc_client.post(ATTRIBUTE_COUNTS, query_string={"state": ""}).status_code
            == 401
        )


class TestStartQuickFilterCounts:
    def test_it_answers_at_once_and_the_counts_come_to_the_caller_alone(
        self, committed: Flask, streams: dict[str, SSEConnection]
    ) -> None:
        client = committed.test_client()
        _sign_in(client, "ada")

        response = client.post(
            QUICK_FILTER_COUNTS, query_string={"state": "t=all&b=past_ttl"}
        )

        assert response.status_code == 202
        body = response.get_json()
        assert (
            body["address"] == "#dash/t=all&by=project&m=cost.sum&b=past_ttl&col=none"
        )
        events = _task_events(streams["ada"], body["task_id"])
        assert [event["event_type"] for event in events] == [
            "task_started",
            "task_completed",
        ]
        assert events[-1]["data"] == {
            "quick_filters": [
                {"key": "compactions", "count": 0, "amount": None},
                {"key": "expensive", "count": 0, "amount": 0.0},
                {"key": "misses", "count": 0, "amount": 0.0},
                {"key": "outliers", "count": 0, "amount": None},
                {"key": "past_ttl", "count": 1, "amount": 0.0},
            ]
        }
        assert _queued(streams["ben"]) == []

    def test_a_task_whose_read_passes_the_bounds_fails_with_why(
        self, committed: Flask, streams: dict[str, SSEConnection]
    ) -> None:
        client = committed.test_client()
        _sign_in(client, "ada")
        container = committed.container
        bounds = Bounds(timeout_seconds=0.2, at_once=1, pool=5)

        with (
            container.dashboard_bounds.override(providers.Object(bounds)),
            scoped_session(container) as other,
            bounds.read(other),
        ):
            response = client.post(QUICK_FILTER_COUNTS, query_string={"state": "t=all"})
            events = _task_events(streams["ada"], response.get_json()["task_id"])

        assert response.status_code == 202
        assert events[-1]["event_type"] == "task_failed"
        assert events[-1]["data"]["error"] == (
            "Cannot answer the dashboard's view because the engine already runs "
            "its 1 statements at once and none ended within 0.2 s"
        )

    def test_a_state_with_faults_is_refused_with_its_text(
        self, client: FlaskClient
    ) -> None:
        response = client.post(QUICK_FILTER_COUNTS, query_string={"state": "by=phases"})

        assert response.status_code == 400
        assert response.get_json()["code"] == "STATE_REFUSED"

    def test_an_entrys_read_past_the_engines_bounds_is_refused(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        worked: Record,
    ) -> None:
        response = _busy_post(
            client,
            container,
            session,
            QUICK_FILTER_COUNTS,
            f"f=project:{worked.project.id}",
        )

        assert response.status_code == 409
        assert response.get_json()["code"] == "QUERY_BUSY"

    def test_no_state_is_refused(self, client: FlaskClient) -> None:
        assert client.post(QUICK_FILTER_COUNTS).status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert (
            client.post(QUICK_FILTER_COUNTS, query_string={"state": ""}).status_code
            == 403
        )

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert (
            oidc_client.post(
                QUICK_FILTER_COUNTS, query_string={"state": ""}
            ).status_code
            == 401
        )


def _busy_post(
    client: FlaskClient,
    container: ServiceContainer,
    session: DbSession,
    path: str,
    state: str,
) -> Any:
    """The answer to a start while the engine's one slot is held."""
    bounds = Bounds(timeout_seconds=0.2, at_once=1, pool=5)
    bind = session.get_bind()
    assert not isinstance(bind, Engine)
    other = DbSession(bind=bind.engine)
    try:
        with (
            container.dashboard_bounds.override(providers.Object(bounds)),
            bounds.read(other),
        ):
            return client.post(path, query_string={"state": state})
    finally:
        other.close()


class TestGetValues:
    def test_it_answers_an_attributes_values_without_its_own_chips(
        self, client: FlaskClient, worked: Record
    ) -> None:
        response = client.get(
            VALUES,
            query_string={
                "state": f"t=all&c=project:{worked.project.id}",
                "dimension": "project",
            },
        )

        assert response.status_code == 200
        assert response.get_json() == {
            "address": (
                f"#dash/t=all&by=project&m=cost.sum&c=project:{worked.project.id}"
                "&col=none"
            ),
            "look": [],
            "notes": [],
            "zone": "Europe/Amsterdam",
            "dimension": {"key": "project", "label": "Project", "group": "part"},
            "values": [
                {
                    "key": str(worked.project.id),
                    "label": "Recipe box",
                    "count": 5,
                    "cost": 2.6,
                },
                {"key": None, "label": "(No project)", "count": 1, "cost": 0.05},
            ],
            "total": 2,
        }

    def test_a_search_keeps_those_whose_label_holds_it(
        self, client: FlaskClient, worked: Record
    ) -> None:
        body = client.get(
            VALUES,
            query_string={"state": "t=all", "dimension": "day", "search": "11-13"},
        ).get_json()

        assert [(value["key"], value["count"]) for value in body["values"]] == [
            ("2026-11-13", 1)
        ]

    def test_no_such_dimension_is_refused_with_the_nearest(
        self, client: FlaskClient
    ) -> None:
        response = client.get(
            VALUES, query_string={"state": "t=all", "dimension": "projct"}
        )

        assert response.status_code == 400
        assert response.get_json()["code"] == "VALIDATION_FAILED"
        assert 'Did you mean "project"?' in response.get_json()["error"]

    def test_a_state_with_faults_is_refused_with_its_text(
        self, client: FlaskClient
    ) -> None:
        response = client.get(
            VALUES, query_string={"state": "by=phases", "dimension": "project"}
        )

        assert response.status_code == 400
        assert response.get_json()["code"] == "STATE_REFUSED"

    def test_a_read_past_the_engines_bounds_is_refused_with_why(
        self, client: FlaskClient, container: ServiceContainer, session: DbSession
    ) -> None:
        bounds = Bounds(timeout_seconds=0.2, at_once=1, pool=5)
        bind = session.get_bind()
        assert not isinstance(bind, Engine)
        other = DbSession(bind=bind.engine)
        try:
            with (
                container.dashboard_bounds.override(providers.Object(bounds)),
                bounds.read(other),
            ):
                response = client.get(
                    VALUES, query_string={"state": "t=all", "dimension": "project"}
                )
        finally:
            other.close()

        assert response.status_code == 409
        assert response.get_json()["code"] == "QUERY_BUSY"

    def test_no_dimension_is_refused(self, client: FlaskClient) -> None:
        assert client.get(VALUES, query_string={"state": "t=all"}).status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert (
            client.get(
                VALUES, query_string={"state": "", "dimension": "project"}
            ).status_code
            == 403
        )

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert (
            oidc_client.get(
                VALUES, query_string={"state": "", "dimension": "project"}
            ).status_code
            == 401
        )
