/**
 * An item's own marks from the page, the record's writes: Read on a notice (F23.1), *Send answers*
 * on a document, its Done, which records every unanswered recommended block first (F24.3, F32.5,
 * D026), Reviewed on a review (F25.2), and Undo on a done item's answer or mark while the record
 * offers it (F14.1). Every screen reads them again. Their form events are `timeline.read`'s,
 * `timeline.send`'s, `timeline.reviewed`'s and `timeline.undo`'s.
 */

import {
  usePostItemsDoneByItemId,
  usePostItemsReadByItemId,
  usePostItemsReviewedByItemId,
  usePostItemsUndoByItemId,
} from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

type Mutation =
  | ReturnType<typeof usePostItemsReadByItemId>
  | ReturnType<typeof usePostItemsDoneByItemId>
  | ReturnType<typeof usePostItemsReviewedByItemId>
  | ReturnType<typeof usePostItemsUndoByItemId>;

/** `onMarked` runs once the record holds the mark. */
function useMark(mutation: Mutation, form: string, itemId: string, onMarked?: () => void) {
  const fields = { item: itemId };
  const mark = () => {
    trackFormSubmit(form, fields);
    mutation.mutate(
      { path: { item_id: itemId } },
      {
        onSuccess: () => {
          trackFormSuccess(form, fields);
          onMarked?.();
        },
        onError: () => trackFormError(form, fields),
      },
    );
  };
  // From the click until the screens read the item back.
  return { mark, pending: mutation.isPending || mutation.isSuccess };
}

export function useRead(itemId: string) {
  return useMark(usePostItemsReadByItemId(), 'timeline.read', itemId);
}

export function useSend(itemId: string, onSent?: () => void) {
  return useMark(usePostItemsDoneByItemId(), 'timeline.send', itemId, onSent);
}

export function useReviewed(itemId: string) {
  return useMark(usePostItemsReviewedByItemId(), 'timeline.reviewed', itemId);
}

export function useUndo(itemId: string) {
  return useMark(usePostItemsUndoByItemId(), 'timeline.undo', itemId);
}
