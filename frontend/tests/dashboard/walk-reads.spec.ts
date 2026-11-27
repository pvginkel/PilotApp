/**
 * What one walk makes the page read again (F160.6), counted over every route of the dashboard's: the
 * tab in view's rows and its quick filters' counts, once each, and nothing else, no tab out of sight,
 * no By's counts, no label and no normal form; an open filter's pane its values beside them; nothing
 * while the browser page is hidden, the same two as it shows; the walk's reads a change of state
 * supersedes cancelled. A write through a generated mutation hook reads none of the engine's. The
 * timing report prices each read (`backend/tools/timing/report.md`, "One walk"). The figures are the
 * tally's, on projects of the spec's own.
 */

import type { Page, Request } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { TALLY, type Collection } from '../support/collection';
import { makeUnique } from '../support/helpers';
import { waitForSseEvent } from '../support/helpers/test-events';
import { PageFetches, slowNetwork } from '../support/network';
import { dashboardAddress } from '../support/page-objects/dashboard-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';

/** The tally loaded on two projects of the person's, beside two more of theirs under the chip that names all four: `more()` loads it on those two. */
async function tally(people: People, projects: Projects, collection: Collection) {
  const me = await people.signIn();
  const ids: string[] = [];
  for (const name of ['Recipes', 'Bikes', 'Pantry', 'Rides']) ids.push(await projects.make({ name: makeUnique(name), members: [me.handle!] }));
  await collection.loadScenario('tally', { 'recipe-box': ids[0], 'bike-log': ids[1] });
  const pause = makeUnique('Pause');
  return {
    first: ids[0],
    chip: `c=project:${[...ids].sort().join(',')}`,
    more: () => collection.loadScenario('tally', { 'recipe-box': ids[2], 'bike-log': ids[3] }),
    pause: { name: pause, id: await projects.make({ name: pause, members: [me.handle!], tasks: [{ id: 'a', title: 'Step a', status: 'pending' }] }) },
  };
}

const ROWS = '/api/dashboard/rows';

const COUNTS = '/api/dashboard/counts/quick-filters';

/** The routes the engine answers: the rows, the two counts' tasks and a dimension's values, a label's lookup among them. */
const ENGINE = [ROWS, COUNTS, '/api/dashboard/counts/attributes', '/api/dashboard/values'];

/** A read's path, as `dashboard.dashboardReads()` records it. */
const pathOf = (read: string) => read.split(' ')[0];

/** A read's state, as `dashboard.dashboardReads()` records it. */
const stateIn = (read: string) => read.split(' ')[1];

const isEngine = (read: string) => ENGINE.includes(pathOf(read));

const isAt = (path: string) => (request: Request) => new URL(request.url()).pathname === path;

/** The walk's event heard by the page. */
const walkHeard = (page: Page) => waitForSseEvent(page, { streamId: 'collection_changed', phase: 'message', event: 'collection_changed' });

test.describe('One walk', () => {
  test('reads the tab in view’s rows and its quick filters’ counts again, once each, and nothing else; a write reads none of the engine’s; an open pane’s values are read with them', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    projectList,
    deploymentSse,
  }) => {
    const { first, chip, more, pause } = await tally(people, projects, collection);
    const fetches = new PageFetches(page);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`)}`);
    await deploymentSse.ensureConnected();
    await expect(dashboard.quickFilter('Cache misses').count).toHaveText('2');
    // A second view, out of sight once the first shows again; By's counts counted in the first's scope.
    await dashboard.newView.click();
    await dashboard.scratch.click();
    await expect(dashboard.lineTabs).toHaveCount(2);
    await dashboard.lineTabs.first().click();
    await expect(dashboard.rows).toHaveCount(TALLY.calls);
    await dashboard.by.click();
    await expect(dashboard.entry('by', 'Call').count).toHaveText(String(TALLY.calls));
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('dashboard.by.pop')).toHaveCount(0);
    await fetches.landed();
    const reads = dashboard.dashboardReads();
    await more();
    const heard = walkHeard(page);

    expect((await collection.walk()).announced).toBe(true);

    await heard;
    await expect(dashboard.rows).toHaveCount(TALLY.calls * 2);
    await expect(dashboard.quickFilter('Cache misses').count).toHaveText('4');
    await fetches.landed();
    const [counts, rows] = [...reads()].sort();
    expect(reads().map(pathOf).sort()).toEqual([COUNTS, ROWS]);
    expect(stateIn(counts)).toBe(stateIn(rows));
    expect(stateIn(rows)).toContain('by=call');

    // A write through a generated mutation hook, the pause, with the Projects screen in view.
    await shell.projectsTab.click();
    await expect(dashboard.screen).toBeHidden();
    const written = dashboard.dashboardReads();
    const paused = projectList.written(pause.id, 'paused');
    await projectList.statusIcon(pause.name).root.click();
    await paused;
    await fetches.landed();
    expect(written().filter(isEngine)).toEqual([]);

    // A walk with a filter's pane open.
    await shell.dashboardTab.click();
    await dashboard.chipWords(dashboard.chips.first()).click();
    await expect(dashboard.paneValues.first()).toBeVisible();
    await fetches.landed();
    const withPane = dashboard.dashboardReads();
    await more();
    const heardAgain = walkHeard(page);

    expect((await collection.walk()).announced).toBe(true);

    await heardAgain;
    await fetches.landed();
    expect(withPane().map(pathOf).sort()).toEqual([COUNTS, ROWS, '/api/dashboard/values']);
    expect(withPane().find((read) => pathOf(read) === '/api/dashboard/values')).toMatch(/ project$/);
  });

  test('reads nothing while the browser page is hidden, and as it shows the rows and the counts, once each', async ({ page, people, projects, collection, shell, dashboard, device, deploymentSse }) => {
    const { first, chip, more } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`)}`);
    await deploymentSse.ensureConnected();
    await expect(dashboard.quickFilter('Cache misses').count).toHaveText('2');
    await device.hide();
    const reads = dashboard.dashboardReads();
    await more();
    const heard = walkHeard(page);

    expect((await collection.walk()).announced).toBe(true);

    await heard;
    await page.evaluate(() => undefined);
    expect(reads()).toEqual([]);
    await device.foreground();
    await expect(dashboard.rows).toHaveCount(TALLY.calls * 2);
    await expect(dashboard.quickFilter('Cache misses').count).toHaveText('4');
    expect(reads().map(pathOf).sort()).toEqual([COUNTS, ROWS]);
  });

  test('’s reads a change of state supersedes are cancelled, the rows’ and the counts’, and the new state’s read', async ({ page, people, projects, collection, shell, dashboard, deploymentSse }) => {
    const { first, chip, more } = await tally(people, projects, collection);
    const state = `t=all&by=call&m=cost.sum&${chip}`;
    const other = `t=all&by=project&m=cost.sum&${chip}`;
    const fetches = new PageFetches(page);
    await shell.open(`${projectAddress(first)}${dashboardAddress(state)}`);
    await deploymentSse.ensureConnected();
    await expect(dashboard.rows).toHaveCount(TALLY.calls);
    // The other state read once, so that a move to it waits on no normal form.
    await dashboard.go(dashboardAddress(other));
    await expect(dashboard.rows).toHaveCount(2);
    await dashboard.go(dashboardAddress(state));
    await expect(dashboard.rows).toHaveCount(TALLY.calls);
    await expect(dashboard.quickFilter('Cache misses').count).toHaveText('2');
    await fetches.landed();
    const cancelled: string[] = [];
    page.on('requestfailed', (request) => {
      if (ENGINE.includes(new URL(request.url()).pathname)) cancelled.push(`${new URL(request.url()).pathname} ${request.failure()?.errorText}`);
    });
    const reads = dashboard.dashboardReads();
    await more();
    const restore = await slowNetwork(page, 2000);
    const underWay = Promise.all([page.waitForRequest(isAt(ROWS)), page.waitForRequest(isAt(COUNTS))]);
    expect((await collection.walk()).announced).toBe(true);
    await underWay;

    await dashboard.go(dashboardAddress(other));

    await expect.poll(() => [...cancelled].sort()).toEqual([`${COUNTS} net::ERR_ABORTED`, `${ROWS} net::ERR_ABORTED`]);
    await restore();
    await expect(dashboard.rows).toHaveCount(4);
    await fetches.landed();
    const asked = reads();
    expect(asked.map(pathOf).sort()).toEqual([COUNTS, COUNTS, ROWS, ROWS]);
    expect(asked.filter((read) => stateIn(read).includes('by=call'))).toHaveLength(2);
    expect(asked.filter((read) => stateIn(read).includes('by=project'))).toHaveLength(2);
  });
});
