/**
 * Toasts (F112): the template's, in the mockup's look and place.
 */

import { test, expect } from '../support/fixtures';

test('a toast has the mockup’s look, 24px from the corner', async ({ page, people, shell }) => {
  await people.signIn();
  await shell.open();

  await page.evaluate(() => {
    window.dispatchEvent(
      new CustomEvent('app:testing:show-exception', {
        detail: { message: 'toast look', error: new Error('toast look') },
      }),
    );
  });

  const toast = page.getByTestId('app-shell.toast.item').filter({ hasText: 'toast look' });
  await expect(toast).toBeVisible();
  const background = await page.locator('body').evaluate((body) => getComputedStyle(body).backgroundColor);
  await expect(toast).toHaveCSS('background-color', background);
  await expect(toast).toHaveCSS('border-radius', '8px');
  await expect(toast).toHaveCSS('max-width', '380px');
  await expect(toast.getByText('toast look')).toHaveCSS('font-size', '13.5px');

  // Once it has slid in.
  const viewport = page.viewportSize()!;
  const gaps = async () => {
    const box = (await toast.boundingBox())!;
    return [Math.round(viewport.width - (box.x + box.width)), Math.round(viewport.height - (box.y + box.height))];
  };
  await expect.poll(gaps).toEqual([24, 24]);
});
