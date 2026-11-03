/**
 * The Cancel of a registered document a run of Pilot's put to the person, in its foot while the run
 * waits on them with nothing of it in flight and holds a block of another document (F28.9; DB 297
 * to 299): a line saying it is part of Pilot's work on that document, linking it, over a button
 * naming what it takes back. The Cancel closes every open document of the run at once, by the
 * person, and the blocks the run held are theirs again; it has no Undo. A refusal is the query
 * client's toast, the API's words. Its form events are `overlay.cancel`'s.
 */

import { Link, useParams } from '@tanstack/react-router';
import { X } from 'lucide-react';
import type { ItemDocument } from '@/hooks/use-document';
import { useArchived } from '@/hooks/use-projects';
import { usePostItemsCancelByItemId } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const FORM = 'overlay.cancel';

type Cancel = NonNullable<ItemDocument['cancel']>;
type TakenBack = Cancel['takes_back'][number];

const AND = new Intl.ListFormat('en', { style: 'long', type: 'conjunction' });

/** The line and the button, the foot's first row and the start of its second. */
export function RunCancel({ itemId, cancel }: { itemId: string; cancel: Cancel }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const archived = useArchived(projectId);
  const mutation = usePostItemsCancelByItemId();
  const fields = { item: itemId };
  const run = () => {
    trackFormSubmit(FORM, fields);
    mutation.mutate(
      { path: { item_id: itemId } },
      {
        onSuccess: () => trackFormSuccess(FORM, fields),
        onError: () => trackFormError(FORM, fields),
      },
    );
  };
  const named = AND.format(unique(cancel.takes_back.map((each) => `“${nameOf(each)}”`)));
  return (
    <>
      <p className="run-cancel-line" data-testid="overlay.cancel.line">
        Pilot asks this as part of its work on <Documents projectId={projectId} cancel={cancel} />.
      </p>
      <button
        type="button"
        className="btn run-cancel"
        onClick={run}
        // From the click until the document is read back as done, which takes the button away.
        disabled={mutation.isPending || mutation.isSuccess || archived}
        title="End that work: this document and every other it put to you close, and what it holds is yours again"
        data-testid="overlay.cancel"
      >
        <X className="icon" aria-hidden="true" />
        Cancel and take back {named}
      </button>
    </>
  );
}

/** The documents whose blocks it takes back, each linking its address, in their order. */
function Documents({ projectId, cancel }: { projectId: string; cancel: Cancel }) {
  const documents = [...new Map(cancel.takes_back.map(({ document }) => [document.id, document])).values()];
  return AND.formatToParts(documents.map(({ id }) => id)).map((part, index) => {
    if (part.type === 'literal') return part.value;
    const document = documents.find(({ id }) => id === part.value)!;
    return (
      <Link
        key={index}
        to="/projects/$projectId/documents/$documentId"
        params={{ projectId, documentId: document.id }}
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
