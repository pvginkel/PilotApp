/**
 * The theme (F109): system, light or dark, remembered in the browser. The page's `data-theme`
 * is what app-theme.css reads; under `system` it follows the OS, live.
 */

import { useEffect } from 'react';
import { browserState, rememberInBrowser, useBrowserState, type Theme } from '@/lib/browser-state';

const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

function applyTheme(theme: Theme): void {
  const dark = theme === 'dark' || (theme === 'system' && systemDark.matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
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

/**
 * While mounted, the browser's own bar takes the page's colour, in either theme (F98.3); after, it
 * has `index.html`'s `theme-color` back, the top bar's.
 */
export function useBrowserBarInPageColour(): void {
  useEffect(() => {
    const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')!;
    const topBar = meta.content;
    const paint = () => {
      meta.content = getComputedStyle(document.body).backgroundColor;
    };
    paint();
    const themed = new MutationObserver(paint);
    themed.observe(document.documentElement, { attributeFilter: ['data-theme'] });
    return () => {
      themed.disconnect();
      meta.content = topBar;
    };
  }, []);
}
