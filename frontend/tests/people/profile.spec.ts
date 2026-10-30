/**
 * The profile page (F134), opened from the profile menu (F126): the person and their handle,
 * shown and not editable (F137); their notification token, saved after its one-shot through the
 * worker's fake bridge, cleared, and never shown back (F94.3, F134.1); and the alarms switch
 * (F142.1).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique, waitTestEvent } from '../support/helpers';
import type { FormTestEvent } from '@/lib/test/test-events';

const ONE_SHOT = 'Pilot will notify you here';

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
    // The token's field is the page's one field.
    await expect(profile.root.locator('input, textarea, select, [contenteditable]')).toHaveCount(1);
    await expect(profile.tokenField).toHaveAttribute('type', 'password');
  });

  test('opens at its own address', async ({ people, shell, profile }) => {
    const me = await people.signIn();
    await shell.open('/profile');

    await expect(profile.handle).toHaveText(me.handle!);
  });
});

test.describe("The profile page's notification token", () => {
  test('starts with none set: the field empty, Save waiting on a token, nothing to clear', async ({ people, shell, profile }) => {
    await people.signIn();
    await shell.open('/profile');

    await expect(profile.tokenState).toHaveText('No token is set.');
    await expect(profile.tokenField).toHaveValue('');
    await expect(profile.tokenField).toHaveAccessibleName('Notification token');
    await expect(profile.save).toBeDisabled();
    await expect(profile.clear).toBeDisabled();

    // Blanks alone are no token.
    await profile.tokenField.fill('   ');
    await expect(profile.save).toBeDisabled();
  });

  test('a save sends its one-shot through the token, trimmed, and shows nothing of it after', async ({ page, people, shell, profile, bridge }) => {
    await people.signIn();
    const phone = await bridge.register();
    await shell.open('/profile');

    await profile.saveToken(`  ${phone.token}\n`);

    await expect(profile.tokenState).toHaveText('A token is set.');
    await expect(profile.tokenField).toHaveValue('');
    await expect(profile.tokenError).toHaveCount(0);
    await expect(profile.clear).toBeEnabled();
    expect(await bridge.oneShots(phone.name)).toEqual([
      { sequence_id: null, priority: 'default', title: null, message: ONE_SHOT, url: null, alerted: true },
    ]);

    // The person as the API reads them says a token is set, and carries nothing of it.
    const self = await people.self();
    expect(self.notification_token_set).toBe(true);
    expect(JSON.stringify(self)).not.toContain(phone.token);

    await page.reload();
    await expect(profile.tokenState).toHaveText('A token is set.');
    await expect(profile.tokenField).toHaveValue('');
  });

  test('a save waits on its one-shot, saying what it sends, however long the bridge takes', async ({ page, people, shell, profile, bridge }) => {
    await people.signIn();
    const phone = await bridge.register();
    await shell.open('/profile');
    await bridge.hold();

    await profile.tokenField.fill(phone.token);
    await profile.save.click();

    await expect(profile.tokenProgress).toHaveText(`Sending "${ONE_SHOT}" through the token`);
    await expect(profile.tokenField).toBeDisabled();
    await expect(profile.save).toBeDisabled();
    await expect(profile.clear).toBeDisabled();
    expect((await people.self()).notification_token_set).toBe(false);

    await bridge.answer();
    await waitTestEvent<FormTestEvent>(page, 'form', (event) => event.formId === 'people.notification-token' && event.phase === 'success');
    await expect(profile.tokenState).toHaveText('A token is set.');
    await expect(profile.tokenProgress).toHaveCount(0);
    await expect(profile.tokenField).toBeEnabled();
  });

  test('a token the bridge refuses fails the save, its reason under the field, and is not stored', async ({ people, shell, profile }) => {
    await people.signIn();
    await shell.open('/profile');

    await profile.saveToken(makeUnique('unknown-token', 16), 'error');

    await expect(profile.tokenError).toContainText('the bridge refused it with 401: unknown bearer token');
    await expect(profile.tokenField).toHaveAttribute('aria-invalid', 'true');
    await expect(profile.tokenField).toHaveAttribute('aria-describedby', (await profile.tokenError.getAttribute('id'))!);
    await expect(profile.tokenState).toHaveText('No token is set.');
    expect((await people.self()).notification_token_set).toBe(false);

    // Typing again takes the reason away.
    await profile.tokenField.press('x');
    await expect(profile.tokenError).toHaveCount(0);
    await expect(profile.tokenField).toHaveAttribute('aria-invalid', 'false');
  });

  test('another token replaces a set one through its own one-shot', async ({ people, shell, profile, bridge }) => {
    await people.signIn();
    const first = await bridge.register();
    const second = await bridge.register();
    await shell.open('/profile');
    await profile.saveToken(first.token);

    await expect(profile.tokenField).toHaveAttribute('placeholder', 'Paste a token to replace it');
    await profile.saveToken(second.token);

    await expect(profile.tokenState).toHaveText('A token is set.');
    expect(await bridge.oneShots(first.name)).toHaveLength(1);
    expect(await bridge.oneShots(second.name)).toHaveLength(1);
  });

  test('Clear drops the token at once', async ({ page, people, shell, profile, bridge }) => {
    await people.signIn();
    const phone = await bridge.register();
    await shell.open('/profile');
    await profile.saveToken(phone.token);

    await profile.clearToken();

    await expect(profile.tokenState).toHaveText('No token is set.');
    await expect(profile.clear).toBeDisabled();
    expect((await people.self()).notification_token_set).toBe(false);
    await page.reload();
    await expect(profile.tokenState).toHaveText('No token is set.');
  });

  test("a set token's standing notification reaches the bridge for a project the person is a member of, and Clear dismisses it", async ({ people, projects, shell, profile, bridge }) => {
    const me = await people.signIn();
    const name = makeUnique('Tent');
    const projectId = await projects.make({ members: [me.handle!], name });
    const phone = await bridge.register();
    await shell.open('/profile');

    await profile.saveToken(phone.token);

    await expect.poll(async () => (await bridge.shown(phone.name))[projectId]).toMatchObject({
      sequence_id: projectId,
      title: name,
      url: expect.stringMatching(new RegExp(`/projects/${projectId}$`)),
    });

    await profile.clearToken();

    await expect.poll(async () => Object.keys(await bridge.shown(phone.name))).toEqual([]);
  });
});

test.describe("The profile page's alarms switch", () => {
  test('is on by default, and disabled while no token is set', async ({ people, shell, profile }) => {
    await people.signIn();
    await shell.open('/profile');

    await expect(profile.alarms).toHaveAttribute('role', 'switch');
    await expect(profile.alarms).toHaveAccessibleName('Send me alarms');
    await expect(profile.alarms).toHaveAttribute('aria-checked', 'true');
    await expect(profile.alarms).toBeDisabled();
  });

  test('turns off and on again with a token set, and stays as turned', async ({ page, people, shell, profile, bridge }) => {
    await people.signIn();
    const phone = await bridge.register();
    await shell.open('/profile');
    await profile.saveToken(phone.token);
    await expect(profile.alarms).toBeEnabled();

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
