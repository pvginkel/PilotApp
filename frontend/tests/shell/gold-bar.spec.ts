/**
 * The gold bar (F125; UC *The gold bar*): with the controller unreachable, it shows in every open
 * browser, at once and with no reload. Off a phone it is a badge in the top bar, left-aligned after
 * Pilot's name, the buttons' corner radius, its full line its title, the light theme's gold in both
 * themes at 4.5:1 or better; below 900px it is a line across the window under the top bar, in gold
 * tokens of its own, light and dark, the drawer opening under it. It goes when the controller
 * answers again, and nothing dismisses it. The time it began carries its date once that is an
 * earlier day than the viewer's today (R9). A stream that comes back up reads it again, covering a
 * turn missed while it was down (design 2 §6.2). A controller that answers about one environment
 * turns nothing on (review O2).
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { coloursOf, hue } from '../support/contrast';
import { makeUnique, waitForUiState } from '../support/helpers';
import { createDeploymentSseHelper } from '../support/helpers/deployment-sse';
import { ShellPage } from '../support/page-objects/shell-page';

const CLOCK = String.raw`\d\d:\d\d`;
const lineOf = (since: string) => new RegExp(String.raw`^The controller has been unreachable since ${since}\. Nothing starts until it answers\.$`);
const badgeOf = (since: string) => new RegExp(`^Controller unreachable since ${since}$`);
const LINE = lineOf(CLOCK);
const BADGE = badgeOf(CLOCK);
const PHONE = { width: 390, height: 844 };

async function boxes(shell: ShellPage) {
  const [top, brand, badge, bar, side, centre] = await Promise.all(
    [shell.topBar, shell.brand, shell.goldBadge('outage'), shell.goldBar, shell.side, shell.centre].map((locator) =>
      locator.boundingBox(),
    ),
  );
  return { top: top!, brand: brand!, badge, bar, side: side!, centre: centre! };
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

/** The buttons' corner radius, `--radius`, as the browser computes it. */
async function buttonRadius(page: Page): Promise<string> {
  return page.evaluate(() => {
    const probe = document.createElement('div');
    probe.style.borderRadius = 'var(--radius)';
    document.body.append(probe);
    const radius = getComputedStyle(probe).borderTopLeftRadius;
    probe.remove();
    return radius;
  });
}

test.describe('The gold bar', () => {
  test('shows the controller unreachable in every open browser, a badge in the top bar off a phone and a line on one, and goes when it answers', async ({
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
    await expect(shell.goldBadge('outage')).toHaveCount(0);

    await controller.outage(true);
    for (const each of [shell, other]) {
      await expect(each.goldBadge('outage')).toHaveText(BADGE);
      await expect(each.goldBadge('outage')).toHaveAttribute('title', LINE);
    }

    // Off a phone: the badge in the top bar, left-aligned after Pilot's name, in the buttons'
    // corner radius; no line over the project list, which starts under the top bar.
    await expect(shell.goldBar).toBeHidden();
    const wide = await boxes(shell);
    expect(wide.badge!.x).toBeCloseTo(wide.brand.x + wide.brand.width + 16, 0);
    expect(wide.badge!.y + wide.badge!.height / 2).toBeCloseTo(wide.top.y + wide.top.height / 2, 0);
    expect(wide.side.y).toBeCloseTo(wide.top.y + wide.top.height, 0);
    expect(wide.centre.y).toBeCloseTo(wide.side.y, 0);
    await expect(shell.goldBadge('outage')).toHaveCSS('border-radius', await buttonRadius(page));

    // Nothing dismisses it.
    await expect(shell.goldBadges.getByRole('button')).toHaveCount(0);
    await shell.goldBadge('outage').click();
    await page.keyboard.press('Escape');
    await expect(shell.goldBadge('outage')).toBeVisible();

    // A browser opened while it holds reads it as it opens.
    const late = await openAnother(page, '/profile');
    await expect(late.goldBadge('outage')).toHaveText(BADGE);

    // The light theme's gold in both themes, at 4.5:1 or better.
    const badgeBackgrounds: string[] = [];
    for (const scheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await expect(page.locator('html')).toHaveAttribute('data-theme', scheme);
      const { ratio, background } = await coloursOf(shell.goldBadge('outage'));
      expect(ratio, `the badge's contrast in ${scheme}`).toBeGreaterThanOrEqual(4.5);
      badgeBackgrounds.push(background.join());
    }
    expect(new Set(badgeBackgrounds).size).toBe(1);

    // Below the breakpoint: a line across the window under the top bar, the centre and the drawer
    // under it, and no badge.
    await page.setViewportSize(PHONE);
    await expect.poll(async () => (await shell.goldBar.boundingBox())?.width).toBe(PHONE.width);
    await expect(shell.goldBadges).toBeHidden();
    await expect(shell.goldLine('outage')).toHaveText(LINE);
    const narrow = await boxes(shell);
    expect(narrow.bar!.x).toBe(0);
    expect(narrow.bar!.y).toBeCloseTo(narrow.top.y + narrow.top.height, 0);
    expect(narrow.centre.y).toBeCloseTo(narrow.bar!.y + narrow.bar!.height, 0);
    expect(narrow.centre.width).toBe(PHONE.width);
    await shell.drawerToggle.click();
    await expect.poll(async () => (await shell.side.boundingBox())?.x).toBe(0);
    expect((await shell.side.boundingBox())!.y).toBeCloseTo(narrow.bar!.y + narrow.bar!.height, 0);
    await expect(shell.goldLine('outage')).toBeInViewport();

    // The line's own gold, at 4.5:1 or better, in either theme; the light one the badge's.
    const lineBackgrounds: string[] = [];
    for (const scheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await expect(page.locator('html')).toHaveAttribute('data-theme', scheme);
      const { ratio, background } = await coloursOf(shell.goldLine('outage'));
      expect(ratio, `the gold bar's contrast in ${scheme}`).toBeGreaterThanOrEqual(4.5);
      expect(Math.abs(hue(background) - 44), `the gold bar's hue in ${scheme}`).toBeLessThan(5);
      lineBackgrounds.push(background.join());
    }
    expect(new Set(lineBackgrounds).size).toBe(2);
    expect(lineBackgrounds[0]).toBe(badgeBackgrounds[0]);

    await controller.outage(false);
    await expect(shell.goldLine('outage')).toHaveCount(0);
    for (const each of [other, late]) await expect(each.goldBadge('outage')).toHaveCount(0);
  });

  test('gives the date with the time it began once that is an earlier day, on the badge, its title and the line', async ({
    page,
    people,
    shell,
    controller,
    conditions,
    deploymentSse,
  }) => {
    // The fixture's restore waits for the backend to read the controller answering at its fleet
    // stream's reconnect, whose backoff grows while the outage holds.
    test.setTimeout(90_000);
    await people.signIn();
    await controller.outage(true);
    const [{ since }] = await conditions.read();

    // The page's clock runs from the moment the outage began: its today is the outage's day.
    await page.clock.install({ time: new Date(since) });
    await shell.open('/profile');
    await deploymentSse.ensureConnected();
    await expect(shell.goldBadge('outage')).toHaveText(BADGE);
    await expect(shell.goldBadge('outage')).toHaveAttribute('title', LINE);

    // The page left open past its midnight.
    const { toMidnight, dated } = await page.evaluate((at) => {
      const began = new Date(at);
      const midnight = new Date(began.getFullYear(), began.getMonth(), began.getDate() + 1);
      const day = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }).format(began);
      const clock = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' }).format(began);
      return { toMidnight: midnight.getTime() - began.getTime(), dated: `${day}, ${clock}` };
    }, since);
    await page.clock.fastForward(toMidnight + 60_000);
    await expect(shell.goldBadge('outage')).toHaveText(badgeOf(dated));
    await expect(shell.goldBadge('outage')).toHaveAttribute('title', lineOf(dated));

    await page.setViewportSize(PHONE);
    await expect(shell.goldLine('outage')).toHaveText(lineOf(dated));

    // A page opened on a later day reads it dated as it opens.
    const later = await page.context().newPage();
    await later.clock.install({ time: new Date(Date.parse(since) + toMidnight + 60_000) });
    await later.goto('/profile');
    await expect(new ShellPage(later).goldBadge('outage')).toHaveText(badgeOf(dated));
  });

  test('is read again when the stream comes back up, showing an outage that began while it was down', async ({
    page,
    backendUrl,
    auth,
    people,
    shell,
    controller,
    deploymentSse,
    toastHelper,
  }) => {
    // The backend reads the controller answering at its fleet stream's reconnect, whose backoff
    // grows while the outage holds.
    test.setTimeout(90_000);
    await people.signIn();
    await shell.open('/profile');
    await deploymentSse.ensureConnected();
    await waitForUiState(page, 'shell.conditions', 'ready');
    await expect(shell.goldBadge('outage')).toHaveCount(0);

    // The stream goes down and stays down: its next connect is refused, and the session check
    // that would open it again fails.
    const refusal = await page.request.post(`${backendUrl}/api/testing/sse/force-callback-error?status=403`);
    expect(refusal.status()).toBe(204);
    await auth.forceError(500);
    await page.evaluate(() => window.__sseForceReconnect!());
    await toastHelper.expectErrorToast(/refresh the page/i);
    expect((await deploymentSse.getStatus()).isConnected).toBe(false);

    // The outage turns on while it is down: the browser does not hear it.
    await controller.outage(true);
    await expect(shell.goldBadge('outage')).toHaveCount(0);

    await deploymentSse.connect();
    await expect(shell.goldBadge('outage')).toHaveText(BADGE);

    await controller.outage(false);
    await expect(shell.goldBadge('outage')).toHaveCount(0);
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
    await shell.open('/profile');
    await deploymentSse.ensureConnected();
    await waitForUiState(page, 'shell.conditions', 'ready');

    // The environment the start creates is held `provisioning` until its worker is unreachable.
    await controller.settleCreates(null);
    const work = await projects.startWork(project, {
      title: 'Renaming the badge',
      brief: 'Rename the badge.',
      cwd: '/work/Example',
    });
    const { id: environment } = await projects.environment(project, work);
    // Its worker's 502 worker-unreachable fails the start, and holds no work.
    await controller.unreachable(environment);
    await controller.setStatus(environment, 'running');
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('failed');
    expect(await conditions.read()).toEqual([]);
    await expect(shell.goldBadge('outage')).toHaveCount(0);
    await expect(shell.goldLine('outage')).toHaveCount(0);
  });
});
