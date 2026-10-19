/**
 * The frame every screen sits in: the side column beside the centre on a wide window, a drawer
 * with a scrim under the mockup's breakpoint (F98.3), the same components.
 */

import { test, expect } from '../support/fixtures';

test.describe('The layout on a wide window', () => {
  test('stands the side column beside the centre, with no drawer toggle', async ({ people, shell }) => {
    await people.signIn();
    await shell.open();

    await expect(shell.drawerToggle).toBeHidden();
    await expect(shell.side).toBeVisible();
    await expect(shell.scrim).toBeHidden();
    const side = (await shell.side.boundingBox())!;
    const centre = (await shell.centre.boundingBox())!;
    expect(side.width).toBe(264);
    expect(centre.x).toBeGreaterThanOrEqual(side.x + side.width);
  });
});

test.describe('The drawer on a narrow window', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('opens from the top bar’s toggle and closes by its scrim', async ({ people, shell }) => {
    await people.signIn();
    await shell.open();

    await expect(shell.drawerToggle).toBeVisible();
    await expect(shell.drawerToggle).toHaveAttribute('aria-expanded', 'false');
    await expect(shell.side).toBeHidden();
    await expect(shell.scrim).toBeHidden();

    await shell.drawerToggle.click();
    await expect(shell.side).toBeVisible();
    await expect(shell.side).toBeInViewport();
    await expect(shell.scrim).toBeVisible();
    await expect(shell.drawerToggle).toHaveAttribute('aria-expanded', 'true');
    // Over the centre once it has slid in.
    await expect.poll(async () => (await shell.side.boundingBox())?.x).toBe(0);
    expect((await shell.side.boundingBox())!.width).toBe(300);
    expect((await shell.centre.boundingBox())!.x).toBe(0);

    // The scrim beside the drawer, which covers its left 300px.
    await shell.scrim.click({ position: { x: 350, y: 300 } });
    await expect(shell.side).toBeHidden();
    await expect(shell.scrim).toBeHidden();
  });

  test('closes again from the toggle', async ({ people, shell }) => {
    await people.signIn();
    await shell.open();

    await shell.drawerToggle.click();
    await expect(shell.side).toBeVisible();
    await shell.drawerToggle.click();
    await expect(shell.side).toBeHidden();
  });
});
