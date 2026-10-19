/**
 * The handle step (F137): at a first sign-in it stands under the top bar in place of the app,
 * which opens once the person has chosen their handle. A refused handle's reason is the API's,
 * toasted by the query client.
 */

import { useEffect, useId, useState, type FormEvent } from 'react';
import type { Self } from '@/hooks/use-self';
import { usePostPeopleSelfHandle } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormOpen, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const FORM_ID = 'people.handle';

export function HandleStep({ self }: { self: Self }) {
  const [handle, setHandle] = useState(self.handle_prefill ?? '');
  const choose = usePostPeopleSelfHandle();
  const formId = useId();
  useEffect(() => trackFormOpen(FORM_ID), []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    trackFormSubmit(FORM_ID, { handle });
    choose.mutate(
      { body: { handle } },
      {
        onSuccess: () => trackFormSuccess(FORM_ID, { handle }),
        onError: () => trackFormError(FORM_ID, { handle }),
      },
    );
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
          {/* Disabled once chosen too, while the person is read again with their handle. */}
          <button
            type="submit"
            className="btn btn-primary"
            disabled={handle === '' || choose.isPending || choose.isSuccess}
            data-testid="people.handle-step.choose"
          >
            Choose
          </button>
        </form>
      </section>
    </main>
  );
}
