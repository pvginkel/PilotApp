"""NotificationSettingsService: a person's alarms switch (F142.1)."""

from sqlalchemy.orm import Session

from app.models import User
from app.services.container import ServiceContainer


class TestSwitchAlarms:
    def test_it_turns_the_switch(
        self, container: ServiceContainer, session: Session, person: User
    ) -> None:
        service = container.notification_settings_service()

        service.switch_alarms(person, False)
        session.flush()
        session.refresh(person)
        assert person.alarms is False

        service.switch_alarms(person, True)
        session.flush()
        session.refresh(person)
        assert person.alarms is True
