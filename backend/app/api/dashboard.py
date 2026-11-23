"""The dashboard's catalogue (F154.4), what a view may name, read through
one route, a part at a call, with what the dashboard stores (F155); a view's
address (F159), its state checked and written back in its normal form; a
view's rows (F154.1), answered from the record at the query; a view's series
and its events strip (F163.3, F164.6), its lanes (F164.6), and its items and
a conversation's calls (F165), each a route of its own."""

import uuid
from datetime import UTC, datetime
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint
from spectree import Response as SpectreeResponse
from sqlalchemy.orm import Session

from app.api.dashboard_store import (
    custom_ratio_response,
    quick_filter_response,
    saved_view_response,
)
from app.dashboard.address import AddressService, View
from app.dashboard.assembly import CatalogueService
from app.dashboard.catalogue import Catalogue, Dimension, Grain
from app.dashboard.counts import CountsService
from app.dashboard.items import Calls, Column, Detail, Items, ItemsService, Listed
from app.dashboard.lanes import Lanes, LanesService
from app.dashboard.planner import Window
from app.dashboard.rows import (
    ByRow,
    Color,
    ColorValue,
    Line,
    Measure,
    Rows,
    RowsService,
)
from app.dashboard.series import Series, SeriesService
from app.dashboard.strip import Strip, StripService
from app.dashboard.tasks import AttributeCountsTask, QuickFilterCountsTask
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.dashboard import (
    AddressQuerySchema,
    AddressResponseSchema,
    AggregateSchema,
    AttributeValueSchema,
    BandSchema,
    BucketSchema,
    ByRowSchema,
    CallEventSchema,
    CallSchema,
    CallsResponseSchema,
    CatalogueQuerySchema,
    CatalogueResponseSchema,
    ColorSchema,
    ColorValueSchema,
    CountsStartedSchema,
    DimensionSchema,
    DotSchema,
    EventDetailSchema,
    FactSchema,
    FigureSchema,
    GrainSchema,
    ItemColumnSchema,
    ItemSchema,
    ItemsResponseSchema,
    LaneEventSchema,
    LaneSchema,
    LanesResponseSchema,
    LineSchema,
    MarkerSchema,
    OpenedSchema,
    PanelSchema,
    PointSchema,
    RatioSchema,
    RollSchema,
    RowsDimensionSchema,
    RowsMeasureSchema,
    RowsResponseSchema,
    SeenKindSchema,
    SelectedSchema,
    SeriesResponseSchema,
    ShownSchema,
    SightingSchema,
    SortSchema,
    SpanSchema,
    StandInSchema,
    StateQuerySchema,
    StripResponseSchema,
    TimeRangeSchema,
    ValueSchema,
    ValuesQuerySchema,
    ValuesResponseSchema,
    WaitSchema,
)
from app.services.base_task import BaseTask
from app.services.container import ServiceContainer
from app.services.dashboard_store_service import DashboardStoreService
from app.services.task_service import TaskService
from app.utils.auth import get_auth_context
from app.utils.spectree_config import api

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.route("/catalogue", methods=["GET"])
@api.validate(
    query=CatalogueQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=CatalogueResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
    ),
)
@inject
def get_catalogue(
    query: CatalogueQuerySchema,
    db: Session = Provide[ServiceContainer.db_session],
    catalogue_service: CatalogueService = Provide[ServiceContainer.catalogue_service],
    dashboard_store_service: DashboardStoreService = Provide[
        ServiceContainer.dashboard_store_service
    ],
) -> Any:
    """Read one part of what a view of the dashboard may name: its
    dimensions, each with its closed list of values where it has one; its
    measures, the facts, figures, aggregates, grains and ratios, built in
    and stored; its time, the ranges, the zone and the sitting's gap; or
    what it stores, the saved views, each with its address, the quick
    filters and the stored ratios, each with whether the catalogue offers it.

    Returns:
        200: The part asked for
        400: No part, or one the catalogue has not
        401: No one is signed in
        403: The caller lacks the editor role
    """
    catalogue = catalogue_service.catalogue(db)
    if query.part == "stored":
        return _stored(catalogue, dashboard_store_service).model_dump(mode="json")
    part = {"dimensions": _dimensions, "measures": _measures, "time": _time}[query.part]
    return part(catalogue).model_dump()


@dashboard_bp.route("/address", methods=["GET"])
@api.validate(
    query=AddressQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=AddressResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
    ),
)
@inject
def get_address(
    query: AddressQuerySchema,
    address_service: AddressService = Provide[ServiceContainer.address_service],
) -> Any:
    """Check a view's state against the catalogue in every part and write it
    back in its normal form, the address a link carries; fill in an entry,
    its focus alone, from the record; and on request write its time range as
    it stands now.

    Returns:
        200: The view's address, its look-only parts and a note for each part
            dropped
        400: The state has faults: the error names every one, and ends on a
            correct example of each kind of part refused
        401: No one is signed in
        403: The caller lacks the editor role
    """
    found = address_service.address(query.state, fix_time=query.fix_time)
    return AddressResponseSchema(
        address=found.address, look=list(found.look), notes=list(found.notes)
    ).model_dump()


@dashboard_bp.route("/rows", methods=["GET"])
@api.validate(
    query=StateQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=RowsResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def get_rows(
    query: StateQuerySchema,
    rows_service: RowsService = Provide[ServiceContainer.rows_service],
) -> Any:
    """Answer a view's rows from the record at the query: each measure on
    every row of the By and on the All row, with the split by the color, in
    the view's sort; its time as instants, with the zone its days are in.

    Returns:
        200: The view's rows, with its address, its look-only parts and a
            note for each part dropped
        400: The state has faults: the error names every one, and ends on a
            correct example of each kind of part refused
        401: No one is signed in
        403: The caller lacks the editor role
        409: The view passed the engine's bounds: a statement past its
            timeout (`QUERY_TIMEOUT`), one past the database's limit on
            temporary files (`QUERY_TEMP_FILE_LIMIT`), or no slot among its
            statements at once freed in time (`QUERY_BUSY`)
    """
    return _rows(rows_service.rows(query.state)).model_dump(mode="json")


@dashboard_bp.route("/series", methods=["GET"])
@api.validate(
    query=StateQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=SeriesResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def get_series(
    query: StateQuerySchema,
    series_service: SeriesService = Provide[ServiceContainer.series_service],
) -> Any:
    """Answer a view's series, in order or over time, from the record at the
    query: its points along the axis, each measure's value on each, with the
    split by the color, as a panel draws it — its dots, its outliers and its
    rolling band — and the markers where a value of a marker's dimension was
    first seen; its time as instants, with the zone its days are in.

    Returns:
        200: The view's series, with its address, its look-only parts and a
            note for each part dropped
        400: The state has faults, or is not in order or over time: the error
            names every one, and ends on a correct example of each kind of
            part refused
        401: No one is signed in
        403: The caller lacks the editor role
        409: The view passed the engine's bounds: a statement past its
            timeout (`QUERY_TIMEOUT`), one past the database's limit on
            temporary files (`QUERY_TEMP_FILE_LIMIT`), or no slot among its
            statements at once freed in time (`QUERY_BUSY`)
    """
    return _series(series_service.series(query.state)).model_dump(mode="json")


@dashboard_bp.route("/series/events", methods=["GET"])
@api.validate(
    query=StateQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=StripResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def get_series_events(
    query: StateQuerySchema,
    strip_service: StripService = Provide[ServiceContainer.strip_service],
) -> Any:
    """Answer a series' events strip from the record at the query: the
    events in each of its points, by their kind, and those that count as
    errors; asked apart from the series, so that it never holds the chart up.

    Returns:
        200: The strip, with the view's address, its look-only parts and a
            note for each part dropped
        400: The state has faults, or is not in order or over time: the error
            names every one, and ends on a correct example of each kind of
            part refused
        401: No one is signed in
        403: The caller lacks the editor role
        409: The view passed the engine's bounds: a statement past its
            timeout (`QUERY_TIMEOUT`), one past the database's limit on
            temporary files (`QUERY_TEMP_FILE_LIMIT`), or no slot among its
            statements at once freed in time (`QUERY_BUSY`)
    """
    return _strip(strip_service.strip(query.state)).model_dump(mode="json")


@dashboard_bp.route("/lanes", methods=["GET"])
@api.validate(
    query=StateQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=LanesResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def get_lanes(
    query: StateQuerySchema,
    lanes_service: LanesService = Provide[ServiceContainer.lanes_service],
) -> Any:
    """Answer a view's lanes from the record at the query: a lane per row of
    the By that holds Calls, the earliest first, with each measure on it,
    its waits and its events, each event with its detail, merged past a
    bound on how many the lanes carry; its time as instants, with the zone
    its days are in.

    Returns:
        200: The view's lanes, with its address, its look-only parts and a
            note for each part dropped
        400: The state has faults, or is not in lanes: the error names every
            one, and ends on a correct example of each kind of part refused
        401: No one is signed in
        403: The caller lacks the editor role
        409: The view passed the engine's bounds: a statement past its
            timeout (`QUERY_TIMEOUT`), one past the database's limit on
            temporary files (`QUERY_TEMP_FILE_LIMIT`), or no slot among its
            statements at once freed in time (`QUERY_BUSY`)
    """
    return _lanes(lanes_service.lanes(query.state)).model_dump(mode="json")


@dashboard_bp.route("/items", methods=["GET"])
@api.validate(
    query=StateQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=ItemsResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def get_items(
    query: StateQuerySchema,
    items_service: ItemsService = Provide[ServiceContainer.items_service],
) -> Any:
    """Answer a view's items from the record at the query: those of the row
    selected, else of every row, at the view's grain of items, or an opened
    item's calls, each with the columns the catalogue gives its grain, the
    earliest first; under a threshold on the By's rows those of the rows it
    keeps; its time as instants, with the zone its days are in.

    Returns:
        200: The view's items, with its address, its look-only parts and a
            note for each part dropped
        400: The state has faults: the error names every one, and ends on a
            correct example of each kind of part refused
        401: No one is signed in
        403: The caller lacks the editor role
        409: The view passed the engine's bounds: a statement past its
            timeout (`QUERY_TIMEOUT`), one past the database's limit on
            temporary files (`QUERY_TEMP_FILE_LIMIT`), or no slot among its
            statements at once freed in time (`QUERY_BUSY`)
    """
    return _items(items_service.items(query.state)).model_dump(mode="json")


@dashboard_bp.route("/conversations/<uuid:transcript_id>/calls", methods=["GET"])
@api.validate(
    query=StateQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=CallsResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def get_conversation_calls(
    transcript_id: uuid.UUID,
    query: StateQuerySchema,
    items_service: ItemsService = Provide[ServiceContainer.items_service],
) -> Any:
    """Answer a conversation's calls from the record at the query: every
    Call of the thread over all time with no chips, in its file's order,
    each with the call's columns, its events with their details and whether
    the view's window and scope hold it.

    Returns:
        200: The calls, with the view's address, its look-only parts and a
            note for each part dropped
        400: The state has faults: the error names every one, and ends on a
            correct example of each kind of part refused
        401: No one is signed in
        403: The caller lacks the editor role
        404: The record holds no such thread
        409: The read passed the engine's bounds: a statement past its
            timeout (`QUERY_TIMEOUT`), one past the database's limit on
            temporary files (`QUERY_TEMP_FILE_LIMIT`), or no slot among its
            statements at once freed in time (`QUERY_BUSY`)
    """
    return _calls(items_service.calls(query.state, transcript_id)).model_dump(
        mode="json"
    )


@dashboard_bp.route("/counts/attributes", methods=["POST"])
@api.validate(
    query=StateQuerySchema,
    resp=SpectreeResponse(
        HTTP_202=CountsStartedSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def start_attribute_counts(
    query: StateQuerySchema,
    address_service: AddressService = Provide[ServiceContainer.address_service],
    task: AttributeCountsTask = Provide[ServiceContainer.attribute_counts_task],
    task_service: TaskService = Provide[ServiceContainer.task_service],
) -> Any:
    """Start By's counts of a view, asked when By's panel opens: each
    dimension's count of values in the view's scope, under every chip, its
    own included, and before a threshold on the By's rows or the outlier
    rows' chip. The task's events go over the stream to the caller alone:
    each fact's counts as a progress update as they are counted, its `data`
    an `AttributeCountsSchema`, then every dimension's as its result.

    Returns:
        202: The task started, with the view's address, its look-only parts
            and a note for each part dropped
        400: The state has faults: the error names every one, and ends on a
            correct example of each kind of part refused
        401: No one is signed in
        403: The caller lacks the editor role
        409: An entry's read passed the engine's bounds (`QUERY_TIMEOUT`,
            `QUERY_TEMP_FILE_LIMIT` or `QUERY_BUSY`)
    """
    return _started(task_service, task, address_service.view(query.state))


@dashboard_bp.route("/counts/quick-filters", methods=["POST"])
@api.validate(
    query=StateQuerySchema,
    resp=SpectreeResponse(
        HTTP_202=CountsStartedSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def start_quick_filter_counts(
    query: StateQuerySchema,
    address_service: AddressService = Provide[ServiceContainer.address_service],
    task: QuickFilterCountsTask = Provide[ServiceContainer.quick_filter_counts_task],
    task_service: TaskService = Provide[ServiceContainer.task_service],
) -> Any:
    """Start the quick filters' counts and amounts of a view, asked with the
    view: each quick filter's count and its figure's sum over what it keeps,
    in the view's scope and under the quick filters that are on. The task's
    result, a `QuickFilterCountsSchema`, goes over the stream to the caller
    alone.

    Returns:
        202: The task started, with the view's address, its look-only parts
            and a note for each part dropped
        400: The state has faults: the error names every one, and ends on a
            correct example of each kind of part refused
        401: No one is signed in
        403: The caller lacks the editor role
        409: An entry's read passed the engine's bounds (`QUERY_TIMEOUT`,
            `QUERY_TEMP_FILE_LIMIT` or `QUERY_BUSY`)
    """
    return _started(task_service, task, address_service.view(query.state))


@dashboard_bp.route("/values", methods=["GET"])
@api.validate(
    query=ValuesQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=ValuesResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def get_values(
    query: ValuesQuerySchema,
    counts_service: CountsService = Provide[ServiceContainer.counts_service],
) -> Any:
    """Answer one attribute's values for a filter's pane, at once: in the
    view's scope without the attribute's own chips, so that its other
    values show, each with its rows and their cost, those whose label or
    key holds the words searched.

    Returns:
        200: The values, with the view's address, its look-only parts and a
            note for each part dropped
        400: The state has faults, every one named, or the catalogue has no
            such dimension
        401: No one is signed in
        403: The caller lacks the editor role
        409: The read passed the engine's bounds (`QUERY_TIMEOUT`,
            `QUERY_TEMP_FILE_LIMIT` or `QUERY_BUSY`)
    """
    found = counts_service.values(query.state, query.dimension, query.search)
    return ValuesResponseSchema(
        address=found.address.address,
        look=list(found.address.look),
        notes=list(found.address.notes),
        zone=found.zone,
        dimension=RowsDimensionSchema(
            key=found.dimension.key,
            label=found.dimension.label,
            group=found.dimension.group,
        ),
        values=[
            AttributeValueSchema(
                key=value.key, label=value.label, count=value.count, cost=value.cost
            )
            for value in found.values
        ],
        total=found.total,
    ).model_dump(mode="json")


def _started(task_service: TaskService, task: BaseTask, view: View) -> Any:
    """The task started on the view as it stands now, for the caller."""
    auth_context = get_auth_context()
    started = task_service.start_task(
        task,
        caller_subject=None if auth_context is None else auth_context.subject,
        view=view,
        now=datetime.now(UTC),
    )
    return (
        CountsStartedSchema(
            task_id=started.task_id,
            status=started.status,
            address=view.address.address,
            look=list(view.address.look),
            notes=list(view.address.notes),
        ).model_dump(mode="json"),
        202,
    )


def _rows(found: Rows) -> RowsResponseSchema:
    return RowsResponseSchema(
        address=found.address.address,
        look=list(found.address.look),
        notes=list(found.address.notes),
        zone=found.zone,
        window=_window(found.window),
        by=RowsDimensionSchema(
            key=found.by.key, label=found.by.label, group=found.by.group
        ),
        measures=[RowsMeasureSchema(**_measure(measure)) for measure in found.measures],
        color=_color(found.color),
        all=LineSchema(**_line(found.all)),
        rows=[ByRowSchema(**_by_row(row)) for row in found.rows],
        total_rows=found.total_rows,
        sort=SortSchema(direction=found.sort.direction, column=found.sort.column),
    )


def _series(found: Series) -> SeriesResponseSchema:
    return SeriesResponseSchema(
        address=found.address.address,
        look=list(found.address.look),
        notes=list(found.address.notes),
        zone=found.zone,
        window=_window(found.window),
        presentation=found.presentation,
        by=RowsDimensionSchema(
            key=found.by.key, label=found.by.label, group=found.by.group
        ),
        roll=RollSchema(read=found.roll.read, before=found.roll.before),
        measures=[
            PanelSchema(
                **_measure(panel.measure),
                kind=panel.kind,
                outliers=list(panel.outliers),
                band=None
                if panel.band is None
                else [
                    None
                    if band is None
                    else BandSchema(
                        first=band.first, median=band.median, third=band.third
                    )
                    for band in panel.band
                ],
                before=panel.before,
                dots=None
                if panel.dots is None
                else [
                    DotSchema(
                        point=dot.point,
                        key=dot.key,
                        label=dot.label,
                        value=dot.value,
                        at=dot.at,
                        focus=dot.focus,
                    )
                    for dot in panel.dots
                ],
                cut=panel.cut,
            )
            for panel in found.panels
        ],
        color=_color(found.color),
        all=LineSchema(**_line(found.all)),
        points=[
            PointSchema(
                **_by_row(point),
                axis=point.axis,
                starts_at=point.starts_at,
                ends_at=point.ends_at,
            )
            for point in found.points
        ],
        total_points=found.total_points,
        off_axis=None
        if found.off_axis is None
        else ByRowSchema(**_by_row(found.off_axis)),
        markers=[
            SightingSchema(
                kind=marker.kind,
                value=marker.value,
                before=marker.before,
                at=marker.at,
            )
            for marker in found.markers
        ],
    )


def _strip(found: Strip) -> StripResponseSchema:
    return StripResponseSchema(
        address=found.address.address,
        look=list(found.address.look),
        notes=list(found.address.notes),
        zone=found.zone,
        window=_window(found.window),
        by=RowsDimensionSchema(
            key=found.by.key, label=found.by.label, group=found.by.group
        ),
        kinds=[
            SeenKindSchema(
                key=kind.key, label=kind.label, is_error=kind.is_error, total=kind.total
            )
            for kind in found.kinds
        ],
        buckets=[
            BucketSchema(
                key=bucket.key, counts=list(bucket.counts), errors=bucket.errors
            )
            for bucket in found.buckets
        ],
        refused=found.refused,
    )


def _lanes(found: Lanes) -> LanesResponseSchema:
    return LanesResponseSchema(
        address=found.address.address,
        look=list(found.address.look),
        notes=list(found.address.notes),
        zone=found.zone,
        window=_window(found.window),
        by=_dimension(found.by),
        measures=[RowsMeasureSchema(**_measure(measure)) for measure in found.measures],
        color=_color(found.color),
        all=LineSchema(**_line(found.all)),
        lanes=[
            LaneSchema(
                **_by_row(lane),
                starts_at=lane.starts_at,
                ends_at=lane.ends_at,
                waits=[
                    WaitSchema(
                        starts_at=wait.starts_at,
                        ends_at=wait.ends_at,
                        conversation=wait.conversation,
                        call=wait.call,
                        past_ttl=wait.past_ttl,
                        n=wait.n,
                    )
                    for wait in lane.waits
                ],
                events=[
                    LaneEventSchema(
                        at=event.at,
                        kind=event.kind,
                        is_error=event.is_error,
                        key=event.key,
                        conversation=event.conversation,
                        call=event.call,
                        cost=event.cost,
                        detail=_detail(event.detail),
                        n=event.n,
                    )
                    for event in lane.events
                ],
            )
            for lane in found.lanes
        ],
        total_lanes=found.total_lanes,
        starts_at=found.starts_at,
        ends_at=found.ends_at,
        weeks=list(found.weeks),
        kinds=[
            SeenKindSchema(
                key=kind.key, label=kind.label, is_error=kind.is_error, total=kind.total
            )
            for kind in found.kinds
        ],
        wait_seconds=found.wait_seconds,
        resolution=found.resolution,
    )


def _items(found: Items) -> ItemsResponseSchema:
    return ItemsResponseSchema(
        address=found.address.address,
        look=list(found.address.look),
        notes=list(found.address.notes),
        zone=found.zone,
        window=_window(found.window),
        grain=_grain(found.grain),
        by=_dimension(found.by),
        selected=None
        if found.selected is None
        else SelectedSchema(key=found.selected.value),
        opened=None
        if found.opened is None
        else OpenedSchema(grain=found.opened.grain, key=found.opened.key),
        figures=_columns(found.figures),
        shows=[_dimension(dimension) for dimension in found.shows],
        items=[ItemSchema(**_item(item)) for item in found.items],
        total=found.total,
    )


def _calls(found: Calls) -> CallsResponseSchema:
    return CallsResponseSchema(
        address=found.address.address,
        look=list(found.address.look),
        notes=list(found.address.notes),
        zone=found.zone,
        window=_window(found.window),
        conversation=found.conversation,
        figures=_columns(found.figures),
        shows=[_dimension(dimension) for dimension in found.shows],
        calls=[
            CallSchema(
                **_item(call),
                position=call.position,
                in_scope=call.in_scope,
                events=[
                    CallEventSchema(
                        key=event.key,
                        kind=event.kind,
                        label=event.label,
                        is_error=event.is_error,
                        at=event.at,
                        detail=EventDetailSchema(**_detail_fields(event.detail)),
                    )
                    for event in call.events
                ],
            )
            for call in found.calls
        ],
        total=found.total,
    )


def _item(item: Listed) -> dict[str, Any]:
    return {
        "key": item.key,
        "label": item.label,
        "first": item.first,
        "last": item.last,
        "values": list(item.values),
        "kinds": [None if one is None else list(one) for one in item.kinds],
        "shown": [ShownSchema(key=one.key, label=one.label) for one in item.shown],
        "focus": item.focus,
        "conversation": item.conversation,
        "session": item.session,
        "turn_seq": item.turn_seq,
        "call": item.call,
        "detail": _detail(item.detail),
    }


def _columns(columns: tuple[Column, ...]) -> list[ItemColumnSchema]:
    return [
        ItemColumnSchema(
            key=column.key,
            label=column.label,
            format=column.format,
            kinds=None if column.kinds is None else list(column.kinds),
        )
        for column in columns
    ]


def _detail(detail: Detail | None) -> EventDetailSchema | None:
    return None if detail is None else EventDetailSchema(**_detail_fields(detail))


def _detail_fields(detail: Detail) -> dict[str, Any]:
    return {
        "qualifier": detail.qualifier,
        "tool": detail.tool,
        "characters": detail.characters,
        "denial": detail.denial,
        "command": detail.command,
        "trigger": detail.trigger,
        "model": detail.model,
    }


def _dimension(dimension: Dimension) -> RowsDimensionSchema:
    return RowsDimensionSchema(
        key=dimension.key, label=dimension.label, group=dimension.group
    )


def _grain(grain: Grain) -> GrainSchema:
    return GrainSchema(
        key=grain.key,
        one=grain.one,
        many=grain.many,
        figures=list(grain.figures),
        shows=list(grain.shows),
    )


def _window(window: Window) -> list[SpanSchema] | None:
    return (
        None
        if window is None
        else [SpanSchema(start=start, end=end) for start, end in window]
    )


def _measure(measure: Measure) -> dict[str, Any]:
    return {
        "key": measure.key,
        "label": measure.label,
        "format": measure.format,
        "aggregate": measure.aggregate,
        "grain": measure.grain,
        "stacks": measure.stacks,
        "refused": measure.refused,
        "stand_in": None
        if measure.stand_in is None
        else StandInSchema(key=measure.stand_in.key, label=measure.stand_in.label),
        "median": measure.median,
    }


def _color(color: Color | None) -> ColorSchema | None:
    return (
        None
        if color is None
        else ColorSchema(
            key=color.key,
            label=color.label,
            values=[_color_value(value) for value in color.values],
        )
    )


def _by_row(row: ByRow) -> dict[str, Any]:
    return {
        **_line(row),
        "key": row.key,
        "label": row.label,
        "focus": row.focus,
        "marked": row.marked,
    }


def _color_value(value: ColorValue) -> ColorValueSchema:
    return ColorValueSchema(
        key=value.key, label=value.label, total=value.total, others=value.others
    )


def _line(line: Line) -> dict[str, Any]:
    return {
        "values": list(line.values),
        "n": list(line.n),
        "split": None
        if line.split is None
        else [None if one is None else list(one) for one in line.split],
        "marks": None if line.marks is None else list(line.marks),
    }


def _dimensions(catalogue: Catalogue) -> CatalogueResponseSchema:
    return CatalogueResponseSchema(
        part="dimensions",
        dimensions=[
            DimensionSchema(
                key=dimension.key,
                label=dimension.label,
                group=dimension.group,
                line=dimension.line,
                null=dimension.null,
                facts=list(catalogue.offered(dimension.key)),
                values=(
                    None
                    if dimension.values is None
                    else [
                        ValueSchema(
                            code=value.code,
                            name=value.name,
                            line=value.line,
                            position=value.position,
                            is_error=value.is_error,
                        )
                        for value in dimension.values
                    ]
                ),
                one=dimension.one,
                many=dimension.many,
                next=dimension.next,
                next_null=dimension.next_null,
                base=dimension.base,
                focus=dimension.focus,
                unit=dimension.unit,
            )
            for dimension in catalogue.dimensions
        ],
        markers=[
            MarkerSchema(
                key=marker.key,
                label=marker.label,
                line=marker.line,
                dimension=marker.dimension,
            )
            for marker in catalogue.markers
        ],
    )


def _measures(catalogue: Catalogue) -> CatalogueResponseSchema:
    return CatalogueResponseSchema(
        part="measures",
        facts=[
            FactSchema(
                key=fact.key,
                label=fact.label,
                counts=fact.counts,
                grain=fact.part or fact.key,
            )
            for fact in catalogue.facts
        ],
        figures=[
            FigureSchema(
                key=figure.key,
                label=figure.label,
                fact=figure.fact,
                line=figure.line,
                format=figure.format,
                aggregate=figure.aggregate,
                aggregates=list(catalogue.aggregates_of(figure)),
                token_kinds=None if figure.kinds is None else list(figure.kinds),
                stacks=figure.stacks,
            )
            for figure in catalogue.figures
        ],
        aggregates=[
            AggregateSchema(
                key=aggregate.key, label=aggregate.label, line=aggregate.line
            )
            for aggregate in catalogue.aggregates
        ],
        grains=[
            GrainSchema(
                key=grain.key,
                one=grain.one,
                many=grain.many,
                figures=list(grain.figures),
                shows=list(grain.shows),
            )
            for grain in catalogue.grains
        ],
        ratios=[
            RatioSchema(
                key=ratio.key,
                label=ratio.label,
                line=ratio.line,
                format=ratio.format,
                numerator=ratio.numerator,
                denominator=ratio.denominator,
                origin=ratio.origin,
            )
            for ratio in catalogue.ratios
        ],
    )


def _time(catalogue: Catalogue) -> CatalogueResponseSchema:
    return CatalogueResponseSchema(
        part="time",
        ranges=[
            TimeRangeSchema(key=range_.key, label=range_.label, line=range_.line)
            for range_ in catalogue.ranges
        ],
        zone=catalogue.zone,
        sitting_gap_seconds=catalogue.sitting_gap.total_seconds(),
    )


def _stored(
    catalogue: Catalogue, dashboard_store_service: DashboardStoreService
) -> CatalogueResponseSchema:
    quick_filters = {quick_filter.key for quick_filter in catalogue.quick_filters}
    ratios = {ratio.key for ratio in catalogue.ratios if ratio.origin is not None}
    return CatalogueResponseSchema(
        part="stored",
        saved_views=[
            saved_view_response(view) for view in dashboard_store_service.saved_views()
        ],
        quick_filters=[
            quick_filter_response(row, offered=row.code in quick_filters)
            for row in dashboard_store_service.quick_filters()
        ],
        custom_ratios=[
            custom_ratio_response(row, offered=row.key in ratios)
            for row in dashboard_store_service.custom_ratios()
        ],
    )
