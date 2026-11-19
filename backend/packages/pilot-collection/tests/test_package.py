"""The package a collector and Pilot both take: it stands without the app,
and its shapes are the ones Pilot's routes read and answer with."""

import ast
import sys
from pathlib import Path

import pilot_collection
from pilot_collection.inventory import InventorySchema
from pilot_collection.publication import PublicationSchema


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
                    }
                ],
            }
        )

        (held,) = inventory.transcripts
        assert (held.file_size, held.replayed_size) == (2_048, 1_024)
        assert held.file_modified_at.microsecond == 123_456
