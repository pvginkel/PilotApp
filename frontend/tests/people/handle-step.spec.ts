/**
 * The handle step (F137): at a first sign-in it stands under the top bar, whose user menu works
 * there, and the app opens once the person has chosen their handle.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique, waitTestEvent } from '../support/helpers';
import type { FormTestEvent } from '@/lib/test/test-events';

test.describe('The handle step', () => {
  test('opens at a first sign-in under the top bar, and nothing else of the app does', async ({ people, shell, handleStep }) => {
    await people.firstSignIn({ name: 'Ada Lovelace' });
    await shell.open();

    await expect(shell.topBar).toBeVisible();
    await expect(handleStep.heading).toHaveText('Choose your handle');
    await expect(handleStep.root).toContainText('Lower-case letters, digits and hyphens. Once chosen, it cannot be changed.');
    await expect(handleStep.field).toHaveAccessibleName('Handle');
    await expect(shell.app).toHaveCount(0);
    await expect(shell.drawerToggle).toHaveCount(0);
  });

  test("prefills the field with the name's first word, made to fit a handle", async ({ people, shell, handleStep }) => {
    await people.firstSignIn({ name: 'Ádám Smith' });
    await shell.open();

    await expect(handleStep.field).toHaveValue('adam');
    await expect(handleStep.field).toBeFocused();
  });

  test("has the text field's look: one line, its button in view", async ({ page, people, shell, handleStep }) => {
    await people.firstSignIn();
    await shell.open();

    await expect(handleStep.field).toHaveJSProperty('tagName', 'INPUT');
    await expect(handleStep.field).toHaveCSS('height', '38px');
    await expect(handleStep.choose).toHaveCSS('height', '38px');
    const field = (await handleStep.field.boundingBox())!;
    const button = (await handleStep.choose.boundingBox())!;
    expect(button.y).toBe(field.y);
    expect(button.x).toBeGreaterThan(field.x + field.width);

    await page.setViewportSize({ width: 390, height: 800 });
    await expect(handleStep.choose).toBeInViewport({ ratio: 1 });
  });

  test("the top bar's menu works there: the name and Sign out, no Profile", async ({ page, people, shell }) => {
    await people.firstSignIn({ name: 'Ada Lovelace' });
    await shell.open();

    await shell.user.click();
    await expect(shell.profileName).toHaveText('Ada Lovelace');
    await expect(shell.profileMenu.getByRole('menuitem')).toHaveText(['Sign out']);
    const signOut = page.waitForRequest((request) => request.url().includes('/api/auth/logout'));
    await shell.signOut.click();
    await signOut;
  });

  test('Enter chooses the handle, and the app opens on the address asked for', async ({ page, people, shell, handleStep, profile }) => {
    await people.firstSignIn({ name: 'Ada Lovelace' });
    await shell.open('/profile');
    await expect(handleStep.root).toBeVisible();
    await expect(profile.root).toHaveCount(0);

    const handle = makeUnique('ada', 8);
    await handleStep.field.fill(handle);
    await handleStep.field.press('Enter');
    await waitTestEvent<FormTestEvent>(page, 'form', (event) => event.formId === 'people.handle' && event.phase === 'success');

    await expect(handleStep.root).toHaveCount(0);
    await expect(shell.app).toBeVisible();
    await expect(profile.handle).toHaveText(handle);
    await expect(shell.avatar).toHaveAttribute('data-colour', /^[1-6]$/);

    // Fixed once chosen: the next sign-in opens the app.
    await shell.open();
    await expect(shell.app).toBeVisible();
    await expect(handleStep.root).toHaveCount(0);
    expect((await people.self()).handle).toBe(handle);
  });

  test('without a name on the token it starts empty, and the handle becomes the name', async ({ people, shell, handleStep }) => {
    await people.firstSignIn({ name: null });
    await shell.open();

    await expect(handleStep.field).toHaveValue('');
    await expect(handleStep.choose).toBeDisabled();
    const handle = makeUnique('nameless', 6);
    await handleStep.field.fill(handle);
    await handleStep.choose.click();

    await expect(shell.app).toBeVisible();
    await expect(shell.userName).toHaveText(handle);
    await expect(shell.avatar).toHaveAttribute('title', handle);
  });

  test('refuses a handle off the pattern, Pilot’s and a taken one, with the reason, and stays', async ({ page, people, shell, handleStep }) => {
    const taken = makeUnique('taken', 8);
    await people.other(taken);
    await people.firstSignIn({ name: 'Ada Lovelace' });
    await shell.open();

    const refusals = [
      ['Ada', 'a handle holds only lower-case letters, digits and hyphens'],
      ['agent', "it is Pilot's"],
      [taken, 'another person has it'],
    ];
    for (const [handle, reason] of refusals) {
      await handleStep.field.fill(handle);
      await handleStep.field.press('Enter');
      const toast = page.getByTestId('app-shell.toast.item').filter({ hasText: `Cannot choose the handle '${handle}' because ${reason}` });
      await expect(toast).toBeVisible();
      await expect(handleStep.field).toHaveValue(handle);
      await expect(handleStep.choose).toBeEnabled();
    }
    await expect(shell.app).toHaveCount(0);
    expect((await people.self()).handle).toBeNull();
  });
});
