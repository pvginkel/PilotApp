/**
 * The two screens (F160.1 to F160.4): Projects and the Dashboard, tabs in the top bar after Pilot's
 * name; the screen out of sight hidden in the same box, out of the flow and inert, never rebuilt;
 * the dashboard drawn when an address first names it, its module read then; its address the app's
 * with `#dash` after it, the project behind kept matched and read, through the bare address and
 * through sign-in too; entering it a new entry of the browser's history.
 */

import type { Locator, Page } from '@playwright/test';
import type { UiStateTestEvent } from '@/lib/test/test-events';
import { test, expect } from '../support/fixtures';
import { makeUnique, waitTestEvent } from '../support/helpers';
import { projectAddress, type Projects } from '../support/projects';

const WORDS = Array.from({ length: 160 }, (_, index) => `word${index}`).join(' ');
/** A document long enough to be a card on the timeline. */
const card = (title: string) => `---\ntitle: ${title}\n---\n\n${WORDS}\n`;
/** A dashboard address of a tab and its view's state, as a link names one. */
const VIEW = '#dash/t1/t=qw&by=project&m=cost.sum&col=none';

/** A project of the person's whose timeline holds more than its screen shows. */
async function longProject(projects: Projects, handle: string): Promise<string> {
  const project = await projects.makeWithSession({ name: makeUnique('Screens'), members: [handle] });
  for (const title of ['Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot']) await projects.place(project, { kind: 'document', title, text: card(title) });
  return project;
}

/** The page's reads of the project's own API from the call on; read by the answer. */
function projectReads(page: Page, project: string): () => string[] {
  const reads: string[] = [];
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith(`/api/projects/${project}`)) reads.push(path);
  });
  return () => reads;
}

/** The read and drawing of a project's timeline, once it is in: not at StrictMode's first unmount, marked aborted. */
function timelineRead(page: Page): Promise<UiStateTestEvent> {
  return waitTestEvent<UiStateTestEvent>(page, 'ui_state', (event) => event.scope === 'project.timeline' && event.phase === 'ready' && event.metadata?.status !== 'aborted');
}

const historyLength = (page: Page) => page.evaluate(() => history.length);
const box = (locator: Locator) => locator.evaluate((element) => element.getBoundingClientRect().toJSON() as DOMRect);

test.describe('The screens’ tabs', () => {
  test('stand in the top bar after the name, Projects and Dashboard, text alone, the one showing marked', async ({ people, projects, shell, timeline }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Screens'), members: [me.handle!] });
    await timeline.open(project);

    await expect(shell.screens.locator('a')).toHaveText(['Projects', 'Dashboard']);
    await expect(shell.brand.locator('xpath=following-sibling::*[1]')).toHaveAttribute('data-testid', 'shell.screens');
    await expect(shell.screens.locator('svg, img')).toHaveCount(0);
    await expect(shell.projectsTab).toHaveAttribute('aria-current', 'page');
    await expect(shell.dashboardTab).not.toHaveAttribute('aria-current');
    await expect(shell.projectsTab).toHaveAttribute('href', projectAddress(project));
    await expect(shell.dashboardTab).toHaveAttribute('href', `${projectAddress(project)}#dash`);
    for (const tab of [shell.projectsTab, shell.dashboardTab]) {
      await expect(tab).toHaveCSS('color', 'rgb(255, 255, 255)');
      await expect(tab).toHaveCSS('font-size', '19px');
      await expect(tab).toHaveCSS('font-weight', '700');
    }
    await expect(shell.projectsTab).toHaveCSS('border-bottom-color', 'rgb(255, 255, 255)');
    await expect(shell.dashboardTab).toHaveCSS('border-bottom-color', 'rgba(0, 0, 0, 0)');

    await shell.dashboardTab.click();
    await expect(shell.dashboardTab).toHaveAttribute('aria-current', 'page');
    await expect(shell.projectsTab).not.toHaveAttribute('aria-current');
    await expect(shell.dashboardTab).toHaveCSS('border-bottom-color', 'rgb(255, 255, 255)');
  });

  test('are not there at the handle step, where a dashboard address shows the handle step', async ({ page, people, shell, handleStep, dashboard }) => {
    await people.firstSignIn();
    await shell.open('/#dash');

    await expect(handleStep.root).toBeVisible();
    await expect(shell.screens).toHaveCount(0);
    await expect(dashboard.screen).toHaveCount(0);
    await expect(page).toHaveURL(/#dash$/);
  });
});

test.describe('The dashboard beside the Projects screen', () => {
  test('Dashboard shows it as a new entry, the project out of sight in the same box; Projects shows the project as it was left, nothing read again, and the dashboard stays drawn, its module read once', async ({
    page,
    people,
    projects,
    shell,
    timeline,
    dashboard,
  }) => {
    const me = await people.signIn();
    const project = await longProject(projects, me.handle!);
    const moduleReads = dashboard.moduleReads();
    await timeline.open(project);
    await timeline.root.evaluate((feed) => (feed.scrollTop = 120));
    const left = await timeline.scrollTop();
    expect(left).toBeGreaterThan(0);
    const reads = projectReads(page, project);
    const entries = await historyLength(page);
    await expect(dashboard.screen).toHaveCount(0);
    expect(moduleReads()).toBe(0);

    await shell.dashboardTab.click();
    await expect(page).toHaveURL(`${projectAddress(project)}#dash`);
    expect(await historyLength(page)).toBe(entries + 1);
    await expect(dashboard.screen).toBeVisible();
    await expect(dashboard.screen).not.toHaveAttribute('inert');
    await expect(shell.app).toBeHidden();
    await expect(shell.app).toHaveAttribute('inert', '');
    await expect(shell.app).toHaveCSS('position', 'absolute');
    expect(await box(shell.app)).toEqual(await box(dashboard.screen));
    expect(moduleReads()).toBe(1);
    await dashboard.screen.evaluate((screen) => (screen.dataset.marked = 'yes'));

    await shell.projectsTab.click();
    await expect(page).toHaveURL(projectAddress(project));
    expect(await historyLength(page)).toBe(entries + 2);
    await expect(shell.app).toBeVisible();
    await expect(shell.app).not.toHaveAttribute('inert');
    await expect(dashboard.screen).toBeHidden();
    await expect(dashboard.screen).toHaveAttribute('inert', '');
    await expect(dashboard.screen).toHaveCSS('position', 'absolute');
    expect(await box(dashboard.screen)).toEqual(await box(shell.app));
    expect(await timeline.scrollTop()).toBe(left);

    await shell.dashboardTab.click();
    await expect(dashboard.screen).toBeVisible();
    await expect(dashboard.screen).toHaveAttribute('data-marked', 'yes');
    await shell.projectsTab.click();
    await expect(shell.app).toBeVisible();
    expect(await timeline.scrollTop()).toBe(left);
    expect(moduleReads()).toBe(1);
    expect(reads()).toEqual([]);
  });

  test('Back from it shows the project as it was left, and Forward it again', async ({ page, people, projects, shell, timeline, dashboard }) => {
    const me = await people.signIn();
    const project = await longProject(projects, me.handle!);
    await timeline.open(project);
    await timeline.root.evaluate((feed) => (feed.scrollTop = 120));
    const left = await timeline.scrollTop();

    await shell.dashboardTab.click();
    await expect(dashboard.screen).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(projectAddress(project));
    await expect(shell.app).toBeVisible();
    await expect(shell.projectsTab).toHaveAttribute('aria-current', 'page');
    expect(await timeline.scrollTop()).toBe(left);

    await page.goForward();
    await expect(page).toHaveURL(`${projectAddress(project)}#dash`);
    await expect(dashboard.screen).toBeVisible();
    await expect(shell.app).toBeHidden();
  });

  test('opened cold at a dashboard address reads the project behind it, which Projects shows at once; Dashboard goes back to the address it was left on', async ({
    page,
    people,
    projects,
    shell,
    timeline,
    dashboard,
  }) => {
    const me = await people.signIn();
    const project = await longProject(projects, me.handle!);

    const read = timelineRead(page);
    await shell.open(`${projectAddress(project)}${VIEW}`);
    await read;
    await expect(dashboard.screen).toBeVisible();
    await expect(shell.app).toBeHidden();
    await expect(shell.dashboardTab).toHaveAttribute('href', `${projectAddress(project)}${VIEW}`);
    const reads = projectReads(page, project);

    await shell.projectsTab.click();
    await expect(page).toHaveURL(projectAddress(project));
    await expect(timeline.items).not.toHaveCount(0);
    await shell.dashboardTab.click();
    await expect(page).toHaveURL(`${projectAddress(project)}${VIEW}`);
    await expect(dashboard.screen).toBeVisible();
    expect(reads()).toEqual([]);
  });

  test('at the bare address keeps its hash through the step to the remembered project', async ({ page, people, projects, shell, timeline, dashboard }) => {
    const me = await people.signIn();
    const project = await longProject(projects, me.handle!);
    await timeline.open(project);

    const read = timelineRead(page);
    await shell.open(`/${VIEW}`);
    await expect(page).toHaveURL(`${projectAddress(project)}${VIEW}`);
    await read;
    await expect(dashboard.screen).toBeVisible();
    await shell.projectsTab.click();
    await expect(timeline.items).not.toHaveCount(0);
  });

  test('at the narrow width has no drawer’s toggle in the top bar, which the Projects screen has again', async ({ page, people, projects, shell, timeline, dashboard }) => {
    await page.setViewportSize({ width: 1000, height: 800 });
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Screens'), members: [me.handle!] });
    await timeline.open(project);
    await expect(shell.drawerToggle).toBeVisible();

    await shell.dashboardTab.click();
    await expect(dashboard.screen).toBeVisible();
    await expect(shell.drawerToggle).toHaveCount(0);
    await shell.projectsTab.click();
    await expect(shell.drawerToggle).toBeVisible();
  });
});

test.describe('A dashboard address signed out', () => {
  test('is the address sign-in comes back to, its hash with it', async ({ page, auth }) => {
    await auth.clearSession();
    await auth.forceError(401);
    const login = page.waitForRequest((request) => request.url().includes('/api/auth/login'));

    await page.goto(`/projects/seed-swap${VIEW}`);

    const redirect = new URL((await login).url()).searchParams.get('redirect');
    expect(redirect).toBe(`/projects/seed-swap${VIEW}`);
  });
});
