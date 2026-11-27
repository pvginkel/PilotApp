"""A publication's labelling: the labeller's labels of one Transcript, written
in its publication's transaction (F152.3, F152.6, F152.7; DB decisions 79.23
and 81, assertion 561).

A labelling replaces every label Pilot holds of the Transcript together, and
writes only the rows that differ: the label columns of its Launches, Calls and
Tool Calls, its Segments, Rule Breaches, labelled Events and Context Parts,
Test Runs with their Test Failures and CI Waits, and of a main thread its
Documents' Ask Category. A labelled Event or Context Part keeps its identity
by its place among its Call's labelled ones, a Test Run by its place among its
Transcript's. Work Units, Test Suites, Tests and CI Builds are written by
their keys and never removed: no one Transcript's labels own them.

An appended call's labelling is the labeller's answer from the call's boundary
on, and replaces the labels from there on alone (F152.15; DB decision 81): the
Launches' from the boundary's Launch, the Segments' from the one its first Call
falls in, the Calls', their Tool Calls', Events', Context Parts', Test Runs'
and CI Waits' from its Call, and always the Test Runs of Work Units, which the
labeller gives on every answer for the Transcript that carries them, and the
Documents'. It is no relabel: it continues labels held under its stamp and its
version's major (`LabelWrite.gaps`), and the Transcript is labelled under its
version, so that all its labels are under one stamp and one major.

A labelled Context Part is a part of its Call's opening prompt, which the
collector counts whole: the publication stores that prompt's part as what the
collector counted less the Call's labelled parts (`carve`).
"""

import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any, cast

from pilot_collection.publication import (
    LabelledTestRunSchema,
    PublicationSchema,
    PublishedBoundarySchema,
    PublishedCallSchema,
    PublishedLabellingSchema,
    PublishedLabelsSchema,
    PublishedWorkUnitSchema,
)
from sqlalchemy import func, select, text, tuple_, update
from sqlalchemy.orm import Session

from app.models import (
    Call,
    CIBuild,
    CIWait,
    ContextPart,
    Document,
    Event,
    Launch,
    RuleBreach,
    Segment,
    Test,
    TestFailure,
    TestRun,
    TestSuite,
    ToolCall,
    Transcript,
    WorkUnit,
    WorkUnitKindNesting,
    WorkUnitMeasure,
)
from app.models.label import PLACING
from app.services.vocabulary_service import LISTS

LABELLER = "labeller"
"""The Component whose version a Transcript is labelled under."""

PROMPT = "prompt"
"""The collector's Context Part Kind of a Prompt a Call carries, out of which
the Call's labelled parts are carved."""

LABEL_ROWS: tuple[type[Any], ...] = (Segment, RuleBreach, TestRun, TestFailure, CIWait)
"""The entities whose rows under a Transcript are all labels."""

LABEL_COLUMNS: dict[type[Any], frozenset[str]] = {
    Launch: frozenset({"work_unit_id"}),
    Call: frozenset(
        {
            "wait_cause_code",
            "segment_position",
            "call_class_code",
            "avoidable_kind_code",
        }
    ),
    ToolCall: frozenset({"command_class_code", "effect_kind_code", "effect_subject"}),
}
"""The label columns of the entities whose rows are facts."""


def major(version: str) -> str:
    """The major of the labeller's version, which alone relabels a
    Transcript whole where it differs (`labeller.md`, "Pilot relabels a
    conversation whole when the major differs")."""
    return version.split(".", 1)[0]


def labelled(row: Any) -> bool:
    """Whether the row is a label: one of `LABEL_ROWS`, or an Event or a
    Context Part the labeller gave."""
    if isinstance(row, Event | ContextPart):
        return bool(row.labelled)
    return isinstance(row, LABEL_ROWS)


def carve(labelling: PublishedLabellingSchema) -> dict[str, int]:
    """The characters the labelling's Context Parts carve out of each Call's
    opening prompt, by its `message_id`."""
    carved: Counter[str] = Counter()
    for part in labelling.labels.context_parts:
        carved[part.call] += part.characters
    return dict(carved)


def carve_faults(
    calls: Iterable[PublishedCallSchema], carved: dict[str, int], whose: str
) -> list[str]:
    """Each Call whose opening prompt, its first Context Part of the kind
    `PROMPT`, cannot hold the characters `carved` takes out of it; `whose`
    names the labelled parts."""
    found: list[str] = []
    for call in calls:
        taken = carved.get(call.message_id, 0)
        if not taken:
            continue
        opening = next(
            (part.characters for part in call.context_parts if part.kind == PROMPT),
            None,
        )
        named = f"call `{call.message_id}`: {whose} carry {taken} characters"
        if opening is None:
            found.append(f"{named}, and it carries no `{PROMPT}` to carve them from")
        elif taken > opening:
            found.append(f"{named}, more than its opening `{PROMPT}`'s {opening}")
    return found


def _twice(what: str, keys: Iterable[Any]) -> list[str]:
    return [
        f"{what} `{key}` is labelled {count} times"
        for key, count in Counter(keys).items()
        if count > 1
    ]


def labelling_faults(publication: PublicationSchema) -> list[str]:
    """What in the call's labelling contradicts the call itself or the
    record's rules for labels (DB 533, 552, 554), each in a line. An
    appended call's labelling labels its rows from its boundary on."""
    labelling = publication.labelling
    if labelling is None:
        if publication.group is not None:
            return ["a call with no labelling names no `group`"]
        return []
    labels = labelling.labels
    found: list[str] = []
    if publication.agent_id is not None and labels.documents:
        found.append("a sub-agent's thread labels no document")

    units = _unit_faults(labelling.units, found)
    found += _twice("launch", (launch.n for launch in labels.launches))
    appended = publication.appended
    first = 1 if appended is None else appended.boundary.launch
    last = first - 1 + len(publication.launches)
    for launch in labels.launches:
        if launch.n < first:
            found.append(
                f"launch {launch.n}: before the call's boundary, at launch {first}"
            )
        if launch.n > last:
            found.append(f"launch {launch.n}: the call has {last} launches")
        if launch.work_unit is not None and launch.work_unit not in units:
            found.append(
                f"launch {launch.n}: the unit `{launch.work_unit}` is none of the"
                " call's `units`"
            )

    calls = [call.message_id for call in publication.calls]
    known = set(calls)
    found += _twice("call", (call.id for call in labels.calls))
    found += [
        f"call `{call.id}`: no call of the call's"
        for call in labels.calls
        if call.id not in known
    ]
    found += _segment_faults(labels, calls, appended is not None)

    requested = {
        tool_call.tool_use_id
        for call in publication.calls
        for tool_call in call.tool_calls
    }
    found += _twice(
        "tool call", (tool_call.tool_use_id for tool_call in labels.tool_calls)
    )
    for tool_call in labels.tool_calls:
        named = f"tool call `{tool_call.tool_use_id}`"
        if tool_call.tool_use_id not in requested:
            found.append(f"{named}: no tool call of the call's")
        if tool_call.effect_subject is not None and tool_call.effect_kind is None:
            found.append(f"{named}: an `effect_subject` with no `effect_kind`")
        found += _twice(f"{named}: the rule", tool_call.rules)
    hung = [event.call for event in labels.events]
    hung += [part.call for part in labels.context_parts]
    found += [
        f"call `{call}`: no call of the call's" for call in hung if call not in known
    ]
    found += carve_faults(
        publication.calls, carve(labelling), "its labelled context parts"
    )

    suites = {suite.code for suite in labelling.test_suites}
    found += _twice("test suite", (suite.code for suite in labelling.test_suites))
    for place, run in enumerate(labels.test_runs, start=1):
        found += _run_faults(f"test run {place}", run, requested, units, suites)

    builds = {(build.job, build.number) for build in labelling.ci_builds}
    found += _twice(
        "ci build", (f"{build.job} #{build.number}" for build in labelling.ci_builds)
    )
    found += _twice(
        "ci wait",
        (
            f"{wait.tool_use_id} on {wait.job} #{wait.number}"
            for wait in labels.ci_waits
        ),
    )
    for wait in labels.ci_waits:
        named = f"ci wait of `{wait.tool_use_id}`"
        if wait.tool_use_id not in requested:
            found.append(f"{named}: no tool call of the call's")
        if (wait.job, wait.number) not in builds:
            found.append(
                f"{named}: {wait.job} #{wait.number} is none of the call's `ci_builds`"
            )
    found += _twice("document", (document.id for document in labels.documents))
    return found


def _unit_faults(units: list[PublishedWorkUnitSchema], found: list[str]) -> set[str]:
    """Add to `found` what in the units contradicts their order or the
    record's rules; returned are their keys."""
    keys: set[str] = set()
    found += _twice("unit", (unit.key for unit in units))
    for unit in units:
        named = f"unit `{unit.key}`"
        for name in ("part_of", "occasioned_by"):
            above = getattr(unit, name)
            if above is not None and above not in keys:
                found.append(f"{named}: its `{name}` `{above}` is no unit before it")
        found += _twice(f"{named}: the measure", (m.measure for m in unit.measures))
        keys.add(unit.key)
    return keys


def _segment_faults(
    labels: PublishedLabelsSchema, calls: list[str], appended: bool
) -> list[str]:
    """Where the Segments do not hold positions one after another, from 1
    on a whole call and from their first's on an appended one, each a run of
    the Calls in their order that covers them, the first Call in the first
    (DB 554)."""
    positions = [segment.position for segment in labels.segments]
    start = positions[0] if appended and positions else 1
    if positions != list(range(start, start + len(positions))):
        if appended:
            return ["the segments' positions do not follow one another, in order"]
        return ["the segments' positions are not 1 to their number, in order"]
    falls = {call.id: call.segment for call in labels.calls}
    if not positions and not any(falls.values()):
        return []
    found: list[str] = []
    end = start - 1 + len(positions)
    last = start - 1
    for message_id in calls:
        place = falls.get(message_id)
        if place is None:
            found.append(f"call `{message_id}`: names no segment")
        elif not start <= place <= end:
            found.append(f"call `{message_id}`: names segment {place}, of none")
        elif place not in (last, last + 1):
            found.append(f"call `{message_id}`: segment {place} follows segment {last}")
        else:
            last = place
            continue
        return found
    if last < end:
        found.append(f"segment {last + 1} holds no call")
    return found


def _run_faults(
    named: str,
    run: LabelledTestRunSchema,
    requested: set[str],
    units: set[str],
    suites: set[str],
) -> list[str]:
    found: list[str] = []
    if (run.tool_use_id is None) == (run.work_unit is None):
        found.append(f"{named}: run by exactly one of a tool call and a unit")
    if run.tool_use_id is not None and run.tool_use_id not in requested:
        found.append(f"{named}: `{run.tool_use_id}` is no tool call of the call's")
    if run.work_unit is not None and run.work_unit not in units:
        found.append(
            f"{named}: the unit `{run.work_unit}` is none of the call's `units`"
        )
    if run.suite not in suites:
        found.append(
            f"{named}: the suite `{run.suite}` is none of the call's `test_suites`"
        )
    found += _twice(f"{named}: the test", (failure.test for failure in run.failures))
    return found


def _named_codes(labelling: PublishedLabellingSchema) -> dict[str, set[str]]:
    """The codes the labelling names, by the declared list each is of."""
    labels = labelling.labels
    named: dict[str, list[str | None]] = {name: [] for name in LISTS}
    for unit in labelling.units:
        named["work_unit_kind"].append(unit.kind)
        named["rework_kind"].append(unit.rework_kind)
        named["unit_outcome"].append(unit.outcome)
        named["unit_measure"] += [measure.measure for measure in unit.measures]
    named["segment_kind"] += [segment.kind for segment in labels.segments]
    for call in labels.calls:
        named["wait_cause"].append(call.wait_cause)
        named["call_class"].append(call.call_class)
        named["avoidable_kind"].append(call.avoidable_kind)
    for tool_call in labels.tool_calls:
        named["command_class"].append(tool_call.command_class)
        named["tool_effect_kind"].append(tool_call.effect_kind)
        named["rule"] += tool_call.rules
    named["event_kind"] += [event.kind for event in labels.events]
    named["context_part_kind"] += [part.kind for part in labels.context_parts]
    named["build_result"] += [build.result for build in labelling.ci_builds]
    named["ask_category"] += [document.ask_category for document in labels.documents]
    return {
        name: {code for code in codes if code is not None}
        for name, codes in named.items()
        if any(code is not None for code in codes)
    }


def _set(row: Any, facts: dict[str, Any]) -> None:
    for column, value in facts.items():
        setattr(row, column, value)


class LabelWrite:
    """Writes a publication's labelling on the caller's transaction."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def faults(self, labelling: PublishedLabellingSchema) -> list[str]:
        """What the labelling names that Pilot does not hold, each in a line:
        a value no declared list holds now, the values a labeller declares
        before it publishes a label of them (F152.6); a unit placed in
        another where no nesting pairs their kinds (DB 551); a Document."""
        found: list[str] = []
        for name, codes in _named_codes(labelling).items():
            entity = LISTS[name]
            declared: set[str] = set(
                self.db.scalars(
                    select(entity.code).where(
                        entity.code.in_(sorted(codes)), entity.position.is_not(None)
                    )
                )
            )
            found += [
                f"`{name}` `{code}`: no value the labeller declares"
                for code in sorted(codes - declared)
            ]
        kinds = {unit.key: unit.kind for unit in labelling.units}
        placed = {
            unit.key: (unit.kind, kinds[unit.part_of])
            for unit in labelling.units
            if unit.part_of in kinds
        }
        if placed:
            nested = set(
                self.db.execute(
                    select(
                        WorkUnitKindNesting.inner_code, WorkUnitKindNesting.outer_code
                    ).where(
                        tuple_(
                            WorkUnitKindNesting.inner_code,
                            WorkUnitKindNesting.outer_code,
                        ).in_(sorted(set(placed.values())))
                    )
                )
            )
            found += [
                f"unit `{key}`: no nesting pairs a `{inner}` in a `{outer}`"
                for key, (inner, outer) in placed.items()
                if (inner, outer) not in nested
            ]
        documents = {document.id for document in labelling.labels.documents}
        if documents:
            held = set(
                self.db.scalars(select(Document.id).where(Document.id.in_(documents)))
            )
            found += [
                f"document `{document}`: no document Pilot holds"
                for document in sorted(documents - held, key=str)
            ]
        return found

    def gaps(
        self,
        thread_id: uuid.UUID,
        held: tuple[str | None, str | None],
        labelling: PublishedLabellingSchema,
        boundary: PublishedBoundarySchema,
    ) -> list[str]:
        """Why an appended call's labelling does not continue the labels
        Pilot holds of the Transcript, `held` the labeller's version they are
        under and their stamp, each in a line: they are under another stamp
        or another major of the labeller's, or the labelling's first Segment
        is neither the one the Call before the boundary falls in nor the
        next, the first where the boundary's Call is the first, and none
        where the Call before falls in none."""
        labelled_under, stamp = held
        found: list[str] = []
        if stamp != labelling.stamp:
            found.append(
                "Pilot holds its labels under no stamp"
                if stamp is None
                else "Pilot holds its labels under another stamp than the labelling's"
            )
        if labelled_under is not None and major(labelled_under) != major(
            labelling.version
        ):
            found.append(
                f"Pilot holds its labels under the labeller's {labelled_under}, of"
                f" another major than the labelling's {labelling.version}"
            )
        before = (
            None
            if boundary.call == 1
            else self.db.scalar(
                select(Call.segment_position).where(
                    Call.transcript_id == thread_id,
                    Call.position == boundary.call - 1,
                )
            )
        )
        segments = labelling.labels.segments
        if before is not None:
            follows: tuple[int, ...] = (before, before + 1)
        else:
            follows = (1,) if boundary.call == 1 else ()
        held_in = "in none" if before is None else f"in segment {before}"
        if not segments and before is not None:
            found.append(
                "the labelling names no segment, and Pilot holds the call before"
                f" its boundary {held_in}"
            )
        if segments and segments[0].position not in follows:
            found.append(
                f"the labelling's segments start at {segments[0].position}, and"
                f" Pilot holds the call before its boundary {held_in}"
            )
        return found

    def write(
        self,
        thread: Transcript,
        labelling: PublishedLabellingSchema,
        ids: dict[str, int],
        boundary: PublishedBoundarySchema,
    ) -> None:
        """Hold the labelling as the Transcript's labels from the call's
        `boundary` on, every label it held there before replaced, and those
        before the boundary as they were; `ids` has the id of each of the
        call's Calls by `message_id`."""
        labels = labelling.labels
        units = self._units(labelling.units)
        suites = self._suites(labelling)
        builds = self._builds(labelling)
        self._launches(thread, labels, units, boundary)
        self._calls(thread, labels, boundary)
        tool_calls = self._tool_calls(thread, labels, boundary)
        self._hung(
            Event,
            thread,
            ids,
            boundary,
            [
                (
                    event.call,
                    {"kind_code": event.kind, "at": event.at, "detail": event.detail},
                )
                for event in labels.events
            ],
        )
        self._hung(
            ContextPart,
            thread,
            ids,
            boundary,
            [
                (
                    part.call,
                    {
                        "kind_code": part.kind,
                        "name": part.name,
                        "characters": part.characters,
                    },
                )
                for part in labels.context_parts
            ],
        )
        self._test_runs(thread, labels, tool_calls, units, suites, boundary)
        self._ci_waits(labels, tool_calls, builds)
        self._documents(labels)

    def _units(self, units: list[PublishedWorkUnitSchema]) -> dict[str, int]:
        """The Work Units as the labelling gives them, by their keys, each
        with its measures; the id of each by its key. A unit Pilot has not
        met takes an id before it is written, so that one written beside it
        sits in it."""
        if not units:
            return {}
        held = {
            row.key: row
            for row in self.db.scalars(
                select(WorkUnit).where(WorkUnit.key.in_([unit.key for unit in units]))
            )
        }
        ids = {key: row.id for key, row in held.items()}
        unmet = [unit.key for unit in units if unit.key not in held]
        if unmet:
            ids.update(
                zip(unmet, self._next_ids("work_units", len(unmet)), strict=True)
            )
        kinds = {unit.key: unit.kind for unit in units}
        rekinded = {
            row.id: kinds[key]
            for key, row in held.items()
            if row.kind_code != kinds[key]
        }
        if rekinded:
            self._rekind(rekinded, set(kinds))
        met: list[tuple[WorkUnit, dict[str, Any]]] = []
        for unit in units:
            facts: dict[str, Any] = {
                "kind_code": unit.kind,
                "part_of_id": ids[unit.part_of] if unit.part_of else None,
                "part_of_kind_code": kinds[unit.part_of] if unit.part_of else None,
                "occasioned_by_id": (
                    ids[unit.occasioned_by] if unit.occasioned_by else None
                ),
                "rework_kind_code": unit.rework_kind,
                "title": unit.title,
                "variant": unit.variant,
                "role": unit.role,
                "round": unit.round,
                "outcome_code": unit.outcome,
                "started_at": unit.started_at,
                "ended_at": unit.ended_at,
                "card": unit.card,
            }
            row = held.get(unit.key)
            if row is None:
                self.db.add(WorkUnit(id=ids[unit.key], key=unit.key, **facts))
            else:
                met.append((row, facts))
        # A held unit may sit in one written here: the new rows stand before
        # a held one names them.
        self.db.flush()
        if rekinded:
            # The new kinds first: the database moves the kind of each unit
            # placed in one to it, and the held rows are read again, so that
            # each is written against what the database holds of it.
            for row, facts in met:
                if row.id in rekinded:
                    row.kind_code = facts["kind_code"]
            self.db.flush()
            for row, _ in met:
                self.db.refresh(row)
        for row, facts in met:
            _set(row, facts)
        self.db.flush()
        if rekinded:
            self.db.execute(text(f"SET CONSTRAINTS {', '.join(PLACING)} IMMEDIATE"))

        measured = {
            (row.work_unit_id, row.measure_code): row
            for row in self.db.scalars(
                select(WorkUnitMeasure).where(
                    WorkUnitMeasure.work_unit_id.in_(list(ids.values()))
                )
            )
        }
        named = {
            (ids[unit.key], measure.measure): measure.amount
            for unit in units
            for measure in unit.measures
        }
        for (unit_id, code), amount in named.items():
            row = measured.get((unit_id, code))
            if row is None:
                self.db.add(
                    WorkUnitMeasure(
                        work_unit_id=unit_id, measure_code=code, amount=amount
                    )
                )
            elif row.amount != amount:
                row.amount = amount
        for key, row in measured.items():
            if key not in named:
                self.db.delete(row)
        self.db.flush()
        return ids

    def _rekind(self, rekinded: dict[int, str], keys: set[str]) -> None:
        """Ready the write of held units that take another kind, `rekinded`
        the new kind by each one's id, `keys` the labelling's units: the
        keys that place a unit are checked once every unit stands. A unit
        another labelling placed in one of them follows it to its new kind,
        and sits in none where no nesting pairs its own kind with that one
        (DB 551), until its own labelling places it again."""
        self.db.execute(text(f"SET CONSTRAINTS {', '.join(PLACING)} DEFERRED"))
        inside = {
            unit: (kind, rekinded[cast(int, outer)])
            for unit, kind, outer in self.db.execute(
                select(WorkUnit.id, WorkUnit.kind_code, WorkUnit.part_of_id).where(
                    WorkUnit.part_of_id.in_(list(rekinded)),
                    WorkUnit.key.not_in(sorted(keys)),
                )
            )
        }
        if not inside:
            return
        nested: set[tuple[str, str]] = {
            (inner, outer)
            for inner, outer in self.db.execute(
                select(
                    WorkUnitKindNesting.inner_code, WorkUnitKindNesting.outer_code
                ).where(
                    tuple_(
                        WorkUnitKindNesting.inner_code, WorkUnitKindNesting.outer_code
                    ).in_(sorted(set(inside.values())))
                )
            )
        }
        stranded = [unit for unit, pair in inside.items() if pair not in nested]
        if stranded:
            self.db.execute(
                update(WorkUnit)
                .where(WorkUnit.id.in_(stranded))
                .values(part_of_id=None, part_of_kind_code=None)
            )

    def _suites(self, labelling: PublishedLabellingSchema) -> dict[str, int]:
        """The Test Suites as the labelling names them; the id of each by its
        code."""
        given = {suite.code: suite.name for suite in labelling.test_suites}
        if not given:
            return {}
        held = {
            row.code: row
            for row in self.db.scalars(
                select(TestSuite).where(TestSuite.code.in_(sorted(given)))
            )
        }
        for code, name in given.items():
            row = held.get(code)
            if row is None:
                held[code] = TestSuite(code=code, name=name)
                self.db.add(held[code])
            else:
                row.name = name
        self.db.flush()
        return {code: row.id for code, row in held.items()}

    def _builds(
        self, labelling: PublishedLabellingSchema
    ) -> dict[tuple[str, int], int]:
        """The CI Builds as the labelling gives them; the id of each by its
        job and number."""
        given = {(build.job, build.number): build for build in labelling.ci_builds}
        if not given:
            return {}
        held = {
            (row.job, row.number): row
            for row in self.db.scalars(
                select(CIBuild).where(
                    tuple_(CIBuild.job, CIBuild.number).in_(sorted(given))
                )
            )
        }
        for key, build in given.items():
            facts = {
                "commit_sha": build.commit,
                "queued_at": build.queued_at,
                "started_at": build.started_at,
                "ended_at": build.ended_at,
                "result_code": build.result,
                "deployed_at": build.deployed_at,
            }
            row = held.get(key)
            if row is None:
                held[key] = CIBuild(job=build.job, number=build.number, **facts)
                self.db.add(held[key])
            else:
                _set(row, facts)
        self.db.flush()
        return {key: row.id for key, row in held.items()}

    def _launches(
        self,
        thread: Transcript,
        labels: PublishedLabelsSchema,
        units: dict[str, int],
        boundary: PublishedBoundarySchema,
    ) -> None:
        """Each of the Transcript's Launches from the boundary's on with the
        Work Unit it carried out, none where the labels name none."""
        carried = {launch.n: launch.work_unit for launch in labels.launches}
        for place, row in enumerate(
            self.db.scalars(
                select(Launch)
                .where(Launch.transcript_id == thread.id)
                .order_by(Launch.id)
                .offset(boundary.launch - 1)
            ),
            start=boundary.launch,
        ):
            key = carried.get(place)
            row.work_unit_id = None if key is None else units[key]

    def _calls(
        self,
        thread: Transcript,
        labels: PublishedLabelsSchema,
        boundary: PublishedBoundarySchema,
    ) -> None:
        """The Transcript's Segments from the labels' first on as the labels
        give them, and each of its Calls from the boundary on with its
        labels. A Segment is held before a Call names it and removed once
        none does."""
        segments = labels.segments
        start = segments[0].position if segments else 1
        held = {
            row.position: row
            for row in self.db.scalars(
                select(Segment).where(
                    Segment.transcript_id == thread.id, Segment.position >= start
                )
            )
        }
        for segment in labels.segments:
            row = held.get(segment.position)
            if row is None:
                self.db.add(
                    Segment(
                        transcript_id=thread.id,
                        position=segment.position,
                        kind_code=segment.kind,
                    )
                )
            else:
                row.kind_code = segment.kind
        self.db.flush()
        given = {call.id: call for call in labels.calls}
        for row in self.db.scalars(
            select(Call).where(
                Call.transcript_id == thread.id, Call.position >= boundary.call
            )
        ):
            call = given.get(row.message_id)
            _set(
                row,
                {
                    "wait_cause_code": None if call is None else call.wait_cause,
                    "segment_position": None if call is None else call.segment,
                    "call_class_code": None if call is None else call.call_class,
                    "avoidable_kind_code": None
                    if call is None
                    else call.avoidable_kind,
                },
            )
        self.db.flush()
        for position, row in held.items():
            if position >= start + len(segments):
                self.db.delete(row)
        self.db.flush()

    def _tool_calls(
        self,
        thread: Transcript,
        labels: PublishedLabelsSchema,
        boundary: PublishedBoundarySchema,
    ) -> dict[str, int]:
        """Each of the Transcript's Tool Calls under its Calls from the
        boundary on with its labels and the Rules it breached; the id of
        each by its `tool_use_id`."""
        given = {tool_call.tool_use_id: tool_call for tool_call in labels.tool_calls}
        rows = {
            row.tool_use_id: row
            for row in self.db.scalars(
                select(ToolCall)
                .join(Call, Call.id == ToolCall.call_id)
                .where(
                    ToolCall.transcript_id == thread.id,
                    Call.position >= boundary.call,
                )
            )
        }
        for tool_use_id, row in rows.items():
            tool_call = given.get(tool_use_id)
            _set(
                row,
                {
                    "command_class_code": None
                    if tool_call is None
                    else tool_call.command_class,
                    "effect_kind_code": None
                    if tool_call is None
                    else tool_call.effect_kind,
                    "effect_subject": None
                    if tool_call is None
                    else tool_call.effect_subject,
                },
            )
        breached = {
            (rows[tool_use_id].id, rule)
            for tool_use_id, tool_call in given.items()
            for rule in tool_call.rules
        }
        held = {
            (row.tool_call_id, row.rule_code): row
            for row in self.db.scalars(
                select(RuleBreach).where(
                    RuleBreach.tool_call_id.in_([row.id for row in rows.values()])
                )
            )
        }
        for key in sorted(breached - held.keys()):
            self.db.add(RuleBreach(tool_call_id=key[0], rule_code=key[1]))
        for key in held.keys() - breached:
            self.db.delete(held[key])
        self.db.flush()
        return {tool_use_id: row.id for tool_use_id, row in rows.items()}

    def _hung(
        self,
        entity: type[Any],
        thread: Transcript,
        ids: dict[str, int],
        boundary: PublishedBoundarySchema,
        given: list[tuple[str, dict[str, Any]]],
    ) -> None:
        """The labelled rows of `entity` under each of the Transcript's
        Calls from the boundary on, as `given` has them by their Call's
        `message_id`, in its order; a held one past the last its Call has is
        removed."""
        held: dict[int, list[Any]] = {}
        row: Any
        for row in self.db.scalars(
            select(entity)
            .join(Call, Call.id == entity.call_id)
            .where(
                Call.transcript_id == thread.id,
                Call.position >= boundary.call,
                entity.labelled.is_(True),
            )
            .order_by(entity.id)
        ):
            held.setdefault(row.call_id, []).append(row)
        under: dict[int, list[dict[str, Any]]] = {}
        for message_id, facts in given:
            under.setdefault(ids[message_id], []).append(facts)
        for call_id in held.keys() | under.keys():
            self._placed(
                held.get(call_id, []),
                under.get(call_id, []),
                entity,
                call_id=call_id,
                labelled=True,
            )
        self.db.flush()

    def _test_runs(
        self,
        thread: Transcript,
        labels: PublishedLabelsSchema,
        tool_calls: dict[str, int],
        units: dict[str, int],
        suites: dict[str, int],
        boundary: PublishedBoundarySchema,
    ) -> None:
        """The Transcript's Test Runs as the labels give them, each with its
        Test Failures, a Test its suite has not named written: those of its
        Tool Calls under its Calls from the boundary on, and those of Work
        Units."""
        held = list(
            self.db.scalars(
                select(TestRun)
                .outerjoin(ToolCall, ToolCall.id == TestRun.tool_call_id)
                .outerjoin(Call, Call.id == ToolCall.call_id)
                .where(
                    TestRun.transcript_id == thread.id,
                    TestRun.work_unit_id.is_not(None)
                    | (Call.position >= boundary.call),
                )
                .order_by(TestRun.id)
            )
        )
        # A Test Failure carries its run's suite, so a run that takes another
        # suite loses its failures first.
        moved = [
            row.id
            for row, run in zip(held, labels.test_runs, strict=False)
            if row.suite_id != suites[run.suite]
        ]
        if moved:
            for lost in self.db.scalars(
                select(TestFailure).where(TestFailure.test_run_id.in_(moved))
            ):
                self.db.delete(lost)
            self.db.flush()
        rows = self._placed(
            held,
            [
                {
                    "tool_call_id": (
                        None if run.tool_use_id is None else tool_calls[run.tool_use_id]
                    ),
                    "work_unit_id": None
                    if run.work_unit is None
                    else units[run.work_unit],
                    "ci_build_id": None,
                    "suite_id": suites[run.suite],
                    "started_at": run.started_at,
                    "ended_at": run.ended_at,
                    "passed": run.passed,
                    "tests": run.tests,
                    "retries_allowed": run.retries_allowed,
                }
                for run in labels.test_runs
            ],
            TestRun,
            transcript_id=thread.id,
        )
        self.db.flush()
        tests = self._tests(
            {
                (suites[run.suite], failure.test)
                for run in labels.test_runs
                for failure in run.failures
            }
        )
        failed = {
            (ran.id, tests[ran.suite_id, failure.test]): failure
            for ran, run in zip(rows, labels.test_runs, strict=True)
            for failure in run.failures
        }
        recorded = {
            (row.test_run_id, row.test_id): row
            for row in self.db.scalars(
                select(TestFailure).where(
                    TestFailure.test_run_id.in_([row.id for row in rows])
                )
            )
        }
        suite_of = {ran.id: ran.suite_id for ran in rows}
        for (run_id, test_id), failure in failed.items():
            held_failure = recorded.get((run_id, test_id))
            facts = {"attempts": failure.attempts, "flaky": failure.flaky}
            if held_failure is None:
                self.db.add(
                    TestFailure(
                        test_run_id=run_id,
                        test_id=test_id,
                        suite_id=suite_of[run_id],
                        **facts,
                    )
                )
            else:
                _set(held_failure, facts)
        for key, gone in recorded.items():
            if key not in failed:
                self.db.delete(gone)
        self.db.flush()

    def _tests(self, named: set[tuple[int, str]]) -> dict[tuple[int, str], int]:
        """The id of each Test, by its suite's id and its name, written where
        Pilot holds none."""
        if not named:
            return {}
        held = {
            (row.suite_id, row.name): row
            for row in self.db.scalars(
                select(Test).where(tuple_(Test.suite_id, Test.name).in_(sorted(named)))
            )
        }
        for suite_id, name in sorted(named - held.keys()):
            held[suite_id, name] = Test(suite_id=suite_id, name=name)
            self.db.add(held[suite_id, name])
        self.db.flush()
        return {key: row.id for key, row in held.items()}

    def _ci_waits(
        self,
        labels: PublishedLabelsSchema,
        tool_calls: dict[str, int],
        builds: dict[tuple[str, int], int],
    ) -> None:
        """The waits on CI Builds of the Tool Calls `tool_calls` has the id
        of, the Transcript's from the boundary on, as the labels give them."""
        waited = {
            (tool_calls[wait.tool_use_id], builds[wait.job, wait.number])
            for wait in labels.ci_waits
        }
        held = {
            (row.tool_call_id, row.ci_build_id): row
            for row in self.db.scalars(
                select(CIWait).where(CIWait.tool_call_id.in_(list(tool_calls.values())))
            )
        }
        for tool_call_id, ci_build_id in sorted(waited - held.keys()):
            self.db.add(CIWait(tool_call_id=tool_call_id, ci_build_id=ci_build_id))
        for key in held.keys() - waited:
            self.db.delete(held[key])
        self.db.flush()

    def _documents(self, labels: PublishedLabelsSchema) -> None:
        """Each Document the labels name with its Ask Category, written where
        it holds another."""
        by_category: dict[str | None, list[uuid.UUID]] = {}
        for document in labels.documents:
            by_category.setdefault(document.ask_category, []).append(document.id)
        for category, documents in by_category.items():
            self.db.execute(
                update(Document)
                .where(
                    Document.id.in_(documents),
                    Document.ask_category_code.is_distinct_from(category),
                )
                .values(ask_category_code=category)
            )

    def _placed[Row](
        self,
        held: Sequence[Row],
        facts: list[dict[str, Any]],
        entity: type[Row],
        **parent: Any,
    ) -> list[Row]:
        """The rows of `facts`, each the held row at its place with those
        facts, else a new row of `parent`'s; the held rows past the last of
        `facts` are removed."""
        rows: list[Row] = []
        for place, values in enumerate(facts):
            if place < len(held):
                row = held[place]
                _set(row, values)
            else:
                row = entity(**parent, **values)
                self.db.add(row)
            rows.append(row)
        for row in held[len(facts) :]:
            self.db.delete(row)
        return rows

    def _next_ids(self, table: str, count: int) -> list[int]:
        return list(
            self.db.scalars(
                select(
                    func.nextval(func.pg_get_serial_sequence(table, "id"))
                ).select_from(func.generate_series(1, count))
            )
        )
