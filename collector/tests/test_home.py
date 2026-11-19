"""A transcript's file by its place under the home's `projects`."""

from pathlib import Path

import pytest

from pilot_collector.home import Transcript, transcript
from tests.support import AGENT, FOLDER, SESSION

PROJECTS = Path("/home/ubuntu/.claude/projects")


class TestATranscriptsPlace:
    def test_a_main_threads_file_is_named_for_its_conversation(self) -> None:
        path = PROJECTS / FOLDER / f"{SESSION}.jsonl"

        assert transcript(PROJECTS, path) == Transcript(path, SESSION)

    def test_a_sub_agents_file_lies_under_its_conversations_subagents(self) -> None:
        path = PROJECTS / FOLDER / SESSION / "subagents" / f"agent-{AGENT}.jsonl"

        assert transcript(PROJECTS, path) == Transcript(path, SESSION, AGENT)

    def test_a_workflows_sub_agent_lies_deeper_and_is_its_conversations(self) -> None:
        folder = PROJECTS / FOLDER / SESSION / "subagents" / "workflows" / "wf_7c21"
        path = folder / f"agent-{AGENT}.jsonl"

        assert transcript(PROJECTS, path) == Transcript(path, SESSION, AGENT)

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

        assert Transcript(path, SESSION).name == SESSION
        assert Transcript(path, SESSION, AGENT).name == f"{SESSION}/{AGENT}"
