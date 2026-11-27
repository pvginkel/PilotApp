/**
 * The measures, the view's columns, with no chip (F163.4, F163.5, F161.6): a heading, a column's in
 * the rows and in a table, is the measure's name, built on the page, which sorts by its column,
 * largest first and then the other way, with the arrow of the sort and at its right, under the
 * pointer, the menu's sign and a ×, the last measure having none; its panel holds the aggregate and
 * the grain, staying open over a change; a heading dragged moves its column, a line marking the
 * drop, Esc putting it back, the walk's event leaving a drag under way alone; + Measure leads the
 * head's right group, the catalogue's measures in their groups; where the By refuses a measure the
 * card says which. A sort and a change of the measures replace the entry (F160.4). Within a tab a
 * By's sort is kept through a drill down and up and a By picked, the link's the first it remembers,
 * one on a measure hidden forgotten, a sort following its column through a change of aggregate or
 * grain; the tab keeps them in the browser (F161.1). The figures are the tally's (`TALLY`), on two
 * projects of the spec's own.
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { TALLY, type Collection } from '../support/collection';
import { makeUnique } from '../support/helpers';
import { dashboardAddress, type DashboardPage } from '../support/page-objects/dashboard-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';

/**
 * The tally loaded on two projects of the person's, and the chip that keeps them; `beside()` makes two
 * more of theirs, empty, and answers the chip that keeps all four and the tally's load on the two.
 */
async function tally(people: People, projects: Projects, collection: Collection) {
  const me = await people.signIn();
  const recipes = makeUnique('Recipes');
  const bikes = makeUnique('Bikes');
  const recipeBox = await projects.make({ name: recipes, members: [me.handle!] });
  const bikeLog = await projects.make({ name: bikes, members: [me.handle!] });
  await collection.loadScenario('tally', { 'recipe-box': recipeBox, 'bike-log': bikeLog });
  return {
    recipeBox,
    recipes,
    bikes,
    chip: `c=project:${[recipeBox, bikeLog].sort().join(',')}`,
    beside: async () => {
      const others = [await projects.make({ name: makeUnique('Pantry'), members: [me.handle!] }), await projects.make({ name: makeUnique('Rides'), members: [me.handle!] })];
      return {
        chip: `c=project:${[recipeBox, bikeLog, ...others].sort().join(',')}`,
        load: () => collection.loadScenario('tally', { 'recipe-box': others[0], 'bike-log': others[1] }),
      };
    },
  };
}

const historyLength = (page: Page) => page.evaluate(() => history.length);

/**
 * By's list once every entry it draws has its count: until then an entry of one value or none moves
 * behind "n hidden" as its count arrives, and the entries under it move up.
 */
const counted = (dashboard: DashboardPage, page: Page) =>
  expect(dashboard.listGroups('by').getByTestId('dashboard.by.entry').filter({ hasNot: page.getByTestId('dashboard.by.entry.count') })).toHaveCount(0);

/** The state the address names, its tab's id read off. */
const stateOf = (page: Page) => decodeURIComponent(new URL(page.url()).hash.replace(/^#dash\/[^/=]+\//, ''));

/** The middle of what `locator` holds, in the page. */
async function middle(locator: Locator): Promise<{ x: number; y: number }> {
  const box = (await locator.boundingBox())!;
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

/** A press on `heading`'s name lifted past 4 px and dragged over the middle of `over`'s left edge, the button held. */
async function dragOver(page: Page, heading: Locator, over: Locator): Promise<void> {
  const from = await middle(heading);
  const to = (await over.boundingBox())!;
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + 12, from.y + 6, { steps: 3 });
  await page.mouse.move(to.x + 2, to.y + to.height / 2, { steps: 5 });
}

test.describe('A measure’s heading', () => {
  test('is the measure’s name, built on the page, and sorts by its column, the largest first, then the other way, the entry in place', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=cost.median.conversation&m=calls.count&${chip}&col=none`)}`);

    // The rows' answer labels the first two alike, "Cost".
    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Cost per conversation (median)', 'Calls']);
    await expect(dashboard.measure('Cost').arrow).toHaveText('▼');
    await expect(dashboard.labels.first()).toHaveText(/^Bikes/);
    const entries = await historyLength(page);

    await dashboard.measure('Calls').sort.click();

    await expect(dashboard.labels.first()).toHaveText(/^Recipes/);
    await expect(dashboard.measure('Calls').arrow).toHaveText('▼');
    await expect(dashboard.measure('Cost').arrow).toHaveCount(0);
    expect(stateOf(page)).toContain('o=desc,calls.count');

    await dashboard.measure('Calls').sort.click();

    await expect(dashboard.labels.first()).toHaveText(/^Bikes/);
    await expect(dashboard.measure('Calls').arrow).toHaveText('▲');
    expect(stateOf(page)).toContain('o=asc,calls.count');
    expect(await historyLength(page)).toBe(entries);
  });

  test('has the menu’s sign and a × under the pointer, the × removing its measure and the sort on it, the last measure having none', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=calls.count&${chip}&col=none&o=asc,calls.count`)}`);
    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Calls']);
    const entries = await historyLength(page);
    const calls = dashboard.measure('Calls');
    await expect(calls.menu).toBeHidden();
    await expect(calls.remove).toBeHidden();

    await calls.head.hover();

    await expect(calls.menu).toBeVisible();
    await expect(calls.remove).toBeVisible();
    await calls.remove.click();

    await expect(dashboard.measureHeadings).toHaveText(['Cost']);
    expect(stateOf(page)).not.toContain('o=');
    expect(await historyLength(page)).toBe(entries);
    await dashboard.measure('Cost').head.hover();
    await expect(dashboard.measure('Cost').menu).toBeVisible();
    await expect(dashboard.measure('Cost').remove).toHaveCount(0);
  });

  test('’s panel holds the aggregate and the grain, stays open over a change, the sort following its column, and closes by Esc', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=calls.count&${chip}&col=none&o=asc,cost.sum`)}`);
    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Calls']);
    const entries = await historyLength(page);

    await dashboard.measure('Calls').head.hover();
    await dashboard.measure('Calls').menu.click();
    await expect(dashboard.paneChoices('Aggregate')).toHaveText(['Sum', 'Median', 'Mean', 'Max', 'P90', 'Count']);
    await dashboard.measurePaneClose.click();
    await expect(dashboard.measurePane).toHaveCount(0);

    await dashboard.measure('Cost').head.hover();
    await dashboard.measure('Cost').menu.click();
    await expect(dashboard.measurePaneName).toHaveText('Cost');
    await expect(dashboard.paneChoices('Aggregate')).toHaveText(['Sum', 'Median', 'Mean', 'Max', 'P90']);
    await expect(dashboard.paneChoice('aggregate', 'sum')).toHaveAttribute('aria-pressed', 'true');
    await expect(dashboard.paneChoices('Grain').first()).toHaveText('Call');
    await expect(dashboard.paneChoice('grain', 'call')).toHaveAttribute('aria-pressed', 'true');

    await dashboard.paneChoice('aggregate', 'median').click();

    await expect(dashboard.measureHeadings).toHaveText(['Cost (median)', 'Calls']);
    await expect(dashboard.measurePaneName).toHaveText('Cost (median)');
    await expect(dashboard.paneChoice('aggregate', 'median')).toHaveAttribute('aria-pressed', 'true');
    expect(stateOf(page)).toContain('m=cost.median&m=calls.count');
    expect(stateOf(page)).toContain('o=asc,cost.median');

    await dashboard.paneChoice('grain', 'conversation').click();

    await expect(dashboard.measureHeadings).toHaveText(['Cost per conversation (median)', 'Calls']);
    await expect(dashboard.measurePane).toBeVisible();
    expect(stateOf(page)).toContain('o=asc,cost.median.conversation');
    expect(await historyLength(page)).toBe(entries);

    await page.keyboard.press('Escape');
    await expect(dashboard.measurePane).toHaveCount(0);
  });

  test('is dragged to move its column, a line marking the drop and the rows keeping their sort; Esc puts it back; the walk’s event leaves a drag under way alone', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    deploymentSse,
  }) => {
    const { recipeBox, beside } = await tally(people, projects, collection);
    const others = await beside();
    // The chip keeps two projects the walk's load fills, so that its re-read answers rows the page has not drawn.
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=calls.count&m=turns.count&${others.chip}&col=none`)}`);
    await deploymentSse.ensureConnected();
    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Calls', 'Pilot turns']);
    await expect(dashboard.rows).toHaveCount(2);
    await expect(dashboard.labels.first()).toHaveText(/^Bikes/);
    const entries = await historyLength(page);

    await dragOver(page, dashboard.measure('Pilot turns').sort, dashboard.measure('Cost').head);
    await expect(dashboard.dragGhost).toHaveText('Pilot turns');
    await expect(dashboard.dropMark).toBeVisible();
    await expect(dashboard.measure('Pilot turns').head).toHaveClass(/\bdragging\b/);
    await others.load();
    expect((await collection.walk()).announced).toBe(true);
    await expect(dashboard.rows).toHaveCount(4);
    await expect(dashboard.dragGhost).toHaveText('Pilot turns');
    await expect(dashboard.dropMark).toBeVisible();
    await expect(dashboard.measure('Pilot turns').head).toHaveClass(/\bdragging\b/);
    await page.mouse.up();

    await expect(dashboard.measureHeadings).toHaveText(['Pilot turns', 'Cost', 'Calls']);
    await expect(dashboard.dragGhost).toHaveCount(0);
    // The rows sorted by Cost by default keep that sort, pinned to it: the two bike logs, the most Cost, first.
    expect(stateOf(page)).toContain('m=turns.count&m=cost.sum&m=calls.count');
    expect(stateOf(page)).toContain('o=desc,cost.sum');
    await expect(dashboard.labels.nth(0)).toHaveText(/^(Bikes|Rides)/);
    await expect(dashboard.labels.nth(1)).toHaveText(/^(Bikes|Rides)/);
    expect(await historyLength(page)).toBe(entries);

    const before = stateOf(page);
    await dragOver(page, dashboard.measure('Calls').sort, dashboard.measure('Pilot turns').head);
    await expect(dashboard.dropMark).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(dashboard.dragGhost).toHaveCount(0);
    await expect(dashboard.dropMark).toHaveCount(0);
    await page.mouse.up();

    await expect(dashboard.measureHeadings).toHaveText(['Pilot turns', 'Cost', 'Calls']);
    expect(stateOf(page)).toBe(before);
  });

  test('stays in sight while the rows scroll', async ({ page, people, shell, dashboard }) => {
    await page.setViewportSize({ width: 1280, height: 560 });
    await people.signIn();
    // The seed's history holds thousands of Calls.
    await shell.open(`/${dashboardAddress('t=all&by=call&m=cost.sum&m=calls.count')}`);
    await expect(dashboard.rows).toHaveCount(40);

    await dashboard.main.evaluate((main) => (main.scrollTop = 600));

    const top = await dashboard.main.evaluate((main) => main.getBoundingClientRect().top);
    await expect.poll(async () => Math.round((await dashboard.measure('Cost').head.boundingBox())!.y - top)).toBeLessThan(24);
    await expect(dashboard.measure('Cost').head).toBeInViewport();
  });
});

test.describe('In a table, a measure’s heading', () => {
  test('sorts, removes and moves its column and opens its panel, which the table’s scroll does not cut', async ({ page, people, projects, collection, shell, dashboard }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&p=table&m=cost.sum&m=calls.count&m=turns.count&${chip}&col=none`)}`);
    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Calls', 'Pilot turns']);
    await expect(dashboard.tableLabels.first()).toHaveText(/^Bikes/);
    await expect(dashboard.measure('Calls').remove).toBeHidden();

    await dashboard.measure('Calls').sort.click();

    await expect(dashboard.tableLabels.first()).toHaveText(/^Recipes/);
    expect(stateOf(page)).toContain('o=desc,calls.count');

    await dashboard.measure('Calls').head.hover();
    await dashboard.measure('Calls').menu.click();
    await expect(dashboard.measurePane).toBeInViewport({ ratio: 1 });
    const pane = (await dashboard.measurePane.boundingBox())!;
    const wrap = (await dashboard.table.boundingBox())!;
    expect(pane.y + pane.height).toBeGreaterThan(wrap.y + 60);
    await page.keyboard.press('Escape');

    await dragOver(page, dashboard.measure('Pilot turns').sort, dashboard.measure('Cost').head);
    await expect(dashboard.dropMark).toBeVisible();
    await page.mouse.up();
    await expect(dashboard.measureHeadings).toHaveText(['Pilot turns', 'Cost', 'Calls']);
    await expect(dashboard.cells(dashboard.tableAll).first()).toHaveText(String(TALLY.turns));
    await expect(dashboard.cells(dashboard.tableAll).nth(2)).toHaveText('$2.29');

    await dashboard.measure('Pilot turns').head.hover();
    await dashboard.measure('Pilot turns').remove.click();
    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Calls']);
  });
});

test.describe('+ Measure', () => {
  test('leads the head’s right group, the catalogue’s measures in their groups, the ratios last; one picked joins the columns at their end, the entry in place', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}&col=none`)}`);
    await expect(dashboard.measureHeadings).toHaveText(['Cost']);
    await expect(dashboard.cardHead.locator('.dash-cardbar-part.end').getByRole('button').first()).toHaveText('Measure');
    const entries = await historyLength(page);

    await dashboard.addMeasure.click();

    await expect(dashboard.addMeasureGroups.locator('.menu-head')).toHaveText(['Calls', 'Pilot turns', 'Events', 'Work units', 'Ratios']);
    // The built-in ratios first, then the stored ones, which other specs may have made.
    const ratios = await dashboard.addMeasureGroups.last().getByTestId('dashboard.add-measure.entry.pick').allTextContents();
    expect(ratios.slice(0, 4)).toEqual(['Overhead ratio', 'Miss-cost share', 'Rework share', 'Cost per call']);
    await expect(dashboard.addMeasureEntry('Cost')).toHaveAttribute('aria-current', 'true');
    await dashboard.addMeasureEntry('Tokens').click();

    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Tokens']);
    expect(stateOf(page)).toContain('m=cost.sum&m=tokens.sum');

    await dashboard.addMeasure.click();
    await dashboard.addMeasureEntry('Cost per call').click();

    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Tokens', 'Cost per call']);
    expect(await historyLength(page)).toBe(entries);
  });
});

test.describe('A By that refuses a measure', () => {
  test('is named over the chart with the measure it refuses and why', async ({ people, projects, collection, shell, dashboard }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=call&m=cost.sum&m=turns.count&${chip}&col=none`)}`);
    await expect(dashboard.rows).toHaveCount(TALLY.calls);

    await expect(dashboard.refused).toHaveText('Call refuses Pilot turns: turns is a figure of Pilot turns, which have no call.');
    await expect(dashboard.measure('Pilot turns').head).toHaveClass(/\brefused\b/);
    await expect(dashboard.values(dashboard.rows.first()).last()).toHaveText('–');
  });

});

test.describe('A By’s sort within a tab', () => {
  test('is kept through a drill down and up and a By picked, the link’s the first it remembers, in the browser too; Reset forgets the others', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, recipes, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=calls.count&${chip}&col=none&o=asc,calls.count`)}`);
    await expect(dashboard.labels.first()).toHaveText(/^Bikes/);

    await dashboard.row(recipes).click();
    await expect(dashboard.labels).toHaveText(['#2 Sort the spices', 'Project chat']);
    expect(stateOf(page)).not.toContain('o=');
    await dashboard.measure('Cost').sort.click();
    await expect(dashboard.labels).toHaveText(['Project chat', '#2 Sort the spices']);
    expect(stateOf(page)).toContain('o=asc,cost.sum');

    await dashboard.pathSegments.first().click();

    await expect(dashboard.labels.first()).toHaveText(/^Bikes/);
    expect(stateOf(page)).toContain('by=project&');
    expect(stateOf(page)).toContain('o=asc,calls.count');

    await dashboard.by.click();
    await counted(dashboard, page);
    await dashboard.entry('by', 'Pilot turn').pick.click();
    await expect(dashboard.byWords).toHaveText('Pilot turn');
    expect(stateOf(page)).not.toContain('o=');
    await dashboard.by.click();
    await counted(dashboard, page);
    await dashboard.entry('by', 'Project').pick.click();
    await expect(dashboard.byWords).toHaveText('Project');
    expect(stateOf(page)).toContain('o=asc,calls.count');
    expect(await dashboard.keptSorts()).toEqual({ psession: { direction: 'asc', column: 'cost.sum' } });

    // A new build's reload: the tab's sorts come back from the browser.
    await page.reload();
    await dashboard.row(recipes).click();
    await expect(dashboard.labels).toHaveText(['Project chat', '#2 Sort the spices']);
    expect(stateOf(page)).toContain('o=asc,cost.sum');

    await dashboard.reset.click();
    await expect(dashboard.labels.first()).toHaveText(/^Bikes/);
    expect(stateOf(page)).toContain('o=asc,calls.count');
    await dashboard.row(recipes).click();
    await expect(dashboard.labels).toHaveText(['#2 Sort the spices', 'Project chat']);
    expect(stateOf(page)).not.toContain('o=');
  });

  test('forgets a sort on a measure hidden, the link’s among them', async ({ page, people, projects, collection, shell, dashboard }) => {
    const { recipeBox, recipes, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=calls.count&${chip}&col=none&o=asc,calls.count`)}`);
    await expect(dashboard.labels.first()).toHaveText(/^Bikes/);

    await dashboard.row(recipes).click();
    await expect(dashboard.labels).toHaveText(['#2 Sort the spices', 'Project chat']);
    await dashboard.measure('Calls').head.hover();
    await dashboard.measure('Calls').remove.click();
    await expect(dashboard.measureHeadings).toHaveText(['Cost']);
    await dashboard.addMeasure.click();
    await dashboard.addMeasureEntry('Calls').click();
    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Calls']);

    await dashboard.pathSegments.first().click();

    await expect(dashboard.labels.first()).toHaveText(/^Bikes/);
    expect(stateOf(page)).toContain('by=project&');
    expect(stateOf(page)).not.toContain('o=');
  });
});
