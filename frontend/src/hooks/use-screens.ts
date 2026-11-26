/**
 * Which of the two screens shows (F160.1, F160.2), from the address (`screens.ts`): the dashboard
 * where its hash names it and the page draws it, else Projects. Once it has shown, the dashboard is
 * drawn for as long as the page. Projects' tab goes to the path at hand without its hash, the
 * Dashboard's to the path at hand with the hash the dashboard was left on, `#dash` before it has
 * shown.
 */

import { useState } from 'react';
import { useRouterState } from '@tanstack/react-router';
import { DASH, hashOf, screenOf, type Screen } from '@/lib/screens';

export interface Screens {
  /** The screen showing. */
  shown: Screen;
  /** The dashboard has shown in this page, and so stays drawn. */
  drawn: boolean;
  /** Where each screen's tab goes. */
  href: Record<Screen, string>;
}

/** The screens, the dashboard shown only where `drawable`: off a phone, once the app is open. */
export function useScreens(drawable: boolean): Screens {
  const href = useRouterState({ select: (state) => state.location.href });
  const hash = hashOf(href);
  const shown = drawable && screenOf(hash) === 'dashboard' ? 'dashboard' : 'projects';
  const [left, setLeft] = useState(DASH);
  if (shown === 'dashboard' && hash !== left) setLeft(hash);
  const [drawn, setDrawn] = useState(false);
  if (shown === 'dashboard' && !drawn) setDrawn(true);
  const path = href.slice(0, href.length - hash.length);
  return { shown, drawn, href: { projects: path, dashboard: path + left } };
}
