"""A transcript's file read from its boundary on (F152.15): the carry a
reading leaves, the appended publication of a file that grew, and where the
file is read whole instead."""

import json
import os
from pathlib import Path

import pytest
from pilot_collection.publication import PublicationSchema
from pilot_scenario import SCENARIO, Builder, Scenario

from pilot_collector import VERSION
from pilot_collector.carry import Carry, Open, Standing, digest
from pilot_collector.home import Transcript, transcript
from pilot_collector.reader import NotContinuedError, Read, UnreadableError, read
from tests import support
from tests.support import (
    AGENT,
    DIRECTORY,
    MANAGED,
    Line,
    assistant,
    cost,
    filed,
    instructions,
    linked,
    loaded,
    moment,
    queue,
    requesting,
    result,
    taken,
    typed,
    user,
)
from tests.test_reader import UNTIL, _resumed

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
            "calls": held.calls[: boundary.call - 1] + grown.calls,
        }
    )


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
            link="line-3",
            directory=DIRECTORY,
            environment=None,
            launch=Open(moment(0), support.VERSION, 1),
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
        lines = [
            typed(0),
            assistant(4, "msg_01"),
            cost(),
            typed(60) | {"version": "2.1.318"},
            typed(61),
            assistant(64, "msg_02"),
        ]

        stands = read(filed(tmp_path, lines), SETTINGS).carry.stands

        assert (stands.launches, stands.prompts) == (1, 3)
        assert stands.launch == Open(moment(60), "2.1.318", 2)

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
            Open(moment(60), support.VERSION, 1),
        )

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
        ("scenario", "read_whole"),
        [(SCENARIO, 2), (_resumed(), 0)],
        ids=["the scenario", "a resumed thread"],
    )
    def test_a_scenarios_file_grown_a_line_at_a_time_reads_as_its_whole(
        self, scenario: Scenario, read_whole: int, tmp_path: Path
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
        assert whole_instead == read_whole
        assert appended >= 10

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
        assert grown.carry.stands.launch == Open(moment(0), support.VERSION, 2)

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
                    assistant(64, "msg_02"),
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

    def test_a_whole_reading_drops_a_result_no_request_names(
        self, named: Transcript, carry: Carry
    ) -> None:
        _added(named, [result(14, "toolu_09")])

        publication = read(named, SETTINGS).publication

        assert [len(call.tool_calls) for call in publication.calls] == [1, 0]
