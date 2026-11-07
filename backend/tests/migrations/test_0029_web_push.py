"""Revision 0029: web push in place of the bridge (DB decision 74): Push
Subscription added, over rows as revision 0028 leaves them: the revision's
downgrade builds 0028's schema in the test's transaction."""

from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.models import PushSubscription, User
from tests.support.database import violated_constraint

_BACKEND_DIR = Path(__file__).resolve().parents[2]
PHONE = "https://push.example.com/send/phone-of-ada"


def _run(db: Session, step: str) -> None:
    """Revision 0029's `step`, `upgrade` or `downgrade`, on the test's
    transaction; what the session holds is read again after an upgrade."""
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision("0029")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db.connection())):
        getattr(revision.module, step)()
    if step == "upgrade":
        db.expire_all()


def _subscription(person: User, endpoint: str = PHONE) -> PushSubscription:
    return PushSubscription(user_id=person.id, endpoint=endpoint, p256dh="p", auth="a")


class TestWebPush:
    def test_the_upgrade_adds_no_subscription_for_any_person(
        self, session: Session, person: User
    ) -> None:
        _run(session, "downgrade")
        assert not inspect(session.connection()).has_table("push_subscriptions")

        _run(session, "upgrade")

        assert session.scalars(select(PushSubscription)).all() == []
        session.add(_subscription(person))
        session.flush()
        row = session.scalars(select(PushSubscription)).one()
        assert (row.user_id, row.endpoint, row.created_at is not None) == (
            person.id,
            PHONE,
            True,
        )

    def test_an_endpoint_is_one_subscriptions(
        self, session: Session, person: User
    ) -> None:
        _run(session, "downgrade")
        _run(session, "upgrade")
        session.add(_subscription(person))
        session.flush()
        session.add(_subscription(person))

        assert violated_constraint(session) == "push_subscriptions_endpoint_key"

    def test_the_subscriptions_are_read_per_person(
        self, session: Session, person: User
    ) -> None:
        _run(session, "downgrade")
        _run(session, "upgrade")

        indexes = inspect(session.connection()).get_indexes("push_subscriptions")

        assert {
            "name": "ix_push_subscriptions_user_id",
            "column_names": ["user_id"],
        } in [
            {"name": index["name"], "column_names": index["column_names"]}
            for index in indexes
        ]

    def test_the_downgrade_drops_the_subscriptions(
        self, session: Session, person: User
    ) -> None:
        session.add(_subscription(person))
        session.flush()

        _run(session, "downgrade")

        assert not inspect(session.connection()).has_table("push_subscriptions")
        assert (
            session.connection()
            .exec_driver_sql("SELECT count(*) FROM users WHERE id = %s", (person.id,))
            .scalar()
            == 1
        )
