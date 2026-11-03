/**
 * The browser's network as a spec slows it, to see what the page shows while a write is on its way,
 * and the page's fetches under way, as the browser reports them.
 */

import type { Page, Request } from '@playwright/test';

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

/**
 * The page's fetches under way since the tracker was made, each from its `request` to its
 * `requestfinished` or `requestfailed`. A stream (`EventSource`) is no fetch.
 */
export class PageFetches {
  private readonly underWay = new Set<Request>();

  constructor(private readonly page: Page) {
    page.on('request', (request) => {
      if (request.resourceType() === 'fetch') this.underWay.add(request);
    });
    const ended = (request: Request) => this.underWay.delete(request);
    page.on('requestfinished', ended);
    page.on('requestfailed', ended);
  }

  /** Every fetch the page had sent before the call has ended. */
  async landed(): Promise<void> {
    // The page reports each fetch it sends before it answers a later evaluate.
    await this.page.evaluate(() => undefined);
    await Promise.all([...this.underWay].map(async (request) => (await request.response())?.finished()));
  }
}
