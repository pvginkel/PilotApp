/**
 * A busy button's icon (F148): once its press has waited a third of a second, the spinner, Lucide's
 * loader turning, in the icon's place until the press ends, so that a quick write never flashes
 * one. A button with no icon has the spinner alone, at its start; an option row, at its end. On a
 * button that starts Pilot's work, `starts`, the icon gives way to the job's mark under the mouse
 * until the spinner takes its place (F59.3; job-glyph.tsx).
 */

import { useEffect, useState, type ReactNode } from 'react';
import { LoaderCircle } from 'lucide-react';
import { StartsWork } from '@/components/shared/job-glyph';

/** How long a press waits before its spinner shows, in milliseconds. */
const SPIN_AFTER = 333;

interface BusyIconProps {
  busy: boolean;
  /** The press starts Pilot's work: every such button has an icon. */
  starts?: boolean;
  children?: ReactNode;
}

export function BusyIcon({ busy, starts = false, children = null }: BusyIconProps) {
  if (useWaited(busy)) return <LoaderCircle className="icon spinner animate-spin" aria-hidden="true" />;
  return starts ? <StartsWork>{children}</StartsWork> : children;
}

/** Whether `busy` has held for SPIN_AFTER. */
function useWaited(busy: boolean): boolean {
  const [waited, setWaited] = useState(false);
  useEffect(() => {
    if (!busy) return undefined;
    const timer = window.setTimeout(() => setWaited(true), SPIN_AFTER);
    return () => {
      window.clearTimeout(timer);
      setWaited(false);
    };
  }, [busy]);
  return busy && waited;
}
