/**
 * The top bar (F111) and its profile menu (F126): the logo and the name, the signed-in person's
 * avatar, and the menu it opens, which ends in the commit the page is built from.
 */

import { execSync } from 'child_process';
import fs from 'fs';
import { test, expect } from '../support/fixtures';

test.describe('The top bar', () => {
  test('shows the logo on its tile, the name and the signed-in person in their colour', async ({ people, shell }) => {
    const me = await people.signIn({ name: 'Ada Example' });
    await shell.open();

    await expect(shell.brand).toHaveText('Pilot');
    const logo = shell.brand.locator('img.logo');
    await expect(logo).toHaveAttribute('src', '/logo.png');
    // Three times the bar's 32px: the 96px render, served under the logo's name (vite-icons.ts).
    await expect.poll(() => logo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(96);
    await expect(shell.avatar).toHaveText('AE');
    await expect(shell.avatar).toHaveAttribute('title', 'Ada Example');
    await expect(shell.userName).toHaveText('Ada Example');
    expect(me.avatar_slot).not.toBeNull();
    await expect(shell.avatar).toHaveAttribute('data-colour', String(((me.avatar_slot! - 1) % 6) + 1));
  });

  test("at a first sign-in shows the token's name, without a palette colour", async ({ people, shell }) => {
    await people.firstSignIn({ name: 'Ben Newcomer' });
    await shell.open();

    await expect(shell.userName).toHaveText('Ben Newcomer');
    await expect(shell.avatar).toHaveText('BN');
    await expect(shell.avatar).not.toHaveAttribute('data-colour');
    await expect(shell.avatar).toHaveCSS('background-color', 'rgba(0, 0, 0, 0.25)');
  });

  test('reads Unknown User for a token with no name, a user icon in the avatar', async ({ people, shell }) => {
    await people.firstSignIn({ name: null });
    await shell.open();

    await expect(shell.userName).toHaveText('Unknown User');
    await expect(shell.avatar).toHaveAttribute('title', 'Unknown User');
    await expect(shell.avatar.locator('svg.icon')).toBeVisible();
  });
});

test.describe('The profile menu', () => {
  test('opens from the avatar: the name, the theme, Profile and Sign out', async ({ people, shell }) => {
    await people.signIn({ name: 'Ada Example' });
    await shell.open();

    await expect(shell.profileMenu).toBeHidden();
    await shell.user.click();
    await expect(shell.profileMenu).toBeVisible();
    await expect(shell.profileName).toHaveText('Ada Example');
    await expect(shell.theme).toHaveValue('system');
    await expect(shell.theme.locator('option')).toHaveText(['System', 'Light', 'Dark']);
    await expect(shell.profileMenu.getByRole('menuitem')).toHaveText(['Profile', 'Sign out']);
    await expect(shell.signOut).toHaveText('Sign out');
  });

  test('ends in the short hash of the commit the page is built from, in extra-small muted type', async ({ people, shell }) => {
    await people.signIn();
    await shell.open();

    await shell.user.click();
    // The commit the dev server embeds as it starts (vite-build-commit.ts): CI's tree has no .git,
    // and the Jenkinsfile writes it to git-rev.
    const written = new URL('../../git-rev', import.meta.url);
    const commit = (fs.existsSync(written) ? fs.readFileSync(written, 'utf8') : execSync('git rev-parse HEAD', { encoding: 'utf8' })).trim();
    await expect(shell.profileVersion).toHaveText(commit.slice(0, 7));
    const items = await shell.profileMenu.evaluate((menu) => Array.from(menu.children, (child) => child.getAttribute('data-testid')));
    expect(items.at(-1)).toBe('shell.profile.version');
    await expect(shell.profileVersion).toHaveCSS('font-size', '12px');
    const muted = await shell.theme.locator('..').evaluate((field) => getComputedStyle(field).color);
    await expect(shell.profileVersion).toHaveCSS('color', muted);
  });

  test('closes on a press outside it, on Esc, and on its button', async ({ page, people, shell }) => {
    await people.signIn();
    await shell.open();

    await shell.user.click();
    await expect(shell.profileMenu).toBeVisible();
    await shell.centre.click();
    await expect(shell.profileMenu).toBeHidden();

    await shell.user.click();
    await expect(shell.profileMenu).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(shell.profileMenu).toBeHidden();

    await shell.user.click();
    await expect(shell.profileMenu).toBeVisible();
    await shell.user.click();
    await expect(shell.profileMenu).toBeHidden();
  });

  test('stays open while the theme is chosen in it', async ({ people, shell }) => {
    await people.signIn();
    await shell.open();

    await shell.user.click();
    await shell.theme.selectOption('dark');
    await expect(shell.profileMenu).toBeVisible();
  });

  test('Sign out leaves through the sign-out endpoint', async ({ page, people, shell }) => {
    await people.signIn();
    await shell.open();

    await shell.user.click();
    const signOut = page.waitForRequest((request) => request.url().includes('/api/auth/logout'));
    await shell.signOut.click();
    await signOut;
  });
});
