"""Pilot's notes and alerts as they stand: the latest of each place unless
withdrawn (DB 625, 631), and whether a note differs from its block's
recommendation (DB 628)."""

from datetime import UTC, datetime

import pilot_dsl as dsl
import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.pilot_notes import differs, standing_alerts, standing_notes
from app.models import Item, PilotNote, Project
from app.services.container import ServiceContainer
from tests.support.pilot_notes import a_turn, alerted, block_of, noted

CAMP = """---
title: Camp plan
---

```decision id=D1
options:
  - Dome
  - Tunnel
recommend: Dome
```

```question id=Q1
default: The lake
```
"""

SITE = """---
title: Camp site
---

```decision id=D1
options:
  - Lake
  - Hill
```
"""


def _bear(
    container: ServiceContainer,
    project: Project,
    run: models.Session,
    title: str,
    text: str,
) -> Item:
    return container.document_service().bear_item(project, "document", title, run, text)


class TestStandingNotes:
    def test_each_places_latest_stands_the_items_own_first_then_its_blocks(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        camp = _bear(container, project, project_session, "Camp plan", CAMP)
        turn = a_turn(session, project_session)
        noted(session, camp, "Q1", turn, text="Ask about the lake.")
        replacing = noted(session, camp, "Q1", turn, suggested_answer="The hill")
        whole = noted(session, camp, None, turn, text="The site moved.")
        on_d1 = noted(session, camp, "D1", turn, text="One tent was ruled.")
        handed = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
        block_of(session, camp, "D1").handed_at = handed
        session.flush()

        standing = standing_notes(session, [camp.id])

        assert [
            (each.note, each.block, each.handed_at) for each in standing[camp.id]
        ] == [(whole, None, None), (on_d1, "D1", handed), (replacing, "Q1", None)]

    def test_a_withdrawn_latest_leaves_none_and_no_earlier_stands_again(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        camp = _bear(container, project, project_session, "Camp plan", CAMP)
        turn = a_turn(session, project_session)
        noted(session, camp, "D1", turn, text="One tent was ruled.")
        noted(session, camp, "D1", turn, text="Two tents now.", withdrawn=True)
        kept = noted(session, camp, None, turn, text="The site moved.")

        assert [each.note for each in standing_notes(session, [camp.id])[camp.id]] == [
            kept
        ]

    def test_an_item_with_none_standing_is_left_out(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        camp = _bear(container, project, project_session, "Camp plan", CAMP)
        site = _bear(container, project, project_session, "Camp site", SITE)
        noted(
            session,
            site,
            "D1",
            a_turn(session, project_session),
            text="Gone.",
            withdrawn=True,
        )

        assert standing_notes(session, [camp.id, site.id]) == {}
        assert standing_notes(session, []) == {}


def _block(text: str) -> dsl.Block:
    (block,) = dsl.parse(text).blocks
    return block


DECISION = "```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nrecommend: Dome\n```\n"


class TestDiffers:
    @pytest.mark.parametrize(
        ("block", "suggested", "expected"),
        [
            pytest.param(DECISION, "Tunnel", True, id="another-option"),
            pytest.param(DECISION, "Dome", False, id="the-recommended-option"),
            pytest.param(DECISION, "dome", True, id="compared-exactly"),
            pytest.param(DECISION, "A bigger dome", True, id="free-words"),
            pytest.param(DECISION, None, False, id="no-suggestion"),
            pytest.param(
                "```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n",
                "Tunnel",
                False,
                id="no-recommendation",
            ),
            pytest.param(
                "```decision id=D2\nproposal: Cook on the fire.\n```\n",
                "Use the stove",
                True,
                id="a-proposal-disagreed",
            ),
            pytest.param(
                "```decision id=D2\nproposal: Cook on the fire.\n```\n",
                "Agree",
                False,
                id="a-proposal-agreed",
            ),
            pytest.param(
                "```decision id=C1\ntype: confirmation\nbecause: rider\n"
                "proposal: Book the site.\n```\n",
                "No",
                True,
                id="a-confirmation-refused",
            ),
            pytest.param(
                "```question id=Q1\ndefault: The lake\n```\n",
                "The lake",
                False,
                id="the-default",
            ),
            pytest.param(
                "```question id=Q1\ndefault: The lake\n```\n",
                "The hill",
                True,
                id="another-answer-to-a-question",
            ),
            pytest.param(
                "```action id=A1\noptions:\n  - Done\n  - Skip\n```\n",
                "Skip",
                False,
                id="an-action-has-no-recommendation",
            ),
        ],
    )
    def test_a_suggestion_differs_from_a_recommendation_it_is_not(
        self, block: str, suggested: str | None, expected: bool
    ) -> None:
        note = PilotNote(suggested_answer=suggested, text="Why.")

        assert differs(note, _block(block)) is expected


class TestStandingAlerts:
    def test_the_latest_stands_with_the_ask_it_awaits_and_whether_its_item_is_open(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        camp = _bear(container, project, project_session, "Camp plan", CAMP)
        site = _bear(container, project, project_session, "Camp site", SITE)
        turn = a_turn(session, project_session)
        alerted(session, camp, site, "D1", turn, "Pick the site first.")
        latest = alerted(session, camp, site, "D1", turn, "Pick the site, then send.")
        site.done_at = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
        site.done_cause_code = "marked"
        session.flush()

        (standing,) = standing_alerts(session, [camp.id, site.id]).values()

        assert (
            standing.alert,
            standing.item_id,
            standing.title,
            standing.block,
            standing.open,
        ) == (latest, site.id, "Camp site", "D1", False)

    def test_a_withdrawn_latest_leaves_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        camp = _bear(container, project, project_session, "Camp plan", CAMP)
        site = _bear(container, project, project_session, "Camp site", SITE)
        turn = a_turn(session, project_session)
        alerted(session, camp, site, "D1", turn, "Pick the site first.")
        alerted(session, camp, site, "D1", turn, "Pick it.", withdrawn=True)

        assert standing_alerts(session, [camp.id]) == {}
        assert standing_alerts(session, []) == {}
