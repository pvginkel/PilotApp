"""Revision 0055: a person's ratio keys held to a space of their own, and its
downgrade, which takes the constraint."""

from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from tests.support.revisions import run_revision

CONSTRAINT = text(
    "SELECT count(*) FROM pg_constraint WHERE conname = 'ck_custom_ratios_key_space'"
)


class TestTheUpgrade:
    def test_it_holds_a_persons_ratio_keys_to_their_space(
        self, session: DbSession
    ) -> None:
        assert session.scalar(CONSTRAINT) == 1


class TestTheDowngrade:
    def test_it_takes_the_constraint_and_the_upgrade_makes_it_again(
        self, session: DbSession
    ) -> None:
        run_revision(session, "0055", "downgrade")

        assert session.scalar(CONSTRAINT) == 0

        run_revision(session, "0055", "upgrade")

        assert session.scalar(CONSTRAINT) == 1
