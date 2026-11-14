/**
 * A dropped connection (F149, the UI pile's M12): while the browser's connection to Pilot's server
 * is down or slow, the whole page lies under the scrim, the top bar included, taking every click,
 * with a badge in its middle: the loader before "Connecting…", or "Retrying…" once an attempt to
 * open the stream has failed. It lifts at once when the connection is back, and the stream's
 * return reads everything again. Down is the live stream gone for more than 3 s after it stood, or
 * the browser offline; slow, a request under way for more than 8 s. The stream is opened again for
 * as long as it takes, at most 5 s apart and at once when the browser is back online, and no toast
 * asks for a reload (F112). The server's heartbeat, every 5 s, is an event the page times: a
 * stream that has heard nothing for two beats died without saying so, and is opened again, so that
 * a connection that died silently tints at most 13 s after its last frame.
 *
 * The drop and the silence run on both of the stream's paths: the direct EventSource in every run,
 * and the SharedWorker, which production's browsers take, in preview mode only, since the dev
 * server never uses it.
 */

import type { Request } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { firstMoment, pageNow, pressLandsOn, stream, watchConnection } from '../support/connection';
import { expectConsoleError, makeUnique } from '../support/helpers';
import { getTestEventBuffer, waitForSseEvent } from '../support/helpers/test-events';
import { slowNetwork } from '../support/network';

const NOTICE = 'The site opens in May.\n';

const PREVIEW_ONLY_REASON = 'Needs PLAYWRIGHT_PREVIEW_MODE=true: the Vite dev server never uses the SharedWorker';

const PATHS = [
  { name: 'direct EventSource', query: '', sharedWorker: false },
  { name: 'SharedWorker', query: '?__sharedWorker', sharedWorker: true },
] as const;

for (const path of PATHS) {
  test.describe(`A dropped connection (${path.name})`, { tag: path.sharedWorker ? ['@preview'] : [] }, () => {
    test.skip(path.sharedWorker && process.env.PLAYWRIGHT_PREVIEW_MODE !== 'true', PREVIEW_ONLY_REASON);

    test('tints the whole page 3 s after the stream went, Retrying once an attempt failed, taking every click; it lifts at once when the stream is back, which reads everything again', async ({
      page,
      people,
      projects,
      projectList,
      shell,
      outage,
      deploymentSse,
      toastHelper,
    }) => {
      const me = await people.signIn();
      const name = makeUnique('Mine');
      await projects.make({ name, members: [me.handle!] });
      await shell.open(`/profile${path.query}`);
      await deploymentSse.ensureConnected();
      const moments = await watchConnection(page);
      const start = await pageNow(page);

      await outage.drop();
      await expect(shell.connectionBadge).toHaveText('Retrying…');
      const recorded = await moments();
      const dropped = firstMoment(recorded, start, (moment) => !moment.connected);
      const tinted = firstMoment(recorded, start, (moment) => moment.badge !== null);
      expect(tinted.at - dropped.at).toBeGreaterThanOrEqual(2_800);
      expect(tinted.at - dropped.at).toBeLessThan(4_500);

      // Every press lands on the tint, the top bar's and the list's included.
      for (const locator of [shell.user, projectList.tab(name)]) {
        expect(await pressLandsOn(page, (await locator.boundingBox())!)).toBe('shell.connection');
      }
      const avatar = (await shell.user.boundingBox())!;
      await page.mouse.click(avatar.x + avatar.width / 2, avatar.y + avatar.height / 2);
      await expect(shell.profileMenu).toHaveCount(0);
      await toastHelper.expectNoToast();

      // A project made while the stream is down: the browser does not hear of it.
      const later = makeUnique('Later');
      await projects.make({ name: later, members: [me.handle!] });
      await expect(projectList.tab(later)).toHaveCount(0);

      const back = await pageNow(page);
      await outage.end();
      await expect(shell.connection).toHaveCount(0, { timeout: 10_000 });
      const after = await moments();
      const connected = firstMoment(after, back, (moment) => moment.connected);
      const lifted = firstMoment(after, back, (moment) => moment.badge === null);
      expect(Math.abs(lifted.at - connected.at)).toBeLessThan(200);
      await expect(projectList.tab(later)).toBeVisible();
    });

    test('a connection that died silently is gone two beats after its last frame, and tints the page at most 13 s after it', async ({
      page,
      people,
      shell,
      outage,
      deploymentSse,
    }) => {
      await people.signIn();
      await shell.open(`/profile${path.query}`);
      await deploymentSse.ensureConnected();
      const moments = await watchConnection(page);

      // The connection dies without saying so, and the attempts to open another fail.
      await outage.silence();
      const silentAt = await pageNow(page);
      await expect(shell.connectionBadge).toHaveText('Retrying…', { timeout: 16_000 });
      const recorded = await moments();
      const gone = firstMoment(recorded, silentAt, (moment) => !moment.connected);
      const tinted = firstMoment(recorded, silentAt, (moment) => moment.badge !== null);
      // Its last frame came at most a beat before the silence: two beats after that frame it is gone,
      // and the page is tinted 3 s later.
      expect(gone.at - silentAt).toBeGreaterThan(4_000);
      expect(gone.at - silentAt).toBeLessThanOrEqual(10_500);
      expect(tinted.at - silentAt).toBeLessThanOrEqual(13_500);

      await outage.end();
      await expect(shell.connection).toHaveCount(0, { timeout: 10_000 });
    });
  });
}

test.describe('A dropped connection', () => {
  test('opens the stream again for as long as it takes, the attempts at most 5 s apart', async ({
    page,
    people,
    shell,
    outage,
    deploymentSse,
  }) => {
    test.setTimeout(90_000);
    await people.signIn();
    await shell.open('/profile');
    await deploymentSse.ensureConnected();
    const attempts: number[] = [];
    page.on('request', (request: Request) => {
      if (stream(new URL(request.url()))) attempts.push(performance.now());
    });

    await outage.drop();
    await expect.poll(() => attempts.length, { timeout: 30_000 }).toBeGreaterThanOrEqual(6);
    // 1, 2 and 4 s, then 5 s where a minute's backoff would wait 8, 16, ….
    const gaps = attempts.slice(1, 6).map((at, index) => at - attempts[index]);
    expect(gaps[2]).toBeGreaterThan(3_500);
    for (const gap of gaps.slice(3)) {
      expect(gap).toBeGreaterThan(4_500);
      expect(gap).toBeLessThan(6_000);
    }
    await expect(shell.connectionBadge).toHaveText('Retrying…');

    await outage.end();
    await expect(shell.connection).toHaveCount(0, { timeout: 10_000 });
  });

  test('takes every press over an open dialog and an open menu, which stand as they stood', async ({ page, people, shell, outage, deploymentSse }) => {
    await people.signIn();
    await shell.open('/profile');
    await deploymentSse.ensureConnected();

    // The keys list is a modal dialog, which turns the body's pointer events off while it is open.
    await page.keyboard.press('?');
    await expect(shell.keys).toBeVisible();
    await outage.drop();
    await expect(shell.connectionBadge).toHaveText('Retrying…');
    const keys = (await shell.keys.boundingBox())!;
    const inDialog = { x: keys.x + 4, y: keys.y + 4, width: 0, height: 0 };
    const beside = { x: 4, y: 4, width: 0, height: 0 };
    for (const box of [inDialog, beside]) {
      expect(await pressLandsOn(page, box)).toBe('shell.connection');
      await page.mouse.click(box.x, box.y);
    }
    await expect(shell.keys).toBeVisible();
    await outage.end();
    await expect(shell.connection).toHaveCount(0, { timeout: 10_000 });
    await page.keyboard.press('Escape');
    await expect(shell.keys).toHaveCount(0);

    // A menu closes on a press outside it.
    await shell.user.click();
    await expect(shell.profileMenu).toBeVisible();
    await outage.drop();
    await expect(shell.connectionBadge).toHaveText('Retrying…');
    await page.mouse.click(beside.x, beside.y);
    await expect(shell.profileMenu).toBeVisible();
    await outage.end();
    await expect(shell.connection).toHaveCount(0, { timeout: 10_000 });
  });

  test('tints at once while the browser is offline, and opens the stream at once when it is back online', async ({
    page,
    context,
    people,
    shell,
    deploymentSse,
  }) => {
    test.setTimeout(90_000);
    await people.signIn();
    await shell.open('/profile');
    await deploymentSse.ensureConnected();
    const moments = await watchConnection(page);
    await expectConsoleError(page, /ERR_INTERNET_DISCONNECTED/);
    const attempts: number[] = [];
    page.on('request', (request: Request) => {
      if (stream(new URL(request.url()))) attempts.push(performance.now());
    });

    const offAt = await pageNow(page);
    await context.setOffline(true);
    try {
      await expect(shell.connection).toBeVisible();
      // Well before the 3 s a stream that went waits.
      expect(firstMoment(await moments(), offAt, (moment) => moment.badge !== null).at - offAt).toBeLessThan(1_500);

      // Each attempt fails, until the backoff has waited 4 s and waits 5 s for the next.
      await page.evaluate(() => window.__sseForceReconnect!());
      await expect
        .poll(() => attempts.length > 1 && attempts.at(-1)! - attempts.at(-2)! > 3_500, { timeout: 30_000, intervals: [50] })
        .toBe(true);

      const onAt = await pageNow(page);
      await context.setOffline(false);
      await expect(shell.connection).toHaveCount(0);
      expect(firstMoment(await moments(), onAt, (moment) => moment.connected).at - onAt).toBeLessThan(2_500);
    } finally {
      await context.setOffline(false);
    }
  });

  test('a quiet stream stands on its heartbeat, every 5 s, an event the page hears', async ({ page, people, shell, deploymentSse }) => {
    await people.signIn();
    await shell.open('/profile');
    const standing = await deploymentSse.ensureConnected();
    const moments = await watchConnection(page);

    // Three heartbeats, more than two beats apart, with no other event: the stream stands.
    getTestEventBuffer(page).clear();
    for (let beat = 0; beat < 3; beat++) {
      await waitForSseEvent(page, { streamId: 'connection', phase: 'message', event: 'heartbeat', timeoutMs: 8_000 });
    }
    expect(await moments()).toHaveLength(1);
    expect(await deploymentSse.getStatus()).toEqual(standing);
  });

  test('tints the page while a request has been under way for more than 8 s, Connecting, and lifts when it is answered', async ({
    page,
    people,
    projects,
    timeline,
    shell,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Slow'), members: [me.handle!] });
    const notice = timeline.item(await projects.place(id, { kind: 'notice', title: 'News', text: NOTICE }));
    await timeline.open(id);
    const moments = await watchConnection(page);

    // The Read's request takes 30 s, until the network is restored, which lands it.
    const restore = await slowNetwork(page, 30_000);
    const pressedAt = await pageNow(page);
    await notice.read.click();
    await expect(shell.connectionBadge).toHaveText('Connecting…', { timeout: 12_000 });
    const tinted = firstMoment(await moments(), pressedAt, (moment) => moment.badge !== null);
    expect(tinted.at - pressedAt).toBeGreaterThanOrEqual(7_800);
    expect(tinted.connected).toBe(true);
    await expect(notice.read).toBeDisabled();

    await restore();
    await expect(shell.connection).toHaveCount(0);
    await expect(notice.root).toHaveAttribute('data-state', 'done');
  });
});
