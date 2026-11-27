"""A read of the invented Repository's history, as a collector sends one:
`read_commit` gives a commit of it, `repository_read` the call, validated, and
`file_class` a class the labeller gives a File."""

from datetime import timedelta
from typing import Any

from pilot_collection.repositories import RepositoryReadSchema

from tests.support.transcripts import STARTED

WHOLE = "3f9a2c1e7b04d6a51c8f2930d4e6b7a8c9d0e1f2"
"""The invented commit's whole hash, which the abbreviated one its call
shows starts."""

REBASED = "8e1d4b2a6c90f3e57d1b2a4c6e8f0a1b3c5d7e9f"
"""The hash the invented commit took when it was rebased."""

MADE_AT = STARTED + timedelta(minutes=1)
"""The invented commit's author's time: when the call that made it was
requested."""

READ_AT = STARTED + timedelta(days=1)
"""When the read of the invented Repository's history ran."""


def change(**overrides: Any) -> dict[str, Any]:
    """A change of the invented recipe."""
    values: dict[str, Any] = {
        "path": "recipes/stew.md",
        "lines_added": 12,
        "lines_removed": 2,
    }
    return values | overrides


def read_commit(**overrides: Any) -> dict[str, Any]:
    """The invented commit as the Repository's history gives it."""
    values: dict[str, Any] = {
        "sha": WHOLE,
        "made_at": MADE_AT.isoformat(),
        "subject": "Scale the stew for six",
        "files": [change()],
    }
    return values | overrides


def repository_read(*commits: dict[str, Any], **overrides: Any) -> RepositoryReadSchema:
    """A read of the invented Repository that gave those commits."""
    values: dict[str, Any] = {
        "repository": "RecipeBox",
        "read_at": READ_AT.isoformat(),
        "commits": list(commits),
    }
    return RepositoryReadSchema.model_validate(values | overrides)


def file_class(**overrides: Any) -> dict[str, Any]:
    """The class the labeller gives the invented recipe."""
    values: dict[str, Any] = {
        "repository": "RecipeBox",
        "path": "recipes/stew.md",
        "file_class": "recipe",
    }
    return values | overrides
