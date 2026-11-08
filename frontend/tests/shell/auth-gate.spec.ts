/**
 * The sign-in gate's screens, the template's: their message at the base size, as the mockup's
 * text is.
 */

import { test, expect } from '../support/fixtures';

test.describe('The sign-in gate', () => {
  test('says the server failed at the base size', async ({ page, auth }) => {
    await auth.forceError(500);
    await page.goto('/');

    const screen = page.getByTestId('auth.gate.error');
    await expect(screen.locator('p')).toHaveText('The server encountered an error. Please try again later.');
    await expect(screen.locator('p')).toHaveCSS('font-size', '15px');
  });

  test('says the account has no access at the base size', async ({ page, auth }) => {
    await auth.createSession({ name: 'No Roles', roles: [] });
    await page.goto('/');

    const screen = page.getByTestId('auth.gate.forbidden');
    await expect(screen.locator('p')).toHaveText(/^Your account is not authorized to use this application\./);
    await expect(screen.locator('p')).toHaveCSS('font-size', '15px');
  });
});
