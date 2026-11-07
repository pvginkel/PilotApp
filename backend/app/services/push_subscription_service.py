"""A browser's subscription, written and deleted by its person (F146; DB 311):
the profile page's switch and the gold bar's Turn on write it, the switch's off
and sign-out delete it."""

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import PushSubscription, User


class PushSubscriptionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def subscribe(self, person: User, endpoint: str, p256dh: str, auth: str) -> None:
        """Write the browser's subscription for `person`: an `endpoint` another
        person holds, or they hold with other keys, is theirs from now on with
        these, as if turned on now."""
        statement = insert(PushSubscription).values(
            user_id=person.id, endpoint=endpoint, p256dh=p256dh, auth=auth
        )
        self.db.execute(
            statement.on_conflict_do_update(
                index_elements=[PushSubscription.endpoint],
                set_={
                    "user_id": statement.excluded.user_id,
                    "p256dh": statement.excluded.p256dh,
                    "auth": statement.excluded.auth,
                    "created_at": func.now(),
                },
            )
        )

    def unsubscribe(self, person: User, endpoint: str) -> None:
        """Delete `person`'s subscription of `endpoint`: another person's of
        it stays, and one nobody holds is nothing to delete."""
        self.db.execute(
            delete(PushSubscription).where(
                PushSubscription.user_id == person.id,
                PushSubscription.endpoint == endpoint,
            )
        )
