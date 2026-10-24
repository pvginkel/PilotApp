/**
 * Sticky-bottom scroll, after DesignAssistant's chat (portal/src/components/workspace/
 * chat-message-list.tsx, `useStickyBottom`): pins the scroll container to the bottom, and keeps
 * pinning as late layout grows the inner wrapper — a reply streaming in token by token, a tool's
 * result, a card opening. The reader scrolling up stops the pinning until they scroll back down.
 *
 * A `ResizeObserver` on the wrapper covers first paint and every later change. Only the reader's
 * own input lets go of the bottom: the wheel or a key moving up, or a scroll while a finger or
 * pointer is down (a drag on the scrollbar, a selection). A scroll event alone is not taken as the
 * reader's: when the content shrinks — a table's columns rebalancing as a reply streams — the
 * browser clamps the view, and the event for that comes a frame later, often after the next delta
 * has grown the content again, when it looks just like a scroll up. DesignAssistant's hook let go
 * there. A scroll down into the bottom picks the pinning up again.
 *
 * In test mode each pin is the `ui_state` `<scope>.scroll`, `{scrollTop, reason}`, the first
 * `initial`, and each change of pinning `<scope>.sticky`, `{stuck}`.
 */

import { useCallback, useEffect, useRef } from 'react';
import { isTestMode } from '@/lib/config/test-mode';
import { endUiState } from '@/lib/test/ui-state';

/** Pixels from the bottom within which the view counts as stuck to it. */
const STICKY_THRESHOLD_PX = 32;

/** The keys that scroll a page up. */
const UP_KEYS = new Set(['ArrowUp', 'PageUp', 'Home']);

const editable = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));

export function useStickyBottom(
  containerRef: React.RefObject<HTMLDivElement | null>,
  wrapperRef: React.RefObject<HTMLDivElement | null>,
  scope: string,
): { stick: () => void; unstick: () => void } {
  const stickToBottomRef = useRef(true);
  const pinnedRef = useRef(false);

  const setStuck = useCallback(
    (stuck: boolean) => {
      if (stickToBottomRef.current === stuck) return;
      stickToBottomRef.current = stuck;
      if (isTestMode()) endUiState(`${scope}.sticky`, { stuck });
    },
    [scope],
  );

  const pinToBottom = useCallback(
    (reason: 'initial' | 'resize' | 'stick') => {
      const container = containerRef.current;
      if (!container) return;
      container.scrollTop = container.scrollHeight;
      if (isTestMode()) endUiState(`${scope}.scroll`, { scrollTop: container.scrollTop, reason });
    },
    [containerRef, scope],
  );

  /** Pins to the bottom now and resumes pinning: the reader sent a message. */
  const stick = useCallback(() => {
    setStuck(true);
    pinToBottom('stick');
  }, [pinToBottom, setStuck]);

  /** Stops pinning until the reader scrolls back down: they asked for what is above. */
  const unstick = useCallback(() => setStuck(false), [setStuck]);

  useEffect(() => {
    const container = containerRef.current;
    const wrapper = wrapperRef.current;
    if (!container || !wrapper) return;

    let held = 0;
    let lastTop = container.scrollTop;
    const distance = () => container.scrollHeight - container.scrollTop - container.clientHeight;
    // The reader asks to go up, and the chat scrolls at all. (The wheel's scroll can come before
    // its event, so where the view is now says nothing.)
    const up = () => {
      if (container.scrollHeight > container.clientHeight + 1) setStuck(false);
    };

    // A drag decides by where it is; otherwise only a scroll down into the bottom picks the pinning
    // up again, for a smooth scroll up starts out near the bottom too.
    const onScroll = () => {
      const top = container.scrollTop;
      const near = distance() <= STICKY_THRESHOLD_PX;
      if (held > 0) setStuck(near);
      else if (near && top > lastTop) setStuck(true);
      lastTop = top;
    };
    const onWheel = (e: WheelEvent) => {
      if (e.deltaY < 0) up();
    };
    // A key scrolls the chat only from inside it, or with nothing focused once it was clicked.
    const onKey = (e: KeyboardEvent) => {
      const t = e.target;
      if (editable(t) || !(t === document.body || (t instanceof Node && container.contains(t)))) return;
      if (UP_KEYS.has(e.key) || (e.key === ' ' && e.shiftKey)) up();
    };
    const press = () => (held += 1);
    const release = () => (held = Math.max(0, held - 1));

    container.addEventListener('scroll', onScroll, { passive: true });
    container.addEventListener('wheel', onWheel, { passive: true });
    container.addEventListener('pointerdown', press);
    container.addEventListener('touchstart', press, { passive: true });
    // Let go anywhere: a drag leaves the container.
    window.addEventListener('pointerup', release);
    window.addEventListener('pointercancel', release);
    window.addEventListener('touchend', release);
    window.addEventListener('touchcancel', release);
    window.addEventListener('keydown', onKey);
    const observer = new ResizeObserver(() => {
      if (!stickToBottomRef.current) return;
      pinToBottom(pinnedRef.current ? 'resize' : 'initial');
      pinnedRef.current = true;
    });
    observer.observe(wrapper);

    return () => {
      container.removeEventListener('scroll', onScroll);
      container.removeEventListener('wheel', onWheel);
      container.removeEventListener('pointerdown', press);
      container.removeEventListener('touchstart', press);
      window.removeEventListener('pointerup', release);
      window.removeEventListener('pointercancel', release);
      window.removeEventListener('touchend', release);
      window.removeEventListener('touchcancel', release);
      window.removeEventListener('keydown', onKey);
      observer.disconnect();
    };
  }, [containerRef, wrapperRef, pinToBottom, setStuck]);

  return { stick, unstick };
}
