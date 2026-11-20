"""A transcript's file by its place under the home's `projects`."""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pilot_collector.home import (
    Listed,
    Transcript,
    find,
    saved_output,
    transcript,
    transcripts,
)
from pilot_collector.reader import read
from tests.support import AGENT, FOLDER, SESSION, filed, settings, typed

OTHER = "9d3b7e52-1c4a-4f80-b6e9-05a7c3f1d248"
"""Claude Code's id of another conversation."""

PROJECTS = Path("/home/ubuntu/.claude/projects")


class TestATranscriptsPlace:
    def test_a_main_threads_file_is_named_for_its_conversation(self) -> None:
        path = PROJECTS / FOLDER / f"{SESSION}.jsonl"

        assert transcript(PROJECTS, path) == Transcript(PROJECTS, path, SESSION)

    def test_a_sub_agents_file_lies_under_its_conversations_subagents(self) -> None:
        path = PROJECTS / FOLDER / SESSION / "subagents" / f"agent-{AGENT}.jsonl"

        assert transcript(PROJECTS, path) == Transcript(PROJECTS, path, SESSION, AGENT)

    def test_a_workflows_sub_agent_lies_deeper_and_is_its_conversations(self) -> None:
        folder = PROJECTS / FOLDER / SESSION / "subagents" / "workflows" / "wf_7c21"
        path = folder / f"agent-{AGENT}.jsonl"

        assert transcript(PROJECTS, path) == Transcript(PROJECTS, path, SESSION, AGENT)

    @pytest.mark.parametrize(
        "place",
        [
            f"{FOLDER}/{SESSION}/subagents/workflows/wf_7c21/journal.jsonl",
            f"{FOLDER}/{SESSION}/subagents/agent-{AGENT}.meta.json",
            f"{FOLDER}/{SESSION}/subagents/agent-.jsonl",
            f"{FOLDER}/{SESSION}/tool-results/toolu_01.txt",
            f"{FOLDER}/{SESSION}/tool-results/agent-{AGENT}.jsonl",
            f"{FOLDER}/{SESSION}/notes.jsonl",
            f"{FOLDER}/{SESSION}.json",
            f"{SESSION}.jsonl",
        ],
    )
    def test_nothing_else_under_projects_is_a_transcript(self, place: str) -> None:
        assert transcript(PROJECTS, PROJECTS / place) is None

    def test_a_message_names_a_thread_by_its_ids(self) -> None:
        path = PROJECTS / FOLDER / f"{SESSION}.jsonl"

        assert Transcript(PROJECTS, path, SESSION).name == SESSION
        assert Transcript(PROJECTS, path, SESSION, AGENT).name == f"{SESSION}/{AGENT}"


class TestASavedOutputsPlace:
    @pytest.mark.parametrize(
        "home", ["/home/ubuntu/.claude", "/home/cleo/.config/claude", "/srv/a home"]
    )
    def test_it_lies_under_projects_by_the_last_four_parts_of_its_path(
        self, home: str
    ) -> None:
        named = f"{home}/projects/{FOLDER}/{SESSION}/tool-results/b7q2x9k1m.txt"

        assert saved_output(PROJECTS, named) == (
            PROJECTS / FOLDER / SESSION / "tool-results" / "b7q2x9k1m.txt"
        )

    @pytest.mark.parametrize(
        "named",
        [
            "/etc/passwd",
            "b7q2x9k1m.txt",
            "/tool-results/b7q2x9k1m.txt",
            "/looms/tool-results/b7q2x9k1m.txt",
            f"/home/ubuntu/.claude/projects/{FOLDER}/{SESSION}/b7q2x9k1m.txt",
            f"/home/ubuntu/.claude/projects/{FOLDER}/{SESSION}/subagents/b7q2x9k1m.txt",
            f"/home/ubuntu/.claude/projects/{FOLDER}/../tool-results/b7q2x9k1m.txt",
            f"/home/ubuntu/.claude/projects/../{SESSION}/tool-results/b7q2x9k1m.txt",
            f"/home/ubuntu/.claude/projects/{FOLDER}/{SESSION}/tool-results/..",
        ],
    )
    def test_a_path_of_another_shape_is_no_saved_outputs(self, named: str) -> None:
        assert saved_output(PROJECTS, named) is None


def _put(path: Path, content: bytes = b"{}\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _names(projects: Path) -> set[str]:
    return {listed.transcript.name for listed in transcripts(projects)}


class TestTheHomesTranscripts:
    def test_every_threads_file_is_listed_with_its_size_and_time(
        self, tmp_path: Path
    ) -> None:
        main = _put(tmp_path / FOLDER / f"{SESSION}.jsonl", b"{}\n{}\n")
        sub_agents = tmp_path / FOLDER / SESSION / "subagents"
        sub_agent = _put(sub_agents / f"agent-{AGENT}.jsonl")
        workflows = _put(sub_agents / "workflows" / "wf_7c21" / "agent-b81e.jsonl")
        other = _put(tmp_path / "-work-Spindle" / f"{OTHER}.jsonl")
        stood = datetime(2026, 11, 12, 10, 2, 3, 456789, tzinfo=UTC)
        at = int(stood.timestamp()) * 10**9 + 456_789_321
        for path in (main, sub_agent, workflows, other):
            os.utime(path, ns=(at, at))

        listed = sorted(transcripts(tmp_path), key=lambda each: each.transcript.name)

        assert listed == [
            Listed(Transcript(tmp_path, main, SESSION), 6, stood),
            Listed(Transcript(tmp_path, sub_agent, SESSION, AGENT), 3, stood),
            Listed(Transcript(tmp_path, workflows, SESSION, "b81e"), 3, stood),
            Listed(Transcript(tmp_path, other, OTHER), 3, stood),
        ]

    def test_a_files_time_is_the_one_its_publication_names(
        self, tmp_path: Path
    ) -> None:
        filed(tmp_path, [typed(0)])
        at = 1_794_474_123_456_789_123
        os.utime(tmp_path / FOLDER / f"{SESSION}.jsonl", ns=(at, at))

        [listed] = transcripts(tmp_path)

        publication = read(listed.transcript, settings()).publication
        assert listed.file_modified_at == publication.file_modified_at
        assert listed.file_size == publication.file_size

    def test_what_is_no_transcripts_is_not_listed(self, tmp_path: Path) -> None:
        session = tmp_path / FOLDER / SESSION
        _put(tmp_path / FOLDER / f"{SESSION}.jsonl")
        _put(tmp_path / f"{OTHER}.jsonl")
        _put(tmp_path / FOLDER / f"{OTHER}.json")
        _put(session / "notes.jsonl")
        _put(session / "tool-results" / f"agent-{AGENT}.jsonl")
        _put(session / "tool-results" / "subagents" / f"agent-{AGENT}.jsonl")
        _put(session / "subagents" / f"agent-{AGENT}.meta.json")
        _put(session / "subagents" / "workflows" / "wf_7c21" / "journal.jsonl")

        assert _names(tmp_path) == {SESSION}

    def test_no_symlink_is_followed(self, tmp_path: Path) -> None:
        """A sub-agent's file linked into another session's folder is its own
        session's, and a linked folder's files are where the folder is."""
        _put(tmp_path / FOLDER / f"{SESSION}.jsonl")
        own = _put(tmp_path / FOLDER / SESSION / "subagents" / f"agent-{AGENT}.jsonl")
        elsewhere = tmp_path / FOLDER / OTHER / "subagents"
        elsewhere.mkdir(parents=True)
        (elsewhere / f"agent-{AGENT}.jsonl").symlink_to(own)
        (tmp_path / FOLDER / f"{OTHER}.jsonl").symlink_to(
            tmp_path / FOLDER / f"{SESSION}.jsonl"
        )
        (tmp_path / "-work-Spindle").symlink_to(tmp_path / FOLDER)
        (elsewhere / "workflows").symlink_to(tmp_path / FOLDER / SESSION / "subagents")

        assert _names(tmp_path) == {SESSION, f"{SESSION}/{AGENT}"}

    def test_a_pipe_of_a_transcripts_name_is_not_listed(self, tmp_path: Path) -> None:
        """Its read would wait for a writer, and the walk with it."""
        _put(tmp_path / FOLDER / f"{SESSION}.jsonl")
        os.mkfifo(tmp_path / FOLDER / f"{OTHER}.jsonl")
        sub_agents = tmp_path / FOLDER / SESSION / "subagents"
        sub_agents.mkdir(parents=True)
        os.mkfifo(sub_agents / f"agent-{AGENT}.jsonl")

        assert _names(tmp_path) == {SESSION}

    def test_a_folder_that_cannot_be_listed_holds_none_and_is_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _put(tmp_path / FOLDER / f"{SESSION}.jsonl")
        closed = tmp_path / "-work-Spindle"
        _put(closed / f"{OTHER}.jsonl")
        closed.chmod(0)
        try:
            if os.access(closed, os.R_OK):
                pytest.skip("this user lists a folder whatever its mode")

            assert _names(tmp_path) == {SESSION}
        finally:
            closed.chmod(0o755)
        assert f"The folder {closed} cannot be listed" in caplog.text

    def test_a_home_with_no_projects_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            transcripts(tmp_path / "projects")


class TestATranscriptByItsIds:
    def test_each_listed_transcript_is_found_as_it_is_listed(
        self, tmp_path: Path
    ) -> None:
        _put(tmp_path / FOLDER / f"{SESSION}.jsonl", b"{}\n{}\n")
        sub_agents = tmp_path / FOLDER / SESSION / "subagents"
        _put(sub_agents / f"agent-{AGENT}.jsonl")
        _put(sub_agents / "workflows" / "wf_7c21" / "agent-b81e.jsonl")
        _put(tmp_path / "-work-Spindle" / f"{OTHER}.jsonl")
        _put(tmp_path / "-work-Spindle" / OTHER / "subagents" / "agent-c02f.jsonl")

        listed = transcripts(tmp_path)

        assert len(listed) == 5
        for each in listed:
            named = each.transcript
            assert find(tmp_path, named.session_id, named.agent_id) == each

    def test_ids_the_home_has_no_file_under_find_none(self, tmp_path: Path) -> None:
        _put(tmp_path / FOLDER / f"{SESSION}.jsonl")
        _put(tmp_path / FOLDER / SESSION / "subagents" / f"agent-{AGENT}.jsonl")
        _put(tmp_path / "-work-Spindle" / f"{OTHER}.jsonl")
        _put(tmp_path / f"{OTHER}.jsonl")

        assert find(tmp_path, "0e5a9b1c-3d7f-4e26-8a4b-c6d0f2e1a397") is None
        assert find(tmp_path, SESSION, "b81e") is None
        assert find(tmp_path, OTHER, AGENT) is None
        assert find(tmp_path, FOLDER) is None

    def test_what_a_walk_does_not_list_is_not_found(self, tmp_path: Path) -> None:
        """A symlink, and what is no transcript's by its place."""
        main = _put(tmp_path / FOLDER / f"{SESSION}.jsonl")
        own = _put(tmp_path / FOLDER / SESSION / "subagents" / f"agent-{AGENT}.jsonl")
        elsewhere = tmp_path / FOLDER / OTHER / "subagents"
        elsewhere.mkdir(parents=True)
        (elsewhere / f"agent-{AGENT}.jsonl").symlink_to(own)
        (tmp_path / FOLDER / f"{OTHER}.jsonl").symlink_to(main)
        _put(tmp_path / FOLDER / SESSION / "tool-results" / "agent-b81e.jsonl")
        (tmp_path / FOLDER / "a-folder.jsonl").mkdir()

        assert find(tmp_path, OTHER) is None
        assert find(tmp_path, OTHER, AGENT) is None
        assert find(tmp_path, SESSION, "b81e") is None
        assert find(tmp_path, "a-folder") is None

    @pytest.mark.parametrize(
        ("session_id", "agent_id"),
        [
            ("..", None),
            (".", None),
            ("", None),
            (f"{SESSION}/subagents/agent-{AGENT}", None),
            (f"../{FOLDER}/{SESSION}", None),
            (f"{SESSION}\0", None),
            ("..", AGENT),
            (SESSION, ""),
            (SESSION, f"../agent-{AGENT}"),
            (SESSION, f"workflows/wf_7c21/agent-{AGENT}"),
        ],
    )
    def test_an_id_that_is_more_than_a_name_finds_none(
        self, tmp_path: Path, session_id: str, agent_id: str | None
    ) -> None:
        _put(tmp_path / FOLDER / f"{SESSION}.jsonl")
        sub_agents = tmp_path / FOLDER / SESSION / "subagents"
        _put(sub_agents / f"agent-{AGENT}.jsonl")
        _put(sub_agents / "workflows" / "wf_7c21" / f"agent-agent-{AGENT}.jsonl")
        _put(tmp_path / "subagents" / f"agent-{AGENT}.jsonl")

        assert find(tmp_path, session_id, agent_id) is None

    def test_a_home_with_no_projects_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            find(tmp_path / "projects", SESSION)
