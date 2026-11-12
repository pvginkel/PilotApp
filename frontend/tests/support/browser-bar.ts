/**
 * The browser's own bar: the `theme-color`s a page's head names, and the one the browser paints
 * its bar in, the first whose `media` holds.
 */

import type { Page } from '@playwright/test';

interface ThemeColour {
  /** Empty for one that holds everywhere. */
  media: string;
  content: string;
}

/** The theme-colors of the page as it stands, in their order. */
export function pageThemeColours(page: Page): Promise<ThemeColour[]> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'), (meta) => ({ media: meta.media, content: meta.content })),
  );
}

/** The theme-colors of the page as the server sends it, before any script ran, in their order. */
export async function servedThemeColours(page: Page): Promise<ThemeColour[]> {
  const response = await page.request.get(new URL('/', page.url()).href);
  const html = await response.text();
  return [...html.matchAll(/<meta name="theme-color"[^>]*>/g)].map(([meta]) => ({
    media: /media="([^"]*)"/.exec(meta)?.[1] ?? '',
    content: /content="([^"]*)"/.exec(meta)![1],
  }));
}

/** The colour the browser paints its bar in, as it computes it: the first of `colours` whose media holds in the page. */
export function barColour(page: Page, colours: ThemeColour[]): Promise<string | null> {
  return page.evaluate((named) => {
    const first = named.find((colour) => matchMedia(colour.media || 'all').matches);
    if (first === undefined) return null;
    const probe = document.createElement('div');
    probe.style.backgroundColor = first.content;
    document.body.append(probe);
    const computed = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return computed;
  }, colours);
}
