"""A view's items and a conversation's calls (F165.1, F165.4), answered from
Pilot's record at the query down the one path the rows take (`rows`), each
read by index of the one thing it is about (`architecture.md` Part 1, "The
items, a conversation's calls").

- The **items** are those of a grain: the state's `ig`, else the first
  measure's grain, else the conversations; with an item opened (`it`) its
  calls. They are the items of the row selected (`sel`), else of every row,
  in the view's window and scope; under a threshold on the By's rows or the
  outlier rows' chip those of the rows kept, as the All row counts them
  (D5). Each carries the columns the catalogue gives its grain (F154.4): its
  figures, each taken together over its rows as the figure says, and, on an
  item that is one row of a fact, the dimensions shown with it. They are in
  the order they began, the earliest first, at most `ITEMS`, with the count
  of all.
- An item that is one row of a fact is its own: a call, its Call's or its
  stand-in Turn's, by the Call's id, none on a stand-in; an event by its key
  (`facts.event_key`), with its detail.
- A **conversation's calls** are every Call of one thread over all time with
  no chips, in its file's order, at most `CALLS`, with the count of all: each
  with the call's columns, its events with their details and whether the
  view's window and scope hold it. *Took* runs from a Call's sending to its
  completion, none where it has no sending time; *Waited* is the record's
  (DB §2.7, Call, `waited_seconds`).
- Times are instants, which the page writes.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dashboard import statements as statement
from app.dashboard.address import Address, AddressService, View
from app.dashboard.assembly import EVENT_KIND
from app.dashboard.bounds import Bounds
from app.dashboard.catalogue import Catalogue, Dimension, Fact, Figure, Format, Grain
from app.dashboard.facts import DETAIL, event_key, read_event_key
from app.dashboard.planner import Condition, Plan, Planned, Window, plan, series_plan
from app.dashboard.reading import READER
from app.dashboard.rows import answered, value_label
from app.dashboard.state import Item, Selected, State, Value, write_value
from app.dashboard.statements import Read
from app.exceptions import RecordNotFoundException
from app.models import Transcript

ITEMS = 2_000
"""The items an answer carries at most."""

CALLS = 2_000
"""The calls of a conversation an answer carries at most (F154.7)."""

CALL = "call"
"""The grain of a conversation's calls, and of an opened item's."""


@dataclass(frozen=True)
class Column:
    """A figure an item carries: `kinds` the token kinds it splits by, where
    it has them."""

    key: str
    label: str
    format: Format
    kinds: tuple[str, ...] | None


@dataclass(frozen=True)
class Shown:
    """The value of a dimension shown with an item, and its label, none
    where the key is its own."""

    key: Value
    label: str | None


@dataclass(frozen=True)
class Detail:
    """An event's one short detail, from the fact behind it, each part none
    where its fact has none (D6)."""

    qualifier: str | None
    tool: str | None
    characters: int | None
    denial: str | None
    command: str | None
    trigger: str | None
    model: str | None


@dataclass(frozen=True)
class Listed:
    """An item: its key, typed as its grain reads it; its label; its first
    and last moment; each figure, and each figure's split by its token
    kinds; each dimension shown with it; whether it is the view's focus. An
    item that is one row of a fact has its thread, Session, Turn and Call,
    and an event its detail."""

    key: Value
    label: str | None
    first: datetime | None
    last: datetime | None
    values: tuple[float | None, ...]
    kinds: tuple[tuple[float, ...] | None, ...]
    shown: tuple[Shown, ...] = ()
    focus: bool = False
    conversation: uuid.UUID | None = None
    session: uuid.UUID | None = None
    turn_seq: int | None = None
    call: int | None = None
    detail: Detail | None = None


@dataclass(frozen=True)
class Items:
    """A view's items: `by` the dimension `selected` is a value of, and
    `opened` the item whose calls they are, where one is."""

    address: Address
    zone: str
    window: Window
    grain: Grain
    by: Dimension
    selected: Selected | None
    opened: Item | None
    figures: tuple[Column, ...]
    shows: tuple[Dimension, ...]
    items: tuple[Listed, ...]
    total: int


@dataclass(frozen=True)
class Happened:
    """An event of a call: its key, its kind, whether it counts as an error,
    its moment and its detail."""

    key: str
    kind: str
    label: str
    is_error: bool
    at: datetime
    detail: Detail


@dataclass(frozen=True)
class ReadCall(Listed):
    """A call of a conversation: its place in its file, whether the view's
    window and scope hold it, and its events in time order."""

    position: int | None = None
    in_scope: bool = False
    events: tuple[Happened, ...] = ()


@dataclass(frozen=True)
class Calls:
    """A conversation's calls."""

    address: Address
    zone: str
    window: Window
    conversation: uuid.UUID
    figures: tuple[Column, ...]
    shows: tuple[Dimension, ...]
    calls: tuple[ReadCall, ...]
    total: int


class ItemsService:
    """A view's items and a conversation's calls, from its state as the URL
    writes it."""

    def __init__(
        self, db: Session, address_service: AddressService, bounds: Bounds
    ) -> None:
        self.db = db
        self.address_service = address_service
        self.bounds = bounds

    def items(self, written: str, now: datetime | None = None) -> Items:
        """The items of the state `written`, its time as it stands at `now`.

        Raises:
            StateRefusedException: the state has a fault
            QueryRefusedException: a statement passed the engine's bounds
        """
        view = self.address_service.view(written)
        state = view.address.state
        catalogue = view.catalogue
        found = viewed(state, catalogue, view, now or datetime.now(UTC))
        grain = _grain(catalogue, items_grain(state, found))
        with self.bounds.read(self.db) as db:
            if found.judges:
                shaper, read = answered(db, found, catalogue, view.address)
                if len(shaper.rows) < len(read):
                    found = replace(found, rows=tuple(shaper.rows))
            found = replace(found, marks=(), thresholds=(), outliers=None)
            listed = _Lister(db, catalogue, state)
            narrowed = listed.narrowed(found, state)
            items, total = (
                listed.items(narrowed, grain) if narrowed is not None else ((), 0)
            )
        return Items(
            address=view.address,
            zone=catalogue.zone,
            window=found.window,
            grain=grain,
            by=catalogue.dimension(found.by),
            selected=state.selected,
            opened=state.item,
            figures=columns(catalogue, grain),
            shows=tuple(catalogue.dimension(key) for key in grain.shows),
            items=items,
            total=total,
        )

    def calls(
        self, written: str, conversation: uuid.UUID, now: datetime | None = None
    ) -> Calls:
        """The calls of the thread `conversation` over all time, each saying
        whether the view of the state `written` holds it, its time as it
        stands at `now`.

        Raises:
            StateRefusedException: the state has a fault
            RecordNotFoundException: the record holds no such thread
            QueryRefusedException: a statement passed the engine's bounds
        """
        view = self.address_service.view(written)
        state = view.address.state
        catalogue = view.catalogue
        found = replace(
            viewed(state, catalogue, view, now or datetime.now(UTC)),
            marks=(),
            thresholds=(),
            outliers=None,
        )
        grain = _grain(catalogue, CALL)
        with self.bounds.read(self.db) as db:
            if db.get(Transcript, conversation) is None:
                raise RecordNotFoundException("Conversation", str(conversation))
            calls, total = _Lister(db, catalogue, state).calls(
                found, grain, conversation
            )
        return Calls(
            address=view.address,
            zone=catalogue.zone,
            window=found.window,
            conversation=conversation,
            figures=columns(catalogue, grain),
            shows=tuple(catalogue.dimension(key) for key in grain.shows),
            calls=calls,
            total=total,
        )


def viewed(state: State, catalogue: Catalogue, view: View, now: datetime) -> Plan:
    """The plan of the view's rows as its presentation asks them: in order
    or over time a series', else the By's."""
    if state.presentation in ("order", "time"):
        return series_plan(state, catalogue, view.weeks, now)
    return plan(state, catalogue, view.weeks, now)


def items_grain(state: State, found: Plan) -> str:
    """The grain of a view's items: an opened item's calls; else the state's
    `ig`; else the first measure's grain, where it has one; else the
    conversations."""
    if state.item is not None:
        return CALL
    if state.item_grain is not None:
        return state.item_grain
    first = found.measures[0]
    if isinstance(first, Planned) and first.grain is not None:
        return first.grain
    return READER


def columns(catalogue: Catalogue, grain: Grain) -> tuple[Column, ...]:
    return tuple(
        Column(
            figure.key,
            figure.label,
            figure.format,
            None if figure.kinds is None else tuple(figure.kinds),
        )
        for figure in (catalogue.figure(key) for key in grain.figures)
    )


def _grain(catalogue: Catalogue, key: str) -> Grain:
    return next(grain for grain in catalogue.grains if grain.key == key)


def listing_fact(catalogue: Catalogue, grain: Grain) -> Fact:
    """The fact whose rows list a grain's items: its first figure's, else,
    for the grain of a fact's own rows that carry none, that fact."""
    if grain.figures:
        return catalogue.fact(catalogue.figure(grain.figures[0]).fact)
    return next(fact for fact in catalogue.facts if fact.key == grain.key)


def is_own(fact: Fact, grain: Grain) -> bool:
    """Whether one row of the fact is one item of the grain."""
    return fact.part == grain.key or fact.key == grain.key


class _Lister:
    def __init__(self, db: Session, catalogue: Catalogue, state: State) -> None:
        self.db = db
        self.catalogue = catalogue
        self.state = state

    def ran(self, read: Read) -> Sequence[Any]:
        return self.db.execute(read.select).all()

    def narrowed(self, found: Plan, state: State) -> Plan | None:
        """The plan with the row selected and the opened item in its scope;
        none where the opened item is an event the record does not hold."""
        scope = list(found.scope)
        if state.selected is not None:
            scope.append(Condition(found.by, (state.selected.value,)))
        opened = state.item
        if opened is not None:
            if any(one.key == opened.grain for one in self.catalogue.dimensions):
                scope.append(Condition(opened.grain, (opened.key,)))
            else:
                call = self.held_on(str(opened.key))
                if call is None:
                    return None
                scope.append(Condition(CALL, (call,)))
        return replace(found, scope=tuple(scope))

    def held_on(self, key: str) -> int | None:
        """The Call the event `key` is held on, none where the record holds
        no such event."""
        read = read_event_key(key)
        assert read is not None
        fact = self.catalogue.fact(self.catalogue.offered(EVENT_KIND)[0])
        source = fact.source
        return self.db.scalar(
            select(source.c.call_id)
            .where(source.c.kind_code == read[0], source.c.source_id == read[1])
            .limit(1)
            .execution_options(max_statement_length=statement.LENGTH)
        )

    # ------------------------------------------------------------ the items

    def items(self, found: Plan, grain: Grain) -> tuple[tuple[Listed, ...], int]:
        fact = listing_fact(self.catalogue, grain)
        figures = [self.catalogue.figure(key) for key in grain.figures]
        if is_own(fact, grain):
            return self.own(found, fact, grain, figures)
        part = self.catalogue.dimension(grain.key)
        mine = [figure for figure in figures if figure.fact == fact.key]
        rows = self.ran(
            statement.grouped(found, self.catalogue, fact.key, part, mine, ITEMS)
        )
        keys = [row.item for row in rows]
        others = self.others(found, part, figures, fact, keys)
        focus = self.state.focus
        listed = []
        for row in rows:
            mapping = row._mapping
            values, kinds = [], []
            for figure in figures:
                if figure.fact == fact.key:
                    at = mine.index(figure)
                    values.append(_number(mapping[f"v{at}"]))
                    kinds.append(_kinds(mapping, at, figure))
                else:
                    values.append(others.get((figure.key, row.item)))
                    kinds.append(None)
            listed.append(
                Listed(
                    key=row.item,
                    label=value_label(part, row.item, mapping.get("name")),
                    first=row.first,
                    last=row.last,
                    values=tuple(values),
                    kinds=tuple(kinds),
                    focus=focus is not None
                    and focus.dimension == part.key
                    and focus.key == row.item,
                )
            )
        return tuple(listed), rows[0].total if rows else 0

    def others(
        self,
        found: Plan,
        part: Dimension,
        figures: Sequence[Figure],
        listing: Fact,
        keys: Sequence[Value],
    ) -> dict[tuple[str, Value], float | None]:
        """Each listed item's figures of the facts but the listing one's, by
        the figure's key and the item."""
        taken: dict[tuple[str, Value], float | None] = {}
        if not keys:
            return taken
        for fact in dict.fromkeys(figure.fact for figure in figures):
            if fact == listing.key or fact not in self.catalogue.offered(part.key):
                continue
            theirs = [figure for figure in figures if figure.fact == fact]
            read = statement.grouped(
                found, self.catalogue, fact, part, theirs, None, keys=keys
            )
            for row in self.ran(read):
                for at, figure in enumerate(theirs):
                    taken[(figure.key, row.item)] = _number(row._mapping[f"v{at}"])
        return taken

    def own(
        self, found: Plan, fact: Fact, grain: Grain, figures: Sequence[Figure]
    ) -> tuple[tuple[Listed, ...], int]:
        shown = [self.catalogue.dimension(key) for key in grain.shows]
        rows = self.ran(
            statement.own(found, self.catalogue, fact.key, figures, shown, ITEMS)
        )
        return (
            tuple(self.one(row, grain, figures, shown) for row in rows),
            rows[0].total if rows else 0,
        )

    def one(
        self,
        row: Any,
        grain: Grain,
        figures: Sequence[Figure],
        shown: Sequence[Dimension],
    ) -> Listed:
        mapping = row._mapping
        events = "kind_code" in mapping
        key: Value = event_key(row.key0, row.key1) if events else row.key0
        focus = self.state.focus
        return Listed(
            key=key,
            label=None,
            first=row.at,
            last=row.at,
            values=tuple(_number(mapping[f"v{at}"]) for at in range(len(figures))),
            kinds=tuple(
                _kinds(mapping, at, figure) for at, figure in enumerate(figures)
            ),
            shown=tuple(
                Shown(
                    mapping[f"s{at}"],
                    value_label(
                        dimension, mapping[f"s{at}"], mapping.get(f"s{at}_name")
                    ),
                )
                for at, dimension in enumerate(shown)
            ),
            focus=focus is not None
            and focus.dimension == grain.key
            and focus.key == key,
            conversation=row.transcript_id,
            session=row.session_id,
            turn_seq=row.turn_seq,
            call=row.call_id,
            detail=detail_of(mapping) if events else None,
        )

    # ------------------------------------------------------------ the calls

    def calls(
        self, found: Plan, grain: Grain, conversation: uuid.UUID
    ) -> tuple[tuple[ReadCall, ...], int]:
        fact = listing_fact(self.catalogue, grain)
        figures = [self.catalogue.figure(key) for key in grain.figures]
        shown = [self.catalogue.dimension(key) for key in grain.shows]
        rows = self.ran(
            statement.thread(
                found, self.catalogue, fact.key, figures, shown, conversation, CALLS
            )
        )
        events = self.events(found, conversation)
        calls = []
        for row in rows:
            listed = self.one(row, grain, figures, shown)
            calls.append(
                ReadCall(
                    **{
                        name: getattr(listed, name)
                        for name in Listed.__dataclass_fields__
                    },
                    position=row.position,
                    in_scope=row.in_scope,
                    events=events.get(row.call_id, ()),
                )
            )
        return tuple(calls), rows[0].total if rows else 0

    def events(
        self, found: Plan, conversation: uuid.UUID
    ) -> dict[int, tuple[Happened, ...]]:
        """The thread's events over all time, by the Call each is held on,
        in time order."""
        names = {
            value.code: value.name
            for value in self.catalogue.dimension(EVENT_KIND).values or ()
        }
        held: dict[int, list[Happened]] = {}
        for row in self.ran(
            statement.thread_events(found, self.catalogue, conversation)
        ):
            mapping = row._mapping
            held.setdefault(row.call_id, []).append(
                Happened(
                    key=event_key(row.kind_code, row.source_id),
                    kind=row.kind_code,
                    label=names.get(row.kind_code, row.kind_code),
                    is_error=row.is_error,
                    at=row.at,
                    detail=detail_of(mapping),
                )
            )
        return {call: tuple(events) for call, events in held.items()}


def detail_of(mapping: Any) -> Detail:
    """An event's detail from a row that carries the Event fact's detail
    columns."""
    found = {column: mapping[column] for column, _ in DETAIL}
    return Detail(
        qualifier=found["detail"],
        tool=found["tool_code"],
        characters=found["saved_characters"],
        denial=found["denial_kind_code"],
        command=found["hook_command"],
        trigger=found["trigger_code"],
        model=found["fallback_model_code"],
    )


def _kinds(mapping: Any, at: int, figure: Figure) -> tuple[float, ...] | None:
    if figure.kinds is None:
        return None
    return tuple(_number(mapping[f"k{at}_{kind}"]) or 0.0 for kind in figure.kinds)


def _number(value: Decimal | float | int | None) -> float | None:
    return None if value is None else float(value)


def described(view: View, now: datetime) -> dict[str, Any] | None:
    """A view's items as the file of states holds them, for a state that
    names the row selected, the items' grain or an opened item: their grain,
    the fact whose rows list them, the row selected and the item opened as
    written, and the read of their rows, an opened event's Call aside, which
    the record gives; and where the opened item is a conversation, its
    calls' read. None for a state that names none of the three."""
    state = view.address.state
    if state.selected is None and state.item_grain is None and state.item is None:
        return None
    catalogue = view.catalogue
    found = viewed(state, catalogue, view, now)
    grain = _grain(catalogue, items_grain(state, found))
    fact = listing_fact(catalogue, grain)
    scope = list(found.scope)
    if state.selected is not None:
        scope.append(Condition(found.by, (state.selected.value,)))
    opened = state.item
    if opened is not None and any(
        one.key == opened.grain for one in catalogue.dimensions
    ):
        scope.append(Condition(opened.grain, (opened.key,)))
    listed = replace(found, scope=tuple(scope))
    figures = [catalogue.figure(key) for key in grain.figures]
    if is_own(fact, grain):
        shown = [catalogue.dimension(key) for key in grain.shows]
        read = statement.own(listed, catalogue, fact.key, figures, shown, ITEMS)
    else:
        mine = [figure for figure in figures if figure.fact == fact.key]
        read = statement.grouped(
            listed, catalogue, fact.key, catalogue.dimension(grain.key), mine, ITEMS
        )
    entry: dict[str, Any] = {
        "grain": grain.key,
        "selected": None
        if state.selected is None
        else write_value(state.selected.value),
        "opened": None
        if opened is None
        else f"{opened.grain},{write_value(opened.key)}",
        **statement.read_described(read),
    }
    if opened is not None and opened.grain == READER:
        assert isinstance(opened.key, uuid.UUID)
        calls = _grain(catalogue, CALL)
        entry["calls"] = statement.read_described(
            statement.thread(
                found,
                catalogue,
                listing_fact(catalogue, calls).key,
                [catalogue.figure(key) for key in calls.figures],
                [catalogue.dimension(key) for key in calls.shows],
                opened.key,
                CALLS,
            )
        )
    return entry
