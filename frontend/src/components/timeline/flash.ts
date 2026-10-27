/**
 * What flashes on the timeline, each once until its animation ends: an item that arrived or that
 * the reader was taken to, by its id, and a block the reader was taken to, by `<item>/<block>`
 * (F8.2, F97). The overlay flashes the blocks it is taken to on its own, the Chat tab, or a draft's
 * definition chat, the message *In the chat* takes it to (F42.3), and a draft's Draft tab the ask it
 * is taken to. Elsewhere nothing flashes. A block on the page is gone to as an address goes to it,
 * from a segment of its document's bar (F33).
 */

import { createContext, useCallback, useContext, useState, type AnimationEvent } from 'react';

interface Flashing {
  fresh: ReadonlySet<string>;
  flashed: (key: string) => void;
}

export const FlashContext = createContext<Flashing>({ fresh: new Set(), flashed: () => undefined });

/** Takes the reader to a block on the page, and flashes it. */
export const GoToContext = createContext<(itemId: string, blockId: string) => void>(() => undefined);

export const blockKey = (itemId: string, blockId: string) => `${itemId}/${blockId}`;

/** Whether the block flashes, and the handler that ends it on its own animation's end. */
export function useBlockFlash(itemId: string, blockId: string) {
  const { fresh, flashed } = useContext(FlashContext);
  const key = blockKey(itemId, blockId);
  return {
    flashing: fresh.has(key),
    onAnimationEnd: (event: AnimationEvent) => {
      if (event.target === event.currentTarget) flashed(key);
    },
  };
}

/** Flashes kept by a page of its own: `flash` starts a key's, again if it is flashing. */
export function useFlashes() {
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set());
  const flashed = useCallback((key: string) => setFresh((current) => new Set([...current].filter((other) => other !== key))), []);
  const flash = useCallback(
    (key: string) => {
      flashed(key);
      // Back on two frames later, once a frame has been drawn without it, so its animation starts again.
      requestAnimationFrame(() => requestAnimationFrame(() => setFresh((current) => new Set([...current, key]))));
    },
    [flashed],
  );
  return { fresh, flashed, flash };
}
