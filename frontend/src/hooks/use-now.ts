/**
 * The wall clock, counted again every `intervalMs` and at once when the page comes back into view:
 * a running time, a due time, "Thinking · 4 s". It is never the page's monotonic clock
 * (performance.now()), which stands still while a phone or a Linux desktop is suspended, so that a
 * page living through a suspend counts from a time behind the wall clock's.
 */

import { useEffect, useState } from 'react';

// eslint-disable-next-line no-restricted-properties -- the wall clock's time, a real timestamp
export const wallClock = () => Date.now();

export function useNow(intervalMs = 500): number {
  const [now, setNow] = useState(wallClock);
  useEffect(() => {
    const tick = () => setNow(wallClock());
    const shown = () => {
      if (document.visibilityState === 'visible') tick();
    };
    const id = setInterval(tick, intervalMs);
    document.addEventListener('visibilitychange', shown);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', shown);
    };
  }, [intervalMs]);
  return now;
}
