"""The notification token at rest: sealed with the app's `SECRET_KEY` (DB
decision 17), opened only where Pilot sends through it.

The key is the one the template's `app/utils/auth.py` derives for the OIDC
state, reused.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.exceptions import InvalidOperationException
from app.models import User
from app.utils.auth import _derive_fernet_key


class NotificationTokenCipher:
    """Seals a person's bridge token for the record, and opens it to send."""

    def __init__(self, secret_key: str) -> None:
        self._fernet = Fernet(_derive_fernet_key(secret_key))

    def seal(self, token: str) -> str:
        """The ciphertext `users.notification_token` holds for `token`."""
        return self._fernet.encrypt(token.encode()).decode("ascii")

    def open(self, user: User) -> str | None:
        """The bearer `user`'s registration takes; None while none is set.

        Raises InvalidOperationException when the key does not open the
        ciphertext, which never reads as no token.
        """
        if user.notification_token is None:
            return None
        try:
            return self._fernet.decrypt(user.notification_token).decode()
        except InvalidToken as error:
            raise InvalidOperationException(
                f"open the notification token of user {user.handle}",
                "the app's SECRET_KEY does not open its ciphertext",
            ) from error
