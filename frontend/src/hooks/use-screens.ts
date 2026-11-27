/**
 * Which of the two screens shows (F160.1, F160.2), from the address (`screens.ts`): off a phone the
 * dashboard where its hash names it, else Projects. Once the app is open and it has shown, the
 * dashboard is drawn for as long as the page. Projects' tab goes to the path at hand without its
 * hash, the Dashboard's to the path at hand with the hash the dashboard was left on, `#dash` before
 * it has shown. On a phone a dashboard address shows the app, its hash taken off in place, on Back
 * into such an entry too (F160.9).
 *
 * The screen out of sight shows nothing to what reads "this page shows" (F160.5): each screen says
 * under it whether it is in view (`ScreenInView`), and outside both, the top bar and what the shell
 * opens over everything, are in view always.
 */

import { createContext, useContext, useEffect, useState } from 'react';
import { useRouter, useRouterState } from '@tanstack/react-router';
import { DASH, hashOf, screenOf, type Screen } from '@/lib/screens';

export interface Screens {
  /** The screen showing. */
  shown: Screen;
  /** The dashboard has shown in this page, and so stays drawn. */
  drawn: boolean;
  /** Where each screen's tab goes. */
  href: Record<Screen, string>;
}

/** The screens on a `phone` or off one, the dashboard drawn only once the app is `open`. */
export function useScreens(phone: boolean, open: boolean): Screens {
  const router = useRouter();
  const href = useRouterState({ select: (state) => state.location.href });
  const hash = hashOf(href);
  const shown = !phone && screenOf(hash) === 'dashboard' ? 'dashboard' : 'projects';
  const [left, setLeft] = useState(DASH);
  if (shown === 'dashboard' && hash !== left) setLeft(hash);
  const [drawn, setDrawn] = useState(false);
  if (shown === 'dashboard' && open && !drawn) setDrawn(true);
  useEffect(() => {
    if (!phone) return;
    // The entry as the history holds it now: the phone's home may have been put under it.
    const { href: at, state } = router.history.location;
    const named = hashOf(at);
    if (screenOf(named) === 'dashboard') router.history.replace(at.slice(0, at.length - named.length), state);
  }, [phone, href, router]);
  const path = href.slice(0, href.length - hash.length);
  return { shown, drawn, href: { projects: path, dashboard: path + left } };
}

const ScreenInViewContext = createContext(true);

/** Says under it whether its screen is in view. */
export const ScreenInView = ScreenInViewContext.Provider;

/** Whether the screen this lies in is in view; outside both screens, true. */
export function useScreenInView(): boolean {
  return useContext(ScreenInViewContext);
}
