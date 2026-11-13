/**
 * A one-ask item's choice before its Send (F32.3): a press only chooses, an option or the field,
 * Other's or a No's, whose words are the choice while it stands open, and whose cross gives back
 * the option chosen before it. The browser keeps the choice as it keeps unsent words (F133), so a
 * reload shows it again, and every screen that draws the block shows the same one; the record sees
 * nothing of it until the block's Send. A done item keeps none: a choice made here on an item
 * answered elsewhere since is dropped, so that an Undo brings the item back with nothing chosen.
 */

import { useEffect, useState, useSyncExternalStore } from 'react';
import { keepUnsentChoice, unsentChoices, type Choice } from '@/lib/browser-state';

/** Each block's choice as the browser kept it at the page's load and as kept since, by the block's key. */
const choices = unsentChoices();
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function keep(field: string, choice: Choice | null): void {
  if (choice === null) choices.delete(field);
  else choices.set(field, choice);
  keepUnsentChoice(field, choice);
  listeners.forEach((listener) => listener());
}

export interface Choosing {
  /** The option chosen; under an open field, the one its cross gives back. None while none is. */
  answer: string | null;
  /** The field stands open: its words are the choice. */
  typing: boolean;
  /** The field was opened by a press on this screen, which gives it the focus; one a reload shows again takes none. */
  opened: boolean;
  /** Chooses an option, closing the field. */
  choose: (answer: string) => void;
  /** Opens the field. */
  type: () => void;
  /** Closes the field: the option chosen before it is the choice again. */
  back: () => void;
  /** The choice was sent: nothing is chosen. */
  sent: () => void;
}

/** `field` is the block's key, which its fields keep their unsent words under. */
export function useChoice(field: string): Choosing {
  const choice = useSyncExternalStore(subscribe, () => choices.get(field) ?? null);
  const [opened, setOpened] = useState(false);
  const answer = choice?.answer ?? null;
  return {
    answer,
    typing: choice?.typing ?? false,
    opened,
    choose: (option) => keep(field, { answer: option, typing: false }),
    type: () => {
      setOpened(true);
      keep(field, { answer, typing: true });
    },
    back: () => keep(field, answer === null ? null : { answer, typing: false }),
    sent: () => keep(field, null),
  };
}

/** Drops the choice kept for the block `field` of a done item; null where the item is open or holds no one ask. */
export function useNoChoice(field: string | null): void {
  useEffect(() => {
    if (field !== null && choices.has(field)) keep(field, null);
  }, [field]);
}
