"""/api/dashboard/catalogue: what a view of the dashboard may name, a part
at a call (F154.4)."""

from typing import Any

import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import Session as DbSession

from app.models import Component, EventKind
from tests.support.transcripts import reference

CATALOGUE = "/api/dashboard/catalogue"


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
        }
        assert dimensions["session_start"]["base"] == "psession"
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
            },
            {
                "key": "miss_share",
                "label": "Miss-cost share",
                "line": "The cost of the cache misses over the cost of all",
                "format": "share",
                "numerator": "miss_cost.sum",
                "denominator": "cost.sum",
            },
            {
                "key": "per_call",
                "label": "Cost per call",
                "line": "The cost over the number of Calls",
                "format": "usd",
                "numerator": "cost.sum",
                "denominator": "calls.count",
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
