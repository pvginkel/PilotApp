/**
 * A busy button's icon (F148): once its press has waited a third of a second, the spinner, Lucide's
 * loader turning, in the icon's place until the press ends, so that a quick write never flashes
 * one. A button with no icon has the spinner alone, at its start; an option row, at its end.
 */

import { useEffect, useState, type ReactNode } from 'react';
import { LoaderCircle } from 'lucide-react';

/** How long a press waits before its spinner shows, in milliseconds. */
const SPIN_AFTER = 333;

export function BusyIcon({ busy, children = null }: { busy: boolean; children?: ReactNode }) {
  return useWaited(busy) ? <LoaderCircle className="icon spinner animate-spin" aria-hidden="true" /> : children;
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
