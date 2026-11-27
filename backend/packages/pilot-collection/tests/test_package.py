"""The package a collector and Pilot both take: it stands without the app,
and its shapes are the ones Pilot's routes read and answer with."""

import ast
import sys
from pathlib import Path
from typing import Any

import pilot_collection
import pytest
from pilot_collection.files import FileClassesSchema, FilesQuerySchema, FilesSchema
from pilot_collection.inventory import InventorySchema
from pilot_collection.publication import PublicationSchema
from pilot_collection.reading import ReadingSchema, ToolCallBlockSchema
from pilot_collection.repositories import RepositoriesSchema, RepositoryReadSchema
from pilot_collection.vocabularies import VocabulariesSchema
from pydantic import ValidationError


class TestThePackage:
    def test_it_imports_nothing_but_pydantic_and_the_standard_library(self) -> None:
        source = Path(pilot_collection.__file__).parent
        imported: set[str] = set()
        for module in source.glob("*.py"):
            for node in ast.walk(ast.parse(module.read_text())):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    assert node.module is not None
                    imported.add(node.module.split(".")[0])

        assert {"pilot_collection", "pydantic"} <= imported
        assert imported - {"pilot_collection", "pydantic"} <= sys.stdlib_module_names

    def test_a_publication_is_read_by_its_shape_alone(self) -> None:
        publication = PublicationSchema.model_validate(
            {
                "session_id": "5e7f9a10-1c2d-4e3f-8a4b-6c7d8e9f0a1b",
                "file_size": 2_048,
                "file_modified_at": "2026-11-12T09:30:00Z",
                "collector": {"version": "1.0.0"},
                "working_directory": "/work/RecipeBox",
            }
        )

        assert publication.agent_id is None
        assert publication.calls == []

    def test_the_inventory_is_read_by_the_shape_pilot_answers_with(self) -> None:
        inventory = InventorySchema.model_validate(
            {
                "walk_interval_seconds": 30.0,
                "settling_seconds": 600.0,
                "transcripts": [
                    {
                        "session_id": "5e7f9a10-1c2d-4e3f-8a4b-6c7d8e9f0a1b",
                        "agent_id": None,
                        "file_size": 2_048,
                        "file_modified_at": "2026-11-12T09:30:00.123456Z",
                        "replayed_size": 1_024,
                        "collector": "1.0.0",
                        "labeller": "1.2.0",
                        "stamp": "1:Qm9hdHMgb24gdGhlIGxha2U",
                    }
                ],
                "conversations": [
                    {
                        "session_id": "5e7f9a10-1c2d-4e3f-8a4b-6c7d8e9f0a1b",
                        "sessions": [
                            {
                                "id": "0b6f3c2a-8d41-4e7a-9c15-2f8e6d4a7b30",
                                "kind": "work",
                                "created_at": "2026-11-12T09:00:00Z",
                                "brief": "Survey the lake.",
                                "repo": "example/Camp",
                                "clarification": False,
                                "holds": [
                                    {
                                        "kind": "slot",
                                        "started_at": "2026-11-12T09:00:01Z",
                                        "ended_at": None,
                                    }
                                ],
                                "turns": [
                                    {
                                        "started_at": "2026-11-12T09:00:05Z",
                                        "cause": "brief",
                                    }
                                ],
                            }
                        ],
                        "documents": [
                            {
                                "id": "e2d9a7c4-5b13-4f60-8a2e-9c7b1d4f6a08",
                                "session": "0b6f3c2a-8d41-4e7a-9c15-2f8e6d4a7b30",
                                "source_path": "/work/Camp/docs/survey.md",
                            }
                        ],
                    }
                ],
            }
        )

        (held,) = inventory.transcripts
        assert (held.file_size, held.replayed_size) == (2_048, 1_024)
        assert held.file_modified_at.microsecond == 123_456
        assert (held.labeller, held.stamp) == ("1.2.0", "1:Qm9hdHMgb24gdGhlIGxha2U")
        ((run,), (document,)) = (
            inventory.conversations[0].sessions,
            inventory.conversations[0].documents,
        )
        assert (run.holds[0].ended_at, run.turns[0].cause) == (None, "brief")
        assert document.session == run.id

    def test_the_vocabularies_are_read_by_the_shape_a_collector_declares(
        self,
    ) -> None:
        def listed(*codes: str, **facts: Any) -> list[dict[str, Any]]:
            return [
                {"code": code, "name": code, "description": code, "position": place}
                | facts
                for place, code in enumerate(codes, start=1)
            ]

        vocabularies = VocabulariesSchema.model_validate(
            {
                "version": "1.0.1",
                "lists": {
                    "work_unit_kind": listed("tour", "leg"),
                    "unit_outcome": listed("arrived"),
                    "rework_kind": listed("detour"),
                    "unit_measure": listed("stops", unit="stops"),
                    "segment_kind": listed("drive", "rest"),
                    "wait_cause": listed("ferry"),
                    "call_class": listed("steer"),
                    "avoidable_kind": listed("wrong_turn"),
                    "command_class": listed("refuel"),
                    "build_result": listed("ARRIVED"),
                    "file_class": listed("map", counted=True),
                    "tool_effect_kind": listed("postcard_sent"),
                    "rule": listed("no_speeding", home="/road/RULES.md"),
                    "ask_category": listed("route_question"),
                    "event_kind": listed("flat_tyre", is_error=True),
                    "context_part_kind": listed("road_sign"),
                },
                "nesting": [{"inner": "leg", "outer": "tour"}],
            }
        )

        assert [kind.position for kind in vocabularies.lists.work_unit_kind] == [1, 2]
        assert vocabularies.lists.file_class[0].counted is True
        assert vocabularies.lists.event_kind[0].is_error is True
        assert (vocabularies.nesting[0].inner, vocabularies.nesting[0].outer) == (
            "leg",
            "tour",
        )

    def test_a_reading_is_read_by_the_shape_a_collector_serves(self) -> None:
        at = "2026-11-12T09:30:04.250Z"
        asked = {
            "kind": "tool_call",
            "at": at,
            "tool_use_id": "toolu_0001",
            "tool": "Read",
            "input": {"file_path": "/work/RecipeBox/stew.md"},
            "started": None,
            "result": {
                "at": at,
                "error": False,
                "text": "Two onions.",
                "images": [{"media_type": "image/png", "size": 4_096}],
            },
        }
        reading = ReadingSchema.model_validate(
            {
                "session_id": "5e7f9a10-1c2d-4e3f-8a4b-6c7d8e9f0a1b",
                "agent_id": None,
                "file_size": 2_048,
                "file_modified_at": "2026-11-12T09:30:00.123456Z",
                "calls": [
                    {
                        "message_id": "msg_0001",
                        "received": [
                            {
                                "kind": "user",
                                "at": at,
                                "writer": "brief",
                                "text": "Halve the stew.",
                            },
                            {
                                "kind": "image",
                                "at": at,
                                "media_type": "image/jpeg",
                                "size": 12,
                            },
                        ],
                        "sent": [
                            {"kind": "thinking", "at": at, "text": ""},
                            {"kind": "text", "at": at, "text": "Reading it."},
                            asked,
                        ],
                    }
                ],
                "after": [
                    {"kind": "synthetic", "at": at, "text": "No response requested."},
                    {
                        "kind": "attachment",
                        "at": at,
                        "type": "date_change",
                        "text": '{"newDate": "2026-11-13"}',
                    },
                    {
                        "kind": "system",
                        "at": at,
                        "subtype": "turn_duration",
                        "text": None,
                    },
                    {
                        "kind": "tool_result",
                        "at": at,
                        "tool_use_id": "toolu_0000",
                        "error": True,
                        "text": "Too late.",
                        "images": [],
                    },
                ],
            }
        )

        (call,) = reading.calls
        assert [block.kind for block in call.received] == ["user", "image"]
        assert isinstance(call.sent[2], ToolCallBlockSchema)
        assert call.sent[2].result is not None
        assert call.sent[2].result.images[0].size == 4_096
        assert [block.kind for block in reading.after] == [
            "synthetic",
            "attachment",
            "system",
            "tool_result",
        ]

    def test_a_reading_takes_no_field_its_shape_does_not_name(self) -> None:
        reading: dict[str, Any] = {
            "session_id": "5e7f9a10-1c2d-4e3f-8a4b-6c7d8e9f0a1b",
            "agent_id": None,
            "file_size": 2_048,
            "file_modified_at": "2026-11-12T09:30:00Z",
            "calls": [],
            "after": [],
        }

        ReadingSchema.model_validate(reading)
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ReadingSchema.model_validate(reading | {"lines": []})

    def test_the_repositories_are_read_by_the_shape_pilot_answers_with(self) -> None:
        whole = "3f9a2c1e7b04d6a51c8f2930d4e6b7a8c9d0e1f2"

        held = RepositoriesSchema.model_validate(
            {"repositories": [{"name": "RecipeBox", "read": [whole]}]}
        )

        assert held.repositories[0].read == [whole]

    @pytest.mark.parametrize(
        "sha",
        ["3f9a2c1", "3F9A2C1E7B04D6A51C8F2930D4E6B7A8C9D0E1F2", "3f9a2c1e" * 6],
        ids=["abbreviated", "in capitals", "of neither length"],
    )
    def test_a_read_takes_a_whole_hash_alone(self, sha: str) -> None:
        read: dict[str, Any] = {
            "repository": "RecipeBox",
            "read_at": "2026-11-13T09:30:00Z",
            "commits": [
                {
                    "sha": "3f9a2c1e7b04d6a51c8f2930d4e6b7a8c9d0e1f2",
                    "made_at": "2026-11-12T09:31:00Z",
                    "subject": "Scale the stew for six",
                    "files": [
                        {
                            "path": "recipes/stew.md",
                            "lines_added": 12,
                            "lines_removed": 2,
                        }
                    ],
                }
            ],
        }

        assert (
            RepositoryReadSchema.model_validate(read).commits[0].files[0].lines_added
            == 12
        )
        read["commits"][0]["sha"] = sha
        with pytest.raises(ValidationError, match="String should match pattern"):
            RepositoryReadSchema.model_validate(read)

    def test_the_files_and_their_classes_are_read_by_their_shapes(self) -> None:
        files = FilesSchema.model_validate(
            {"files": [{"repository": "RecipeBox", "path": "recipes/stew.md"}]}
        )
        classes = FileClassesSchema.model_validate(
            {
                "classes": [
                    {
                        "repository": "RecipeBox",
                        "path": "recipes/stew.md",
                        "file_class": "recipe",
                    }
                ]
            }
        )

        assert files.files[0].path == classes.classes[0].path
        assert FilesQuerySchema.model_validate({}).unclassed is False
