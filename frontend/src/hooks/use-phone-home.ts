/**
 * The phone's home (F98.5, F98.6), the bare address's, is the entry in the browser's history
 * under every other screen a phone shows: a project's, a new project's and the profile page lie on
 * its entry, which Back from their first entry shows, never the screen before, and which the head's
 * arrow goes back to. What opens from the home says so in its entry (`overHome`); a screen's first
 * entry that does not — its address reached cold, a notification's link among them, a link from
 * another project, a window narrowed to a phone's width — has the home's entry put under it.
 */

import { useLayoutEffect } from 'react';
import { useRouter, type HistoryState, type RouterHistory } from '@tanstack/react-router';

declare module '@tanstack/react-router' {
  interface HistoryState {
    /** The entry lies on the phone's home's, which Back shows. */
    overHome?: boolean;
    /** At the home's address, the view pushed over the home: the archived projects (F128.2). */
    homeView?: 'archived';
  }
}

/** The state of an entry opened from the home. */
export const OVER_HOME: HistoryState = { overHome: true };

/** Puts the home's entry in the place of the entry showing, and pushes `entries` over it, bottom to top. */
export function putHomeUnder(history: RouterHistory, entries: { href: string; state: HistoryState }[]): void {
  history.replace('/', {});
  for (const { href, state } of entries) {
    // The browser takes both a microtask later, as one entry, unless the first is taken now.
    history.flush();
    history.push(href, state);
  }
}

/**
 * On a phone, the entry of a screen of one entry outside a project, the profile page, lies on the
 * home's; returns the way back to it.
 */
export function useOverHome(phone: boolean): () => void {
  const router = useRouter();
  useLayoutEffect(() => {
    const { href, state } = router.history.location;
    if (!phone || state.overHome === true) return;
    putHomeUnder(router.history, [{ href, state: { ...state, overHome: true } }]);
  }, [phone, router]);
  return () => router.history.back();
}
