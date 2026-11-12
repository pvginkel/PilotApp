/**
 * The theme (F109): system, light or dark, remembered in the browser. The page's `data-theme`
 * is what app-theme.css reads; under `system` it follows the OS, live.
 */

import { browserState, rememberInBrowser, useBrowserState, type Theme } from '@/lib/browser-state';

const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

/**
 * A phone's two `theme-color`s in `index.html`, the bottom tabs' tint in each scheme. The browser
 * paints its own bar in the first whose `media` holds: the dark one's under a dark OS, else the
 * light one's.
 */
const bar = {
  dark: document.querySelector<HTMLMetaElement>('meta[name="theme-color"][data-scheme="dark"]')!,
  light: document.querySelector<HTMLMetaElement>('meta[name="theme-color"][data-scheme="light"]')!,
};
const tint = { dark: bar.dark.content, light: bar.light.content };

function applyTheme(theme: Theme): void {
  const dark = theme === 'dark' || (theme === 'system' && systemDark.matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  // A theme chosen over the OS's gives both its own tint, so that the OS's scheme picks it either way.
  bar.dark.content = tint[theme === 'light' ? 'light' : 'dark'];
  bar.light.content = tint[theme === 'dark' ? 'dark' : 'light'];
}

/** Sets the remembered theme on the page and follows the OS's; runs once, before the first render. */
export function startTheme(): void {
  applyTheme(browserState().theme);
  systemDark.addEventListener('change', () => applyTheme(browserState().theme));
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const { theme } = useBrowserState();
  const choose = (chosen: Theme) => {
    rememberInBrowser({ theme: chosen });
    applyTheme(chosen);
  };
  return [theme, choose];
}
