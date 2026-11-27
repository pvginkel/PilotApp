/**
 * The quick filters (F162.6): a line under the chips, each with its count and the cost of what it
 * keeps in the view's scope, a task's answer; a press turns one on, filtering or marking as it was
 * made, with no chip added, a second press off, each a new entry (F160.4); one that is on narrows the
 * others' counts; one that counts nothing and is off takes no press. "Add as quick filter", in a
 * dimension's pane, makes one under a name, for everyone, its amount the cost, no chip joining the
 * scope; its × removes it after a dialog. On the walk's event the counts are read again with the
 * rows (F160.6), and a count whose answer the stream lost, as it dropped or before it first stood,
 * is asked again as it comes up. The figures are the tally's (`backend/tests/dashboard/test_tally.py`),
 * on projects of the spec's own; the quick filters are everyone's in the worker's record, so each is
 * found by its name.
 */

import type { Page, Request } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import type { Collection } from '../support/collection';
import { makeUnique } from '../support/helpers';
import { dashboardAddress, type DashboardPage } from '../support/page-objects/dashboard-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';

/** The words of the quick filters a spec makes, so that the record is left without them. */
const MADE = 'Spec chats';

/** The tally loaded on two projects of the person's, beside two more of theirs under the chip that names all four: `more()` loads it on those two. */
async function tally(people: People, projects: Projects, collection: Collection) {
  const me = await people.signIn();
  const ids: string[] = [];
  for (const name of ['Recipes', 'Bikes', 'Pantry', 'Rides']) ids.push(await projects.make({ name: makeUnique(name), members: [me.handle!] }));
  await collection.loadScenario('tally', { 'recipe-box': ids[0], 'bike-log': ids[1] });
  return {
    first: ids[0],
    chip: `c=project:${[...ids].sort().join(',')}`,
    more: () => collection.loadScenario('tally', { 'recipe-box': ids[2], 'bike-log': ids[3] }),
  };
}

const toast = (page: Page) => page.getByTestId('app-shell.toast.item');

const historyLength = (page: Page) => page.evaluate(() => history.length);

/** The state the address names, its tab's id read off. */
const stateOf = (page: Page) => decodeURIComponent(new URL(page.url()).hash.replace(/^#dash\/[^/=]+\//, ''));

const isMade = (request: Request) => request.method() === 'POST' && new URL(request.url()).pathname === '/api/dashboard/quick-filters';

/** The seeded quick filters' counts and amounts by Call over the tally, as `test_tally.py` pins them. */
async function expectSeeded(dashboard: DashboardPage) {
  const expected: [string, string, string | null][] = [
    ['Waits past the cache TTL', '1', '$0.24'],
    ['Cache misses', '2', '$0.49'],
    ['Compactions', '1', null],
    ['Outlier rows', '1', null],
    ['Expensive calls', '1', '$1.05'],
  ];
  for (const [label, count, amount] of expected) {
    const quickFilter = dashboard.quickFilter(label);
    await expect(quickFilter.count).toHaveText(count);
    if (amount === null) await expect(quickFilter.amount).toHaveCount(0);
    else await expect(quickFilter.amount).toHaveText(amount);
  }
}

test.describe('The quick filters', () => {
  test.afterEach(async ({ page, backendUrl }) => {
    const response = await page.request.get(`${backendUrl}/api/dashboard/catalogue?part=stored`);
    const { quick_filters } = (await response.json()) as { quick_filters: { id: string; label: string }[] };
    for (const made of quick_filters.filter((each) => each.label.startsWith(MADE))) {
      await page.request.delete(`${backendUrl}/api/dashboard/quick-filters/${made.id}`);
    }
  });

  test('stand on a line under the chips, each counting what it keeps in scope, with the cost its figure names; by project the outliers count none and take no press', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { first, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`)}`);
    await expect(dashboard.rows).toHaveCount(16);

    await expectSeeded(dashboard);
    const line = dashboard.scope.locator('.dash-line').first();
    expect((await dashboard.quickFilters.boundingBox())!.y).toBeGreaterThanOrEqual((await line.boundingBox())!.y + (await line.boundingBox())!.height);
    await expect(dashboard.quickFilter('Compactions').toggle).toHaveAttribute('title', /^The Calls that follow a compaction of their thread's context\n/);
    await expect(dashboard.quickFilter('Cache misses').toggle).toHaveAttribute('aria-pressed', 'false');

    await dashboard.go(dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`));
    const outliers = dashboard.quickFilter('Outlier rows');
    await expect(outliers.count).toHaveText('0');
    await expect(outliers.toggle).toHaveAttribute('aria-disabled', 'true');
    const entries = await historyLength(page);
    await outliers.toggle.click({ force: true });
    await expect(outliers.toggle).toHaveAttribute('aria-pressed', 'false');
    expect(stateOf(page)).not.toContain('b=');
    expect(await historyLength(page)).toBe(entries);
  });

  test('a press turns one on, filtering as it was made with no chip added, narrowing the others’ counts; a second press turns it off, each a new entry', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { first, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`)}`);
    await expectSeeded(dashboard);
    const entries = await historyLength(page);
    const pastTtl = dashboard.quickFilter('Waits past the cache TTL');

    await pastTtl.toggle.click();

    expect(stateOf(page)).toContain('&b=past_ttl&');
    await expect(pastTtl.toggle).toHaveAttribute('aria-pressed', 'true');
    await expect(pastTtl.item).toHaveClass(/\bon\b/);
    await expect(dashboard.rows).toHaveCount(1);
    await expect(dashboard.allValues).toHaveText(['$0.24']);
    await expect(dashboard.chips).toHaveCount(1);
    await expect(dashboard.quickFilter('Cache misses').count).toHaveText('1');
    await expect(dashboard.quickFilter('Cache misses').amount).toHaveText('$0.24');
    await expect(dashboard.quickFilter('Compactions').count).toHaveText('0');
    await expect(dashboard.quickFilter('Compactions').toggle).toHaveAttribute('aria-disabled', 'true');
    await expect(dashboard.quickFilter('Expensive calls').amount).toHaveText('$0.00');
    await expect(pastTtl.toggle).not.toHaveAttribute('aria-disabled');
    expect(await historyLength(page)).toBe(entries + 1);

    await pastTtl.toggle.click();

    expect(stateOf(page)).not.toContain('b=');
    await expect(pastTtl.toggle).toHaveAttribute('aria-pressed', 'false');
    await expect(dashboard.rows).toHaveCount(16);
    await expectSeeded(dashboard);
    expect(await historyLength(page)).toBe(entries + 2);
  });

  test('“Add as quick filter” in a dimension’s pane makes one of its chip under a name, for everyone, its amount the cost, with no chip added; it marks as it was made, and its × removes it after a dialog', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { first, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`)}`);
    await expectSeeded(dashboard);
    const before = stateOf(page);
    const entries = await historyLength(page);

    await dashboard.addFilter.click();
    await dashboard.filterGroup('Attributes').getByText('Source', { exact: true }).click();
    await dashboard.paneValue("Pilot's chats").getByRole('checkbox').check();
    await dashboard.paneMark.click();
    await dashboard.paneQuickFilter.click();

    await expect(dashboard.quickFilterName).toHaveValue("Source: Pilot's chats");
    await expect(dashboard.quickFilterName).toBeFocused();
    await dashboard.quickFilterName.press('Escape');
    await expect(dashboard.quickFilterName).toHaveCount(0);
    await expect(dashboard.paneApply).toBeVisible();

    await dashboard.paneQuickFilter.click();
    const name = makeUnique(MADE);
    await dashboard.quickFilterName.fill(name);
    const made = page.waitForRequest(isMade);
    await dashboard.quickFilterSave.click();

    expect((await made).postDataJSON()).toEqual({ label: name, chip: '~source:chat', amount: 'cost' });
    await expect(dashboard.pane).toHaveCount(0);
    await expect(toast(page)).toContainText(`Added the quick filter "${name}" for everyone`);
    const chats = dashboard.quickFilter(name);
    await expect(chats.count).toHaveText('3');
    await expect(chats.amount).toHaveText('$0.25');
    await expect(chats.toggle.getByLabel('Marks')).toHaveCount(1);
    await expect(dashboard.chips).toHaveCount(1);
    expect(stateOf(page)).toBe(before);
    expect(await historyLength(page)).toBe(entries);

    await chats.toggle.click();

    expect(stateOf(page)).toMatch(/&b=[^&]+&/);
    await expect(dashboard.rows).toHaveCount(16);
    await expect(page.locator('[data-testid="dashboard.row"].marked')).toHaveCount(3);

    await chats.item.hover();
    await chats.remove.click();
    await expect(dashboard.quickFilterRemoveDialog.getByTestId('dashboard.quick-filter.remove-dialog.title')).toHaveText(`Remove the quick filter "${name}"?`);
    await dashboard.quickFilterRemoveDialog.getByTestId('dashboard.quick-filter.remove-dialog.confirm').click();

    await expect(dashboard.quickFilterRemoveDialog).toHaveCount(0);
    await expect(toast(page).last()).toContainText(`Removed the quick filter "${name}" for everyone`);
    await expect(chats.item).toHaveCount(0);
    await expect(page.locator('[data-testid="dashboard.row"].marked')).toHaveCount(0);
    await expectSeeded(dashboard);
  });

  test('are everyone’s: one another person made meanwhile shows as the line shows again', async ({ page, backendUrl, people, projects, collection, shell, dashboard }) => {
    const { first, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`)}`);
    await expectSeeded(dashboard);
    await dashboard.newView.click();
    await dashboard.scratch.click();
    await expect(dashboard.lineTabs).toHaveCount(2);
    const name = makeUnique(MADE);
    const response = await page.request.post(`${backendUrl}/api/dashboard/quick-filters`, { data: { label: name, chip: 'source:chat', amount: 'cost' } });
    expect(response.status(), await response.text()).toBe(201);
    const stored = page.waitForResponse((answer) => new URL(answer.url()).searchParams.get('part') === 'stored');

    await dashboard.lineTabs.first().click();

    await stored;
    await expect(dashboard.quickFilter(name).item).toHaveCount(1);
    await expect(dashboard.panel).toHaveCount(0);
  });

  test('on the walk’s event reads the counts again with the rows', async ({ people, projects, collection, shell, dashboard, deploymentSse }) => {
    const { first, chip, more } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`)}`);
    await deploymentSse.ensureConnected();
    await expectSeeded(dashboard);
    const counts = dashboard.countsReads();
    const rows = dashboard.rowsReads();

    await more();
    expect((await collection.walk()).announced).toBe(true);

    await expect(dashboard.quickFilter('Cache misses').count).toHaveText('4');
    await expect(dashboard.quickFilter('Cache misses').amount).toHaveText('$0.99');
    await expect(dashboard.rows).toHaveCount(32);
    expect(counts()).toHaveLength(1);
    expect(rows()).toHaveLength(1);
    expect(counts()[0]).toBe(rows()[0]);
  });

  test('asks a count again as the stream comes back up where its answer came while the stream was down', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    deploymentSse,
    outage,
  }) => {
    const { first, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`)}`);
    await deploymentSse.ensureConnected();
    await expectSeeded(dashboard);
    await outage.drop();
    const counts = dashboard.countsReads();
    const started = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/dashboard/counts/quick-filters');

    await dashboard.quickFilter('Waits past the cache TTL').toggle.click();
    await started;
    await expect(dashboard.rows).toHaveCount(1);
    await expect(dashboard.quickFilters).toHaveAttribute('aria-busy', 'true');

    await outage.end();

    await expect(dashboard.quickFilter('Cache misses').count).toHaveText('1');
    await expect(dashboard.quickFilters).toHaveAttribute('aria-busy', 'false');
    expect(counts()).toHaveLength(2);
    expect(counts()[1]).toBe(counts()[0]);
  });

  test('reads the counts as the stream first stands where the dashboard opened with none, their answer then lost', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    deploymentSse,
    outage,
  }) => {
    const { first, chip } = await tally(people, projects, collection);
    await outage.refuse();
    const started = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/dashboard/counts/quick-filters');

    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`)}`);
    await expect(dashboard.rows).toHaveCount(16);
    await started;
    await expect(dashboard.quickFilter('Cache misses').count).toHaveText('–');

    await outage.end();
    await deploymentSse.ensureConnected();

    await expectSeeded(dashboard);
  });
});
