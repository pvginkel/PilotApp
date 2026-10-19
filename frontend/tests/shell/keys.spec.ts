/**
 * The keys (F110): `?` opens the keys list, and Esc closes the top-most open thing, one per press.
 */

import { test, expect } from '../support/fixtures';

test.describe('Keys', () => {
  test('? opens the keys list, with Pilot’s own keys, and closes it again', async ({ page, people, shell }) => {
    await people.signIn();
    await shell.open();

    await page.keyboard.press('?');
    await expect(shell.keys).toBeVisible();
    await expect(shell.keys.getByRole('heading')).toHaveText('Keys');
    await expect(shell.keys.locator('dt')).toHaveText(['Esc', '?']);

    await page.keyboard.press('?');
    await expect(shell.keys).toBeHidden();
  });

  test('Esc or a click beside it closes the keys list', async ({ page, people, shell }) => {
    await people.signIn();
    await shell.open();

    await page.keyboard.press('?');
    await expect(shell.keys).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(shell.keys).toBeHidden();

    await page.keyboard.press('?');
    await shell.keys.click();
    await expect(shell.keys).toBeVisible();
    await shell.keysBackdrop.click({ position: { x: 5, y: 5 } });
    await expect(shell.keys).toBeHidden();
  });

  test('Esc closes the top-most open thing, one per press', async ({ page, people, shell }) => {
    await people.signIn();
    await shell.open();

    await shell.user.click();
    await expect(shell.profileMenu).toBeVisible();
    await page.keyboard.press('?');
    await expect(shell.keys).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(shell.keys).toBeHidden();
    await expect(shell.profileMenu).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(shell.profileMenu).toBeHidden();
  });

  test('? with a modifier held opens nothing', async ({ page, people, shell }) => {
    await people.signIn();
    await shell.open();

    await page.keyboard.press('Control+?');
    await page.keyboard.press('?');
    await expect(shell.keys).toBeVisible();
    await page.keyboard.press('?');
    await expect(shell.keys).toBeHidden();
  });
});
