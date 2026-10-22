/**
 * What flashes on the timeline, each once until its animation ends: an item that arrived or that
 * the reader was taken to, by its id, and a block the reader was taken to, by `<item>/<block>`
 * (F8.2, F97). Outside a timeline nothing flashes.
 */

import { createContext, useContext, type AnimationEvent } from 'react';

interface Flashing {
  fresh: ReadonlySet<string>;
  flashed: (key: string) => void;
}

export const FlashContext = createContext<Flashing>({ fresh: new Set(), flashed: () => undefined });

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
