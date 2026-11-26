/**
 * The shell's keys (F110): `?` opens the keys list, and Esc closes the top-most open thing, one
 * per press, in ui-conventions.md's order ("Keys"). Neither acts in a text field, nor with a
 * modifier held: Esc in Other's field is the field's own (text-field.tsx). What is open in the
 * screen out of sight is not Esc's while it is (F160.5), but a dialog, which stands over the page
 * whichever screen shows.
 */

import { useEffect, useRef } from 'react';
import { useScreenInView } from '@/hooks/use-screens';

// Each layer's rank, bottom to top: Esc closes the highest ranked open, and within a rank the one
// opened last. Other's consoles lie under everything; a menu shares its rank with Stop's
// confirmation.
const RANKS = { console: 0, overlay: 1, plan: 2, menu: 3, dialog: 4, keys: 5 } as const;
type EscapeLayer = keyof typeof RANKS;

// A dialog's layers: a dialog is drawn in the page's body (dialog.tsx's portal), outside its
// screen's box, so it stays in sight while its screen is out of it.
const OVER_THE_PAGE: ReadonlySet<EscapeLayer> = new Set(['dialog', 'keys']);

interface OpenThing {
  rank: number;
  opened: number;
  close: () => void;
  /** Its screen is in view. */
  inView: () => boolean;
}

const openThings = new Set<OpenThing>();
let openings = 0;

/** While `isOpen`, the thing is Esc's to close when it is the top-most of what is in view. */
export function useEscape(layer: EscapeLayer, isOpen: boolean, close: () => void): void {
  const inView = useScreenInView() || OVER_THE_PAGE.has(layer);
  const closeRef = useRef(close);
  const inViewRef = useRef(inView);
  useEffect(() => {
    closeRef.current = close;
    inViewRef.current = inView;
  });
  useEffect(() => {
    if (!isOpen) return undefined;
    const thing = { rank: RANKS[layer], opened: ++openings, close: () => closeRef.current(), inView: () => inViewRef.current };
    openThings.add(thing);
    return () => {
      openThings.delete(thing);
    };
  }, [layer, isOpen]);
}

function topMost(): OpenThing | undefined {
  let top: OpenThing | undefined;
  for (const thing of openThings) {
    if (!thing.inView()) continue;
    if (!top || thing.rank > top.rank || (thing.rank === top.rank && thing.opened > top.opened)) top = thing;
  }
  return top;
}

function inTextField(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest('input, textarea, [contenteditable="true"]') !== null;
}

/** Listens for the shell's keys while the shell is mounted; `?` calls `onKeysList`. */
export function useShellKeys(onKeysList: () => void): void {
  const keysListRef = useRef(onKeysList);
  useEffect(() => {
    keysListRef.current = onKeysList;
  });
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey || inTextField(event.target)) return;
      if (event.key === '?') {
        event.preventDefault();
        keysListRef.current();
      } else if (event.key === 'Escape') {
        const top = topMost();
        if (!top) return;
        event.preventDefault();
        top.close();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);
}
