/**
 * The profile page's notification settings: the switch of this browser's notifications (F146.1)
 * and, beside it, the alarms switch, the person's on every browser (F142.1).
 */

import { useQueryClient } from '@tanstack/react-query';
import { useDeviceNotifications } from '@/hooks/use-device-notifications';
import { usePerson } from '@/hooks/use-self';
import { usePutPeopleSelfAlarms } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const ALARMS_FORM = 'people.alarms';

/** "Notify me on this device": on subscribes this browser, off unsubscribes it and leaves its permission granted. */
export function DeviceSwitch() {
  const { handle } = usePerson();
  const { unavailable, on, blocked, busy, turnOn, turnOff } = useDeviceNotifications(handle);
  const note =
    unavailable === 'no-key'
      ? 'This deployment of Pilot sends no notifications.'
      : unavailable === 'unsupported'
        ? 'This browser cannot show Pilot’s notifications.'
        : blocked
          ? 'This browser blocks Pilot’s notifications: its site settings for Pilot unblock them.'
          : 'A notification on this device of what waits on you in your projects, and of the alarms, while you are not in Pilot.';

  return (
    <>
      <button
        type="button"
        className="switch"
        role="switch"
        aria-checked={on === true}
        disabled={unavailable !== null || on === null || busy}
        onClick={() => (on ? turnOff() : turnOn())}
        data-testid="profile.device"
      >
        <span className="track">
          <span className="knob" />
        </span>
        Notify me on this device
      </button>
      <p data-testid="profile.device.note">{note}</p>
    </>
  );
}

/** The alarms switch, on by default. */
export function AlarmsSwitch({ on }: { on: boolean }) {
  const queryClient = useQueryClient();
  const turn = usePutPeopleSelfAlarms({ onSuccess: () => queryClient.invalidateQueries() });

  const toggle = () => {
    if (turn.isPending) return;
    const fields = { alarms: !on };
    trackFormSubmit(ALARMS_FORM, fields);
    turn.mutate(
      { body: fields },
      {
        onSuccess: () => trackFormSuccess(ALARMS_FORM, fields),
        onError: () => trackFormError(ALARMS_FORM, fields),
      },
    );
  };

  return (
    <>
      <button type="button" className="switch" role="switch" aria-checked={on} onClick={toggle} data-testid="profile.alarms">
        <span className="track">
          <span className="knob" />
        </span>
        Send me alarms
      </button>
      <p data-testid="profile.alarms.note">
        A notification while Pilot cannot reach KubeCoder for five minutes, or while the week&rsquo;s usage limit halts
        the work, on every device whose notifications are on.
      </p>
    </>
  );
}
