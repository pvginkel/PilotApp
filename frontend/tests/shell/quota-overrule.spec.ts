/**
 * The week's halt's overrule on the gold bar (F135.2, F135.7; UC *The gold bar*): off a phone the
 * halt's badge is a button with a chevron that opens a popover under it, holding its line and the
 * overrule, so that a stray click on the top bar spends no quota; on a phone the overrule sits on the
 * halt's line. One at a time, as the halt offers it: under the second limit the allowance, its
 * target the share plus 5% and at most the second limit; at it, run-out. A toast says what it did,
 * and every open browser's bar follows. The overrule ends at its target, and the halt holds there
 * again. A browser that missed the reading that changed the offer is refused, with the reason. The
 * reading is the fake controller's, on the backend's fleet stream.
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { createDeploymentSseHelper } from '../support/helpers/deployment-sse';
import { ShellPage } from '../support/page-objects/shell-page';

const PHONE = { width: 390, height: 844 };
const CLOCK = String.raw`\d\d:\d\d`;

const WEEK_BADGE = new RegExp(`^Halted at the week’s limit since ${CLOCK}$`);
const weekLine = (percent: number) =>
  new RegExp(
    `^Work items have been halted at the week’s usage limit since ${CLOCK}\\. ${percent}% of the week’s quota is used, as of ${CLOCK}\\. `,
  );
const goOnTo = (percent: number) => `Work items go on until ${percent}% of the week’s quota is used.`;
const RUN_OUT = 'Work items go on until the week’s quota runs out.';

/** A browser of the same person's beside the spec's, open at `path` with its stream up. */
async function openAnother(page: Page, path: string): Promise<ShellPage> {
  const other = await page.context().newPage();
  const shell = new ShellPage(other);
  await other.goto(path);
  await expect(shell.user).toBeVisible();
  await createDeploymentSseHelper(other).ensureConnected();
  return shell;
}

test.describe('The week’s overrule', () => {
  test('opens from the halt’s badge, never from a click beside it; the allowance lets the held work go on to its target, where the halt holds again', async ({
    page,
    people,
    projects,
    controller,
    timeline,
    shell,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Overrule'), members: [me.handle!] });
    await controller.usage({ seven_day: 0.92, five_hour: 0.1 });
    const work = await projects.startWork(project, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('held');
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const other = await openAnother(page, '/profile');
    const item = timeline.item(work).work;
    const badge = shell.goldBadge('week_halt');
    const toast = (text: string) => page.getByTestId('app-shell.toast.item').getByText(text, { exact: true });

    await expect(badge).toHaveRole('button');
    await expect(badge).toHaveText(WEEK_BADGE);
    await expect(badge).toHaveAttribute('aria-expanded', 'false');
    await expect(shell.goldPopover).toHaveCount(0);

    // A click on the top bar beside the badge opens nothing.
    await shell.brand.click();
    await expect(shell.goldPopover).toHaveCount(0);

    // The popover drops under the badge, left-aligned with it, its line and its button in it.
    await badge.click();
    await expect(badge).toHaveAttribute('aria-expanded', 'true');
    await expect(shell.goldText(shell.goldPopover)).toHaveText(weekLine(92));
    const button = shell.goldOverrule(shell.goldPopover);
    await expect(button).toHaveText('Go on to 97%');
    await expect(button).toHaveAttribute('title', goOnTo(97));
    const [badgeBox, popBox] = await Promise.all([badge.boundingBox(), shell.goldPopover.boundingBox()]);
    expect(popBox!.x).toBeCloseTo(badgeBox!.x, 0);
    expect(popBox!.y).toBeCloseTo(badgeBox!.y + badgeBox!.height + 8, 0);
    // A button's shape, ruled in the line's text colour.
    const textColour = await shell.goldText(shell.goldPopover).evaluate((text) => getComputedStyle(text).color);
    await expect(button).toHaveCSS('border-top-color', textColour);

    // Esc closes it, and so does a press outside it, neither making the overrule.
    await page.keyboard.press('Escape');
    await expect(shell.goldPopover).toHaveCount(0);
    await badge.click();
    await shell.brand.click();
    await expect(shell.goldPopover).toHaveCount(0);
    await expect(item.cue).toHaveText('Halted at the week’s limit');

    await badge.click();
    await button.click();
    await expect(toast(goOnTo(97))).toBeVisible();
    await expect(badge).toHaveCount(0);
    await expect(other.goldBadge('week_halt')).toHaveCount(0);
    await expect(item.running).toBeVisible();

    // A reading at its target ends it: the halt holds again, the allowance now up to the second limit.
    await controller.usage({ seven_day: 0.97, five_hour: 0.1 });
    await expect(badge).toHaveText(WEEK_BADGE);
    await expect(other.goldBadge('week_halt')).toHaveText(WEEK_BADGE);
    await badge.click();
    await expect(shell.goldText(shell.goldPopover)).toHaveText(weekLine(97));
    await expect(button).toHaveText('Go on to 98%');
  });

  test('at the second limit runs the quota out, on a phone from the halt’s line', async ({ page, people, controller, shell, deploymentSse }) => {
    await people.signIn();
    await controller.usage({ seven_day: 0.98, five_hour: 0.1 });
    await shell.open('/profile');
    await deploymentSse.ensureConnected();
    await page.setViewportSize(PHONE);

    const line = shell.goldLine('week_halt');
    await expect(shell.goldText(line)).toHaveText(weekLine(98));
    const button = shell.goldOverrule(line);
    await expect(button).toHaveText('Run it out');
    await expect(button).toHaveAttribute('title', RUN_OUT);
    const textColour = await shell.goldText(line).evaluate((text) => getComputedStyle(text).color);
    await expect(button).toHaveCSS('border-top-color', textColour);

    await button.click();
    await expect(page.getByTestId('app-shell.toast.item').getByText(RUN_OUT, { exact: true })).toBeVisible();
    await expect(line).toHaveCount(0);
  });

  test('is refused, with the reason, where the browser missed the reading that changed the offer', async ({
    page,
    backendUrl,
    auth,
    people,
    controller,
    conditions,
    shell,
    deploymentSse,
    toastHelper,
  }) => {
    await people.signIn();
    await controller.usage({ seven_day: 0.92, five_hour: 0.1 });
    await shell.open('/profile');
    await deploymentSse.ensureConnected();
    await expect(shell.goldBadge('week_halt')).toHaveText(WEEK_BADGE);

    // The stream goes down and stays down: its next connect is refused, and the session check
    // that would open it again fails.
    const refusal = await page.request.post(`${backendUrl}/api/testing/sse/force-callback-error?status=403`);
    expect(refusal.status()).toBe(204);
    await auth.forceError(500);
    await page.evaluate(() => window.__sseForceReconnect!());
    await toastHelper.expectErrorToast(/refresh the page/i);

    // The week reaches the second limit, where run-out is offered: the browser does not hear it.
    await controller.usage({ seven_day: 0.98, five_hour: 0.1 });
    await expect.poll(async () => (await conditions.read()).find((condition) => condition.code === 'week_halt')?.offer).toBe('run_out');
    await shell.goldBadge('week_halt').click();
    await expect(shell.goldOverrule(shell.goldPopover)).toHaveText('Go on to 97%');

    await shell.goldOverrule(shell.goldPopover).click();
    await toastHelper.expectErrorToast(
      "Cannot add the week's allowance because the week's share is at the second limit, where only run-out is offered",
    );
    await expect(shell.goldBadge('week_halt')).toBeVisible();
  });
});
