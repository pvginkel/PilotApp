"""A view's address (F159): a state checked and written back in its normal
form, an entry's focus filled in from the record (F166.1), and its time
range fixed on request."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard.address import AddressService, fixed, parents
from app.dashboard.catalogue import Catalogue
from app.dashboard.state import Between, Preset, Weeks
from app.exceptions import StateRefusedException
from app.models import Project, QuotaWeek, User
from app.services.container import ServiceContainer
from app.services.quota_week_service import Period
from tests.support.dashboard import Record, catalogue, record, sent

THIS = datetime(2026, 11, 19, 10, tzinfo=UTC)
LAST = THIS - timedelta(days=7)
BEFORE = LAST - timedelta(days=7)
WEEKS = (
    Period(BEFORE, LAST),
    Period(LAST, THIS),
    Period(THIS, THIS + timedelta(days=7)),
)
NOW = datetime(2026, 11, 22, 23, 30, tzinfo=UTC)
"""Monday 23 November 2026, half past midnight in Europe/Amsterdam."""


def _key(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z").replace(":", "%3A")


@pytest.fixture
def service(container: ServiceContainer) -> AddressService:
    return container.address_service()


@pytest.fixture
def held(session: DbSession) -> Catalogue:
    return catalogue(session)


@pytest.fixture
def weeks(session: DbSession) -> None:
    session.execute(delete(QuotaWeek))
    session.add_all(
        QuotaWeek(starts_at=week.starts_at, ends_at=week.ends_at) for week in WEEKS
    )
    session.flush()


@pytest.fixture
def worked(
    session: DbSession, person: User, project: Project, project_session: models.Session
) -> Record:
    return record(session, person, project, project_session)


class TestAddress:
    def test_it_is_the_normal_form_after_dash(self, service: AddressService) -> None:
        found = service.address("#dash/m=cost&by=project&rel=1&dw=cols:off")

        assert found.address == (
            "#dash/t=qw&by=project&m=cost.sum&col=none&rel=1&dw=cols:off"
        )
        assert found.look == ("rel=1", "dw=cols:off")
        assert found.notes == ()

    def test_two_spellings_of_one_view_are_one_address(
        self, service: AddressService
    ) -> None:
        assert (
            service.address(
                "by=session_start&m=cost.sum.call&p=order,session_start"
            ).address
            == service.address("p=order&m=cost&by=psession&col=none").address
        )

    def test_its_notes(self, service: AddressService) -> None:
        assert service.address("m=r:gone").notes == (
            'm=r:gone: no ratio has the key "gone", so the measure is dropped.',
            "m=r:gone: the view keeps no measure, so it takes cost.sum.",
        )

    def test_a_state_with_a_fault_is_refused(self, service: AddressService) -> None:
        with pytest.raises(StateRefusedException) as refused:
            service.address("by=phases")

        assert refused.value.message.splitlines()[0] == (
            "Cannot read the view because its state has 1 fault."
        )

    def test_its_weeks_are_the_records_in_their_order(
        self, service: AddressService, weeks: None
    ) -> None:
        assert service.weeks() == WEEKS


@pytest.mark.usefixtures("weeks")
class TestFixTime:
    @pytest.mark.parametrize(
        ("written", "range_"),
        [
            ("qw", f"wk,{_key(THIS)}"),
            ("lqw", f"wk,{_key(LAST)}"),
            ("l2", f"wk,{_key(LAST)},{_key(THIS)}"),
            ("l8", f"wk,{_key(BEFORE)},{_key(LAST)},{_key(THIS)}"),
            ("today", "c,2026-11-23,2026-11-23"),
            ("d2", "c,2026-11-22,2026-11-23"),
            ("d7", "c,2026-11-17,2026-11-23"),
            ("all", "all"),
            ("c,2026-11-01,", "c,2026-11-01,"),
            (f"wk,{_key(LAST)}", f"wk,{_key(LAST)}"),
        ],
    )
    def test_a_range_as_it_stands_now(
        self, service: AddressService, written: str, range_: str
    ) -> None:
        found = service.address(f"t={written}", fix_time=True, now=NOW)

        assert found.address == f"#dash/t={range_}&by=project&m=cost.sum&col=none"

    def test_unasked_a_range_stays_as_written(self, service: AddressService) -> None:
        assert service.address("t=qw", now=NOW).address.startswith("#dash/t=qw&")

    def test_the_running_week_is_the_latest_the_record_holds(
        self, held: Catalogue
    ) -> None:
        assert fixed(Preset("qw"), held, WEEKS[:2], NOW) == Weeks((LAST,))

    def test_weeks_the_record_does_not_reach_leave_it_as_written(
        self, held: Catalogue
    ) -> None:
        assert fixed(Preset("lqw"), held, WEEKS[:1], NOW) == Preset("lqw")

    def test_a_range_already_fixed_stays(self, held: Catalogue) -> None:
        between = Between(date(2026, 11, 1), None)

        assert fixed(between, held, WEEKS, NOW) == between


class TestEntry:
    def test_a_projects_its_path_by_its_sessions_and_the_weeks_of_its_calls(
        self, service: AddressService, worked: Record
    ) -> None:
        project = worked.project.id
        weeks = f"{_key(datetime(2026, 11, 5, 10, tzinfo=UTC))},{_key(THIS - timedelta(days=7))}"

        found = service.address(f"f=project:{project}")

        assert found.address == (
            f"#dash/t=wk,{weeks}&by=psession&m=cost.sum&m=misses.sum"
            f"&dr=project:{project}@project&col=none&f=project:{project}"
        )
        assert found.notes == ()

    def test_a_pilot_sessions_with_its_project_above_it(
        self, service: AddressService, worked: Record
    ) -> None:
        project, work = worked.project.id, worked.work.id

        found = service.address(f"#dash/f=psession:{work}")

        assert found.address == (
            f"#dash/t=wk,{_key(datetime(2026, 11, 5, 10, tzinfo=UTC))}&by=pturn"
            f"&m=cost.sum&m=misses.sum&dr=project:{project}@project"
            f"&dr=psession:{work}@psession&col=none&f=psession:{work}"
        )

    def test_its_read_runs_under_the_engines_bounds(
        self, service: AddressService, session: DbSession, worked: Record
    ) -> None:
        with sent(session) as statements:
            service.address(f"f=project:{worked.project.id}")

        at = statements.index("SET TRANSACTION READ ONLY")
        assert statements[at + 1] == "SET LOCAL statement_timeout = 30000"
        assert statements[at + 2].startswith("SELECT DISTINCT")
        assert statements[at + 3].startswith("ROLLBACK")

    def test_one_the_record_holds_nothing_of_takes_all_time(
        self, service: AddressService
    ) -> None:
        key = uuid.uuid4()

        found = service.address(f"f=psession:{key}")

        assert found.address == (
            f"#dash/t=all&by=pturn&m=cost.sum&m=misses.sum"
            f"&dr=psession:{key}@psession&col=none&f=psession:{key}"
        )
        assert found.notes == (
            "f=psession: the record holds nothing of it yet, so the view takes all "
            "time.",
        )

    def test_a_focus_with_more_beside_it_is_no_entry(
        self, service: AddressService
    ) -> None:
        key = uuid.uuid4()

        assert service.address(f"f=project:{key}&t=all").address == (
            f"#dash/t=all&by=project&m=cost.sum&col=none&f=project:{key}"
        )

    def test_one_that_is_no_focus_is_refused(self, service: AddressService) -> None:
        with pytest.raises(StateRefusedException):
            service.address("f=slice:x")


class TestParents:
    def test_the_parts_above_one_outermost_first(self, held: Catalogue) -> None:
        assert parents(held, "project") == []
        assert parents(held, "psession") == ["project"]
        assert parents(held, "pturn") == ["project", "psession"]

    def test_none_above_a_part_two_name_as_their_next(self, held: Catalogue) -> None:
        assert parents(held, "conversation") == []
