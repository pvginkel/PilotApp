/**
 * A line of a scrolling transcript kept where it stands in the view while what stands above it
 * grows: a chat loaded above by "Load previous", whose records land after the click, or the
 * message *In the chat* went to (project-chat.tsx, project-conversations.tsx). The line is one of
 * the things standing in the transcript's wrapper, or something inside one. Each change of the
 * wrapper's size moves the scroll by as much as the line moved. The reader's own input lets go of
 * it, and so does a view pinned to its end again, where the end rules.
 */

import { useCallback, useEffect, useRef, type RefObject } from 'react';
import { BAR_PRESS } from '@/lib/scroll-bar';

/** The reader's own input, a press on the drawn bar among it. */
const READER = ['wheel', 'touchstart', 'pointerdown', 'keydown', BAR_PRESS] as const;

interface KeptLine {
  /** Keeps the element where it stands now; `null` lets go of the one kept. */
  keep: (element: Element | null) => void;
  /** Keeps what stands at the top of the view, a button of the wrapper's own left out. */
  keepTop: () => void;
}

export function useKeptLine(containerRef: RefObject<HTMLDivElement | null>, wrapperRef: RefObject<HTMLDivElement | null>, stuck: boolean): KeptLine {
  const kept = useRef<{ element: Element; top: number } | null>(null);

  useEffect(() => {
    const box = containerRef.current!;
    const observer = new ResizeObserver(() => {
      const held = kept.current;
      if (held === null) return;
      if (!held.element.isConnected) {
        kept.current = null;
        return;
      }
      const moved = held.element.getBoundingClientRect().top - box.getBoundingClientRect().top - held.top;
      if (Math.abs(moved) >= 1) box.scrollTop += moved;
    });
    observer.observe(wrapperRef.current!);
    const release = () => {
      kept.current = null;
    };
    for (const event of READER) box.addEventListener(event, release, { passive: true });
    return () => {
      observer.disconnect();
      for (const event of READER) box.removeEventListener(event, release);
    };
  }, [containerRef, wrapperRef]);

  useEffect(() => {
    if (stuck) kept.current = null;
  }, [stuck]);

  const keep = useCallback(
    (element: Element | null) => {
      const box = containerRef.current;
      kept.current = element === null || box === null ? null : { element, top: element.getBoundingClientRect().top - box.getBoundingClientRect().top };
    },
    [containerRef],
  );
  const keepTop = useCallback(() => {
    const box = containerRef.current;
    const standing = wrapperRef.current;
    if (box === null || standing === null) return;
    const top = box.getBoundingClientRect().top;
    keep([...standing.children].find((child) => child.tagName !== 'BUTTON' && child.getBoundingClientRect().bottom > top) ?? null);
  }, [containerRef, wrapperRef, keep]);

  return { keep, keepTop };
}
