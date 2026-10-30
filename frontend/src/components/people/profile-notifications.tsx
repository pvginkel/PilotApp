/**
 * The profile page's notification settings (F134): the person's notification token, the bearer of
 * their own bridge registration, set, replaced or cleared and never shown back (F94.3, F134.1), and
 * beside it the alarms switch (F142.1).
 *
 * A save is a task (API-2): the backend sends the one-shot "Pilot will notify you here" through the
 * token and stores it only once the bridge took it, so a refused token's reason shows under the
 * field it was typed in. A refused request is the query client's to toast.
 */

import { useEffect, useId, useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useSSETask } from '@/hooks/use-sse-task';
import {
  useDeletePeopleSelfNotificationToken,
  usePutPeopleSelfAlarms,
  usePutPeopleSelfNotificationToken,
} from '@/lib/api/generated/hooks';
import { trackFormError, trackFormOpen, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const TOKEN_FORM = 'people.notification-token';
const CLEAR_FORM = 'people.notification-token.clear';
const ALARMS_FORM = 'people.alarms';

/** The token field, Save and Clear, and whether a token is set. */
export function NotificationToken({ set }: { set: boolean }) {
  const queryClient = useQueryClient();
  const [token, setToken] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorId = useId();

  const task = useSSETask({
    onResult: () => {
      // The save's result is the person, a token set: read again before the form says so.
      void queryClient.invalidateQueries().then(() => {
        setSaving(false);
        setToken('');
        trackFormSuccess(TOKEN_FORM);
      });
    },
    onError: (message) => {
      setSaving(false);
      setError(message);
      trackFormError(TOKEN_FORM, { error: message });
    },
  });
  const save = usePutPeopleSelfNotificationToken();
  const clear = useDeletePeopleSelfNotificationToken({ onSuccess: () => queryClient.invalidateQueries() });
  useEffect(() => trackFormOpen(TOKEN_FORM), []);

  // The API refuses a token that is not visible ASCII: what surrounds a pasted one is no part of it.
  const trimmed = token.trim();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSaving(true);
    trackFormSubmit(TOKEN_FORM);
    save.mutate(
      { body: { token: trimmed } },
      {
        onSuccess: ({ task_id }) => task.subscribeToTask(task_id),
        onError: () => {
          setSaving(false);
          trackFormError(TOKEN_FORM);
        },
      },
    );
  };

  const remove = () => {
    setError(null);
    trackFormSubmit(CLEAR_FORM);
    clear.mutate(undefined, {
      onSuccess: () => trackFormSuccess(CLEAR_FORM),
      onError: () => trackFormError(CLEAR_FORM),
    });
  };

  return (
    <>
      <p data-testid="profile.token.state">{set ? 'A token is set.' : 'No token is set.'}</p>
      {/* Enter in the field saves: a token holds no line break. */}
      <form className="field-row" onSubmit={submit}>
        <input
          type="password"
          className="field"
          aria-label="Notification token"
          aria-invalid={error !== null}
          aria-describedby={error !== null ? errorId : undefined}
          placeholder={set ? 'Paste a token to replace it' : 'Paste your token'}
          value={token}
          onChange={(event) => {
            setToken(event.target.value);
            setError(null);
          }}
          disabled={saving}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          data-testid="profile.token.field"
        />
        <button type="submit" className="btn btn-primary" disabled={trimmed === '' || saving} data-testid="profile.token.save">
          Save
        </button>
        <button
          type="button"
          className="btn"
          disabled={!set || saving || clear.isPending}
          onClick={remove}
          data-testid="profile.token.clear"
        >
          Clear
        </button>
      </form>
      {saving && task.progress !== null && <p data-testid="profile.token.progress">{task.progress.message}</p>}
      {error !== null && (
        <p id={errorId} className="field-error" role="alert" data-testid="profile.token.error">
          {error}
        </p>
      )}
      <p>
        The token of your own registration with the notification bridge. Pilot notifies you through it of what waits on
        you in your projects; a save first sends &ldquo;Pilot will notify you here&rdquo; through it.
      </p>
    </>
  );
}

/** The alarms switch, on by default; without a token there is nothing to send, and it is disabled. */
export function AlarmsSwitch({ on, tokenSet }: { on: boolean; tokenSet: boolean }) {
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
      <button
        type="button"
        className="switch"
        role="switch"
        aria-checked={on}
        disabled={!tokenSet}
        onClick={toggle}
        data-testid="profile.alarms"
      >
        <span className="track">
          <span className="knob" />
        </span>
        Send me alarms
      </button>
      <p>
        A notification while Pilot cannot reach KubeCoder for five minutes, or while a usage limit halts the work, through
        your token.
      </p>
    </>
  );
}
