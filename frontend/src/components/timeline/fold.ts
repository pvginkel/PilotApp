/**
 * An open item's fold on the timeline (F12.3): the kind's label in its head folds it in its place,
 * and a press or Enter anywhere on it folded unfolds it. The fold is the item's, the record's, the
 * same for every member: each press is a write, and the screens read the item back. The timeline
 * alone offers it; an item drawn anywhere else, an item alone or an opened document, has no fold.
 * An archived project's items keep the folds they were left with and take neither (D012). One
 * press at a time: another while one is on its way does nothing. Their form events are
 * `timeline.fold`'s and `timeline.unfold`'s.
 */

import { createContext, useCallback, useContext, useRef } from 'react';
import { useArchived } from '@/hooks/use-projects';
import { usePostItemsFoldByItemId, usePostItemsUnfoldByItemId } from '@/lib/api/generated/hooks';
import { UNTIL_READ } from '@/lib/api/until-read';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

interface Folds {
  fold: (itemId: string) => void;
  unfold: (itemId: string) => void;
  /** The project is archived: its folds show and take no press. */
  archived: boolean;
  /** Whether this browser's latest press folded or unfolded the item, asked once, by its box as it draws the change. */
  pressedOn: (itemId: string) => boolean;
}

/** The timeline's folds; null wherever an item is drawn off the timeline. */
export const FoldsContext = createContext<Folds | null>(null);

export const useFolds = () => useContext(FoldsContext);

/** The folds of the project's timeline, for its items. */
export function useTimelineFolds(projectId: string): Folds {
  const archived = useArchived(projectId);
  const folding = usePostItemsFoldByItemId(UNTIL_READ);
  const unfolding = usePostItemsUnfoldByItemId(UNTIL_READ);
  const pressed = useRef<string | null>(null);
  // From the press until the screens have read it back.
  const pending = folding.isPending || unfolding.isPending;
  const pressedOn = useCallback((itemId: string) => {
    if (pressed.current !== itemId) return false;
    pressed.current = null;
    return true;
  }, []);
  const press = (mutation: typeof folding, form: string, itemId: string) => {
    if (pending || archived) return;
    const fields = { item: itemId };
    pressed.current = itemId;
    trackFormSubmit(form, fields);
    mutation.mutate(
      { path: { item_id: itemId } },
      {
        onSuccess: () => trackFormSuccess(form, fields),
        onError: () => {
          pressed.current = null;
          trackFormError(form, fields);
        },
      },
    );
  };
  return {
    fold: (itemId) => press(folding, 'timeline.fold', itemId),
    unfold: (itemId) => press(unfolding, 'timeline.unfold', itemId),
    archived,
    pressedOn,
  };
}
