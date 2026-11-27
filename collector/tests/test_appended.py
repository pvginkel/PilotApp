"""A transcript's file read from its boundary on (F152.15): the carry a
reading leaves, the appended publication of a file that grew, and where the
file is read whole instead."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from pilot_collection.publication import PublicationSchema
from pilot_scenario import SCENARIO, Builder, Scenario

from pilot_collector import VERSION
from pilot_collector.carry import (
    ROOT,
    Carry,
    Checkpoint,
    Fork,
    Lead,
    Left,
    Occurred,
    Open,
    Opening,
    Part,
    Prompted,
    Ran,
    Requested,
    Shape,
    Standing,
    Unhashed,
    digest,
)
from pilot_collector.home import Transcript, transcript
from pilot_collector.reader import NotContinuedError, Read, UnreadableError, read
from tests import support
from tests.support import (
    AGENT,
    DIRECTORY,
    MANAGED,
    Line,
    answering,
    assistant,
    attached,
    boundary,
    chained,
    cost,
    erred,
    expanded,
    fallback,
    fell_back,
    filed,
    finished,
    hooked,
    instructions,
    interruption,
    linked,
    loaded,
    moment,
    queue,
    recorded,
    request,
    requesting,
    result,
    retried,
    sent,
    shaped,
    snapshot,
    summary,
    taken,
    typed,
    user,
)
from tests.test_reader import (
    FORKED,
    LOOM,
    SCHEMAS,
    SPAWNING,
    UNTIL,
    WEAVE,
    _committing,
    _forked,
    _made,
    _resumed,
)

SETTINGS = support.settings()


def _added(named: Transcript, lines: list[Line]) -> None:
    """Append the lines to the file."""
    with named.path.open("ab") as file:
        file.write(support.content(lines))


def _grown(
    projects: Path, first: list[Line], then: list[Line], agent: str | None = None
) -> tuple[Read, Read]:
    """A thread's file holding `first`, read, then grown by `then` and read
    from where the first reading stood: both readings."""
    named = filed(projects, first, agent)
    before = read(named, SETTINGS)
    _added(named, then)
    return before, read(named, SETTINGS, before.carry)


def _continuing(last: str, lines: list[Line], name: str = "grown") -> list[Line]:
    """The lines as a chain that goes on from the line `last` names."""
    first, *rest = linked(lines, name)
    follows = "logicalParentUuid" if "logicalParentUuid" in first else "parentUuid"
    return [first | {follows: last}, *rest]


def _held(held: PublicationSchema, grown: PublicationSchema) -> PublicationSchema:
    """What Pilot holds once it took `grown`, an appended publication, of a
    transcript it held as `held`: what lies before the boundary's places as
    it was, and from them on what the call carries."""
    assert grown.appended is not None
    boundary = grown.appended.boundary
    before = held.launches[: boundary.launch - 1]
    kept = boundary.prompt - 1 - sum(len(launch.prompts) for launch in before)
    carried = list(grown.launches)
    if carried and boundary.launch <= len(held.launches):
        first = held.launches[boundary.launch - 1]
        carried[0] = carried[0].model_copy(
            update={"prompts": first.prompts[:kept] + carried[0].prompts}
        )
    return grown.model_copy(
        update={
            "appended": None,
            "launches": before + carried,
            "compactions": held.compactions[: boundary.compaction - 1]
            + grown.compactions,
            "calls": held.calls[: boundary.call - 1] + grown.calls,
        }
    )


def _ticks(count: int) -> list[Line]:
    """That many `system` lines, each a second after the one before."""
    return [
        chained("system", 5 + place / 10, subtype="turn_duration", durationMs=1_000)
        for place in range(count)
    ]


def _places(publication: PublicationSchema) -> tuple[int, int, int, int]:
    """The four places an appended publication's boundary names."""
    assert publication.appended is not None
    boundary = publication.appended.boundary
    return boundary.call, boundary.launch, boundary.prompt, boundary.compaction


class TestTheCarry:
    def test_it_stands_before_the_files_last_call(self, tmp_path: Path) -> None:
        lines = linked(
            [
                typed(0),
                requesting(4, "toolu_01", message_id="msg_01"),
                result(6, "toolu_01"),
                assistant(9, "msg_02", output=3),
                assistant(10, "msg_02", output=8),
            ]
        )
        named = filed(tmp_path, lines)

        carry = read(named, SETTINGS).carry

        status = named.path.stat()
        assert (carry.file_size, carry.collector) == (status.st_size, VERSION)
        assert (
            carry.file_modified_at == read(named, SETTINGS).publication.file_modified_at
        )
        assert carry.stands == Standing(
            byte=len(support.content(lines[:3])),
            calls=1,
            launches=0,
            prompts=1,
            compactions=0,
            link="line-3",
            leads=Lead(
                "msg_01",
                left=Left(
                    place=0,
                    completed_at=moment(4),
                    model="claude-opus-4-5",
                    effort=None,
                    version=support.VERSION,
                    cached=0,
                    hour=False,
                    shape=None,
                    sent=None,
                ),
            ),
            directory=DIRECTORY,
            environment=None,
            launch=Open(moment(0), support.VERSION, 1, moment(6)),
            prompt=Prompted(moment(0), "typed", len("Warp the loom.")),
            queue=(),
        )
        assert carry.end == digest(support.content(lines[3:]))

    def test_a_file_with_no_call_stands_at_its_start(self, tmp_path: Path) -> None:
        lines = [typed(0)]

        carry = read(filed(tmp_path, lines), SETTINGS).carry

        assert carry.stands == Standing()
        assert carry.end == digest(support.content(lines))

    def test_a_later_line_of_an_earlier_response_moves_no_boundary(
        self, tmp_path: Path
    ) -> None:
        lines = [
            typed(0),
            assistant(4, "msg_01", output=1),
            assistant(5, "msg_02", output=1),
            assistant(6, "msg_01", output=9),
        ]

        stands = read(filed(tmp_path, lines), SETTINGS).carry.stands

        assert (stands.byte, stands.calls) == (len(support.content(lines[:2])), 1)

    def test_it_counts_the_launches_that_exited_and_names_the_one_open(
        self, tmp_path: Path
    ) -> None:
        later = {"version": "2.1.318"}
        lines = [
            typed(0),
            assistant(4, "msg_01"),
            cost(),
            typed(60) | later,
            typed(61) | later,
            assistant(64, "msg_02") | later,
        ]

        stands = read(filed(tmp_path, lines), SETTINGS).carry.stands

        assert (stands.launches, stands.prompts) == (1, 3)
        assert stands.launch == Open(moment(60), "2.1.318", 2, moment(61))

    def test_no_launch_is_open_where_the_last_call_starts_one(
        self, tmp_path: Path
    ) -> None:
        lines = [typed(0), assistant(4, "msg_01"), cost(), assistant(64, "msg_02")]

        stands = read(filed(tmp_path, lines), SETTINGS).carry.stands

        assert (stands.launches, stands.launch) == (1, None)

    def test_a_launch_that_named_no_version_and_exited_is_not_counted(
        self, tmp_path: Path
    ) -> None:
        lines = [
            queue("enqueue", 0),
            cost(),
            typed(60),
            assistant(64, "msg_01"),
        ]

        stands = read(filed(tmp_path, lines), SETTINGS).carry.stands

        assert (stands.launches, stands.launch) == (
            0,
            Open(moment(60), support.VERSION, 1, moment(60)),
        )

    def test_it_holds_the_open_launchs_end_and_the_plugins_it_named(
        self, tmp_path: Path
    ) -> None:
        lines = linked(
            [
                typed(0),
                expanded(1, None, support.plugin_body("dev", "0.10.92")),
                assistant(4, "msg_01"),
                assistant(9, "msg_02"),
                assistant(10, "msg_02"),
            ]
        )

        stands = read(filed(tmp_path, lines), SETTINGS).carry.stands

        assert stands.launch == Open(
            moment(0), support.VERSION, 1, moment(4), None, (("dev", "0.10.92"),)
        )

    def test_it_holds_where_the_lines_since_one_named_a_version_began(
        self, tmp_path: Path
    ) -> None:
        """A line from the boundary on that names another version starts a
        Launch from there."""
        lines = [
            typed(0),
            assistant(4, "msg_01"),
            queue("enqueue", 60, "Thread the heddles."),
            queue("dequeue", 60.2),
            assistant(64, "msg_02"),
        ]

        stands = read(filed(tmp_path, lines), SETTINGS).carry.stands

        assert stands.launch == Open(
            moment(0), support.VERSION, 1, moment(60.2), (moment(4), moment(60))
        )

    def test_the_plugins_the_launch_open_named_count_in_its_size(
        self, tmp_path: Path
    ) -> None:
        def size(*plugins: str) -> int:
            lines = [
                typed(0),
                *(
                    expanded(1, None, support.plugin_body(plugin, "0.3.1"))
                    for plugin in plugins
                ),
                assistant(4, "msg_01"),
            ]
            return read(filed(tmp_path, linked(lines)), SETTINGS).carry.size

        assert size("dev", "kubecoder") > size("dev") > size()

    def test_it_holds_the_prompts_waiting_in_the_queue(self, tmp_path: Path) -> None:
        lines = [
            typed(0),
            queue("enqueue", 2, "Thread the heddles."),
            queue("enqueue", 3, "Tie the treadles."),
            queue("remove", 3.5, "Tie the treadles."),
            assistant(4, "msg_01"),
            queue("enqueue", 5, "Wind the bobbins."),
        ]

        stands = read(filed(tmp_path, lines), SETTINGS).carry.stands

        assert stands.queue == ((digest(b"Thread the heddles."), moment(2)),)

    def test_it_holds_the_prompts_a_remove_took_out_that_none_claimed(
        self, tmp_path: Path
    ) -> None:
        lines = [
            typed(0),
            queue("enqueue", 2, "Thread the heddles."),
            queue("enqueue", 3, "Tie the treadles."),
            queue("remove", 3.5, "Tie the treadles."),
            queue("remove", 3.6, "Thread the heddles."),
            taken(3.7, "Thread the heddles."),
            assistant(4, "msg_01"),
        ]

        stands = read(filed(tmp_path, lines), SETTINGS).carry.stands

        assert (stands.queue, stands.removed) == (
            (),
            ((digest(b"Tie the treadles."), moment(3)),),
        )

    def test_a_sub_agents_thread_has_no_launch_open(self, tmp_path: Path) -> None:
        lines = [user(0), assistant(4, "msg_01"), assistant(9, "msg_02")]

        stands = read(filed(tmp_path, lines, AGENT), SETTINGS).carry.stands

        assert (stands.calls, stands.launches, stands.prompts) == (1, 0, 0)
        assert stands.launch is None

    def test_a_forks_thread_holds_the_call_that_started_it(
        self, tmp_path: Path
    ) -> None:
        named = filed(tmp_path, _forked(), AGENT)
        recorded(tmp_path, **FORKED)

        stands = read(named, SETTINGS).carry.stands

        assert stands.fork == Fork(SPAWNING, "msg_02", moment(9))
        assert stands.calls == 0

    def test_a_fork_with_no_call_of_its_own_stands_at_its_start(
        self, tmp_path: Path
    ) -> None:
        named = filed(tmp_path, _forked()[:-1], AGENT)
        recorded(tmp_path, **FORKED)

        stands = read(named, SETTINGS).carry.stands

        assert (stands.byte, stands.fork) == (0, Fork(SPAWNING, "msg_02", moment(9)))

    def test_a_fork_whose_file_holds_no_line_of_its_call_holds_the_call_alone(
        self, tmp_path: Path
    ) -> None:
        named = filed(tmp_path, _forked()[:3], AGENT)
        recorded(tmp_path, **FORKED)

        assert read(named, SETTINGS).carry.stands.fork == Fork(SPAWNING)

    def test_no_other_thread_holds_a_fork(self, tmp_path: Path) -> None:
        main = filed(tmp_path, linked([typed(0), assistant(4)]))
        agent = filed(tmp_path, _forked(), AGENT)
        recorded(tmp_path, **(FORKED | {"agentType": "general-purpose"}))

        assert read(main, SETTINGS).carry.stands.fork is None
        assert read(agent, SETTINGS).carry.stands.fork is None

    def test_it_holds_where_the_chain_leads_from_its_line_and_no_other_lines(
        self, tmp_path: Path
    ) -> None:
        """The Call the chain leads to and the compaction crossed on the
        way, however many lines and Calls lie before the boundary (D256)."""
        lines = [typed(0)]
        for place in range(1, 41):
            lines += [typed(10 * place), assistant(10 * place + 4, f"msg_{place:02}")]
        lines += [boundary(500), summary(499.7), assistant(510, "msg_41")]

        carry = read(filed(tmp_path, linked(lines)), SETTINGS).carry

        stands = carry.stands
        assert (stands.calls, stands.compactions) == (40, 1)
        assert (stands.link, stands.leads.call, stands.leads.compaction) == (
            "line-83",
            "msg_40",
            1,
        )
        few = read(filed(tmp_path, linked(lines[-5:], "lines")), SETTINGS).carry
        assert (few.stands.calls, few.stands.link) == (1, "lines-4")
        assert carry.size == few.size

    def test_a_chain_that_reaches_no_call_leads_nowhere(self, tmp_path: Path) -> None:
        lines = [typed(0), assistant(4, "msg_01")]

        stands = read(filed(tmp_path, linked(lines)), SETTINGS).carry.stands

        assert (stands.link, stands.leads) == ("line-1", ROOT)

    def test_it_holds_the_lines_named_before_it_that_the_file_holds_none_of_there(
        self, tmp_path: Path
    ) -> None:
        """A line of another file, and one written after the boundary's
        first: the chain leads from the carry's line as the lines before the
        boundary stand, nowhere, where the Call's own goes on through the
        line written late."""
        lines = linked([typed(0), assistant(4, "msg_01"), *_ticks(4), assistant(9)])
        lines[0]["parentUuid"] = "a-line-of-another-file"
        lines[-1]["message"]["id"] = "msg_02"
        late = [lines[at] for at in (0, 1, 2, 3, 5, 6, 4)]

        taken = read(filed(tmp_path, late), SETTINGS)

        stands = taken.carry.stands
        assert stands.byte == len(support.content(late[:5]))
        assert stands.awaited == ("a-line-of-another-file", "line-5")
        assert (stands.link, stands.leads) == ("line-6", ROOT)
        assert taken.publication.calls[-1].predecessor == "msg_01"

    def test_it_holds_no_line_written_early_whose_line_stands_before_it(
        self, tmp_path: Path
    ) -> None:
        lines = linked([typed(0), assistant(4, "msg_01"), *_ticks(2), assistant(9)])
        lines[-1]["message"]["id"] = "msg_02"
        early = [lines[at] for at in (0, 1, 3, 2, 4)]

        stands = read(filed(tmp_path, early), SETTINGS).carry.stands

        assert stands.awaited == ()
        assert (stands.link, stands.leads.call) == ("line-3", "msg_01")

    def test_it_holds_the_requests_written_since_the_last_one_a_call_named(
        self, tmp_path: Path
    ) -> None:
        """The boundary's Call's request among them, and one a later Call's
        lines name, written before the boundary."""
        lines = [
            typed(0),
            request(1, "request-1"),
            sent(assistant(4, "msg_01"), "request-1"),
            request(6, "request-2"),
            request(9.5, "request-3"),
            sent(assistant(9, "msg_02"), "request-2"),
            request(10, "request-4"),
        ]

        stands = read(filed(tmp_path, lines), SETTINGS).carry.stands

        assert stands.requests == (
            Requested("request-2", moment(6)),
            Requested("request-3", moment(9.5)),
        )

    def test_a_request_held_counts_in_its_size_with_its_id(
        self, tmp_path: Path
    ) -> None:
        def size(*requests: str) -> int:
            lines = [
                typed(0),
                assistant(4, "msg_01"),
                *(request(5, named) for named in requests),
                sent(assistant(9, "msg_02"), "request-1"),
            ]
            return read(filed(tmp_path, lines), SETTINGS).carry.size

        none, short, long = size(), size("request-1"), size("request-1-of-a-retry")

        assert long - short == len("-of-a-retry")
        assert short - none > len("request-1")

    def test_the_call_its_chain_leads_to_counts_in_its_size(
        self, tmp_path: Path
    ) -> None:
        short = [typed(0), assistant(4, "msg_01"), assistant(9, "msg_02")]
        long = [typed(0), assistant(4, "msg_01" + "0" * 20), assistant(9, "msg_02")]

        sizes = [
            read(filed(tmp_path, linked(lines)), SETTINGS).carry.size
            for lines in (short, long)
        ]

        assert sizes[1] - sizes[0] == 20

    def test_it_holds_what_the_call_its_chain_leads_to_left_and_no_other_calls(
        self, tmp_path: Path
    ) -> None:
        """Its place and completion, its model, effort and version, what it
        left in the cache, and what its request sent (D256)."""
        lines = [typed(0)]
        for place in range(1, 41):
            lines += [typed(10 * place), assistant(10 * place + 4, f"msg_{place:02}")]
        lines += [
            typed(500),
            request(501, "request-41", shapeHash="a1", keep=80, tail=["x", "y"]),
            sent(
                assistant(504, "msg_41", cache_read=900, cache_write_1h=100)
                | {"effort": "high"},
                "request-41",
            ),
            typed(510),
            assistant(514, "msg_42"),
        ]

        stands = read(filed(tmp_path, linked(lines)), SETTINGS).carry.stands

        assert stands.leads.left == Left(
            place=40,
            completed_at=moment(504),
            model="claude-opus-4-5",
            effort="high",
            version=support.VERSION,
            cached=1_000,
            hour=True,
            shape="a1",
            sent=82,
        )

    def test_it_holds_the_events_before_the_first_call_and_none_after(
        self, tmp_path: Path
    ) -> None:
        first = read(
            filed(tmp_path, [typed(0), retried(1), assistant(4, "msg_01")]), SETTINGS
        ).carry.stands
        later = read(
            filed(
                tmp_path,
                [typed(0), assistant(2, "msg_01"), retried(3), assistant(4, "msg_02")],
            ),
            SETTINGS,
        ).carry.stands

        assert first.events == (Occurred("api_retry", moment(1), "529"),)
        assert later.events == ()

    def test_what_the_call_its_chain_leads_to_left_counts_in_its_size(
        self, tmp_path: Path
    ) -> None:
        def size(model: str) -> int:
            lines = [typed(0), assistant(4, "msg_01", model), assistant(9, "msg_02")]
            return read(filed(tmp_path, linked(lines)), SETTINGS).carry.size

        assert size("claude-opus-4-5-of-a-loom") - size("claude-opus-4-5") == len(
            "-of-a-loom"
        )

    def test_it_holds_the_latest_prompt_the_launch_open_received_with_its_runs(
        self, tmp_path: Path
    ) -> None:
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01"),
                hooked(5, "tidy.sh", prevented=True),
                assistant(8, "msg_02"),
                hooked(9, "notes.sh", run="hooks-2"),
            ]
        )

        stands = read(filed(tmp_path, lines), SETTINGS).carry.stands

        assert stands.prompt == Prompted(
            moment(0),
            "typed",
            len("Warp the loom."),
            (Ran("tidy.sh", 10, False, True),),
        )

    def test_it_holds_no_prompt_where_the_launch_open_received_none(
        self, tmp_path: Path
    ) -> None:
        for resumed in ([], [chained("system", 28, subtype="turn_duration")]):
            lines = linked(
                [
                    typed(0),
                    assistant(4, "msg_01"),
                    cost(),
                    *resumed,
                    assistant(30, "msg_02"),
                ]
            )

            assert read(filed(tmp_path, lines), SETTINGS).carry.stands.prompt is None

    def test_the_latest_prompt_counts_in_its_size_with_its_runs(
        self, tmp_path: Path
    ) -> None:
        def size(*commands: str) -> int:
            summaries = [hooked(5, command) for command in commands]
            lines = linked(
                [typed(0), assistant(4, "msg_01"), *summaries, assistant(8, "msg_02")]
            )
            return read(filed(tmp_path, lines), SETTINGS).carry.size

        assert size("t.sh", "tidy.sh") > size("tidy.sh") > size()
        assert size("tidy.sh") - size() > len("tidy.sh")

    def test_a_line_awaited_counts_in_its_size_with_its_id(
        self, tmp_path: Path
    ) -> None:
        lines = linked([typed(0), assistant(4, "msg_01"), assistant(9, "msg_02")])

        sizes = [
            read(
                filed(tmp_path, [lines[0] | {"parentUuid": follows}, *lines[1:]]),
                SETTINGS,
            ).carry.size
            for follows in (None, "a-line", "a-line-of-another-file")
        ]

        assert sizes[2] - sizes[1] == len("-of-another-file")
        assert sizes[1] - sizes[0] > len("a-line")

    def test_it_holds_what_the_boundarys_call_carries_where_it_is_its_launchs_first(
        self, tmp_path: Path
    ) -> None:
        """What the lines before it record of its Context Parts, its
        requests with what their shape's line records they sent."""
        managed = "# Environment: cleo-loom-4b7d21"
        opening = [
            typed(0),
            instructions(0.1, loaded("Managed", managed)),
            snapshot(0.2, "You spin."),
            shaped(0.5, tools=(LOOM,)),
            request(1, shapeHash="shape-1"),
            sent(assistant(4, "msg_01"), "request-1"),
        ]

        first = read(filed(tmp_path, linked(opening)), SETTINGS).carry.stands
        later = read(
            filed(
                tmp_path,
                linked([*opening, request(6, "request-2", shapeHash="shape-1")])
                + [sent(assistant(9, "msg_02"), "request-2")],
            ),
            SETTINGS,
        ).carry.stands

        assert first.opening == Opening(
            Shape(len("You spin.")),
            ((MANAGED, len(managed)),),
            (len("Warp the loom."),),
        )
        assert first.requests == (
            Requested("request-1", moment(1), "shape-1", sends=Shape(10, SCHEMAS)),
        )
        assert later.opening is None
        assert later.requests == (Requested("request-2", moment(6), "shape-1"),)

    def test_a_sub_agents_thread_holds_what_its_first_call_carries(
        self, tmp_path: Path
    ) -> None:
        lines = linked([user(0, "Count the threads."), assistant(4, "msg_01")])

        stands = read(filed(tmp_path, lines, AGENT), SETTINGS).carry.stands

        assert stands.opening == Opening(prompts=(len("Count the threads."),))

    def test_what_the_boundarys_call_carries_counts_in_its_size_with_its_files(
        self, tmp_path: Path
    ) -> None:
        def size(path: str) -> int:
            lines = [
                typed(0),
                instructions(0.1, loaded("Project", "# Looms", path)),
                assistant(4, "msg_01"),
            ]
            return read(filed(tmp_path, linked(lines)), SETTINGS).carry.size

        assert size(f"{DIRECTORY}/looms/CLAUDE.md") - size(
            f"{DIRECTORY}/CLAUDE.md"
        ) == len("/looms")

    def test_it_holds_what_was_injected_before_the_boundarys_call(
        self, tmp_path: Path
    ) -> None:
        """What was injected before an earlier Call is that one's."""
        lines = [
            typed(0),
            attached(0.2, "date", "Today is a weaving day."),
            requesting(4, "toolu_01", "Skill", {"skill": "loom:weave"}),
            result(5, "toolu_01", "Launching skill: loom:weave"),
            expanded(5.1),
            attached(5.2, "total_tokens_reminder", "Plenty left."),
            assistant(9, "msg_02"),
        ]

        held = read(filed(tmp_path, linked(lines)), SETTINGS).carry.stands
        none = read(
            filed(tmp_path, linked([*lines, assistant(14, "msg_03")])), SETTINGS
        ).carry.stands

        assert held.injected == (
            Part("skill_body", len(support.BODY), "loom:weave"),
            Part("reminder", len("Plenty left."), "total_tokens_reminder"),
        )
        assert none.injected == ()

    def test_what_was_injected_counts_in_its_size_with_its_names(
        self, tmp_path: Path
    ) -> None:
        def size(*kinds: str) -> int:
            lines = [
                typed(0),
                assistant(4, "msg_01"),
                *(attached(5, kind, "Plenty left.") for kind in kinds),
                assistant(9, "msg_02"),
            ]
            return read(filed(tmp_path, linked(lines)), SETTINGS).carry.size

        assert size("date") - size() > len("date")
        assert size("total_tokens_reminder") - size("date") == len(
            "total_tokens_reminder"
        ) - len("date")


class TestAFileThatGrew:
    def test_it_is_published_appended_on_what_the_carry_was_built_on(
        self, tmp_path: Path
    ) -> None:
        before, grown = _grown(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01"), assistant(9, "msg_02")]),
            linked([assistant(14, "msg_03")], "grown"),
        )

        publication = grown.publication
        assert publication.appended is not None
        assert publication.appended.builds_on.model_dump() == {
            "file_size": before.publication.file_size,
            "file_modified_at": before.publication.file_modified_at,
            "collector": VERSION,
        }
        assert publication.file_size > before.publication.file_size
        assert _places(publication) == (2, 1, 2, 1)
        assert [call.message_id for call in publication.calls] == ["msg_02", "msg_03"]

    @pytest.mark.parametrize(
        ("scenario", "read_whole", "read_on"),
        [(SCENARIO, 3, 85), (_resumed(), 0, 11)],
        ids=["the scenario", "a resumed thread"],
    )
    def test_a_scenarios_file_grown_a_line_at_a_time_reads_as_its_whole(
        self, scenario: Scenario, read_whole: int, read_on: int, tmp_path: Path
    ) -> None:
        """At every step the appended publication, on what Pilot held, is
        the whole one of the file as it then stands, and the carry it leaves
        the whole reading's (F152.16). The steps read whole instead are
        those from a line that goes back in the chain, behind the boundary,
        until the next Call begins and the boundary has passed that line."""
        builder = Builder(scenario, UNTIL)
        builder.write(tmp_path)
        appended = whole_instead = 0
        for file in builder.files():
            if not file.path.endswith(".jsonl"):
                continue
            named = transcript(tmp_path / "projects", tmp_path / file.path)
            assert named is not None
            named.path.write_bytes(b"")
            held: Read | None = None
            last: str | None = None
            behind = False
            for line in file.content.splitlines(keepends=True):
                with named.path.open("ab") as grown:
                    grown.write(line)
                added = json.loads(line)
                follows, last = last, added.get("uuid", last)
                try:
                    whole = read(named, SETTINGS)
                except UnreadableError:
                    assert held is None
                    continue
                if held is not None:
                    try:
                        taken = read(named, SETTINGS, held.carry)
                    except NotContinuedError:
                        assert behind or added["parentUuid"] not in (None, follows)
                        behind = True
                        whole_instead += 1
                    else:
                        behind = False
                        was = _held(held.publication, taken.publication)
                        assert was == whole.publication
                        assert taken.carry == whole.carry
                        appended += 1
                held = whole
        assert (whole_instead, appended) == (read_whole, read_on)

    def test_a_file_with_lines_written_early_grown_a_line_at_a_time_reads_as_its_whole(
        self, tmp_path: Path
    ) -> None:
        """Lines written before the line they follow: a tool's result, a
        `system` line a Call's first line apart from its own, a compaction's
        summary and a response's second line. At every step the file is
        read whole instead, or its appended publication on what Pilot held
        is the whole one, with the whole reading's carry."""
        lines = linked(
            [
                typed(0),
                requesting(4, "toolu_01", message_id="msg_01"),
                result(6, "toolu_01"),
                assistant(9, "msg_02"),
                typed(10),
                assistant(11, "msg_03"),
                *_ticks(2),
                assistant(14, "msg_04"),
                typed(15),
                assistant(16, "msg_05"),
                boundary(30),
                summary(29.7),
                assistant(40, "msg_06", output=1),
                assistant(41, "msg_06", output=5),
                typed(50),
                assistant(54, "msg_07"),
                typed(60),
                assistant(64, "msg_08"),
            ]
        )
        written = [
            lines[at]
            for at in (0, 2, 1, 3, 4, 5, 7, 8, 6, 9, 10, 12, 11, 14, 13, 15, 16, 17, 18)
        ]
        named = filed(tmp_path, written[:1])
        held = read(named, SETTINGS)
        appended, stopped = 0, set()
        for line in written[1:]:
            _added(named, [line])
            whole = read(named, SETTINGS)
            try:
                taken = read(named, SETTINGS, held.carry)
            except NotContinuedError as stop:
                stopped.add(str(stop))
            else:
                assert _held(held.publication, taken.publication) == whole.publication
                assert taken.carry == whole.carry
                appended += 1
            held = whole

        assert [
            (call.predecessor, call.compaction) for call in whole.publication.calls
        ] == [
            (None, None),
            ("msg_01", None),
            ("msg_02", None),
            ("msg_03", None),
            ("msg_04", None),
            ("msg_05", 1),
            ("msg_06", None),
            ("msg_07", None),
        ]
        assert stopped == {
            "a line follows one before its boundary that is not the last there",
            "a line before its boundary follows one written from it on",
        }
        assert appended == 4

    def test_a_line_awaited_before_the_boundary_stays_in_the_carry(
        self, tmp_path: Path
    ) -> None:
        first = linked([typed(0), assistant(4, "msg_01"), assistant(9, "msg_02")])
        first[0]["parentUuid"] = "a-line-of-another-file"

        _, grown = _grown(
            tmp_path, first, _continuing("line-3", [typed(12), assistant(14, "msg_03")])
        )

        assert grown.publication.appended is not None
        assert grown.carry.stands.calls == 2
        assert grown.carry.stands.awaited == ("a-line-of-another-file",)

    def test_a_line_awaited_at_the_files_first_line_stays_in_the_carry_once(
        self, tmp_path: Path
    ) -> None:
        """A sub-agent's file whose first line is its first Call's, following
        a line of another file: the boundary is the file's start, and every
        reading from it on carries that line's id once, as the whole reading
        does."""
        lines = linked([assistant(4, "msg_01"), *_ticks(3)])
        lines[0]["parentUuid"] = "a-line-of-another-file"
        named = filed(tmp_path, lines[:1], AGENT)
        held = read(named, SETTINGS)
        for line in lines[1:]:
            _added(named, [line])
            whole = read(named, SETTINGS)

            taken = read(named, SETTINGS, held.carry)

            assert taken.carry.stands.byte == 0
            assert taken.carry.stands.awaited == ("a-line-of-another-file",)
            assert taken.carry == whole.carry
            held = taken

    def test_the_boundarys_call_takes_what_its_later_lines_say(
        self, tmp_path: Path
    ) -> None:
        """A Call's facts are settled once the next has begun, and not
        before."""
        _, grown = _grown(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01", output=2)]),
            linked([assistant(6, "msg_01", output=31)], "grown"),
        )

        (call,) = grown.publication.calls
        assert (call.tokens, call.completed_at) == ({"output": 31}, moment(6))
        assert grown.carry.stands.calls == 0

    def test_the_boundarys_call_takes_its_choices_from_its_lines_from_there_on(
        self, tmp_path: Path
    ) -> None:
        """Each lies on a line of the Call's own."""
        before, grown = _grown(
            tmp_path,
            linked(
                [
                    typed(0),
                    answering(4, "msg_01", fallback("claude-opus-4-1"))
                    | {"effort": "high", "attributionSkill": "loom:warping"},
                ]
            ),
            _continuing(
                "line-2",
                [finished(assistant(6, "msg_01", output=31), 12, "max_tokens")],
            ),
        )

        (call,) = grown.publication.calls
        assert (call.requested_model, call.effort, call.attributed_skill) == (
            "claude-opus-4-1",
            "high",
            "loom:warping",
        )
        assert (call.thinking_tokens, call.stop_reason) == (12, "max_tokens")
        assert (
            _held(before.publication, grown.publication)
            == read(filed_again(tmp_path), SETTINGS).publication
        )

    def test_a_fallbacks_line_from_the_boundary_on_names_the_boundarys_call(
        self, tmp_path: Path
    ) -> None:
        """Claude Code writes it after the lines of the Call it names."""
        _, grown = _grown(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01") | {"requestId": "req_01"}]),
            _continuing("line-2", [fell_back(4.2, "req_01", "claude-opus-4-1")]),
        )

        (call,) = grown.publication.calls
        assert call.requested_model == "claude-opus-4-1"

    def test_a_result_from_the_boundary_on_reaches_its_request(
        self, tmp_path: Path
    ) -> None:
        _, grown = _grown(
            tmp_path,
            linked([typed(0), requesting(4, "toolu_01")]),
            linked([result(7, "toolu_01", "twill")], "grown"),
        )

        (call,) = grown.publication.calls
        (asked,) = call.tool_calls
        assert (asked.returned_at, asked.result_characters) == (moment(7), 5)

    def test_the_boundarys_call_reaches_its_predecessor_behind_its_first_line(
        self, tmp_path: Path
    ) -> None:
        """Pilot takes a predecessor before the boundary by its name."""
        _, grown = _grown(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01"), assistant(9, "msg_02")]),
            _continuing("line-3", [assistant(14, "msg_03")]),
        )

        assert [
            (call.message_id, call.predecessor) for call in grown.publication.calls
        ] == [("msg_02", "msg_01"), ("msg_03", "msg_02")]

    def test_the_boundarys_call_names_a_compaction_it_crossed_before_its_first_line(
        self, tmp_path: Path
    ) -> None:
        """The compaction lies before the boundary, so the call carries
        none, places its next after it and names it by its place among the
        transcript's."""
        before, grown = _grown(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01"),
                    boundary(30),
                    summary(29.7),
                    assistant(40, "msg_02"),
                ]
            ),
            _continuing("line-5", [assistant(42, "msg_02")]),
        )

        publication = grown.publication
        assert _places(publication) == (2, 1, 2, 2)
        assert publication.compactions == []
        (call,) = publication.calls
        assert (call.predecessor, call.compaction) == ("msg_01", 1)
        assert (
            _held(before.publication, publication)
            == read(filed_again(tmp_path), SETTINGS).publication
        )

    def test_the_boundarys_call_was_sent_when_its_request_before_its_first_line_was(
        self, tmp_path: Path
    ) -> None:
        before, grown = _grown(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01"),
                    request(5, "request-2"),
                    sent(assistant(9, "msg_02"), "request-2"),
                ]
            ),
            _continuing(
                "line-3",
                [
                    typed(10),
                    request(11, "request-3"),
                    sent(assistant(14, "msg_03"), "request-3"),
                ],
            ),
        )

        assert [
            (call.message_id, call.sent_at) for call in grown.publication.calls
        ] == [("msg_02", moment(5)), ("msg_03", moment(11))]
        assert grown.carry.stands.requests == (Requested("request-3", moment(11)),)

    def test_a_later_call_was_sent_when_its_request_before_the_boundary_was(
        self, tmp_path: Path
    ) -> None:
        """Claude Code may write the next request before the lines of the
        response it follows, the boundary's Call's."""
        named = filed(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01"),
                    request(5, "request-2"),
                    request(9.5, "request-3"),
                    sent(assistant(9, "msg_02"), "request-2"),
                ]
            ),
        )
        before = read(named, SETTINGS)
        _added(
            named, _continuing("line-3", [sent(assistant(12, "msg_03"), "request-3")])
        )

        grown = read(named, SETTINGS, before.carry)

        assert [
            (call.message_id, call.sent_at) for call in grown.publication.calls
        ] == [("msg_02", moment(5)), ("msg_03", moment(9.5))]
        assert (
            _held(before.publication, grown.publication)
            == read(named, SETTINGS).publication
        )

    @pytest.mark.parametrize(
        ("changed", "cause"),
        [
            ({}, "unknown"),
            ({"model": "claude-haiku-4-5"}, "model"),
            ({"effort": "low"}, "model"),
            ({"sent": 400}, "ttl"),
            ({"version": "2.1.318"}, "version"),
            ({"shapeHash": "b2"}, "system"),
            ({"keep": 2}, "history"),
            ({"cache_read": 1_000}, None),
        ],
        ids=[
            "nothing",
            "the model",
            "the effort",
            "the wait",
            "the version",
            "the shape",
            "the history",
            "no miss",
        ],
    )
    def test_the_boundarys_call_misses_by_what_its_predecessor_behind_it_left(
        self, changed: dict[str, Any], cause: str | None, tmp_path: Path
    ) -> None:
        """Its own request's line lies behind the boundary too."""
        at = changed.get("sent", 6)
        boundarys = assistant(
            at + 3,
            "msg_02",
            changed.get("model", "claude-opus-4-5"),
            cache_write_5m=1_000 - changed.get("cache_read", 0),
            cache_read=changed.get("cache_read", 0),
        ) | {"effort": changed.get("effort", "high")}
        if "version" in changed:
            boundarys["version"] = changed["version"]
        before, grown = _grown(
            tmp_path,
            linked(
                [
                    typed(0),
                    request(
                        1, "request-1", shapeHash="a1", keep=0, tail=["a", "b", "c"]
                    ),
                    sent(
                        assistant(4, "msg_01", cache_write_5m=1_000)
                        | {"effort": "high"},
                        "request-1",
                    ),
                    request(
                        at,
                        "request-2",
                        shapeHash=changed.get("shapeHash", "a1"),
                        keep=changed.get("keep", 3),
                        tail=["d"],
                    ),
                    sent(boundarys, "request-2"),
                ]
            ),
            _continuing("line-3", [assistant(at + 9, "msg_03", cache_read=1_000)]),
        )

        whole = read(filed_again(tmp_path), SETTINGS)
        assert [call.miss_cause for call in grown.publication.calls] == [cause, None]
        assert _held(before.publication, grown.publication) == whole.publication
        assert grown.carry == whole.carry

    def test_the_boundarys_call_is_a_rewind_to_the_call_its_line_leads_to(
        self, tmp_path: Path
    ) -> None:
        first = linked(
            [
                typed(0),
                assistant(4, "msg_01", cache_write_5m=1_000),
                typed(6),
                assistant(8, "msg_02", cache_read=1_000),
                typed(10),
                assistant(12, "msg_03", cache_write_5m=1_000),
            ]
        )
        first[4]["parentUuid"] = "line-2"
        before, grown = _grown(
            tmp_path,
            first,
            _continuing("line-6", [assistant(16, "msg_04", cache_read=1_000)]),
        )

        assert [call.miss_cause for call in grown.publication.calls] == ["rewind", None]
        assert (
            _held(before.publication, grown.publication)
            == read(filed_again(tmp_path), SETTINGS).publication
        )

    def test_an_event_before_the_first_call_is_its_from_the_boundary_on(
        self, tmp_path: Path
    ) -> None:
        before, grown = _grown(
            tmp_path,
            [typed(0), retried(1), assistant(4, "msg_01")],
            [assistant(9, "msg_02")],
        )

        first, _ = grown.publication.calls
        assert [(event.kind, event.at) for event in first.events] == [
            ("api_retry", moment(1))
        ]
        whole = read(filed_again(tmp_path), SETTINGS)
        assert _held(before.publication, grown.publication) == whole.publication
        assert grown.carry == whole.carry

    def test_an_event_from_the_boundary_on_is_the_call_before_its(
        self, tmp_path: Path
    ) -> None:
        before, grown = _grown(
            tmp_path,
            [typed(0), assistant(2, "msg_01"), retried(3), assistant(4, "msg_02")],
            [interruption(5), erred(6), assistant(9, "msg_03")],
        )

        assert [
            [event.kind for event in call.events] for call in grown.publication.calls
        ] == [["interrupt", "api_error"], []]
        assert (
            _held(before.publication, grown.publication)
            == read(filed_again(tmp_path), SETTINGS).publication
        )

    def test_a_compaction_from_the_boundary_on_is_placed_after_those_before_it(
        self, tmp_path: Path
    ) -> None:
        before, grown = _grown(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01"),
                    boundary(30, postTokens=9_000),
                    summary(29.7),
                    assistant(40, "msg_02"),
                ]
            ),
            _continuing(
                "line-5",
                [boundary(70, "manual"), summary(69.7), assistant(80, "msg_03")],
            ),
        )

        publication = grown.publication
        assert _places(publication) == (2, 1, 2, 2)
        assert [(made.at, made.trigger) for made in publication.compactions] == [
            (moment(70), "manual")
        ]
        assert [
            (call.message_id, call.predecessor, call.compaction)
            for call in publication.calls
        ] == [("msg_02", "msg_01", 1), ("msg_03", "msg_02", 2)]
        assert grown.carry.stands.compactions == 2
        assert (grown.carry.stands.leads.call, grown.carry.stands.leads.compaction) == (
            "msg_02",
            2,
        )
        assert (
            _held(before.publication, publication)
            == read(filed_again(tmp_path), SETTINGS).publication
        )

    def test_a_stop_hooks_summary_from_the_boundary_on_publishes_its_prompt_again(
        self, tmp_path: Path
    ) -> None:
        """With the runs of the summaries before the boundary, and at its
        place among the Transcript's."""
        first = linked(
            [
                typed(0),
                assistant(4, "msg_01"),
                hooked(5, "tidy.sh", prevented=True),
                assistant(8, "msg_02"),
            ]
        )
        before, grown = _grown(
            tmp_path,
            first,
            _continuing("line-4", [hooked(9, "notes.sh", run="hooks-2")]),
        )

        publication = grown.publication
        assert _places(publication) == (2, 1, 1, 1)
        (launch,) = publication.launches
        assert [
            (prompt.received_at, [run.command for run in prompt.hook_runs])
            for prompt in launch.prompts
        ] == [(moment(0), ["tidy.sh", "notes.sh"])]
        whole = read(filed_again(tmp_path), SETTINGS)
        assert _held(before.publication, publication) == whole.publication
        assert grown.carry == whole.carry

    def test_a_summary_from_the_boundary_on_of_a_prompt_taken_there_is_its(
        self, tmp_path: Path
    ) -> None:
        """The Prompt the carry holds is not published again."""
        _, grown = _grown(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01")]),
            _continuing(
                "line-2",
                [
                    typed(10, "Beat the weft."),
                    assistant(14, "msg_02"),
                    hooked(15, "notes.sh"),
                ],
            ),
        )

        publication = grown.publication
        assert _places(publication) == (1, 1, 2, 1)
        (launch,) = publication.launches
        assert [
            [run.command for run in prompt.hook_runs] for prompt in launch.prompts
        ] == [["notes.sh"]]

    def test_the_launch_open_at_the_boundary_comes_with_its_prompts_from_there_on(
        self, tmp_path: Path
    ) -> None:
        before, grown = _grown(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01")]),
            linked([typed(10, "Beat the weft."), assistant(14, "msg_02")], "grown"),
        )

        publication = grown.publication
        assert _places(publication) == (1, 1, 2, 1)
        (launch,) = publication.launches
        assert launch.started_at == before.publication.launches[0].started_at
        assert [prompt.received_at for prompt in launch.prompts] == [moment(10)]
        assert [call.prompt for call in publication.calls] == [1, 2]
        assert grown.carry.stands.launch == Open(
            moment(0), support.VERSION, 2, moment(10)
        )

    def test_a_resumed_process_is_a_launch_at_the_next_place(
        self, tmp_path: Path
    ) -> None:
        _, grown = _grown(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01")]),
            linked(
                [
                    cost(),
                    typed(60) | {"version": "2.1.318"},
                    assistant(64, "msg_02") | {"version": "2.1.318"},
                    cost(),
                    assistant(90, "msg_03"),
                ],
                "grown",
            ),
        )

        publication = grown.publication
        assert _places(publication) == (1, 1, 2, 1)
        assert [
            (launch.started_at, launch.components[0].version, len(launch.prompts))
            for launch in publication.launches
        ] == [
            (moment(0), support.VERSION, 0),
            (moment(60), "2.1.318", 1),
            (moment(90), support.VERSION, 0),
        ]
        assert _places(_again(tmp_path, grown)) == (3, 3, 3, 1)

    def test_the_launch_open_at_the_boundary_ends_at_its_last_line_from_there_on(
        self, tmp_path: Path
    ) -> None:
        before, grown = _grown(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01"), assistant(9, "msg_02")]),
            _continuing("line-3", [typed(12), queue("enqueue", 20, "Beat the weft.")]),
        )

        (launch,) = grown.publication.launches
        assert (launch.started_at, launch.ended_at) == (moment(0), moment(20))
        assert before.publication.launches[0].ended_at == moment(9)

    def test_the_launch_open_at_the_boundary_names_the_plugins_named_before_it(
        self, tmp_path: Path
    ) -> None:
        before, grown = _grown(
            tmp_path,
            linked(
                [
                    typed(0),
                    expanded(1, None, support.plugin_body("dev", "0.10.92")),
                    assistant(4, "msg_01"),
                    assistant(9, "msg_02"),
                ]
            ),
            _continuing(
                "line-3",
                [
                    expanded(10, None, support.plugin_body("kubecoder", "0.15.4")),
                    expanded(11, None, support.plugin_body("dev", "0.10.93")),
                    assistant(14, "msg_03"),
                ],
            ),
        )

        whole = read(filed_again(tmp_path), SETTINGS)
        (launch,) = grown.publication.launches
        assert [(used.component, used.version) for used in launch.components] == [
            ("claude-code", support.VERSION),
            ("plugin:dev", "0.10.92"),
            ("plugin:kubecoder", "0.15.4"),
        ]
        assert _held(before.publication, grown.publication) == whole.publication
        assert grown.carry == whole.carry

    def test_a_line_from_the_boundary_on_naming_another_version_starts_a_launch(
        self, tmp_path: Path
    ) -> None:
        """From the queue's lines since the last line that named the earlier
        version, which lie before the boundary."""
        later = {"version": "2.1.318"}
        before, grown = _grown(
            tmp_path,
            [
                typed(0),
                assistant(4, "msg_01"),
                queue("enqueue", 60, "Thread the heddles."),
                assistant(64, "msg_02") | later,
            ],
            [user(64.5, "Thread the heddles.", promptSource="queued") | later],
        )

        whole = read(filed_again(tmp_path), SETTINGS)
        assert _places(grown.publication) == (2, 1, 2, 1)
        assert [
            (launch.started_at, launch.ended_at, len(launch.prompts))
            for launch in grown.publication.launches
        ] == [(moment(0), moment(4), 0), (moment(60), moment(64.5), 1)]
        assert grown.publication.launches[1].prompts[0].received_at == moment(60)
        assert _held(before.publication, grown.publication) == whole.publication
        assert grown.carry == whole.carry

    def test_a_launch_names_its_version_once_a_line_from_the_boundary_on_does(
        self, tmp_path: Path
    ) -> None:
        versionless = assistant(4, "msg_01")
        del versionless["version"]
        before, grown = _grown(
            tmp_path,
            linked([queue("enqueue", 0), versionless]),
            linked([typed(8)], "grown"),
        )

        assert before.publication.launches == []
        assert _places(grown.publication) == (1, 1, 1, 1)
        (launch,) = grown.publication.launches
        assert (launch.started_at, len(launch.prompts)) == (moment(0), 1)

    def test_a_prompt_was_received_when_it_was_queued_before_the_boundary(
        self, tmp_path: Path
    ) -> None:
        _, grown = _grown(
            tmp_path,
            linked(
                [
                    typed(0),
                    queue("enqueue", 2, "Beat the weft."),
                    assistant(4, "msg_01"),
                    assistant(9, "msg_02"),
                ]
            ),
            linked([user(15, "Beat the weft.", promptSource="queued")], "grown"),
        )

        (launch,) = grown.publication.launches
        assert [prompt.received_at for prompt in launch.prompts] == [moment(2)]

    def test_a_message_taken_mid_run_was_received_when_queued_before_the_boundary(
        self, tmp_path: Path
    ) -> None:
        _, grown = _grown(
            tmp_path,
            linked(
                [
                    typed(0),
                    queue("enqueue", 2, "Beat the weft."),
                    queue("enqueue", 3, "Tie on."),
                    queue("remove", 3.5, "Tie on."),
                    assistant(4, "msg_01"),
                    assistant(9, "msg_02"),
                ]
            ),
            linked(
                [
                    taken(15, "Tie on."),
                    taken(16, "Beat the weft.", "task-notification"),
                ],
                "grown",
            ),
        )

        (launch,) = grown.publication.launches
        assert [(prompt.received_at, prompt.source) for prompt in launch.prompts] == [
            (moment(3), "queued"),
            (moment(2), "system"),
        ]

    def test_the_place_stays_the_files_first(self, tmp_path: Path) -> None:
        hosted = instructions(1, loaded("Managed", "# Environment: cleo-loom-7a41d9\n"))
        moved = instructions(11, loaded("Managed", "# Environment: cleo-reed-0c2b55\n"))
        before, grown = _grown(
            tmp_path,
            linked([typed(0), hosted, assistant(4, "msg_01")]),
            linked([moved, typed(12) | {"cwd": "/work/Reed"}], "grown"),
        )

        for publication in (before.publication, grown.publication):
            assert publication.working_directory == DIRECTORY
            assert publication.repository == "Loom"
            assert publication.environment == "cleo-loom-7a41d9"

    def test_an_environment_first_named_from_the_boundary_on_is_the_transcripts(
        self, tmp_path: Path
    ) -> None:
        hosted = instructions(11, loaded("Managed", "# Environment: cleo-loom-7a41d9"))
        before, grown = _grown(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01")]),
            linked([hosted], "grown"),
        )

        assert before.publication.environment is None
        assert grown.publication.environment == "cleo-loom-7a41d9"
        assert grown.carry.stands.environment is None
        assert MANAGED == hosted["attachment"]["files"][0]["path"]

    @pytest.mark.parametrize(
        "agent", [None, AGENT], ids=["a launch's", "a sub-agent's"]
    )
    def test_the_boundarys_call_carries_what_the_lines_before_it_record(
        self, agent: str | None, tmp_path: Path
    ) -> None:
        """Its first Call is the boundary's."""
        opened = [
            typed(0) if agent is None else user(0, "Count the threads."),
            instructions(0.1, loaded("Project", "# Looms", f"{DIRECTORY}/CLAUDE.md")),
            shaped(0.5, tools=(LOOM,)),
            request(1, shapeHash="shape-1"),
            sent(assistant(4, "msg_01", output=1), "request-1"),
        ]
        before, grown = _grown(
            tmp_path,
            linked(opened),
            _continuing(
                "line-3",
                [sent(assistant(5, "msg_01", output=9), "request-1"), typed(8)]
                + [assistant(12, "msg_02")],
            ),
            agent,
        )

        whole = read(filed_again(tmp_path, agent), SETTINGS)
        first, later = grown.publication.calls
        assert [part.kind for part in first.context_parts] == [
            "system_prompt",
            "tool_schemas",
            "instruction_file",
            "prompt",
        ]
        assert later.context_parts == []
        assert _held(before.publication, grown.publication) == whole.publication
        assert grown.carry == whole.carry

    def test_a_resumed_launchs_own_shape_from_the_boundary_on_is_read(
        self, tmp_path: Path
    ) -> None:
        _, grown = _grown(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01")]),
            linked(
                [
                    cost(),
                    typed(60),
                    shaped(60.5, "shape-2", tools=(LOOM,)),
                    request(61, shapeHash="shape-2"),
                    sent(assistant(64, "msg_02"), "request-1"),
                ],
                "grown",
            ),
        )

        assert [
            [part.kind for part in call.context_parts]
            for call in grown.publication.calls
        ] == [["prompt"], ["system_prompt", "tool_schemas", "prompt"]]

    @pytest.mark.parametrize(
        "agent", [None, AGENT], ids=["a launch's", "a sub-agent's"]
    )
    def test_the_boundarys_call_carries_what_was_injected_before_its_first_line(
        self, agent: str | None, tmp_path: Path
    ) -> None:
        before, grown = _grown(
            tmp_path,
            linked(
                [
                    typed(0) if agent is None else user(0, "Count the threads."),
                    requesting(4, "toolu_01", "Skill", {"skill": "loom:weave"}),
                    result(5, "toolu_01", "Launching skill: loom:weave"),
                    expanded(5.1),
                    attached(5.2, "date", "Today is a weaving day."),
                    assistant(9, "msg_02", output=1),
                ]
            ),
            _continuing(
                "line-5",
                [
                    assistant(10, "msg_02", output=4),
                    attached(11, "total_tokens_reminder", "Plenty left."),
                    assistant(14, "msg_03"),
                ],
            ),
            agent,
        )

        whole = read(filed_again(tmp_path, agent), SETTINGS)
        assert [
            [(part.kind, part.name) for part in call.context_parts]
            for call in grown.publication.calls
        ] == [
            [("skill_body", "loom:weave"), ("reminder", "date")],
            [("reminder", "total_tokens_reminder")],
        ]
        assert _held(before.publication, grown.publication) == whole.publication
        assert grown.carry == whole.carry

    def test_a_skills_body_from_the_boundary_on_names_the_boundarys_call(
        self, tmp_path: Path
    ) -> None:
        before, grown = _grown(
            tmp_path,
            linked(
                [typed(0), assistant(4, "msg_01")]
                + [
                    requesting(
                        8, "toolu_01", "Skill", {"skill": "loom:weave"}, "msg_02"
                    )
                ]
            ),
            _continuing(
                "line-3",
                [
                    result(9, "toolu_01", "Launching skill: loom:weave"),
                    expanded(9.1),
                    assistant(14, "msg_03"),
                ],
            ),
        )

        whole = read(filed_again(tmp_path), SETTINGS)
        assert [part.name for part in grown.publication.calls[-1].context_parts] == [
            "loom:weave"
        ]
        assert _held(before.publication, grown.publication) == whole.publication

    def test_a_sub_agents_appended_publication_names_its_record(
        self, tmp_path: Path
    ) -> None:
        recorded(
            tmp_path,
            agentType="Explore",
            description="Count the heddles",
            toolUseId="toolu_09",
        )
        _, grown = _grown(
            tmp_path,
            linked([user(0), assistant(4, "msg_01"), assistant(9, "msg_02")]),
            linked([assistant(14, "msg_03")], "grown"),
            agent=AGENT,
        )

        assert grown.publication.appended is not None
        assert (
            grown.publication.agent_type,
            grown.publication.description,
            grown.publication.spawned_by,
        ) == ("Explore", "Count the heddles", "toolu_09")

    def test_a_forks_file_grown_a_line_at_a_time_reads_as_its_whole(
        self, tmp_path: Path
    ) -> None:
        """Its copies, the one from the boundary on among them, stay no
        facts of its, as the whole reading has it; read whole instead at the
        line that holds its call, which the carry before it was read
        without."""
        lines = _forked()
        lines += _continuing(
            lines[-1]["uuid"],
            [
                assistant(18, "msg_04", output=2),
                retried(9),
                assistant(21, "msg_04", output=5),
                assistant(25, "msg_05", output=1),
            ],
        )
        named = filed(tmp_path, b"", AGENT)
        recorded(tmp_path, **FORKED)
        held: Read | None = None
        whole_instead: list[str] = []
        for line in lines:
            _added(named, [line])
            whole = read(named, SETTINGS)
            if held is not None:
                try:
                    taken = read(named, SETTINGS, held.carry)
                except NotContinuedError as error:
                    whole_instead.append(line["uuid"])
                    assert "holds the call that started it" in str(error)
                else:
                    was = _held(held.publication, taken.publication)
                    assert was == whole.publication
                    assert taken.carry == whole.carry
            held = whole

        assert held is not None
        assert [call.message_id for call in held.publication.calls] == [
            "msg_03",
            "msg_04",
            "msg_05",
        ]
        assert whole_instead == ["copy-7"]

    def test_a_sub_agents_thread_names_no_launch_and_no_prompt_before(
        self, tmp_path: Path
    ) -> None:
        _, grown = _grown(
            tmp_path,
            linked([user(0), assistant(4, "msg_01"), assistant(9, "msg_02")]),
            linked([assistant(14, "msg_03")], "grown"),
            agent=AGENT,
        )

        assert _places(grown.publication) == (2, 1, 1, 1)
        assert grown.publication.launches == []

    def test_a_file_with_no_call_is_read_from_its_start(self, tmp_path: Path) -> None:
        before, grown = _grown(
            tmp_path, linked([typed(0)]), linked([assistant(4, "msg_01")], "grown")
        )

        assert _places(grown.publication) == (1, 1, 1, 1)
        assert _held(
            before.publication, grown.publication
        ) == grown.publication.model_copy(update={"appended": None})
        assert len(grown.publication.launches[0].prompts) == 1

    def test_a_line_still_being_written_is_read_once_it_is_whole(
        self, tmp_path: Path
    ) -> None:
        lines = linked([typed(0), assistant(4, "msg_01"), assistant(9, "msg_02")])
        whole = support.content(lines)
        named = filed(tmp_path, whole[:-30])
        before = read(named, SETTINGS)
        with named.path.open("ab") as file:
            file.write(whole[-30:])

        grown = read(named, SETTINGS, before.carry)

        assert [call.message_id for call in before.publication.calls] == ["msg_01"]
        assert _places(grown.publication) == (1, 1, 2, 1)
        assert [call.message_id for call in grown.publication.calls] == [
            "msg_01",
            "msg_02",
        ]


def _at(call: str) -> Checkpoint:
    """A labeller's checkpoint whose boundary is the Call of that id."""
    return Checkpoint(
        version="1.0.0",
        stamp="1:stamp",
        call=call,
        byte=0,
        text="1:1.0.0:checkpoint",
        position=1,
        shift=0,
    )


class TestFromTheLabellersBoundary:
    """A carry that stands before the first line of an earlier Call than the
    file's last, the labeller's boundary (F152.15)."""

    def test_it_stands_before_that_calls_first_line_and_holds_the_checkpoint(
        self, tmp_path: Path
    ) -> None:
        taken = read(
            filed(
                tmp_path,
                linked(
                    [
                        typed(0),
                        assistant(4, "msg_01"),
                        assistant(9, "msg_02"),
                        assistant(14, "msg_03"),
                    ]
                ),
            ),
            SETTINGS,
        )
        checkpoint = _at("msg_02")

        carry = taken.carried(checkpoint)

        assert list(taken.stood) == ["msg_01", "msg_02", "msg_03"]
        assert taken.stood["msg_03"] == taken.carry.stands
        assert carry.stands == taken.stood["msg_02"]
        assert carry.stands.calls == 1
        assert carry.checkpoint == checkpoint
        assert carry.end == digest(taken.content[carry.stands.byte :])
        assert (carry.file_size, carry.file_modified_at, carry.collector) == (
            taken.carry.file_size,
            taken.carry.file_modified_at,
            taken.carry.collector,
        )

    def test_with_no_checkpoint_or_one_of_a_call_it_took_none_of_it_is_its_own(
        self, tmp_path: Path
    ) -> None:
        taken = read(
            filed(tmp_path, linked([typed(0), assistant(4, "msg_01")])), SETTINGS
        )

        assert taken.carried(None) == taken.carry
        assert taken.carried(_at("msg_synthetic")) == taken.carry
        assert taken.carry.checkpoint is None

    def test_a_reading_from_it_hands_the_labeller_its_checkpoint(
        self, tmp_path: Path
    ) -> None:
        named = filed(
            tmp_path, linked([typed(0), assistant(4, "msg_01"), assistant(9, "msg_02")])
        )
        checkpoint = _at("msg_01")
        carry = read(named, SETTINGS).carried(checkpoint)
        _added(named, _continuing("line-2", [assistant(14, "msg_03")]))

        grown = read(named, SETTINGS, carry)

        assert grown.checkpoint == checkpoint
        assert grown.calls == ("msg_01", "msg_02", "msg_03")
        assert _places(grown.publication) == (1, 1, 2, 1)
        assert read(named, SETTINGS).checkpoint is None

    def test_other_bytes_between_it_and_the_last_call_no_longer_continue_it(
        self, tmp_path: Path
    ) -> None:
        """Bytes before the file's last Call that a carry at that Call
        never reads again."""
        named = filed(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01", output=6),
                    assistant(9, "msg_02"),
                ]
            ),
        )
        taken = read(named, SETTINGS)
        held = named.path.read_bytes()
        named.path.write_bytes(
            held.replace(b'"output_tokens": 6', b'"output_tokens": 7')
        )
        assert named.path.read_bytes() != held
        _added(named, _continuing("line-2", [assistant(14, "msg_03")]))

        with pytest.raises(
            NotContinuedError, match="its file has other bytes before its old end"
        ):
            read(named, SETTINGS, taken.carried(_at("msg_01")))
        assert read(named, SETTINGS, taken.carry).publication.appended is not None

    @pytest.mark.parametrize(
        ("scenario", "read_whole", "read_on"),
        [(SCENARIO, 10, 196), (_resumed(), 0, 22)],
        ids=["the scenario", "a resumed thread"],
    )
    def test_read_on_from_any_call_a_reading_took_a_file_reads_as_its_whole(
        self, scenario: Scenario, read_whole: int, read_on: int, tmp_path: Path
    ) -> None:
        """At every step, from the carry at each Call the reading before
        took, the appended publication on what Pilot held is the whole one
        of the file as it then stands, and the carry it leaves, and where it
        stood at each Call it took, the whole reading's; or, where a line it
        reads goes back behind that Call, it is read whole instead."""
        builder = Builder(scenario, UNTIL)
        builder.write(tmp_path)
        appended = whole_instead = 0
        for file in builder.files():
            if not file.path.endswith(".jsonl"):
                continue
            named = transcript(tmp_path / "projects", tmp_path / file.path)
            assert named is not None
            named.path.write_bytes(b"")
            held: Read | None = None
            for line in file.content.splitlines(keepends=True):
                with named.path.open("ab") as grown:
                    grown.write(line)
                try:
                    whole = read(named, SETTINGS)
                except UnreadableError:
                    assert held is None
                    continue
                for call in () if held is None else held.stood:
                    assert held is not None
                    try:
                        taken = read(named, SETTINGS, held.carried(_at(call)))
                    except NotContinuedError:
                        whole_instead += 1
                    else:
                        assert _held(held.publication, taken.publication) == (
                            whole.publication
                        )
                        assert taken.carry == whole.carry
                        assert taken.stood == {
                            each: whole.stood[each] for each in taken.stood
                        }
                        appended += 1
                held = whole
        assert (whole_instead, appended) == (read_whole, read_on)


def _logged(at: float, place: int, said: str) -> list[Line]:
    """A Call whose Bash call runs a `git log` in the file's checkout, which
    says `said`."""
    return [
        requesting(
            at,
            f"toolu_0{place}",
            given={"command": "git log --oneline -1"},
            message_id=f"msg_0{place}",
        ),
        result(at + 1, f"toolu_0{place}", said, error=False),
    ]


class TestACommitsHashALaterCallShows:
    """A commit whose hash only a later call shows (P-349): the carry holds
    the commits made before its boundary that showed none."""

    def test_the_carry_holds_each_one_made_before_the_boundary(
        self, tmp_path: Path
    ) -> None:
        taken = read(
            filed(tmp_path, _committing((WEAVE, ""), ("ls looms", "warp"))), SETTINGS
        )

        assert taken.carry.stands.unhashed == (
            Unhashed("toolu_01", "Loom", "Weave the warp"),
        )
        assert taken.stood["msg_01"].unhashed == ()

    def test_a_git_log_from_the_boundary_on_that_shows_one_reads_the_file_whole(
        self, tmp_path: Path
    ) -> None:
        """The appended publication holds no Call before the boundary to
        give the hash to."""
        named = filed(tmp_path, _committing((WEAVE, ""), ("ls looms", "warp")))
        before = read(named, SETTINGS)
        _added(named, _logged(8, 3, "1a2b3c4 Weave the warp"))

        with pytest.raises(
            NotContinuedError,
            match="a call shows the hash of a commit made before its boundary",
        ):
            read(named, SETTINGS, before.carry)
        assert _made(read(named, SETTINGS).publication)[0] == [
            ("Loom", "Weave the warp", "1a2b3c4")
        ]

    def test_one_made_from_the_boundary_on_takes_the_hash_a_later_call_shows(
        self, tmp_path: Path
    ) -> None:
        named = filed(tmp_path, _committing(("ls looms", "warp"), (WEAVE, "")))
        before = read(named, SETTINGS)
        _added(named, _logged(8, 3, "1a2b3c4 Weave the warp"))

        grown = read(named, SETTINGS, before.carry)

        assert _made(grown.publication) == [
            [("Loom", "Weave the warp", "1a2b3c4")],
            [],
        ]
        assert grown.carry.stands.unhashed == ()

    def test_one_a_later_call_the_reading_took_showed_is_held_nowhere_before_it(
        self, tmp_path: Path
    ) -> None:
        """Pilot holds the hash the reading gave it: one read on from a Call
        between the two, the labeller's boundary, goes on past the log."""
        named = filed(
            tmp_path,
            _committing(
                (WEAVE, ""),
                ("ls looms", "warp"),
                ("git log --oneline -1", "1a2b3c4 Weave the warp"),
            ),
        )
        taken = read(named, SETTINGS)
        _added(named, [assistant(10, "msg_04")])

        grown = read(named, SETTINGS, taken.carried(_at("msg_02")))

        assert taken.stood["msg_02"].unhashed == ()
        assert _made(grown.publication) == [[], []]


def filed_again(projects: Path, agent: str | None = None) -> Transcript:
    """The main thread's file as it stands or, with `agent`, a sub-agent's."""
    path = projects / support.FOLDER / f"{support.SESSION}.jsonl"
    if agent is not None:
        path = (
            projects
            / support.FOLDER
            / support.SESSION
            / "subagents"
            / f"agent-{agent}.jsonl"
        )
    return Transcript(projects, path, support.SESSION, agent)


def _again(projects: Path, read_before: Read) -> PublicationSchema:
    """The file grown by one more line of its last response, read from
    where `read_before` stood."""
    named = Transcript(
        projects,
        projects / support.FOLDER / f"{support.SESSION}.jsonl",
        support.SESSION,
    )
    last = read_before.publication.calls[-1].message_id
    _added(named, [assistant(120, last) | {"parentUuid": None}])
    return read(named, SETTINGS, read_before.carry).publication


class TestAFileThatDoesNotContinueItsCarry:
    @pytest.fixture
    def named(self, tmp_path: Path) -> Transcript:
        return filed(
            tmp_path,
            linked(
                [
                    typed(0),
                    requesting(4, "toolu_01", message_id="msg_01"),
                    result(6, "toolu_01"),
                    assistant(9, "msg_02"),
                ]
            ),
        )

    @pytest.fixture
    def carry(self, named: Transcript) -> Carry:
        return read(named, SETTINGS).carry

    def test_a_file_at_the_same_size_is_not_read_from_the_boundary(
        self, named: Transcript, carry: Carry
    ) -> None:
        later = named.path.stat().st_mtime_ns + 5 * 10**9
        os.utime(named.path, ns=(later, later))

        with pytest.raises(NotContinuedError, match="no larger than the one last read"):
            read(named, SETTINGS, carry)

    def test_a_smaller_file_is_not(self, named: Transcript, carry: Carry) -> None:
        named.path.write_bytes(named.path.read_bytes()[: carry.stands.byte + 10])

        with pytest.raises(NotContinuedError, match="no larger than the one last read"):
            read(named, SETTINGS, carry)

    def test_a_file_with_other_bytes_before_its_old_end_is_not(
        self, named: Transcript, carry: Carry
    ) -> None:
        held = named.path.read_bytes()
        rewritten = held.replace(b"The warp is on.", b"The weft is in.")
        assert len(rewritten) == len(held)
        assert rewritten[: carry.stands.byte] == held[: carry.stands.byte]
        assert rewritten[carry.stands.byte :] != held[carry.stands.byte :]
        named.path.write_bytes(rewritten)
        _added(named, [assistant(14, "msg_03")])

        with pytest.raises(NotContinuedError, match="other bytes before its old end"):
            read(named, SETTINGS, carry)

    def test_a_line_that_follows_one_behind_the_boundary_is_not_read_on(
        self, named: Transcript, carry: Carry
    ) -> None:
        assert carry.stands.link == "line-3"
        _added(named, [typed(14) | {"uuid": "grown-1", "parentUuid": "line-2"}])

        with pytest.raises(NotContinuedError, match="follows one before its boundary"):
            read(named, SETTINGS, carry)

    def test_a_line_that_a_line_behind_the_boundary_follows_is_not_read_on(
        self, tmp_path: Path
    ) -> None:
        """A compaction's summary written before its boundary, with two
        Calls begun between them: the chain of the first, behind the
        carry's boundary, crosses the compaction once its line is there."""
        prompt, answer, made, left, *rest = linked(
            [
                typed(0),
                assistant(4, "msg_01"),
                boundary(30),
                summary(29.7),
                assistant(40, "msg_02"),
                typed(50),
                assistant(54, "msg_03"),
            ]
        )
        named = filed(tmp_path, [prompt, answer, left, *rest])
        before = read(named, SETTINGS)
        assert before.carry.stands.awaited == ("line-3",)
        assert before.publication.calls[1].compaction is None
        _added(named, [made | {"logicalParentUuid": None}])

        with pytest.raises(
            NotContinuedError,
            match="a line before its boundary follows one written from it on",
        ):
            read(named, SETTINGS, before.carry)

        assert read(named, SETTINGS).publication.calls[1].compaction == 1

    def test_a_result_for_a_request_behind_the_boundary_is_not_read_on(
        self, named: Transcript, carry: Carry
    ) -> None:
        _added(
            named,
            [result(14, "toolu_01") | {"uuid": "grown-1", "parentUuid": "line-4"}],
        )

        with pytest.raises(
            NotContinuedError, match="names a request no line from its boundary on"
        ):
            read(named, SETTINGS, carry)

    @pytest.mark.parametrize(
        "body",
        [
            expanded(10),
            user(10, [support.words("# Weave\n\nWeave tight.")])
            | {"isMeta": True, "sourceToolUseID": "toolu_01"},
        ],
        ids=["opening as a skill's", "opening otherwise"],
    )
    def test_a_skills_body_that_names_a_call_behind_the_boundary_is_not_read_on(
        self, body: Line, tmp_path: Path
    ) -> None:
        named = filed(
            tmp_path,
            linked(
                [
                    typed(0),
                    requesting(4, "toolu_01", "Skill", {"skill": "loom:weave"}),
                    result(5, "toolu_01", "Launching skill: loom:weave"),
                    assistant(9, "msg_02"),
                ]
            ),
        )
        carry = read(named, SETTINGS).carry
        _added(named, [body | {"uuid": "grown-1", "parentUuid": "line-4"}])

        with pytest.raises(
            NotContinuedError,
            match="a skill's body names a request no line from its boundary on",
        ):
            read(named, SETTINGS, carry)
        assert read(named, SETTINGS).publication.calls[-1].context_parts == []

    def test_a_launchs_first_request_naming_a_shape_behind_the_boundary_is_not_read_on(
        self, tmp_path: Path
    ) -> None:
        """A resumed process names the shapes an earlier one's lines
        record."""
        named = filed(
            tmp_path,
            linked(
                [
                    typed(0),
                    shaped(0.5),
                    request(1, shapeHash="shape-1"),
                    sent(assistant(4, "msg_01"), "request-1"),
                    typed(6),
                    assistant(9, "msg_02"),
                ]
            ),
        )
        carry = read(named, SETTINGS).carry
        _added(
            named,
            [cost(), request(61, "request-2", shapeHash="shape-1")],
        )

        with pytest.raises(
            NotContinuedError,
            match="a launch's first request names a shape no line from its boundary on",
        ):
            read(named, SETTINGS, carry)

    def test_a_fallbacks_line_that_names_a_call_behind_the_boundary_is_not_read_on(
        self, tmp_path: Path
    ) -> None:
        """One written once the next Call began names a Call the carry
        holds nothing of."""
        named = filed(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01") | {"requestId": "req_01"},
                    assistant(9, "msg_02") | {"requestId": "req_02"},
                ]
            ),
        )
        carry = read(named, SETTINGS).carry
        _added(
            named, _continuing("line-3", [fell_back(9.2, "req_01", "claude-opus-4-1")])
        )

        with pytest.raises(
            NotContinuedError,
            match="a fallback names a request no Call from its boundary on answered",
        ):
            read(named, SETTINGS, carry)

        assert [
            call.requested_model for call in read(named, SETTINGS).publication.calls
        ] == [
            "claude-opus-4-1",
            None,
        ]

    def test_a_summary_on_a_prompt_before_the_boundarys_launch_is_not_read_on(
        self, tmp_path: Path
    ) -> None:
        """Read whole, it lies on the Launch before's last Prompt."""
        named = filed(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01"), cost(), assistant(30, "msg_02")]),
        )
        carry = read(named, SETTINGS).carry
        _added(named, _continuing("line-3", [hooked(31, "tidy.sh")]))

        with pytest.raises(
            NotContinuedError,
            match="a Stop hook's summary lies on a prompt received before its boundary's",
        ):
            read(named, SETTINGS, carry)
        whole = read(named, SETTINGS).publication
        assert [len(prompt.hook_runs) for prompt in whole.launches[0].prompts] == [1]

    def test_a_compaction_that_continues_a_line_behind_the_boundary_is_not_read_on(
        self, named: Transcript, carry: Carry
    ) -> None:
        """The carry holds where the chain leads from its own line alone."""
        (made,) = linked([boundary(14)], "grown")
        _added(named, [made | {"logicalParentUuid": "line-2"}])

        with pytest.raises(
            NotContinuedError, match="a compaction continues a line before its boundary"
        ):
            read(named, SETTINGS, carry)

        assert read(named, SETTINGS).publication.calls[-1].predecessor == "msg_01"

    def test_a_compaction_that_names_no_line_of_the_file_is_not_read_on(
        self, named: Transcript, carry: Carry
    ) -> None:
        """Read from its boundary on, a line the file does not hold is not
        told from one behind the boundary."""
        (made,) = linked([boundary(14)], "grown")
        _added(
            named,
            [made | {"logicalParentUuid": "a-line-of-another-file"}, summary(13.7)],
        )

        with pytest.raises(
            NotContinuedError, match="a compaction continues a line before its boundary"
        ):
            read(named, SETTINGS, carry)

    def test_a_compaction_that_continues_the_carrys_line_or_a_later_one_is_read_on(
        self, named: Transcript, carry: Carry
    ) -> None:
        assert carry.stands.link == "line-3"
        made, left, answer = linked(
            [boundary(14), summary(13.7), assistant(20, "msg_03")], "grown"
        )
        again, more = linked([boundary(30), assistant(34, "msg_04")], "more")
        _added(
            named,
            [
                made | {"logicalParentUuid": "line-3"},
                left,
                answer,
                again | {"logicalParentUuid": "grown-2"},
                more,
            ],
        )

        publication = read(named, SETTINGS, carry).publication

        assert len(publication.compactions) == 2
        assert [
            (call.message_id, call.predecessor, call.compaction)
            for call in publication.calls
        ] == [
            ("msg_02", "msg_01", None),
            ("msg_03", "msg_01", 1),
            ("msg_04", "msg_01", 2),
        ]

    def test_the_lines_of_a_file_that_grew_follow_the_carrys_line_and_each_other(
        self, named: Transcript, carry: Carry
    ) -> None:
        """The boundary's first line follows the last line before it, and a
        line beside the chain follows none."""
        _added(
            named,
            [
                queue("enqueue", 12, "Beat the weft."),
                typed(14) | {"uuid": "grown-1", "parentUuid": "line-4"},
                assistant(16, "msg_03") | {"uuid": "grown-2", "parentUuid": "line-3"},
                typed(18) | {"uuid": "grown-3", "parentUuid": None},
            ],
        )

        publication = read(named, SETTINGS, carry).publication

        assert [call.message_id for call in publication.calls] == ["msg_02", "msg_03"]

    @pytest.mark.parametrize(
        ("then", "reason"),
        [
            (
                FORKED | {"toolUseId": "toolu_77"},
                "its record names another fork's call than the one it was read with",
            ),
            (
                FORKED | {"agentType": "general-purpose"},
                "its record names another fork's call than the one it was read with",
            ),
        ],
        ids=["another fork's call", "no fork's"],
    )
    def test_a_record_that_names_another_fork_than_the_carrys_is_not_read_on(
        self, then: dict[str, str], reason: str, tmp_path: Path
    ) -> None:
        named = filed(tmp_path, _forked(), AGENT)
        recorded(tmp_path, **FORKED)
        carry = read(named, SETTINGS).carry
        recorded(tmp_path, **then)
        _added(named, [assistant(18, "msg_03", output=6)])

        with pytest.raises(NotContinuedError, match=reason):
            read(named, SETTINGS, carry)

    def test_a_forks_record_written_after_the_reading_it_continues_is_not_read_on(
        self, tmp_path: Path
    ) -> None:
        named = filed(tmp_path, _forked(), AGENT)
        carry = read(named, SETTINGS).carry
        recorded(tmp_path, **FORKED)
        _added(named, [assistant(18, "msg_03", output=6)])

        with pytest.raises(
            NotContinuedError, match="its record names another fork's call"
        ):
            read(named, SETTINGS, carry)

    def test_a_forks_line_from_the_boundary_on_holding_its_call_is_not_read_on(
        self, tmp_path: Path
    ) -> None:
        """Read before the file held the line, every line was the fork's."""
        lines = _forked()
        named = filed(tmp_path, lines[:5], AGENT)
        recorded(tmp_path, **FORKED)
        carry = read(named, SETTINGS).carry
        _added(named, lines[5:])

        with pytest.raises(
            NotContinuedError,
            match="a fork's line from its boundary on holds the call that started it",
        ):
            read(named, SETTINGS, carry)

    def test_a_whole_reading_drops_a_result_no_request_names(
        self, named: Transcript, carry: Carry
    ) -> None:
        _added(named, [result(14, "toolu_09")])

        publication = read(named, SETTINGS).publication

        assert [len(call.tool_calls) for call in publication.calls] == [1, 0]
