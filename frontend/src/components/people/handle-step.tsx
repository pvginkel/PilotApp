/**
 * The handle step (F137): at a first sign-in it stands under the top bar, on a phone under its
 * block of colour, in place of the app, which opens once the person has chosen their handle. Its
 * Choose is a press that writes, the spinner at its start once it has waited (F148). A refused
 * handle's reason is the API's, toasted by the query client.
 */

import { useEffect, useId, useState, type FormEvent } from 'react';
import { BusyIcon } from '@/components/shared/busy-icon';
import { usePress } from '@/hooks/use-press';
import type { Self } from '@/hooks/use-self';
import { usePostPeopleSelfHandle } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormOpen, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const FORM_ID = 'people.handle';

export function HandleStep({ self }: { self: Self }) {
  const [handle, setHandle] = useState(self.handle_prefill ?? '');
  const choose = usePostPeopleSelfHandle();
  const press = usePress();
  // Disabled once chosen too, while the person is read again with their handle.
  const busy = press.held !== null || choose.isPending || choose.isSuccess;
  const formId = useId();
  useEffect(() => trackFormOpen(FORM_ID), []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    press.run(() => {
      trackFormSubmit(FORM_ID, { handle });
      return choose.mutateAsync({ body: { handle } }).then(
        () => trackFormSuccess(FORM_ID, { handle }),
        () => trackFormError(FORM_ID, { handle }),
      );
    });
  };

  return (
    <main className="people-page" data-testid="people.handle-step">
      <section>
        <h1>Choose your handle</h1>
        <p>The short name that stands for you in Pilot&rsquo;s files.</p>
        <p id={formId}>Lower-case letters, digits and hyphens. Once chosen, it cannot be changed.</p>
        {/* Enter in the field submits the form: a handle holds no line break. */}
        <form className="field-row" onSubmit={submit}>
          <input
            className="field"
            aria-label="Handle"
            aria-describedby={formId}
            value={handle}
            onChange={(event) => setHandle(event.target.value)}
            autoFocus
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            data-testid="people.handle-step.field"
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={handle === '' || busy}
            data-testid="people.handle-step.choose"
          >
            <BusyIcon busy={busy} />
            Choose
          </button>
        </form>
      </section>
    </main>
  );
}
