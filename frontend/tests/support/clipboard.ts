/**
 * The page's clipboard, for a spec of a copy button: `allowClipboard` before the page copies, then
 * `copied` reads what it holds.
 */

import type { BrowserContext, Page } from '@playwright/test';

export async function allowClipboard(context: BrowserContext): Promise<void> {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
}

export function copied(page: Page): Promise<string> {
  return page.evaluate(() => navigator.clipboard.readText());
}
