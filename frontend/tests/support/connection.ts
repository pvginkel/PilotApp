/**
 * The page's connection to the server as a spec breaks it (F149), through the worker's backend:
 * `POST /api/testing/sse/outage` fails every stream connect with a 503 until it ends, and with
 * `silent` keeps the open streams from sending anything, their heartbeat included. The fixture
 * ends an outage a spec left standing. Beside it, a record of how the page stood, on the page's
 * own clock.
 */

import { expect, type Page } from '@playwright/test';
import { expectConsoleError } from './helpers';

/** The live stream's requests, `/api/sse/stream?request_id=…`. */
export const stream = (url: URL): boolean => url.pathname === '/api/sse/stream';

export class Outage {
  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
  ) {}

  /** The stream drops and stays down, each attempt to open it again failing, until `end()`. */
  async drop(): Promise<void> {
    await this.refuse();
    await this.page.evaluate(() => window.__sseForceReconnect!());
  }

  /** Each attempt to open a stream fails until `end()`, a stream that stands left standing: a page opened meanwhile has none. */
  async refuse(): Promise<void> {
    await this.start(false);
  }

  /** The open stream sends nothing more, as a connection that died without saying so, and each attempt to open another fails, until `end()`. */
  async silence(): Promise<void> {
    await this.start(true);
  }

  async end(): Promise<void> {
    const response = await this.page.request.delete(`${this.backendUrl}/api/testing/sse/outage`);
    expect(response.status(), await response.text()).toBe(204);
  }

  private async start(silent: boolean): Promise<void> {
    // Each attempt that fails is said in the console: the browser's 503, or on the SharedWorker's
    // path the provider's line for the worker's error.
    await expectConsoleError(this.page, /503|SSE connection error/);
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/sse/outage?silent=${silent}`);
    expect(response.status(), await response.text()).toBe(204);
  }
}

/** How the page stood from a moment on: whether its stream stood, and the tint's badge or none. */
interface ConnectionMoment {
  /** The page's `performance.now()`. */
  at: number;
  connected: boolean;
  badge: string | null;
}

type Watched = { connectionMoments: ConnectionMoment[]; lookAtConnection: () => void };

/**
 * Records each change of how the page stands, read by the returned call: the tint as the page
 * draws it, the stream every 25 ms and at each read.
 */
export async function watchConnection(page: Page): Promise<() => Promise<ConnectionMoment[]>> {
  await page.evaluate(() => {
    const moments: ConnectionMoment[] = [];
    const look = () => {
      const connected = window.__deploymentSseControls?.getStatus().isConnected ?? false;
      const badge = document.querySelector('[data-testid="shell.connection.badge"]')?.textContent ?? null;
      const last = moments.at(-1);
      if (last === undefined || last.connected !== connected || last.badge !== badge) moments.push({ at: performance.now(), connected, badge });
    };
    look();
    window.setInterval(look, 25);
    new MutationObserver(look).observe(document.body, { subtree: true, childList: true, characterData: true });
    Object.assign(window, { connectionMoments: moments, lookAtConnection: look });
  });
  return () =>
    page.evaluate(() => {
      const watched = window as unknown as Watched;
      watched.lookAtConnection();
      return watched.connectionMoments;
    });
}

/** The page's clock now. */
export const pageNow = (page: Page): Promise<number> => page.evaluate(() => performance.now());

/** The first moment from `after` on that `test` holds for, or a failure naming what was recorded. */
export function firstMoment(moments: ConnectionMoment[], after: number, test: (moment: ConnectionMoment) => boolean): ConnectionMoment {
  const moment = moments.find((each) => each.at >= after && test(each));
  if (moment === undefined) throw new Error(`No such moment after ${after}: ${JSON.stringify(moments)}`);
  return moment;
}

/** The test id of the element a press at the middle of the box would land on. */
export async function pressLandsOn(page: Page, box: { x: number; y: number; width: number; height: number }): Promise<string | null> {
  return page.evaluate(
    ([x, y]) => document.elementFromPoint(x, y)?.closest('[data-testid]')?.getAttribute('data-testid') ?? null,
    [box.x + box.width / 2, box.y + box.height / 2],
  );
}
