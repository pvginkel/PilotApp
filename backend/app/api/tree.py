"""The store's tree as the record renders it, read by path: a directory's
entries, the files a glob matches and a file as text (F150.5). No screen reads
them: they are the routes behind `pilot-projects`' file tools, which page what
these answer whole."""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.schemas.common import ApiErrorResponseSchema
from app.schemas.tree import (
    TreeEntriesQuerySchema,
    TreeEntriesSchema,
    TreeEntrySchema,
    TreeMatchesQuerySchema,
    TreeMatchesSchema,
    TreeTextQuerySchema,
    TreeTextSchema,
)
from app.services.container import ServiceContainer
from app.services.tree_read_service import TreeReadService
from app.utils.spectree_config import api

tree_bp = Blueprint("tree", __name__, url_prefix="/tree")


@tree_bp.route("/entries", methods=["GET"])
@api.validate(
    query=TreeEntriesQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=TreeEntriesSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def list_entries(
    tree_read_service: TreeReadService = Provide[ServiceContainer.tree_read_service],
) -> Any:
    """List what a directory of the tree holds: every project that is not
    archived has its folder at the root, beside `reference.json`.

    Returns:
        200: The directory's entries, directories first
        400: The path leaves the tree
        401: No one is signed in
        403: The caller lacks the editor role
        404: Nothing is at the path
        409: The path is a file's
    """
    query = TreeEntriesQuerySchema.model_validate(request.args.to_dict())
    return TreeEntriesSchema(
        entries=[
            TreeEntrySchema(path=entry.path, is_directory=entry.is_directory)
            for entry in tree_read_service.entries(query.path)
        ]
    ).model_dump(mode="json")


@tree_bp.route("/matches", methods=["GET"])
@api.validate(
    query=TreeMatchesQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=TreeMatchesSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
    ),
)
@inject
def list_matches(
    tree_read_service: TreeReadService = Provide[ServiceContainer.tree_read_service],
) -> Any:
    """Find the tree's files whose path matches a glob.

    Returns:
        200: The matching files' paths, in path order
        400: No pattern is given, it uses glob syntax that is not supported,
            or it starts with `/`
        401: No one is signed in
        403: The caller lacks the editor role
    """
    query = TreeMatchesQuerySchema.model_validate(request.args.to_dict())
    return TreeMatchesSchema(paths=tree_read_service.matches(query.pattern)).model_dump(
        mode="json"
    )


@tree_bp.route("/text", methods=["GET"])
@api.validate(
    query=TreeTextQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=TreeTextSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def read_text(
    tree_read_service: TreeReadService = Provide[ServiceContainer.tree_read_service],
) -> Any:
    """Read a file of the tree as text, its lines numbered: whole up to
    128 KB, or a line range or a tail of a file of any size, cut at 2,000
    lines and 128 KB.

    Returns:
        200: The lines read, with the whole file's hash and line count
        400: No path is given, a line number is under 1, a tail is asked with
            a range, or the path leaves the tree
        401: No one is signed in
        403: The caller lacks the editor role
        404: Nothing is at the path
        409: The path is a directory's, the file is not UTF-8 text, or it is
            read whole and is over 128 KB
    """
    query = TreeTextQuerySchema.model_validate(request.args.to_dict())
    text = tree_read_service.text(
        query.path, query.start_line, query.end_line, query.tail_lines
    )
    return TreeTextSchema(
        content=text.content,
        sha256=text.sha256,
        total_count=text.total_count,
        limit_hit=text.limit_hit,
        line_cut=text.line_cut,
    ).model_dump(mode="json")
