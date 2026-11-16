"""The shape of a collector's publication: what a call must hold before
Pilot reads it (F152.3; DB 389, 547)."""

from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.publication import PublicationSchema
from tests.support.publications import (
    appended,
    builds_on,
    call,
    compaction,
    context_part,
    event,
    group,
    hook_run,
    launch,
    prompt,
    sub_agent,
    tool_call,
    whole,
)
from tests.support.transcripts import CAMP, STARTED


def _refused(**overrides: Any) -> list[tuple[Any, ...]]:
    """Where the call with those overrides fails."""
    with pytest.raises(ValidationError) as refused:
        whole(**overrides)
    return [error["loc"] for error in refused.value.errors()]


class TestPublicationSchema:
    def test_a_call_with_the_files_facts_alone_is_a_main_threads(self) -> None:
        publication = whole()

        assert (publication.session_id, publication.agent_id) == (CAMP, None)
        assert publication.file_modified_at.utcoffset() is not None
        assert (publication.launches, publication.compactions, publication.calls) == (
            [],
            [],
            [],
        )
        assert (publication.repository, publication.environment) == (None, None)

    def test_a_call_carries_every_part(self) -> None:
        publication = whole(
            launches=[launch(prompts=[prompt(hook_runs=[hook_run()])])],
            compactions=[compaction()],
            calls=[
                call(
                    1,
                    prompt=1,
                    compaction=1,
                    tool_calls=[tool_call(1)],
                    events=[event()],
                    context_parts=[context_part()],
                )
            ],
        )

        ran = publication.launches[0]
        assert ran.started_at == STARTED
        assert ran.ended_at is None
        assert ran.prompts[0].hook_runs[0].command == "signal_activity.sh"
        assert publication.calls[0].tokens == {
            "input": 1_204,
            "cache_write_1h": 3_310,
            "cache_read": 48_112,
            "output": 2_870,
        }
        requested = publication.calls[0].tool_calls[0]
        assert (requested.tool_use_id, requested.tool) == ("toolu_0001", "Bash")
        assert (requested.mcp_server, requested.exit_code) == (None, None)
        assert requested.requested_at == STARTED + timedelta(minutes=1)
        marked = publication.calls[0].events[0]
        assert (marked.kind, marked.is_error, marked.detail) == (
            "api_error",
            True,
            "529",
        )
        carried = publication.calls[0].context_parts[0]
        assert (carried.kind, carried.name, carried.characters) == (
            "system_prompt",
            None,
            9_100,
        )

    def test_a_call_that_did_nothing_carries_no_part_of_what_one_does(self) -> None:
        requested = whole(calls=[call(1)]).calls[0]

        assert (requested.tool_calls, requested.events, requested.context_parts) == (
            [],
            [],
            [],
        )

    def test_a_sub_agents_thread_names_its_spawning_call(self) -> None:
        assert sub_agent().spawned_by == "toolu_0031"
        assert sub_agent(spawned_by=None).spawned_by is None
        assert whole().spawned_by is None

    @pytest.mark.parametrize(
        ("part", "values", "missing"),
        [
            ("tool_calls", tool_call(1), "tool_use_id"),
            ("tool_calls", tool_call(1), "tool"),
            ("tool_calls", tool_call(1), "requested_at"),
            ("tool_calls", tool_call(1), "failed"),
            ("tool_calls", tool_call(1), "interrupted"),
            ("events", event(), "kind"),
            ("events", event(), "is_error"),
            ("events", event(), "at"),
            ("context_parts", context_part(), "kind"),
            ("context_parts", context_part(), "characters"),
        ],
    )
    def test_what_a_call_did_holds_its_own_facts(
        self, part: str, values: dict[str, Any], missing: str
    ) -> None:
        del values[missing]

        assert _refused(calls=[call(1, **{part: [values]})]) == [
            ("calls", 0, part, 0, missing)
        ]

    @pytest.mark.parametrize(
        "missing",
        [
            "session_id",
            "file_size",
            "file_modified_at",
            "collector",
            "working_directory",
        ],
    )
    def test_the_transcripts_own_facts_are_required(self, missing: str) -> None:
        values = whole().model_dump(mode="json", exclude_unset=True)
        del values[missing]

        with pytest.raises(ValidationError) as refused:
            PublicationSchema.model_validate(values)

        assert [error["loc"] for error in refused.value.errors()] == [(missing,)]

    def test_a_field_pilot_does_not_take_is_refused(self) -> None:
        assert _refused(transcript="the words of the conversation") == [("transcript",)]
        assert _refused(calls=[call(1, text="Scale the recipe")]) == [
            ("calls", 0, "text")
        ]
        assert _refused(
            calls=[call(1, tool_calls=[tool_call(1, output="flour.md")])]
        ) == [("calls", 0, "tool_calls", 0, "output")]
        assert _refused(calls=[call(1, events=[event(message="Overloaded")])]) == [
            ("calls", 0, "events", 0, "message")
        ]
        assert _refused(
            calls=[call(1, context_parts=[context_part(text="You are a cook")])]
        ) == [("calls", 0, "context_parts", 0, "text")]

    def test_a_call_names_no_group_unless_its_labels_do(self) -> None:
        assert whole().group is None

    def test_a_group_is_its_key_its_name_and_its_summary(self) -> None:
        named = whole(group=group()).group

        assert named is not None
        assert (named.key, named.name, named.summary) == (
            "recipe-box-first-menus",
            "Recipe box: the first menus",
            "The menus Ada wrote by hand, before the recipe box.",
        )

    @pytest.mark.parametrize("fact", ["key", "name", "summary"])
    def test_a_group_names_all_three(self, fact: str) -> None:
        named = group()
        del named[fact]

        assert _refused(group=named) == [("group", fact)]

    @pytest.mark.parametrize("fact", ["key", "name"])
    def test_a_groups_key_and_name_are_not_empty(self, fact: str) -> None:
        assert _refused(group=group(**{fact: ""})) == [("group", fact)]

    def test_a_group_with_no_summary_is_taken(self) -> None:
        named = whole(group=group(summary="")).group

        assert named is not None
        assert named.summary == ""

    def test_a_group_takes_no_field_pilot_does_not_know(self) -> None:
        assert _refused(group=group(slices=["012"])) == [("group", "slices")]

    def test_a_call_without_appended_is_whole(self) -> None:
        assert whole().appended is None

    def test_an_appended_call_names_what_it_builds_on_and_its_boundary(self) -> None:
        publication = appended(call=7, launch=2, prompt=5, compaction=3)

        assert publication.appended is not None
        base = publication.appended.builds_on
        assert (base.file_size, base.collector) == (48_112, "1.0.0")
        assert base.file_modified_at == STARTED + timedelta(minutes=12)
        assert publication.appended.boundary.model_dump() == {
            "call": 7,
            "launch": 2,
            "prompt": 5,
            "compaction": 3,
        }
        assert publication.file_size == 61_000

    @pytest.mark.parametrize("part", ["builds_on", "boundary"])
    def test_an_appended_call_names_both(self, part: str) -> None:
        values = appended().model_dump(mode="json", exclude_unset=True)
        del values["appended"][part]

        with pytest.raises(ValidationError) as refused:
            PublicationSchema.model_validate(values)

        assert [error["loc"] for error in refused.value.errors()] == [
            ("appended", part)
        ]

    @pytest.mark.parametrize("place", ["call", "launch", "prompt", "compaction"])
    def test_a_boundary_names_each_place_from_1(self, place: str) -> None:
        values = appended().model_dump(mode="json", exclude_unset=True)
        boundary = values["appended"]["boundary"]

        with pytest.raises(ValidationError) as refused:
            PublicationSchema.model_validate(
                values
                | {"appended": values["appended"] | {"boundary": boundary | {place: 0}}}
            )
        assert [error["loc"] for error in refused.value.errors()] == [
            ("appended", "boundary", place)
        ]

        del boundary[place]
        with pytest.raises(ValidationError) as refused:
            PublicationSchema.model_validate(values)
        assert [error["loc"] for error in refused.value.errors()] == [
            ("appended", "boundary", place)
        ]

    @pytest.mark.parametrize("fact", ["file_size", "file_modified_at", "collector"])
    def test_what_an_appended_call_builds_on_is_required(self, fact: str) -> None:
        base = builds_on()
        del base[fact]

        with pytest.raises(ValidationError) as refused:
            appended(builds_on=base)

        assert [error["loc"] for error in refused.value.errors()] == [
            ("appended", "builds_on", fact)
        ]

    def test_an_appended_call_takes_no_field_pilot_does_not_know(self) -> None:
        with pytest.raises(ValidationError) as refused:
            appended(builds_on=builds_on(checkpoint="opaque"))

        assert [error["loc"] for error in refused.value.errors()] == [
            ("appended", "builds_on", "checkpoint")
        ]

    def test_a_launch_runs_with_a_version(self) -> None:
        """DB 389."""
        assert _refused(launches=[launch(components=[])]) == [
            ("launches", 0, "components")
        ]

    def test_a_calls_tokens_are_of_a_kind_nothing_is_within(self) -> None:
        """DB 547: `cache_write` has the five-minute and the one-hour kinds
        within it."""
        assert _refused(calls=[call(1, tokens={"cache_write": 3_310})]) == [
            ("calls", 0, "tokens", "cache_write", "[key]")
        ]

    def test_a_files_size_is_one_every_json_reader_takes_exactly(self) -> None:
        assert whole(file_size=2**53 - 1).file_size == 9_007_199_254_740_991

    def test_a_time_names_its_offset(self) -> None:
        assert _refused(file_modified_at="2026-11-12T09:42:00") == [
            ("file_modified_at",)
        ]

    @pytest.mark.parametrize(
        ("overrides", "where"),
        [
            ({"file_size": -1}, ("file_size",)),
            ({"file_size": 2**53}, ("file_size",)),
            (
                {"calls": [call(1, tokens={"output": -1})]},
                ("calls", 0, "tokens", "output"),
            ),
            (
                {"calls": [call(1, tokens={"output": 2_147_483_648})]},
                ("calls", 0, "tokens", "output"),
            ),
            ({"calls": [call(1, prompt=0)]}, ("calls", 0, "prompt")),
            ({"calls": [call(1, compaction=0)]}, ("calls", 0, "compaction")),
            (
                {"launches": [launch(prompts=[prompt(characters=-1)])]},
                ("launches", 0, "prompts", 0, "characters"),
            ),
            (
                {"compactions": [compaction(tokens_before=-1)]},
                ("compactions", 0, "tokens_before"),
            ),
            (
                {"calls": [call(1, tool_calls=[tool_call(1, result_characters=-1)])]},
                ("calls", 0, "tool_calls", 0, "result_characters"),
            ),
            (
                {"calls": [call(1, tool_calls=[tool_call(1, saved_characters=-1)])]},
                ("calls", 0, "tool_calls", 0, "saved_characters"),
            ),
            (
                {
                    "calls": [
                        call(1, tool_calls=[tool_call(1, exit_code=2_147_483_648)])
                    ]
                },
                ("calls", 0, "tool_calls", 0, "exit_code"),
            ),
            (
                {"calls": [call(1, context_parts=[context_part(characters=-1)])]},
                ("calls", 0, "context_parts", 0, "characters"),
            ),
        ],
    )
    def test_a_count_is_one_the_record_holds(
        self, overrides: dict[str, Any], where: tuple[Any, ...]
    ) -> None:
        assert _refused(**overrides) == [where]

    @pytest.mark.parametrize(
        ("overrides", "where"),
        [
            ({"session_id": ""}, ("session_id",)),
            ({"agent_id": ""}, ("agent_id",)),
            ({"repository": ""}, ("repository",)),
            ({"environment": ""}, ("environment",)),
            ({"collector": {"version": ""}}, ("collector", "version")),
            ({"calls": [call(1, message_id="")]}, ("calls", 0, "message_id")),
            ({"calls": [call(1, model="")]}, ("calls", 0, "model")),
            ({"agent_id": "a4f1c09e2b7d3e586", "spawned_by": ""}, ("spawned_by",)),
            (
                {"calls": [call(1, tool_calls=[tool_call(1, tool_use_id="")])]},
                ("calls", 0, "tool_calls", 0, "tool_use_id"),
            ),
            (
                {"calls": [call(1, tool_calls=[tool_call(1, tool="")])]},
                ("calls", 0, "tool_calls", 0, "tool"),
            ),
            (
                {"calls": [call(1, tool_calls=[tool_call(1, mcp_server="")])]},
                ("calls", 0, "tool_calls", 0, "mcp_server"),
            ),
            (
                {"calls": [call(1, tool_calls=[tool_call(1, denial_kind="")])]},
                ("calls", 0, "tool_calls", 0, "denial_kind"),
            ),
            (
                {"calls": [call(1, events=[event(kind="")])]},
                ("calls", 0, "events", 0, "kind"),
            ),
            (
                {"calls": [call(1, context_parts=[context_part(kind="")])]},
                ("calls", 0, "context_parts", 0, "kind"),
            ),
        ],
    )
    def test_a_name_is_not_empty(
        self, overrides: dict[str, Any], where: tuple[Any, ...]
    ) -> None:
        assert _refused(**overrides) == [where]
