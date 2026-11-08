import { useEffect, useLayoutEffect, useRef, useState } from 'react';

/** The least time a held text stands once shown (C1). */
const HOLD_MS = 200;

/**
 * A line's text held for a moment (C1), `key` telling one text from another: once the text
 * differs from the one shown, the line waits HOLD_MS and then shows the text as it is then. A text
 * shown so stands at least HOLD_MS, one that came and went within the wait is never shown, and the
 * wait does not start over on a change, so the line moves on every HOLD_MS however fast its text
 * changes.
 */
export function useHeld<T>(value: T, key: string): T {
  const [shown, setShown] = useState({ value, key });
  const latest = useRef({ value, key });
  useLayoutEffect(() => {
    latest.current = { value, key };
  });
  const differs = shown.key !== key;
  useEffect(() => {
    if (!differs) return;
    const timer = window.setTimeout(() => setShown(latest.current), HOLD_MS);
    return () => window.clearTimeout(timer);
  }, [differs]);
  return differs ? shown.value : value;
}
