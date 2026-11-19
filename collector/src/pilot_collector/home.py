"""A transcript's file on the home: where Claude Code files a thread under
the home's `projects`, and the ids its place gives it.

A main thread's file is `<folder>/<session_id>.jsonl`, the folder named for
the directory the conversation began in. A sub-agent's is
`<folder>/<session_id>/subagents/agent-<agent_id>.jsonl`, and one a workflow
started lies deeper, under `subagents/workflows/<workflow>/`. Nothing else
under `projects` is a transcript: a workflow's `journal.jsonl`, a sub-agent's
`.meta.json` and the outputs saved under `tool-results/` among them.

An output too large for its result is saved as
`<folder>/<session_id>/tool-results/<name>`, beside the conversation's
sub-agents, and the result names it by its path as the session's own process
sees the home.
"""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_SUFFIX = ".jsonl"
_SUB_AGENTS = "subagents"
_AGENT = "agent-"
_SAVED = "tool-results"


@dataclass(frozen=True)
class Transcript:
    """One thread's file: the home's `projects` it is filed under, its
    path, Claude Code's id of its conversation's main thread and, on a
    sub-agent's thread, of the sub-agent."""

    projects: Path
    path: Path
    session_id: str
    agent_id: str | None = None

    @property
    def name(self) -> str:
        """The transcript as a message names it."""
        if self.agent_id is None:
            return self.session_id
        return f"{self.session_id}/{self.agent_id}"


def transcript(projects: Path, path: Path) -> Transcript | None:
    """The transcript the file at `path` under `projects` is, by its place;
    none for a file that is no transcript's."""
    *folders, name = path.relative_to(projects).parts
    if not name.endswith(_SUFFIX):
        return None
    stem = name.removesuffix(_SUFFIX)
    if len(folders) == 1:
        return Transcript(projects, path, stem)
    if (
        len(folders) >= 3
        and folders[2] == _SUB_AGENTS
        and stem.startswith(_AGENT)
        and stem != _AGENT
    ):
        return Transcript(projects, path, folders[1], stem.removeprefix(_AGENT))
    return None


def saved_output(projects: Path, named: str) -> Path | None:
    """Where under `projects` the saved output lies that a result names as
    `named`, its path on the session's own home: by that path's last four
    parts, whatever the home's folder is there. None for a path that is no
    saved output's."""
    parts = PurePosixPath(named).parts[-4:]
    if len(parts) != 4 or parts[2] != _SAVED or {"/", ".."} & set(parts):
        return None
    return projects.joinpath(*parts)
