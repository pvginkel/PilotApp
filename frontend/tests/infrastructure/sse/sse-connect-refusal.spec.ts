/**
 * The SSE stream admits only the identity the API serves.
 *
 * The backend's connect callback refuses a stream with 401/403, and the gateway
 * answers the refusal in-stream: it opens the stream, sends a named `rejected`
 * event carrying `{status, message}` and ends it. These tests open a bare
 * EventSource from the page, through the Vite proxy, so the callback sees the
 * browser's session cookie exactly as the app's own stream does.
 *
 * The app's recovery from `rejected` (the SharedWorker's terminal state, the
 * provider's /api/auth/self probe and reconnect) runs only in a production
 * build; this suite serves the Vite dev server, where the provider always
 * takes the direct EventSource path.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../../support/fixtures';

type StreamOutcome =
  | { outcome: 'accepted' }
  | { outcome: 'rejected'; status: number; message: string };

/**
 * Open a stream and report how the gateway answered: `accepted` on the first
 * envelope (an accepted stream is sent the current version on connect),
 * `rejected` on the gateway's `rejected` event.
 */
async function openStream(page: Page, timeoutMs = 15000): Promise<StreamOutcome> {
  return page.evaluate(
    timeout =>
      new Promise<StreamOutcome>((resolve, reject) => {
        const requestId = 'pw-' + Math.random().toString(36).substring(2, 15);
        const es = new EventSource(`/api/sse/stream?${new URLSearchParams({ request_id: requestId })}`);

        const timer = setTimeout(() => {
          es.close();
          reject(new Error('The SSE stream neither delivered an event nor was rejected'));
        }, timeout);

        const settle = (result: StreamOutcome) => {
          clearTimeout(timer);
          es.close();
          resolve(result);
        };

        es.onmessage = () => settle({ outcome: 'accepted' });
        es.addEventListener('rejected', event => {
          const { status, message } = JSON.parse((event as MessageEvent).data);
          settle({ outcome: 'rejected', status, message });
        });
      }),
    timeoutMs,
  );
}

test.describe('SSE connect refusal', () => {
  test('refuses a session without the editor role', async ({ page, frontendUrl, auth }) => {
    await auth.createSession({ roles: ['admin'] });
    await page.goto(frontendUrl);

    const result = await openStream(page);

    expect(result).toMatchObject({ outcome: 'rejected', status: 403 });
  });

  test('accepts a session with the editor role', async ({ page, frontendUrl, auth }) => {
    await auth.createSession({ roles: ['editor'] });
    await page.goto(frontendUrl);

    const result = await openStream(page);

    expect(result).toEqual({ outcome: 'accepted' });
  });

  test('the forced callback error refuses the next stream only', async ({
    page,
    frontendUrl,
    backendUrl,
    auth,
    deploymentSse,
  }) => {
    await auth.createSession({ roles: ['editor'] });
    await page.goto(frontendUrl);
    // Let the app's own stream connect first, so it does not consume the hook.
    await deploymentSse.ensureConnected();

    const armed = await page.request.post(`${backendUrl}/api/testing/sse/force-callback-error?status=401`);
    expect(armed.status()).toBe(204);

    expect(await openStream(page)).toMatchObject({ outcome: 'rejected', status: 401 });
    expect(await openStream(page)).toEqual({ outcome: 'accepted' });
  });
});
