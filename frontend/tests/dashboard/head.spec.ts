/**
 * The view's card's head (F163.1 to F163.3, F163.7): By, the presentation; at the right Color,
 * Relative and the table's Copy and CSV; no Options, Items or Discuss, which later slices bring.
 * By's list holds the parts and the attributes, each its count of values in scope, asked as the list
 * opens, a task's progress updates bringing each fact's (F154.6), once for a scope, a walk asking
 * nothing while it is open; those with one value or none behind "n hidden", unfolded muted; a search;
 * a star, the person's favorite rising to Favorites. Color's list is By's with None and Token kind
 * under a rule. A By, a presentation or a color picked is a new entry, Relative the entry in place
 * (F160.4). The table draws the By's rows under the All row, each measure's figure and n, the share
 * and the color's split, scrolling both ways inside the card, its headings in sight, Relative greyed;
 * Copy and CSV take every row. The figures are the tally's (`TALLY`), on two projects of the spec's
 * own.
 */

import { readFile } from 'node:fs/promises';
import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { allowClipboard, copied } from '../support/clipboard';
import { TALLY, type Collection } from '../support/collection';
import { makeUnique } from '../support/helpers';
import { extractSseData, waitForSseEvent } from '../support/helpers/test-events';
import { dashboardAddress, type DashboardPage } from '../support/page-objects/dashboard-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';

/** The tally loaded on two projects of the person's, and the chip that keeps them; `more()` loads it on two more of theirs, outside the chip. */
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
    more: async () => {
      const others = [await projects.make({ name: makeUnique('Pantry'), members: [me.handle!] }), await projects.make({ name: makeUnique('Rides'), members: [me.handle!] })];
      await collection.loadScenario('tally', { 'recipe-box': others[0], 'bike-log': others[1] });
    },
  };
}

const historyLength = (page: Page) => page.evaluate(() => history.length);

/** The state the address names, its tab's id read off. */
const stateOf = (page: Page) => decodeURIComponent(new URL(page.url()).hash.replace(/^#dash\/[^/=]+\//, ''));

/** The text of every heading of the list `of`'s groups, in its order; a group under a rule has none. */
const headings = (dashboard: DashboardPage, of: 'by' | 'color') => dashboard.listGroups(of).evaluateAll((groups) => groups.map((group) => group.querySelector('.menu-head')?.textContent ?? null));

test.describe('The card’s head', () => {
  test('holds By and the presentation, at the right Color and Relative, and nothing a later slice brings', async ({ people, projects, collection, shell, dashboard }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}&col=psession`)}`);

    await expect(dashboard.byWords).toHaveText('Project');
    await expect(dashboard.rowsPresentation).toHaveAttribute('aria-pressed', 'true');
    await expect(dashboard.tablePresentation).toHaveAttribute('aria-pressed', 'false');
    await expect(dashboard.colorWords).toHaveText('Pilot session');
    await expect(dashboard.relative).toHaveAttribute('aria-pressed', 'false');
    await expect(dashboard.cardHead.getByRole('button')).toHaveText(['ByProject', 'Rows', 'Table', 'ColorPilot session', 'Relative']);
    await expect(dashboard.copy).toHaveCount(0);
    await expect(dashboard.csv).toHaveCount(0);
  });
});

test.describe('By', () => {
  test('lists the parts and the attributes, each its count of values in scope as it comes, those with one value or none behind "n hidden", unfolded muted; a search finds them', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    testEvents,
    dashboardBounds,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await expect(dashboard.rows).toHaveCount(2);
    const asked = dashboard.byCountsAnswered();
    await testEvents.clearEvents();
    // The engine holds By's counts after their first fact: the task stands between that fact's progress update and its end.
    await dashboardBounds.set({ hold: true });

    await dashboard.by.click();

    // Each progress update carries one fact's counts, drawn as it comes, the facts after it counting none yet.
    const update = await waitForSseEvent(page, { streamId: 'task', event: 'progress_update' });
    const counted = extractSseData<{ data: { counts: { dimension: string; count: number }[] } }>(update)!.data.counts;
    expect(counted).toEqual(expect.arrayContaining([{ dimension: 'project', count: 2 }, { dimension: 'call', count: TALLY.calls }]));
    await expect(dashboard.entry('by', 'Project').count).toHaveText('2');
    await expect(dashboard.entry('by', 'Call').count).toHaveText(String(TALLY.calls));
    const uncounted = await dashboard
      .listGroups('by')
      .getByTestId('dashboard.by.entry')
      .filter({ hasNot: page.getByTestId('dashboard.by.entry.count') })
      .evaluateAll((entries) => entries.map((entry) => entry.getAttribute('data-key')));
    expect(uncounted.length).toBeGreaterThan(0);
    expect(uncounted.filter((key) => counted.some(({ dimension }) => dimension === key))).toEqual([]);
    await dashboardBounds.set({});
    await expect(dashboard.entry('by', 'Project').count).toHaveText('2');
    await expect(dashboard.entry('by', 'Pilot session').count).toHaveText('3');
    await expect(dashboard.entry('by', 'Pilot turn').count).toHaveText(String(TALLY.turns));
    await expect(dashboard.entry('by', 'Conversation').count).toHaveText('4');
    await expect(dashboard.entry('by', 'Call').count).toHaveText(String(TALLY.calls));
    await waitForSseEvent(page, { streamId: 'task', event: 'task_completed' });
    expect(asked()).toHaveLength(1);
    expect(await headings(dashboard, 'by')).toEqual(['Parts', 'Attributes']);
    await expect(dashboard.entry('by', 'Project').item).toHaveClass(/\bon\b/);
    await expect(dashboard.listLabels('by')).not.toContainText(['Quota week']);

    // The hidden: none shown, then each muted, its count one or none.
    const hidden = Number((await dashboard.byMore.textContent())!.replace(/ hidden$/, ''));
    expect(hidden).toBeGreaterThan(0);
    const shown = await dashboard.listLabels('by').count();
    await expect(dashboard.listGroups('by').locator('.dash-dimrow.dim')).toHaveCount(0);
    await dashboard.byMore.click();
    await expect(dashboard.byMore).toHaveCount(0);
    const muted = dashboard.listGroups('by').locator('.dash-dimrow.dim');
    await expect(muted).toHaveCount(hidden);
    await expect(dashboard.listLabels('by')).toHaveCount(shown + hidden);
    for (const count of await muted.getByTestId('dashboard.by.entry.count').allTextContents()) expect(Number(count)).toBeLessThanOrEqual(1);

    // A search finds the hidden too, muted.
    const name = (await muted.first().getByTestId('dashboard.by.entry.label').textContent()) ?? '';
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('dashboard.by.pop')).toHaveCount(0);
    await dashboard.by.click();
    await expect(dashboard.byMore).toHaveText(`${hidden} hidden`);
    await dashboard.listSearch('by').fill(name.toUpperCase());
    await expect(dashboard.entry('by', name).item).toHaveClass(/\bdim\b/);
    await expect(dashboard.byMore).toHaveCount(0);
    await dashboard.listSearch('by').fill('no such dimension');
    await expect(dashboard.listLabels('by')).toHaveCount(0);
    await expect(page.getByTestId('dashboard.by.list')).toContainText('No dimension of that name');
    // Esc in the search clears it, then closes the list.
    await page.keyboard.press('Escape');
    await expect(dashboard.listSearch('by')).toHaveValue('');
    await expect(dashboard.byMore).toHaveText(`${hidden} hidden`);
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('dashboard.by.pop')).toHaveCount(0);
    // Opened again in the scope it counted, it asks nothing.
    expect(asked()).toHaveLength(1);
  });

  test('picked sets the view’s By, a new entry, letting go of its sort', async ({ page, people, projects, collection, shell, dashboard }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}&col=none&o=asc,cost.sum`)}`);
    await expect(dashboard.rows).toHaveCount(2);
    const entries = await historyLength(page);

    await dashboard.by.click();
    await dashboard.entry('by', 'Pilot turn').pick.click();

    await expect(dashboard.labels).toHaveText(['Turn 1 · brief', 'Turn 1 · brief', 'Turn 2 · continuation', 'Turn 1 · person', 'Turn 2 · person']);
    await expect(dashboard.byWords).toHaveText('Pilot turn');
    await expect(dashboard.tab).toHaveText('Pilot turn');
    expect(stateOf(page)).toBe(`t=all&by=pturn&m=cost.sum&${chip}&col=none`);
    expect(await historyLength(page)).toBe(entries + 1);
    await expect(page.getByTestId('dashboard.by.pop')).toHaveCount(0);
  });

  test('takes a star on hover: a favorite rises to Favorites in the list’s own order, kept for the person, and a second press puts it back', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await dashboard.by.click();
    const model = dashboard.entry('by', 'Model');
    await expect(model.star).toHaveCSS('opacity', '0');
    await model.item.hover();
    await expect(model.star).toHaveCSS('opacity', '1');

    await model.star.click();
    await dashboard.entry('by', 'Call').item.hover();
    await dashboard.entry('by', 'Call').star.click();

    const favorites = dashboard.listGroups('by').first();
    await expect(favorites.locator('.menu-head')).toHaveText('Favorites');
    await expect(dashboard.listLabels('by', favorites)).toHaveText(['Call', 'Model']);
    await expect(dashboard.entry('by', 'Model').star).toHaveAttribute('aria-pressed', 'true');

    await page.reload();
    await dashboard.by.click();
    await expect(dashboard.listLabels('by', dashboard.listGroups('by').first())).toHaveText(['Call', 'Model']);
    await dashboard.entry('by', 'Call').item.hover();
    await dashboard.entry('by', 'Call').star.click();
    await expect(dashboard.listLabels('by', dashboard.listGroups('by').first())).toHaveText(['Model']);
    await expect(dashboard.listLabels('by', dashboard.listGroups('by').nth(1))).toContainText(['Project', 'Pilot session', 'Pilot turn', 'Conversation', 'Call']);
  });

  test('’s counts are not asked again by a walk while the list is open; its next opening asks them again', async ({ page, people, projects, collection, shell, dashboard }) => {
    const { recipeBox, chip, more } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await expect(dashboard.rows).toHaveCount(2);
    const asked = dashboard.byCountsAnswered();
    const rowsAsked = dashboard.rowsReads();
    await dashboard.by.click();
    await expect(dashboard.entry('by', 'Call').count).toHaveText(String(TALLY.calls));
    expect(asked()).toHaveLength(1);

    await more();
    expect((await collection.walk()).announced).toBe(true);

    await expect.poll(() => rowsAsked().length).toBe(1);
    await expect(dashboard.entry('by', 'Call').count).toHaveText(String(TALLY.calls));
    expect(asked()).toHaveLength(1);

    await page.keyboard.press('Escape');
    await expect(page.getByTestId('dashboard.by.pop')).toHaveCount(0);
    await dashboard.by.click();
    await expect.poll(() => asked().length).toBe(2);
    await expect(dashboard.entry('by', 'Call').count).toHaveText(String(TALLY.calls));
  });
});

test.describe('Color', () => {
  test('lists By’s list with its stars, no counts, None and Token kind under a rule after it; a pick colors the view, a new entry', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}&col=none`)}`);
    await expect(dashboard.colorWords).toHaveText('None');
    await expect(dashboard.legend).toHaveCount(0);
    const entries = await historyLength(page);

    await dashboard.color.click();
    expect(await headings(dashboard, 'color')).toEqual(['Parts', 'Attributes', null]);
    await expect(dashboard.listLabels('color', dashboard.listGroups('color').last())).toHaveText(['None', 'Token kind']);
    await expect(dashboard.listGroups('color').last()).toHaveCSS('border-top-style', 'solid');
    await expect(dashboard.entry('color', 'None').item).toHaveClass(/\bon\b/);
    await expect(dashboard.entry('color', 'None').star).toHaveCount(0);
    await expect(page.getByTestId('dashboard.color.entry.count')).toHaveCount(0);
    await expect(dashboard.entry('color', 'Call').item).toBeVisible();

    await dashboard.entry('color', 'Token kind').item.hover();
    await dashboard.entry('color', 'Token kind').star.click();
    await expect(dashboard.listLabels('color', dashboard.listGroups('color').first())).toHaveText(['Token kind']);
    await dashboard.listSearch('color').fill('session');
    await expect(dashboard.listLabels('color')).toHaveText(['Pilot session', 'Session kind']);
    await dashboard.entry('color', 'Pilot session').pick.click();

    await expect(dashboard.legend.locator('.lbl')).toHaveText('Pilot session, by Cost');
    await expect(dashboard.colorWords).toHaveText('Pilot session');
    expect(stateOf(page)).toBe(`t=all&by=project&m=cost.sum&${chip}&col=psession`);
    expect(await historyLength(page)).toBe(entries + 1);

    await dashboard.color.click();
    await dashboard.entry('color', 'None').pick.click();
    await expect(dashboard.legend).toHaveCount(0);
    expect(await historyLength(page)).toBe(entries + 2);
  });
});

test.describe('Relative', () => {
  test('reads each figure as a multiple of its median, a look, the entry in place, asking nothing; a second press takes it off', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}&col=none`)}`);
    await expect(dashboard.values(dashboard.rows.first())).toHaveText(['$1.18 · 52%']);
    const entries = await historyLength(page);
    const reads = dashboard.rowsReads();

    await dashboard.relative.click();

    await expect(dashboard.relative).toHaveAttribute('aria-pressed', 'true');
    await expect(dashboard.values(dashboard.rows.first())).toHaveText(['1.0×']);
    expect(stateOf(page)).toBe(`t=all&by=project&m=cost.sum&${chip}&col=none&rel=1`);
    await dashboard.relative.click();
    await expect(dashboard.values(dashboard.rows.first())).toHaveText(['$1.18 · 52%']);
    expect(await historyLength(page)).toBe(entries);
    expect(reads()).toEqual([]);
  });
});

test.describe('The table', () => {
  test('is the presentation’s other choice: the By’s rows under the All row, each measure’s figure and its n, the share and the color’s split; Relative greyed', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, recipes, bikes, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=calls.count&${chip}&col=psession`)}`);
    await expect(dashboard.rows).toHaveCount(2);
    const entries = await historyLength(page);

    await dashboard.tablePresentation.click();

    await expect(dashboard.tableRows).toHaveCount(2);
    await expect(dashboard.rows).toHaveCount(0);
    await expect(dashboard.legend).toHaveCount(0);
    await expect(dashboard.tablePresentation).toHaveAttribute('aria-pressed', 'true');
    expect(stateOf(page)).toBe(`t=all&by=project&p=table&m=cost.sum&m=calls.count&${chip}&col=psession`);
    expect(await historyLength(page)).toBe(entries + 1);
    await expect(dashboard.tab.locator('svg.lucide-table')).toHaveCount(1);
    await expect(dashboard.byHeading).toHaveText('Project');
    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Calls']);
    await expect(dashboard.tableHeads).toHaveText(['n', 'n', 'Share', '#2 Tidy the ride notes', '#2 Sort the spices', 'Project chat']);
    await expect(dashboard.tableAll.locator('td').first()).toHaveText('All · 2');
    await expect(dashboard.cells(dashboard.tableAll)).toHaveText(['$2.29', String(TALLY.calls), String(TALLY.calls), String(TALLY.calls), '100%', '$1.18', '$0.86', '$0.25']);
    await expect(dashboard.tableLabels).toHaveText([bikes, recipes]);
    await expect(dashboard.cells(dashboard.tableRows.first()).nth(0)).toHaveText('$1.18');
    await expect(dashboard.cells(dashboard.tableRows.first()).nth(2)).toHaveText('3');
    await expect(dashboard.cells(dashboard.tableRows.first()).nth(4)).toHaveText('52%');
    await expect(dashboard.cells(dashboard.tableRows.last()).nth(2)).toHaveText('13');

    await expect(dashboard.relative).toHaveAttribute('aria-disabled', 'true');
    await dashboard.relative.click({ force: true });
    expect(stateOf(page)).toBe(`t=all&by=project&p=table&m=cost.sum&m=calls.count&${chip}&col=psession`);
    await expect(dashboard.copy).toBeVisible();
    await expect(dashboard.csv).toBeVisible();

    await dashboard.rowsPresentation.click();
    await expect(dashboard.rows).toHaveCount(2);
    await expect(dashboard.table).toHaveCount(0);
    expect(await historyLength(page)).toBe(entries + 2);
  });

  test('by a timed part reads each row’s name and its time under it', async ({ people, projects, collection, shell, dashboard }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=psession&p=table&m=cost.sum&${chip}`)}`);
    await expect(dashboard.tableLabels).toHaveText(['#2 Tidy the ride notes', '#2 Sort the spices', 'Project chat']);
    await expect(dashboard.tableTimes).toHaveCount(3);
    await expect(dashboard.tableTimes.first()).toHaveText(/^\d{1,2} [A-Z][a-z]{2}( \d{4})? \d{2}:\d{2}$/);
  });

  test('scrolls both ways inside the card, its headings in sight, the main area standing still; the tab keeps its scroll', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    await page.setViewportSize({ width: 1000, height: 560 });
    const { recipeBox, chip } = await tally(people, projects, collection);
    const measures = 'm=cost.sum&m=tokens.sum&m=misses.sum&m=ctx.max&m=calls.count&m=cost.median.call&m=r:overhead';
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=call&p=table&${measures}&${chip}&col=psession`)}`);
    await expect(dashboard.tableRows).toHaveCount(TALLY.calls);

    const box = await dashboard.table.evaluate((wrap) => ({ down: wrap.scrollHeight > wrap.clientHeight, sideways: wrap.scrollWidth > wrap.clientWidth }));
    expect(box).toEqual({ down: true, sideways: true });
    expect(await dashboard.main.evaluate((main) => main.scrollHeight - main.clientHeight)).toBe(0);

    await dashboard.table.evaluate((wrap) => {
      wrap.scrollTop = 120;
      wrap.scrollLeft = 60;
    });
    const wrapTop = await dashboard.table.evaluate((wrap) => wrap.getBoundingClientRect().top);
    await expect.poll(() => dashboard.byHeading.evaluate((heading) => Math.round(heading.getBoundingClientRect().top))).toBe(Math.round(wrapTop));
    const left = await dashboard.table.evaluate((wrap) => wrap.scrollTop);
    expect(left).toBe(120);

    // Another tab and back: the table where it was left.
    await dashboard.newView.click();
    await expect(dashboard.panel).toBeVisible();
    await dashboard.lineTab('Call').click();
    await expect(dashboard.tableRows).toHaveCount(TALLY.calls);
    await expect.poll(() => dashboard.table.evaluate((wrap) => wrap.scrollTop)).toBe(left);
  });

  test('’s Copy puts every row on the clipboard tab-separated, the All row first, and CSV downloads them comma-separated', async ({
    page,
    context,
    backendUrl,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    await allowClipboard(context);
    const { recipeBox, chip } = await tally(people, projects, collection);
    const state = `t=all&by=project&p=table&m=cost.sum&m=calls.count&${chip}&col=none`;
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(state)}`);
    await expect(dashboard.tableRows).toHaveCount(2);
    const answer = (await (await page.request.get(`${backendUrl}/api/dashboard/rows`, { params: { state } })).json()) as {
      all: { values: number[]; n: number[] };
      rows: { label: string; values: number[]; n: number[] }[];
    };
    const line = (label: string, { values, n }: { values: number[]; n: number[] }) => [label, values[0], n[0], values[1], n[1], values[0] / TALLY.cost];
    const lines = [['Project', 'Cost', 'n', 'Calls', 'n', 'Share'], line('All', answer.all), ...answer.rows.map((row) => line(row.label, row))];
    expect(answer.all.values).toEqual([TALLY.cost, TALLY.calls]);

    await dashboard.copy.click();
    await expect(dashboard.copy).toHaveAttribute('data-copy-state', 'success');
    expect(await copied(page)).toBe(lines.map((each) => each.join('\t')).join('\n'));

    const download = page.waitForEvent('download');
    await dashboard.csv.click();
    const file = await download;
    expect(file.suggestedFilename()).toBe('dashboard-project.csv');
    expect(await readFile((await file.path())!, 'utf8')).toBe(lines.map((each) => each.join(',')).join('\n'));
  });
});
