"""A person's notification settings on their profile (F134): their bridge
token, set, replaced or cleared, never shown back, sealed at rest (F134.1; DB
decision 17), and their alarms switch (F142.1).

A save sends the one-shot "Pilot will notify you here" through the token
first, in a task, since the bridge can take about a minute to answer: a token
the bridge refuses or does not answer is not saved, and the task fails with the
bridge's reason. One the bridge took is sealed onto the person's row, and what
they should see goes out through it once that commits, their projects'
notifications (`NotificationReconcileService`) and their alarms
(`AlarmService`). A replace is the same save, and sends nothing through the
token it replaces (the A3 ruling).

A clear and the switch answer at once: the clear's dismisses are tried once,
off the request, through the token it cleared (the A2 ruling), and the
switch's submits and dismisses are the alarms' reconcile's.
"""

import re
import uuid
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.exceptions import InvalidOperationException, ValidationException
from app.models import User
from app.schemas.task_schema import TaskStartResponse
from app.services.alarm_service import AlarmService
from app.services.base_task import BaseTask, ProgressHandle
from app.services.notification_reconcile_service import NotificationReconcileService
from app.services.notification_token_cipher import NotificationTokenCipher
from app.services.people_service import self_response
from app.services.task_service import TaskService

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

ONE_SHOT_MESSAGE = "Pilot will notify you here"
"""What a save sends through the token it saves (F134.1)."""

TOKEN_PATTERN = re.compile(r"[!-~]+")
"""What a token matches whole: visible ASCII, which the bridge's
`Authorization` header carries as given."""

SAVE_OPERATION = "save your notification token"


class NotificationSettingsService:
    """Saves, replaces and clears a person's bridge token, and turns their
    alarms switch."""

    def __init__(
        self,
        db: Session,
        container: "ServiceContainer",
        notification_token_cipher: NotificationTokenCipher,
        notification_reconcile_service: NotificationReconcileService,
        alarm_service: AlarmService,
        task_service: TaskService,
        bridge_configured: bool,
    ) -> None:
        """The service on `db`, a request's transaction or a save task's.

        Args:
            db: The transaction a save's store, a clear and the switch write in
            container: Gives a save's task its database session, the bridge's
                client and this service on it
            notification_token_cipher: Seals a saved token, and opens a
                cleared one to dismiss through
            notification_reconcile_service: Submits and dismisses the
                person's projects' notifications
            alarm_service: Submits and dismisses the person's alarms
            task_service: Runs a save
            bridge_configured: False saves no token
        """
        self._db = db
        self._container = container
        self._cipher = notification_token_cipher
        self._reconciles = notification_reconcile_service
        self._alarms = alarm_service
        self._tasks = task_service
        self._configured = bridge_configured

    def start_save(
        self, person: User, token: str, caller_subject: str
    ) -> TaskStartResponse:
        """Start saving `token` as `person`'s, a first one or another in its
        place: a task sends the one-shot through it and, once the bridge took
        it, stores it (`save`). The task's result is the person as the self
        read answers; it fails on a token the bridge refused or did not
        answer, with the bridge's reason, and nothing is stored then.

        Raises:
            ValidationException: the token is not visible ASCII.
            InvalidOperationException: no notification bridge is configured.
        """
        if not TOKEN_PATTERN.fullmatch(token):
            raise ValidationException(
                f"Cannot {SAVE_OPERATION} because a token holds only visible ASCII "
                "characters, with no spaces or line breaks"
            )
        if not self._configured:
            raise InvalidOperationException(
                SAVE_OPERATION, "no notification bridge is configured"
            )
        return self._tasks.start_task(
            SaveTokenTask(self._container, person.id, token, person.notification_token),
            caller_subject=caller_subject,
        )

    def save(self, person_id: uuid.UUID, token: str, held: str | None) -> User:
        """In a save's transaction, the bridge having taken the one-shot
        through `token`: `token` sealed as the person's, and what they should
        see submitted through it once the transaction commits, their
        projects' notifications and their alarms (F94.3, F142.1). `held` is
        the ciphertext the person's row held when the save began.

        Raises:
            InvalidOperationException: the person's token was cleared or set
                to another since the save began.
        """
        person = self._locked(person_id)
        if person.notification_token != held and self._cipher.open(person) != token:
            raise InvalidOperationException(
                SAVE_OPERATION,
                "your token was cleared or set to another while the bridge took "
                "this one's notification",
            )
        person.notification_token = self._cipher.seal(token)
        self._reconciles.submit_all(self._db, person)
        self._alarms.submit_all(self._db, person)
        return person

    def clear(self, person: User) -> None:
        """Clear `person`'s token: none is set from the commit on, and each of
        their notifications and alarms that stands, an owed one included,
        reads as dismissed; once the transaction commits each is dismissed
        through the token cleared, tried once, off the request (F134, the A2
        ruling). A person with no token has nothing to clear.

        Raises:
            InvalidOperationException: the app's `SECRET_KEY` does not open
                the person's token.
        """
        self._locked(person.id)
        token = self._cipher.open(person)
        if token is None:
            return
        person.notification_token = None
        self._reconciles.dismiss_all(self._db, person, token)
        self._alarms.dismiss_all(self._db, person, token)

    def switch_alarms(self, person: User, on: bool) -> None:
        """Turn `person`'s alarms switch: once the transaction commits, off
        dismisses their standing alarms and on submits those of the
        conditions that hold, off the request (F142.1)."""
        person.alarms = on
        self._alarms.switched()

    def _locked(self, person_id: uuid.UUID) -> User:
        """The person's row, read afresh under a lock held to the commit,
        before any row the reconciles' write-backs lock after it."""
        return self._db.scalars(
            select(User)
            .where(User.id == person_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).one()


class SaveTokenTask(BaseTask):
    """A save: the one-shot through the token, then the token stored unless
    the task was cancelled."""

    def __init__(
        self,
        container: "ServiceContainer",
        person_id: uuid.UUID,
        token: str,
        held: str | None,
    ) -> None:
        super().__init__()
        self._container = container
        self._person_id = person_id
        self._token = token
        self._held = held

    def execute(self, progress_handle: ProgressHandle, **kwargs: Any) -> BaseModel:
        progress_handle.send_progress_text(
            f'Sending "{ONE_SHOT_MESSAGE}" through the token'
        )
        self._container.notification_bridge_client().send_one_shot(
            self._token, message=ONE_SHOT_MESSAGE
        )
        with scoped_session(self._container) as db:
            if self.is_cancelled:
                person = db.get_one(User, self._person_id)
            else:
                person = self._container.notification_settings_service().save(
                    self._person_id, self._token, self._held
                )
            return self_response(person)
