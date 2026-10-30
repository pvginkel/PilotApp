"""NotificationTokenCipher: the bridge token sealed at rest with the app's
`SECRET_KEY`, opened to send (DB decision 17)."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.exceptions import InvalidOperationException
from app.models import User
from app.services.container import ServiceContainer
from app.services.notification_token_cipher import NotificationTokenCipher

_TOKEN = "bridge-token-ada-0001"


class TestNotificationTokenCipher:
    def test_a_sealed_token_opens(self, session: Session, person: User) -> None:
        cipher = NotificationTokenCipher("a-secret-key")
        person.notification_token = cipher.seal(_TOKEN)
        session.flush()

        assert cipher.open(person) == _TOKEN

    def test_the_record_holds_the_ciphertext(
        self, session: Session, person: User
    ) -> None:
        person.notification_token = NotificationTokenCipher("a-secret-key").seal(_TOKEN)
        session.flush()

        stored = session.execute(
            text("SELECT notification_token FROM users WHERE id = :id"),
            {"id": person.id},
        ).scalar_one()
        assert _TOKEN not in stored

    def test_a_person_without_a_token_opens_to_none(self, person: User) -> None:
        assert NotificationTokenCipher("a-secret-key").open(person) is None

    def test_another_key_s_ciphertext_fails_loudly(self, person: User) -> None:
        person.notification_token = NotificationTokenCipher("another-key").seal(_TOKEN)

        with pytest.raises(InvalidOperationException) as raised:
            NotificationTokenCipher("a-secret-key").open(person)

        assert raised.value.message == (
            "Cannot open the notification token of user ada because the app's"
            " SECRET_KEY does not open its ciphertext"
        )

    def test_a_token_stored_unsealed_fails_loudly(self, person: User) -> None:
        person.notification_token = _TOKEN

        with pytest.raises(InvalidOperationException):
            NotificationTokenCipher("a-secret-key").open(person)

    def test_the_container_s_cipher_takes_the_app_s_secret_key(
        self, container: ServiceContainer, test_settings: Settings, person: User
    ) -> None:
        person.notification_token = NotificationTokenCipher(
            test_settings.secret_key
        ).seal(_TOKEN)

        assert container.notification_token_cipher().open(person) == _TOKEN
