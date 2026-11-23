"""The two counts as tasks (F154.6), on the app's task form: started by a
route that answers at once, their events going over the stream the page
holds to the caller alone, each answering when it is done, every statement
under the engine's timeout.

- **By's counts**: each fact's attributes' counts as a progress update
  as they are counted, its `data` the counts so far, then all of them as
  its result.
- **The quick filters' counts and amounts**: all of them as its result.

Each runs on a session of its own thread, `BaseSessionTask`'s.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dashboard.address import View
from app.dashboard.counts import Count
from app.schemas.dashboard import (
    AttributeCountSchema,
    AttributeCountsSchema,
    QuickFilterCountSchema,
    QuickFilterCountsSchema,
)
from app.services.base_task import BaseSessionTask, ProgressHandle


def _counts(counts: tuple[Count, ...]) -> AttributeCountsSchema:
    return AttributeCountsSchema(
        counts=[
            AttributeCountSchema(dimension=count.dimension, count=count.count)
            for count in counts
        ]
    )


class AttributeCountsTask(BaseSessionTask):
    """By's counts of a view, `view` and `now` its keywords."""

    def execute_session(
        self, session: Session, progress_handle: ProgressHandle, **kwargs: Any
    ) -> BaseModel:
        view: View = kwargs["view"]
        now: datetime = kwargs["now"]

        def counted(part: tuple[Count, ...], done: int, facts: int) -> None:
            progress_handle.send_progress(
                f"Counted the attributes of {done} of {facts} facts",
                done / facts,
                _counts(part).model_dump(mode="json"),
            )

        counts = self.container.counts_service().attributes(view, now, counted)
        return _counts(counts)


class QuickFilterCountsTask(BaseSessionTask):
    """The quick filters' counts and amounts of a view, `view` and `now`
    its keywords."""

    def execute_session(
        self, session: Session, progress_handle: ProgressHandle, **kwargs: Any
    ) -> BaseModel:
        view: View = kwargs["view"]
        now: datetime = kwargs["now"]
        counts = self.container.counts_service().quick_filters(view, now)
        return QuickFilterCountsSchema(
            quick_filters=[
                QuickFilterCountSchema(
                    key=count.key, count=count.count, amount=count.amount
                )
                for count in counts
            ]
        )
