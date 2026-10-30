/**
 * A popover that drops from its button (the mockup's `.plan-pop`): it closes on a press outside
 * it, on Esc, on its button, and on an action in it that calls `close`; it scrolls inside the
 * window.
 */

import { useCallback, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { useDismiss } from '@/hooks/use-dismiss';
import { cn } from '@/lib/utils';

interface PopoverProps {
  /** The popover's accessible name. */
  label: string;
  /** The class of the box that holds the button and the popover. */
  anchorClassName?: string;
  className: string;
  testId: string;
  trigger: (state: { open: boolean; toggle: () => void }) => ReactNode;
  children: ReactNode | ((close: () => void) => ReactNode);
}

/** The head's popovers stand in Esc's order where the plan does. */
export function Popover({ label, anchorClassName, className, testId, trigger, children }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const anchor = useDismiss('plan', open, close);
  const pop = useRef<HTMLDivElement>(null);

  // It runs to 12px above the bottom of the window, and scrolls past that.
  useLayoutEffect(() => {
    if (open && pop.current) {
      pop.current.style.maxHeight = `${window.innerHeight - pop.current.getBoundingClientRect().top - 12}px`;
    }
  }, [open]);

  return (
    <div className={cn('popover-anchor', anchorClassName)} ref={anchor}>
      {trigger({ open, toggle: () => setOpen(!open) })}
      {open && (
        <div ref={pop} className={cn('popover', className)} role="dialog" aria-label={label} data-testid={testId}>
          {typeof children === 'function' ? children(close) : children}
        </div>
      )}
    </div>
  );
}
