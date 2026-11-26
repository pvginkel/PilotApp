"""The shape of a collector's publication: what a call must hold before
Pilot reads it (F152.3; DB 389, 547)."""

from datetime import timedelta
from typing import Any

import pytest
from pilot_collection.publication import PublicationSchema
from pydantic import ValidationError

from tests.support.publications import (
    STAMP,
    appended,
    builds_on,
    call,
    commit,
    compaction,
    context_part,
    event,
    file_edit,
    group,
    hook_run,
    labelling,
    launch,
    prompt,
    sub_agent,
    tool_call,
    whole,
)
from tests.support.transcripts import CAMP, STARTED
from tests.support.vocabularies import VERSION


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


def _requesting(**made: Any) -> list[dict[str, Any]]:
    """A call's Calls: one, requesting a Tool Call that made those."""
    return [call(1, tool_calls=[tool_call(1, **made)])]


MADE = ("calls", 0, "tool_calls", 0)
"""Where a call's first Tool Call stands."""


class TestMadeSchema:
    """What a Tool Call made: the commits it held at once and the file
    edits it carries (F152.11, F158.4; P-348)."""

    def test_a_tool_call_carries_none_unless_it_made_some(self) -> None:
        requested = whole(calls=_requesting()).calls[0].tool_calls[0]

        assert (requested.commits, requested.file_edits) == ([], [])

    def test_a_tool_call_carries_its_commits_and_its_file_edits(self) -> None:
        requested = (
            whole(
                calls=_requesting(
                    commits=[commit(), commit(sha=None)], file_edits=[file_edit()]
                )
            )
            .calls[0]
            .tool_calls[0]
        )

        assert [
            (made.repository, made.subject, made.sha) for made in requested.commits
        ] == [
            ("RecipeBox", "Scale the stew for six", "3f9a2c1"),
            ("RecipeBox", "Scale the stew for six", None),
        ]
        edit = requested.file_edits[0]
        assert (edit.repository, edit.path, edit.lines_added, edit.lines_removed) == (
            "RecipeBox",
            "recipes/stew.md",
            3,
            1,
        )

    @pytest.mark.parametrize(
        "sha", ["3f9a", "3f9a2c1e7b04d6a51c8f2930d4e6b7a8c9d0e1f2", "a" * 64]
    )
    def test_a_hash_is_one_git_prints_whole_or_abbreviated(self, sha: str) -> None:
        made = whole(calls=_requesting(commits=[commit(sha=sha)]))

        assert made.calls[0].tool_calls[0].commits[0].sha == sha

    @pytest.mark.parametrize("sha", ["", "3f9", "3F9A2C1", "3f9a2c1g", "a" * 65])
    def test_a_hash_git_does_not_print_is_refused(self, sha: str) -> None:
        assert _refused(calls=_requesting(commits=[commit(sha=sha)])) == [
            (*MADE, "commits", 0, "sha")
        ]

    @pytest.mark.parametrize("fact", ["repository", "subject"])
    def test_a_commit_names_its_repository_and_its_subject(self, fact: str) -> None:
        made = commit()
        del made[fact]

        assert _refused(calls=_requesting(commits=[made])) == [
            (*MADE, "commits", 0, fact)
        ]
        assert _refused(calls=_requesting(commits=[commit(**{fact: ""})])) == [
            (*MADE, "commits", 0, fact)
        ]

    @pytest.mark.parametrize(
        "fact", ["repository", "path", "lines_added", "lines_removed"]
    )
    def test_a_file_edit_names_its_file_and_its_lines(self, fact: str) -> None:
        edit = file_edit()
        del edit[fact]

        assert _refused(calls=_requesting(file_edits=[edit])) == [
            (*MADE, "file_edits", 0, fact)
        ]

    @pytest.mark.parametrize(
        ("overrides", "fact"),
        [
            ({"repository": ""}, "repository"),
            ({"path": ""}, "path"),
            ({"path": "/work/RecipeBox/recipes/stew.md"}, "path"),
            ({"lines_added": -1}, "lines_added"),
            ({"lines_removed": 2_147_483_648}, "lines_removed"),
        ],
    )
    def test_a_file_edits_path_is_within_its_checkout_and_its_lines_are_counts(
        self, overrides: dict[str, Any], fact: str
    ) -> None:
        assert _refused(calls=_requesting(file_edits=[file_edit(**overrides)])) == [
            (*MADE, "file_edits", 0, fact)
        ]

    def test_neither_takes_a_field_pilot_does_not_know(self) -> None:
        assert _refused(
            calls=_requesting(commits=[commit(message="Scale the stew\n\nFor six.")])
        ) == [(*MADE, "commits", 0, "message")]
        assert _refused(
            calls=_requesting(file_edits=[file_edit(patch="@@ -1 +1 @@")])
        ) == [(*MADE, "file_edits", 0, "patch")]


def _labelled(**labels: list[dict[str, Any]]) -> dict[str, Any]:
    """A labelling with those labels."""
    return labelling(labels=labels)


class TestLabellingSchema:
    """The labeller's labels of the Transcript, as its `label` answer's line
    gives them, each row named as both sides compute it (F152.6, F152.7)."""

    def test_a_call_carries_no_labelling_unless_a_labeller_answered(self) -> None:
        assert whole().labelling is None

    def test_a_labelling_carries_every_label(self) -> None:
        given = whole(
            labelling=labelling(
                labels={
                    "launches": [{"n": 1, "work_unit": "spring|soup"}],
                    "calls": [
                        {
                            "id": "msg_0001",
                            "segment": 1,
                            "call_class": "chop",
                            "avoidable_kind": "spilt",
                            "wait_cause": "oven",
                        }
                    ],
                    "segments": [{"position": 1, "kind": "prep"}],
                    "tool_calls": [
                        {
                            "tool_use_id": "toolu_0001",
                            "command_class": "timer",
                            "effect_kind": "order_placed",
                            "effect_subject": "ORDER-12",
                            "rules": ["no_tasting_from_the_pot"],
                        }
                    ],
                    "events": [
                        {"call": "msg_0001", "kind": "burnt", "at": STARTED.isoformat()}
                    ],
                    "context_parts": [
                        {"call": "msg_0001", "kind": "recipe_card", "characters": 40}
                    ],
                    "test_runs": [
                        {
                            "tool_use_id": "toolu_0001",
                            "suite": "RecipeBox/backend/test",
                            "passed": False,
                            "tests": 12,
                            "failures": [{"test": "t", "attempts": 2, "flaky": True}],
                        }
                    ],
                    "ci_waits": [
                        {"tool_use_id": "toolu_0001", "job": "Build", "number": 812}
                    ],
                    "documents": [
                        {
                            "id": "0b5e3c1a-0000-4f6e-9a18-2c4d6e8f0a1b",
                            "ask_category": "menu_question",
                        }
                    ],
                },
                units=[
                    {
                        "key": "spring|soup",
                        "kind": "dish",
                        "title": "Soup",
                        "round": 2,
                        "measures": [{"measure": "tastings", "amount": 3}],
                    }
                ],
                test_suites=[{"code": "RecipeBox/backend/test", "name": "RecipeBox"}],
                ci_builds=[{"job": "Build", "number": 812, "result": "DONE"}],
            )
        ).labelling

        assert given is not None
        assert (given.version, given.stamp) == (VERSION, STAMP)
        labels = given.labels
        assert labels.calls[0].segment == 1
        assert labels.tool_calls[0].rules == ["no_tasting_from_the_pot"]
        assert labels.test_runs[0].failures[0].attempts == 2
        assert labels.test_runs[0].work_unit is None
        assert given.units[0].measures[0].amount == 3
        assert given.units[0].part_of is None
        assert given.ci_builds[0].deployed_at is None

    @pytest.mark.parametrize("missing", ["version", "stamp", "labels"])
    def test_a_labelling_names_its_version_its_stamp_and_its_labels(
        self, missing: str
    ) -> None:
        given = labelling()
        del given[missing]

        assert _refused(labelling=given) == [("labelling", missing)]

    @pytest.mark.parametrize(
        ("labels", "where"),
        [
            ({"launches": [{"work_unit": "spring"}]}, ("launches", 0, "n")),
            ({"calls": [{"segment": 1}]}, ("calls", 0, "id")),
            ({"segments": [{"position": 1}]}, ("segments", 0, "kind")),
            ({"tool_calls": [{"rules": []}]}, ("tool_calls", 0, "tool_use_id")),
            (
                {"events": [{"call": "msg_0001", "kind": "burnt"}]},
                ("events", 0, "at"),
            ),
            (
                {"context_parts": [{"call": "msg_0001", "kind": "recipe_card"}]},
                ("context_parts", 0, "characters"),
            ),
            (
                {"test_runs": [{"suite": "s", "passed": True}]},
                ("test_runs", 0, "tests"),
            ),
            (
                {"ci_waits": [{"tool_use_id": "toolu_0001", "job": "Build"}]},
                ("ci_waits", 0, "number"),
            ),
            (
                {"documents": [{"ask_category": "menu_question"}]},
                ("documents", 0, "id"),
            ),
        ],
    )
    def test_a_label_names_its_row(
        self, labels: dict[str, Any], where: tuple[Any, ...]
    ) -> None:
        assert _refused(labelling=_labelled(**labels)) == [
            ("labelling", "labels", *where)
        ]

    @pytest.mark.parametrize(
        ("part", "values", "where"),
        [
            ("units", {"key": "k", "kind": "dish"}, ("units", 0, "title")),
            ("test_suites", {"code": "s"}, ("test_suites", 0, "name")),
            ("ci_builds", {"job": "Build"}, ("ci_builds", 0, "number")),
        ],
    )
    def test_what_the_labels_name_is_given_whole(
        self, part: str, values: dict[str, Any], where: tuple[Any, ...]
    ) -> None:
        assert _refused(labelling=labelling(**{part: [values]})) == [
            ("labelling", *where)
        ]

    def test_a_labelling_takes_no_field_pilot_does_not_know(self) -> None:
        assert _refused(labelling=labelling(checkpoint="opaque")) == [
            ("labelling", "checkpoint")
        ]
        assert _refused(
            labelling=_labelled(
                calls=[{"id": "msg_0001", "batchable_condition": "orient-read"}]
            )
        ) == [("labelling", "labels", "calls", 0, "batchable_condition")]
        assert _refused(
            labelling=labelling(labels={"transcript": [{"adopted_group": None}]})
        ) == [("labelling", "labels", "transcript")]

    @pytest.mark.parametrize(
        ("labelled", "where"),
        [
            ({"ci_waits": [{"tool_use_id": "t", "job": "B", "number": 0}]}, "number"),
            (
                {
                    "test_runs": [
                        {
                            "work_unit": "u",
                            "suite": "s",
                            "passed": True,
                            "tests": 1,
                            "failures": [{"test": "t", "attempts": 0, "flaky": False}],
                        }
                    ]
                },
                "attempts",
            ),
            ({"segments": [{"position": 0, "kind": "prep"}]}, "position"),
        ],
    )
    def test_a_number_or_a_place_counts_from_one(
        self, labelled: dict[str, Any], where: str
    ) -> None:
        refused = _refused(labelling=_labelled(**labelled))

        assert [location[-1] for location in refused] == [where]
