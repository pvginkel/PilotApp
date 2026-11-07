/**
 * The gold bar's offer of the browser's notifications (F146.2): across the full width of the top
 * at a browser's first open, while its notifications are off and its permission not refused, on
 * the desktop over the top bar and on a phone over the conditions' bar. Turn on asks the
 * permission from its tap and subscribes the browser with the worker's fake push service; after
 * Turn on, Not now or the profile page's switch, it never shows in that browser again.
 */

import { test, expect } from '../support/fixtures';
import { waitForUiState, waitTestEvent } from '../support/helpers';
import type { FormTestEvent } from '@/lib/test/test-events';

const SUBSCRIPTIONS = '/api/people/self/push-subscriptions';

test.describe("The notifications' offer", () => {
  test('spans the top over the top bar at a first open, offering Turn on and Not now', async ({ page, people, shell, browserPush }) => {
    await browserPush.install();
    await people.signIn();
    await shell.open();

    await expect(shell.offer).toHaveAccessibleName('Notifications');
    await expect(shell.offer).toContainText(
      'Turn on notifications on this device? Pilot tells you here what waits on you in your projects, while you are not in Pilot.',
    );
    await expect(shell.offerOn).toHaveText('Turn on');
    await expect(shell.offerNotNow).toHaveText('Not now');
    const offer = (await shell.offer.boundingBox())!;
    expect(offer).toMatchObject({ x: 0, y: 0, width: page.viewportSize()!.width });
    expect((await shell.topBar.boundingBox())!.y).toBeGreaterThanOrEqual(offer.height);
    expect(await browserPush.prompts()).toBe(0);
  });

  test('Turn on asks the permission from its tap and writes the subscription; it never shows again', async ({ page, people, shell, profile, browserPush }) => {
    await browserPush.install();
    await people.signIn();
    await shell.open();
    const written = page.waitForRequest((request) => request.method() === 'POST' && new URL(request.url()).pathname === SUBSCRIPTIONS);
    const turnedOn = waitTestEvent<FormTestEvent>(page, 'form', (event) => event.formId === 'shell.notifications-offer' && event.phase === 'success');

    await shell.offerOn.click();

    await expect(shell.offer).toHaveCount(0);
    await turnedOn;
    expect(await browserPush.prompts()).toBe(1);
    expect((await written).postDataJSON()).toEqual(await browserPush.subscription());

    await shell.open('/profile');
    await expect(profile.device).toHaveAttribute('aria-checked', 'true');
    await expect(shell.offer).toHaveCount(0);
  });

  test("Not now puts it away for good in that browser, and the profile page's switch still turns them on", async ({ page, people, shell, profile, browserPush }) => {
    await browserPush.install();
    await people.signIn();
    await shell.open();

    await shell.offerNotNow.click();

    await expect(shell.offer).toHaveCount(0);
    expect(await browserPush.prompts()).toBe(0);
    expect(await browserPush.subscription()).toBeNull();
    expect(await page.evaluate(() => (JSON.parse(localStorage.getItem('pilot')!) as Record<string, unknown>).notificationsOffered)).toBe(true);

    await shell.open('/profile');
    await expect(profile.device).toBeEnabled();
    await expect(profile.device).toHaveAttribute('aria-checked', 'false');
    await expect(shell.offer).toHaveCount(0);
    await profile.turnDevice();
    await expect(profile.device).toHaveAttribute('aria-checked', 'true');
  });

  test("goes once the profile page's switch turns them on, and stays away once it turns them off", async ({ people, shell, profile, browserPush }) => {
    await browserPush.install();
    await people.signIn();
    await shell.open('/profile');
    await expect(shell.offer).toBeVisible();

    await profile.turnDevice();
    await expect(shell.offer).toHaveCount(0);
    await profile.turnDevice();

    await expect(profile.device).toHaveAttribute('aria-checked', 'false');
    await expect(shell.offer).toHaveCount(0);
  });

  test('shows nowhere the permission is refused', async ({ page, people, shell, profile, browserPush }) => {
    await browserPush.install({ permission: 'denied' });
    await people.signIn();
    await shell.open('/profile');
    await waitForUiState(page, 'notifications.device', 'ready');

    await expect(profile.device).toHaveAttribute('aria-checked', 'false');
    await expect(shell.offer).toHaveCount(0);
  });

  test('is not at the handle step', async ({ people, shell, handleStep, browserPush }) => {
    await browserPush.install();
    await people.firstSignIn();
    await shell.open();

    await expect(handleStep.root).toBeVisible();
    await expect(shell.offer).toHaveCount(0);
  });

  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test("is a bar of its own across the page's top, over the conditions' bar and the screen", async ({ people, shell, browserPush }) => {
      await browserPush.install();
      await people.signIn();
      await shell.open();

      const offer = (await shell.offer.boundingBox())!;
      expect(offer).toMatchObject({ x: 0, y: 0, width: 390 });
      expect((await shell.app.boundingBox())!.y).toBeGreaterThanOrEqual(offer.height);
      await expect(shell.goldBar.locator(shell.offer)).toHaveCount(0);

      await shell.offerNotNow.click();
      await expect(shell.offer).toHaveCount(0);
      expect((await shell.app.boundingBox())!.y).toBe(0);
    });
  });
});
