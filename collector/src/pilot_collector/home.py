"""A transcript's file on the home: where Claude Code files a thread under
the home's `projects`, and the ids its place gives it.

A main thread's file is `<folder>/<session_id>.jsonl`, the folder named for
the directory the conversation began in. A sub-agent's is
`<folder>/<session_id>/subagents/agent-<agent_id>.jsonl`, and one a workflow
started lies deeper, under `subagents/workflows/<workflow>/`. Nothing else
under `projects` is a transcript: a workflow's `journal.jsonl`, a sub-agent's
`.meta.json` and the outputs saved under `tool-results/` among them.
"""

from dataclasses import dataclass
from pathlib import Path

_SUFFIX = ".jsonl"
_SUB_AGENTS = "subagents"
_AGENT = "agent-"


@dataclass(frozen=True)
class Transcript:
    """One thread's file: its path, Claude Code's id of its conversation's
    main thread and, on a sub-agent's thread, of the sub-agent."""

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
        return Transcript(path, stem)
    if (
        len(folders) >= 3
        and folders[2] == _SUB_AGENTS
        and stem.startswith(_AGENT)
        and stem != _AGENT
    ):
        return Transcript(path, folders[1], stem.removeprefix(_AGENT))
    return None
