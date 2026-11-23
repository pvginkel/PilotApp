"""The dashboard's catalogue (F154.4), what a view may name, read through
one route, a part at a call, with what the dashboard stores (F155); a view's
address (F159), its state checked and written back in its normal form; and
a view's rows (F154.1), answered from the record at the query."""

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
from app.dashboard.address import AddressService
from app.dashboard.assembly import CatalogueService
from app.dashboard.catalogue import Catalogue
from app.dashboard.rows import ColorValue, Line, Rows, RowsService
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.dashboard import (
    AddressQuerySchema,
    AddressResponseSchema,
    AggregateSchema,
    ByRowSchema,
    CatalogueQuerySchema,
    CatalogueResponseSchema,
    ColorSchema,
    ColorValueSchema,
    DimensionSchema,
    FactSchema,
    FigureSchema,
    GrainSchema,
    LineSchema,
    RatioSchema,
    RowsDimensionSchema,
    RowsMeasureSchema,
    RowsQuerySchema,
    RowsResponseSchema,
    SortSchema,
    SpanSchema,
    StandInSchema,
    TimeRangeSchema,
    ValueSchema,
)
from app.services.container import ServiceContainer
from app.services.dashboard_store_service import DashboardStoreService
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
    query=RowsQuerySchema,
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
    query: RowsQuerySchema,
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


def _rows(found: Rows) -> RowsResponseSchema:
    return RowsResponseSchema(
        address=found.address.address,
        look=list(found.address.look),
        notes=list(found.address.notes),
        zone=found.zone,
        window=(
            None
            if found.window is None
            else [SpanSchema(start=start, end=end) for start, end in found.window]
        ),
        by=RowsDimensionSchema(
            key=found.by.key, label=found.by.label, group=found.by.group
        ),
        measures=[
            RowsMeasureSchema(
                key=measure.key,
                label=measure.label,
                format=measure.format,
                aggregate=measure.aggregate,
                grain=measure.grain,
                stacks=measure.stacks,
                refused=measure.refused,
                stand_in=None
                if measure.stand_in is None
                else StandInSchema(
                    key=measure.stand_in.key, label=measure.stand_in.label
                ),
                median=measure.median,
            )
            for measure in found.measures
        ],
        color=(
            None
            if found.color is None
            else ColorSchema(
                key=found.color.key,
                label=found.color.label,
                values=[_color_value(value) for value in found.color.values],
            )
        ),
        all=LineSchema(**_line(found.all)),
        rows=[
            ByRowSchema(
                **_line(row),
                key=row.key,
                label=row.label,
                focus=row.focus,
                marked=row.marked,
            )
            for row in found.rows
        ],
        total_rows=found.total_rows,
        sort=SortSchema(direction=found.sort.direction, column=found.sort.column),
    )


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
            )
            for dimension in catalogue.dimensions
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
