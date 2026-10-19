/**
 * The PWA shell (F95): the manifest the page head names and its icons, and the service worker that
 * caches nothing, answers a navigation the network does not with one line, and never answers a
 * request under /api/.
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';

const UNREACHABLE = 'Pilot is unreachable. Try again when you are back on the network.';

/** Resolves once the service worker controls the page. */
async function controlled(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) {
      await new Promise((resolve) =>
        navigator.serviceWorker.addEventListener('controllerchange', resolve, { once: true }),
      );
    }
  });
}

/** A PNG's width and height as a manifest's `sizes` writes them, from its IHDR chunk. */
function pngSize(png: Buffer): string {
  return `${png.readUInt32BE(16)}x${png.readUInt32BE(20)}`;
}

test.describe('The PWA shell', () => {
  test.beforeEach(async ({ people, shell }) => {
    await people.signIn();
    await shell.open('/profile');
  });

  test('serves the manifest the page head names, with its icons', async ({ page }) => {
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#568ed2');
    const href = await page.locator('link[rel="manifest"]').getAttribute('href');
    const manifestUrl = new URL(href!, page.url());
    const response = await page.request.get(manifestUrl.href);
    expect(response.ok()).toBe(true);
    const manifest = await response.json();

    expect(manifest).toMatchObject({ name: 'Pilot', short_name: 'Pilot', display: 'standalone' });
    const root = new URL('/', page.url()).href;
    expect(new URL(manifest.start_url, manifestUrl).href).toBe(root);
    expect(new URL(manifest.scope, manifestUrl).href).toBe(root);
    expect(manifest.icons.map((icon: { sizes: string; purpose?: string }) => [icon.sizes, icon.purpose])).toEqual([
      ['192x192', undefined],
      ['512x512', undefined],
      ['512x512', 'maskable'],
    ]);
    for (const icon of manifest.icons) {
      const image = await page.request.get(new URL(icon.src, manifestUrl).href);
      expect(image.headers()['content-type']).toBe('image/png');
      expect(pngSize(await image.body())).toBe(icon.sizes);
    }
  });

  // Chrome's own installability check is not witnessed: headless Chromium's
  // Page.getInstallabilityErrors answers no error for a page that names no manifest at all.
  test('names a manifest Chrome reads without an error', async ({ page }) => {
    const cdp = await page.context().newCDPSession(page);
    const { url, errors } = await cdp.send('Page.getAppManifest');
    expect(url).toBe(new URL('/manifest.json', page.url()).href);
    expect(errors).toEqual([]);
  });

  test('controls the whole app from the root and caches nothing', async ({ page, shell }) => {
    await controlled(page);
    const registration = await page.evaluate(async () => {
      const ready = await navigator.serviceWorker.ready;
      return { script: ready.active!.scriptURL, scope: ready.scope };
    });
    expect(registration).toEqual({
      script: new URL('/sw.js', page.url()).href,
      scope: new URL('/', page.url()).href,
    });

    const response = await page.reload();
    expect(response!.fromServiceWorker()).toBe(true);
    await shell.open('/profile');
    expect(await page.evaluate(() => caches.keys())).toEqual([]);
  });

  test('answers a navigation with one line while the network is down', async ({ context, page, shell }) => {
    await controlled(page);

    await context.setOffline(true);
    await page.reload();
    await expect(page).toHaveTitle('Pilot');
    await expect(page.locator('body')).toHaveText(UNREACHABLE);

    await context.setOffline(false);
    await shell.open('/profile');
    await expect(shell.topBar).toBeVisible();
  });

  test('never answers a request under /api/', async ({ context, page }) => {
    await controlled(page);

    expect((await page.goto('/profile'))!.fromServiceWorker()).toBe(true);
    expect((await page.goto('/api/people/self'))!.fromServiceWorker()).toBe(false);

    await context.setOffline(true);
    await expect(page.goto('/api/people/self')).rejects.toThrow('net::ERR_INTERNET_DISCONNECTED');
  });
});
