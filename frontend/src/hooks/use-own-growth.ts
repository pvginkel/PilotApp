/**
 * Whether what a scrolling view's content laid out last is the reader's own: a press of a control
 * inside it — a button, a summary, an element in a button's role — opens or closes something there,
 * and a change of the content's size up to the second frame after the press is that press's. Any
 * other growth is an arrival: an item, streamed text, a fold settling. Only an arrival takes a view
 * at its end with it; the reader's own expand or collapse leaves the top of what they read where it
 * stands.
 */

import { useCallback, useEffect, useRef, type RefObject } from 'react';

const CONTROLS = 'button, summary, [role="button"]';

export function useOwnGrowth(container: RefObject<HTMLElement | null>): () => boolean {
  const own = useRef(false);

  useEffect(() => {
    const box = container.current!;
    let frame = 0;
    // A `ResizeObserver` reports a press's layout in the frame after it, after that frame's
    // animation callbacks: the second frame's lets go.
    const onPress = (event: MouseEvent) => {
      if (!(event.target instanceof Element) || event.target.closest(CONTROLS) === null) return;
      own.current = true;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        frame = requestAnimationFrame(() => {
          own.current = false;
        });
      });
    };
    box.addEventListener('click', onPress, true);
    return () => {
      box.removeEventListener('click', onPress, true);
      cancelAnimationFrame(frame);
      own.current = false;
    };
  }, [container]);

  return useCallback(() => own.current, []);
}
