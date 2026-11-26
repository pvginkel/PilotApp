"""What the dashboard stores (F155): the saved views, the quick filters and
the custom ratios everyone shares, written by anyone signed in, and a
person's favourites, their stars on views and their dimensions in By's list
and Color's. The server holds no tab and nothing of a By's look (F155.2).
The workflow's views and ratios are loaded from its file by the service user
alone. What is stored is listed by the catalogue's part `stored`."""

import uuid
from typing import Any, cast

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.api.caller import caller
from app.dashboard.state import PREFIX
from app.dashboard.views import SystemView
from app.models import CustomRatio, QuickFilter, SavedView
from app.models.reference import FavouriteMenu, NumberFormat
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.dashboard import (
    CustomRatioSchema,
    QuickFilterSchema,
    SavedViewSchema,
    StoredOrigin,
)
from app.schemas.dashboard_store import (
    AddQuickFilterSchema,
    CustomRatioWriteSchema,
    DimensionFavouriteSchema,
    FavouritesSchema,
    LoadCountsSchema,
    RenameViewSchema,
    SaveViewResponseSchema,
    SaveViewSchema,
    WorkflowLoadedSchema,
    WorkflowLoadSchema,
)
from app.services.container import ServiceContainer
from app.services.dashboard_store_service import (
    DashboardStoreService,
    Loaded,
    RatioEntry,
)
from app.services.people_service import PeopleService
from app.utils.spectree_config import api

dashboard_store_bp = Blueprint("dashboard_store", __name__, url_prefix="/dashboard")


@dashboard_store_bp.route("/saved-views", methods=["POST"])
@api.validate(
    json=SaveViewSchema,
    resp=SpectreeResponse(
        HTTP_200=SaveViewResponseSchema,
        HTTP_201=SaveViewResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
    ),
)
@inject
def save_view(
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
) -> Any:
    """Save a view's whole state for everyone under a name, in its normal
    form, its band's length with it (F155.1). A view a person saved under
    the name is replaced, its stars kept; a system view of the name stays
    beside it.

    Returns:
        200: The view of the name, replaced, and a note for each part of the
            state dropped
        201: The view, saved, and a note for each part of the state dropped
        400: No name, or no state; or the state has faults: the error names
            every one, and ends on a correct example of each kind of part
            refused
        401: No one is signed in
        403: The caller lacks the editor role
    """
    body = SaveViewSchema.model_validate(request.get_json())
    saved = store.save_view(body.name, body.state, body.note)
    answer = SaveViewResponseSchema(
        view=saved_view_response(saved.view), notes=list(saved.notes)
    )
    return answer.model_dump(mode="json"), 201 if saved.made else 200


@dashboard_store_bp.route("/saved-views/<uuid:view_id>", methods=["PATCH"])
@api.validate(
    json=RenameViewSchema,
    resp=SpectreeResponse(
        HTTP_200=SavedViewSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def rename_view(
    view_id: uuid.UUID,
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
) -> Any:
    """Rename a view a person saved, for everyone; its stars stay on it.

    Returns:
        200: The view, renamed
        400: No name
        401: No one is signed in
        403: The caller lacks the editor role
        404: No saved view has the id
        409: The view is a system view, which no one renames; or another view
            a person saved has the name
    """
    body = RenameViewSchema.model_validate(request.get_json())
    view = store.rename_view(view_id, body.name)
    return saved_view_response(view).model_dump(mode="json")


@dashboard_store_bp.route("/saved-views/<uuid:view_id>", methods=["DELETE"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def remove_view(
    view_id: uuid.UUID,
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
) -> Any:
    """Remove a view a person saved, for everyone, the stars on it with it.

    Returns:
        204: The view is removed
        401: No one is signed in
        403: The caller lacks the editor role
        404: No saved view has the id
        409: The view is a system view, which no one removes
    """
    store.remove_view(view_id)
    return "", 204


@dashboard_store_bp.route("/saved-views/<uuid:view_id>/star", methods=["PUT"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def star_view(
    view_id: uuid.UUID,
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Star a view, a system view or a saved one, for the signed-in person;
    a view they starred keeps its place among their stars (F155.2).

    Returns:
        204: The person has a star on the view
        401: No one is signed in
        403: The caller lacks the editor role
        404: No saved view has the id
        409: The caller has not chosen a handle, or is a service user
    """
    person = people_service.require_person(caller(), "star a view")
    store.star(person, view_id)
    return "", 204


@dashboard_store_bp.route("/saved-views/<uuid:view_id>/star", methods=["DELETE"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def unstar_view(
    view_id: uuid.UUID,
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Take the signed-in person's star off a view.

    Returns:
        204: The person has no star on the view
        401: No one is signed in
        403: The caller lacks the editor role
        404: No saved view has the id
        409: The caller has not chosen a handle, or is a service user
    """
    person = people_service.require_person(caller(), "take your star off a view")
    store.unstar(person, view_id)
    return "", 204


@dashboard_store_bp.route("/favourites", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=FavouritesSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def get_favourites(
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Read the signed-in person's favourites: the views they starred, and
    their dimensions in By's list and in Color's (F155.2).

    Returns:
        200: Their favourites
        401: No one is signed in
        403: The caller lacks the editor role
        409: The caller has not chosen a handle, or is a service user
    """
    person = people_service.require_person(caller(), "read your favourites")
    favourites = store.favourites(person)
    return FavouritesSchema(
        views=favourites.views, by=favourites.by, color=favourites.color
    ).model_dump(mode="json")


@dashboard_store_bp.route("/favourites/dimensions", methods=["POST"])
@api.validate(
    json=DimensionFavouriteSchema,
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def favour_dimension(
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Mark a dimension a favourite of the signed-in person's in By's list or
    Color's.

    Returns:
        204: The dimension is their favourite there
        400: No list, or one that is neither; or a dimension the catalogue
            offers not in that list: the error names the nearest
        401: No one is signed in
        403: The caller lacks the editor role
        409: The caller has not chosen a handle, or is a service user
    """
    body = DimensionFavouriteSchema.model_validate(request.get_json())
    person = people_service.require_person(caller(), "mark a favourite")
    store.favour(person, FavouriteMenu(body.menu), body.dimension)
    return "", 204


@dashboard_store_bp.route("/favourites/dimensions", methods=["DELETE"])
@api.validate(
    query=DimensionFavouriteSchema,
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def unfavour_dimension(
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Take a dimension off the signed-in person's favourites in By's list
    or Color's, one the catalogue no longer offers among them.

    Returns:
        204: The dimension is no favourite of theirs there
        400: No list, or one that is neither; or no dimension
        401: No one is signed in
        403: The caller lacks the editor role
        409: The caller has not chosen a handle, or is a service user
    """
    query = DimensionFavouriteSchema.model_validate(request.args.to_dict())
    person = people_service.require_person(caller(), "take a favourite off")
    store.unfavour(person, FavouriteMenu(query.menu), query.dimension)
    return "", 204


@dashboard_store_bp.route("/quick-filters", methods=["POST"])
@api.validate(
    json=AddQuickFilterSchema,
    resp=SpectreeResponse(
        HTTP_201=QuickFilterSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
    ),
)
@inject
def add_quick_filter(
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
) -> Any:
    """Make a quick filter for everyone, under a key of its own: a chip,
    filtering or marking as written, fixed once made (F155.1).

    Returns:
        201: The quick filter
        400: No label, or no chip; or the chip has faults: the error names
            every one, and ends on a correct example; or no figure has the
            amount's key
        401: No one is signed in
        403: The caller lacks the editor role
    """
    body = AddQuickFilterSchema.model_validate(request.get_json())
    quick_filter = store.add_quick_filter(body.label, body.chip, body.amount, body.note)
    return quick_filter_response(quick_filter, offered=True).model_dump(
        mode="json"
    ), 201


@dashboard_store_bp.route("/quick-filters/<uuid:quick_filter_id>", methods=["DELETE"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
    ),
)
@inject
def remove_quick_filter(
    quick_filter_id: uuid.UUID,
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
) -> Any:
    """Remove a quick filter for everyone, one the dashboard shipped with
    too, which stays removed (F155.3).

    Returns:
        204: The quick filter is removed
        401: No one is signed in
        403: The caller lacks the editor role
        404: No quick filter has the id
    """
    store.remove_quick_filter(quick_filter_id)
    return "", 204


@dashboard_store_bp.route("/custom-ratios", methods=["POST"])
@api.validate(
    json=CustomRatioWriteSchema,
    resp=SpectreeResponse(
        HTTP_201=CustomRatioSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def add_custom_ratio(
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
) -> Any:
    """Make a ratio of two measures for everyone, its key made from its name
    in a space no built-in or loaded ratio's key is in, and kept (F155.3),
    its numbers written in the format the person picked (DB 640).

    Returns:
        201: The ratio
        400: No name, a side or the format missing, or a format not among
            them; or a side has faults: the error names every one of both,
            and ends on a correct example
        401: No one is signed in
        403: The caller lacks the editor role
        409: A ratio a person made has the name
    """
    body = CustomRatioWriteSchema.model_validate(request.get_json())
    ratio = store.add_ratio(
        body.name,
        body.numerator,
        body.denominator,
        NumberFormat(body.format),
        body.note,
    )
    return custom_ratio_response(ratio, offered=True).model_dump(mode="json"), 201


@dashboard_store_bp.route("/custom-ratios/<uuid:ratio_id>", methods=["PUT"])
@api.validate(
    json=CustomRatioWriteSchema,
    resp=SpectreeResponse(
        HTTP_200=CustomRatioSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def edit_custom_ratio(
    ratio_id: uuid.UUID,
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
) -> Any:
    """Change a ratio a person made, for everyone, under its key: the views
    that show it show it changed.

    Returns:
        200: The ratio, changed
        400: No name, a side or the format missing, or a format not among
            them; or a side has faults: the error names every one of both,
            and ends on a correct example
        401: No one is signed in
        403: The caller lacks the editor role
        404: No stored ratio has the id
        409: The ratio was loaded, which no one changes; or another ratio a
            person made has the name
    """
    body = CustomRatioWriteSchema.model_validate(request.get_json())
    ratio = store.edit_ratio(
        ratio_id,
        body.name,
        body.numerator,
        body.denominator,
        NumberFormat(body.format),
        body.note,
    )
    return custom_ratio_response(ratio, offered=True).model_dump(mode="json")


@dashboard_store_bp.route("/custom-ratios/<uuid:ratio_id>", methods=["DELETE"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def remove_custom_ratio(
    ratio_id: uuid.UUID,
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
) -> Any:
    """Remove a ratio a person made, for everyone: a view that shows it
    shows without it, with a note.

    Returns:
        204: The ratio is removed
        401: No one is signed in
        403: The caller lacks the editor role
        404: No stored ratio has the id
        409: The ratio was loaded, which no one removes
    """
    store.remove_ratio(ratio_id)
    return "", 204


@dashboard_store_bp.route("/workflow", methods=["PUT"])
@api.validate(
    json=WorkflowLoadSchema,
    resp=SpectreeResponse(
        HTTP_200=WorkflowLoadedSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def load_workflow(
    store: DashboardStoreService = Provide[ServiceContainer.dashboard_store_service],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Load the workflow's views and ratios from the entries of its file,
    each by its key, as the service user, which the workflow's command calls
    as (F155.3): an entry a system view or a loaded ratio of the workflow's
    has changes it in place, a view's stars kept; one none has is added; one
    whose key the entries no longer hold is removed, a view's stars with it.
    Every entry is checked before any is written, a view's state and a
    ratio's two measures as any state is, and kept in their normal form; a
    view's state may name a ratio of the same load.

    Returns:
        200: The views and the ratios it added, changed and removed, and a
            note for each part of a view's state dropped
        400: An entry has faults: the error names every fault of every entry
            with its entry, and ends on a correct example of each kind of
            part refused; or an entry lacks a key, a name, its state or a
            measure
        401: No one is signed in
        403: The caller lacks the editor role
        409: The caller is no service user
    """
    people_service.require_service_user(
        caller(), "load the workflow's views and ratios"
    )
    body = WorkflowLoadSchema.model_validate(request.get_json())
    loaded = store.load_workflow(
        [SystemView(view.key, view.name, view.state, view.note) for view in body.views],
        [
            RatioEntry(
                ratio.key, ratio.name, ratio.numerator, ratio.denominator, ratio.note
            )
            for ratio in body.ratios
        ],
    )
    answer = WorkflowLoadedSchema(
        views=_counts(loaded.views),
        ratios=_counts(loaded.ratios),
        notes=list(loaded.notes),
    )
    return answer.model_dump(mode="json")


def _counts(loaded: Loaded) -> LoadCountsSchema:
    return LoadCountsSchema(
        added=loaded.added, changed=loaded.changed, removed=loaded.removed
    )


def saved_view_response(view: SavedView) -> SavedViewSchema:
    """A saved view as its schema writes it, its state as its address."""
    return SavedViewSchema(
        id=view.id,
        system=view.system,
        origin=view.origin_code.value,
        key=view.key,
        name=view.name,
        address=PREFIX + view.state,
        note=view.note,
        saved_at=view.saved_at,
    )


def quick_filter_response(
    quick_filter: QuickFilter, offered: bool
) -> QuickFilterSchema:
    """A quick filter as its schema writes it; `offered` whether the
    catalogue offers it. A write refuses what does not read, so a quick
    filter just written is offered."""
    return QuickFilterSchema(
        id=quick_filter.id,
        key=quick_filter.code,
        label=quick_filter.label,
        condition=quick_filter.condition,
        marks=quick_filter.marks,
        amount=quick_filter.amount_figure,
        note=quick_filter.note,
        saved_at=quick_filter.saved_at,
        offered=offered,
    )


def custom_ratio_response(ratio: CustomRatio, offered: bool) -> CustomRatioSchema:
    """A stored ratio as its schema writes it; `offered` whether the
    catalogue offers it. A write refuses a side that does not read and makes
    a person's key in a space no built-in ratio's is in, so a ratio just
    written is offered."""
    return CustomRatioSchema(
        id=ratio.id,
        system=ratio.system,
        origin=cast(StoredOrigin, ratio.origin_code.value),
        key=ratio.key,
        name=ratio.name,
        numerator=ratio.numerator,
        denominator=ratio.denominator,
        format=None if ratio.format_code is None else ratio.format_code.value,
        note=ratio.note,
        saved_at=ratio.saved_at,
        offered=offered,
    )
