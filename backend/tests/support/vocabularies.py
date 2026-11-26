"""An invented declaration of the labeller's vocabularies, as a collector
makes it: every list the call names, short and in words of a kitchen's, with
the Work Unit Kinds' nestings (F152.6)."""

from typing import Any

from pilot_collection.vocabularies import VocabulariesSchema

VERSION = "1.4.2"
"""The invented labeller's version."""


def value(code: str, position: int, **facts: Any) -> dict[str, Any]:
    """A declared value, named and described after its code."""
    return {
        "code": code,
        "name": code.replace("_", " ").capitalize(),
        "description": f"The {code.replace('_', ' ')} of the kitchen's work.",
        "position": position,
    } | facts


def listed(*codes: str, **facts: Any) -> list[dict[str, Any]]:
    """Those values in that order, from place 1, each with the `facts`."""
    return [value(code, place, **facts) for place, code in enumerate(codes, start=1)]


def lists(**overrides: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Every list of the call, with `overrides` in place of the invented
    ones."""
    return {
        "work_unit_kind": listed("menu", "course", "dish"),
        "unit_outcome": listed("served", "sent_back"),
        "rework_kind": listed("recooked"),
        "unit_measure": [
            value("planned_dishes", 1, unit="dishes"),
            value("tastings", 2, unit="tastings"),
        ],
        "segment_kind": listed("prep", "cook", "plate"),
        "wait_cause": listed("oven", "delivery"),
        "call_class": listed("chop", "stir", "other"),
        "avoidable_kind": listed("spilt"),
        "command_class": listed("timer"),
        "build_result": [value("DONE", 1, name="DONE")],
        "file_class": [
            value("recipe", 1, counted=True),
            value("shopping_list", 2, counted=False),
        ],
        "tool_effect_kind": listed("order_placed"),
        "rule": [value("no_tasting_from_the_pot", 1, home="/kitchen/RULES.md")],
        "ask_category": listed("menu_question"),
        "event_kind": [value("burnt", 1, is_error=False)],
        "context_part_kind": listed("recipe_card"),
    } | overrides


def nesting(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    """The pairings, each inner and outer."""
    return [{"inner": inner, "outer": outer} for inner, outer in pairs]


NESTING = (("course", "menu"), ("dish", "course"))
"""The invented Work Unit Kinds' pairings."""


def declared(**overrides: Any) -> dict[str, Any]:
    """The call's body, with `overrides` at its top in place of the
    invented parts."""
    return {"version": VERSION, "lists": lists(), "nesting": nesting(*NESTING)} | (
        overrides
    )


def vocabularies(**overrides: Any) -> VocabulariesSchema:
    """The call, validated, with `overrides` at its top."""
    return VocabulariesSchema.model_validate(declared(**overrides))
