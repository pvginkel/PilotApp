/**
 * The app's two screens (F160.1) and what of the address says which shows (F160.3): Projects, the
 * app at its path with no hash, and the dashboard, the app's path with `#dash/<tab>/<state>` after
 * it, the tab's id before the view's state. `#dash` alone names no tab: the dashboard as it was
 * left, on its first opening the new tab's panel.
 */

export type Screen = 'projects' | 'dashboard';

/** The dashboard's address after the app's path, naming no tab. */
export const DASH = '#dash';

/** The hash of an href as the browser holds it, its `#` first; empty where it has none. */
export function hashOf(href: string): string {
  const at = href.indexOf('#');
  return at < 0 ? '' : href.slice(at);
}

/** The screen a hash names, `#` first: the dashboard's `#dash` and every address under `#dash/`, else Projects. */
export function screenOf(hash: string): Screen {
  return hash === DASH || hash.startsWith(`${DASH}/`) ? 'dashboard' : 'projects';
}
