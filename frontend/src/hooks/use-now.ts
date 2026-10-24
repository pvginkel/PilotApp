/** The page's clock (performance.now()), ticking while `active`: a live "Thinking… 4 s". */

import { useEffect, useState } from 'react';

export function useNow(active: boolean, intervalMs = 500): number {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(performance.now()), intervalMs);
    return () => clearInterval(id);
  }, [active, intervalMs]);
  return now;
}
