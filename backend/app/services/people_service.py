"""The signed-in person on the record: the User row, born at the handle step
(F137, DB decision 30), refreshed at every later sign-in."""

import re
import unicodedata
from datetime import UTC, datetime
from itertools import count

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.exceptions import InvalidOperationException, ValidationException
from app.models import User
from app.models.reference import UserKind
from app.services.auth_service import AuthContext

HANDLE_PATTERN = re.compile(r"[a-z0-9-]+")
"""What a handle matches whole: `ck_users_handle`."""

AGENT_HANDLE = "agent"
"""Pilot's handle, and no person's: `ck_users_agent_handle`."""


def initials(name: str) -> str:
    """What an avatar shows (F106): the first two capitals of the full name.

    A name with fewer capitals, such as a handle standing as the name, gives
    the first letters of its first two words, upper-cased.
    """
    capitals = [character for character in name if character.isupper()]
    if len(capitals) >= 2:
        return capitals[0] + capitals[1]
    words = re.findall(r"[^\W_]+", name)
    return "".join(word[0] for word in words[:2]).upper() or name[:1].upper()


def handle_prefill(name: str | None) -> str:
    """What the handle step's field starts with: the name's first word, made
    to fit a handle; empty for no name, or a word with nothing that fits."""
    if name is None:
        return ""
    folded = unicodedata.normalize("NFKD", name.split()[0].casefold())
    return re.sub(r"[^a-z0-9-]", "", folded.encode("ascii", "ignore").decode())


def token_name(auth: AuthContext) -> str | None:
    """The full name the token carries; none for a blank one."""
    if auth.name is None:
        return None
    return auth.name.strip() or None


class PeopleService:
    """Who is signed in, as a User of kind person, keyed by the token's subject."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def find(self, auth: AuthContext) -> User | None:
        """The caller's row; none before they chose their handle."""
        return self.db.scalars(select(User).where(User.subject == auth.subject)).first()

    def record_sign_in(self, auth: AuthContext) -> User | None:
        """Refresh the caller's row from the token: the name, unless the token
        carries none, the email and the last seen. None before the row exists,
        and nothing is written then."""
        person = self.find(auth)
        if person is None:
            return None
        person.name = token_name(auth) or person.name
        person.email = auth.email
        person.last_seen_at = datetime.now(UTC)
        self.db.flush()
        return person

    def choose_handle(self, auth: AuthContext, handle: str) -> User:
        """Create the caller's row with `handle`, which never changes after,
        and the lowest free avatar slot (F132).

        The name is the token's, or the handle when the token carries none.

        Raises:
            ValidationException: the handle is not lower-case letters, digits
                and hyphens.
            InvalidOperationException: the handle is Pilot's or another
                person's, or the caller chose theirs already.
        """
        operation = f"choose the handle {handle!r}"
        if not HANDLE_PATTERN.fullmatch(handle):
            raise ValidationException(
                f"Cannot {operation} because a handle holds only lower-case "
                "letters, digits and hyphens"
            )
        if handle == AGENT_HANDLE:
            raise InvalidOperationException(operation, "it is Pilot's")

        # Choosers take turns from here to their commit, so the slot read
        # below is still free at the insert, and the checks see every row a
        # chooser before them committed.
        self.db.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))

        chosen = self.find(auth)
        if chosen is not None:
            raise InvalidOperationException(
                operation,
                f"your handle is {chosen.handle!r} already, and a handle never changes",
            )
        if self.db.scalars(select(User.id).where(User.handle == handle)).first():
            raise InvalidOperationException(operation, "another person has it")

        taken = set(
            self.db.scalars(
                select(User.avatar_slot).where(User.avatar_slot.is_not(None))
            )
        )
        person = User(
            kind_code=UserKind.PERSON,
            subject=auth.subject,
            handle=handle,
            name=token_name(auth) or handle,
            email=auth.email,
            avatar_slot=next(slot for slot in count(1) if slot not in taken),
            last_seen_at=datetime.now(UTC),
        )
        self.db.add(person)
        self.db.flush()
        return person

    def require_person(self, auth: AuthContext, operation: str) -> User:
        """The caller's row, for a write attributed to them.

        Raises:
            InvalidOperationException: the caller has not chosen a handle yet.
        """
        person = self.find(auth)
        if person is None:
            raise InvalidOperationException(
                operation, "you have not chosen your handle yet"
            )
        return person
