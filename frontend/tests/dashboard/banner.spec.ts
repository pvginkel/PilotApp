/**
 * What failed is a banner under the global toolbar (F160.8): a refusal of the engine's shows its
 * reason there, with Retry, the previous answer staying drawn; the banner closes, and a read that
 * goes well takes it away. A state's fault is refused as its normal form is read; a read past the
 * engine's bounds (F154.5) as its rows are, the engine's timeout set below any read's here.
 */

import type { Page, Response } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import type { Collection } from '../support/collection';
import { NONE_LEFT } from '../support/dashboard-bounds';
import { expectConsoleError, makeUnique } from '../support/helpers';
import { dashboardAddress, type DashboardPage } from '../support/page-objects/dashboard-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';

/** The engine's refusal of a read past its timeout, as the backend words it. */
const TIMED_OUT = "its read ran past the engine's timeout of 1e-09 s";

/** The tally on two projects of the person's, and the chip that names them. */
async function tally(people: People, projects: Projects, collection: Collection) {
  const me = await people.signIn();
  const recipeBox = await projects.make({ name: makeUnique('Recipes'), members: [me.handle!] });
  const bikeLog = await projects.make({ name: makeUnique('Bikes'), members: [me.handle!] });
  await collection.loadScenario('tally', { 'recipe-box': recipeBox, 'bike-log': bikeLog });
  return { first: recipeBox, chip: `c=project:${recipeBox},${bikeLog}` };
}

const declareRefusals = (page: Page) => expectConsoleError(page, /409/);

/** The chip's projects named, their lookups answered before the engine refuses every read. */
const labelled = (dashboard: DashboardPage) => expect(dashboard.chipWords(dashboard.chips)).toHaveText(/Recipes-.*Bikes-|Bikes-.*Recipes-/);

/** The rows next answered. */
const rowsAnswered = (page: Page) =>
  page.waitForResponse((response: Response) => new URL(response.url()).pathname === '/api/dashboard/rows' && response.ok());

test.describe('The dashboard’s banner', () => {
  test('shows a refusal’s reason under the toolbar, the previous answer staying drawn; Retry asks again, and the banner closes', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const me = await people.signIn();
    const recipeBox = await projects.make({ name: makeUnique('Recipes'), members: [me.handle!] });
    const bikeLog = await projects.make({ name: makeUnique('Bikes'), members: [me.handle!] });
    await collection.loadScenario('tally', { 'recipe-box': recipeBox, 'bike-log': bikeLog });
    const chip = `c=project:${recipeBox},${bikeLog}`;
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await expect(dashboard.rows).toHaveCount(2);
    await expect(dashboard.banner).toHaveCount(0);
    await expectConsoleError(page, /400/);
    const refused = `t=all&by=projekt&m=cost.sum&${chip}`;
    const reads = dashboard.addressReads();

    await dashboard.go(dashboardAddress(refused));

    await expect(dashboard.bannerText).toContainText('- by=projekt: "projekt" is no dimension. Did you mean "project"?');
    await expect(dashboard.toolbar.locator('xpath=following-sibling::*[1]')).toHaveAttribute('data-testid', 'dashboard.banner');
    await expect(dashboard.rows).toHaveCount(2);
    await expect(dashboard.allValues).toHaveText(['$2.29']);
    expect(reads()).toEqual([refused]);

    await dashboard.retry.click();
    await expect.poll(() => reads()).toEqual([refused, refused]);
    await expect(dashboard.bannerText).toContainText('"projekt" is no dimension');

    await dashboard.closeBanner.click();
    await expect(dashboard.banner).toHaveCount(0);
    await expect(dashboard.rows).toHaveCount(2);
  });

  test('shows the engine’s refusal of the rows read again on the walk’s event, the figures drawn staying; Retry reads them again', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    dashboardBounds,
    deploymentSse,
  }) => {
    const { first, chip } = await tally(people, projects, collection);
    const state = `t=all&by=project&m=cost.sum&${chip}`;
    await shell.open(`${projectAddress(first)}${dashboardAddress(state)}`);
    await deploymentSse.ensureConnected();
    await expect(dashboard.rows).toHaveCount(2);
    await labelled(dashboard);
    await declareRefusals(page);
    await dashboardBounds.set({ timeout_seconds: NONE_LEFT });
    const reads = dashboard.rowsReads();

    expect((await collection.walk()).announced).toBe(true);

    await expect(dashboard.bannerText).toContainText(TIMED_OUT);
    await expect(dashboard.rows).toHaveCount(2);
    await expect(dashboard.allValues).toHaveText(['$2.29']);
    expect(reads()).toHaveLength(1);

    await dashboard.retry.click();
    await expect.poll(() => reads()).toHaveLength(2);
    await expect(dashboard.bannerText).toContainText(TIMED_OUT);

    await dashboardBounds.set({});
    const answered = rowsAnswered(page);
    await dashboard.retry.click();
    await answered;
    expect(reads()).toHaveLength(3);
    await expect(dashboard.banner).toHaveCount(0);
    await expect(dashboard.allValues).toHaveText(['$2.29']);
  });

  test('shows the engine’s refusal of a new state’s rows, the answer drawn before staying until Retry draws the new', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    dashboardBounds,
  }) => {
    const { first, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await expect(dashboard.labels).toHaveText([/^Bikes/, /^Recipes/]);
    await labelled(dashboard);
    await declareRefusals(page);
    await dashboardBounds.set({ timeout_seconds: NONE_LEFT });

    await dashboard.go(dashboardAddress(`t=all&by=psession&m=cost.sum&${chip}`));

    await expect(dashboard.bannerText).toContainText(TIMED_OUT);
    await expect(dashboard.labels).toHaveText([/^Bikes/, /^Recipes/]);
    await expect(dashboard.allValues).toHaveText(['$2.29']);

    await dashboardBounds.set({});
    const answered = rowsAnswered(page);
    await dashboard.retry.click();
    await answered;
    await expect(dashboard.labels).toHaveText(['#2 Tidy the ride notes', '#2 Sort the spices', 'Project chat']);
    await expect(dashboard.banner).toHaveCount(0);
  });

  test('a pane’s refusal leaves the banner as the pane closes, the rows’ refusal standing there with its Retry', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    dashboardBounds,
    deploymentSse,
  }) => {
    const { first, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await deploymentSse.ensureConnected();
    await expect(dashboard.rows).toHaveCount(2);
    await labelled(dashboard);
    await declareRefusals(page);
    await dashboardBounds.set({ timeout_seconds: NONE_LEFT });
    const reads = dashboard.rowsReads();
    expect((await collection.walk()).announced).toBe(true);
    await expect(dashboard.bannerText).toContainText(TIMED_OUT);

    await dashboard.addFilter.click();
    await dashboard.filterGroup('Parts').getByText('Pilot session', { exact: true }).click();
    await expect(dashboard.pane).toContainText('The values did not come.');
    await dashboard.addFilter.click();
    await expect(dashboard.pane).toHaveCount(0);

    await expect(dashboard.bannerText).toContainText(TIMED_OUT);
    await dashboardBounds.set({});
    const answered = rowsAnswered(page);
    await dashboard.retry.click();

    await expect.poll(() => reads()).toHaveLength(2);
    await answered;
    await expect(dashboard.banner).toHaveCount(0);
    await expect(dashboard.allValues).toHaveText(['$2.29']);
  });

  test('Retry asks again every read refused, a value’s lookup beside a new state’s rows, whichever the banner shows', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    dashboardBounds,
  }) => {
    const me = await people.signIn();
    const recipeBox = await projects.make({ name: makeUnique('Recipes'), members: [me.handle!] });
    const bikeLog = await projects.make({ name: makeUnique('Bikes'), members: [me.handle!] });
    const empty = await projects.make({ name: makeUnique('Empty'), members: [me.handle!] });
    await collection.loadScenario('tally', { 'recipe-box': recipeBox, 'bike-log': bikeLog });
    // A project with no Call is named by no lookup, which the tab asks again as its chip comes back.
    const chip = `c=project:${recipeBox},${bikeLog},${empty}`;
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await expect(dashboard.rows).toHaveCount(2);
    await labelled(dashboard);
    const two = rowsAnswered(page);
    await dashboard.go(dashboardAddress(`t=all&by=project&m=cost.sum&c=project:${recipeBox},${bikeLog}`));
    await two;
    await declareRefusals(page);
    await dashboardBounds.set({ timeout_seconds: NONE_LEFT });

    // The chip back, its rows held: the empty project's lookup alone is read, and refused.
    await dashboard.go(dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`));
    await expect(dashboard.bannerText).toContainText(TIMED_OUT);
    await dashboardBounds.set({ timeout_seconds: 2 * NONE_LEFT });
    await dashboard.go(dashboardAddress(`t=all&by=psession&m=cost.sum&${chip}`));
    await expect(dashboard.bannerText).toContainText("its read ran past the engine's timeout of 2e-09 s");
    await expect(dashboard.labels).toHaveText([/^Bikes/, /^Recipes/]);

    await dashboardBounds.set({});
    await dashboard.retry.click();

    await expect(dashboard.labels).toHaveText(['#2 Tidy the ride notes', '#2 Sort the spices', 'Project chat']);
    await expect(dashboard.banner).toHaveCount(0);
  });
});
