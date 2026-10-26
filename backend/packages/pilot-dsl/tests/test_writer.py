"""The block DSL's writer: the record's splices and the merge by ownership,
and their conformance corpus."""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pilot_dsl import (
    AnswerChannel,
    DocumentKind,
    Facts,
    Fault,
    Merge,
    WriteRefused,
    clear_answer,
    merge,
    parse,
    recommendation,
    validate,
    with_facts,
    with_title,
    write_answer,
    write_done,
    write_recommended,
)

CORPUS = Path(__file__).parent / "corpus"
SPLICES = sorted((CORPUS / "splice").glob("*.json"))
MERGES = sorted((CORPUS / "merge").glob("*.json"))

AT = datetime(2026, 10, 12, 9, 40, tzinfo=UTC)

# Design 1 §6.4, its record's writes and its merge paragraph with §5.3 step 4,
# one entry per rule, each the `rule` of a splice or a merge case.
SECTION_6_4 = (
    "splice: a person's answer at the end of the block's mapping: `answer`, `by`, `at`",
    "splice: `note`, `via` and `to` where given, in that order,"
    " after `answer`, `by`, `at`",
    "splice: a person's answer replaces Pilot's `by: agent` line,"
    " its `to` and `note` with it",
    "splice: undo removes the answer lines and restores nothing",
    "splice: Done on an action writes `done` and `by`",
    "splice: Done's recommended answers, `via: recommended`, never an action's",
    "splice: the switch's `Yes`, `via: autopilot`, by the person",
    "splice: the lines written take the text's own line ending",
    "merge: the agent's prose, front matter and definitions from the save, as written",
    "merge: the agent's own `by: agent` lines from the save, as written",
    "merge: a block Pilot answered `by: agent` is the agent's to reword",
    "merge: a block a person has answered is carried whole,"
    " the save's definition reverted (F32.7)",
    "merge: a record-owned line the save changed is restored",
    "merge: a record-owned line the save dropped is restored",
    "merge: the agent's answer over a person's is reverted",
    "merge: a registered document's body prose is carried whole once a person has"
    " answered in it, its front matter the agent's",
    "merge: a registered document's body prose is the agent's until a person"
    " answers in it",
    "merge: a block the save adds to a frozen body stays where the save put it",
    "merge: a reverted body keeps the blocks the save added, after the block before them",
    "merge: a person's lines the record does not hold are dropped",
    "merge: a block the save dropped is restored whole, after the block before it",
    "merge: in the draft, a block the save dropped goes with its answers (F47.4)",
    "merge: in the draft, the definition of a block a person answered is the agent's"
    " (F47.4)",
    "merge: in the draft, a record-owned line of a block the save keeps is restored",
    "merge: every line of the opening is the record's (DB 162)",
    "merge: the save's own line endings, a restored line's among them",
)


def _case(path: Path) -> dict[str, Any]:
    case: dict[str, Any] = json.loads(path.read_text())
    return case


def _text(path: Path) -> str:
    return path.read_bytes().decode()


def _sibling(path: Path, suffix: str) -> Path:
    return path.with_name(path.name.removesuffix(".json") + suffix)


def _facts(document: DocumentKind) -> Facts:
    values = json.loads((CORPUS / "facts.json").read_text())
    return Facts(
        document=document,
        handles=set(values["handles"]),
        plan_task_ids=set(values["plan_task_ids"]),
        removed_task_ids=set(values["removed_task_ids"]),
        confirmation_reasons=tuple(values["confirmation_reasons"]),
        taken_slugs=set(values["taken_slugs"]),
        published_to={},
    )


def _splice(text: str, write: dict[str, Any]) -> str:
    """A splice case's `write` applied to its text."""
    operation = write["op"]
    if operation == "undo":
        return clear_answer(text, write["block"])
    at = datetime.fromisoformat(write["at"])
    if operation == "recommended":
        return write_recommended(text, by=write["by"], at=at)
    if operation == "done":
        return write_done(
            text, write["block"], by=write["by"], at=at, note=write.get("note")
        )
    return write_answer(
        text,
        write["block"],
        answer=write["answer"],
        by=write["by"],
        at=at,
        via=AnswerChannel(write["via"]),
        note=write.get("note"),
        to=write.get("to"),
    )


def _merge(path: Path) -> tuple[str, str, DocumentKind]:
    return (
        _text(_sibling(path, ".published.md")),
        _text(_sibling(path, ".save.md")),
        DocumentKind(_case(path)["document"]),
    )


def _clean(text: str, document: DocumentKind) -> list[Fault]:
    return validate(parse(text), _facts(document))


class TestConformanceCorpus:
    """The splice and merge cases of `corpus/`: a published text,
    the record's write or the agent's save, and the text that results."""

    @pytest.mark.parametrize("path", SPLICES, ids=lambda path: path.stem)
    def test_splice_case(self, path: Path) -> None:
        written = _splice(_text(path.with_suffix(".md")), _case(path)["write"])

        assert written == _text(path.with_suffix(".expected.md"))
        assert _clean(written, DocumentKind.REGISTERED_ITEM) == []

    @pytest.mark.parametrize("path", MERGES, ids=lambda path: path.stem)
    def test_merge_case(self, path: Path) -> None:
        published, save, document = _merge(path)
        expected = [
            Fault(fault["line"], fault["message"]) for fault in _case(path)["reverted"]
        ]

        merged = merge(published, save, document)

        assert merged == Merge(_text(_sibling(path, ".expected.md")), tuple(expected))
        assert _clean(merged.text, document) == []

    @pytest.mark.parametrize("path", MERGES, ids=lambda path: path.stem)
    def test_a_merge_case_merges_two_texts_that_publish(self, path: Path) -> None:
        published, save, document = _merge(path)

        assert _clean(published, document) == []
        assert _clean(save, document) == []

    @pytest.mark.parametrize("path", MERGES, ids=lambda path: path.stem)
    def test_a_merged_text_saved_again_merges_to_itself(self, path: Path) -> None:
        published, save, document = _merge(path)
        merged = merge(published, save, document).text

        assert merge(published, merged, document) == Merge(merged, ())

    def test_every_rule_of_section_6_4_has_a_case(self) -> None:
        rules = {_case(path)["rule"] for path in SPLICES + MERGES}

        assert set(SECTION_6_4) - rules == set()

    def test_every_case_has_its_texts(self) -> None:
        for path in SPLICES:
            assert path.with_suffix(".md").is_file(), path
            assert path.with_suffix(".expected.md").is_file(), path
        for path in MERGES:
            for suffix in (".published.md", ".save.md", ".expected.md"):
                assert _sibling(path, suffix).is_file(), (path, suffix)

    def test_the_crlf_cases_are_stored_with_crlf(self) -> None:
        assert b"\r\n" in (CORPUS / "splice" / "crlf-kept.md").read_bytes()
        assert b"\r\n" in (CORPUS / "merge" / "crlf-kept.save.md").read_bytes()


QUESTION = "# Pick\n\n```question id=Q1\ndefault: Oak\n```\n"


class TestWriteAnswer:
    @pytest.mark.parametrize(
        "value",
        [
            "Yes",
            "No",
            "2",
            "2026-10-12T12:34:00Z",
            "null",
            "Agree, but next week",
            "Neither: oil it",
            "# not a comment",
            "- not a list",
            "'quoted'",
            '"double"',
            "[a, b]",
            "x" * 200,
            "Café für Bücher",
            "a\tb",
        ],
    )
    def test_a_value_reads_back_as_written(self, value: str) -> None:
        written = write_answer(
            QUESTION, "Q1", answer=value, by="ada", at=AT, via=AnswerChannel.APP
        )

        [block] = parse(written).blocks
        assert block.answer == value
        assert parse(written).faults == ()

    def test_a_plain_value_is_written_plain(self) -> None:
        written = write_answer(
            QUESTION, "Q1", answer="Yes", by="ada", at=AT, via=AnswerChannel.APP
        )

        assert "answer: Yes\n" in written

    def test_a_note_over_several_lines_is_a_literal_block(self) -> None:
        written = write_answer(
            QUESTION,
            "Q1",
            answer="No",
            by="ada",
            at=AT,
            via=AnswerChannel.APP,
            note="Too dark.\n\nAsk ben: he has samples.",
        )

        assert "note: |-\n    Too dark.\n\n    Ask ben: he has samples.\n" in written
        assert parse(written).blocks[0].note == "Too dark.\n\nAsk ben: he has samples."

    @pytest.mark.parametrize(
        "value",
        [
            "Ran it:\n```\nok\n```",
            "a\n````\nb",
            "a\n```js\nb\n```",
            "a\n~~~\nb",
            "line\n\n\n",
            "\n\nafter two blank lines",
        ],
    )
    @pytest.mark.parametrize("fence", ["", "   "])
    def test_a_value_over_several_lines_reads_back_as_written(
        self, value: str, fence: str
    ) -> None:
        text = f"{fence}```question id=Q1\n{fence}default: Oak\n{fence}```\n\nAfter.\n"

        written = write_answer(
            text,
            "Q1",
            answer=value,
            by="ada",
            at=AT,
            via=AnswerChannel.CHAT,
            note=value,
        )

        document = parse(written)
        assert document.faults == ()
        [block] = document.blocks
        assert (block.answer, block.note, block.via) == (
            value.strip(),
            value.strip(),
            "chat",
        )
        assert written.endswith(f"{fence}via: chat\n{fence}```\n\nAfter.\n")

    @pytest.mark.parametrize("char", [" ", " ", "\x85", "\r"])
    def test_a_value_holding_a_yaml_line_break_is_escaped_on_one_line(
        self, char: str
    ) -> None:
        note = f"first{char}second"

        written = write_answer(
            QUESTION,
            "Q1",
            answer="No",
            by="ada",
            at=AT,
            via=AnswerChannel.APP,
            note=note,
        )

        document = parse(written)
        assert document.faults == ()
        assert document.blocks[0].note == note
        assert (
            document.blocks[0].lines["note"].first
            == document.blocks[0].lines["note"].last
        )

    def test_the_time_is_written_in_utc_to_the_second(self) -> None:
        moment = datetime(
            2026, 10, 12, 11, 40, 7, 123456, tzinfo=timezone(timedelta(hours=2))
        )

        written = write_answer(
            QUESTION, "Q1", answer="Oak", by="ada", at=moment, via=AnswerChannel.APP
        )

        assert "at: 2026-10-12T09:40:07Z\n" in written

    @pytest.mark.parametrize(
        ("via", "line"),
        [
            (AnswerChannel.CHAT, "via: chat\n"),
            (AnswerChannel.RECOMMENDED, "via: recommended\n"),
            (AnswerChannel.AUTOPILOT, "via: autopilot\n"),
        ],
    )
    def test_a_channel_other_than_app_writes_its_via(
        self, via: AnswerChannel, line: str
    ) -> None:
        written = write_answer(QUESTION, "Q1", answer="Oak", by="ada", at=AT, via=via)

        assert written.endswith(f"at: 2026-10-12T09:40:00Z\n{line}```\n")
        assert parse(written).blocks[0].via == str(via)

    def test_the_app_channel_writes_no_via(self) -> None:
        written = write_answer(
            QUESTION, "Q1", answer="Oak", by="ada", at=AT, via=AnswerChannel.APP
        )

        assert "via" not in written
        assert parse(written).blocks[0].via == "app"

    def test_a_person_s_answer_replaces_another_s(self) -> None:
        answered = write_answer(
            QUESTION,
            "Q1",
            answer="Oak",
            by="ada",
            at=AT,
            via=AnswerChannel.CHAT,
            note="n",
        )

        written = write_answer(
            answered, "Q1", answer="Pine", by="ben", at=AT, via=AnswerChannel.APP
        )

        assert written == (
            "# Pick\n\n```question id=Q1\ndefault: Oak\nanswer: Pine\nby: ben\n"
            "at: 2026-10-12T09:40:00Z\n```\n"
        )

    def test_a_done_action_answered_loses_its_done(self) -> None:
        text = "```action id=A1\ndone: 2026-10-11T08:00:00Z\nby: ben\n```\n"

        written = write_answer(
            text,
            "A1",
            answer="deferred",
            by="ada",
            at=AT,
            via=AnswerChannel.CHAT,
            to="plan",
        )

        [block] = parse(written).blocks
        assert (block.answer, block.done, block.to) == ("deferred", None, "plan")

    def test_only_the_named_block_is_written(self) -> None:
        text = QUESTION + "\n```question id=Q2\ndefault: Pine\n```\n"

        written = write_answer(
            text, "Q2", answer="Elm", by="ada", at=AT, via=AnswerChannel.APP
        )

        first, second = parse(written).blocks
        assert first.answer is None
        assert second.answer == "Elm"
        assert written.startswith(QUESTION)

    def test_a_block_without_keys_takes_the_lines_before_its_closing_fence(
        self,
    ) -> None:
        written = write_answer(
            "```question id=Q1\n# ask ben first\n```\n",
            "Q1",
            answer="Oak",
            by="ada",
            at=AT,
            via=AnswerChannel.APP,
        )

        assert written == (
            "```question id=Q1\n# ask ben first\nanswer: Oak\nby: ada\n"
            "at: 2026-10-12T09:40:00Z\n```\n"
        )

    def test_a_text_without_a_final_newline_keeps_it_missing(self) -> None:
        written = write_answer(
            "```question id=Q1\n```",
            "Q1",
            answer="Oak",
            by="ada",
            at=AT,
            via=AnswerChannel.APP,
        )

        assert written == (
            "```question id=Q1\nanswer: Oak\nby: ada\nat: 2026-10-12T09:40:00Z\n```"
        )

    def test_a_block_scalar_s_trailing_blank_lines_stay_after_the_answer(self) -> None:
        text = "```question id=Q1\ndefault: |\n  two coats\n  then wax\n\n```\n"

        written = write_answer(
            text, "Q1", answer="wax", by="ada", at=AT, via=AnswerChannel.APP
        )

        assert written == (
            "```question id=Q1\ndefault: |\n  two coats\n  then wax\nanswer: wax\n"
            "by: ada\nat: 2026-10-12T09:40:00Z\n\n```\n"
        )

    def test_the_answer_goes_after_a_key_the_agent_wrote_after_the_old_one(
        self,
    ) -> None:
        text = "```decision id=D1\nanswer: Oak\nby: agent\nrecommend: Oak\noptions:\n  - Oak\n```\n"

        written = write_answer(
            text, "D1", answer="Oak", by="ada", at=AT, via=AnswerChannel.APP
        )

        assert written == (
            "```decision id=D1\nrecommend: Oak\noptions:\n  - Oak\nanswer: Oak\n"
            "by: ada\nat: 2026-10-12T09:40:00Z\n```\n"
        )

    def test_a_block_the_text_lacks_is_refused(self) -> None:
        with pytest.raises(WriteRefused) as raised:
            write_answer(
                QUESTION, "D9", answer="Oak", by="ada", at=AT, via=AnswerChannel.APP
            )

        assert str(raised.value) == (
            "Cannot write an answer into block D9 because the text has no block D9"
        )


class TestWriteDone:
    def test_done_and_by_replace_the_answer_lines(self) -> None:
        text = "```action id=A1\ncheck: the drill is back\nanswer: deferred\nby: agent\nto: plan\n```\n"

        written = write_done(text, "A1", by="ben", at=AT)

        assert written == (
            "```action id=A1\ncheck: the drill is back\ndone: 2026-10-12T09:40:00Z\n"
            "by: ben\n```\n"
        )
        [block] = parse(written).blocks
        assert (block.done, block.by, block.answer, block.to) == (AT, "ben", None, None)

    def test_the_paste_back_note_goes_with_done(self) -> None:
        written = write_done(
            "```action id=A1\n```\n", "A1", by="ben", at=AT, note="Receipt 4471."
        )

        assert written.endswith("by: ben\nnote: Receipt 4471.\n```\n")

    def test_a_paste_back_holding_a_fence_stays_in_the_block(self) -> None:
        text = "# Shed\n\n```action id=A1\ncheck: the drill is back\n```\n\nAfter.\n"

        written = write_done(text, "A1", by="ben", at=AT, note="Ran it:\n```\nok\n```")

        assert written == (
            "# Shed\n\n```action id=A1\ncheck: the drill is back\n"
            "done: 2026-10-12T09:40:00Z\nby: ben\nnote: |-\n    Ran it:\n    ```\n"
            "    ok\n    ```\n```\n\nAfter.\n"
        )
        assert parse(written).blocks[0].note == "Ran it:\n```\nok\n```"

    def test_a_paste_back_ending_in_blank_lines_is_written_trimmed(self) -> None:
        written = write_done(
            "```action id=A1\n```\n", "A1", by="ben", at=AT, note="Receipt 4471.\n\n\n"
        )

        assert written == (
            "```action id=A1\ndone: 2026-10-12T09:40:00Z\nby: ben\n"
            "note: Receipt 4471.\n```\n"
        )

    def test_a_block_the_text_lacks_is_refused(self) -> None:
        with pytest.raises(WriteRefused) as raised:
            write_done("```action id=A1\n```\n", "A2", by="ben", at=AT)

        assert str(raised.value) == (
            "Cannot mark block A2 done because the text has no block A2"
        )


class TestClearAnswer:
    def test_undo_leaves_the_definition_and_every_other_line(self) -> None:
        text = (
            "Intro.\n\n```decision id=D1\noptions:\n  - Oak\n# ben's pick\n"
            "answer: Oak\nby: ben\nat: 2026-10-12T09:40:00Z\nvia: chat\n```\n\nAfter.\n"
        )

        written = clear_answer(text, "D1")

        assert written == (
            "Intro.\n\n```decision id=D1\noptions:\n  - Oak\n# ben's pick\n```\n\nAfter.\n"
        )

    def test_undo_of_an_unanswered_block_changes_nothing(self) -> None:
        assert clear_answer(QUESTION, "Q1") == QUESTION

    def test_a_block_the_text_lacks_is_refused(self) -> None:
        with pytest.raises(WriteRefused) as raised:
            clear_answer(QUESTION, "Q2")

        assert str(raised.value) == (
            "Cannot undo the answer of block Q2 because the text has no block Q2"
        )


class TestWriteRecommended:
    def test_a_text_with_nothing_to_recommend_is_unchanged(self) -> None:
        text = "# T\n\n```question id=Q1\n```\n\n```action id=A1\noptions:\n  - Done\n```\n"

        assert write_recommended(text, by="ada", at=AT) == text

    def test_a_block_pilot_answered_keeps_its_answer(self) -> None:
        text = "```question id=Q1\ndefault: Oak\nanswer: deferred\nby: agent\nto: plan\n```\n"

        assert write_recommended(text, by="ada", at=AT) == text

    def test_a_done_action_is_left_as_it_is(self) -> None:
        text = "```action id=A1\ndone: 2026-10-11T08:00:00Z\nby: ben\n```\n"

        assert write_recommended(text, by="ada", at=AT) == text


class TestWithTitle:
    @pytest.mark.parametrize(
        ("text", "titled"),
        [
            pytest.param("", "---\ntitle: Tent\n---\n", id="empty"),
            pytest.param("Prose.\n", "---\ntitle: Tent\n---\nProse.\n", id="prose"),
            pytest.param("Prose.", "---\ntitle: Tent\n---\nProse.", id="no-ending"),
            pytest.param(
                "# Which tent?\n",
                "---\ntitle: Tent\n---\n# Which tent?\n",
                id="heading",
            ),
            pytest.param(
                "---\nurgent: true\n---\nProse.\n",
                "---\ntitle: Tent\nurgent: true\n---\nProse.\n",
                id="front-matter",
            ),
            pytest.param(
                "---\r\nurgent: true\r\n---\r\nProse.\r\n",
                "---\r\ntitle: Tent\r\nurgent: true\r\n---\r\nProse.\r\n",
                id="crlf",
            ),
            pytest.param(
                "---\nProse.\n",
                "---\ntitle: Tent\n---\n---\nProse.\n",
                id="unclosed-front-matter",
            ),
        ],
    )
    def test_the_title_is_written_first_in_the_front_matter(
        self, text: str, titled: str
    ) -> None:
        assert with_title(text, "Tent") == titled

    def test_a_title_the_front_matter_gives_is_kept(self) -> None:
        text = "---\nurgent: true\ntitle: Which tent?\n---\n# Tent\n"

        assert with_title(text, "Tent") == text

    @pytest.mark.parametrize(
        ("text", "titled"),
        [
            pytest.param(
                "---\ntitle:\n---\nBody\n", "---\ntitle: Tent\n---\nBody\n", id="blank"
            ),
            pytest.param(
                "---\nurgent: true\ntitle: ''\n---\nBody\n",
                "---\nurgent: true\ntitle: Tent\n---\nBody\n",
                id="empty-quoted",
            ),
            pytest.param(
                "---\ntitle:\n  - Dome\n  - Tunnel\nurgent: true\n---\nBody\n",
                "---\ntitle: Tent\nurgent: true\n---\nBody\n",
                id="list",
            ),
        ],
    )
    def test_a_title_key_that_gives_none_is_replaced(
        self, text: str, titled: str
    ) -> None:
        assert with_title(text, "Tent") == titled
        assert parse(titled).faults == ()

    @pytest.mark.parametrize(
        "title", ["Fix: the client", "#1 priority", "yes", "  Tent  ", "'Tent'"]
    )
    def test_the_written_title_reads_back_as_given(self, title: str) -> None:
        document = parse(with_title("Prose.\n", title))

        assert document.faults == ()
        assert document.title == title.strip()


class TestWithFacts:
    @pytest.mark.parametrize(
        ("text", "written"),
        [
            pytest.param(
                "",
                "---\nstep: pitch\nurgent: true\nfor: ada\nsummary: The dome.\n---\n",
                id="empty",
            ),
            pytest.param(
                "Prose.\n",
                "---\nstep: pitch\nurgent: true\nfor: ada\nsummary: The dome.\n---\n"
                "Prose.\n",
                id="prose",
            ),
            pytest.param(
                "---\ntitle: Tent\n---\nProse.\n",
                "---\ntitle: Tent\nstep: pitch\nurgent: true\nfor: ada\n"
                "summary: The dome.\n---\nProse.\n",
                id="after-the-front-matter",
            ),
            pytest.param(
                "---\r\ntitle: Tent\r\n---\r\nProse.\r\n",
                "---\r\ntitle: Tent\r\nstep: pitch\r\nurgent: true\r\nfor: ada\r\n"
                "summary: The dome.\r\n---\r\nProse.\r\n",
                id="crlf",
            ),
        ],
    )
    def test_each_fact_is_written_in_the_front_matter(
        self, text: str, written: str
    ) -> None:
        assert (
            with_facts(
                text, step="pitch", urgent=True, addressee="ada", summary="The dome."
            )
            == written
        )
        assert parse(written).faults == ()

    def test_a_fact_the_front_matter_gives_is_kept(self) -> None:
        text = (
            "---\ntitle: Tent\nstep: camp\nurgent: true\nfor: ben\n"
            "summary: Theirs.\n---\n"
        )

        assert (
            with_facts(
                text, step="pitch", urgent=True, addressee="ada", summary="Ours."
            )
            == text
        )

    def test_a_key_that_gives_none_is_replaced_in_place(self) -> None:
        text = "---\nstep:\ntitle: Tent\nurgent: false\nfor: ''\n---\nProse.\n"

        assert with_facts(text, step="pitch", urgent=True, addressee="ada") == (
            "---\nstep: pitch\ntitle: Tent\nurgent: true\nfor: ada\n---\nProse.\n"
        )

    def test_no_fact_given_leaves_the_text_as_it_is(self) -> None:
        assert with_facts("Prose.\n") == "Prose.\n"

    def test_the_written_facts_read_back_as_given(self) -> None:
        summary = "Fix: the client\nin two lines"

        front = parse(
            with_facts(
                "Prose.\n", step="t3", urgent=True, addressee="ada", summary=summary
            )
        ).front_matter

        assert (front.step, front.urgent, front.addressee, front.summary) == (
            "t3",
            True,
            "ada",
            summary,
        )


class TestRecommendation:
    @pytest.mark.parametrize(
        ("block", "answer"),
        [
            ("decision id=D1\noptions:\n  - Oak\n  - Pine\nrecommend: Pine", "Pine"),
            ("decision id=D1\noptions:\n  - Oak\n  - Pine", None),
            ("decision id=D1\nproposal: Oil the door.", "Agree"),
            (
                "decision id=C1\ntype: confirmation\nbecause: rider\nproposal: Oil it.",
                "Yes",
            ),
            ("question id=Q1\ndefault: Oak", "Oak"),
            ("question id=Q1", None),
            ("action id=A1\noptions:\n  - Done\n  - Skipped", None),
            ("decision id=D1", None),
        ],
    )
    def test_the_recommended_answer_of_each_kind(
        self, block: str, answer: str | None
    ) -> None:
        [parsed] = parse(f"```{block}\n```\n").blocks

        assert recommendation(parsed) == answer

    def test_an_answered_block_still_has_its_recommendation(self) -> None:
        [block] = parse(
            "```question id=Q1\ndefault: Oak\nanswer: Pine\nby: ada\n```\n"
        ).blocks

        assert recommendation(block) == "Oak"


ANSWERED = (
    "# Tent\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nanswer: Tunnel\n"
    "by: ada\nat: 2026-10-12T09:40:00Z\n```\n"
)
FROZEN = "block D1 reverted: answered by a person"
PROSE = "the body prose reverted: a person has answered in the document"
TENT = "# Tent\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nrecommend: Dome\n```\n"
SEND = (
    "# Send\n\n```decision id=C1\ntype: confirmation\nbecause: auto-pilot-off\n"
    "proposal: Post the invitations today.\n```\n"
)
DRILL = "# Drill\n\n```action id=A1\ncheck: the receipt shows it returned\n```\n"
REGISTERED = (
    "---\ntitle: Tent\n---\n\nRain on the second night.\n\n```decision id=D1\n"
    "options:\n  - Dome\n  - Tunnel\nanswer: Tunnel\nby: ada\n"
    "at: 2026-10-12T09:40:00Z\n```\n"
)


class TestMerge:
    def test_a_save_equal_to_the_published_text_is_kept(self) -> None:
        assert merge(ANSWERED, ANSWERED, DocumentKind.HANDBOOK) == Merge(ANSWERED, ())

    def test_a_person_s_lines_reordered_revert_the_block(self) -> None:
        save = ANSWERED.replace(
            "by: ada\nat: 2026-10-12T09:40:00Z\n", "at: 2026-10-12T09:40:00Z\nby: ada\n"
        )

        assert merge(ANSWERED, save, DocumentKind.HANDBOOK) == Merge(
            ANSWERED, (Fault(3, FROZEN),)
        )

    def test_in_the_draft_a_person_s_lines_reordered_unchanged_are_kept(
        self,
    ) -> None:
        save = ANSWERED.replace(
            "by: ada\nat: 2026-10-12T09:40:00Z\n", "at: 2026-10-12T09:40:00Z\nby: ada\n"
        )

        assert merge(ANSWERED, save, DocumentKind.DRAFT) == Merge(save, ())

    def test_a_person_s_lines_kept_in_a_save_with_crlf_are_kept(self) -> None:
        save = ANSWERED.replace("\n", "\r\n")

        assert merge(ANSWERED, save, DocumentKind.HANDBOOK) == Merge(save, ())

    def test_a_block_the_save_emptied_gets_its_fence_back(self) -> None:
        save = "# Tent\n\n```decision id=D1\n```\n"

        assert merge(ANSWERED, save, DocumentKind.HANDBOOK) == Merge(
            ANSWERED, (Fault(3, FROZEN),)
        )

    def test_in_the_draft_a_block_the_save_emptied_gets_the_record_s_lines_back(
        self,
    ) -> None:
        save = "# Tent\n\n```decision id=D1\n```\n"

        merged = merge(ANSWERED, save, DocumentKind.DRAFT)

        assert merged.text == (
            "# Tent\n\n```decision id=D1\nanswer: Tunnel\nby: ada\n"
            "at: 2026-10-12T09:40:00Z\n```\n"
        )
        assert [fault.line for fault in merged.reverted] == [4, 5, 6]

    def test_a_renamed_block_is_restored_beside_the_new_one(self) -> None:
        save = ANSWERED.replace("id=D1", "id=D2").replace(
            "answer: Tunnel\nby: ada\nat: 2026-10-12T09:40:00Z\n", ""
        )

        merged = merge(ANSWERED, save, DocumentKind.HANDBOOK)

        assert [block.local_id for block in parse(merged.text).blocks] == ["D2", "D1"]
        assert merged.reverted == (
            Fault(9, "block D1: only the draft's blocks may be removed; restored"),
        )

    def test_an_empty_save_gets_every_block_back(self) -> None:
        published = ANSWERED + "\n```question id=Q1\n```\n"

        merged = merge(published, "", DocumentKind.HANDBOOK)

        assert merged == Merge(
            published.removeprefix("# Tent\n\n"),
            (
                Fault(1, "block D1: only the draft's blocks may be removed; restored"),
                Fault(10, "block Q1: only the draft's blocks may be removed; restored"),
            ),
        )

    def test_a_new_block_with_a_person_s_answer_loses_it(self) -> None:
        save = ANSWERED + "\n```question id=Q1\nanswer: Oak\nby: ben\n```\n"

        merged = merge(ANSWERED, save, DocumentKind.HANDBOOK)

        assert merged.text == ANSWERED + "\n```question id=Q1\n```\n"
        assert merged.reverted == (
            Fault(
                13,
                "block Q1: `answer:` is ben's answer, which the record does not hold; dropped",
            ),
            Fault(
                13,
                "block Q1: `by:` is ben's answer, which the record does not hold; dropped",
            ),
        )

    @pytest.mark.parametrize("by", ["by: agent\n", ""])
    def test_pilot_s_or_an_unowned_answer_is_the_agent_s_to_change(
        self, by: str
    ) -> None:
        published = f"```question id=Q1\nanswer: Oak\n{by}```\n"
        save = "```question id=Q1\nanswer: Pine\nby: agent\n```\n"

        assert merge(published, save, DocumentKind.HANDBOOK) == Merge(save, ())

    def test_the_faults_are_in_line_order(self) -> None:
        published = ANSWERED + "\n```question id=Q1\n```\n"
        save = (
            "# Tent\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n"
            "answer: Dome\nby: ada\nat: 2026-10-12T09:40:00Z\n```\n"
        )

        merged = merge(published, save, DocumentKind.HANDBOOK)

        assert [fault.line for fault in merged.reverted] == [3, 12]

    def test_the_opening_saved_as_published_is_kept(self) -> None:
        text = "# Shed\n\nThe roof leaks.\n"

        assert merge(text, text, DocumentKind.OPENING) == Merge(text, ())

    def test_an_opening_save_that_only_adds_lines_names_no_line(self) -> None:
        text = "# Shed\n\nThe roof leaks.\n"

        merged = merge(text, text + "And the door.\n", DocumentKind.OPENING)

        assert merged == Merge(
            text, (Fault(None, "the opening is the record's: the save is reverted"),)
        )

    def test_an_opening_save_that_drops_lines_names_the_first(self) -> None:
        text = "# Shed\n\nThe roof leaks.\n"

        merged = merge(text, "# Shed\n", DocumentKind.OPENING)

        assert merged.reverted == (
            Fault(2, "the opening is the record's: the save is reverted"),
        )

    @pytest.mark.parametrize(
        ("published", "old", "new"),
        [
            (
                write_answer(
                    TENT, "D1", answer="Tunnel", by="ada", at=AT, via=AnswerChannel.APP
                ),
                "  - Tunnel\n",
                "  - Tunnel: in the rain\n",
            ),
            (
                write_answer(
                    TENT, "D1", answer="Tunnel", by="ada", at=AT, via=AnswerChannel.CHAT
                ),
                "recommend: Dome\n",
                "recommend: Tunnel\n",
            ),
            (
                write_answer(
                    TENT,
                    "D1",
                    answer="deferred",
                    by="ada",
                    at=AT,
                    via=AnswerChannel.CHAT,
                    to="build",
                ),
                "  - Dome\n",
                "  - Dome: four people\n",
            ),
            (
                write_answer(
                    SEND,
                    "C1",
                    answer="Yes",
                    by="ada",
                    at=AT,
                    via=AnswerChannel.AUTOPILOT,
                ),
                "today.",
                "next week.",
            ),
            (
                write_done(DRILL, "A1", by="ada", at=AT),
                "it returned",
                "it paid",
            ),
            (write_recommended(TENT, by="ada", at=AT), "  - Tunnel\n", ""),
        ],
        ids=["page", "chat", "deferred", "switch", "done", "recommended"],
    )
    def test_a_person_s_answer_freezes_the_block(
        self, published: str, old: str, new: str
    ) -> None:
        [block] = parse(published).blocks
        save = published.replace(old, new)

        merged = merge(published, save, DocumentKind.OWN_ITEM)

        assert merged == Merge(
            published,
            (Fault(3, f"block {block.local_id} reverted: answered by a person"),),
        )

    def test_a_person_replacing_pilot_s_answer_freezes_the_block(self) -> None:
        pilot_s = "```question id=Q1\ndefault: Oak\nanswer: Pine\nby: agent\n```\n"
        answered = write_answer(
            pilot_s, "Q1", answer="Elm", by="ada", at=AT, via=AnswerChannel.APP
        )

        assert merge(
            pilot_s, pilot_s.replace("Oak", "Ash"), DocumentKind.OWN_ITEM
        ) == Merge(pilot_s.replace("Oak", "Ash"), ())
        assert merge(
            answered, answered.replace("Oak", "Ash"), DocumentKind.OWN_ITEM
        ) == Merge(answered, (Fault(1, "block Q1 reverted: answered by a person"),))

    def test_undo_unfreezes_the_block(self) -> None:
        published = clear_answer(ANSWERED, "D1")
        save = published.replace("  - Tunnel\n", "  - Tunnel: in the rain\n")

        assert merge(published, save, DocumentKind.HANDBOOK) == Merge(save, ())

    def test_a_block_a_person_answered_moved_whole_stays_where_the_save_put_it(
        self,
    ) -> None:
        published = ANSWERED + "\n```question id=Q1\n```\n"
        save = "# Tent\n\n```question id=Q1\n```\n\n" + ANSWERED.removeprefix(
            "# Tent\n\n"
        )

        assert merge(published, save, DocumentKind.OWN_ITEM) == Merge(save, ())

    def test_a_frozen_body_with_prose_added_at_its_end_names_no_line(self) -> None:
        save = REGISTERED + "\nPack the tarp.\n"

        merged = merge(REGISTERED, save, DocumentKind.REGISTERED_ITEM)

        assert merged == Merge(REGISTERED, (Fault(None, PROSE),))

    def test_a_frozen_body_with_prose_dropped_names_the_first_line_restored(
        self,
    ) -> None:
        save = REGISTERED.replace("Rain on the second night.\n\n", "")

        merged = merge(REGISTERED, save, DocumentKind.REGISTERED_ITEM)

        assert merged == Merge(REGISTERED, (Fault(5, PROSE),))

    def test_a_block_moved_in_a_frozen_body_goes_back(self) -> None:
        published = REGISTERED + "\n```question id=Q1\n```\n"
        save = REGISTERED.replace(
            "```decision id=D1", "```question id=Q1\n```\n\n```decision id=D1"
        )

        merged = merge(published, save, DocumentKind.REGISTERED_ITEM)

        assert merged == Merge(published, (Fault(7, PROSE),))

    @pytest.mark.parametrize(
        ("save", "expected", "line"),
        [
            (REGISTERED.replace("---\ntitle: Tent\n---\n", "# Tent\n"), REGISTERED, 4),
            (
                REGISTERED.replace("title: Tent", "summary: Which tent").replace(
                    "\n\nRain", "\n\n# Shelter\n\nRain"
                ),
                REGISTERED.replace(
                    "title: Tent", "title: Shelter\nsummary: Which tent"
                ),
                6,
            ),
            (
                REGISTERED.replace("title: Tent\n---\n", "title:\n---\n# Tent\n"),
                REGISTERED,
                4,
            ),
            (
                REGISTERED.replace("title: Tent\n---\n", "title: ''\n---\n# Tent\n"),
                REGISTERED,
                4,
            ),
        ],
        ids=[
            "no-front-matter",
            "front-matter-without-title",
            "blank-title",
            "empty-title",
        ],
    )
    def test_a_title_the_reverted_body_took_is_written_into_the_front_matter(
        self, save: str, expected: str, line: int
    ) -> None:
        merged = merge(REGISTERED, save, DocumentKind.REGISTERED_ITEM)

        assert merged == Merge(expected, (Fault(line, PROSE),))

    def test_a_reverted_body_takes_the_save_s_line_endings(self) -> None:
        save = REGISTERED.replace("Rain", "Sun").replace("\n", "\r\n")

        merged = merge(REGISTERED, save, DocumentKind.REGISTERED_ITEM)

        assert merged == Merge(REGISTERED.replace("\n", "\r\n"), (Fault(5, PROSE),))

    def test_a_reverted_body_keeps_each_block_s_faults(self) -> None:
        save = (
            REGISTERED.replace("Rain", "Sun").replace("answer: Tunnel", "answer: Dome")
            + "\n```question id=Q2\nanswer: Oak\nby: ben\n```\n"
        )

        merged = merge(REGISTERED, save, DocumentKind.REGISTERED_ITEM)

        assert merged == Merge(
            REGISTERED + "\n```question id=Q2\n```\n",
            (
                Fault(5, PROSE),
                Fault(7, FROZEN),
                Fault(
                    17,
                    "block Q2: `answer:` is ben's answer, which the record does not"
                    " hold; dropped",
                ),
                Fault(
                    17,
                    "block Q2: `by:` is ben's answer, which the record does not hold;"
                    " dropped",
                ),
            ),
        )

    def test_undo_unfreezes_the_body(self) -> None:
        published = clear_answer(REGISTERED, "D1")
        save = published.replace("Rain", "Sun")

        assert merge(published, save, DocumentKind.REGISTERED_ITEM) == Merge(save, ())

    @pytest.mark.parametrize(
        "document", [DocumentKind.OWN_ITEM, DocumentKind.HANDBOOK, DocumentKind.DRAFT]
    )
    def test_only_a_registered_document_s_body_freezes(
        self, document: DocumentKind
    ) -> None:
        save = REGISTERED.replace("Rain", "Sun")

        assert merge(REGISTERED, save, document) == Merge(save, ())
