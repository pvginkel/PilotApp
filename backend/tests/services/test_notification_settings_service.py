"""A person's notification settings (F134, F134.1, F142.1; DB decision 17;
V07, V12, V16, V18, V19): the token's save after its one-shot, as a task, its
replace and its clear, and the alarms switch, through the fake bridge.

Every test is on a database of its own: a save's task stores in a session of
its own, on another thread. Where a test follows what goes out after a save, a
clear or the switch, the reconcile and the alarms run on a supervisor of their
own, the container's, with the outage holding and its alarm due at once."""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from dependency_injector import providers
from flask import Flask
from sqlalchemy import select

from app.database import scoped_session
from app.engine.bus import EngineBus
from app.exceptions import InvalidOperationException, ValidationException
from app.models import User
from app.models.reference import Condition
from app.schemas.task_schema import TaskInfo, TaskStartResponse, TaskStatus
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.alarm_service import AlarmService
from app.services.condition_service import ConditionService
from app.services.container import ServiceContainer
from app.services.controller_outage import ControllerOutage
from app.services.fake_notification_bridge import FakeCall
from app.services.notification_reconcile_service import NotificationReconcileService
from app.services.notification_settings_service import ONE_SHOT_MESSAGE, SaveTokenTask
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.fake_notification_bridge import (
    WatchedFakeNotificationBridge,
    bridge_client_of,
)
from tests.support.supervisor import Supervise, wait_until

ADA_TOKEN = "token-of-ada"
NEW_TOKEN = "token-of-adas-new-phone"
OTHER_TOKEN = "token-of-adas-other-phone"
NOT_VISIBLE_ASCII = (
    pytest.param("", id="empty"),
    pytest.param("token of ada", id="space"),
    pytest.param("token-of-ada\n", id="line-break"),
    pytest.param("token-of-ada\r\nX-Injected: 1", id="header-injection"),
    pytest.param("token\tof-ada", id="tab"),
    pytest.param("token-of-ada​", id="zero-width-space"),
    pytest.param("tökén-of-ada", id="non-ascii"),
)


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def container(committed_app: Flask) -> ServiceContainer:
    """The committed app's container, with Ada."""
    container: ServiceContainer = committed_app.container
    with scoped_session(container):
        container.test_data_service().person("ada", "Ada Example")
    return container


@pytest.fixture
def bridge(container: ServiceContainer) -> Iterator[WatchedFakeNotificationBridge]:
    """The fake bridge, the app's: the container's client on it and its
    address the app's setting, with a registration for Ada."""
    fake = WatchedFakeNotificationBridge()
    try:
        bridge_client_of(container, fake)
        container.app_config.override(
            container.app_config().model_copy(
                update={"notification_bridge_url": fake.url}
            )
        )
        fake.add_registration("ada", ADA_TOKEN)
        yield fake
        assert fake.failures == []
    finally:
        fake.close()


@pytest.fixture
def sends(
    container: ServiceContainer,
    bridge: WatchedFakeNotificationBridge,
    supervise: Supervise,
) -> None:
    """The container's reconcile and alarms on a supervisor of their own,
    STARTUP fired, so that what a commit asks for goes out; the outage holds,
    and its alarm is due at once."""
    supervisor, coordinator = supervise(container)
    outage = ControllerOutage()
    cipher = container.notification_token_cipher()
    container.notification_reconcile_service.override(
        providers.Object(
            NotificationReconcileService(
                container=container,
                supervisor=supervisor,
                engine_bus=EngineBus(),
                notification_token_cipher=cipher,
                bridge_configured=True,
            )
        )
    )
    container.alarm_service.override(
        providers.Object(
            AlarmService(
                container=container,
                supervisor=supervisor,
                condition_service=ConditionService(
                    container, outage, container.sse_connection_manager()
                ),
                notification_token_cipher=cipher,
                bridge_configured=True,
                base_url=container.config().baseurl,
                outage_after_seconds=0,
            )
        )
    )
    outage.call_unanswered()
    coordinator.fire_startup()


@dataclass
class _Progress:
    """A save's progress, as a task's handle would send it."""

    texts: list[str]

    def send_progress_text(self, text: str) -> None:
        self.texts.append(text)

    def send_progress_value(self, value: float) -> None:
        raise AssertionError("a save sends no progress value")

    def send_progress(self, text: str, value: float) -> None:
        raise AssertionError("a save sends no progress value")


def _person(container: ServiceContainer, handle: str = "ada") -> User:
    return (
        container.db_session().scalars(select(User).where(User.handle == handle)).one()
    )


def _person_id(container: ServiceContainer) -> uuid.UUID:
    with scoped_session(container):
        return _person(container).id


def _sealed(container: ServiceContainer) -> str | None:
    """Ada's token's ciphertext, as committed."""
    with scoped_session(container):
        return _person(container).notification_token


def _held(container: ServiceContainer) -> str | None:
    """Ada's token, as committed, opened."""
    with scoped_session(container):
        return container.notification_token_cipher().open(_person(container))


def _give_token(container: ServiceContainer, token: str) -> None:
    """Ada's token on the record, as a save before this one left it."""
    with scoped_session(container):
        _person(
            container
        ).notification_token = container.notification_token_cipher().seal(token)


def _alarms(container: ServiceContainer) -> bool:
    with scoped_session(container):
        return _person(container).alarms


def _project(container: ServiceContainer) -> str:
    """Ada's project, not started; its id, the notification's sequence id."""
    with scoped_session(container):
        project = container.test_data_service().project(
            InventedProjectCreateSchema.model_validate(
                {"members": ["ada"], "name": "Camp"}
            )
        )
        return str(project.id)


def _start_save(container: ServiceContainer, token: str) -> TaskStartResponse:
    with scoped_session(container):
        person = _person(container)
        assert person.subject is not None
        return container.notification_settings_service().start_save(
            person, token, person.subject
        )


def _finished(container: ServiceContainer, started: TaskStartResponse) -> TaskInfo:
    """The save's task, once it completed or failed."""
    tasks = container.task_service()

    def info() -> TaskInfo:
        found = tasks.get_task_status(started.task_id)
        assert found is not None
        return found

    wait_until(
        lambda: info().status in (TaskStatus.COMPLETED, TaskStatus.FAILED),
        "the save's task finished",
    )
    return info()


def _save(container: ServiceContainer, token: str) -> TaskInfo:
    return _finished(container, _start_save(container, token))


def _clear(container: ServiceContainer) -> None:
    with scoped_session(container):
        container.notification_settings_service().clear(_person(container))


def _switch(container: ServiceContainer, on: bool) -> None:
    with scoped_session(container):
        container.notification_settings_service().switch_alarms(_person(container), on)


def _during_the_one_shot(
    bridge: WatchedFakeNotificationBridge, change: Callable[[], None]
) -> None:
    """`change` committed once the bridge took the save's one-shot, before it
    answers."""
    bridge.on_submit = change


class TestStartSave:
    def test_the_one_shot_goes_out_through_the_token_before_it_is_stored(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        stored_at_the_one_shot: list[str | None] = []
        _during_the_one_shot(
            bridge, lambda: stored_at_the_one_shot.append(_sealed(container))
        )

        started = _start_save(container, ADA_TOKEN)
        task = _finished(container, started)

        assert started.status == TaskStatus.PENDING
        assert task.status == TaskStatus.COMPLETED
        assert stored_at_the_one_shot == [None]
        (one_shot,) = bridge.one_shots("ada")
        assert (one_shot.sequence_id, one_shot.message, one_shot.priority) == (
            None,
            ONE_SHOT_MESSAGE,
            "default",
        )
        assert _held(container) == ADA_TOKEN

    def test_the_token_is_stored_sealed_and_the_result_never_carries_it(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        task = _save(container, ADA_TOKEN)

        sealed = _sealed(container)
        assert sealed is not None
        assert ADA_TOKEN not in sealed
        assert task.result == {
            "handle": "ada",
            "handle_prefill": None,
            "name": "Ada Example",
            "initials": "AE",
            "avatar_slot": 1,
            "notification_token_set": True,
            "alarms": True,
        }

    def test_a_token_the_bridge_refuses_fails_with_its_reason_and_is_not_stored(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        _give_token(container, ADA_TOKEN)

        task = _save(container, "token-of-nobody")

        assert task.status == TaskStatus.FAILED
        assert task.error == (
            "Cannot send a one-shot notification through the bridge because external "
            "service failed: the bridge refused it with 401: unknown bearer token"
        )
        assert _held(container) == ADA_TOKEN

    def test_a_token_the_bridge_does_not_answer_is_not_stored(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        bridge.unreachable(answer="error")

        task = _save(container, ADA_TOKEN)

        assert task.status == TaskStatus.FAILED
        assert task.error is not None
        assert task.error.startswith(
            "Cannot send a one-shot notification through the bridge because external "
            "service failed: the bridge did not answer"
        )
        assert _sealed(container) is None

    def test_the_start_waits_on_no_bridge_call(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        bridge.unreachable(answer="stall")

        started = _start_save(container, ADA_TOKEN)

        assert _sealed(container) is None
        bridge.unreachable(on=False)
        assert _finished(container, started).status == TaskStatus.COMPLETED
        assert _held(container) == ADA_TOKEN

    @pytest.mark.parametrize("token", NOT_VISIBLE_ASCII)
    def test_a_token_that_is_not_visible_ascii_is_refused_before_the_bridge(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        token: str,
    ) -> None:
        with pytest.raises(ValidationException) as raised:
            _start_save(container, token)

        assert raised.value.message == (
            "Cannot save your notification token because a token holds only "
            "visible ASCII characters, with no spaces or line breaks"
        )
        assert bridge.one_shots("ada") == []
        assert _sealed(container) is None

    def test_with_no_bridge_no_token_is_saved(
        self, container: ServiceContainer
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            _start_save(container, ADA_TOKEN)

        assert raised.value.message == (
            "Cannot save your notification token because no notification bridge "
            "is configured"
        )
        assert _sealed(container) is None

    @pytest.mark.usefixtures("sends")
    def test_a_saved_token_has_the_persons_projects_and_alarms_submitted_through_it(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        project_id = _project(container)

        _save(container, ADA_TOKEN)

        wait_until(
            lambda: set(bridge.shown("ada")) == {project_id, Condition.OUTAGE.value},
            "the project's notification and the outage's alarm shown",
        )

    @pytest.mark.usefixtures("sends")
    def test_a_replace_resubmits_through_the_new_token(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        project_id = _project(container)
        _save(container, ADA_TOKEN)
        wait_until(lambda: len(bridge.shown("ada")) == 2, "both shown")
        bridge.rotate_token("ada", NEW_TOKEN)

        task = _save(container, NEW_TOKEN)

        assert task.status == TaskStatus.COMPLETED
        assert _held(container) == NEW_TOKEN
        wait_until(lambda: len(bridge.calls("ada")) == 6, "both resubmitted")
        one_shot, *resubmits = bridge.calls("ada")[3:]
        assert one_shot == FakeCall("submit", None, True)
        assert sorted(resubmits, key=lambda call: str(call.sequence_id)) == sorted(
            [
                FakeCall("submit", project_id, False),
                FakeCall("submit", Condition.OUTAGE.value, False),
            ],
            key=lambda call: str(call.sequence_id),
        )


class TestSaveTokenTask:
    def test_it_says_it_sends_the_one_shot(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        progress = _Progress([])

        SaveTokenTask(container, _person_id(container), ADA_TOKEN, None).execute(
            progress
        )

        assert progress.texts == [
            'Sending "Pilot will notify you here" through the token'
        ]

    def test_cancelled_during_the_one_shot_it_stores_nothing(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        task = SaveTokenTask(container, _person_id(container), ADA_TOKEN, None)
        _during_the_one_shot(bridge, task.cancel)

        result = task.execute(_Progress([]))

        assert len(bridge.one_shots("ada")) == 1
        assert _sealed(container) is None
        assert result.model_dump()["notification_token_set"] is False


class TestSaveSuperseded:
    def test_a_clear_during_the_one_shot_stands(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        _give_token(container, ADA_TOKEN)
        bridge.rotate_token("ada", NEW_TOKEN)
        _during_the_one_shot(bridge, lambda: _clear(container))

        task = _save(container, NEW_TOKEN)

        assert task.status == TaskStatus.FAILED
        assert task.error == (
            "Cannot save your notification token because your token was cleared "
            "or set to another while the bridge took this one's notification"
        )
        assert _sealed(container) is None

    def test_another_token_saved_during_the_one_shot_stands(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        _during_the_one_shot(bridge, lambda: _give_token(container, OTHER_TOKEN))

        task = _save(container, ADA_TOKEN)

        assert task.status == TaskStatus.FAILED
        assert _held(container) == OTHER_TOKEN

    def test_the_same_token_saved_during_the_one_shot_is_saved(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        _during_the_one_shot(bridge, lambda: _give_token(container, ADA_TOKEN))

        task = _save(container, ADA_TOKEN)

        assert task.status == TaskStatus.COMPLETED
        assert _held(container) == ADA_TOKEN


class TestClear:
    @pytest.mark.usefixtures("sends")
    def test_none_is_set_at_once_and_what_stands_is_dismissed_through_the_token(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        _project(container)
        _save(container, ADA_TOKEN)
        wait_until(lambda: len(bridge.shown("ada")) == 2, "both shown")
        bridge.unreachable(answer="stall")

        _clear(container)

        assert _sealed(container) is None
        bridge.unreachable(on=False)
        wait_until(lambda: bridge.shown("ada") == {}, "both dismissed")

    def test_a_person_with_no_token_has_nothing_to_clear(
        self, container: ServiceContainer
    ) -> None:
        _clear(container)

        assert _sealed(container) is None

    def test_a_token_the_apps_key_does_not_open_is_not_cleared(
        self, container: ServiceContainer
    ) -> None:
        with scoped_session(container):
            _person(container).notification_token = "not-a-ciphertext"

        with pytest.raises(InvalidOperationException) as raised:
            _clear(container)

        assert raised.value.message == (
            "Cannot open the notification token of user ada because the app's "
            "SECRET_KEY does not open its ciphertext"
        )
        assert _sealed(container) == "not-a-ciphertext"


class TestSwitchAlarms:
    def test_it_turns_the_switch(self, container: ServiceContainer) -> None:
        _switch(container, False)
        assert _alarms(container) is False

        _switch(container, True)
        assert _alarms(container) is True

    @pytest.mark.usefixtures("sends")
    def test_off_dismisses_the_persons_alarms_and_on_submits_them(
        self, container: ServiceContainer, bridge: WatchedFakeNotificationBridge
    ) -> None:
        _save(container, ADA_TOKEN)
        wait_until(lambda: len(bridge.shown("ada")) == 1, "the outage's alarm shown")

        _switch(container, False)
        wait_until(lambda: bridge.shown("ada") == {}, "the outage's alarm dismissed")

        _switch(container, True)
        wait_until(
            lambda: set(bridge.shown("ada")) == {Condition.OUTAGE.value},
            "the outage's alarm shown again",
        )
