/** The browser's network as a spec slows it, to see what the page shows while a write is on its way. */

import type { Page } from '@playwright/test';

/** Every request the page sends waits `latency` milliseconds longer, until the returned call. */
export async function slowNetwork(page: Page, latency: number): Promise<() => Promise<void>> {
  const cdp = await page.context().newCDPSession(page);
  const conditions = (wait: number) =>
    cdp.send('Network.emulateNetworkConditions', { offline: false, latency: wait, downloadThroughput: -1, uploadThroughput: -1 });
  await cdp.send('Network.enable');
  await conditions(latency);
  return async () => {
    await conditions(0);
    await cdp.detach();
  };
}
