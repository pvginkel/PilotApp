/**
 * How a menu or a popover closes: on a press outside it, which does nothing else, and on Esc while
 * it is the top-most.
 */

import { useEffect, useRef, type RefObject } from 'react';
import { useEscape } from '@/lib/keys';

/**
 * While `open`, a press outside the element the ref is put on, or Esc when it is the top-most
 * open thing of `layer`, calls `close`. The press's click reaches nothing.
 */
export function useDismiss(layer: 'plan' | 'menu', open: boolean, close: () => void): RefObject<HTMLDivElement | null> {
  const anchor = useRef<HTMLDivElement>(null);
  useEscape(layer, open, close);
  useEffect(() => {
    if (!open) return undefined;
    const onPress = (event: PointerEvent) => {
      if (anchor.current?.contains(event.target as Node)) return;
      close();
      takeClick();
    };
    document.addEventListener('pointerdown', onPress);
    return () => document.removeEventListener('pointerdown', onPress);
  }, [open, close]);
  return anchor;
}

/**
 * Takes the click of the press in progress before anything hears it. A press that ends in no click,
 * a scroll's or another button's than the first, leaves the next press its own.
 */
function takeClick(): void {
  const drop = () => {
    document.removeEventListener('click', take, true);
    document.removeEventListener('pointercancel', drop, true);
    document.removeEventListener('pointerdown', drop, true);
  };
  const take = (event: MouseEvent) => {
    drop();
    event.preventDefault();
    event.stopPropagation();
  };
  document.addEventListener('click', take, true);
  document.addEventListener('pointercancel', drop, true);
  document.addEventListener('pointerdown', drop, true);
}
