/**
 * A person's answer to a block from the page, and Done on an action without options, saved as
 * given, through the app (F32.1), with its note (F17.4); on a one-ask item either is the item's
 * done (F32.3), and every screen reads it again. In a document the block takes another answer
 * once the screens have read this one back (F32.2). A draft's ask is answered in place the same
 * way, through the draft's own path (F47.4), and takes another answer as a document's does. Their
 * form events are `timeline.answer`'s and `timeline.done`'s, a draft's `draft.answer`'s and
 * `draft.done`'s.
 */

import { useRef } from 'react';
import { useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import {
  usePostItemsBlocksAnswerByItemIdAndBlockId,
  usePostItemsBlocksDoneByItemIdAndBlockId,
  usePostProjectsDraftBlocksAnswerByProjectIdAndBlockId,
  usePostProjectsDraftBlocksDoneByProjectIdAndBlockId,
} from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

type AnswerBody = components['schemas']['AnswerRequestSchema.bfdf230'];
type DoneBody = components['schemas']['ActionDoneRequestSchema.bfdf230'];

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

/** How a block takes an answer: its answer, its action's Done, and what is being saved. */
export interface Answering {
  answer: Answer;
  done: (sent?: Sent) => void;
  saving: Saving | null;
}

const given = (note: string | undefined) => (note === undefined || note.trim() === '' ? undefined : note);

/** An item's block, answered through its item. */
export function useAnswer(itemId: string, blockId: string): Answering {
  return useAnswering(
    'timeline',
    usePostItemsBlocksAnswerByItemIdAndBlockId(),
    usePostItemsBlocksDoneByItemIdAndBlockId(),
    { item_id: itemId, block_id: blockId },
    { item: itemId, block: blockId },
  );
}

/** A draft's block, answered in place through the draft (F47.4). */
export function useDraftAnswer(projectId: string, blockId: string): Answering {
  return useAnswering(
    'draft',
    usePostProjectsDraftBlocksAnswerByProjectIdAndBlockId(),
    usePostProjectsDraftBlocksDoneByProjectIdAndBlockId(),
    { project_id: projectId, block_id: blockId },
    { project: projectId, block: blockId },
  );
}

function useAnswering<Path>(
  form: 'timeline' | 'draft',
  // The generated hooks read every query again once the record holds the write.
  answering: UseMutationResult<void, Error, { path: Path; body: AnswerBody }>,
  marking: UseMutationResult<void, Error, { path: Path; body: DoneBody }>,
  path: Path,
  /** What its form events name the block by. */
  names: Record<string, string>,
): Answering {
  const queryClient = useQueryClient();
  // The block's latest write: an earlier one read back leaves a later one being saved.
  const latest = useRef(0);

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
    const fields = { ...names, ...body };
    const formId = `${form}.answer`;
    const write = ++latest.current;
    trackFormSubmit(formId, fields);
    answering.mutate(
      { path, body },
      {
        onSuccess: () => {
          trackFormSuccess(formId, fields);
          onSaved?.();
          readBack(write);
        },
        onError: () => trackFormError(formId, fields),
      },
    );
  };

  const done = ({ note, onSaved }: Sent = {}) => {
    const body = { note: given(note) };
    const fields = { ...names, ...body };
    const formId = `${form}.done`;
    const write = ++latest.current;
    trackFormSubmit(formId, fields);
    marking.mutate(
      { path, body },
      {
        onSuccess: () => {
          trackFormSuccess(formId, fields);
          onSaved?.();
          readBack(write);
        },
        onError: () => trackFormError(formId, fields),
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
