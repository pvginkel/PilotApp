"""The fake collector (F122.5): the collector's readings route as the
collector answers it, the scenario's readings by the collector's own code,
and its verbs, in process and over HTTP."""

import gzip
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pilot_collection.reading import ReadingSchema
from pilot_scenario import SCENARIO, TALLY, Builder

from app.services.fake_collector import (
    TOO_LARGE,
    FakeAsk,
    FakeCollectorProblem,
    validator,
)
from tests.support.fake_collector import (
    WRITTEN_AT,
    ServedFakeCollector,
    invented_reading,
)
from tests.support.publications import COLLECTOR_TOKEN

MAIN = "4f1c9e2a-7b3d-4a68-9c05-e1d2b3a4f567"
AGENT = "a7c2e9f41b3d5e860"
UNTIL = datetime(2026, 11, 12, 9, 30, tzinfo=UTC)
HEADERS = {"Authorization": f"Bearer {COLLECTOR_TOKEN}", "X-Pilot-Reading-Version": "1"}


@pytest.fixture
def fake() -> Iterator[ServedFakeCollector]:
    served = ServedFakeCollector()
    try:
        yield served
    finally:
        served.close()


@pytest.fixture
def client(fake: ServedFakeCollector) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=fake.url) as http:
        yield http


def _read(client: httpx.Client, path: str) -> ReadingSchema:
    """The reading served at `path`, its body decoded."""
    return ReadingSchema.model_validate_json(
        client.get(f"/readings/{path}", headers=HEADERS).content
    )


class TestRoute:
    def test_it_serves_a_reading_compressed_with_its_validator(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        reading = invented_reading()
        fake.serve(reading)

        with client.stream("GET", f"/readings/{MAIN}", headers=HEADERS) as response:
            body = b"".join(response.iter_raw())

        assert response.status_code == 200
        assert response.headers["Content-Encoding"] == "gzip"
        assert response.headers["ETag"] == '"4096-1794217927123456"'
        assert ReadingSchema.model_validate_json(gzip.decompress(body)) == reading

    def test_the_validator_is_the_files_size_and_time(self) -> None:
        assert validator(invented_reading()) == '"4096-1794217927123456"'

    def test_it_serves_a_sub_agents_reading_by_both_its_ids(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        reading = invented_reading(agent_id=AGENT)
        fake.serve(invented_reading())
        fake.serve(reading)

        response = client.get(f"/readings/{MAIN}/{AGENT}", headers=HEADERS)

        assert response.status_code == 200
        assert ReadingSchema.model_validate_json(response.content) == reading

    def test_a_validator_named_is_answered_not_changed(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        reading = invented_reading()
        fake.serve(reading)

        response = client.get(
            f"/readings/{MAIN}",
            headers={**HEADERS, "If-None-Match": f'W/"1-2", {validator(reading)}'},
        )

        assert (response.status_code, response.content) == (304, b"")
        assert response.headers["ETag"] == validator(reading)

    def test_another_validator_is_answered_with_the_reading(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        fake.serve(invented_reading())

        response = client.get(
            f"/readings/{MAIN}", headers={**HEADERS, "If-None-Match": '"1-2"'}
        )

        assert response.status_code == 200

    def test_ids_it_holds_no_reading_of_are_gone(self, client: httpx.Client) -> None:
        response = client.get(f"/readings/{MAIN}", headers=HEADERS)

        assert response.status_code == 404
        assert response.json() == {
            "error": "The home has no transcript of those ids",
            "code": "TRANSCRIPT_GONE",
        }

    @pytest.mark.parametrize(
        "headers",
        [{}, {"Authorization": "Bearer another"}, {"Authorization": COLLECTOR_TOKEN}],
    )
    def test_an_ask_without_its_bearer_is_refused(
        self, fake: ServedFakeCollector, client: httpx.Client, headers: dict[str, str]
    ) -> None:
        fake.serve(invented_reading())

        response = client.get(
            f"/readings/{MAIN}", headers={"X-Pilot-Reading-Version": "1", **headers}
        )

        assert response.status_code == 401
        assert response.json() == {
            "error": "The call does not carry the collector's bearer"
        }

    @pytest.mark.parametrize("version", [None, "2", "0", "one"])
    def test_an_ask_of_no_version_it_serves_is_refused_with_its_versions(
        self, fake: ServedFakeCollector, client: httpx.Client, version: str | None
    ) -> None:
        fake.serve(invented_reading())
        headers = {"Authorization": HEADERS["Authorization"]}
        if version is not None:
            headers["X-Pilot-Reading-Version"] = version

        response = client.get(f"/readings/{MAIN}", headers=headers)

        assert (response.status_code, response.json()) == (426, {"min": 1, "max": 1})

    def test_it_lists_each_ask_with_the_validator_it_named(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        reading = invented_reading()
        fake.serve(reading)
        client.get(f"/readings/{MAIN}", headers=HEADERS)
        client.get(
            f"/readings/{MAIN}",
            headers={**HEADERS, "If-None-Match": validator(reading)},
        )
        client.get(f"/readings/{MAIN}/{AGENT}", headers=HEADERS)

        assert fake.asks() == [
            FakeAsk(MAIN, None, None, 200),
            FakeAsk(MAIN, None, validator(reading), 304),
            FakeAsk(MAIN, AGENT, None, 404),
        ]


class TestScenario:
    def test_it_serves_each_conversation_of_the_scenario_as_the_collector_reads_its_file(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        builder = Builder(SCENARIO, UNTIL)

        fake.scenario(builder)

        publications = builder.publications()
        for publication in publications:
            ids = [publication["session_id"], publication.get("agent_id")]
            reading = _read(client, "/".join(part for part in ids if part))
            assert [call.message_id for call in reading.calls] == [
                call["message_id"] for call in publication["calls"]
            ]
            assert (reading.file_size, reading.file_modified_at) == (
                publication["file_size"],
                datetime.fromisoformat(publication["file_modified_at"]),
            )
        assert len(publications) == 3

    def test_a_load_takes_the_place_of_the_scenario_before_and_its_refusal(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        fake.scenario(Builder(SCENARIO, UNTIL))
        first = Builder(SCENARIO, UNTIL).publications()[0]
        fake.refuse()

        fake.scenario(Builder(SCENARIO, UNTIL + timedelta(days=1)))

        assert _read(client, first["session_id"]).file_modified_at == (
            datetime.fromisoformat(first["file_modified_at"]) + timedelta(days=1)
        )

    def test_two_loads_before_an_ask_hold_both_scenarios(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        fake.scenario(Builder(SCENARIO, UNTIL))
        fake.scenario(Builder(TALLY, UNTIL))

        for scenario in (SCENARIO, TALLY):
            first = Builder(scenario, UNTIL).publications()[0]
            assert _read(client, first["session_id"]).file_size == first["file_size"]

    def test_a_load_reads_none_of_the_scenario_until_it_is_asked(
        self, fake: ServedFakeCollector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "pilot_collector.reading", None)

        fake.scenario(Builder(SCENARIO, UNTIL))

        with pytest.raises(ImportError):
            fake.gone(MAIN)


class TestVerbs:
    def test_a_transcript_made_gone_is_gone(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        fake.serve(invented_reading())
        fake.serve(invented_reading(agent_id=AGENT))

        fake.gone(MAIN, AGENT)

        assert client.get(f"/readings/{MAIN}/{AGENT}", headers=HEADERS).json()[
            "code"
        ] == ("TRANSCRIPT_GONE")
        assert client.get(f"/readings/{MAIN}", headers=HEADERS).status_code == 200

    def test_a_reading_made_too_large_grows_by_a_persons_line_past_the_readers_answer(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        reading = invented_reading()
        fake.serve(reading)

        fake.too_large(MAIN)
        grown = _read(client, MAIN)

        assert grown.calls == reading.calls
        (line,) = grown.after
        assert (line.kind, line.writer, len(line.text)) == (  # type: ignore[union-attr]
            "user",
            "person",
            TOO_LARGE,
        )
        assert line.at == grown.file_modified_at == WRITTEN_AT + timedelta(seconds=1)
        assert grown.file_size == reading.file_size + TOO_LARGE
        assert TOO_LARGE > 2 * 1024 * 1024

    def test_too_large_takes_how_many_characters(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        fake.serve(invented_reading())

        fake.too_large(MAIN, characters=10)

        assert _read(client, MAIN).file_size == invented_reading().file_size + 10

    def test_too_large_refuses_ids_it_holds_no_reading_of(
        self, fake: ServedFakeCollector
    ) -> None:
        with pytest.raises(FakeCollectorProblem, match="holds no reading of"):
            fake.too_large(MAIN)

    @pytest.mark.parametrize(
        ("refusal", "status"), [("version", 426), ("unreadable", 500)]
    )
    def test_a_refusal_answers_every_ask_until_it_is_lifted(
        self,
        fake: ServedFakeCollector,
        client: httpx.Client,
        refusal: str,
        status: int,
    ) -> None:
        fake.serve(invented_reading())

        fake.refuse(refusal)  # type: ignore[arg-type]
        refused = client.get(f"/readings/{MAIN}", headers=HEADERS)
        gone = client.get(f"/readings/{MAIN}/{AGENT}", headers=HEADERS)
        fake.refuse(None)
        served = client.get(f"/readings/{MAIN}", headers=HEADERS)

        assert (refused.status_code, gone.status_code) == (status, status)
        assert served.status_code == 200

    def test_the_version_refusal_names_a_later_version(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        fake.refuse()

        response = client.get(f"/readings/{MAIN}", headers=HEADERS)

        assert response.json() == {"min": 2, "max": 2}

    def test_reset_forgets_every_reading_ask_and_refusal(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        fake.scenario(Builder(SCENARIO, UNTIL))
        fake.serve(invented_reading())
        client.get(f"/readings/{MAIN}", headers=HEADERS)
        fake.refuse()

        fake.reset()

        assert fake.asks() == []
        response = client.get(f"/readings/{MAIN}", headers=HEADERS)
        assert response.status_code == 404
        assert fake.asks() == [FakeAsk(MAIN, None, None, 404)]

    def test_its_verbs_are_served_over_http(
        self, fake: ServedFakeCollector, client: httpx.Client
    ) -> None:
        reading = invented_reading()

        served = client.post(
            "/fake/serve", json={"reading": reading.model_dump(mode="json")}
        )
        grown = client.post(
            "/fake/too-large", json={"session_id": MAIN, "characters": 10}
        )
        asked = client.get(f"/readings/{MAIN}", headers=HEADERS)
        gone = client.post("/fake/gone", json={"session_id": MAIN})
        refused = client.post("/fake/refuse", json={"refusal": "unreadable"})
        asks = client.post("/fake/asks")
        reset = client.post("/fake/reset")

        assert [served.status_code, grown.status_code] == [204, 204]
        assert ReadingSchema.model_validate_json(asked.content).after[0].at == (
            WRITTEN_AT + timedelta(seconds=1)
        )
        assert [gone.status_code, refused.status_code, reset.status_code] == [
            204,
            204,
            204,
        ]
        assert asks.json() == [
            {"session_id": MAIN, "agent_id": None, "validator": None, "status": 200}
        ]

    def test_a_verb_it_has_not_or_a_body_it_does_not_take_is_refused(
        self, client: httpx.Client
    ) -> None:
        unknown = client.post("/fake/scenario", json={})
        listed = client.post("/fake/refuse", json=["version"])
        wrong = client.post("/fake/refuse", json={"refusal": "silence"})
        missing = client.post("/fake/too-large", json={"session_id": MAIN})

        assert (unknown.status_code, unknown.json()) == (
            404,
            {"error": "the fake has no verb scenario"},
        )
        assert listed.status_code == wrong.status_code == 422
        assert missing.status_code == 404
