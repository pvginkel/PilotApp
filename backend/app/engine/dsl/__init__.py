"""The block DSL as a pure library (design 1 §9): it imports nothing of the
database, Flask or the app's services, and takes what it validates against as
values."""

from app.engine.dsl.document import (
    AnswerChannel,
    Block,
    BlockKind,
    Fault,
    FrontMatter,
    Option,
    ParsedDocument,
    Prose,
    Section,
    Span,
)
from app.engine.dsl.reader import (
    AGENT,
    ANSWER_KEYS,
    DEFERRED,
    PLAN,
    DocumentKind,
    Facts,
    body,
    parse,
    validate,
)
from app.engine.dsl.writer import (
    Merge,
    clear_answer,
    merge,
    recommendation,
    with_title,
    write_answer,
    write_done,
    write_recommended,
)

__all__ = [
    "AGENT",
    "ANSWER_KEYS",
    "DEFERRED",
    "PLAN",
    "AnswerChannel",
    "Block",
    "BlockKind",
    "DocumentKind",
    "Facts",
    "Fault",
    "FrontMatter",
    "Merge",
    "Option",
    "ParsedDocument",
    "Prose",
    "Section",
    "Span",
    "body",
    "clear_answer",
    "merge",
    "parse",
    "recommendation",
    "validate",
    "with_title",
    "write_answer",
    "write_done",
    "write_recommended",
]
