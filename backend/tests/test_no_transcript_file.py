"""No transcript's file is committed (F122.3): a transcript in a test is
generated when the suite runs. The six stream fixtures of
`tests/fixtures/raw/` stay: a turn's events as the controller relays them.

The suite's tree holds no `.git`, so the check reads the tree's files: all
but the folders the tree's `.gitignore` files keep out of a commit.
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
"""The repository's root, which holds `backend/`."""

STREAMS = {
    Path("backend/tests/fixtures/raw") / name
    for name in (
        "turn_background.jsonl",
        "turn_resumed.jsonl",
        "turn_subagent.jsonl",
        "turn_text.jsonl",
        "turn_tool.jsonl",
        "turn_wall.jsonl",
    )
}
"""The invented stream fixtures, the one kind of JSON Lines file the tree
holds."""

UNCOMMITTED = {
    "node_modules",
    "__pycache__",
    "test-results",
    "playwright-report",
    "browsers",
    "logs",
    "tmp",
    "dist",
}
"""The folders no commit holds, beside those whose name starts with a dot."""

LINE_KEYS = {"sessionId", "parentUuid"}
"""What a line Claude Code writes into a transcript carries: the
conversation's id and the line it follows."""


def _is_a_transcripts_line(line: bytes) -> bool:
    if not line.startswith(b"{"):
        return False
    try:
        read = json.loads(line)
    except ValueError:
        return False
    return isinstance(read, dict) and LINE_KEYS <= read.keys()


def _transcripts(root: Path) -> set[Path]:
    """The files under `root` that are a transcript's, each from `root`: one
    named as Claude Code names a transcript's file, in JSON Lines, or one
    holding a line of a transcript's."""
    found: set[Path] = set()
    for folder, folders, files in os.walk(root):
        folders[:] = [
            name
            for name in folders
            if not name.startswith(".") and name not in UNCOMMITTED
        ]
        for name in files:
            file = Path(folder) / name
            if file.is_symlink():
                continue
            if file.suffix == ".jsonl" or any(
                _is_a_transcripts_line(line) for line in file.read_bytes().splitlines()
            ):
                found.add(file.relative_to(root))
    return found


class TestNoTranscriptFile:
    def test_the_tree_holds_no_transcript_but_the_six_stream_fixtures(self) -> None:
        assert _transcripts(ROOT) == STREAMS

    def test_a_stream_fixture_holds_no_line_of_a_transcript(self) -> None:
        for stream in STREAMS:
            lines = (ROOT / stream).read_bytes().splitlines()
            assert lines
            assert not any(_is_a_transcripts_line(line) for line in lines), stream

    def test_a_transcripts_file_in_the_tree_is_found(self, tmp_path: Path) -> None:
        (tmp_path / "tests" / "fixtures").mkdir(parents=True)
        named = tmp_path / "tests" / "fixtures" / "session.jsonl"
        named.write_text("{}\n")

        assert _transcripts(tmp_path) == {Path("tests/fixtures/session.jsonl")}

    def test_a_transcript_under_another_name_is_found(self, tmp_path: Path) -> None:
        line = {
            "sessionId": "5e7f9a10-1c2d-4e3f-8a4b-6c7d8e9f0a1b",
            "parentUuid": None,
            "type": "user",
        }
        (tmp_path / "notes.txt").write_text(f"A note.\n{json.dumps(line)}\n")
        (tmp_path / "plain.json").write_text(json.dumps({"sessionId": "invented"}))

        assert _transcripts(tmp_path) == {Path("notes.txt")}

    def test_a_folder_no_commit_holds_is_not_read(self, tmp_path: Path) -> None:
        for folder in (".venv", "node_modules", "frontend/test-results"):
            (tmp_path / folder).mkdir(parents=True)
            (tmp_path / folder / "run.jsonl").write_text("{}\n")

        assert _transcripts(tmp_path) == set()
