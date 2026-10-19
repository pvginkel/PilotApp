/**
 * The shell's keys (F110): `?` opens the keys list, and Esc closes the top-most open thing, one
 * per press, in ui-conventions.md's order ("Keys"). Neither acts in a text field, nor with a
 * modifier held.
 */

import { useEffect, useRef } from 'react';

// Bottom to top: Esc closes the highest layer open, and within a layer the one opened last.
// A menu shares its layer with Stop's confirmation; the panel is the one that lies over the
// overlay.
const LAYERS = ['overlay', 'panel', 'plan', 'menu', 'dialog', 'keys'] as const;
type EscapeLayer = (typeof LAYERS)[number];

interface OpenThing {
  layer: number;
  opened: number;
  close: () => void;
}

const openThings = new Set<OpenThing>();
let openings = 0;

/** While `isOpen`, the thing is Esc's to close when it is the top-most. */
export function useEscape(layer: EscapeLayer, isOpen: boolean, close: () => void): void {
  const closeRef = useRef(close);
  useEffect(() => {
    closeRef.current = close;
  });
  useEffect(() => {
    if (!isOpen) return undefined;
    const thing = { layer: LAYERS.indexOf(layer), opened: ++openings, close: () => closeRef.current() };
    openThings.add(thing);
    return () => {
      openThings.delete(thing);
    };
  }, [layer, isOpen]);
}

function topMost(): OpenThing | undefined {
  let top: OpenThing | undefined;
  for (const thing of openThings) {
    if (!top || thing.layer > top.layer || (thing.layer === top.layer && thing.opened > top.opened)) top = thing;
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
