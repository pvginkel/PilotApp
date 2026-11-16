"""Revision 0046's downgrade: Work Trigger without `offer_taken`, and a Work
without `trigger_note_id`. Its upgrade adds the enum's value in a
transaction of its own, which no test's transaction holds: the run's
template database is built by it."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Item, Project, Work
from app.models.reference import SessionState, WorkTrigger
from app.services.container import ServiceContainer
from tests.support.pilot_notes import a_turn, noted
from tests.support.revisions import run_revision

OFFERED = """---
title: Put the key into OpenBao
---

```action id=A1
```
"""


def _labels(db: DbSession) -> list[str]:
    return list(
        db.scalars(
            text(
                "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e"
                " ON e.enumtypid = t.oid WHERE t.typname = 'work_trigger'"
                " ORDER BY e.enumsortorder"
            )
        )
    )


class TestTheDowngrade:
    def test_the_triggers_are_without_offer_taken(self, session: DbSession) -> None:
        run_revision(session, "0046", "downgrade")

        assert _labels(session) == [
            "setup",
            "worker_turn_ended",
            "item_done",
            "wait_fired",
        ]

    def test_the_column_it_added_is_gone(self, session: DbSession) -> None:
        run_revision(session, "0046", "downgrade")

        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns"
                    " WHERE table_name = 'work' AND column_name = 'trigger_note_id'"
                )
            )
            == 0
        )

    def test_an_offers_job_fails_the_cast(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = container.document_service().bear_item(
            project, "action", "Put the key into OpenBao", project_session, OFFERED
        )
        note = noted(
            session,
            item,
            "A1",
            a_turn(session, project_session),
            offer="I can store the key myself",
        )
        job_id = uuid.uuid4()
        session.add_all(
            [
                Item(
                    id=job_id,
                    project_id=project.id,
                    seq=item.seq + 1,
                    kind_code="work",
                    title="Starting the work offered on A1",
                    created_by_session_id=project_session.id,
                ),
                models.Session(
                    id=job_id,
                    project_id=project.id,
                    kind_code="job",
                    cwd="/work/PilotProjects",
                    token_hash=uuid.uuid4().hex * 2,
                    state_code=SessionState.HELD,
                ),
                Work(
                    id=job_id,
                    project_id=project.id,
                    session_kind_code="job",
                    trigger_code=WorkTrigger.OFFER_TAKEN,
                    trigger_note_id=note.id,
                    autopilot=False,
                ),
            ]
        )
        session.flush()

        with pytest.raises(DBAPIError, match="invalid input value for enum"):
            run_revision(session, "0046", "downgrade")
