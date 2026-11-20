"""The Prices, loaded from the price file, a Model priced as another, and a
Call's cost (DB §2.7, §2.11, 548; F152.12). The suite's database holds the
price file's rows, loaded as a deploy loads them."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pilot_scenario import SCENARIO, Builder
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.exceptions import InvalidOperationException
from app.models import Call, Model, Price, Transcript
from app.models.call import PRICED_KINDS
from app.services.container import ServiceContainer
from app.services.price_service import (
    FilePrice,
    PriceLoad,
    PriceService,
    costs,
    family,
    price_as_family,
    priced_as,
    read_price_file,
)
from tests.support import transcripts
from tests.support.transcripts import STARTED

PANTRY = "claude-pantry-2"
"""An invented model, of a family the price file knows nothing of."""
OLDER = "claude-pantry-1-5"
LARDER = "claude-larder-1"
"""An invented model of another family."""
FROM = datetime(2026, 1, 1, tzinfo=UTC)
"""When the invented rates apply from."""
RATES = {
    "input": "3",
    "cache_write_5m": "3.75",
    "cache_write_1h": "6",
    "cache_read": "0.3",
    "output": "15",
}
"""An invented model's rates."""
TOKENS = {
    "input_tokens": 1_000,
    "cache_write_5m_tokens": 2_000,
    "cache_write_1h_tokens": 3_000,
    "cache_read_tokens": 40_000,
    "output_tokens": 500,
}
COST = Decimal("0.048")
"""What `TOKENS` cost at `RATES`: 3,000 + 7,500 + 18,000 + 12,000 + 7,500
millionths of a dollar."""


def _row(
    model: str = PANTRY,
    kind: str = "input",
    rate: str = "3",
    above_context: int | None = None,
    effective_at: datetime = FROM,
) -> FilePrice:
    return FilePrice(model, kind, above_context, Decimal(rate), effective_at)


def _rows(model: str = PANTRY, **overrides: Any) -> list[FilePrice]:
    """The invented model's base rate for every kind."""
    return [_row(model, kind, rate, **overrides) for kind, rate in RATES.items()]


def _given(**overrides: Any) -> dict[str, Any]:
    """A Call as `costs` takes one."""
    values: dict[str, Any] = {
        "id": 1,
        "model_code": PANTRY,
        "completed_at": STARTED,
        **TOKENS,
    }
    return values | overrides


def _cost(db: DbSession, **overrides: Any) -> Decimal | None:
    return costs(db, [_given(**overrides)])[1]


def _stored_costs(db: DbSession) -> list[Decimal | None]:
    """The cost of each Call stored, in their order."""
    return list(db.scalars(select(Call.cost).order_by(Call.id)))


def _priced_as(db: DbSession, code: str) -> str | None:
    return db.scalars(select(Model.priced_as_code).where(Model.code == code)).one()


@pytest.fixture
def prices(container: ServiceContainer) -> PriceService:
    return container.price_service()


@pytest.fixture
def pantry(prices: PriceService) -> None:
    """The invented model, priced."""
    prices.load(_rows())


@pytest.fixture
def thread(session: DbSession) -> Transcript:
    return transcripts.transcript(session, transcripts.component_version(session))


class TestThePriceFile:
    def test_each_row_is_a_rate_for_a_kind_a_price_is_of(self) -> None:
        rows = read_price_file()

        assert rows
        assert {row.token_kind for row in rows} == set(PRICED_KINDS)
        assert all(row.rate > 0 for row in rows)
        assert all(row.model.startswith("claude-") for row in rows)

    def test_no_two_rows_are_one_price(self) -> None:
        keys = [row.key for row in read_price_file()]

        assert len(set(keys)) == len(keys)

    def test_each_model_has_a_base_rate_for_every_kind(self) -> None:
        rows = read_price_file()
        base = {(row.model, row.token_kind) for row in rows if not row.above_context}

        assert base == {(row.model, kind) for row in rows for kind in PRICED_KINDS}

    def test_every_row_applies_from_before_any_record(self) -> None:
        assert {row.effective_at for row in read_price_file()} == {
            datetime(2025, 1, 1, tzinfo=UTC)
        }

    @pytest.mark.parametrize(
        ("model", "above_context", "rates"),
        [
            ("claude-fable-5-2", None, ["8", "10", "16", "0.2", "40"]),
            ("claude-fable-5", None, ["10", "12.5", "20", "1", "50"]),
            ("claude-opus-5-5", None, ["4", "5", "8", "0.2", "20"]),
            ("claude-opus-4-5", None, ["5", "6.25", "10", "0.5", "25"]),
            ("claude-sonnet-5-5", None, ["2", "2.5", "4", "0.1", "10"]),
            ("claude-haiku-5-5", None, ["0.1", "0.125", "0.2", "0.01", "0.5"]),
            ("claude-haiku-5-5", 100_001, ["0.5", "0.625", "1", "0.05", "2.5"]),
            ("claude-haiku-4-5-20251001", None, ["1", "1.25", "2", "0.1", "5"]),
        ],
    )
    def test_a_models_rates_are_its_public_ones(
        self, model: str, above_context: int | None, rates: list[str]
    ) -> None:
        held = {
            row.token_kind: row.rate
            for row in read_price_file()
            if (row.model, row.above_context) == (model, above_context)
        }

        assert held == dict(zip(PRICED_KINDS, map(Decimal, rates), strict=True))

    def test_it_names_every_model_the_scenarios_calls_use(self) -> None:
        used = {
            call["model"]
            for publication in Builder(SCENARIO, STARTED).publications()
            for call in publication["calls"]
        }

        assert used
        assert used <= {row.model for row in read_price_file()}

    def test_a_row_is_read_with_its_date_at_midnight_utc_and_a_comment_is_none(
        self, tmp_path: Path
    ) -> None:
        file = tmp_path / "prices.csv"
        file.write_text(
            "# An invented list.\n"
            "model,token_kind,above_context,rate,effective_from\n"
            f"{PANTRY},input,,3,2026-01-01\n"
            "# A higher rate over 100,000 tokens of context.\n"
            f"{PANTRY},input,100001,6.5,2026-03-01\n"
        )

        assert read_price_file(file) == [
            FilePrice(PANTRY, "input", None, Decimal("3"), FROM),
            FilePrice(
                PANTRY,
                "input",
                100_001,
                Decimal("6.5"),
                datetime(2026, 3, 1, tzinfo=UTC),
            ),
        ]


class TestPricedAs:
    KNOWN = (
        "claude-opus-5-5",
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-fable-5",
        "claude-fable-5-1",
        "claude-fable-5-2",
        "claude-haiku-5-5",
        "claude-haiku-4-5",
        "claude-haiku-4-5-20251001",
    )

    @pytest.mark.parametrize(
        ("code", "lender"),
        [
            ("claude-opus-6", "claude-opus-5-5"),
            ("claude-opus-4-1", "claude-opus-5-5"),
            ("claude-fable-6-1", "claude-fable-5-2"),
            ("claude-haiku-3", "claude-haiku-5-5"),
        ],
    )
    def test_a_model_takes_the_newest_of_its_family(
        self, code: str, lender: str
    ) -> None:
        assert priced_as(code, self.KNOWN) == lender

    def test_a_dated_snapshot_takes_the_model_it_is_of(self) -> None:
        assert priced_as("claude-opus-4-8-20260301", self.KNOWN) == "claude-opus-4-8"

    def test_a_snapshot_of_a_model_the_prices_do_not_know_takes_its_familys_newest(
        self,
    ) -> None:
        assert priced_as("claude-opus-6-20270101", self.KNOWN) == "claude-opus-5-5"

    def test_of_a_model_and_its_snapshot_the_model_is_the_newest(self) -> None:
        known = ("claude-haiku-4-5-20251001", "claude-haiku-4-5")

        assert priced_as("claude-haiku-3", known) == "claude-haiku-4-5"

    @pytest.mark.parametrize("code", ["claude-pantry-1", "pantry-opus-6", "claude"])
    def test_a_model_of_a_family_the_prices_do_not_know_takes_none(
        self, code: str
    ) -> None:
        assert priced_as(code, self.KNOWN) is None

    def test_a_family_is_the_word_after_claude(self) -> None:
        assert family("claude-opus-5-5") == "opus"
        assert family("claude-haiku-4-5-20251001") == "haiku"
        assert family("pantry-opus-1") is None


class TestPriceAsFamily:
    def test_a_model_with_no_price_is_given_its_familys_newest(
        self, session: DbSession, prices: PriceService
    ) -> None:
        prices.load(_rows(OLDER) + _rows(PANTRY))
        transcripts.reference(session, Model, "claude-pantry-3")

        assert price_as_family(session, ["claude-pantry-3"]) == ["claude-pantry-3"]
        assert _priced_as(session, "claude-pantry-3") == PANTRY

    def test_a_model_with_a_price_of_its_own_is_given_none(
        self, session: DbSession, pantry: None
    ) -> None:
        assert price_as_family(session, [PANTRY]) == []
        assert _priced_as(session, PANTRY) is None

    def test_a_model_priced_as_one_keeps_it_when_a_newer_one_is_known(
        self, session: DbSession, prices: PriceService
    ) -> None:
        prices.load(_rows(OLDER))
        transcripts.reference(session, Model, "claude-pantry-3")
        price_as_family(session)
        prices.load(_rows(PANTRY))

        assert price_as_family(session) == []
        assert _priced_as(session, "claude-pantry-3") == OLDER

    def test_a_model_of_a_family_the_prices_do_not_know_is_given_none(
        self, session: DbSession
    ) -> None:
        transcripts.reference(session, Model, LARDER)

        assert price_as_family(session, [LARDER]) == []
        assert _priced_as(session, LARDER) is None

    def test_only_the_models_named_are_given_one(
        self, session: DbSession, pantry: None
    ) -> None:
        transcripts.reference(session, Model, "claude-pantry-3")
        transcripts.reference(session, Model, "claude-pantry-4")

        assert price_as_family(session, ["claude-pantry-4"]) == ["claude-pantry-4"]
        assert _priced_as(session, "claude-pantry-3") is None

    def test_every_model_waiting_is_given_one_where_none_is_named(
        self, session: DbSession, pantry: None
    ) -> None:
        transcripts.reference(session, Model, "claude-pantry-3")
        transcripts.reference(session, Model, "claude-pantry-4")

        assert price_as_family(session) == ["claude-pantry-3", "claude-pantry-4"]


class TestCosts:
    def test_a_call_costs_its_tokens_of_each_kind_at_that_kinds_rate(
        self, session: DbSession, pantry: None
    ) -> None:
        assert _cost(session) == COST

    def test_each_call_given_is_priced_by_its_id(
        self, session: DbSession, pantry: None
    ) -> None:
        assert costs(
            session,
            [
                _given(),
                _given(id=2, output_tokens=1_500),
                _given(id=3, model_code="claude-opus-5-5", **dict.fromkeys(TOKENS, 0))
                | {"input_tokens": 1_000_000},
            ],
        ) == {1: COST, 2: Decimal("0.063"), 3: Decimal("4")}

    def test_no_call_given_costs_nothing_to_ask(self, session: DbSession) -> None:
        assert costs(session, []) == {}

    def test_a_call_at_a_rates_context_size_is_priced_at_that_rate(
        self, session: DbSession, pantry: None, prices: PriceService
    ) -> None:
        prices.load([_row(rate="6", above_context=46_001)])

        # `TOKENS` carry 46,000 tokens of context.
        assert _cost(session) == COST
        assert _cost(session, input_tokens=1_001) == COST + Decimal("0.003006")

    def test_a_call_is_priced_at_the_highest_context_size_it_reaches(
        self, session: DbSession, pantry: None, prices: PriceService
    ) -> None:
        prices.load(
            [
                _row(rate="6", above_context=10_000),
                _row(rate="9", above_context=40_000),
                _row(rate="12", above_context=90_000),
            ]
        )

        assert _cost(session) == COST + Decimal("0.006")

    def test_a_kind_with_no_rate_at_a_context_size_keeps_its_base_rate(
        self, session: DbSession, pantry: None, prices: PriceService
    ) -> None:
        prices.load([_row(kind="output", rate="30", above_context=10_000)])

        assert _cost(session) == COST + Decimal("0.0075")

    def test_a_call_is_priced_at_the_rate_in_force_when_it_completed(
        self, session: DbSession, pantry: None, prices: PriceService
    ) -> None:
        later = STARTED + timedelta(days=30)
        prices.load([_row(kind="output", rate="30", effective_at=later)])

        assert _cost(session, completed_at=later - timedelta(seconds=1)) == COST
        assert _cost(session, completed_at=later) == COST + Decimal("0.0075")

    def test_a_call_from_before_a_models_first_price_has_no_cost(
        self, session: DbSession, pantry: None
    ) -> None:
        assert _cost(session, completed_at=FROM - timedelta(seconds=1)) is None

    def test_a_call_of_a_model_priced_as_another_is_priced_at_that_ones_rates(
        self, session: DbSession, pantry: None
    ) -> None:
        transcripts.reference(session, Model, "claude-pantry-3", priced_as_code=PANTRY)

        assert _cost(session, model_code="claude-pantry-3") == COST

    def test_a_call_with_tokens_of_a_kind_no_price_covers_has_no_cost(
        self, session: DbSession, prices: PriceService
    ) -> None:
        prices.load([row for row in _rows() if row.token_kind != "cache_write_1h"])

        assert _cost(session) is None

    def test_a_call_with_no_tokens_of_the_kind_no_price_covers_has_its_cost(
        self, session: DbSession, prices: PriceService
    ) -> None:
        prices.load([row for row in _rows() if row.token_kind != "cache_write_1h"])

        assert _cost(session, cache_write_1h_tokens=0) == COST - Decimal("0.018")

    def test_a_call_of_a_model_with_no_price_has_no_cost(
        self, session: DbSession
    ) -> None:
        transcripts.reference(session, Model, LARDER)

        assert _cost(session, model_code=LARDER) is None

    def test_a_call_with_no_tokens_costs_nothing(self, session: DbSession) -> None:
        transcripts.reference(session, Model, LARDER)

        assert _cost(session, model_code=LARDER, **dict.fromkeys(TOKENS, 0)) == 0


class TestLoad:
    def test_the_suites_database_holds_the_price_file(self, session: DbSession) -> None:
        held = session.execute(
            select(
                Price.model_code,
                Price.token_kind_code,
                Price.above_context,
                Price.effective_at,
                Price.rate,
            )
        ).all()

        rows = read_price_file()
        assert len(held) == len(rows)
        assert {tuple(price) for price in held} == {
            (*row.key, row.rate) for row in rows
        }

    def test_a_file_the_prices_hold_adds_nothing(
        self, session: DbSession, prices: PriceService
    ) -> None:
        before = session.scalar(select(func.count()).select_from(Price))

        assert prices.load(read_price_file()) == PriceLoad(prices=0, models=0, calls=0)
        assert session.scalar(select(func.count()).select_from(Price)) == before

    def test_a_row_the_file_gained_is_added(
        self, session: DbSession, prices: PriceService
    ) -> None:
        later = FROM + timedelta(days=90)
        prices.load(_rows())

        loaded = prices.load([*_rows(), _row(rate="4", effective_at=later)])

        assert loaded.prices == 1
        assert session.execute(
            select(Price.rate, Price.effective_at)
            .where(Price.model_code == PANTRY, Price.token_kind_code == "input")
            .order_by(Price.effective_at)
        ).all() == [(Decimal("3"), FROM), (Decimal("4"), later)]

    def test_a_row_the_file_lost_stays(
        self, session: DbSession, prices: PriceService
    ) -> None:
        prices.load(_rows())

        assert prices.load(_rows()[:1]) == PriceLoad(prices=0, models=0, calls=0)
        assert (
            session.scalar(
                select(func.count())
                .select_from(Price)
                .where(Price.model_code == PANTRY)
            )
            == 5
        )

    def test_a_model_the_file_names_that_no_call_has_met_is_written(
        self, session: DbSession, prices: PriceService
    ) -> None:
        prices.load(_rows())

        assert session.execute(
            select(Model.code, Model.name, Model.priced_as_code).where(
                Model.code == PANTRY
            )
        ).all() == [(PANTRY, PANTRY, None)]

    def test_a_model_pilot_has_met_stands_as_it_is(
        self, session: DbSession, prices: PriceService
    ) -> None:
        transcripts.reference(session, Model, PANTRY).name = "Pantry 2"

        prices.load(_rows())

        assert session.scalars(
            select(Model.name).where(Model.code == PANTRY)
        ).all() == ["Pantry 2"]

    def test_a_row_that_changes_a_held_rate_is_refused_and_nothing_is_written(
        self, session: DbSession, prices: PriceService
    ) -> None:
        prices.load([*_rows(), _row(rate="2", above_context=100_001)])
        edited = [
            _row(kind="output", rate="14.5"),
            _row(rate="2.5", above_context=100_001),
            *_rows(OLDER),
        ]

        with pytest.raises(InvalidOperationException) as raised:
            prices.load(edited)

        assert str(raised.value) == (
            "Cannot load the prices because the price file changes"
            " claude-pantry-2's output rate of 2026-01-01 from 15 to 14.5,"
            " claude-pantry-2's input rate above 100,001 tokens of 2026-01-01"
            " from 2 to 2.5; a rate that changed is a new row with its own date"
        )
        assert session.scalar(select(func.count()).where(Model.code == OLDER)) == 0

    def test_a_model_the_file_names_is_no_longer_priced_as_another(
        self, session: DbSession, prices: PriceService, thread: Transcript
    ) -> None:
        prices.load(_rows(OLDER))
        transcripts.reference(session, Model, PANTRY)
        price_as_family(session)
        transcripts.call(session, thread, 1, model_code=PANTRY, **TOKENS)
        prices.load(_rows(OLDER))
        dearer = [
            _row(PANTRY, kind, str(2 * Decimal(rate))) for kind, rate in RATES.items()
        ]

        assert _stored_costs(session) == [COST]
        assert prices.load(dearer) == PriceLoad(prices=5, models=1, calls=1)

        assert _priced_as(session, PANTRY) is None
        assert _stored_costs(session) == [2 * COST]

    def test_a_stored_model_with_no_price_is_given_its_familys_newest(
        self, session: DbSession, prices: PriceService, thread: Transcript
    ) -> None:
        transcripts.reference(session, Model, "claude-pantry-3")
        transcripts.call(session, thread, 1, model_code="claude-pantry-3", **TOKENS)

        assert prices.load(_rows()) == PriceLoad(prices=5, models=1, calls=1)

        assert _priced_as(session, "claude-pantry-3") == PANTRY
        assert _stored_costs(session) == [COST]

    def test_a_stored_call_with_no_cost_is_priced(
        self,
        session: DbSession,
        prices: PriceService,
        pantry: None,
        thread: Transcript,
    ) -> None:
        # As a server that priced nothing wrote it.
        transcripts.call(session, thread, 1, model_code=PANTRY, **TOKENS)

        assert _stored_costs(session) == [None]
        assert prices.load(_rows()) == PriceLoad(prices=0, models=0, calls=1)

        assert _stored_costs(session) == [COST]

    def test_a_gained_rate_prices_the_calls_from_its_date_on_again(
        self,
        session: DbSession,
        prices: PriceService,
        pantry: None,
        thread: Transcript,
    ) -> None:
        later = STARTED + timedelta(minutes=2)
        for position in (1, 2, 3):
            transcripts.call(session, thread, position, model_code=PANTRY, **TOKENS)
        prices.load(_rows())

        loaded = prices.load(
            [*_rows(), _row(kind="output", rate="30", effective_at=later)]
        )

        assert loaded == PriceLoad(prices=1, models=0, calls=2)
        dearer = COST + Decimal("0.0075")
        assert _stored_costs(session) == [COST, dearer, dearer]

    def test_a_gained_rate_prices_the_calls_of_the_models_priced_as_its_model_again(
        self,
        session: DbSession,
        prices: PriceService,
        pantry: None,
        thread: Transcript,
    ) -> None:
        transcripts.reference(session, Model, "claude-pantry-3")
        transcripts.call(session, thread, 1, model_code="claude-pantry-3", **TOKENS)
        prices.load(_rows())
        gained = _row(kind="output", rate="30", effective_at=STARTED)

        assert _stored_costs(session) == [COST]
        assert prices.load([*_rows(), gained]).calls == 1

        assert _stored_costs(session) == [COST + Decimal("0.0075")]

    def test_a_call_of_a_model_whose_prices_stand_is_not_written(
        self,
        session: DbSession,
        prices: PriceService,
        pantry: None,
        thread: Transcript,
    ) -> None:
        transcripts.call(session, thread, 1, **TOKENS)
        transcripts.call(session, thread, 2, model_code=PANTRY, **TOKENS)
        prices.load(_rows())
        opus = _stored_costs(session)[0]
        gained = _row(kind="output", rate="30", effective_at=STARTED)

        assert prices.load([*_rows(), gained]).calls == 1

        assert opus is not None
        assert _stored_costs(session) == [opus, COST + Decimal("0.0075")]

    def test_a_stored_call_no_price_covers_stays_without_a_cost(
        self, session: DbSession, prices: PriceService, thread: Transcript
    ) -> None:
        transcripts.reference(session, Model, LARDER)
        transcripts.call(session, thread, 1, model_code=LARDER, **TOKENS)

        assert prices.load(_rows()).calls == 0
        assert _stored_costs(session) == [None]
