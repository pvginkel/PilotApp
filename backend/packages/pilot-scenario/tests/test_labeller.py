"""The stub labeller (F122.5): the labeller's contract 1 as a collector runs
it, its verbs, refusals, exit codes and per-transcript errors, the stamp with
its index, and the appended labelling with its boundary, its checkpoint and
the answer `whole`, over the invented scenario and over files built for a
rule."""

import json
import os
import subprocess
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pilot_scenario import SCENARIO, Builder, labeller

UNTIL = datetime(2026, 11, 12, 9, 30, tzinfo=UTC)
RECIPES = "8766dbc8-267a-5322-9a1d-cc49ad56eedd"
COUNTING = "6d6212072d4d5b429"
RIDES = "037915e7-de88-5550-9746-3e7a4472413a"
STEW = "recipe-box|Scale the recipes|Halve the stew"

LISTS = {
    "work_unit_kind",
    "unit_outcome",
    "rework_kind",
    "unit_measure",
    "segment_kind",
    "wait_cause",
    "call_class",
    "avoidable_kind",
    "batchable_condition",
    "command_class",
    "build_result",
    "file_class",
    "tool_effect_kind",
    "rule",
    "ask_category",
    "event_kind",
    "context_part_kind",
}
"""Every list the labeller declares (`labeller.md` § The vocabularies)."""


def _run(verb: str, request: Any, *options: str) -> tuple[int, list[Any]]:
    """The stub run as a collector runs it: its exit and its answer's
    lines."""
    done = subprocess.run(
        [*labeller.command(*options), verb],
        input=request if isinstance(request, str) else json.dumps(request),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return done.returncode, [json.loads(line) for line in done.stdout.splitlines()]


def _home(root: Path, **given: str) -> dict[str, str]:
    return {
        "projects": str(root / "projects"),
        "plugins": str(root / "plugins"),
    } | given


def _records(root: Path) -> Path:
    return root / "plugins" / "data" / labeller.DATA / labeller.RECORDS


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A home of the scenario's files and the stub's run records."""
    Builder(SCENARIO, UNTIL).write(tmp_path)
    return tmp_path


def _ids(content: bytes) -> list[str]:
    """The message id of each assistant line, in the order of its first."""
    ids: dict[str, None] = {}
    for raw in content.splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if line.get("type") == "assistant":
            ids.setdefault(line["message"]["id"], None)
    return list(ids)


def _item(path: str, content: bytes, agent: str | None = None) -> dict[str, Any]:
    """A transcript as a collector hands it to be labelled whole: a main
    thread's Calls all in one Launch."""
    calls: list[dict[str, Any]] = [
        {"id": each, "position": n} for n, each in enumerate(_ids(content), start=1)
    ]
    if agent is not None:
        return {"agent_id": agent, "path": path, "mode": "whole", "calls": calls}
    return {
        "agent_id": None,
        "path": path,
        "mode": "whole",
        "launches": [{"n": 1, "started_at": "2026-11-12T09:00:00Z"}],
        "calls": [call | {"launch": 1} for call in calls],
    }


def _conversations(root: Path) -> list[dict[str, Any]]:
    """The scenario's conversations as a collector hands them, Pilot holding
    nothing of them."""
    projects = root / "projects"
    recipes = projects / "-work-RecipeBox" / f"{RECIPES}.jsonl"
    counting = (
        projects / "-work-RecipeBox" / RECIPES / "subagents" / f"agent-{COUNTING}.jsonl"
    )
    rides = projects / "-work-BikeLog" / f"{RIDES}.jsonl"

    def item(file: Path, agent: str | None = None) -> dict[str, Any]:
        return _item(str(file.relative_to(projects)), file.read_bytes(), agent)

    return [
        {
            "session_id": RECIPES,
            "sessions": [],
            "documents": [],
            "transcripts": [
                item(counting, COUNTING) | {"agent_type": "Explore"},
                item(recipes),
            ],
        },
        {
            "session_id": RIDES,
            "sessions": [],
            "documents": [],
            "transcripts": [item(rides)],
        },
    ]


def _request(root: Path, **given: Any) -> dict[str, Any]:
    return {
        "contract": 1,
        "home": _home(root),
        "conversations": _conversations(root),
    } | given


class TestTheCommand:
    def test_info_names_the_contract_the_version_and_the_verbs_whatever_it_is_sent(
        self,
    ) -> None:
        assert _run("info", "not a request") == (
            0,
            [
                {
                    "contract": 1,
                    "version": labeller.VERSION,
                    "verbs": ["info", "vocabularies", "stamps", "label", "classes"],
                }
            ],
        )
        assert _run("info", "", "--version", "2.3.1", "--speaks", "2")[1][0] | {
            "verbs": None
        } == {"contract": 2, "version": "2.3.1", "verbs": None}

    @pytest.mark.parametrize(
        ("verb", "request_", "code"),
        [
            pytest.param("stamps", "{not json", "json", id="no JSON"),
            pytest.param("stamps", "[1]", "request", id="no object"),
            pytest.param("cook", "{}", "verb", id="an unknown verb"),
            pytest.param("stamps", {"contract": 1}, "home", id="no home"),
            pytest.param(
                "stamps",
                {"contract": 1, "home": {"projects": "/p"}},
                "home",
                id="no plugins",
            ),
            pytest.param(
                "stamps",
                {"contract": 1, "home": {"projects": "/p", "plugins": "/q"}},
                "request",
                id="no conversations",
            ),
            pytest.param(
                "label",
                {
                    "contract": 1,
                    "home": {"projects": "/p", "plugins": "/q"},
                    "conversations": [
                        {
                            "session_id": RIDES,
                            "transcripts": [
                                {"path": "a.jsonl", "mode": "partly", "calls": []}
                            ],
                        }
                    ],
                },
                "request",
                id="a mode of no labelling",
            ),
            pytest.param(
                "label",
                {
                    "contract": 1,
                    "home": {"projects": "/p", "plugins": "/q"},
                    "conversations": [
                        {
                            "session_id": RIDES,
                            "transcripts": [
                                {"path": "a.jsonl", "mode": "appended", "calls": []}
                            ],
                        }
                    ],
                },
                "request",
                id="an appended transcript with no from",
            ),
            pytest.param(
                "classes",
                {
                    "contract": 1,
                    "home": {"projects": "/p", "plugins": "/q"},
                    "files": [["a"]],
                },
                "request",
                id="a file with no path",
            ),
        ],
    )
    def test_a_request_it_cannot_take_is_refused(
        self, verb: str, request_: Any, code: str
    ) -> None:
        exit_code, (answer,) = _run(verb, request_)

        assert exit_code == 2
        assert answer["error"]["code"] == code
        assert answer["error"]["detail"]

    def test_a_request_of_another_contract_is_refused_with_the_one_it_speaks(
        self, home: Path
    ) -> None:
        assert _run("stamps", _request(home, contract=2)) == (
            2,
            [
                {
                    "error": {
                        "code": "contract",
                        "detail": "contract 2 is not spoken here",
                        "speaks": [1],
                    }
                }
            ],
        )
        exit_code, (answer,) = _run("stamps", _request(home), "--speaks", "2")
        assert (exit_code, answer["error"]["speaks"]) == (2, [2])

    def test_run_records_that_do_not_read_crash_it(self, home: Path) -> None:
        _records(home).write_text("{not json")

        done = subprocess.run(
            [*labeller.command(), "stamps"],
            input=json.dumps(_request(home)),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        assert (done.returncode, done.stdout) == (1, "")
        assert "Traceback" in done.stderr

    def test_it_writes_nothing_on_the_home(self, home: Path) -> None:
        before = {path: path.stat().st_mtime_ns for path in home.rglob("*")}

        for verb in ("vocabularies", "stamps", "label"):
            assert _run(verb, _request(home))[0] == 0

        assert {path: path.stat().st_mtime_ns for path in home.rglob("*")} == before


class TestItsVocabularies:
    def test_every_list_is_declared_each_value_in_its_place(self, home: Path) -> None:
        exit_code, (answer,) = _run("vocabularies", _request(home))

        assert exit_code == 0
        assert (answer["contract"], answer["version"]) == (1, labeller.VERSION)
        assert set(answer["lists"]) == LISTS
        for values in answer["lists"].values():
            assert [value["position"] for value in values] == list(
                range(1, len(values) + 1)
            )
            for value in values:
                assert {"code", "name", "description"} <= set(value)
        assert {
            value["code"]: value["counted"] for value in answer["lists"]["file_class"]
        } == {
            "recipe": True,
            "tasting": True,
            "note": True,
            "menu": True,
            "printout": False,
            "logbook": False,
        }

    def test_the_kinds_of_work_and_their_nestings_are_the_run_records(
        self, home: Path
    ) -> None:
        (answer,) = _run("vocabularies", _request(home))[1]

        assert answer["lists"]["work_unit_kind"] == [
            {
                "code": "errand",
                "name": "Errand",
                "description": "The widest kind of work.",
                "position": 1,
            },
            {
                "code": "leg",
                "name": "Leg",
                "description": "A part of one errand.",
                "position": 2,
            },
        ]
        assert answer["nesting"] == [{"inner": "leg", "outer": "errand"}]
        assert answer["groups"] == [
            {
                "key": "bike-log-first-rides",
                "spec_repo": "BikeLog",
                "name": "Bike log: the first rides",
                "summary": (
                    "The gear tables and ride notes Ada kept by hand, before Pilot"
                    " kept the log."
                ),
                "slices": [],
            }
        ]

    def test_a_home_with_no_run_records_has_no_kind_of_work_and_no_group(
        self, tmp_path: Path
    ) -> None:
        (answer,) = _run("vocabularies", {"contract": 1, "home": _home(tmp_path)})[1]

        assert answer["lists"]["work_unit_kind"] == []
        assert (answer["nesting"], answer["groups"]) == ([], [])

    def test_the_run_records_are_read_in_the_folder_home_data_names(
        self, home: Path, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / labeller.RECORDS).write_text(json.dumps({"kinds": ["chore"]}))

        (answer,) = _run(
            "vocabularies", {"contract": 1, "home": _home(home, data=str(elsewhere))}
        )[1]

        assert [kind["code"] for kind in answer["lists"]["work_unit_kind"]] == ["chore"]

    def test_a_nesting_the_run_records_give_is_declared_as_they_give_it(
        self, tmp_path: Path
    ) -> None:
        nesting = [
            {"inner": "trip", "outer": "errand"},
            {"inner": "leg", "outer": "trip"},
            {"inner": "check", "outer": "errand"},
            {"inner": "check", "outer": "trip"},
        ]
        records = _records(tmp_path)
        records.parent.mkdir(parents=True)
        records.write_text(
            json.dumps(
                {"kinds": ["errand", "trip", "leg", "check"], "nesting": nesting}
            )
        )

        (answer,) = _run("vocabularies", {"contract": 1, "home": _home(tmp_path)})[1]

        assert answer["nesting"] == nesting
        assert [
            (kind["code"], kind["description"], kind["position"])
            for kind in answer["lists"]["work_unit_kind"]
        ] == [
            ("errand", "The widest kind of work.", 1),
            ("trip", "A part of one errand.", 2),
            ("leg", "A part of one trip.", 3),
            ("check", "A part of one errand or trip.", 4),
        ]


def _stamps(home: Path, **given: Any) -> dict[str | None, str | None]:
    """Each transcript's stamp by its agent id, the main threads' by their
    session id."""
    exit_code, (answer,) = _run("stamps", _request(home, **given))
    assert exit_code == 0
    return {
        stamp["agent_id"] or stamp["session_id"]: stamp["stamp"]
        for stamp in answer["stamps"]
    }


def _rewrite(home: Path, change: Any) -> None:
    records = json.loads(_records(home).read_text())
    change(records)
    _records(home).write_text(json.dumps(records))


class TestTheStamps:
    def test_every_transcript_is_stamped_in_request_order_without_reading_one(
        self, home: Path, tmp_path: Path
    ) -> None:
        """The stamp the label line gives, on a home whose transcripts are
        gone."""
        request = _request(home)
        *lines, last = _run("label", request)[1]
        labelled = {
            line["agent_id"] or line["session_id"]: line["stamp"] for line in lines[1:]
        }
        for path in (home / "projects").rglob("*.jsonl"):
            path.unlink()

        exit_code, (answer,) = _run("stamps", request)

        assert exit_code == 0
        assert [(s["session_id"], s["agent_id"]) for s in answer["stamps"]] == [
            (RECIPES, COUNTING),
            (RECIPES, None),
            (RIDES, None),
        ]
        assert {
            s["agent_id"] or s["session_id"]: s["stamp"] for s in answer["stamps"]
        } == (labelled)
        assert all(stamp.startswith("1:") for stamp in labelled.values())
        assert answer["index"] and last["index"]

    def test_what_pilot_hands_with_a_conversation_changes_its_stamps_alone(
        self, home: Path
    ) -> None:
        held = _stamps(home)
        conversations = _conversations(home)
        conversations[1]["sessions"] = [
            {
                "id": "s1",
                "kind": "chat",
                "created_at": "2026-11-12T09:00:00Z",
                "holds": [],
            }
        ]

        now = _stamps(home, conversations=conversations)

        assert now[RIDES] != held[RIDES]
        assert (now[RECIPES], now[COUNTING]) == (held[RECIPES], held[COUNTING])

    def test_a_units_row_changes_the_stamp_of_the_main_thread_that_names_it_alone(
        self, home: Path
    ) -> None:
        held = _stamps(home)

        def retitled(records: dict[str, Any]) -> None:
            records["units"][1]["title"] = "Halve the stew again"

        _rewrite(home, retitled)
        now = _stamps(home)

        assert now[RECIPES] != held[RECIPES]
        assert (now[COUNTING], now[RIDES]) == (held[COUNTING], held[RIDES])

    def test_a_unit_no_transcript_names_changes_no_stamp(self, home: Path) -> None:
        held = _stamps(home)

        def retitled(records: dict[str, Any]) -> None:
            records["units"][2]["title"] = "Halve the dumplings at last"

        _rewrite(home, retitled)

        assert _stamps(home) == held

    def test_a_conversation_a_session_of_pilots_ran_is_adopted_by_no_group(
        self, home: Path
    ) -> None:
        held = _stamps(home)
        pilot = {"conversations": [RIDES]}

        now = _stamps(home, pilot=pilot)
        rides = _run("label", _request(home, pilot=pilot))[1][-2]

        assert now[RIDES] != held[RIDES]
        assert rides["labels"]["transcript"] == [{"adopted_group": None}]
        assert rides["stamp"] == now[RIDES]

    def test_a_transcript_it_cannot_stamp_is_stamped_none_and_the_rest_are_answered(
        self, home: Path
    ) -> None:
        held = _stamps(home)

        def lost(records: dict[str, Any]) -> None:
            records["ran"][RECIPES] = "recipe-box|No such errand"

        _rewrite(home, lost)
        now = _stamps(home)

        assert now[RECIPES] is None
        assert (now[COUNTING], now[RIDES]) == (held[COUNTING], held[RIDES])

    def test_the_declarations_and_the_file_rules_follow_what_they_are_of(
        self, home: Path
    ) -> None:
        def digests() -> tuple[str, str]:
            (answer,) = _run("stamps", _request(home))[1]
            return answer["declarations"], answer["file_rules"]

        declarations, rules = digests()

        def regrouped(records: dict[str, Any]) -> None:
            records["groups"][0]["name"] = "Bike log: the very first rides"

        _rewrite(home, regrouped)
        assert digests()[0] != declarations
        assert digests()[1] == rules

        def ruled(records: dict[str, Any]) -> None:
            records["file_rules"] = {
                "BikeLog": [{"class": "menu", "paths": ["plans/**"]}]
            }

        _rewrite(home, ruled)
        assert digests()[1] != rules
        (answer,) = _run("stamps", _request(home), "--version", "1.3.0")[1]
        assert answer["declarations"] != digests()[0]


def _rewritten_in_place(home: Path) -> None:
    """The run records rewritten in place at their size and their time, a
    unit's title another."""
    stat = _records(home).stat()
    text = _records(home).read_text()
    _records(home).write_text(text.replace("Halve the stew", "Halve the stow"))
    os.utime(_records(home), ns=(stat.st_atime_ns, stat.st_mtime_ns))


class TestTheIndex:
    def test_an_index_whose_records_file_stands_as_it_was_is_taken_for_it(
        self, home: Path
    ) -> None:
        """Keyed by the file's size, time and inode: a file rewritten in
        place at its old size and time reads as the index has it."""
        (first,) = _run("stamps", _request(home))[1]
        _rewritten_in_place(home)

        (taken,) = _run("stamps", _request(home, index=first["index"]))[1]
        (read,) = _run("stamps", _request(home))[1]

        assert taken["stamps"] == first["stamps"]
        assert read["stamps"] != first["stamps"]

    @pytest.mark.parametrize(
        ("index", "options"),
        [
            pytest.param("1:1.0.0:not-base64", (), id="one that does not read"),
            pytest.param(None, ("--version", "2.0.0"), id="one of another major"),
        ],
    )
    def test_an_index_it_cannot_take_is_built_again(
        self, home: Path, index: str | None, options: tuple[str, ...]
    ) -> None:
        (first,) = _run("stamps", _request(home))[1]
        _rewritten_in_place(home)

        (answer,) = _run(
            "stamps", _request(home, index=index or first["index"]), *options
        )[1]

        assert answer["stamps"] != first["stamps"]


class TestALabelAnswer:
    def test_it_streams_a_line_per_transcript_main_threads_first_then_its_end(
        self, home: Path
    ) -> None:
        request = _request(home)

        exit_code, lines = _run("label", request)

        assert exit_code == 0
        head, *transcripts, done = lines
        assert head == {"contract": 1, "version": labeller.VERSION}
        assert [(line["session_id"], line["agent_id"]) for line in transcripts] == [
            (RECIPES, None),
            (RECIPES, COUNTING),
            (RIDES, None),
        ]
        assert done == {"done": True, "count": 3, "index": done["index"]}
        records = json.loads(_records(home).read_text())
        for line, (conversation, transcript) in zip(
            transcripts,
            [
                (
                    request["conversations"][0],
                    request["conversations"][0]["transcripts"][1],
                ),
                (
                    request["conversations"][0],
                    request["conversations"][0]["transcripts"][0],
                ),
                (
                    request["conversations"][1],
                    request["conversations"][1]["transcripts"][0],
                ),
            ],
            strict=True,
        ):
            content = (home / "projects" / transcript["path"]).read_bytes()
            assert line == labeller.label(
                content, transcript, conversation, frozenset(), records
            )

    def test_a_main_threads_labels_name_its_unit_its_group_and_its_documents(
        self, home: Path
    ) -> None:
        conversations = _conversations(home)
        conversations[0]["documents"] = [
            {"id": "d1", "session": "s1", "source_path": "/work/RecipeBox/asks/1.md"},
            {"id": "d2", "session": "s1", "source_path": None},
        ]

        recipes, counting, rides = _run(
            "label", _request(home, conversations=conversations)
        )[1][1:-1]

        assert recipes["labels"]["launches"] == [{"n": 1, "work_unit": STEW}]
        assert recipes["labels"]["transcript"] == [{"adopted_group": None}]
        assert recipes["labels"]["documents"] == [
            {"id": "d1", "ask_category": "menu_question"},
            {"id": "d2", "ask_category": "house_note"},
        ]
        assert [unit["key"] for unit in recipes["units"]] == [
            "recipe-box|Scale the recipes",
            STEW,
        ]
        assert counting["labels"]["transcript"] == counting["labels"]["launches"] == []
        assert counting["labels"]["documents"] == counting["units"] == []
        assert rides["labels"]["transcript"] == [
            {"adopted_group": "bike-log-first-rides"}
        ]

    def test_a_units_test_runs_come_with_it_and_their_suites(self, home: Path) -> None:
        def tasted(records: dict[str, Any]) -> None:
            records["unit_runs"] = [
                {
                    "work_unit": STEW,
                    "suite": "RecipeBox/tasting",
                    "passed": True,
                    "tests": 3,
                },
                {
                    "work_unit": "elsewhere",
                    "suite": "RecipeBox/tasting",
                    "passed": False,
                    "tests": 1,
                },
            ]
            records["suites"] = [
                {"code": "RecipeBox/tasting", "name": "RecipeBox tasting"}
            ]

        _rewrite(home, tasted)
        recipes = _run("label", _request(home))[1][1]

        assert recipes["labels"]["test_runs"] == [
            {
                "work_unit": STEW,
                "suite": "RecipeBox/tasting",
                "passed": True,
                "tests": 3,
            }
        ]
        assert recipes["test_suites"] == [
            {"code": "RecipeBox/tasting", "name": "RecipeBox tasting"}
        ]

    def test_a_transcript_it_cannot_label_fails_alone_and_the_batch_goes_on(
        self, home: Path
    ) -> None:
        conversations = _conversations(home)
        recipes = conversations[0]["transcripts"][1]
        wrong = recipes | {
            "calls": [*recipes["calls"][:3], {"id": "msg_9999", "launch": 1}]
        }
        conversations[0]["transcripts"] = [
            wrong,
            recipes | {"agent_id": "gone", "path": "-work-RecipeBox/gone.jsonl"},
            recipes | {"agent_id": "outside", "path": "../outside.jsonl"},
        ]

        exit_code, lines = _run("label", _request(home, conversations=conversations))

        assert exit_code == 0
        errors = [line.get("error") for line in lines[1:-1]]
        assert errors[:3] == [
            {
                "code": "calls_mismatch",
                "detail": "Call 4: handed 'msg_9999', the file has 'msg_0004'",
            },
            {"code": "unreadable", "detail": errors[1]["detail"]},
            {
                "code": "unreadable",
                "detail": "../outside.jsonl is not under home.projects",
            },
        ]
        assert lines[-2]["answer"] == "labels"
        assert lines[-1]["count"] == 4

    def test_a_rule_that_raises_is_an_internal_error_of_that_transcript(
        self, home: Path
    ) -> None:
        _rewrite(home, lambda records: records["ran"].update({RECIPES: "nowhere"}))

        recipes, counting, rides = _run("label", _request(home))[1][1:-1]

        assert recipes["answer"] == "error"
        assert recipes["error"]["code"] == "internal"
        assert recipes["error"]["detail"].startswith(
            "KeyError: 'nowhere' at labeller.py:"
        )
        assert (counting["answer"], rides["answer"]) == ("labels", "labels")

    def test_a_pause_is_taken_before_each_transcripts_line(self, home: Path) -> None:
        started = time.monotonic()

        assert _run("label", _request(home), "--pause", "0.25")[0] == 0

        assert time.monotonic() - started >= 0.75


def _line(kind: str, **fields: Any) -> dict[str, Any]:
    return {"type": kind, "timestamp": "2026-11-12T09:00:00.000Z", **fields}


def _asked(
    message_id: str, *tools: dict[str, Any], model: str = "claude-opus-4-5"
) -> dict[str, Any]:
    """An assistant line of that message, with those `tool_use` blocks."""
    return _line(
        "assistant",
        message={
            "id": message_id,
            "model": model,
            "content": [{"type": "text", "text": "Stir."}, *tools],
        },
    )


def _tool(tool_use_id: str, name: str = "Read", **given: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": tool_use_id, "name": name, "input": given}


def _result(
    tool_use_id: str, error: bool = False, text: str = "Done."
) -> dict[str, Any]:
    return _line(
        "user",
        message={
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": [{"type": "text", "text": text}],
                    "is_error": error,
                }
            ],
        },
    )


def _said(text: str) -> dict[str, Any]:
    return _line("user", message={"role": "user", "content": text})


def _file(*lines: dict[str, Any]) -> bytes:
    return b"".join(json.dumps(line).encode() + b"\n" for line in lines)


def _whole(content: bytes, records: dict[str, Any] | None = None) -> dict[str, Any]:
    return labeller.label(
        content,
        _item("t.jsonl", content),
        {"session_id": RIDES},
        frozenset(),
        records or {},
    )


def _appended(
    content: bytes,
    held: dict[str, Any],
    records: dict[str, Any] | None = None,
    version: str = labeller.VERSION,
) -> dict[str, Any]:
    """The labels of `content` from the boundary and checkpoint of the
    answer `held`."""
    handed = _item("t.jsonl", content)
    calls = [call["id"] for call in handed["calls"]]
    start = calls.index(held["boundary"]["call"])
    item = handed | {
        "mode": "appended",
        "from": held["boundary"],
        "checkpoint": held["checkpoint"],
        "calls": handed["calls"][start:],
    }
    return labeller.label(
        content, item, {"session_id": RIDES}, frozenset(), records or {}, version
    )


def _merged(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Pilot's merge of a Call's labels and what hangs on it: those before
    the appended answer's first Call kept, the rest the answer's; and the
    Segments before the answer's first, then the answer's."""
    ids = [call["id"] for call in before["labels"]["calls"]]
    kept = set(ids[: ids.index(after["labels"]["calls"][0]["id"])])
    merged = {
        name: [
            row
            for row in before["labels"][name]
            if row.get("call", row.get("id")) in kept
        ]
        + after["labels"][name]
        for name in ("calls", "events", "context_parts")
    }
    start = after["labels"]["segments"][0]["position"]
    merged["segments"] = [
        segment
        for segment in before["labels"]["segments"]
        if segment["position"] < start
    ] + after["labels"]["segments"]
    return merged


def _cuts(content: bytes) -> Iterator[int]:
    """Each byte a Call's first line starts at, past the first Call's."""
    seen: set[str] = set()
    at = 0
    for raw in content.splitlines(keepends=True):
        line = json.loads(raw)
        if line.get("type") == "assistant" and line["message"]["id"] not in seen:
            if seen:
                yield at
            seen.add(line["message"]["id"])
        at += len(raw)


class TestAppendedLabelling:
    @pytest.mark.parametrize(
        "content",
        [
            *(
                pytest.param(file.content, id=file.path.rsplit("/", 1)[-1])
                for file in Builder(SCENARIO, UNTIL).files()
                if file.path.endswith(".jsonl")
            ),
            pytest.param(
                _file(
                    _asked("m1", _tool("t1")),
                    _asked("m2"),
                    _result("t1"),
                    _asked("m3", _tool("t2", "Edit")),
                    _result("t2"),
                    _asked("m4"),
                ),
                id="a result after the next call",
            ),
            pytest.param(
                _file(
                    _asked(
                        "m1", _tool("t1", "Bash", command="x", run_in_background=True)
                    ),
                    _result("t1"),
                    _asked("m2", _tool("t2")),
                    _result("t2"),
                    _said("<task-notification>t1</task-notification>"),
                    _asked("m3"),
                    _asked(
                        "m4", _tool("t3", "Bash", command="y", run_in_background=True)
                    ),
                    _result("t3"),
                    _asked("m5"),
                    _asked("m6"),
                    _asked("m7"),
                    _asked("m8"),
                ),
                id="background commands",
            ),
        ],
    )
    def test_labelled_at_every_cut_and_appended_from_its_boundary_it_is_the_whole(
        self, content: bytes
    ) -> None:
        """The replay: a file labelled whole as it stood just before any of
        its Calls, then on from the boundary and checkpoint that handed back,
        merged as Pilot merges it, is the file labelled whole."""
        whole = _whole(content)
        cuts = list(_cuts(content))
        assert cuts
        for cut in cuts:
            before = _whole(content[:cut])
            after = _appended(content, before)

            assert after["answer"] == "labels", (cut, after)
            merged = _merged(before, after)
            for name in ("calls", "segments", "events", "context_parts"):
                assert merged[name] == whole["labels"][name], (cut, name)
            assert (after["boundary"], after["stamp"]) == (
                whole["boundary"],
                whole["stamp"],
            )

    def test_a_result_that_came_after_the_next_call_holds_the_boundary_at_its_call(
        self,
    ) -> None:
        late = _file(_asked("m1", _tool("t1")), _asked("m2"), _result("t1"))

        assert _whole(late)["boundary"] == {"call": "m1", "byte": 0}
        grown = late + _file(_asked("m3"))
        assert _whole(grown)["boundary"]["call"] == "m3"
        after = _appended(grown, _whole(late))
        assert after["answer"] == "labels"
        assert [call["id"] for call in after["labels"]["calls"]] == ["m1", "m2", "m3"]

    def test_a_background_command_holds_the_boundary_until_its_notification(
        self,
    ) -> None:
        started = _file(
            _asked(
                "m1", _tool("t1", "Bash", command="sleep 60", run_in_background=True)
            ),
            _result("t1", text="Running in the background."),
            _asked("m2"),
            _asked("m3"),
        )
        assert _whole(started)["boundary"]["call"] == "m1"

        notified = started + _file(
            _said(
                "<task-notification><tool-use-id>t1</tool-use-id></task-notification>"
            ),
            _asked("m4"),
        )
        labelled = _whole(notified)

        assert labelled["boundary"]["call"] == "m4"
        assert labelled["labels"]["calls"][-1]["wait_cause"] == "timer"

    def test_a_background_command_no_notification_names_is_let_go_after_three_calls(
        self,
    ) -> None:
        lines = [
            _asked(
                "m1", _tool("t1", "Bash", command="sleep 60", run_in_background=True)
            ),
            _result("t1"),
            _asked("m2"),
            _asked("m3"),
        ]

        assert _whole(_file(*lines))["boundary"]["call"] == "m1"
        assert _whole(_file(*lines, _asked("m4")))["boundary"]["call"] == "m4"

    def test_a_file_with_no_counted_call_hands_back_no_boundary(self) -> None:
        labelled = _whole(_file(_asked("m1", model="<synthetic>")))

        assert (labelled["boundary"], labelled["checkpoint"]) == (None, None)
        assert labelled["labels"]["calls"][0]["segment"] == 1

    def _held(self) -> tuple[bytes, dict[str, Any]]:
        content = _file(_asked("m1", _tool("t1")), _result("t1"), _asked("m2"))
        return content, _whole(content)

    def test_one_from_a_checkpoint_that_does_not_read_is_answered_whole(self) -> None:
        content, held = self._held()

        for checkpoint in (
            "not one",
            held["checkpoint"].replace("1:1.0.0:", "1:2.0.0:"),
        ):
            after = _appended(content, held | {"checkpoint": checkpoint})
            assert after == {
                "session_id": RIDES,
                "agent_id": None,
                "answer": "whole",
                "why": "checkpoint",
            }

    def test_one_under_a_minor_or_a_patch_of_its_major_goes_on(self) -> None:
        content, held = self._held()

        for version in ("1.3.0", "1.0.1"):
            assert _appended(content, held, version=version)["answer"] == "labels"

    def test_one_whose_stamp_now_differs_is_answered_whole(self) -> None:
        content, held = self._held()

        after = _appended(
            content,
            held,
            {
                "groups": [
                    {"key": "g", "name": "G", "summary": "", "conversations": [RIDES]}
                ]
            },
        )

        assert after["why"] == "stamp"

    def test_one_whose_boundary_line_moved_is_answered_whole(self) -> None:
        content, held = self._held()

        after = _appended(_file(_said("An early word.")) + content, held)

        assert after["why"] == "boundary"

    def test_one_whose_calls_do_not_continue_the_checkpoints_is_answered_whole(
        self,
    ) -> None:
        content, held = self._held()
        grown = content + _file(_asked("m3"))
        handed = _item("t.jsonl", grown)
        appended = handed | {
            "mode": "appended",
            "from": held["boundary"],
            "checkpoint": held["checkpoint"],
        }

        for calls in (handed["calls"][2:], handed["calls"][1:2]):
            after = labeller.label(
                grown,
                appended | {"calls": calls},
                {"session_id": RIDES},
                frozenset(),
                {},
            )
            assert after["why"] == "calls"

    def test_a_result_owed_at_the_boundary_that_comes_later_is_behind(self) -> None:
        owing = _file(_asked("m1", _tool("t1")), _asked("m2"))
        held = _whole(owing)
        assert held["boundary"]["call"] == "m2"

        after = _appended(owing + _file(_result("t1"), _asked("m3")), held)

        assert after["why"] == "behind"


class TestItsRules:
    def test_a_tool_calls_command_class_its_effect_and_its_breach(self) -> None:
        labelled = _whole(
            _file(
                _asked(
                    "m1",
                    _tool(
                        "t1", "Bash", command="cd /work && timeout 9 python scale.py"
                    ),
                    _tool("t2", "Bash", command="cat ~/.pantry/token"),
                    _tool("t3", "mcp__larder__place_order", order="o-17"),
                ),
                _result("t1"),
                _result("t2"),
                _result("t3"),
            )
        )

        assert labelled["labels"]["tool_calls"] == [
            {
                "tool_use_id": "t1",
                "command_class": "script",
                "effect_kind": None,
                "effect_subject": None,
                "rules": [],
            },
            {
                "tool_use_id": "t2",
                "command_class": None,
                "effect_kind": None,
                "effect_subject": None,
                "rules": ["no_pantry_token"],
            },
            {
                "tool_use_id": "t3",
                "command_class": None,
                "effect_kind": "order_placed",
                "effect_subject": "o-17",
                "rules": [],
            },
        ]

    def test_a_wait_on_the_oven_gives_its_bakes(self) -> None:
        labelled = _whole(
            _file(
                _asked(
                    "m1", _tool("t1", "Bash", command="watch_oven Bread --hash abc123")
                ),
                _result("t1", text="Bread #12 RISEN\nRolls #3 FLAT\n"),
            )
        )

        assert labelled["labels"]["ci_waits"] == [
            {"tool_use_id": "t1", "job": "Bread", "number": 12},
            {"tool_use_id": "t1", "job": "Rolls", "number": 3},
        ]
        assert [
            (b["job"], b["result"], b["commit"]) for b in labelled["ci_builds"]
        ] == [
            ("Bread", "RISEN", "abc123"),
            ("Rolls", "FLAT", None),
        ]

    def test_a_prompts_recipe_card_is_the_first_calls_context_parts(self) -> None:
        card = "# Recipe card — stew\n\n## Pot (four)\nHalve it.\n\n## Spices\nLess.\n"

        labelled = _whole(_file(_said(card), _asked("m1"), _said(card), _asked("m2")))

        assert labelled["labels"]["context_parts"] == [
            {
                "call": "m1",
                "kind": "recipe_card",
                "name": "Pot",
                "characters": len("## Pot (four)\nHalve it.\n\n"),
            },
            {
                "call": "m1",
                "kind": "recipe_card",
                "name": "Spices",
                "characters": len("## Spices\nLess.\n"),
            },
        ]
        assert [call["wait_cause"] for call in labelled["labels"]["calls"]] == [
            "lighting",
            "guest",
        ]


class TestTheClasses:
    def _classes(self, root: Path, *files: list[str]) -> dict[str, Any]:
        exit_code, (answer,) = _run(
            "classes", {"contract": 1, "home": _home(root), "files": list(files)}
        )
        assert exit_code == 0
        classed: dict[str, Any] = answer
        return classed

    def test_a_file_is_classed_by_the_first_starting_rule_that_names_it(
        self, home: Path
    ) -> None:
        answer = self._classes(
            home,
            ["RecipeBox", "uv.lock"],
            ["RecipeBox", "printed/menu.md"],
            ["RecipeBox", "tests/scale.py"],
            ["RecipeBox", "app/test_scale.py"],
            ["RecipeBox", "recipes/stew.md"],
            ["RecipeBox", "README"],
            ["RecipeBox", "scale.py"],
        )

        assert answer["classes"] == [
            "printout",
            "printout",
            "tasting",
            "tasting",
            "note",
            "note",
            "recipe",
        ]
        assert (answer["contract"], answer["version"]) == (1, labeller.VERSION)

    def test_a_repositorys_own_rules_come_first_and_one_it_cannot_use_is_skipped(
        self, home: Path
    ) -> None:
        plain = self._classes(home)["file_rules"]

        def ruled(records: dict[str, Any]) -> None:
            records["file_rules"] = {
                "RecipeBox": [
                    {"class": "boiled", "paths": ["**"]},
                    {"class": "logbook", "paths": []},
                    {"class": "menu", "paths": ["menus/**", "/plans/*.md"]},
                ]
            }

        _rewrite(home, ruled)
        answer = self._classes(
            home,
            ["RecipeBox", "menus/week.md"],
            ["RecipeBox", "plans/june.md"],
            ["RecipeBox", "notes/plans/june.md"],
            ["BikeLog", "menus/week.md"],
        )

        assert answer["classes"] == ["menu", "menu", "note", "note"]
        assert answer["file_rules"] != plain
