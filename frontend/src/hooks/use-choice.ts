/**
 * A one-ask item's choice before its Send (F32.3): a press only chooses, an option or the field,
 * Other's or a No's, whose words are the choice while it stands open, and whose cross gives back
 * the option chosen before it. The browser keeps the choice as it keeps unsent words (F133), so a
 * reload shows it again, and every screen that draws the block shows the same one; the record sees
 * nothing of it until the block's Send.
 */

import { useState, useSyncExternalStore } from 'react';
import { keepUnsentChoice, unsentChoice, type Choice } from '@/lib/browser-state';

/** Each block's choice as last read or kept, by the block's key. */
const choices = new Map<string, Choice | null>();
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function chosenIn(field: string): Choice | null {
  if (!choices.has(field)) choices.set(field, unsentChoice(field));
  return choices.get(field)!;
}

function keep(field: string, choice: Choice | null): void {
  choices.set(field, choice);
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
  const choice = useSyncExternalStore(subscribe, () => chosenIn(field));
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
