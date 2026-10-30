/**
 * The viewer's today, as `Date.toDateString()` gives it, read again each minute: it turns within a
 * minute of the browser's midnight, a sleep of the device's in between included.
 */

import { useEffect, useState } from 'react';

const MINUTE = 60_000;

const today = () => new Date().toDateString();

export function useToday(): string {
  const [day, setDay] = useState(today);
  useEffect(() => {
    const id = setInterval(() => setDay(today()), MINUTE);
    return () => clearInterval(id);
  }, []);
  return day;
}
