/**
 * The keyboard focus handed on from a pressed button to the one drawn in its place, where the
 * press takes the pressed one away: `keep` holds a button under its key, and `hand`, called as one
 * is pressed, names the key of the one that takes the focus once it is drawn.
 */

import { useEffect, useRef, type RefCallback } from 'react';

export function useHandedFocus() {
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const next = useRef<string | null>(null);
  useEffect(() => {
    if (next.current === null) return;
    buttons.current.get(next.current)?.focus({ preventScroll: true });
    next.current = null;
  });
  return {
    keep:
      (key: string): RefCallback<HTMLButtonElement> =>
      (button) => {
        if (button === null) buttons.current.delete(key);
        else buttons.current.set(key, button);
      },
    hand: (key: string) => {
      next.current = key;
    },
  };
}
