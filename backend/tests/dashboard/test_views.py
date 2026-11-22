"""Pilot's own system views (F155.3): each held in the normal form the
engine writes, so that it reads back to itself."""

import pytest
from sqlalchemy.orm import Session as DbSession

from app.dashboard.assembly import assemble
from app.dashboard.reading import read
from app.dashboard.state import write
from app.dashboard.views import VIEWS, SystemView
from app.services.quota_week_service import quota_weeks
from tests.support.dashboard import GAP, ZONE


class TestViews:
    def test_pilot_ships_three(self) -> None:
        """Kinds of work and the share of steps not listed ahead are slice
        056's."""
        assert [view.name for view in VIEWS] == [
            "Projects",
            "Work types",
            "Where the week went",
        ]

    def test_their_keys_and_names_are_each_one_views(self) -> None:
        assert len({view.key for view in VIEWS}) == len(VIEWS)
        assert len({view.name for view in VIEWS}) == len(VIEWS)

    @pytest.mark.parametrize("view", VIEWS, ids=lambda view: view.key)
    def test_its_state_is_its_normal_form(
        self, session: DbSession, view: SystemView
    ) -> None:
        checked = read(view.state, assemble(session, ZONE, GAP), quota_weeks(session))

        assert (write(checked.state), checked.notes) == (view.state, ())
