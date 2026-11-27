/**
 * The dashboard kept current (F160.6): each part of the screen a query keyed by the state without
 * its look-only parts, a link opened cold read through the server's normal form first, a read a
 * change supersedes cancelled; on the walk's event the view is read again in place, its figures
 * drawn until the new arrive and its scroll left alone, whichever screen is in view, and a hidden
 * page reads nothing until it shows. Each walk here comes after a second load of the tally, on two
 * projects of the spec's own that the view's chip already names, so that the new figures show.
 */

import type { Page, Request } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { TALLY, type Collection } from '../support/collection';
import { makeUnique } from '../support/helpers';
import { waitForSseEvent } from '../support/helpers/test-events';
import { slowNetwork } from '../support/network';
import { dashboardAddress } from '../support/page-objects/dashboard-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';

/** Four projects of the person's under one chip, the tally loaded on the first two: `more()` loads it on the other two, beside it. */
async function fourProjects(people: People, projects: Projects, collection: Collection) {
  const me = await people.signIn();
  const ids: string[] = [];
  for (const name of ['Recipes', 'Bikes', 'Pantry', 'Rides']) ids.push(await projects.make({ name: makeUnique(name), members: [me.handle!] }));
  await collection.loadScenario('tally', { 'recipe-box': ids[0], 'bike-log': ids[1] });
  return {
    first: ids[0],
    chip: `c=project:${ids.join(',')}`,
    more: async () => {
      await collection.loadScenario('tally', { 'recipe-box': ids[2], 'bike-log': ids[3] });
    },
  };
}

const isRows = (request: Request) => new URL(request.url()).pathname === '/api/dashboard/rows';

/** The walk's event heard by the page. */
const walkHeard = (page: Page) => waitForSseEvent(page, { streamId: 'collection_changed', phase: 'message', event: 'collection_changed' });

test.describe('The dashboard kept current', () => {
  test('on the walk’s event reads the view in view again in place: its figures drawn until the new arrive, its scroll left alone', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    deploymentSse,
  }) => {
    await page.setViewportSize({ width: 1280, height: 500 });
    const { first, chip, more } = await fourProjects(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`)}`);
    await deploymentSse.ensureConnected();
    await expect(dashboard.rows).toHaveCount(TALLY.calls);
    await dashboard.main.evaluate((main) => (main.scrollTop = 150));
    const left = await dashboard.scrollTop();
    await more();
    const restore = await slowNetwork(page, 1500);
    const reads = dashboard.rowsReads();
    const read = page.waitForRequest(isRows);

    expect((await collection.walk()).announced).toBe(true);

    await read;
    await expect(dashboard.all).toContainText(`All · ${TALLY.calls}`);
    await expect(dashboard.card).toHaveAttribute('aria-busy', 'false');
    await expect(dashboard.rows).toHaveCount(TALLY.calls * 2);
    await expect(dashboard.all).toContainText(`All · ${TALLY.calls * 2}`);
    await restore();
    expect(reads()).toHaveLength(1);
    expect(await dashboard.scrollTop()).toBe(left);
  });

  test('reads it again while the Projects screen shows, and Dashboard shows the new figures with nothing read again', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    deploymentSse,
  }) => {
    const { first, chip, more } = await fourProjects(people, projects, collection);
    const state = `t=all&by=project&m=cost.sum&${chip}`;
    await shell.open(`${projectAddress(first)}${dashboardAddress(state)}`);
    await deploymentSse.ensureConnected();
    await expect(dashboard.rows).toHaveCount(2);
    await shell.projectsTab.click();
    await expect(dashboard.screen).toBeHidden();
    await more();
    const reads = dashboard.rowsReads();
    const read = page.waitForResponse((response) => isRows(response.request()));

    await collection.walk();

    await read;
    expect(reads()).toHaveLength(1);
    await shell.dashboardTab.click();
    await expect(dashboard.rows).toHaveCount(4);
    expect(reads()).toHaveLength(1);
  });

  test('lets a read under way as a walk ends land, and reads again after it', async ({ page, people, projects, collection, shell, dashboard, deploymentSse }) => {
    const { first, chip, more } = await fourProjects(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await deploymentSse.ensureConnected();
    await expect(dashboard.rows).toHaveCount(2);
    const log: string[] = [];
    page.on('request', (request) => isRows(request) && log.push('sent'));
    page.on('requestfinished', (request) => isRows(request) && log.push('landed'));
    page.on('requestfailed', (request) => isRows(request) && log.push('cancelled'));
    await more();
    const restore = await slowNetwork(page, 3000);
    const underWay = page.waitForRequest(isRows);
    const firstHeard = walkHeard(page);
    await collection.walk();
    await firstHeard;
    await underWay;

    // A second walk while the first's read is under way.
    await more();
    const heard = walkHeard(page);
    expect((await collection.walk()).announced).toBe(true);
    await heard;

    await expect.poll(() => log, { timeout: 15_000 }).toEqual(['sent', 'landed', 'sent', 'landed']);
    await restore();
    await expect(dashboard.rows).toHaveCount(4);
  });

  test('reads nothing while the browser page is hidden, and reads the view again as it shows', async ({ page, people, projects, collection, shell, dashboard, device, deploymentSse }) => {
    const { first, chip, more } = await fourProjects(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await deploymentSse.ensureConnected();
    await expect(dashboard.rows).toHaveCount(2);
    await more();
    await device.hide();
    const reads = dashboard.rowsReads();
    const heard = walkHeard(page);

    await collection.walk();

    await heard;
    await page.evaluate(() => undefined);
    expect(reads()).toEqual([]);
    await expect(dashboard.rows).toHaveCount(2);

    await device.foreground();
    await expect(dashboard.rows).toHaveCount(4);
    expect(reads()).toHaveLength(1);
  });

  test('asks the rows of the state without its look-only parts, so that a change of look asks nothing', async ({ page, people, projects, collection, shell, dashboard }) => {
    const { first, chip } = await fourProjects(people, projects, collection);
    const state = `t=all&by=project&m=cost.sum&${chip}`;
    const reads = dashboard.rowsReads();
    await shell.open(`${projectAddress(first)}${dashboardAddress(`${state}&rel=1`)}`);
    await expect(dashboard.all).toContainText('(absolute)');
    expect(reads()).toHaveLength(1);
    expect(reads()[0]).not.toContain('rel=');

    await dashboard.go(dashboardAddress(state));

    await expect(dashboard.all).not.toContainText('(absolute)');
    await page.evaluate(() => undefined);
    expect(reads()).toHaveLength(1);
  });

  test('opened cold at a link reads the link’s state through the server’s normal form first', async ({ people, projects, collection, shell, dashboard }) => {
    const { first, chip } = await fourProjects(people, projects, collection);
    const addressReads = dashboard.addressReads();
    const reads = dashboard.rowsReads();

    // A figure written without its aggregate, which the catalogue gives it.
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=project&m=cost&${chip}`)}`);

    await expect(dashboard.allValues).toHaveText(['$2.29']);
    // Under the dev server's StrictMode a first read is cancelled as its mount is undone, and sent again.
    expect([...new Set(addressReads())]).toEqual([`t=all&by=project&m=cost&${chip}`]);
    expect(reads()).toHaveLength(1);
    expect(reads()[0]).toContain('m=cost.sum');
  });

  test('cancels a read a change of state supersedes, the view drawn from what it had', async ({ page, people, projects, collection, shell, dashboard }) => {
    const { first, chip } = await fourProjects(people, projects, collection);
    const state = `t=all&by=project&m=cost.sum&${chip}`;
    await shell.open(`${projectAddress(first)}${dashboardAddress(state)}`);
    await expect(dashboard.rows).toHaveCount(2);
    const restore = await slowNetwork(page, 2000);
    const superseded = page.waitForRequest((request) => isRows(request) && request.url().includes('by%3Dcall'));

    await dashboard.go(dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`));
    const request = await superseded;
    await expect(dashboard.card).toHaveAttribute('aria-busy', 'true');
    const failed = page.waitForEvent('requestfailed', (one) => one === request);
    const reads = dashboard.rowsReads();
    await dashboard.go(dashboardAddress(state));

    expect((await failed).failure()?.errorText).toContain('ERR_ABORTED');
    await restore();
    await expect(dashboard.card).toHaveAttribute('aria-busy', 'false');
    await expect(dashboard.rows).toHaveCount(2);
    expect(reads()).toEqual([]);
  });
});
