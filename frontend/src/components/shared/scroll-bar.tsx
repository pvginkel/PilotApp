/**
 * A pane's drawn scrollbar (P-269): the pane hides its own (`scroll-view`), and this one floats over
 * its right edge, the pane's sibling in a positioned box that holds both, taking none of its width,
 * so that nothing reflows as it shows. The pane scrolls as the browser scrolls it, by the wheel, a
 * touch, the keys and a script alike.
 *
 * It is drawn while the pane's content overflows it, and shows while the mouse is over what holds
 * it, the focus is in that from the keyboard, its thumb is dragged, and for 800 ms after any scroll,
 * so that a touch screen shows it too; its thumb widens under the mouse. The thumb is dragged with
 * the pointer, a press on the track pages towards it, and the wheel over the bar scrolls the pane,
 * the wheel's event sent on to the pane. A press on the bar sends the pane `BAR_PRESS`.
 */

import { useEffect, useRef, type RefObject } from 'react';
import { smoothly } from '@/lib/motion';
import { BAR_PRESS } from '@/lib/scroll-bar';

/** The thumb's least length, in pixels. */
const MIN_THUMB = 32;
/** How long the bar shows after a scroll, in milliseconds. */
const SHOWN_AFTER_SCROLL = 800;
/** What a press on the track scrolls, as a share of the pane's height. */
const PAGE = 0.875;
/** A wheel's line, where the wheel counts in lines, in pixels. */
const LINE = 40;

interface ScrollBarProps {
  /** The pane it scrolls: its sibling. */
  view: RefObject<HTMLElement | null>;
  testId: string;
}

export function ScrollBar({ view, testId }: ScrollBarProps) {
  const bar = useRef<HTMLDivElement>(null);
  const thumb = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const pane = view.current!;
    const track = bar.current!;
    const grip = thumb.current!;
    let frame = 0;
    let fade = 0;
    let drag: { from: number; top: number } | null = null;

    const place = () => {
      frame = 0;
      const { scrollTop, scrollHeight, clientHeight } = pane;
      const over = scrollHeight - clientHeight;
      track.hidden = over < 1;
      if (track.hidden) return;
      const length = track.clientHeight;
      const size = Math.min(length, Math.max(MIN_THUMB, (length * clientHeight) / scrollHeight));
      grip.style.height = `${size}px`;
      grip.style.transform = `translateY(${Math.min(1, scrollTop / over) * (length - size)}px)`;
    };
    const schedule = () => {
      if (frame === 0) frame = requestAnimationFrame(place);
    };

    const onScroll = () => {
      schedule();
      track.toggleAttribute('data-scrolled', true);
      clearTimeout(fade);
      fade = window.setTimeout(() => track.toggleAttribute('data-scrolled', false), SHOWN_AFTER_SCROLL);
    };

    const onPress = (event: PointerEvent) => {
      if (event.button !== 0) return;
      // No selection starts and the focus stays where it is, as on a press on the browser's bar.
      event.preventDefault();
      pane.dispatchEvent(new Event(BAR_PRESS));
      if (event.target === grip) {
        drag = { from: event.clientY, top: pane.scrollTop };
        track.setPointerCapture(event.pointerId);
        track.toggleAttribute('data-dragging', true);
        return;
      }
      const above = event.clientY < grip.getBoundingClientRect().top;
      pane.scrollBy({ top: (above ? -PAGE : PAGE) * pane.clientHeight, behavior: smoothly() });
    };
    const onMove = (event: PointerEvent) => {
      if (drag === null) return;
      const room = track.clientHeight - grip.offsetHeight;
      if (room <= 0) return;
      pane.scrollTop = drag.top + ((event.clientY - drag.from) * (pane.scrollHeight - pane.clientHeight)) / room;
    };
    const onRelease = () => {
      drag = null;
      track.toggleAttribute('data-dragging', false);
    };

    // The pane hears the wheel as if it were over it, and what none of its listeners cancels
    // scrolls it: an event a script sends scrolls nothing itself.
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey) return;
      event.preventDefault();
      event.stopPropagation();
      const { deltaX, deltaY, deltaZ, deltaMode, clientX, clientY, screenX, screenY, shiftKey, altKey, metaKey } = event;
      const forwarded = new WheelEvent('wheel', {
        bubbles: true,
        cancelable: true,
        deltaX,
        deltaY,
        deltaZ,
        deltaMode,
        clientX,
        clientY,
        screenX,
        screenY,
        shiftKey,
        altKey,
        metaKey,
      });
      if (!pane.dispatchEvent(forwarded)) return;
      const unit = deltaMode === WheelEvent.DOM_DELTA_PIXEL ? 1 : deltaMode === WheelEvent.DOM_DELTA_LINE ? LINE : pane.clientHeight;
      pane.scrollBy({ top: deltaY * unit });
    };

    // The pane's height and its content's: each child of the pane is watched, those it gains too.
    const sizes = new ResizeObserver(schedule);
    const watch = () => {
      sizes.disconnect();
      sizes.observe(pane);
      sizes.observe(track);
      for (const child of pane.children) sizes.observe(child);
    };
    watch();
    const children = new MutationObserver(watch);
    children.observe(pane, { childList: true });

    pane.addEventListener('scroll', onScroll, { passive: true });
    track.addEventListener('pointerdown', onPress);
    track.addEventListener('pointermove', onMove);
    track.addEventListener('lostpointercapture', onRelease);
    track.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(fade);
      sizes.disconnect();
      children.disconnect();
      pane.removeEventListener('scroll', onScroll);
      track.removeEventListener('pointerdown', onPress);
      track.removeEventListener('pointermove', onMove);
      track.removeEventListener('lostpointercapture', onRelease);
      track.removeEventListener('wheel', onWheel);
    };
  }, [view]);

  return (
    <div ref={bar} className="scrollbar" aria-hidden="true" hidden data-testid={testId}>
      <div ref={thumb} className="scrollbar-thumb" data-testid={`${testId}.thumb`} />
    </div>
  );
}
