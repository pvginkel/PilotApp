/**
 * A person's answer to a block from the page, saved as given, through the app (F32.1); on a
 * one-ask item it is the item's done (F32.3), and every screen reads it again. Its form events are
 * `timeline.answer`'s.
 */

import { usePostItemsBlocksAnswerByItemIdAndBlockId } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const FORM_ID = 'timeline.answer';

export function useAnswer(itemId: string, blockId: string) {
  // The generated hook reads every query again once the answer is saved.
  const mutation = usePostItemsBlocksAnswerByItemIdAndBlockId();
  /** `onSaved` runs once the record holds the answer. */
  const answer = (text: string, onSaved?: () => void) => {
    const fields = { item: itemId, block: blockId, answer: text };
    trackFormSubmit(FORM_ID, fields);
    mutation.mutate(
      { path: { item_id: itemId, block_id: blockId }, body: { answer: text } },
      {
        onSuccess: () => {
          trackFormSuccess(FORM_ID, fields);
          onSaved?.();
        },
        onError: () => trackFormError(FORM_ID, fields),
      },
    );
  };
  // The answer from its click on, until the screens read it back; an answer refused is none.
  const saving = mutation.isPending || mutation.isSuccess ? mutation.variables!.body.answer : null;
  return { answer, saving };
}
