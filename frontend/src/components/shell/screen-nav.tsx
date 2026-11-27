/**
 * The two screens' tabs in the top bar after Pilot's name (F160.1), text alone, as FieldnotesApp's
 * `ScreenNav`: Projects and Dashboard, the one showing marked. A press on the other is a new entry
 * in the browser's history (F160.4), carrying none of the app's state; a press with a key held or
 * the middle button is the browser's own, its link opened where the browser opens one.
 */

import type { MouseEvent } from 'react';
import { useRouter } from '@tanstack/react-router';
import type { Screens } from '@/hooks/use-screens';
import type { Screen } from '@/lib/screens';

const TABS: { screen: Screen; label: string }[] = [
  { screen: 'projects', label: 'Projects' },
  { screen: 'dashboard', label: 'Dashboard' },
];

export function ScreenNav({ screens }: { screens: Screens }) {
  const router = useRouter();
  const go = (event: MouseEvent, screen: Screen) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (screen !== screens.shown) router.history.push(screens.href[screen], {});
  };
  return (
    <nav className="screens" aria-label="Screens" data-testid="shell.screens">
      {TABS.map(({ screen, label }) => (
        <a
          key={screen}
          href={screens.href[screen]}
          className={screen === screens.shown ? 'active' : undefined}
          aria-current={screen === screens.shown ? 'page' : undefined}
          onClick={(event) => go(event, screen)}
          data-testid={`shell.screens.${screen}`}
        >
          {label}
        </a>
      ))}
    </nav>
  );
}
