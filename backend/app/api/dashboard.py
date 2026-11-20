"""The dashboard's catalogue (F154.4): what a view may name, read through
one route, a part at a call."""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint
from spectree import Response as SpectreeResponse
from sqlalchemy.orm import Session

from app.dashboard.assembly import CatalogueService
from app.dashboard.catalogue import Catalogue
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.dashboard import (
    AggregateSchema,
    CatalogueQuerySchema,
    CatalogueResponseSchema,
    DimensionSchema,
    FactSchema,
    FigureSchema,
    GrainSchema,
    RatioSchema,
    TimeRangeSchema,
    ValueSchema,
)
from app.services.container import ServiceContainer
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
) -> Any:
    """Read one part of what a view of the dashboard may name: its
    dimensions, each with its closed list of values where it has one; its
    measures, the facts, figures, aggregates, grains and built-in ratios; or
    its time, the ranges, the zone and the sitting's gap.

    Returns:
        200: The part asked for
        400: No part, or one the catalogue has not
        401: No one is signed in
        403: The caller lacks the editor role
    """
    catalogue = catalogue_service.catalogue(db)
    part = {"dimensions": _dimensions, "measures": _measures, "time": _time}[query.part]
    return part(catalogue).model_dump()


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
