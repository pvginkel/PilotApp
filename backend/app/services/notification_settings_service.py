"""A person's alarms switch on their profile (F142.1), read by the alarms'
next reconcile (`AlarmService`)."""

from app.models import User


class NotificationSettingsService:
    """Turns a person's alarms switch."""

    def switch_alarms(self, person: User, on: bool) -> None:
        """Turn `person`'s alarms switch: off pushes them no alarm, and on
        alarms on the next condition that comes to hold (F142.1)."""
        person.alarms = on
