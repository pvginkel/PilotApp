"""A claimed action as the queries read it: `claimed()`, the DSL's claim on a
Block's row (DB 262), and `standing()`, each named Block's latest Claim
Assignment, the earlier kept (DB 260; decision 64)."""

import uuid

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.claims import claimed, standing
from app.models import Block, ClaimAssignment, Document, Item, Project, Work
from app.models.reference import SessionState
from app.services.container import ServiceContainer

ACTIONS = """---
title: Cut-over plan
---

```action id=A1
answer: Pilot does it
by: agent
at: 2026-10-12T09:30:00Z
```

```action id=A2
answer: Pilot does it
by: ada
at: 2026-10-12T09:30:00Z
```

```action id=A3
done: 2026-10-12T10:30:00Z
by: agent
```

```action id=A4
```

```question id=Q1
answer: Pilot does it
by: agent
at: 2026-10-12T09:30:00Z
```
"""


def _registered(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    run: models.Session,
    text: str = ACTIONS,
) -> Item:
    documents = container.document_service()
    item = documents.register(project, run, "/work/Example/cut-over.md").item
    documents.publish_read(session.get_one(Document, item.id), text, run.id)
    return item


def _block(session: DbSession, item: Item, local_id: str) -> Block:
    return session.scalars(
        select(Block).where(Block.document_id == item.id, Block.local_id == local_id)
    ).one()


def _work(
    session: DbSession, container: ServiceContainer, project: Project, title: str
) -> Work:
    run = models.Session(
        project_id=project.id,
        kind_code="work",
        cwd="/work/Example",
        token_hash=f"hash-{uuid.uuid4()}",
        state_code=SessionState.RUNNING,
    )
    session.add(run)
    session.flush()
    return container.record_service().place_work(project, run, title)


class TestClaimed:
    def test_it_is_an_action_pilot_said_it_does_and_has_not_done(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _registered(session, container, project, project_session)

        assert session.scalars(
            select(Block.local_id).where(Block.document_id == item.id, claimed())
        ).all() == ["A1"]


class TestStanding:
    def test_the_latest_naming_stands_and_the_earlier_are_kept(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _registered(session, container, project, project_session)
        a1, a4 = _block(session, item, "A1"), _block(session, item, "A4")
        first = _work(session, container, project, "Rotating the token and runners")
        retry = _work(session, container, project, "Rotating the token")
        session.add_all(
            [
                ClaimAssignment(work_id=first.id, block_id=a1.id),
                ClaimAssignment(work_id=first.id, block_id=a4.id),
                ClaimAssignment(work_id=retry.id, block_id=a1.id),
            ]
        )
        session.flush()

        assert sorted(session.execute(standing()).all()) == sorted(
            [(a1.id, retry.id), (a4.id, first.id)]
        )
        assert session.scalars(
            select(ClaimAssignment.work_id)
            .where(ClaimAssignment.block_id == a1.id)
            .order_by(ClaimAssignment.work_id)
        ).all() == sorted([first.id, retry.id])

    def test_a_work_item_names_a_block_once(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _registered(session, container, project, project_session)
        a1 = _block(session, item, "A1")
        work = _work(session, container, project, "Rotating the token")
        session.add(ClaimAssignment(work_id=work.id, block_id=a1.id))
        session.flush()

        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                insert(ClaimAssignment).values(work_id=work.id, block_id=a1.id)
            )
