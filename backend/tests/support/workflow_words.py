"""The workflow's words an invented record holds none of (F122.4), so that
a word of the workflow put into one of the tests' histories fails a test."""

import re
from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from typing import Any

WORKFLOW = {"slice", "stage", "phase"}


def _words(part: Any) -> Iterator[str]:
    if isinstance(part, str):
        for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+", part):
            yield word.lower()
    elif isinstance(part, tuple | list):
        for each in part:
            yield from _words(each)
    elif is_dataclass(part) and not isinstance(part, type):
        for field in fields(part):
            yield from _words(getattr(part, field.name))


def workflow_words(part: Any) -> set[str]:
    """The words of the workflow in a part of a scenario, a history or a
    list of them, read through their strings and dataclasses, a camel-cased
    name split into its words and a word's plural counted as the word."""
    return {word for word in _words(part) if word.removesuffix("s") in WORKFLOW}
