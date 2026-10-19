/**
 * The theme (F109): system, light or dark, following the OS live under System, and remembered in
 * the browser (F133).
 */

import { test, expect } from '../support/fixtures';

test.describe('The theme', () => {
  test('follows the OS, live, under System', async ({ page, people, shell }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await people.signIn();
    await shell.open();
    const html = page.locator('html');

    await expect(html).toHaveAttribute('data-theme', 'light');
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(html).toHaveAttribute('data-theme', 'dark');
    await page.emulateMedia({ colorScheme: 'light' });
    await expect(html).toHaveAttribute('data-theme', 'light');
  });

  test('Light holds where the OS is dark, over the template’s tokens too, and is remembered', async ({ page, people, shell }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await people.signIn();
    await shell.open();
    const html = page.locator('html');
    await expect(html).toHaveAttribute('data-theme', 'dark');

    await shell.user.click();
    await shell.theme.selectOption('light');

    await expect(html).toHaveAttribute('data-theme', 'light');
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(255, 255, 255)');
    // A token index.css sets in its prefers-color-scheme block, and the mockup never had.
    const secondary = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--secondary').trim());
    expect(secondary).toBe('220 15% 96%');
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('pilot')!).theme)).toBe('light');

    await shell.open();
    await expect(html).toHaveAttribute('data-theme', 'light');
    await shell.user.click();
    await expect(shell.theme).toHaveValue('light');
  });

  test('Dark holds where the OS is light, and System follows the OS again', async ({ page, people, shell }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await people.signIn();
    await shell.open();
    const html = page.locator('html');

    await shell.user.click();
    await shell.theme.selectOption('dark');
    await expect(html).toHaveAttribute('data-theme', 'dark');
    const secondary = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--secondary').trim());
    expect(secondary).toBe('215 28% 17%');

    await shell.theme.selectOption('system');
    await expect(html).toHaveAttribute('data-theme', 'light');
  });
});
