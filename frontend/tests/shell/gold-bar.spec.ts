/**
 * The gold bar (F125; UC *The gold bar*): with the controller unreachable, its line stands over
 * the project list in every open browser, at once and with no reload, in gold tokens of its own at
 * 4.5:1 or better, light and dark; below 900px it spans the window under the top bar, the drawer
 * opening under it. It goes when the controller answers again, and nothing dismisses it. A
 * controller that answers about one environment turns nothing on (review O2).
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { coloursOf, hue } from '../support/contrast';
import { makeUnique, waitForUiState } from '../support/helpers';
import { createDeploymentSseHelper } from '../support/helpers/deployment-sse';
import { ShellPage } from '../support/page-objects/shell-page';

const LINE = /^The controller has been unreachable since \d\d:\d\d\. Nothing starts until it answers\.$/;

async function boxes(shell: ShellPage) {
  const [top, bar, side, centre] = await Promise.all(
    [shell.topBar, shell.goldBar, shell.side, shell.centre].map(async (locator) => (await locator.boundingBox())!),
  );
  return { top, bar, side, centre };
}

/** A browser of the same person's beside the spec's, open at `path` with its stream up. */
async function openAnother(page: Page, path: string): Promise<ShellPage> {
  const other = await page.context().newPage();
  const shell = new ShellPage(other);
  await other.goto(path);
  await expect(shell.user).toBeVisible();
  await createDeploymentSseHelper(other).ensureConnected();
  return shell;
}

test.describe('The gold bar', () => {
  test('shows the controller unreachable over the project list in every open browser, and goes when it answers', async ({
    page,
    people,
    shell,
    controller,
    deploymentSse,
  }) => {
    // The backend reads the controller answering at its fleet stream's reconnect, whose backoff
    // grows while the outage holds.
    test.setTimeout(90_000);
    await people.signIn();
    await shell.open('/profile');
    await deploymentSse.ensureConnected();
    await waitForUiState(page, 'shell.conditions', 'ready');
    const other = await openAnother(page, '/profile');
    await expect(shell.goldLine('outage')).toHaveCount(0);

    await controller.outage(true);
    for (const each of [shell, other]) await expect(each.goldLine('outage')).toHaveText(LINE);

    // Over the project list, in the side column's width; the centre beside both from the top bar down.
    const wide = await boxes(shell);
    expect(wide.bar.x).toBe(wide.side.x);
    expect(wide.bar.width).toBe(264);
    expect(wide.bar.y).toBeCloseTo(wide.top.y + wide.top.height, 0);
    expect(wide.side.y).toBeCloseTo(wide.bar.y + wide.bar.height, 0);
    expect(wide.centre.y).toBeCloseTo(wide.bar.y, 0);
    expect(wide.centre.x).toBeGreaterThanOrEqual(wide.bar.x + wide.bar.width);

    // Nothing dismisses it.
    await expect(shell.goldBar.getByRole('button')).toHaveCount(0);
    await shell.goldLine('outage').click();
    await page.keyboard.press('Escape');
    await expect(shell.goldLine('outage')).toBeVisible();

    // A browser opened while it holds reads it as it opens.
    const late = await openAnother(page, '/profile');
    await expect(late.goldLine('outage')).toHaveText(LINE);

    // Its own gold, at 4.5:1 or better, in either theme.
    const backgrounds: string[] = [];
    for (const scheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await expect(page.locator('html')).toHaveAttribute('data-theme', scheme);
      const { ratio, background } = await coloursOf(shell.goldLine('outage'));
      expect(ratio, `the gold bar's contrast in ${scheme}`).toBeGreaterThanOrEqual(4.5);
      expect(Math.abs(hue(background) - 44), `the gold bar's hue in ${scheme}`).toBeLessThan(5);
      backgrounds.push(background.join());
    }
    expect(new Set(backgrounds).size).toBe(2);

    // Below the breakpoint: across the window under the top bar, the centre and the drawer under it.
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(async () => (await shell.goldBar.boundingBox())?.width).toBe(390);
    const narrow = await boxes(shell);
    expect(narrow.bar.x).toBe(0);
    expect(narrow.bar.y).toBeCloseTo(narrow.top.y + narrow.top.height, 0);
    expect(narrow.centre.y).toBeCloseTo(narrow.bar.y + narrow.bar.height, 0);
    expect(narrow.centre.width).toBe(390);
    await shell.drawerToggle.click();
    await expect.poll(async () => (await shell.side.boundingBox())?.x).toBe(0);
    expect((await shell.side.boundingBox())!.y).toBeCloseTo(narrow.bar.y + narrow.bar.height, 0);
    await expect(shell.goldLine('outage')).toBeInViewport();

    await controller.outage(false);
    for (const each of [shell, other, late]) await expect(each.goldLine('outage')).toHaveCount(0);
  });

  test('stays away while the controller answers about one environment alone', async ({
    page,
    people,
    projects,
    shell,
    controller,
    conditions,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Worker'), members: [me.handle!] });
    const environment = await controller.environment();
    await shell.open('/profile');
    await deploymentSse.ensureConnected();
    await waitForUiState(page, 'shell.conditions', 'ready');

    // Its worker's 502 worker-unreachable fails the start, and holds no work.
    await controller.unreachable(environment);
    const work = await projects.startWork(project, {
      environment_id: environment,
      title: 'Renaming the badge',
      brief: 'Rename the badge.',
      cwd: '/work/Example',
    });
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('failed');
    expect(await conditions.read()).toEqual([]);
    await expect(shell.goldLine('outage')).toHaveCount(0);
  });
});
