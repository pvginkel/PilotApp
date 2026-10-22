/**
 * A person's answer to a block from the page, and Done on an action without options, saved as
 * given, through the app (F32.1), with its note (F17.4); on a one-ask item either is the item's
 * done (F32.3), and every screen reads it again. Their form events are `timeline.answer`'s and
 * `timeline.done`'s.
 */

import { usePostItemsBlocksAnswerByItemIdAndBlockId, usePostItemsBlocksDoneByItemIdAndBlockId } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const ANSWER_FORM = 'timeline.answer';
const DONE_FORM = 'timeline.done';

export interface Sent {
  /** The note under the answer: a paste-back or a No's reason; a blank one is none. */
  note?: string;
  /** Runs once the record holds it. */
  onSaved?: () => void;
}

export type Answer = (text: string, sent?: Sent) => void;

/** What is being saved, from its click until the screens read it back; one refused is none. */
export interface Saving {
  /** The answer; null for Done. */
  answer: string | null;
  note: string | null;
}

const given = (note: string | undefined) => (note === undefined || note.trim() === '' ? undefined : note);

export function useAnswer(itemId: string, blockId: string) {
  // The generated hooks read every query again once the record holds the write.
  const answering = usePostItemsBlocksAnswerByItemIdAndBlockId();
  const marking = usePostItemsBlocksDoneByItemIdAndBlockId();
  const path = { item_id: itemId, block_id: blockId };

  const answer: Answer = (text, { note, onSaved } = {}) => {
    const body = { answer: text, note: given(note) };
    const fields = { item: itemId, block: blockId, ...body };
    trackFormSubmit(ANSWER_FORM, fields);
    answering.mutate(
      { path, body },
      {
        onSuccess: () => {
          trackFormSuccess(ANSWER_FORM, fields);
          onSaved?.();
        },
        onError: () => trackFormError(ANSWER_FORM, fields),
      },
    );
  };

  const done = ({ note, onSaved }: Sent = {}) => {
    const body = { note: given(note) };
    const fields = { item: itemId, block: blockId, ...body };
    trackFormSubmit(DONE_FORM, fields);
    marking.mutate(
      { path, body },
      {
        onSuccess: () => {
          trackFormSuccess(DONE_FORM, fields);
          onSaved?.();
        },
        onError: () => trackFormError(DONE_FORM, fields),
      },
    );
  };

  const saving: Saving | null =
    answering.isPending || answering.isSuccess
      ? { answer: answering.variables!.body.answer, note: answering.variables!.body.note ?? null }
      : marking.isPending || marking.isSuccess
        ? { answer: null, note: marking.variables!.body.note ?? null }
        : null;
  return { answer, done, saving };
}
