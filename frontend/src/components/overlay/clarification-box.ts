/**
 * Going to the box of Pilot's questions to a registered document's writer and the reply in the
 * overlay's body (F52.2; clarification.tsx), which flashes: at once where the overlay is opened at
 * the box's address, once the box is drawn, and on each `goTo`, an asked block's mark in the overlay.
 * The overlay's body and the box take `body` and `box` as their refs. Its effect runs in an ancestor
 * of the body, after the refs under it are attached.
 */

import { useLayoutEffect, useRef } from 'react';
import { scrollToIn } from '@/components/overlay/scroll-to';
import { useFlashes } from '@/components/timeline/flash';
import { smoothly } from '@/lib/motion';

const BOX = 'clarification';

/** `at` is the document whose box's address it is opened at; null at any other address. */
export function useClarificationBox(at: string | null) {
  const body = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const { fresh, flashed, flash } = useFlashes();
  const goTo = (behavior: ScrollBehavior) => {
    scrollToIn(body.current!, box.current!, behavior);
    flash(BOX);
  };
  // The document whose box it was opened at, once gone to.
  const reached = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (at === null) {
      reached.current = null;
      return;
    }
    if (reached.current === at || box.current === null) return;
    reached.current = at;
    goTo('instant');
  });
  return { body, box, flashing: fresh.has(BOX), onFlashed: () => flashed(BOX), goTo: () => goTo(smoothly()) };
}
