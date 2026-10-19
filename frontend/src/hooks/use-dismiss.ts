/** How a menu or a popover closes: on a press outside it, and on Esc while it is the top-most. */

import { useEffect, useRef, type RefObject } from 'react';
import { useEscape } from '@/lib/keys';

/**
 * While `open`, a press outside the element the ref is put on, or Esc when it is the top-most
 * open thing of `layer`, calls `close`.
 */
export function useDismiss(layer: 'plan' | 'menu', open: boolean, close: () => void): RefObject<HTMLDivElement | null> {
  const anchor = useRef<HTMLDivElement>(null);
  useEscape(layer, open, close);
  useEffect(() => {
    if (!open) return undefined;
    const onPress = (event: PointerEvent) => {
      if (!anchor.current?.contains(event.target as Node)) close();
    };
    document.addEventListener('pointerdown', onPress);
    return () => document.removeEventListener('pointerdown', onPress);
  }, [open, close]);
  return anchor;
}
