"""The labeller's vocabularies, as a collector declares them to Pilot: the
call's shape (F152.6; DB decisions 79.12 and 79.40, assertion 585).

Every list a label takes its value from, each named after the record's
reference entity it fills (DB §2.11, "the labeller's"), with the Work Unit
Kinds' nestings and the labeller's version that declared them. A list the
record has no place for is no part of the call. Each value carries its code,
its name, the line that says what it is and its place in its list, and the
fact about its category where its entity has one.
"""

from pydantic import BaseModel, ConfigDict, Field

from pilot_collection.publication import Name, Place


class _Declared(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeclaredValueSchema(_Declared):
    """One value of a list, as the labeller declares it."""

    code: Name = Field(description="The value's code, which a label names it by")
    name: Name = Field(description="Its name, to be read")
    description: Name = Field(description="The one line that says what it is")
    position: Place = Field(
        description="Its place in its list, from 1, unique within the list"
    )


class DeclaredUnitMeasureSchema(DeclaredValueSchema):
    """A Unit Measure, a kind of figure read for a Work Unit."""

    unit: Name = Field(description="What it counts", examples=["phases"])


class DeclaredFileClassSchema(DeclaredValueSchema):
    """A File Class, a kind of file by what it is for."""

    counted: bool = Field(
        description="Whether its Files are written work, which the figures count"
    )


class DeclaredRuleSchema(DeclaredValueSchema):
    """A Rule, one convention the sessions are held to."""

    home: Name = Field(description="The file that states it")


class DeclaredEventKindSchema(DeclaredValueSchema):
    """An Event Kind of the labeller's, beside the collector's."""

    is_error: bool = Field(description="Whether it counts as an error")


class DeclaredListsSchema(_Declared):
    """Every list the record keeps of the labeller's, by the reference
    entity it fills."""

    work_unit_kind: list[DeclaredValueSchema] = Field(description="The Work Unit Kinds")
    unit_outcome: list[DeclaredValueSchema] = Field(description="The Unit Outcomes")
    rework_kind: list[DeclaredValueSchema] = Field(description="The Rework Kinds")
    unit_measure: list[DeclaredUnitMeasureSchema] = Field(
        description="The Unit Measures"
    )
    segment_kind: list[DeclaredValueSchema] = Field(description="The Segment Kinds")
    wait_cause: list[DeclaredValueSchema] = Field(description="The Wait Causes")
    call_class: list[DeclaredValueSchema] = Field(description="The Call Classes")
    avoidable_kind: list[DeclaredValueSchema] = Field(description="The Avoidable Kinds")
    command_class: list[DeclaredValueSchema] = Field(description="The Command Classes")
    build_result: list[DeclaredValueSchema] = Field(description="The Build Results")
    file_class: list[DeclaredFileClassSchema] = Field(description="The File Classes")
    tool_effect_kind: list[DeclaredValueSchema] = Field(
        description="The Tool Effect Kinds"
    )
    rule: list[DeclaredRuleSchema] = Field(description="The Rules")
    ask_category: list[DeclaredValueSchema] = Field(description="The Ask Categories")
    event_kind: list[DeclaredEventKindSchema] = Field(
        description="The labeller's Event Kinds, beside the collector's"
    )
    context_part_kind: list[DeclaredValueSchema] = Field(
        description="The labeller's Context Part Kinds, beside the collector's"
    )


class DeclaredNestingSchema(_Declared):
    """A pairing of two Work Unit Kinds: units of `inner` may sit in units
    of `outer`."""

    inner: Name = Field(description="The inner Work Unit Kind's code")
    outer: Name = Field(description="The outer Work Unit Kind's code")


class VocabulariesSchema(_Declared):
    """The labeller's vocabularies, whole: what Pilot holds of them after
    the call."""

    version: Name = Field(
        description="The labeller's own version that declared them", examples=["1.0.1"]
    )
    lists: DeclaredListsSchema = Field(description="Every list, by its entity")
    nesting: list[DeclaredNestingSchema] = Field(
        description="Every pairing of Work Unit Kinds the labeller allows"
    )
