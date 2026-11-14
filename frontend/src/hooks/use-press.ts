/**
 * The app's one press that writes (F148): from a press until its write settles, another press that
 * writes does nothing, wherever it is on the page. Its button is disabled from the press, and its
 * icon turns to the spinner once it has waited (busy-icon.tsx).
 */

import { useState, useSyncExternalStore } from 'react';

interface Hold {
  owner: object;
  key: string;
}

let hold: Hold | null = null;
const listeners = new Set<() => void>();

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

const set = (next: Hold | null) => {
  hold = next;
  for (const listener of listeners) listener();
};

interface Press {
  /**
   * Runs `write` as the app's one press, under `key`, and answers its promise; while another press
   * waits, it does nothing and answers null.
   */
  run: <T>(write: () => Promise<T>, key?: string) => Promise<T> | null;
  /** The key this hook's press waits under, from the press until its write settles; null while none of its own does. */
  held: string | null;
}

export function usePress(): Press {
  const [owner] = useState(() => ({}));
  // A press re-renders its own owner alone.
  const held = useSyncExternalStore(subscribe, () => (hold?.owner === owner ? hold.key : null));
  const run = <T>(write: () => Promise<T>, key = ''): Promise<T> | null => {
    if (hold !== null) return null;
    set({ owner, key });
    const written = write();
    const release = () => set(null);
    written.then(release, release);
    return written;
  };
  return { run, held };
}
