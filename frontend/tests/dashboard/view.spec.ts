/**
 * One view drawn (F163.3, F160.11): a dashboard address names a view, which the dashboard draws in
 * its card as Rows, a row per value of the By under the All row, each measure's figure in its
 * format, the color's split and its legend, the peers' median; a view that names a presentation
 * drawn elsewhere opens on its rows; the view's tab at the global toolbar's left, with no Refresh
 * (F160.7). A row of a Pilot session, a Pilot turn, a conversation or a Call reads its name, its
 * time on a second line in the engine's zone, not the browser's; a label is cut to its room; past
 * 40 rows Show all draws the rest. The card keeps its scroll through Projects and back (F160.2).
 * The figures are the tally's (`TALLY`), on two projects of the spec's own.
 */

import { test, expect } from '../support/fixtures';
import { TALLY } from '../support/collection';
import { makeUnique } from '../support/helpers';
import { dashboardAddress } from '../support/page-objects/dashboard-page';
import { projectAddress, type Projects } from '../support/projects';
import type { Collection } from '../support/collection';
import type { People } from '../support/people';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** An instant's day and time of day in Europe/Amsterdam, the engine's zone by default: "7 Nov 09:52". */
function amsterdam(at: string): string {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Amsterdam', hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      .formatToParts(new Date(at))
      .map((part) => [part.type, part.value]),
  );
  const year = Number(parts.year) === new Date().getFullYear() ? '' : ` ${parts.year}`;
  return `${Number(parts.day)} ${MONTHS[Number(parts.month) - 1]}${year} ${parts.hour}:${parts.minute}`;
}

/** The tally loaded on two projects of the person's: their ids, and the chip that keeps them. */
async function tally(people: People, projects: Projects, collection: Collection) {
  const me = await people.signIn();
  const recipeBox = await projects.make({ name: makeUnique('Recipes'), members: [me.handle!] });
  const bikeLog = await projects.make({ name: makeUnique('Bikes'), members: [me.handle!] });
  await collection.loadScenario('tally', { 'recipe-box': recipeBox, 'bike-log': bikeLog });
  return { recipeBox, bikeLog, chip: `c=project:${[recipeBox, bikeLog].sort().join(',')}` };
}

test.describe('A view', () => {
  test('is drawn as rows: the All row and a row per project, each figure in its format, the headings the By, n and each measure; its tab at the toolbar’s left, with no Refresh', async ({
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=calls.count&m=turns.count&${chip}`)}`);

    await expect(dashboard.rows).toHaveCount(2);
    await expect(dashboard.all).toContainText('All · 2');
    await expect(dashboard.allValues).toHaveText(['$2.29', String(TALLY.calls), String(TALLY.turns)]);
    await expect(dashboard.byHeading).toHaveText('Project');
    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Calls', 'Pilot turns']);
    // By cost, the largest first: the job's project, then the work item's and the chat's.
    await expect(dashboard.labels.first()).toHaveText(/^Bikes/);
    await expect(dashboard.values(dashboard.rows.first())).toHaveText(['$1.18', '3', '1']);
    await expect(dashboard.values(dashboard.rows.last())).toHaveText(['$1.11', '13', '4']);
    await expect(dashboard.times).toHaveCount(0);
    await expect(dashboard.medians).toHaveText(['median $1.14', 'median 8', 'median 2.5']);

    await expect(dashboard.tab).toHaveText('Project');
    await expect(dashboard.toolbar.getByRole('button', { name: /refresh/i })).toHaveCount(0);
  });

  test('of one measure gives each row its share of All, and Relative reads each figure as a multiple of the median, asking nothing', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    const state = `t=all&by=project&m=cost.sum&${chip}&col=none`;
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(state)}`);
    await expect(dashboard.values(dashboard.rows.first())).toHaveText(['$1.18 · 52%']);
    await expect(dashboard.values(dashboard.rows.last())).toHaveText(['$1.11 · 48%']);
    const rowsReads = dashboard.rowsReads();

    await dashboard.go(dashboardAddress(`${state}&rel=1`));

    await expect(dashboard.values(dashboard.rows.first())).toHaveText(['1.0×']);
    await expect(dashboard.all).toContainText('All · 2 (absolute)');
    await expect(dashboard.allValues).toHaveText(['$2.29']);
    await expect(dashboard.medians).toHaveText(['1× = $1.14']);
    await page.evaluate(() => undefined);
    expect(rowsReads()).toEqual([]);
  });

  test('by Pilot turn, conversation and Call reads each row’s name and time', async ({ people, projects, collection, shell, dashboard }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);

    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=pturn&m=cost.sum&${chip}`)}`);
    await expect(dashboard.labels).toHaveText(['Turn 1 · brief', 'Turn 1 · brief', 'Turn 2 · continuation', 'Turn 1 · person', 'Turn 2 · person']);
    await expect(dashboard.times).toHaveCount(5);

    await dashboard.go(dashboardAddress(`t=all&by=conversation&m=cost.sum&${chip}`));
    await expect(dashboard.labels).toHaveText(['Main thread', 'Main thread', 'Main thread', 'Explore · Find where the jars are counted']);
    await expect(dashboard.times).toHaveCount(4);

    await dashboard.go(dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`));
    await expect(dashboard.rows).toHaveCount(TALLY.calls);
    await expect(dashboard.labels.first()).toHaveText('Call 1');
    await expect(dashboard.values(dashboard.rows.first())).toHaveText(['$1.05 · 46%']);
    await expect(dashboard.times).toHaveCount(TALLY.calls);
  });

  test('split by its color draws each bar in the color’s values, which the legend names with their amounts and shares', async ({ people, projects, collection, shell, dashboard }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}&col=psession`)}`);

    await expect(dashboard.legend.locator('.lbl')).toHaveText('Pilot session, by Cost');
    await expect(dashboard.legendValues).toHaveText(['#2 Tidy the ride notes$1.18 · 52%', '#2 Sort the spices$0.86 · 38%', 'Project chat$0.25 · 11%']);
    const bars = (label: RegExp) => dashboard.rows.filter({ has: dashboard.labels.getByText(label) }).locator('rect.bseg');
    await expect(bars(/^Bikes/)).toHaveCount(1);
    await expect(bars(/^Recipes/)).toHaveCount(2);
    const fills = await bars(/^Recipes/).evaluateAll((rects) => rects.map((rect) => (rect as SVGRectElement).style.fill));
    expect(fills).toEqual(['var(--series-1)', 'var(--series-2)']);
  });

  test('whose state names a presentation drawn elsewhere opens on its rows, as Pilot’s own Where the week went does', async ({ people, projects, collection, shell, dashboard }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&p=time,qweek&m=cost.sum&m=r:overhead&${chip}&col=source`)}`);

    await expect(dashboard.rows).toHaveCount(2);
    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Overhead ratio']);
    await expect(dashboard.values(dashboard.rows.first()).first()).toHaveText('$1.18');
    await expect(dashboard.legend).toBeVisible();
  });

  test('cuts a label to its room, its whole name in its tooltip', async ({ page, people, projects, collection, shell, dashboard }) => {
    await page.setViewportSize({ width: 1000, height: 800 });
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=conversation&m=cost.sum&m=calls.count&m=cost.median.call&${chip}`)}`);

    const label = dashboard.labels.last();
    await expect(label).toHaveText(/^Explore · Find.*…$/);
    await expect(dashboard.rows.last().getByTestId('dashboard.row.whole')).toHaveText('Explore · Find where the jars are counted');
    // Within the label's column: short of the row's n, which stands at the column's end.
    const right = await label.evaluate((text) => (text as SVGTextElement).getBBox().x + (text as SVGTextElement).getBBox().width);
    const nLeft = await dashboard.rows
      .last()
      .locator('text[text-anchor="end"]')
      .evaluate((text) => (text as SVGTextElement).getBBox().x);
    expect(right).toBeLessThanOrEqual(nLeft - 8);
    await expect(dashboard.labels.first()).toHaveText('Main thread');
    await expect(dashboard.rows.first().getByTestId('dashboard.row.whole')).toHaveCount(0);
  });

  test('of an empty scope keeps its headings and says there is nothing', async ({ people, projects, shell, dashboard }) => {
    const me = await people.signIn();
    const quiet = await projects.make({ name: makeUnique('Quiet'), members: [me.handle!] });
    await shell.open(`${projectAddress(quiet)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=calls.count&c=project:${quiet}`)}`);

    await expect(dashboard.empty).toHaveText('Nothing in this scope');
    await expect(dashboard.measureHeadings).toHaveText(['Cost', 'Calls']);
    await expect(dashboard.rows).toHaveCount(0);
  });

  test('past 40 rows draws the first 40, and Show all the rest', async ({ people, shell, dashboard }) => {
    await people.signIn();
    // The seed's history holds thousands of Calls.
    await shell.open(`/${dashboardAddress('t=all&by=call&m=cost.sum')}`);

    await expect(dashboard.rows).toHaveCount(40);
    await expect(dashboard.cut).toContainText(/^The first 40 of [\d,]+ rows, in this order/);
    await dashboard.cut.getByRole('button').click();
    await expect(dashboard.rows).toHaveCount(1000);
    await expect(dashboard.cut).toContainText('(show all: at most 1,000)');
  });

  test('keeps its card’s scroll through Projects and back, nothing read again', async ({ page, people, projects, collection, shell, dashboard }) => {
    await page.setViewportSize({ width: 1280, height: 500 });
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`)}`);
    await expect(dashboard.rows).toHaveCount(TALLY.calls);
    await dashboard.main.evaluate((main) => (main.scrollTop = 150));
    const left = await dashboard.scrollTop();
    expect(left).toBeGreaterThan(100);
    const reads = dashboard.rowsReads();

    await shell.projectsTab.click();
    await expect(dashboard.screen).toBeHidden();
    await shell.dashboardTab.click();
    await expect(dashboard.screen).toBeVisible();

    expect(await dashboard.scrollTop()).toBe(left);
    expect(reads()).toEqual([]);
  });
});

test.describe('A view read in a browser in another zone', () => {
  test.use({ timezoneId: 'Pacific/Auckland' });

  test('by Pilot session reads each its name, the work item’s or the job’s number and title or the chat’s kind, its start under it in the engine’s zone', async ({
    page,
    backendUrl,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    const state = `t=all&by=psession&m=cost.sum&m=calls.count&${chip}`;
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(state)}`);

    await expect(dashboard.labels).toHaveText(['#2 Tidy the ride notes', '#2 Sort the spices', 'Project chat']);
    const answer = (await (await page.request.get(`${backendUrl}/api/dashboard/rows`, { params: { state } })).json()) as { zone: string; rows: { at: string }[] };
    expect(answer.zone).toBe('Europe/Amsterdam');
    await expect(dashboard.times).toHaveText(answer.rows.map((row) => amsterdam(row.at)));
    expect(await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone)).toBe('Pacific/Auckland');
    await expect(dashboard.tab).toHaveText('Pilot session');
  });
});
