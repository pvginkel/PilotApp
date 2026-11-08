/**
 * A long text clamped (T5): cut after its first `lines` lines, Show more over the end of the last
 * one, and once opened whole, Show less after its last word, which cuts it again. A text that fits
 * shows whole, with neither. Both are buttons, so that a scrolling view takes what they open or
 * close for the reader's own (use-own-growth.ts); the one pressed hands the focus to the other.
 */

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { cn } from '@/lib/utils';

export function Clamp({ lines, children, testId }: { lines: number; children: ReactNode; testId: string }) {
  const box = useRef<HTMLDivElement>(null);
  const other = useRef<HTMLButtonElement>(null);
  const pressed = useRef(false);
  const [open, setOpen] = useState(false);
  const [long, setLong] = useState(false);

  useLayoutEffect(() => {
    if (open) return;
    const element = box.current!;
    // The observer reports the box's size when it starts, and again on every change, a narrower
    // window's included; what it cuts is what its box does not show.
    const observer = new ResizeObserver(() => setLong(element.scrollHeight > element.clientHeight));
    observer.observe(element);
    return () => observer.disconnect();
  }, [open]);

  useEffect(() => {
    if (!pressed.current) return;
    pressed.current = false;
    other.current?.focus({ preventScroll: true });
  }, [open]);

  const toggle = (opened: boolean) => {
    pressed.current = true;
    setOpen(opened);
  };

  return (
    <div ref={box} className={cn('clamp', !open && 'cut')} style={{ '--lines': lines } as CSSProperties} data-testid={testId}>
      {children}
      {long && !open && (
        <button ref={other} type="button" className="link clamp-more" onClick={() => toggle(true)} data-testid={`${testId}.more`}>
          Show more
        </button>
      )}
      {open && (
        <>
          {' '}
          <button ref={other} type="button" className="link" onClick={() => toggle(false)} data-testid={`${testId}.less`}>
            Show less
          </button>
        </>
      )}
    </div>
  );
}
