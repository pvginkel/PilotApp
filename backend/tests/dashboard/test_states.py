"""The file of states (F154.2): every state it holds as written, read
through the address's service, gives its normal form, its look-only parts,
its notes and the query it means, the planner's, or the refusal's exact
text. The file is read whole."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.dashboard import planner, statements
from app.dashboard.address import AddressService
from app.exceptions import StateRefusedException
from app.services.container import ServiceContainer

FILE = Path(__file__).parents[2] / "dashboard-states" / "states.json"

STATES: list[dict[str, Any]] = json.loads(FILE.read_text())["states"]


@pytest.fixture
def service(container: ServiceContainer) -> AddressService:
    return container.address_service()


NOW = datetime(2026, 11, 20, tzinfo=UTC)
"""The clock the queries are planned at: a range by its key is described by
its key, so no query reads it."""


def test_each_entry_reads_or_is_refused_never_both() -> None:
    for entry in STATES:
        assert ("refusal" in entry) != ("normal" in entry), entry["about"]
        assert ("query" in entry) == ("normal" in entry), entry["about"]
        assert set(entry) <= {
            "about",
            "state",
            "normal",
            "look",
            "notes",
            "query",
            "refusal",
        }


def test_no_two_entries_write_one_state() -> None:
    written = [entry["state"] for entry in STATES]

    assert len(written) == len(set(written))


@pytest.mark.parametrize("entry", STATES, ids=[entry["about"] for entry in STATES])
def test_an_entry(service: AddressService, entry: dict[str, Any]) -> None:
    if "refusal" in entry:
        with pytest.raises(StateRefusedException) as refused:
            service.address(entry["state"])
        assert refused.value.message.splitlines() == entry["refusal"]
        return

    view = service.view(entry["state"])
    found = view.address
    planned = planner.plan(found.state, view.catalogue, view.weeks, NOW)

    assert found.address == f"#dash/{entry['normal']}"
    assert list(found.look) == entry["look"]
    assert list(found.notes) == entry.get("notes", [])
    assert (
        planner.described(planned, statements.described(planned, view.catalogue))
        == entry["query"]
    )


@pytest.mark.parametrize(
    "entry",
    [entry for entry in STATES if "normal" in entry],
    ids=[entry["about"] for entry in STATES if "normal" in entry],
)
def test_a_normal_form_is_its_own(
    service: AddressService, entry: dict[str, Any]
) -> None:
    found = service.address(entry["normal"])

    assert found.address == f"#dash/{entry['normal']}"
    assert found.notes == ()
