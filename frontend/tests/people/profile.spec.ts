/**
 * The profile page (F134), opened from the profile menu (F126): the person and their handle,
 * shown and not editable (F137).
 */

import { test, expect } from '../support/fixtures';

test.describe('The profile page', () => {
  test('opens from Profile in the profile menu: the handle shown, nothing editable', async ({ page, people, shell, profile }) => {
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
    await expect(profile.root.locator('input, textarea, select, [contenteditable]')).toHaveCount(0);
  });

  test('opens at its own address', async ({ people, shell, profile }) => {
    const me = await people.signIn();
    await shell.open('/profile');

    await expect(profile.handle).toHaveText(me.handle!);
  });
});
