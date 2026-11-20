"""The catalogue's assembly (F154.4): Pilot's code's entries with the
record's vocabularies, and the process's copy, kept until a publication
writes a vocabulary's row."""

from datetime import timedelta

import pytest
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.dashboard.assembly import CatalogueService, assemble
from app.dashboard.catalogue import Catalogue
from app.dashboard.facts import FACTS, OCCURRENCES
from app.dashboard.measures import AGGREGATES, FIGURES, RANGES, RATIOS
from app.models import (
    CompactionTrigger,
    Component,
    EventKind,
    MissCause,
    Model,
    Project,
    SessionKind,
    StopReason,
)
from app.services.container import ServiceContainer
from app.utils.after_commit import run_after_commit_callbacks
from tests.support.dashboard import GAP, ZONE
from tests.support.transcripts import reference


def _codes(catalogue: Catalogue, dimension: str) -> list[str]:
    values = catalogue.dimension(dimension).values
    assert values is not None
    return [value.code for value in values]


class TestAssemble:
    def test_it_holds_what_pilots_code_declares(self, session: DbSession) -> None:
        catalogue = assemble(session, ZONE, GAP)

        assert (catalogue.zone, catalogue.sitting_gap) == (ZONE, GAP)
        assert catalogue.facts == FACTS
        assert catalogue.figures == FIGURES
        assert catalogue.aggregates == AGGREGATES
        assert catalogue.ratios == RATIOS
        assert catalogue.ranges == RANGES
        assert [grain.key for grain in catalogue.grains] == [
            "project",
            "psession",
            "pturn",
            "sitting",
            "conversation",
            "call",
            "event",
        ]

    def test_a_vocabularys_rows_are_its_dimensions_values(
        self, session: DbSession
    ) -> None:
        reference(session, StopReason, "max_tokens")
        reference(session, MissCause, "ttl")
        reference(session, CompactionTrigger, "manual")

        catalogue = assemble(session, ZONE, GAP)

        assert _codes(catalogue, "session_kind") == sorted(
            session.scalars(select(SessionKind.code))
        )
        assert set(_codes(catalogue, "model")) == set(
            session.scalars(select(Model.code))
        )
        assert _codes(catalogue, "stop_reason") == ["max_tokens"]
        assert _codes(catalogue, "miss_cause") == ["ttl"]
        assert _codes(catalogue, "compact_trigger") == ["manual"]

    def test_a_value_has_its_rows_name_in_the_names_order(
        self, session: DbSession
    ) -> None:
        catalogue = assemble(session, ZONE, GAP)

        kinds = catalogue.dimension("session_kind").values
        assert kinds is not None
        assert [(kind.code, kind.name) for kind in kinds] == [
            ("chat", "Chat"),
            ("conversation", "Conversation"),
            ("job", "Job"),
            ("work", "Work"),
        ]

    def test_the_event_kinds_are_the_records_and_those_other_entities_record(
        self, session: DbSession
    ) -> None:
        reference(session, EventKind, "api_error", is_error=True)
        reference(session, EventKind, "interrupt", is_error=False)

        kinds = assemble(session, ZONE, GAP).dimension("event_kind").values

        assert kinds is not None
        errors = {kind.code: kind.is_error for kind in kinds}
        assert errors == {
            "api_error": True,
            "interrupt": False,
            "compaction": False,
            "rewind": False,
            "cache_miss": False,
            "past_ttl": False,
            "model_fallback": True,
            "max_tokens": True,
            "refusal": True,
            "output_saved": False,
            "denied": False,
            "hook_error": True,
        }
        assert len(errors) == 2 + len(OCCURRENCES)
        assert [kind.name for kind in kinds] == sorted(kind.name for kind in kinds)

    def test_a_dimension_with_open_values_has_none(self, session: DbSession) -> None:
        catalogue = assemble(session, ZONE, GAP)

        for key in ("project", "conversation", "person", "effort", "qweek", "day"):
            assert catalogue.dimension(key).values is None

    def test_a_component_adds_its_version_dimension_and_its_joins(
        self, session: DbSession
    ) -> None:
        before = assemble(session, ZONE, GAP)
        reference(session, Component, "plugin:pantry")

        after = assemble(session, ZONE, GAP)

        added = {dimension.key for dimension in after.dimensions} - {
            dimension.key for dimension in before.dimensions
        }
        assert added == {"plugin_pantry_version"}
        assert {join.key for join in after.joins} - {
            join.key for join in before.joins
        } == {"used_plugin:pantry", "version_plugin:pantry"}

    def test_the_sittings_gap_is_the_one_given(self, session: DbSession) -> None:
        catalogue = assemble(session, ZONE, timedelta(minutes=30))

        sitting = {join.key: join for join in catalogue.joins}["sitting"].table
        compiled = select(sitting.c.id).compile()

        assert compiled.params == {"gap": 1800.0}


class TestCatalogueService:
    def test_it_is_assembled_with_the_servers_settings(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        catalogue = container.catalogue_service().catalogue(session)

        assert catalogue.zone == "Europe/Amsterdam"
        assert catalogue.sitting_gap == timedelta(hours=4)

    def test_the_process_keeps_it(self, session: DbSession) -> None:
        service = CatalogueService("UTC", 3600)
        first = service.catalogue(session)
        reference(session, StopReason, "refusal")

        again = service.catalogue(session)

        assert again is first
        assert (again.zone, again.sitting_gap) == ("UTC", timedelta(hours=1))
        assert _codes(again, "stop_reason") == []

    def test_a_drop_has_the_next_read_assemble_it_anew(
        self, session: DbSession
    ) -> None:
        service = CatalogueService(ZONE, GAP.total_seconds())
        first = service.catalogue(session)
        reference(session, StopReason, "refusal")

        service.drop()

        assert _codes(service.catalogue(session), "stop_reason") == ["refusal"]
        assert service.catalogue(session) is not first

    def test_one_dropped_while_it_was_assembled_is_not_kept(
        self, session: DbSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = CatalogueService(ZONE, GAP.total_seconds())

        def assemble_and_drop(*arguments: object) -> Catalogue:
            assembled = assemble(*arguments)  # type: ignore[arg-type]
            service.drop()
            return assembled

        monkeypatch.setattr("app.dashboard.assembly.assemble", assemble_and_drop)
        stale = service.catalogue(session)
        monkeypatch.undo()

        assert service.catalogue(session) is not stale

    def test_the_container_holds_one(self, container: ServiceContainer) -> None:
        assert container.catalogue_service() is container.catalogue_service()


@pytest.mark.usefixtures("service_user")
class TestAPublication:
    def test_one_that_writes_a_vocabularys_row_drops_it_once_it_has_committed(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        service = container.catalogue_service()
        before = service.catalogue(session)
        assert "claude_code_version" not in {d.key for d in before.dimensions}

        container.scenario_service().load({"recipe-box": project.id})

        # Not before its transaction commits: a reader would assemble it
        # from a record that has not the row yet.
        assert service.catalogue(session) is before
        run_after_commit_callbacks()

        after = service.catalogue(session)
        assert after is not before
        assert "claude_code_version" in {d.key for d in after.dimensions}

    def test_one_that_writes_none_leaves_it(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        container.scenario_service().load({"recipe-box": project.id})
        run_after_commit_callbacks()
        service = container.catalogue_service()
        held = service.catalogue(session)

        container.scenario_service().load({"recipe-box": project.id})
        run_after_commit_callbacks()

        assert service.catalogue(session) is held

    def test_the_catalogues_route_reads_what_a_request_published(
        self, client: FlaskClient, project: Project
    ) -> None:
        catalogue = "/api/dashboard/catalogue"
        before = client.get(catalogue, query_string={"part": "dimensions"})

        loaded = client.post(
            "/api/testing/scenarios", json={"projects": {"recipe-box": str(project.id)}}
        )

        assert loaded.status_code == 201
        after = client.get(catalogue, query_string={"part": "dimensions"})
        added = {d["key"] for d in after.get_json()["dimensions"]} - {
            d["key"] for d in before.get_json()["dimensions"]
        }
        assert "claude_code_version" in added
