/**
 * A person's answer to a block from the page, and Done on an action without options, saved as
 * given, through the app (F32.1), with its note (F17.4); on a one-ask item either is the item's
 * done (F32.3), and every screen reads it again. In a document the block takes another answer
 * once the screens have read this one back (F32.2). Their form events are `timeline.answer`'s and
 * `timeline.done`'s.
 */

import { useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
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
  const queryClient = useQueryClient();
  // The block's latest write: an earlier one read back leaves a later one being saved.
  const latest = useRef(0);
  const path = { item_id: itemId, block_id: blockId };

  // By the time a write's own callbacks run, its hook has set the screens' reads going again; a
  // live event may cancel one and read again, so the write is read back once none is in flight.
  const readBack = (write: number) => {
    const settle = () => {
      if (latest.current !== write) return;
      answering.reset();
      marking.reset();
    };
    if (queryClient.isFetching() === 0) return settle();
    const unsubscribe = queryClient.getQueryCache().subscribe(() => {
      if (queryClient.isFetching() > 0) return;
      unsubscribe();
      settle();
    });
  };

  const answer: Answer = (text, { note, onSaved } = {}) => {
    const body = { answer: text, note: given(note) };
    const fields = { item: itemId, block: blockId, ...body };
    const write = ++latest.current;
    trackFormSubmit(ANSWER_FORM, fields);
    answering.mutate(
      { path, body },
      {
        onSuccess: () => {
          trackFormSuccess(ANSWER_FORM, fields);
          onSaved?.();
          readBack(write);
        },
        onError: () => trackFormError(ANSWER_FORM, fields),
      },
    );
  };

  const done = ({ note, onSaved }: Sent = {}) => {
    const body = { note: given(note) };
    const fields = { item: itemId, block: blockId, ...body };
    const write = ++latest.current;
    trackFormSubmit(DONE_FORM, fields);
    marking.mutate(
      { path, body },
      {
        onSuccess: () => {
          trackFormSuccess(DONE_FORM, fields);
          onSaved?.();
          readBack(write);
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
