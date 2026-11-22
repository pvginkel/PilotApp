"""/api/dashboard/catalogue, what a view of the dashboard may name, a part
at a call (F154.4), with what the dashboard stores (F155);
/api/dashboard/address, a view's state checked and written back in its
normal form (F159); and /api/dashboard/rows, a view's rows (F154.1)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard.views import VIEWS
from app.models import (
    Component,
    CustomRatio,
    EventKind,
    Project,
    QuickFilter,
    SavedView,
    User,
)
from app.models.reference import Origin
from tests.support.dashboard import Record, record
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
            "dimensions": {"dimensions"},
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
        }
        assert dimensions["session_start"]["base"] == "psession"
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
        }
        assert body["rows"][1]["key"] is None
        assert body["total_rows"] == 2
        assert body["sort"] == {"direction": "desc", "column": "cost.sum"}

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
