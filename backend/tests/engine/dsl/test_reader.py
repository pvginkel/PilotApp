"""The block DSL's reader: parse and validate, and the conformance corpus."""

import ast
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import app.engine.dsl as dsl
from app.engine.dsl import (
    BlockKind,
    DocumentKind,
    Facts,
    Fault,
    ParsedDocument,
    Span,
    parse,
    validate,
)

CORPUS = Path(__file__).parents[2] / "fixtures" / "dsl"
GROUPS = ("accepted", "held", "never-a-fault", "normalised")
CASES = sorted(path for group in GROUPS for path in (CORPUS / group).glob("*.md"))

# Design 1 §6.1's table, one entry per rule, each the `rule` of a corpus case.
SECTION_6_1 = (
    "accepted: Markdown around the fences, never parsed",
    "accepted: a front matter block at the top",
    "accepted: no front matter",
    "accepted: unknown front-matter keys, kept and ignored",
    "accepted: CRLF line endings",
    "accepted: a fence closed by the same character and at least the same length",
    "accepted: a block quoted inside a longer fence is no block",
    "accepted: whitespace around `id=`",
    "accepted: an option as a bare label or `- Label: one line`",
    "accepted: a scalar where a string is wanted, coerced",
    "accepted: a time without a zone, read as UTC",
    "accepted: the first ATX heading as the title when `title` is absent",
    "accepted: a registered document with neither title nor heading",
    "held: a fence opened and not closed",
    "held: a block whose body is not a YAML mapping",
    "held: a block without `id`",
    "held: two blocks with one id",
    "held: a key a kind does not take",
    "held: `options` not a list",
    "held: an option that is not a label with at most one line",
    "held: `recommend` naming no label",
    "held: `recommend` beside `proposal`",
    "held: `type: confirmation` without `proposal` or `because`",
    "held: `because` outside Confirmation Reason",
    "held: `answer: deferred` without `to`",
    "held: `to` without `deferred`",
    "held: a written `to` naming neither `plan` nor a task in the plan",
    "held: `by` naming no handle",
    "held: `at` or `done` not a time",
    "held: a Pilot's-own one-block item with neither `title` nor a first heading",
    "held: a block kind in the wrong case",
    "held: `id=` on a fence that is not a block",
    "held: `step` naming no task of the project",
    "held: `for` naming no handle",
    "held: the draft's `slug` present and invalid or taken",
    "never a fault: an `answer` that matches no option",
    "never a fault: a block kind the record does not know",
    "never a fault: prose the skill would call bad",
    "never a fault: the draft's `slug` missing",
    "never a fault: a `to` carried unchanged from the published text",
    "normalised: labels and values trimmed",
    "normalised: option order and block order as written",
    "normalised: `via` absent read as `app` for a person's line",
    "Later: `check` parsed and kept, never acted on",
)

FACTS = Facts(
    document=DocumentKind.REGISTERED_ITEM,
    handles={"agent", "ada", "ben"},
    plan_task_ids={"build", "verify"},
    removed_task_ids={"spike"},
    confirmation_reasons=(
        "auto-pilot-off",
        "rider",
        "irreversible",
        "product-hold",
        "self-approval",
    ),
    taken_slugs={"harbour"},
    published_to={},
)


NOT_TEXT = "{} is not text: a key or value holds NUL or an unpaired surrogate"


def _facts(**overrides: Any) -> Facts:
    values = {name: getattr(FACTS, name) for name in Facts.__dataclass_fields__}
    values.update(overrides)
    return Facts(**values)


def _corpus_facts(path: Path) -> Facts:
    defaults = json.loads((CORPUS / "facts.json").read_text())
    defaults.update(_case(path).get("facts", {}))
    return Facts(
        document=DocumentKind(defaults["document"]),
        handles=set(defaults["handles"]),
        plan_task_ids=set(defaults["plan_task_ids"]),
        removed_task_ids=set(defaults["removed_task_ids"]),
        confirmation_reasons=tuple(defaults["confirmation_reasons"]),
        taken_slugs=set(defaults["taken_slugs"]),
        published_to=defaults["published_to"],
    )


def _case(path: Path) -> dict[str, Any]:
    return json.loads(path.with_suffix(".json").read_text())


def _text(path: Path) -> str:
    return path.read_bytes().decode()


def _span(span: Span) -> list[int]:
    return [span.first, span.last]


def _lines(lines: Mapping[str, Span]) -> dict[str, list[int]]:
    return {key: _span(span) for key, span in lines.items()}


def _compact(values: dict[str, Any]) -> dict[str, Any]:
    """The corpus leaves out what is none, false or empty."""
    return {
        key: value
        for key, value in values.items()
        if value not in (None, False, [], {})
    }


def _time(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def corpus_parse(document: ParsedDocument) -> dict[str, Any]:
    """A parse as the corpus writes it."""
    front_matter = document.front_matter
    return _compact(
        {
            "front_matter": _compact(
                {
                    "span": _span(front_matter.span) if front_matter.span else None,
                    "lines": _lines(front_matter.lines),
                    "title": front_matter.title,
                    "summary": front_matter.summary,
                    "step": front_matter.step,
                    "urgent": front_matter.urgent,
                    "for": front_matter.addressee,
                    "slug": front_matter.slug,
                }
            ),
            "title": document.title,
            "title_heading_line": document.title_heading_line,
            "blocks": [
                _compact(
                    {
                        "id": block.local_id,
                        "kind": str(block.kind),
                        "fence": _span(block.fence),
                        "lines": _lines(block.lines),
                        "confirmation": block.confirmation,
                        "because": block.because,
                        "proposal": block.proposal,
                        "default": block.default,
                        "check": block.check,
                        "options": [
                            _compact(
                                {
                                    "label": option.label,
                                    "text": option.text,
                                    "recommended": option.recommended,
                                    "line": option.line,
                                }
                            )
                            for option in block.options
                        ],
                        "answer": block.answer,
                        "by": block.by,
                        "at": _time(block.at),
                        "note": block.note,
                        "via": block.via,
                        "to": block.to,
                        "done": _time(block.done),
                    }
                )
                for block in document.blocks
            ],
        }
    )


def corpus_faults(faults: list[Fault]) -> list[dict[str, Any]]:
    return [{"line": fault.line, "message": fault.message} for fault in faults]


def _messages(text: str, facts: Facts = FACTS) -> list[str]:
    return [fault.message for fault in validate(parse(text), facts)]


class TestConformanceCorpus:
    """Every case of `tests/fixtures/dsl/`: a document beside the parse and the
    faults expected of it, validated against `facts.json` and the case's own
    `facts`."""

    @pytest.mark.parametrize(
        "path", CASES, ids=lambda path: f"{path.parent.name}/{path.stem}"
    )
    def test_case(self, path: Path) -> None:
        case = _case(path)
        document = parse(_text(path))

        assert corpus_parse(document) == case["parse"]
        assert corpus_faults(validate(document, _corpus_facts(path))) == case["faults"]

    @pytest.mark.parametrize(
        "path", CASES, ids=lambda path: f"{path.parent.name}/{path.stem}"
    )
    def test_a_case_is_held_exactly_when_its_group_says(self, path: Path) -> None:
        held = bool(_case(path)["faults"])

        assert held == (path.parent.name == "held")

    def test_every_rule_of_section_6_1_has_a_case(self) -> None:
        rules = {_case(path)["rule"] for path in CASES}

        assert set(SECTION_6_1) - rules == set()

    def test_every_case_has_its_expectation(self) -> None:
        expectations = {
            path.with_suffix(".md")
            for group in GROUPS
            for path in (CORPUS / group).glob("*.json")
        }

        assert expectations == set(CASES)

    def test_the_crlf_case_is_stored_with_crlf(self) -> None:
        assert b"\r\n" in (CORPUS / "accepted" / "crlf-line-endings.md").read_bytes()


class TestPurity:
    def test_the_library_imports_only_the_standard_library_yaml_and_exceptions(
        self,
    ) -> None:
        package = Path(dsl.__file__).parent
        imported: set[str] = set()
        for module in package.glob("*.py"):
            for node in ast.walk(ast.parse(module.read_text())):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)

        foreign = {
            name
            for name in imported
            if name.split(".")[0]
            not in {"re", "collections", "dataclasses", "datetime", "enum", "yaml"}
            and not name.startswith("app.engine.dsl")
            and name != "app.exceptions"
        }
        assert foreign == set()


class TestParse:
    def test_a_document_is_read_into_its_front_matter_title_and_blocks(self) -> None:
        document = parse(
            "---\ntitle: Pick a queue\nstep: build\n---\n\nWhy it matters.\n\n"
            "```decision id=D1\noptions:\n  - Redis: a sidecar\n  - Memory\n"
            "recommend: Redis\n```\n"
        )

        assert document.title == "Pick a queue"
        assert document.front_matter.step == "build"
        [block] = document.blocks
        assert block.kind is BlockKind.DECISION
        assert block.local_id == "D1"
        assert block.fence == Span(8, 13)
        assert [(o.label, o.text, o.recommended) for o in block.options] == [
            ("Redis", "a sidecar", True),
            ("Memory", None, False),
        ]
        assert document.faults == ()

    def test_an_empty_text_is_an_empty_document(self) -> None:
        document = parse("")

        assert document.blocks == ()
        assert document.title is None
        assert document.front_matter.span is None
        assert document.faults == ()

    def test_a_text_without_a_final_newline_keeps_its_last_line(self) -> None:
        document = parse("```question id=Q1\ndefault: none\n```")

        assert document.blocks[0].default == "none"
        assert document.blocks[0].fence == Span(1, 3)

    def test_crlf_lines_are_counted_as_lines(self) -> None:
        document = parse("# Pick\r\n\r\n```action id=A1\r\nanswer: done it\r\n```\r\n")

        assert document.title == "Pick"
        assert document.blocks[0].lines["answer"] == Span(4, 4)
        assert document.blocks[0].answer == "done it"

    def test_a_fence_indented_up_to_three_spaces_is_a_fence(self) -> None:
        document = parse("   ```question id=Q1\n   default: a\n   ```\n")

        assert document.blocks[0].default == "a"
        assert document.faults == ()

    def test_the_indentation_of_an_indented_fence_is_removed_from_its_body(
        self,
    ) -> None:
        document = parse("  ```question id=Q1\n  default: a\n  answer: b\n  ```\n")

        [block] = document.blocks
        assert (block.default, block.answer) == ("a", "b")
        assert document.faults == ()

    def test_a_line_indented_four_spaces_opens_no_fence(self) -> None:
        document = parse("    ```decision id=D1\n    options: Works\n")

        assert document.blocks == ()
        assert document.faults == ()

    def test_a_backtick_fence_whose_info_string_holds_a_backtick_is_prose(self) -> None:
        document = parse("```decision id=`D1`\noptions: Works\n")

        assert document.blocks == ()
        assert document.faults == ()

    def test_a_tilde_fence_may_carry_a_backtick_in_its_info_string(self) -> None:
        document = parse("~~~question id=Q`1\n~~~\n")

        assert document.blocks[0].local_id == "Q`1"

    def test_a_fence_line_with_an_info_string_does_not_close_a_fence(self) -> None:
        document = parse("```question id=Q1\n```python\n```\n")

        [fault] = document.faults
        assert fault.line == 2
        assert fault.message.startswith("block Q1: the body is not a YAML mapping")

    def test_a_shorter_fence_does_not_close_a_longer_one(self) -> None:
        document = parse("````question id=Q1\n```\n")

        assert document.faults == (Fault(1, "a fence opened with ```` is not closed"),)

    def test_a_fence_of_the_other_character_does_not_close_one(self) -> None:
        document = parse("```question id=Q1\n~~~\n")

        assert document.faults == (Fault(1, "a fence opened with ``` is not closed"),)

    def test_an_unclosed_fence_hides_the_blocks_after_it(self) -> None:
        document = parse("```sh\nls\n\n```question id=Q1\n")

        assert document.blocks == ()
        assert document.faults == (Fault(1, "a fence opened with ``` is not closed"),)

    def test_a_block_without_a_body_is_an_empty_block(self) -> None:
        document = parse("```question id=Q1\n```\n")

        assert document.blocks[0].lines == {}
        assert document.faults == ()

    def test_a_body_of_comments_is_an_empty_block(self) -> None:
        document = parse("```question id=Q1\n# nothing yet\n```\n")

        assert document.blocks[0].lines == {}
        assert document.faults == ()

    def test_a_yaml_error_names_the_file_line(self) -> None:
        document = parse(
            "# T\n\n```decision id=D1\noptions:\n  - a\nrecommend: a: b\n```\n"
        )

        assert document.faults == (
            Fault(
                6,
                "block D1: the body is not a YAML mapping: mapping values are not allowed here",
            ),
        )

    def test_two_yaml_documents_in_a_body_are_no_mapping(self) -> None:
        document = parse("```question id=Q1\ndefault: a\n---\ndefault: b\n```\n")

        [fault] = document.faults
        assert fault.line == 3
        assert fault.message == (
            "block Q1: the body is not a YAML mapping: expected a single document"
            " in the stream, but found another document"
        )

    def test_a_character_yaml_refuses_is_a_fault_on_the_body(self) -> None:
        document = parse("```question id=Q1\ndefault: a\x07\n```\n")

        assert document.faults == (
            Fault(
                2,
                "block Q1: the body is not a YAML mapping: special characters are not allowed",
            ),
        )

    def test_a_key_that_is_not_a_name_is_no_mapping(self) -> None:
        document = parse("```question id=Q1\n? [a, b]\n: c\n```\n")

        assert document.faults == (
            Fault(2, "block Q1: the body has a key that is not a name"),
        )

    def test_a_key_written_twice_is_no_mapping(self) -> None:
        document = parse("```question id=Q1\nanswer: a\nanswer: b\n```\n")

        assert document.faults == (Fault(3, "block Q1: the body has `answer` twice"),)
        assert document.blocks[0].answer is None

    def test_a_key_spans_its_value_lines(self) -> None:
        document = parse(
            "```action id=A1\noptions:\n  - Works\n  - Doesn't\nanswer: Works\n"
            "note: |\n  first\n  second\nby: ada\n```\n"
        )

        lines = document.blocks[0].lines
        assert lines["options"] == Span(2, 4)
        assert lines["answer"] == Span(5, 5)
        assert lines["note"] == Span(6, 8)
        assert lines["by"] == Span(9, 9)
        assert document.blocks[0].note == "first\nsecond"

    def test_a_list_s_span_ends_at_its_last_entry(self) -> None:
        document = parse(
            "```decision id=D1\noptions:\n  - Oak\n  - Pine:\n      sanded\n\n"
            "# ask about the varnish\nanswer: Oak\n```\n"
        )

        assert document.blocks[0].lines["options"] == Span(2, 5)

    def test_a_flow_list_s_span_ends_at_its_closing_bracket(self) -> None:
        document = parse("```decision id=D1\noptions: [Oak,\n  Pine]\n\n```\n")

        assert document.blocks[0].lines["options"] == Span(2, 3)

    def test_a_block_scalar_s_span_ends_at_its_last_line_that_is_not_blank(
        self,
    ) -> None:
        document = parse(
            "```question id=Q1\ndefault: |\n  two coats\n\n  then wax\n\n\n"
            "answer: wax\n```\n"
        )

        assert document.blocks[0].lines["default"] == Span(2, 5)

    def test_a_kept_block_scalar_s_span_takes_its_trailing_blank_lines(self) -> None:
        document = parse(
            "```question id=Q1\ndefault: |+\n  two coats\n\n\nanswer: x\n```\n"
        )

        assert document.blocks[0].lines["default"] == Span(2, 5)
        assert document.blocks[0].lines["answer"] == Span(6, 6)

    def test_a_front_matter_key_s_span_ends_at_its_value_s_last_line(self) -> None:
        document = parse(
            "---\nsummary: >\n  Two nights.\n\n# draft\ntitle: Tent\n---\n"
        )

        assert document.front_matter.lines["summary"] == Span(2, 3)

    @pytest.mark.parametrize(
        ("char", "name", "escape"),
        [
            ("\u2028", "U+2028", "\\u2028"),
            ("\u2029", "U+2029", "\\u2029"),
            ("\x85", "U+0085", "\\x85"),
            ("\r", "a carriage return", "\\r"),
        ],
    )
    def test_a_raw_line_break_yaml_reads_and_the_file_does_not_holds_the_body(
        self, char: str, name: str, escape: str
    ) -> None:
        document = parse(f'```question id=Q1\ndefault: a\nanswer: "x{char}y"\n```\n')

        assert document.faults == (
            Fault(
                3,
                f"block Q1: the body holds {name}, which YAML reads as a line break:"
                f" write it as `{escape}` in a double-quoted value",
            ),
        )
        assert document.blocks[0].lines == {}

    def test_a_raw_line_break_holds_the_front_matter(self) -> None:
        document = parse("---\ntitle: Tent\nsummary: two\u2028nights\n---\n")

        assert [fault.line for fault in document.faults] == [3]
        assert document.front_matter.title is None

    @pytest.mark.parametrize(
        "body",
        [
            "{default: Oak, answer: Pine, by: agent}",
            "{default: Oak,\n answer: Pine}",
            "{}",
        ],
    )
    def test_a_body_in_flow_style_is_held(self, body: str) -> None:
        document = parse(f"# Pick\n\n```question id=Q1\n{body}\n```\n")

        assert document.faults == (
            Fault(
                4,
                "block Q1: the body is a flow mapping:"
                " write each key on a line of its own",
            ),
        )
        assert document.blocks[0].lines == {}

    def test_the_front_matter_in_flow_style_is_read(self) -> None:
        document = parse("---\n{title: Tent, summary: two nights}\n---\n")

        assert (document.front_matter.title, document.faults) == ("Tent", ())

    def test_an_escaped_line_break_is_read(self) -> None:
        document = parse('```question id=Q1\nanswer: "x\\u2028y"\nby: ada\n```\n')

        [block] = document.blocks
        assert block.answer == "x\u2028y"
        assert block.lines["by"] == Span(3, 3)
        assert document.faults == ()

    @pytest.mark.parametrize("escape", ["\\0", "\\x00", "\\u0000", "\\ud800"])
    def test_an_escape_no_row_holds_holds_the_body(self, escape: str) -> None:
        document = parse(
            f'```decision id=D1\noptions:\n  - Tunnel\n  - "Dome{escape}"\n```\n'
        )

        assert document.faults == (Fault(4, NOT_TEXT.format("block D1: the body")),)
        assert document.blocks[0].options == ()

    def test_an_escape_no_row_holds_in_a_key_holds_the_body(self) -> None:
        document = parse('```decision id=D1\n"opt\\0": Dome\n```\n')

        assert document.faults == (Fault(2, NOT_TEXT.format("block D1: the body")),)

    def test_an_escape_no_row_holds_holds_the_front_matter(self) -> None:
        document = parse('---\nsummary: two\ntitle: "Tent\\0"\n---\n')

        assert document.faults == (Fault(3, NOT_TEXT.format("the front matter")),)
        assert document.front_matter.title is None

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param("options: " + "[" * 3000 + "]" * 3000, id="flow"),
            pytest.param(
                "options:\n" + "\n".join("  " * depth + "  -" for depth in range(3000)),
                id="block",
            ),
            pytest.param("options: &x\n  - *x", id="alias-of-itself"),
        ],
    )
    def test_a_body_nested_too_deep_is_held(self, body: str) -> None:
        document = parse(f"```decision id=D1\n{body}\n```\n")

        assert document.faults == (
            Fault(2, "block D1: the body is nested too deep to read"),
        )
        assert document.blocks[0].lines == {}

    def test_a_front_matter_nested_too_deep_is_held(self) -> None:
        document = parse("---\ntitle: " + "[" * 3000 + "]" * 3000 + "\n---\n")

        assert document.faults == (
            Fault(2, "the front matter is nested too deep to read"),
        )

    def test_a_first_line_of_dashes_without_a_closing_one_is_prose(self) -> None:
        document = parse("---\ntitle: Not front matter\n\n# Heading\n")

        assert document.front_matter.span is None
        assert document.title == "Heading"
        assert document.faults == ()

    def test_front_matter_below_the_first_line_is_prose(self) -> None:
        document = parse("\n---\ntitle: Not front matter\n---\n")

        assert document.front_matter.span is None
        assert document.title is None

    def test_a_block_inside_the_front_matter_is_no_block(self) -> None:
        document = parse("---\nnote: |\n  ```question id=Q1\n  ```\n---\n")

        assert document.blocks == ()
        assert document.faults == ()

    @pytest.mark.parametrize(
        ("line", "title"),
        [
            ("# Title", "Title"),
            ("###### Six", "Six"),
            ("  ## Indented", "Indented"),
            ("# Closed #", "Closed"),
            ("#\tTabbed", "Tabbed"),
            ("# A *styled* title", "A *styled* title"),
        ],
    )
    def test_an_atx_heading_gives_the_title(self, line: str, title: str) -> None:
        document = parse(f"Intro.\n\n{line}\n")

        assert document.title == title
        assert document.title_heading_line == 3

    @pytest.mark.parametrize(
        "line", ["#Hashtag", "####### Seven", "    # Indented four", "#", "#   "]
    )
    def test_a_line_that_is_no_heading_gives_no_title(self, line: str) -> None:
        assert parse(f"{line}\n").title is None

    def test_the_first_heading_is_the_title_and_later_ones_are_not(self) -> None:
        document = parse("```sh\n# a comment\n```\n\n## First\n\n# Second\n")

        assert document.title == "First"
        assert document.title_heading_line == 5

    def test_a_front_matter_title_wins_over_the_first_heading(self) -> None:
        document = parse("---\ntitle: From front matter\n---\n# From heading\n")

        assert document.title == "From front matter"
        assert document.title_heading_line is None

    def test_an_empty_front_matter_title_falls_back_to_the_heading(self) -> None:
        document = parse("---\ntitle:\n---\n# From heading\n")

        assert document.title == "From heading"
        assert document.title_heading_line == 4

    def test_urgent_is_read_without_regard_to_case(self) -> None:
        assert parse("---\nurgent: True\n---\n").front_matter.urgent is True
        assert parse("---\nurgent: FALSE\n---\n").front_matter.urgent is False
        assert parse("---\n---\n").front_matter.urgent is False

    @pytest.mark.parametrize(
        ("value", "moment"),
        [
            ("2026-10-12T09:40", datetime(2026, 10, 12, 9, 40, tzinfo=UTC)),
            ("2026-10-12 09:40", datetime(2026, 10, 12, 9, 40, tzinfo=UTC)),
            ("2026-10-12T09:40:05Z", datetime(2026, 10, 12, 9, 40, 5, tzinfo=UTC)),
            (
                "2026-10-12T09:40:05.25",
                datetime(2026, 10, 12, 9, 40, 5, 250000, tzinfo=UTC),
            ),
            (
                "2026-10-12T11:40+02:00",
                datetime(2026, 10, 12, 11, 40, tzinfo=timezone(timedelta(hours=2))),
            ),
            (
                "2026-10-12T11:40+0200",
                datetime(2026, 10, 12, 11, 40, tzinfo=timezone(timedelta(hours=2))),
            ),
        ],
    )
    def test_a_time_is_read(self, value: str, moment: datetime) -> None:
        document = parse(f"```action id=A1\ndone: {value}\n```\n")

        assert document.blocks[0].done == moment
        assert document.faults == ()

    @pytest.mark.parametrize(
        "value",
        [
            "yesterday",
            "2026-10-12",
            "09:40",
            "2026-13-01T09:40",
            "2026-10-12T25:00",
            "12/10/2026 09:40",
        ],
    )
    def test_what_is_not_a_time_is_a_fault(self, value: str) -> None:
        document = parse(f"```action id=A1\ndone: {value}\n```\n")

        assert document.blocks[0].done is None
        assert document.faults == (
            Fault(2, f"block A1: `done: {value}` is not a time"),
        )

    def test_an_explicit_app_channel_reads_as_app(self) -> None:
        document = parse("```question id=Q1\nanswer: a\nby: ada\nvia: app\n```\n")

        assert document.blocks[0].via == "app"
        assert document.faults == ()

    def test_an_answer_without_by_has_no_channel(self) -> None:
        document = parse("```question id=Q1\nanswer: a\n```\n")

        assert document.blocks[0].via is None
        assert document.faults == ()

    def test_a_deferred_action_keeps_its_answer_and_to(self) -> None:
        document = parse(
            "```action id=A1\nanswer: deferred\nby: agent\nto: verify\n```\n"
        )

        block = document.blocks[0]
        assert (block.answer, block.to, block.done) == ("deferred", "verify", None)
        assert document.faults == ()

    def test_answer_side_keys_are_taken_on_every_kind(self) -> None:
        lines = "answer: x\nby: ada\nat: 2026-10-12T09:40\nnote: n\nvia: chat\ndone: 2026-10-12T09:41\n"
        for kind in ("decision", "question", "action"):
            document = parse(f"```{kind} id=X1\n{lines}```\n")

            assert document.faults == (), kind

    def test_the_faults_of_a_parse_are_in_line_order(self) -> None:
        document = parse("```question id=Q1\n```\n```question id=Q1\nnote: [a]\n```\n")

        assert [fault.line for fault in document.faults] == [3, 4]


class TestValidate:
    def test_a_clean_document_has_no_faults(self) -> None:
        text = (
            "---\ntitle: T\nstep: build\nfor: ben\n---\n"
            "```decision id=D1\noptions:\n  - a\nanswer: deferred\nby: ada\nto: verify\n```\n"
        )

        assert validate(parse(text), FACTS) == []

    def test_the_text_s_own_faults_are_among_the_save_s(self) -> None:
        document = parse("```question id=Q1\nproposal: x\n```\n")

        assert validate(document, FACTS) == list(document.faults)

    def test_step_may_name_a_task_removed_from_the_plan(self) -> None:
        assert _messages("---\nstep: spike\n---\n") == []

    def test_step_naming_no_task_is_a_fault(self) -> None:
        assert validate(parse("---\nstep: deploy\n---\n"), FACTS) == [
            Fault(2, "front matter: `step: deploy` names no task of the project")
        ]

    def test_for_naming_no_handle_is_a_fault(self) -> None:
        assert validate(parse("---\nfor: carol\n---\n"), FACTS) == [
            Fault(2, "front matter: `for: carol` names no handle")
        ]

    @pytest.mark.parametrize(
        ("slug", "problem"),
        [
            ("Crumb", "is not lower-case letters, digits and hyphens"),
            ("crumb_app", "is not lower-case letters, digits and hyphens"),
            ("draft-7", "starts with `draft-`"),
            ("harbour", "is taken by another project"),
        ],
    )
    def test_the_draft_s_invalid_or_taken_slug_is_a_fault(
        self, slug: str, problem: str
    ) -> None:
        facts = _facts(document=DocumentKind.DRAFT)

        assert validate(parse(f"---\nslug: {slug}\n---\n"), facts) == [
            Fault(2, f"front matter: `slug: {slug}` {problem}")
        ]

    def test_the_draft_s_valid_slug_is_no_fault(self) -> None:
        facts = _facts(document=DocumentKind.DRAFT)

        assert _messages("---\nslug: crumb-2\n---\n", facts) == []

    def test_a_slug_outside_the_draft_is_not_read(self) -> None:
        assert _messages("---\nslug: Not A Slug\n---\n") == []

    def test_pilot_s_own_one_block_item_needs_a_title(self) -> None:
        facts = _facts(document=DocumentKind.OWN_ITEM)

        assert validate(parse("```question id=Q1\n```\n"), facts) == [
            Fault(
                None,
                "the item has no title: give it `title` in the front matter or a first heading",
            )
        ]

    @pytest.mark.parametrize(
        "text",
        [
            "---\ntitle: T\n---\n```question id=Q1\n```\n",
            "# T\n```question id=Q1\n```\n",
        ],
    )
    def test_either_title_source_satisfies_the_rule(self, text: str) -> None:
        assert _messages(text, _facts(document=DocumentKind.OWN_ITEM)) == []

    @pytest.mark.parametrize(
        "blocks", ["", "```question id=Q1\n```\n```question id=Q2\n```\n"]
    )
    def test_pilot_s_own_item_of_other_than_one_block_needs_no_title(
        self, blocks: str
    ) -> None:
        assert _messages(blocks, _facts(document=DocumentKind.OWN_ITEM)) == []

    @pytest.mark.parametrize(
        "document",
        [
            DocumentKind.DRAFT,
            DocumentKind.HANDBOOK,
            DocumentKind.OPENING,
            DocumentKind.REGISTERED_ITEM,
        ],
    )
    def test_no_other_document_needs_a_title(self, document: DocumentKind) -> None:
        assert _messages("```question id=Q1\n```\n", _facts(document=document)) == []

    def test_an_unknown_because_prints_the_reasons_in_their_order(self) -> None:
        facts = _facts(confirmation_reasons=("rider", "irreversible"))
        text = "```decision id=C1\ntype: confirmation\nproposal: Ship it\nbecause: hunch\n```\n"

        assert validate(parse(text), facts) == [
            Fault(
                4,
                "block C1: `because: hunch` is not a confirmation reason (rider,"
                " irreversible); the reasons are in `reference.json`",
            )
        ]

    def test_by_naming_no_handle_is_a_fault(self) -> None:
        assert _messages("```question id=Q1\nanswer: a\nby: carol\n```\n") == [
            "block Q1: `by: carol` names no handle"
        ]

    @pytest.mark.parametrize("to", ["plan", "build", "verify"])
    def test_a_written_to_naming_the_plan_or_a_task_in_it_is_no_fault(
        self, to: str
    ) -> None:
        assert (
            _messages(
                f"```question id=Q1\nanswer: deferred\nby: agent\nto: {to}\n```\n"
            )
            == []
        )

    @pytest.mark.parametrize("to", ["spike", "deploy"])
    def test_a_written_to_naming_a_removed_or_unknown_task_is_a_fault(
        self, to: str
    ) -> None:
        assert _messages(
            f"```question id=Q1\nanswer: deferred\nby: agent\nto: {to}\n```\n"
        ) == [f"block Q1: `to: {to}` names neither `plan` nor a task in the plan"]

    def test_a_to_carried_unchanged_is_not_checked_again(self) -> None:
        facts = _facts(published_to={"Q1": "spike"})

        assert (
            _messages(
                "```question id=Q1\nanswer: deferred\nby: ada\nto: spike\n```\n", facts
            )
            == []
        )

    def test_a_changed_to_is_checked(self) -> None:
        facts = _facts(published_to={"Q1": "build"})

        assert _messages(
            "```question id=Q1\nanswer: deferred\nby: agent\nto: spike\n```\n", facts
        ) == ["block Q1: `to: spike` names neither `plan` nor a task in the plan"]

    def test_a_to_carried_by_another_block_is_checked(self) -> None:
        facts = _facts(published_to={"Q2": "spike"})

        assert _messages(
            "```question id=Q1\nanswer: deferred\nby: agent\nto: spike\n```\n", facts
        ) == ["block Q1: `to: spike` names neither `plan` nor a task in the plan"]

    def test_a_to_without_deferred_is_faulted_once(self) -> None:
        assert _messages(
            "```question id=Q1\nanswer: a\nby: ada\nto: deploy\n```\n"
        ) == ["block Q1: `to` without `answer: deferred`"]
