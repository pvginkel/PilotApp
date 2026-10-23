/**
 * An item's own marks from the page, the record's writes: Read on a notice (F23.1), *Send answers*
 * on a document, its Done, which records every unanswered recommended block first (F24.3, F32.5,
 * D026), and Undo on a done item's answer or mark while the record offers it (F14.1). Every screen
 * reads them again. Their form events are `timeline.read`'s, `timeline.send`'s and
 * `timeline.undo`'s.
 */

import { usePostItemsDoneByItemId, usePostItemsReadByItemId, usePostItemsUndoByItemId } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

type Mutation =
  | ReturnType<typeof usePostItemsReadByItemId>
  | ReturnType<typeof usePostItemsDoneByItemId>
  | ReturnType<typeof usePostItemsUndoByItemId>;

function useMark(mutation: Mutation, form: string, itemId: string) {
  const fields = { item: itemId };
  const mark = () => {
    trackFormSubmit(form, fields);
    mutation.mutate(
      { path: { item_id: itemId } },
      {
        onSuccess: () => trackFormSuccess(form, fields),
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

export function useSend(itemId: string) {
  return useMark(usePostItemsDoneByItemId(), 'timeline.send', itemId);
}

export function useUndo(itemId: string) {
  return useMark(usePostItemsUndoByItemId(), 'timeline.undo', itemId);
}
