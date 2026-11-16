/**
 * Taking the offer of Pilot's note on an action (F168.7): one press records who took it, and when,
 * and places Pilot's job that starts the offered work, naming the note the page shows, so that a
 * note replaced meanwhile refuses it. The action stays the person's, with its Done. It is a press
 * that writes, one at a time across the app (use-press.ts); every screen reads it again. Its form
 * events are `timeline.offer`'s.
 */

import { usePress } from '@/hooks/use-press';
import { usePostItemsBlocksOfferByItemIdAndBlockId } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const FORM = 'timeline.offer';

export function useOffer(itemId: string, blockId: string, noteId: number) {
  const mutation = usePostItemsBlocksOfferByItemIdAndBlockId();
  const press = usePress();
  const fields = { item: itemId, block: blockId };
  const take = () => {
    press.run(() => {
      trackFormSubmit(FORM, fields);
      // The query client toasts a refusal (UI-2).
      return mutation.mutateAsync({ path: { item_id: itemId, block_id: blockId }, body: { note_id: noteId } }).then(
        () => trackFormSuccess(FORM, fields),
        () => trackFormError(FORM, fields),
      );
    });
  };
  // From the press until the screens read the offer back taken.
  return { take, pending: press.held !== null || mutation.isPending || mutation.isSuccess };
}
