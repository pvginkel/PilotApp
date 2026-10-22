/**
 * A long text folded (F12.2): cut after its first lines, fading out, until Show more unfolds it.
 * A text that fits shows whole, with no Show more.
 */

import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/lib/utils';

export function Fold({ children, testId }: { children: ReactNode; testId: string }) {
  const box = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [long, setLong] = useState(false);

  useLayoutEffect(() => {
    if (open) return;
    // The observer reports the content's height when it starts, and again on every change, a
    // narrower window's included.
    const observer = new ResizeObserver(() => setLong(content.current!.offsetHeight > box.current!.clientHeight));
    observer.observe(content.current!);
    return () => observer.disconnect();
  }, [open]);

  return (
    <>
      <div ref={box} className={cn(!open && 'fold', long && !open && 'long')} data-testid={testId}>
        <div ref={content}>{children}</div>
      </div>
      {long && !open && (
        <button type="button" className="link more" onClick={() => setOpen(true)} data-testid={`${testId}.more`}>
          Show more
        </button>
      )}
    </>
  );
}
