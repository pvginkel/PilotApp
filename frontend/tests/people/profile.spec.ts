/**
 * The profile page (F134), opened from the profile menu (F126): the person and their handle,
 * shown and not editable (F137); the switch of this browser's notifications, its subscription
 * from the worker's fake push service (F146.1), which Sign out removes (F146.3); the alarms
 * switch, the person's on every browser (F142.1); and the switch *Join projects started on my
 * behalf* (F134.2).
 */

import type { Page, Request } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { waitForUiState } from '../support/helpers';

const SUBSCRIPTIONS = '/api/people/self/push-subscriptions';

/** The next write of this browser's subscription, by method. */
function subscriptionWrite(page: Page, method: 'POST' | 'DELETE'): Promise<Request> {
  return page.waitForRequest((request) => request.method() === method && new URL(request.url()).pathname === SUBSCRIPTIONS);
}

test.describe('The profile page', () => {
  test('opens from Profile in the profile menu: the handle shown, not editable', async ({ page, people, shell, profile }) => {
    const me = await people.signIn({ name: 'Ada Example' });
    await shell.open();

    await shell.user.click();
    await shell.profileItem.click();

    await expect(shell.profileMenu).toBeHidden();
    await expect(page).toHaveURL(/\/profile$/);
    await expect(profile.heading).toHaveText('Profile');
    await expect(profile.name).toHaveText('Ada Example');
    await expect(profile.avatar).toHaveText('AE');
    await expect(profile.avatar).toHaveAttribute('data-colour', String(((me.avatar_slot! - 1) % 6) + 1));
    await expect(profile.handle).toHaveText(me.handle!);
    // Nothing on the page is typed into.
    await expect(profile.root.locator('input, textarea, select, [contenteditable]')).toHaveCount(0);
  });

  test('opens at its own address', async ({ people, shell, profile }) => {
    const me = await people.signIn();
    await shell.open('/profile');

    await expect(profile.handle).toHaveText(me.handle!);
  });
});

test.describe("The profile page's notifications switch", () => {
  test("starts off in a browser that has not answered the permission, and on asks it from the tap and writes the browser's subscription", async ({ page, people, shell, profile, browserPush }) => {
    await browserPush.install();
    await people.signIn();
    await shell.open('/profile');
    await waitForUiState(page, 'notifications.device', 'ready');

    await expect(profile.device).toHaveAttribute('role', 'switch');
    await expect(profile.device).toHaveAccessibleName('Notify me on this device');
    await expect(profile.device).toHaveAttribute('aria-checked', 'false');
    await expect(profile.device).toBeEnabled();
    await expect(profile.deviceNote).toHaveText(
      'A notification on this device of what waits on you in your projects, and of the alarms, while you are not in Pilot.',
    );
    expect(await browserPush.prompts()).toBe(0);

    const written = subscriptionWrite(page, 'POST');
    await profile.turnDevice();

    await expect(profile.device).toHaveAttribute('aria-checked', 'true');
    expect(await browserPush.prompts()).toBe(1);
    const subscription = await browserPush.subscription();
    expect(subscription?.endpoint).toMatch(/\/api\/testing\/push-service\/push\//);
    const request = await written;
    expect(request.postDataJSON()).toEqual(subscription);
    expect((await request.response())?.status()).toBe(204);

    await page.reload();
    await expect(profile.device).toHaveAttribute('aria-checked', 'true');
  });

  test('off deletes the subscription and leaves the permission granted, so on again asks nothing', async ({ page, people, shell, profile, browserPush }) => {
    await browserPush.install();
    await people.signIn();
    await shell.open('/profile');
    await profile.turnDevice();
    const { endpoint } = (await browserPush.subscription())!;

    const deleted = subscriptionWrite(page, 'DELETE');
    await profile.turnDevice();

    await expect(profile.device).toHaveAttribute('aria-checked', 'false');
    const request = await deleted;
    expect(new URL(request.url()).searchParams.get('endpoint')).toBe(endpoint);
    expect((await request.response())?.status()).toBe(204);
    expect(await browserPush.subscription()).toBeNull();
    expect(await page.evaluate(() => Notification.permission)).toBe('granted');

    await page.reload();
    await expect(profile.device).toBeEnabled();
    await expect(profile.device).toHaveAttribute('aria-checked', 'false');
    await profile.turnDevice();
    await expect(profile.device).toHaveAttribute('aria-checked', 'true');
    expect(await browserPush.prompts()).toBe(1);
  });

  test('refused at its prompt it stays off, writes nothing, and says the site settings undo it', async ({ page, people, shell, profile, browserPush }) => {
    await browserPush.install({ answer: 'denied' });
    await people.signIn();
    await shell.open('/profile');
    const writes: string[] = [];
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === SUBSCRIPTIONS) writes.push(request.method());
    });

    const refused = await profile.turnDevice('error');

    expect(refused.fields).toMatchObject({ permission: 'denied' });
    await expect(profile.device).toHaveAttribute('aria-checked', 'false');
    await expect(profile.deviceNote).toHaveText('This browser blocks Pilot’s notifications: its site settings for Pilot unblock them.');
    expect(await browserPush.subscription()).toBeNull();
    expect(writes).toEqual([]);
  });

  test("says so in a browser that blocks Pilot's notifications", async ({ page, people, shell, profile }) => {
    // The suite's headless shell keeps its permission denied.
    await people.signIn();
    await shell.open('/profile');
    await waitForUiState(page, 'notifications.device', 'ready');

    await expect(profile.device).toHaveAttribute('aria-checked', 'false');
    await expect(profile.deviceNote).toHaveText('This browser blocks Pilot’s notifications: its site settings for Pilot unblock them.');
  });

  test("reads off for a person signing in where the browser's subscription is another's, and on makes it theirs", async ({ page, people, shell, profile, browserPush }) => {
    await browserPush.install();
    await people.signIn();
    await shell.open('/profile');
    await profile.turnDevice();
    const { endpoint } = (await browserPush.subscription())!;

    // Another person signs in where the first one's session ended without a sign-out.
    await people.signIn();
    await page.reload();
    await expect(profile.device).toBeEnabled();
    await expect(profile.device).toHaveAttribute('aria-checked', 'false');

    const written = subscriptionWrite(page, 'POST');
    await profile.turnDevice();

    await expect(profile.device).toHaveAttribute('aria-checked', 'true');
    expect((await written).postDataJSON()).toMatchObject({ endpoint });
  });

  test("Sign out deletes the browser's subscription and unsubscribes it before the session ends", async ({ page, people, shell, profile, browserPush }) => {
    await browserPush.install();
    await people.signIn();
    await shell.open('/profile');
    await profile.turnDevice();
    const { endpoint } = (await browserPush.subscription())!;
    const sent: string[] = [];
    page.on('request', (request) => {
      const { pathname } = new URL(request.url());
      if (pathname === SUBSCRIPTIONS || pathname === '/api/auth/logout') sent.push(`${request.method()} ${pathname}`);
    });
    const deleted = subscriptionWrite(page, 'DELETE');
    const unsubscribed = page.waitForFunction(() => localStorage.getItem('playwright.push.subscription') === null);
    const signOut = page.waitForRequest((request) => request.url().includes('/api/auth/logout'));

    await shell.user.click();
    await shell.signOut.click();

    const request = await deleted;
    expect(new URL(request.url()).searchParams.get('endpoint')).toBe(endpoint);
    expect((await request.response())?.status()).toBe(204);
    await unsubscribed;
    await signOut;
    expect(sent).toEqual([`DELETE ${SUBSCRIPTIONS}`, 'GET /api/auth/logout']);
  });
});

test.describe("The profile page's alarms switch", () => {
  test("is on by default, whatever this browser's notifications, and names the outage and the week's limit", async ({ people, shell, profile }) => {
    await people.signIn();
    await shell.open('/profile');

    await expect(profile.alarms).toHaveAttribute('role', 'switch');
    await expect(profile.alarms).toHaveAccessibleName('Send me alarms');
    await expect(profile.alarms).toHaveAttribute('aria-checked', 'true');
    await expect(profile.alarms).toBeEnabled();
    await expect(profile.alarmsNote).toHaveText(
      'A notification while Pilot cannot reach KubeCoder for five minutes, or while the week’s usage limit halts the work, on every device whose notifications are on.',
    );
  });

  test('turns off and on again, and stays as turned', async ({ page, people, shell, profile }) => {
    await people.signIn();
    await shell.open('/profile');

    await profile.turnAlarms();
    await expect(profile.alarms).toHaveAttribute('aria-checked', 'false');
    expect((await people.self()).alarms).toBe(false);
    await page.reload();
    await expect(profile.alarms).toHaveAttribute('aria-checked', 'false');

    await profile.turnAlarms();
    await expect(profile.alarms).toHaveAttribute('aria-checked', 'true');
    expect((await people.self()).alarms).toBe(true);
  });
});

test.describe("The profile page's switch Join projects started on my behalf", () => {
  test('is the third switch, under the alarms switch, on by default, and says whose projects it joins', async ({ people, shell, profile }) => {
    await people.signIn();
    await shell.open('/profile');

    await expect(profile.root.getByRole('switch')).toHaveCount(3);
    await expect(profile.root.getByRole('switch').nth(1)).toHaveAccessibleName('Send me alarms');
    await expect(profile.root.getByRole('switch').nth(2)).toHaveAccessibleName('Join projects started on my behalf');
    await expect(profile.joinCalls).toHaveAttribute('role', 'switch');
    await expect(profile.joinCalls).toHaveAttribute('aria-checked', 'true');
    await expect(profile.joinCalls).toBeEnabled();
    await expect(profile.joinCallsNote).toHaveText(
      'A member, from its start, of every project a session outside Pilot starts here. Off, only of one started for you by name.',
    );
  });

  test('turns off and on again, stays as turned, and leaves the alarms switch as it stood', async ({ page, people, shell, profile }) => {
    await people.signIn();
    await shell.open('/profile');

    await profile.turnJoinCalls();
    await expect(profile.joinCalls).toHaveAttribute('aria-checked', 'false');
    await expect(profile.alarms).toHaveAttribute('aria-checked', 'true');
    expect(await people.self()).toMatchObject({ join_calls: false, alarms: true });
    await page.reload();
    await expect(profile.joinCalls).toHaveAttribute('aria-checked', 'false');

    await profile.turnJoinCalls();
    await expect(profile.joinCalls).toHaveAttribute('aria-checked', 'true');
    expect((await people.self()).join_calls).toBe(true);
  });

  test('the alarms switch turned leaves it as it stood', async ({ people, shell, profile }) => {
    await people.signIn();
    await shell.open('/profile');
    await profile.turnJoinCalls();

    await profile.turnAlarms();

    await expect(profile.alarms).toHaveAttribute('aria-checked', 'false');
    await expect(profile.joinCalls).toHaveAttribute('aria-checked', 'false');
    expect(await people.self()).toMatchObject({ join_calls: false, alarms: false });
  });
});
