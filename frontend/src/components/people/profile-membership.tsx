/**
 * The profile page's switch *Join projects started on my behalf* (F134.2): on, the person is a
 * member of every project a call to Pilot starts.
 */

import { useQueryClient } from '@tanstack/react-query';
import { usePutPeopleSelfJoinCalls } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const JOIN_CALLS_FORM = 'people.join-calls';

/** The switch, on by default. */
export function JoinCallsSwitch({ on }: { on: boolean }) {
  const queryClient = useQueryClient();
  const turn = usePutPeopleSelfJoinCalls({ onSuccess: () => queryClient.invalidateQueries() });

  const toggle = () => {
    if (turn.isPending) return;
    const fields = { join_calls: !on };
    trackFormSubmit(JOIN_CALLS_FORM, fields);
    turn.mutate(
      { body: fields },
      {
        onSuccess: () => trackFormSuccess(JOIN_CALLS_FORM, fields),
        onError: () => trackFormError(JOIN_CALLS_FORM, fields),
      },
    );
  };

  return (
    <>
      <button type="button" className="switch" role="switch" aria-checked={on} onClick={toggle} data-testid="profile.join-calls">
        <span className="track">
          <span className="knob" />
        </span>
        Join projects started on my behalf
      </button>
      <p data-testid="profile.join-calls.note">
        A member, from its start, of every project a session outside Pilot starts here. Off, only of one started for
        you by name.
      </p>
    </>
  );
}
