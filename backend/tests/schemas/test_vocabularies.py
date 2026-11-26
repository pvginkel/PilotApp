"""The shape of a collector's declaration of the labeller's vocabularies:
what a call must hold before Pilot reads it (F152.6; DB decision 79.40,
assertion 585)."""

from typing import Any

import pytest
from pilot_collection.vocabularies import (
    DeclaredEventKindSchema,
    DeclaredFileClassSchema,
    DeclaredRuleSchema,
    DeclaredUnitMeasureSchema,
    DeclaredValueSchema,
    VocabulariesSchema,
)
from pydantic import ValidationError

from tests.support.vocabularies import (
    NESTING,
    VERSION,
    declared,
    lists,
    nesting,
    value,
    vocabularies,
)

LISTS = (
    "work_unit_kind",
    "unit_outcome",
    "rework_kind",
    "unit_measure",
    "segment_kind",
    "wait_cause",
    "call_class",
    "avoidable_kind",
    "command_class",
    "build_result",
    "file_class",
    "tool_effect_kind",
    "rule",
    "ask_category",
    "event_kind",
    "context_part_kind",
)
"""Every list the call names, the record's places for the labeller's
values."""

FACTS = {
    "unit_measure": ("unit", DeclaredUnitMeasureSchema),
    "file_class": ("counted", DeclaredFileClassSchema),
    "rule": ("home", DeclaredRuleSchema),
    "event_kind": ("is_error", DeclaredEventKindSchema),
}
"""The lists whose values carry a fact about their category, and the
fact."""


def _refused(**overrides: Any) -> list[tuple[Any, ...]]:
    """Where the call with those overrides at its top fails."""
    with pytest.raises(ValidationError) as refused:
        vocabularies(**overrides)
    return [error["loc"] for error in refused.value.errors()]


class TestVocabulariesSchema:
    def test_a_call_carries_every_list_the_nestings_and_the_version(self) -> None:
        call = vocabularies()

        assert call.version == VERSION
        assert tuple(type(call.lists).model_fields) == LISTS
        assert [(pair.inner, pair.outer) for pair in call.nesting] == list(NESTING)
        [course, *_] = call.lists.work_unit_kind
        assert course.model_dump() == {
            "code": "menu",
            "name": "Menu",
            "description": "The menu of the kitchen's work.",
            "position": 1,
        }

    @pytest.mark.parametrize("name", list(FACTS))
    def test_a_lists_values_carry_its_fact_about_their_category(
        self, name: str
    ) -> None:
        fact, schema = FACTS[name]
        [first, *_] = getattr(vocabularies().lists, name)

        assert type(first) is schema
        assert fact in first.model_dump()

    @pytest.mark.parametrize("name", [one for one in LISTS if one not in FACTS])
    def test_the_other_lists_carry_a_value_alone(self, name: str) -> None:
        for declared_value in getattr(vocabularies().lists, name):
            assert type(declared_value) is DeclaredValueSchema

    @pytest.mark.parametrize("name", LISTS)
    def test_every_list_is_required(self, name: str) -> None:
        given = lists()
        del given[name]

        assert _refused(lists=given) == [("lists", name)]

    def test_a_list_may_be_empty(self) -> None:
        call = vocabularies(lists=lists(rework_kind=[]), nesting=[])

        assert (call.lists.rework_kind, call.nesting) == ([], [])

    def test_a_list_the_record_has_no_place_for_is_refused(self) -> None:
        """The batchable condition (P-382): the record has no place for it."""
        given = lists() | {"batchable_condition": [value("alone", 1)]}

        assert _refused(lists=given) == [("lists", "batchable_condition")]

    def test_the_groups_are_no_part_of_the_call(self) -> None:
        assert _refused(groups=[]) == [("groups",)]

    @pytest.mark.parametrize("part", ["version", "lists", "nesting"])
    def test_its_three_parts_are_required(self, part: str) -> None:
        given = declared()
        del given[part]

        with pytest.raises(ValidationError) as refused:
            VocabulariesSchema.model_validate(given)

        assert [error["loc"] for error in refused.value.errors()] == [(part,)]

    @pytest.mark.parametrize("fact", ["code", "name", "description", "position"])
    def test_a_value_names_its_code_name_line_and_place(self, fact: str) -> None:
        declared_value = value("simmer", 1)
        del declared_value[fact]

        assert _refused(lists=lists(segment_kind=[declared_value])) == [
            ("lists", "segment_kind", 0, fact)
        ]

    @pytest.mark.parametrize("name", list(FACTS))
    def test_a_value_names_its_lists_fact(self, name: str) -> None:
        fact, _ = FACTS[name]
        declared_value = value("simmer", 1)

        assert _refused(lists=lists(**{name: [declared_value]})) == [
            ("lists", name, 0, fact)
        ]

    def test_a_value_takes_no_fact_its_list_does_not_hold(self) -> None:
        declared_value = value("simmer", 1, counted=True)

        assert _refused(lists=lists(segment_kind=[declared_value])) == [
            ("lists", "segment_kind", 0, "counted")
        ]

    @pytest.mark.parametrize("fact", ["code", "name", "description"])
    def test_a_values_words_are_not_empty(self, fact: str) -> None:
        declared_value = value("simmer", 1) | {fact: ""}

        assert _refused(lists=lists(segment_kind=[declared_value])) == [
            ("lists", "segment_kind", 0, fact)
        ]

    @pytest.mark.parametrize("position", [0, -1, 2_147_483_648])
    def test_a_place_is_from_one_and_one_the_record_holds(self, position: int) -> None:
        declared_value = value("simmer", position)

        assert _refused(lists=lists(segment_kind=[declared_value])) == [
            ("lists", "segment_kind", 0, "position")
        ]

    @pytest.mark.parametrize("part", ["inner", "outer"])
    def test_a_nesting_names_both_kinds(self, part: str) -> None:
        [pair] = nesting(("course", "menu"))
        del pair[part]

        assert _refused(nesting=[pair]) == [("nesting", 0, part)]

    def test_a_nesting_takes_no_field_pilot_does_not_know(self) -> None:
        [pair] = nesting(("course", "menu"))

        assert _refused(nesting=[pair | {"depth": 1}]) == [("nesting", 0, "depth")]

    def test_the_version_is_not_empty(self) -> None:
        assert _refused(version="") == [("version",)]

    def test_the_labellers_contract_is_no_part_of_the_call(self) -> None:
        """The protocol's header is what the call speaks."""
        assert _refused(contract=1) == [("contract",)]
