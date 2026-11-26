"""The workflow's labeller as the collector runs it (F152.6, F152.7): the
command its settings name, the stamps of every transcript on a home in one
call and the vocabularies as Pilot takes them, proved against the stub
labeller (F122.5) on a home the scenario's builder wrote, and every way a
call gives no answer the collector takes."""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pilot_collection.inventory import InventorySchema
from pilot_collection.vocabularies import VocabulariesSchema
from pilot_scenario import SCENARIO, Builder, labeller

from pilot_collector import labeller as running
from pilot_collector.home import transcripts
from pilot_collector.labeller import Labeller, Unanswered
from tests.support import settings

UNTIL = datetime(2026, 11, 12, 9, 30, tzinfo=UTC)
RECIPES = "8766dbc8-267a-5322-9a1d-cc49ad56eedd"
"""The scenario's conversation with a sub-agent."""
COUNTING = "6d6212072d4d5b429"
"""Its sub-agent."""
RIDES = "037915e7-de88-5550-9746-3e7a4472413a"
"""The scenario's other conversation, the first by its id."""
STAMP = "1:Qm9hdHMgb24gdGhlIGxha2U"
"""A stamp Pilot holds."""
COPY = "/home/ubuntu/.claude/plugins/cache/aiworkflow/dev/0.10.200"
"""The installed copy's folder as the fleet's sessions see it."""


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A fleet's home that holds the scenario's transcripts and the stub
    labeller's run records."""
    Builder(SCENARIO, UNTIL).write(tmp_path)
    return tmp_path


def _stub(home: Path, *options: str, **given: Any) -> Labeller:
    """The collector's labeller on `home`: the stub, run with `options`."""
    return Labeller(
        settings(
            COLLECTOR_HOME=home, COLLECTOR_LABELLER=labeller.command(*options), **given
        )
    )


def _answering(home: Path, said: str, exits: int = 0, **given: Any) -> Labeller:
    """The collector's labeller on `home`: a command that reads its request,
    writes `said` and a line to its stderr, and exits `exits`."""
    script = (
        "import sys; sys.stdin.read()"
        f"; sys.stdout.write({said!r}); sys.stderr.write('The pot boiled over.\\n')"
        f"; sys.exit({exits})"
    )
    return Labeller(
        settings(
            COLLECTOR_HOME=home,
            COLLECTOR_LABELLER=[sys.executable, "-c", script],
            **given,
        )
    )


def _inventory(*held: dict[str, Any], **ran: list[Any]) -> InventorySchema:
    """Pilot's inventory holding `held`, and of each conversation of `ran`,
    by its session id, the Sessions of Pilot's on it."""
    return InventorySchema.model_validate(
        {
            "walk_interval_seconds": 30.0,
            "settling_seconds": 600.0,
            "transcripts": list(held),
            "conversations": [
                {"session_id": session_id, "sessions": sessions, "documents": []}
                for session_id, sessions in ran.items()
            ],
        }
    )


def _held(session_id: str, agent_id: str | None = None, **facts: Any) -> dict[str, Any]:
    """A transcript as Pilot's inventory holds one, labelled, but for
    `facts`."""
    held: dict[str, Any] = {
        "session_id": session_id,
        "agent_id": agent_id,
        "file_size": 61_000,
        "file_modified_at": UNTIL.isoformat(),
        "replayed_size": 61_000,
        "collector": "1.0.0",
        "labeller": labeller.VERSION,
        "stamp": STAMP,
    }
    return held | facts


def _session(brief: str = "Halve the stew.") -> dict[str, Any]:
    """A Session of Pilot's, as the inventory hands one."""
    return {
        "id": "0b6f3c2a-8d41-4e7a-9c15-2f8e6d4a7b30",
        "kind": "work",
        "created_at": (UNTIL - timedelta(hours=1)).isoformat(),
        "brief": brief,
        "repo": "RecipeBox",
        "clarification": False,
        "holds": [],
        "turns": [
            {
                "started_at": (UNTIL - timedelta(minutes=59)).isoformat(),
                "cause": "brief",
            }
        ],
    }


def _calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Each call of the labeller from here on: its verb and its request."""
    calls: list[tuple[str, dict[str, Any]]] = []
    run = subprocess.run

    def recorded(command: list[str], **given: Any) -> Any:
        calls.append((command[-1], json.loads(given["input"])))
        return run(command, **given)

    monkeypatch.setattr(running.subprocess, "run", recorded)
    return calls


def _installed(home: Path, *copies: str, plugin: str = "dev@aiworkflow") -> None:
    """The home's `installed_plugins.json`, naming those copies of
    `plugin` as the fleet's sessions see them."""
    file = home / "plugins" / "installed_plugins.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    plugin: [
                        {"scope": "user", "installPath": copy, "version": "0.10.200"}
                        for copy in copies
                    ]
                },
            }
        )
    )


def _copied_in(home: Path, copy: str = COPY) -> Path:
    """The stub put where the home installs the `dev` plugin's copy, as its
    `tools/labeller.py`: the copy's folder as the collector sees it."""
    folder = home / "plugins" / Path(copy).relative_to("/home/ubuntu/.claude/plugins")
    (folder / "tools").mkdir(parents=True)
    shutil.copyfile(labeller.__file__, folder / "tools" / "labeller.py")
    return folder


def _record(home: Path, agent_type: object) -> Path:
    """Rewrite the sub-agent's record to name `agent_type`."""
    path = next((home / "projects").rglob(f"agent-{COUNTING}.meta.json"))
    path.write_text(json.dumps({"agentType": agent_type, "toolUseId": "toolu_0002"}))
    return path


def _handed_types(calls: list[tuple[str, dict[str, Any]]]) -> list[object]:
    """The sub-agent's `agent_type` as each call handed it."""
    return [
        transcript.get("agent_type", "none handed")
        for _, request in calls
        for conversation in request["conversations"]
        for transcript in conversation["transcripts"]
        if transcript["agent_id"] == COUNTING
    ]


class TestTheStamps:
    def test_every_transcript_on_the_home_is_stamped_in_one_call(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _calls(monkeypatch)

        stamps = _stub(home).stamps(transcripts(home / "projects"), _inventory())

        assert [verb for verb, _ in calls] == ["stamps"]
        assert stamps.version == labeller.VERSION
        assert set(stamps.stamps) == {
            (RECIPES, None),
            (RECIPES, COUNTING),
            (RIDES, None),
        }
        assert None not in stamps.stamps.values()
        assert stamps.seconds > 0

    def test_each_is_handed_in_its_conversation_with_what_pilot_holds(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A conversation Pilot ran is handed its Sessions as the inventory
        gives them, one it did not none; a transcript Pilot holds no stamp
        for, or holds not at all, is handed none."""
        calls = _calls(monkeypatch)
        inventory = _inventory(
            _held(RIDES), _held(RECIPES, COUNTING, stamp=None), **{RIDES: [_session()]}
        )

        _stub(home).stamps(transcripts(home / "projects"), inventory)

        ((_, request),) = calls
        assert set(request) == {"contract", "home", "pilot", "index", "conversations"}
        assert request["contract"] == 1
        assert request["home"] == {
            "projects": str(home / "projects"),
            "plugins": str(home / "plugins"),
        }
        assert request["pilot"] == {"conversations": [RIDES]}
        assert request["index"] is None
        assert request["conversations"] == [
            {
                "session_id": RIDES,
                "sessions": inventory.conversations[0].model_dump(mode="json")[
                    "sessions"
                ],
                "documents": [],
                "transcripts": [{"agent_id": None, "held": STAMP}],
            },
            {
                "session_id": RECIPES,
                "sessions": [],
                "documents": [],
                "transcripts": [
                    {"agent_id": None, "held": None},
                    {"agent_id": COUNTING, "agent_type": "Explore", "held": None},
                ],
            },
        ]

    def test_a_conversation_handed_the_same_keeps_its_stamp(self, home: Path) -> None:
        """The stamp covers what is handed with a conversation, so it is
        handed in one form at every walk."""
        stub, listed = _stub(home), transcripts(home / "projects")
        ran = _inventory(**{RIDES: [_session()]})

        first, again = stub.stamps(listed, ran), stub.stamps(listed, ran)
        other = stub.stamps(listed, _inventory(**{RIDES: [_session("Bake.")]}))

        assert first.stamps == again.stamps
        assert other.stamps[(RIDES, None)] != first.stamps[(RIDES, None)]
        assert other.stamps[(RECIPES, None)] == first.stamps[(RECIPES, None)]

    def test_the_index_it_handed_back_is_handed_at_its_next_call(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub, listed = _stub(home), transcripts(home / "projects")
        calls = _calls(monkeypatch)

        stub.stamps(listed, _inventory())
        stub.stamps(listed, _inventory())
        stub.vocabularies()

        _, first = calls[0]
        index = first["index"]
        assert index is None
        handed = [request["index"] for _, request in calls[1:]]
        assert handed[0] is not None and handed == [handed[0]] * 2

    def test_a_sub_agents_type_follows_its_record(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub, listed = _stub(home), transcripts(home / "projects")
        calls = _calls(monkeypatch)

        stub.stamps(listed, _inventory())
        record = _record(home, "Plan")
        stub.stamps(listed, _inventory())
        _record(home, 7)
        stub.stamps(listed, _inventory())
        record.unlink()
        stub.stamps(listed, _inventory())

        assert _handed_types(calls) == ["Explore", "Plan", None, None]

    def test_a_sub_agents_record_unchanged_is_not_read_again(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub, listed = _stub(home), transcripts(home / "projects")
        stub.stamps(listed, _inventory())
        read = Path.read_bytes
        records: list[Path] = []

        def reading(path: Path) -> bytes:
            records.append(path)
            return read(path)

        monkeypatch.setattr(Path, "read_bytes", reading)
        stub.stamps(listed, _inventory())

        assert not [path for path in records if path.name.endswith(".meta.json")]


class TestTheVocabularies:
    def test_pilot_takes_its_version_nestings_and_the_lists_it_keeps(
        self, home: Path
    ) -> None:
        """The stub's groups and its batchable conditions are no part of the
        call: the builder's declaration leaves them out."""
        declared = _stub(home).vocabularies()

        builder = Builder(SCENARIO, UNTIL)
        assert declared == VocabulariesSchema.model_validate(builder.vocabularies())
        assert declared.version == labeller.VERSION

    def test_one_that_lacks_a_list_pilot_keeps_is_none(self, home: Path) -> None:
        answer = labeller.vocabularies(Builder(SCENARIO, UNTIL).records())
        del answer["lists"]["rule"]

        with pytest.raises(
            Unanswered, match="not the shape Pilot takes: (?s:.*)lists.rule"
        ):
            _answering(home, json.dumps(answer)).vocabularies()


class TestTheCommand:
    def test_by_default_it_is_the_installed_copys_under_the_homes_plugins(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The copy's path on the fleet's home is taken from its `cache`
        folder on, under the `plugins` the collector sees."""
        folder = _copied_in(home)
        _installed(home, COPY, "/home/ubuntu/.claude/plugins/cache/aiworkflow/dev/0.9")
        commands: list[list[str]] = []
        run = running.subprocess.run

        def ran(command: list[str], **given: Any) -> Any:
            commands.append(command)
            return run(command, **given)

        monkeypatch.setattr(running.subprocess, "run", ran)

        stamps = Labeller(settings(COLLECTOR_HOME=home)).stamps(
            transcripts(home / "projects"), _inventory()
        )

        assert commands == [["python3", "-B", f"{folder}/tools/labeller.py", "stamps"]]
        assert stamps.version == labeller.VERSION

    def test_one_that_names_no_installed_copy_needs_none(self, home: Path) -> None:
        stamps = _stub(home).stamps(transcripts(home / "projects"), _inventory())

        assert not (home / "plugins" / "installed_plugins.json").exists()
        assert stamps.version == labeller.VERSION


class TestNoAnswer:
    """Every way a call of the labeller gives no answer the collector
    takes."""

    def _stamps(self, labelling: Labeller, home: Path) -> None:
        labelling.stamps(transcripts(home / "projects"), _inventory())

    def test_no_installed_plugins_is_no_copy_installed(self, home: Path) -> None:
        with pytest.raises(
            Unanswered,
            match="no copy is installed: the home has no plugins/installed_plugins.json",
        ):
            self._stamps(Labeller(settings(COLLECTOR_HOME=home)), home)

    def test_installed_plugins_that_name_no_dev_plugin_is_none_installed(
        self, home: Path
    ) -> None:
        _installed(home, COPY, plugin="looms@weavers")

        with pytest.raises(
            Unanswered,
            match="no copy is installed: the home's plugins/installed_plugins.json"
            " names no dev@aiworkflow",
        ):
            self._stamps(Labeller(settings(COLLECTOR_HOME=home)), home)

    def test_installed_plugins_that_do_not_read_are_none(self, home: Path) -> None:
        (home / "plugins" / "installed_plugins.json").write_text('{"plugins": [1]}')

        with pytest.raises(
            Unanswered,
            match="the home's plugins/installed_plugins.json cannot be read",
        ):
            self._stamps(Labeller(settings(COLLECTOR_HOME=home)), home)

    @pytest.mark.parametrize(
        "copy",
        [
            "/work/AIWorkflow/plugins/dev",
            "/home/ubuntu/.claude/plugins/cache/../dev/0.10.200",
        ],
    )
    def test_a_copy_outside_the_plugins_cache_is_none(
        self, home: Path, copy: str
    ) -> None:
        _installed(home, copy)

        with pytest.raises(
            Unanswered,
            match=re.escape(
                f"the installed copy's path {copy} is no copy in the home's"
                " plugins/cache"
            ),
        ):
            self._stamps(Labeller(settings(COLLECTOR_HOME=home)), home)

    def test_a_copy_with_no_labeller_fails_its_call(self, home: Path) -> None:
        _installed(home, COPY)
        (home / "plugins" / "cache" / "aiworkflow" / "dev" / "0.10.200").mkdir(
            parents=True
        )

        with pytest.raises(
            Unanswered, match="its `stamps` call exited 2: .*can't open file"
        ):
            self._stamps(Labeller(settings(COLLECTOR_HOME=home)), home)

    def test_a_labeller_of_another_contract_refuses_it(self, home: Path) -> None:
        with pytest.raises(
            Unanswered,
            match="it refused the `stamps` call: contract: contract 1 is not spoken here",
        ):
            self._stamps(_stub(home, "--speaks", "2"), home)

    def test_one_that_crashes_fails_it(self, home: Path) -> None:
        """Run records that do not parse crash the stub."""
        records = home / "plugins" / "data" / labeller.DATA / labeller.RECORDS
        records.write_text("{")

        with pytest.raises(
            Unanswered, match="its `stamps` call exited 1: json.decoder.JSONDecodeError"
        ):
            self._stamps(_stub(home), home)

    def test_one_that_cannot_be_run_fails_it(self, home: Path) -> None:
        missing = Labeller(
            settings(
                COLLECTOR_HOME=home, COLLECTOR_LABELLER=[str(home / "no-labeller")]
            )
        )

        with pytest.raises(Unanswered, match="its command cannot be run: "):
            self._stamps(missing, home)

    def test_one_past_its_time_is_stopped(self, home: Path) -> None:
        slow = Labeller(
            settings(
                COLLECTOR_HOME=home,
                COLLECTOR_LABELLER=[
                    sys.executable,
                    "-c",
                    "import time; time.sleep(30)",
                ],
                COLLECTOR_LABELLER_SECONDS=0.2,
            )
        )

        with pytest.raises(
            Unanswered, match=r"its `stamps` gave no answer within 0\.2 s"
        ):
            self._stamps(slow, home)

    def test_an_exit_2_with_no_refusal_is_a_failure_with_its_stderr(
        self, home: Path
    ) -> None:
        with pytest.raises(
            Unanswered, match="its `stamps` call exited 2: The pot boiled over.$"
        ):
            self._stamps(_answering(home, "The stove is cold.", exits=2), home)

    def test_a_crash_that_says_nothing_says_so(self, home: Path) -> None:
        script = "import sys; sys.stdin.read(); sys.exit(3)"
        silent = Labeller(
            settings(
                COLLECTOR_HOME=home, COLLECTOR_LABELLER=[sys.executable, "-c", script]
            )
        )

        with pytest.raises(
            Unanswered,
            match="its `stamps` call exited 3: it wrote nothing to its stderr",
        ):
            self._stamps(silent, home)

    @pytest.mark.parametrize(
        ("said", "fault"),
        [
            ("Simmering.", "its `stamps` answer is not the call's: "),
            (
                '{"contract": 1, "version": "1.0.0"}',
                "its `stamps` answer is not the call's: (?s:.*)declarations",
            ),
            (
                json.dumps(
                    {
                        "contract": 2,
                        "version": "2.0.0",
                        "declarations": "d",
                        "file_rules": "f",
                        "index": None,
                        "stamps": [],
                    }
                ),
                "its `stamps` answer is of contract 2, and the collector speaks 1",
            ),
            (
                json.dumps(
                    {
                        "contract": 1,
                        "version": "1.0.0",
                        "declarations": "d",
                        "file_rules": "f",
                        "index": None,
                        "stamps": [],
                    }
                ),
                "its stamps are not those of the transcripts it was handed, in their"
                " order",
            ),
        ],
    )
    def test_an_answer_that_is_not_the_calls_is_none(
        self, home: Path, said: str, fault: str
    ) -> None:
        with pytest.raises(Unanswered, match=fault):
            self._stamps(_answering(home, said), home)

    def test_a_failed_call_keeps_the_index_for_the_next(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub, listed = _stub(home), transcripts(home / "projects")
        stub.stamps(listed, _inventory())
        records = home / "plugins" / "data" / labeller.DATA / labeller.RECORDS
        kept = records.read_text()
        records.write_text("{")
        with pytest.raises(Unanswered):
            stub.stamps(listed, _inventory())
        records.write_text(kept)
        os.utime(records)
        calls = _calls(monkeypatch)

        stub.stamps(listed, _inventory())

        ((_, request),) = calls
        assert request["index"] is not None
