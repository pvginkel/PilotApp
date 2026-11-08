/**
 * The loading bar: while the router keeps the screen showing for what its successor reads
 * (`screen-reads.ts`), a thin line under the top bar, on a phone at the page's top, once the wait
 * has lasted 200 ms; a shorter wait shows none.
 */

import { useEffect, useState } from 'react';
import { useRouterState } from '@tanstack/react-router';

/** How long a wait lasts before the bar shows, in milliseconds. */
const LATE = 200;

export function LoadingBar() {
  const waiting = useRouterState({ select: (state) => state.status === 'pending' });
  const [late, setLate] = useState(false);
  useEffect(() => {
    if (!waiting) return;
    const timer = setTimeout(() => setLate(true), LATE);
    return () => {
      clearTimeout(timer);
      setLate(false);
    };
  }, [waiting]);
  if (!waiting || !late) return null;
  return <div className="loading-bar" role="progressbar" aria-label="Loading" data-testid="shell.loading" />;
}
