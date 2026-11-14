/**
 * The Cancel of a registered document a run of Pilot's put to the person, in its foot while the run
 * waits on them with nothing of it in flight and holds a block of another document (F28.9; DB 297
 * to 299): a line saying it is part of Pilot's work on that document, linking it, over a button
 * naming what it takes back. The Cancel closes every open document of the run at once, by the
 * person, and the blocks the run held are theirs again; it has no Undo, so the button asks first, in
 * its own place, as a work item's Stop does: the question names the documents the Cancel closes and
 * the blocks it gives back, with Confirm and Keep, Keep focused as it opens so that Enter pressed
 * again keeps, and Esc keeping too. Confirm is a press that writes, its icon the spinner once it has
 * waited (F148). A refusal is the query client's toast, the API's words. Its form events are
 * `overlay.cancel`'s.
 */

import { Link } from '@tanstack/react-router';
import { X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { BusyIcon } from '@/components/shared/busy-icon';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import type { ItemDocument } from '@/hooks/use-document';
import { usePress } from '@/hooks/use-press';
import { useShownProject } from '@/hooks/use-project-address';
import { useArchived } from '@/hooks/use-projects';
import { usePostItemsCancelByItemId } from '@/lib/api/generated/hooks';
import { useEscape } from '@/lib/keys';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const FORM = 'overlay.cancel';

type Cancel = NonNullable<ItemDocument['cancel']>;
type TakenBack = Cancel['takes_back'][number];

const AND = new Intl.ListFormat('en', { style: 'long', type: 'conjunction' });

/** The line, the foot's first row, and under it the button, or its question in the button's place. */
export function RunCancel({ itemId, cancel }: { itemId: string; cancel: Cancel }) {
  const { id: projectId } = useShownProject();
  const archived = useArchived(projectId);
  const mutation = usePostItemsCancelByItemId();
  const press = usePress();
  const [asking, setAsking] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const keepButton = useRef<HTMLButtonElement>(null);
  // The focus goes with the swap: onto Keep as the question opens, back onto the button once kept.
  const asked = useRef(false);
  useEffect(() => {
    if (asking) keepButton.current?.focus();
    else if (asked.current) button.current?.focus();
    asked.current = asking;
  }, [asking]);
  // From the click until the document is read back as done, which takes the Cancel away.
  const busy = press.held !== null || mutation.isPending || mutation.isSuccess;
  const keep = () => {
    if (!busy) setAsking(false);
  };
  useEscape('menu', asking, keep);
  const fields = { item: itemId };
  const run = () => {
    press.run(() => {
      trackFormSubmit(FORM, fields);
      return mutation.mutateAsync({ path: { item_id: itemId } }).then(
        () => trackFormSuccess(FORM, fields),
        () => trackFormError(FORM, fields),
      );
    });
  };
  const names = unique(cancel.takes_back.map((each) => `“${nameOf(each)}”`));
  return (
    <>
      <p className="run-cancel-line" data-testid="overlay.cancel.line">
        Pilot asks this as part of its work on <Documents cancel={cancel} />.
      </p>
      {asking ? (
        <div className="run-cancel-confirm" data-testid="overlay.cancel.confirm">
          <span className="confirm-text" data-testid="overlay.cancel.confirm.text">
            {question(cancel, names)}
          </span>
          <button type="button" className="btn btn-sm btn-danger" disabled={busy} onClick={run} data-testid="overlay.cancel.confirm.yes">
            <BusyIcon busy={busy}>
              <X className="icon" aria-hidden="true" />
            </BusyIcon>
            Confirm
          </button>
          <button ref={keepButton} type="button" className="btn btn-sm" disabled={busy} onClick={keep} data-testid="overlay.cancel.confirm.keep">
            Keep
          </button>
        </div>
      ) : (
        <button
          ref={button}
          type="button"
          className="btn run-cancel"
          onClick={() => setAsking(true)}
          disabled={archived}
          title="End that work: this document and every other it put to you close, and what it holds is yours again"
          data-testid="overlay.cancel"
        >
          <X className="icon" aria-hidden="true" />
          Cancel and take back {AND.format(names)}
        </button>
      )}
    </>
  );
}

/** The question's words: the documents the Cancel closes, this one first, and the blocks it gives back, by their names. */
function question(cancel: Cancel, names: string[]): string {
  const closed = AND.format(['This document', ...cancel.also_closes.map(({ title }) => `“${title}”`)]);
  const close = cancel.also_closes.length === 0 ? 'closes' : 'close';
  return `End that work? ${closed} ${close} for good, with no Undo, and ${AND.format(names)} ${names.length === 1 ? 'is' : 'are'} yours again.`;
}

/** The documents whose blocks it takes back, each linking its address, in their order. */
function Documents({ cancel }: { cancel: Cancel }) {
  const { address } = useShownProject();
  const documents = [...new Map(cancel.takes_back.map(({ document }) => [document.id, document])).values()];
  const replace = useTabReplace();
  return AND.formatToParts(documents.map(({ id }) => id)).map((part, index) => {
    if (part.type === 'literal') return part.value;
    const document = documents.find(({ id }) => id === part.value)!;
    return (
      <Link
        key={index}
        to="/projects/$address/documents/$documentId"
        params={{ address, documentId: document.id }}
        replace={replace}
        className="link"
        data-testid="overlay.cancel.link"
      >
        {document.title}
      </Link>
    );
  });
}

/** What the button calls a block: its own section's heading, else its document's title. */
const nameOf = (block: TakenBack): string => block.heading ?? block.document.title;

const unique = (names: string[]): string[] => [...new Set(names)];
