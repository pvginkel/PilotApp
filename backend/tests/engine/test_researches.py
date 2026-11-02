"""A researched Block as the queries read it: `standing()`, each named
Block's latest Research Assignment, the earlier kept (DB 292; decision 71)."""

import uuid

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.researches import standing
from app.models import Block, Document, Item, Project, ResearchAssignment, Work
from app.models.reference import SessionState
from app.services.container import ServiceContainer

KEYS = """---
title: Plan review for 060
---

```decision id=D1
options:
  - Rotate now
  - Wait for the window
```

```question id=Q1
```
"""


def _registered(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    run: models.Session,
) -> Item:
    documents = container.document_service()
    item = documents.register(project, run, "/work/Example/review.md").item
    documents.publish_read(session.get_one(Document, item.id), KEYS, run.id)
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


class TestStanding:
    def test_the_latest_naming_stands_and_the_earlier_are_kept(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _registered(session, container, project, project_session)
        d1, q1 = _block(session, item, "D1"), _block(session, item, "Q1")
        first = _work(session, container, project, "Checking which hosts take it")
        again = _work(session, container, project, "Trying the rotation on one host")
        session.add_all(
            [
                ResearchAssignment(work_id=first.id, block_id=d1.id),
                ResearchAssignment(work_id=first.id, block_id=q1.id),
                ResearchAssignment(work_id=again.id, block_id=d1.id),
            ]
        )
        session.flush()

        assert sorted(session.execute(standing()).all()) == sorted(
            [(d1.id, again.id), (q1.id, first.id)]
        )
        assert session.scalars(
            select(ResearchAssignment.work_id)
            .where(ResearchAssignment.block_id == d1.id)
            .order_by(ResearchAssignment.work_id)
        ).all() == sorted([first.id, again.id])

    def test_a_work_item_names_a_block_once(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _registered(session, container, project, project_session)
        d1 = _block(session, item, "D1")
        work = _work(session, container, project, "Checking which hosts take it")
        session.add(ResearchAssignment(work_id=work.id, block_id=d1.id))
        session.flush()

        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                insert(ResearchAssignment).values(work_id=work.id, block_id=d1.id)
            )
