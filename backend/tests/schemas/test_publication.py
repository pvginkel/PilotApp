"""The shape of a collector's publication: what a call must hold before
Pilot reads it (F152.3; DB 389, 547)."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.publication import PublicationSchema
from tests.support.publications import call, compaction, hook_run, launch, prompt, whole
from tests.support.transcripts import CAMP, STARTED


def _refused(**overrides: Any) -> list[tuple[Any, ...]]:
    """Where the call with those overrides fails."""
    with pytest.raises(ValidationError) as refused:
        whole(**overrides)
    return [error["loc"] for error in refused.value.errors()]


class TestPublicationSchema:
    def test_a_call_with_the_files_facts_alone_is_a_main_threads(self) -> None:
        publication = whole()

        assert (publication.session_id, publication.agent_id) == (CAMP, None)
        assert publication.file_modified_at.utcoffset() is not None
        assert (publication.launches, publication.compactions, publication.calls) == (
            [],
            [],
            [],
        )
        assert (publication.repository, publication.environment) == (None, None)

    def test_a_call_carries_every_part(self) -> None:
        publication = whole(
            launches=[launch(prompts=[prompt(hook_runs=[hook_run()])])],
            compactions=[compaction()],
            calls=[call(1, prompt=1, compaction=1)],
        )

        ran = publication.launches[0]
        assert ran.started_at == STARTED
        assert ran.ended_at is None
        assert ran.prompts[0].hook_runs[0].command == "signal_activity.sh"
        assert publication.calls[0].tokens == {
            "input": 1_204,
            "cache_write_1h": 3_310,
            "cache_read": 48_112,
            "output": 2_870,
        }

    @pytest.mark.parametrize(
        "missing",
        [
            "session_id",
            "file_size",
            "file_modified_at",
            "collector",
            "working_directory",
        ],
    )
    def test_the_transcripts_own_facts_are_required(self, missing: str) -> None:
        values = whole().model_dump(mode="json", exclude_unset=True)
        del values[missing]

        with pytest.raises(ValidationError) as refused:
            PublicationSchema.model_validate(values)

        assert [error["loc"] for error in refused.value.errors()] == [(missing,)]

    def test_a_field_pilot_does_not_take_is_refused(self) -> None:
        assert _refused(transcript="the words of the conversation") == [("transcript",)]
        assert _refused(calls=[call(1, text="Scale the recipe")]) == [
            ("calls", 0, "text")
        ]

    def test_a_launch_runs_with_a_version(self) -> None:
        """DB 389."""
        assert _refused(launches=[launch(components=[])]) == [
            ("launches", 0, "components")
        ]

    def test_a_calls_tokens_are_of_a_kind_nothing_is_within(self) -> None:
        """DB 547: `cache_write` has the five-minute and the one-hour kinds
        within it."""
        assert _refused(calls=[call(1, tokens={"cache_write": 3_310})]) == [
            ("calls", 0, "tokens", "cache_write", "[key]")
        ]

    def test_a_time_names_its_offset(self) -> None:
        assert _refused(file_modified_at="2026-11-12T09:42:00") == [
            ("file_modified_at",)
        ]

    @pytest.mark.parametrize(
        ("overrides", "where"),
        [
            ({"file_size": -1}, ("file_size",)),
            (
                {"calls": [call(1, tokens={"output": -1})]},
                ("calls", 0, "tokens", "output"),
            ),
            (
                {"calls": [call(1, tokens={"output": 2_147_483_648})]},
                ("calls", 0, "tokens", "output"),
            ),
            ({"calls": [call(1, prompt=0)]}, ("calls", 0, "prompt")),
            ({"calls": [call(1, compaction=0)]}, ("calls", 0, "compaction")),
            (
                {"launches": [launch(prompts=[prompt(characters=-1)])]},
                ("launches", 0, "prompts", 0, "characters"),
            ),
            (
                {"compactions": [compaction(tokens_before=-1)]},
                ("compactions", 0, "tokens_before"),
            ),
        ],
    )
    def test_a_count_is_one_the_record_holds(
        self, overrides: dict[str, Any], where: tuple[Any, ...]
    ) -> None:
        assert _refused(**overrides) == [where]

    @pytest.mark.parametrize(
        ("overrides", "where"),
        [
            ({"session_id": ""}, ("session_id",)),
            ({"agent_id": ""}, ("agent_id",)),
            ({"repository": ""}, ("repository",)),
            ({"environment": ""}, ("environment",)),
            ({"collector": {"version": ""}}, ("collector", "version")),
            ({"calls": [call(1, message_id="")]}, ("calls", 0, "message_id")),
            ({"calls": [call(1, model="")]}, ("calls", 0, "model")),
        ],
    )
    def test_a_name_is_not_empty(
        self, overrides: dict[str, Any], where: tuple[Any, ...]
    ) -> None:
        assert _refused(**overrides) == [where]
