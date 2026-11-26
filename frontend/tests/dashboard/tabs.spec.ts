/**
 * The dashboard's view tabs (F161) and the new tab's panel (F161.4): the dashboard's first opening
 * is the panel, its find and Start from scratch over System views and Saved views; a view opened
 * there takes its tab, which with one view stands at the global toolbar's left, its close going
 * back to the panel; copy-plus opens another, the line of tabs showing from two on, each its
 * presentation's icon and its name, the tab showing closed giving way to the one that showed
 * before it; each tab's answers kept while another shows, and read again as it is brought into
 * view after the walk's event; the tabs, the tab at hand and its scroll back after a reload, a
 * window beside it keeping its own (F161.1, F160.10). On the panel a view's star, a saved view's
 * rename and remove (F161.7), each write failing into the banner alone and reading again no figure.
 */

import type { Locator, Page, Request } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { TALLY, type Collection } from '../support/collection';
import { NONE_LEFT } from '../support/dashboard-bounds';
import { expectConsoleError, makeUnique } from '../support/helpers';
import { dashboardAddress, type DashboardPage } from '../support/page-objects/dashboard-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';

const SCRATCH = 't=qw&by=project&m=cost.sum&col=none';

const historyLength = (page: Page) => page.evaluate(() => history.length);
const box = (locator: Locator) => locator.evaluate((element) => element.getBoundingClientRect().toJSON() as DOMRect);
const toast = (page: Page) => page.getByTestId('app-shell.toast.item');

/** A project of the person's, signed in. */
async function aProject(people: People, projects: Projects) {
  const me = await people.signIn();
  return projects.make({ name: makeUnique('Tabs'), members: [me.handle!] });
}

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

/** The tab of the line named `name`, as its tab role. */
const lineTab = (dashboard: DashboardPage, name: string) => dashboard.lineTab(name).getByRole('tab');

/** Opens the view named `name` from a list of the panel. */
const open = (dashboard: DashboardPage, list: Locator, name: string) => dashboard.view(list, name).getByTestId('dashboard.panel.view.open').click();

/** Where the browser keeps the tab `id`'s scroll. */
const keptScroll = (page: Page, id: string) =>
  page.evaluate((tab) => (JSON.parse(localStorage.getItem('pilot') ?? '{}').viewTabs?.tabs ?? []).find((each: { id: string }) => each.id === tab)?.scroll, id);

test.describe('The new tab’s panel', () => {
  test('is the dashboard’s first opening, with no line and no toolbar: its block centred, the find and Start from scratch over System views at the left and Saved views at the right', async ({
    people,
    projects,
    shell,
    dashboard,
  }) => {
    const project = await aProject(people, projects);
    await shell.open(`${projectAddress(project)}#dash`);

    await expect(dashboard.panel).toBeVisible();
    await expect(dashboard.line).toHaveCount(0);
    await expect(dashboard.toolbar).toHaveCount(0);
    await expect(dashboard.find).toHaveAttribute('placeholder', 'Find a view');
    await expect(dashboard.scratch).toHaveText('Start from scratch');
    await expect(dashboard.scratch).toHaveAttribute('title', 'This quota week, by project, cost alone');
    await expect(dashboard.systemViews.getByRole('heading')).toHaveText('System views');
    await expect(dashboard.savedViews.getByRole('heading')).toHaveText('Saved views');
    for (const name of ['Projects', 'Work types', 'Where the week went']) await expect(dashboard.view(dashboard.systemViews, name)).toBeVisible();

    const system = await box(dashboard.systemViews);
    const saved = await box(dashboard.savedViews);
    expect(system.top).toBe(saved.top);
    expect(system.right).toBeLessThanOrEqual(saved.left);
    const panel = await box(dashboard.panel);
    const head = await box(dashboard.panel.getByTestId('dashboard.panel.head'));
    const lists = await box(dashboard.panel.getByTestId('dashboard.panel.lists'));
    expect(Math.abs(head.top - panel.top - (panel.bottom - lists.bottom))).toBeLessThanOrEqual(1);
  });

  test('lists a system view with its star alone, what it draws and its note in its tooltip; a saved view with its rename, its remove and its star', async ({
    people,
    projects,
    shell,
    dashboard,
    savedViews,
  }) => {
    const project = await aProject(people, projects);
    const name = makeUnique('Saved');
    await savedViews.save(name, 't=qw&by=model&p=table&m=calls.count&col=none');
    await shell.open(`${projectAddress(project)}#dash`);

    const system = dashboard.view(dashboard.systemViews, 'Projects');
    await expect(system.getByTestId('dashboard.panel.view.open')).toHaveAttribute(
      'title',
      "By Project · All time · Cost, Tokens, Cache misses, Peak context\nEach project's cost, tokens, cache misses and largest context, over all time, colored by work type",
    );
    await expect(system.locator('svg.lucide-chart-bar')).toHaveCount(1);
    await expect(dashboard.view(dashboard.systemViews, 'Where the week went').locator('svg.lucide-chart-line')).toHaveCount(1);
    await system.hover();
    await expect(system.getByTestId('dashboard.panel.view.star')).toBeVisible();
    await expect(system.getByTestId('dashboard.panel.view.rename')).toHaveCount(0);
    await expect(system.getByTestId('dashboard.panel.view.remove')).toHaveCount(0);

    const mine = dashboard.view(dashboard.savedViews, name);
    await expect(mine.getByTestId('dashboard.panel.view.open')).toHaveAttribute('title', 'Table by Model · This quota week · Calls');
    await expect(mine.locator('svg.lucide-table')).toHaveCount(1);
    await expect(mine.getByTestId('dashboard.panel.view.star')).toHaveCSS('opacity', '0');
    await mine.hover();
    for (const act of ['rename', 'remove', 'star']) await expect(mine.getByTestId(`dashboard.panel.view.${act}`)).toHaveCSS('opacity', '1');
  });

  test('finds views in both lists on the name, case aside, Esc clearing the find; lists the starred first in the order starred, kept for the person', async ({
    page,
    people,
    projects,
    shell,
    dashboard,
    savedViews,
  }) => {
    const project = await aProject(people, projects);
    const tag = makeUnique('Find');
    const [alpha, beta] = [`${tag} alpha`, `${tag} beta`];
    await savedViews.save(alpha, 't=all&by=project&m=cost.sum&col=none');
    await savedViews.save(beta, 't=all&by=model&m=cost.sum&col=none');
    await shell.open(`${projectAddress(project)}#dash`);
    await expect(dashboard.view(dashboard.savedViews, alpha)).toBeVisible();

    await dashboard.find.fill(tag.toUpperCase());
    await expect(dashboard.viewNames(dashboard.savedViews)).toHaveText([alpha, beta]);
    await expect(dashboard.viewNames(dashboard.systemViews)).toHaveCount(0);
    await expect(dashboard.systemViews.getByTestId('dashboard.panel.system.none')).toHaveText('No view matches.');

    await dashboard.act(dashboard.view(dashboard.savedViews, beta), 'star');
    await expect(dashboard.viewNames(dashboard.savedViews)).toHaveText([beta, alpha]);
    await dashboard.act(dashboard.view(dashboard.savedViews, alpha), 'star');
    await expect(dashboard.viewNames(dashboard.savedViews)).toHaveText([beta, alpha]);
    await expect(dashboard.view(dashboard.savedViews, alpha).getByTestId('dashboard.panel.view.star')).toHaveAttribute('aria-pressed', 'true');
    await dashboard.act(dashboard.view(dashboard.savedViews, beta), 'star');
    await expect(dashboard.viewNames(dashboard.savedViews)).toHaveText([alpha, beta]);

    await dashboard.find.press('Escape');
    await expect(dashboard.find).toHaveValue('');
    await expect(dashboard.view(dashboard.systemViews, 'Projects')).toBeVisible();
    await dashboard.act(dashboard.view(dashboard.systemViews, 'Where the week went'), 'star');
    await expect(dashboard.viewNames(dashboard.systemViews).first()).toHaveText('Where the week went');
    await expect(dashboard.viewNames(dashboard.savedViews).first()).toHaveText(alpha);

    await page.reload();
    await expect(dashboard.viewNames(dashboard.systemViews).first()).toHaveText('Where the week went');
    await expect(dashboard.viewNames(dashboard.savedViews).first()).toHaveText(alpha);
  });

  test('renames a saved view in place, the tab that opened it taking the new name, a name taken said under the field; removes one behind a dialog, the tab that has it keeping what it shows', async ({
    page,
    people,
    projects,
    shell,
    dashboard,
    savedViews,
  }) => {
    const project = await aProject(people, projects);
    const tag = makeUnique('Name');
    const [one, two, three] = [`${tag} one`, `${tag} two`, `${tag} three`];
    await savedViews.save(one, 't=all&by=project&m=cost.sum&col=none');
    await savedViews.save(two, 't=all&by=model&m=cost.sum&col=none');
    await shell.open(`${projectAddress(project)}#dash`);
    await open(dashboard, dashboard.savedViews, one);
    await expect(dashboard.tab).toHaveText(one);
    await dashboard.newView.click();
    await dashboard.find.fill(tag);

    await dashboard.act(dashboard.view(dashboard.savedViews, one), 'rename');
    const field = dashboard.savedViews.getByTestId('dashboard.panel.view.name-field');
    await expect(field).toBeFocused();
    await expect(field).toHaveValue(one);
    await field.fill(two);
    await field.press('Enter');
    await expect(dashboard.savedViews.getByTestId('dashboard.panel.view.taken')).toHaveText(`A view named "${two}" exists already`);
    await expect(field).toBeVisible();
    await field.fill(three);
    await field.press('Enter');
    await expect(toast(page)).toContainText(`Renamed the view "${one}" to "${three}"`);
    await expect(dashboard.view(dashboard.savedViews, three)).toBeVisible();
    await expect(dashboard.lineNames).toHaveText([three, 'New view']);

    await dashboard.act(dashboard.view(dashboard.savedViews, two), 'rename');
    await field.fill('Anything else');
    await field.press('Escape');
    await expect(field).toHaveCount(0);
    await expect(dashboard.view(dashboard.savedViews, two)).toBeVisible();

    await dashboard.act(dashboard.view(dashboard.savedViews, three), 'remove');
    await expect(dashboard.removeDialog.getByTestId('dashboard.panel.remove-dialog.title')).toHaveText(`Remove the view "${three}"?`);
    await dashboard.removeDialog.getByTestId('dashboard.panel.remove-dialog.confirm').click();
    await expect(dashboard.removeDialog).toHaveCount(0);
    await expect(toast(page).last()).toContainText(`Removed the view "${three}" for everyone`);
    await expect(dashboard.view(dashboard.savedViews, three)).toHaveCount(0);
    await lineTab(dashboard, three).click();
    await expect(dashboard.byHeading).toHaveText('Project');
  });

  test('fails a write into the banner alone, with no toast and no Retry, the list read again; a write reads again no view’s figures', async ({
    page,
    people,
    projects,
    shell,
    dashboard,
    savedViews,
  }) => {
    const project = await aProject(people, projects);
    const name = makeUnique('Gone');
    const id = await savedViews.save(name, 't=all&by=project&m=cost.sum&col=none');
    await shell.open(`${projectAddress(project)}${dashboardAddress(SCRATCH)}`);
    await expect(dashboard.byHeading).toHaveText('Project');
    let favourites = 0;
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/dashboard/favourites') favourites += 1;
    });
    await dashboard.newView.click();
    await expect(dashboard.view(dashboard.savedViews, name)).toBeVisible();
    const reads = dashboard.rowsReads();
    favourites = 0;

    const star = dashboard.view(dashboard.systemViews, 'Projects').getByTestId('dashboard.panel.view.star');
    await dashboard.act(dashboard.view(dashboard.systemViews, 'Projects'), 'star');
    await expect(star).toHaveAttribute('aria-pressed', 'true');
    await expect.poll(() => favourites).toBe(1);

    await expectConsoleError(page, /404/);
    await savedViews.remove(id);
    await dashboard.act(dashboard.view(dashboard.savedViews, name), 'remove');
    await dashboard.removeDialog.getByTestId('dashboard.panel.remove-dialog.confirm').click();
    await expect(dashboard.bannerText).toHaveText(`Saved view ${id} was not found`);
    await expect(dashboard.retry).toHaveCount(0);
    await expect(toast(page)).toHaveCount(0);
    await expect(dashboard.view(dashboard.savedViews, name)).toHaveCount(0);
    expect(reads()).toEqual([]);

    await dashboard.closeBanner.click();
    await expect(dashboard.banner).toHaveCount(0);
    await lineTab(dashboard, 'Project').click();
    await expect(dashboard.byHeading).toHaveText('Project');
    await expect(dashboard.banner).toHaveCount(0);
  });
});

test.describe('The view tabs', () => {
  test('a view opened from the panel takes its tab, at the toolbar’s left with copy-plus at its end; its close, or the middle button’s, goes back to the panel, adding no entry', async ({
    page,
    people,
    projects,
    shell,
    dashboard,
  }) => {
    const project = await aProject(people, projects);
    await shell.open(`${projectAddress(project)}#dash`);
    await dashboard.scratch.click();

    await expect(page).toHaveURL(new RegExp(`#dash/[a-z0-9]{4}/${SCRATCH.replace(/\./g, '\\.')}$`));
    await expect(dashboard.panel).toHaveCount(0);
    await expect(dashboard.line).toHaveCount(0);
    await expect(dashboard.tab).toHaveText('Project');
    await expect(dashboard.tab.locator('svg.lucide-chart-bar')).toHaveCount(1);
    await expect(dashboard.toolbar.locator(':scope > *').first()).toHaveAttribute('data-testid', 'dashboard.tab');
    await expect(dashboard.toolbar.locator(':scope > *').last()).toHaveAttribute('data-testid', 'dashboard.new');
    await expect(dashboard.byHeading).toHaveText('Project');

    const entries = await historyLength(page);
    await dashboard.tabClose.click();
    await expect(dashboard.panel).toBeVisible();
    await expect(page).toHaveURL(/#dash\/[a-z0-9]{4}$/);
    expect(await historyLength(page)).toBe(entries);

    await open(dashboard, dashboard.systemViews, 'Work types');
    await expect(dashboard.tab).toHaveText('Work types');
    await dashboard.tab.click({ button: 'middle' });
    await expect(dashboard.panel).toBeVisible();
  });

  test('copy-plus opens another on the panel, the line showing, each tab its icon and its name; the tab showing closed gives way to the one that showed before it; Close all leaves the panel', async ({
    page,
    people,
    projects,
    shell,
    dashboard,
  }) => {
    const project = await aProject(people, projects);
    await shell.open(`${projectAddress(project)}#dash`);
    await dashboard.scratch.click();
    await expect(dashboard.tab).toHaveText('Project');

    await dashboard.newView.click();
    await expect(dashboard.lineNames).toHaveText(['Project', 'New view']);
    await expect(lineTab(dashboard, 'New view')).toHaveAttribute('aria-selected', 'true');
    await expect(dashboard.lineTab('New view').locator('svg.lucide-layout-list')).toHaveCount(1);
    await expect(dashboard.panel).toBeVisible();
    await expect(dashboard.tab).toHaveCount(0);
    await expect(dashboard.closeAll).toBeVisible();
    await expect(dashboard.line.locator(':scope > *').last()).toHaveAttribute('data-testid', 'dashboard.new');

    await open(dashboard, dashboard.systemViews, 'Where the week went');
    await expect(dashboard.lineNames).toHaveText(['Project', 'Where the week went']);
    await expect(dashboard.lineTab('Where the week went').locator('svg.lucide-chart-line')).toHaveCount(1);
    await expect(dashboard.toolbar).toBeVisible();
    await expect(dashboard.tab).toHaveCount(0);
    await expect(dashboard.toolbar.getByTestId('dashboard.new')).toHaveCount(0);
    await dashboard.newView.click();
    await open(dashboard, dashboard.systemViews, 'Work types');
    await expect(dashboard.lineNames).toHaveText(['Project', 'Where the week went', 'Work types']);

    await lineTab(dashboard, 'Project').click();
    await expect(lineTab(dashboard, 'Project')).toHaveAttribute('aria-selected', 'true');
    await expect(dashboard.byHeading).toHaveText('Project');
    await lineTab(dashboard, 'Work types').click();
    await expect(dashboard.byHeading).toHaveText('Work type');
    const entries = await historyLength(page);
    await dashboard.lineTab('Work types').getByTestId('dashboard.tabs.tab.close').click();
    await expect(dashboard.lineNames).toHaveText(['Project', 'Where the week went']);
    await expect(lineTab(dashboard, 'Project')).toHaveAttribute('aria-selected', 'true');
    await expect(lineTab(dashboard, 'Project')).toBeFocused();

    await dashboard.lineTab('Where the week went').click({ button: 'middle' });
    await expect(dashboard.line).toHaveCount(0);
    await expect(dashboard.tab).toHaveText('Project');
    expect(await historyLength(page)).toBe(entries);

    await dashboard.newView.click();
    await expect(dashboard.lineNames).toHaveText(['Project', 'New view']);
    await dashboard.closeAll.click();
    await expect(dashboard.line).toHaveCount(0);
    await expect(dashboard.tab).toHaveCount(0);
    await expect(dashboard.panel).toBeVisible();
    expect(await historyLength(page)).toBe(entries + 1);
  });

  test('a link opened cold opens one tab of its own, the address written back in place to name it, where it names no tab and where it names one the page cannot take', async ({
    page,
    people,
    projects,
    shell,
    dashboard,
  }) => {
    const project = await aProject(people, projects);
    const byModel = 't=qw&by=model&m=cost.sum&col=none';
    await shell.open(`${projectAddress(project)}#dash/${SCRATCH}`);

    await expect(dashboard.tab).toHaveText('Project');
    await expect(dashboard.line).toHaveCount(0);
    const [opened] = await dashboard.keptTabs();
    expect(await dashboard.keptTabs()).toEqual([{ id: opened.id, now: SCRATCH }]);
    await expect(page).toHaveURL(`${projectAddress(project)}#dash/${opened.id}/${SCRATCH}`);

    await page.goto(`${projectAddress(project)}#dash/not_one/${byModel}`);
    await expect(dashboard.lineNames).toHaveText(['Project', 'Model']);
    const tabs = await dashboard.keptTabs();
    expect(tabs).toHaveLength(2);
    expect(tabs[1]).toEqual({ id: expect.stringMatching(/^[a-z0-9]{4}$/), now: byModel });
    await expect(page).toHaveURL(`${projectAddress(project)}#dash/${tabs[1].id}/${byModel}`);
  });

  test('keep their answers while another shows, never reading them; after the walk’s event the tab in view is read again, another as it is brought into view', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    deploymentSse,
  }) => {
    const { first, chip, more } = await fourProjects(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`, 'byproj')}`);
    await deploymentSse.ensureConnected();
    await expect(dashboard.rows).toHaveCount(2);
    await dashboard.go(dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`, 'bycall'));
    await expect(dashboard.lineNames).toHaveText(['Project', 'Call']);
    await expect(dashboard.rows).toHaveCount(TALLY.calls);
    const reads = dashboard.rowsReads();

    await lineTab(dashboard, 'Project').click();
    await expect(dashboard.rows).toHaveCount(2);
    await lineTab(dashboard, 'Call').click();
    await expect(dashboard.rows).toHaveCount(TALLY.calls);
    await lineTab(dashboard, 'Project').click();
    await expect(dashboard.rows).toHaveCount(2);
    expect(reads()).toEqual([]);

    await more();
    const answered = dashboard.rowsAnswered();
    const read = page.waitForRequest(isRows);
    expect((await collection.walk()).announced).toBe(true);
    await read;
    await expect(dashboard.rows).toHaveCount(4);
    expect(answered()).toHaveLength(1);
    expect(answered()[0]).toContain('by=project');

    await lineTab(dashboard, 'Call').click();
    await expect(dashboard.rows).toHaveCount(TALLY.calls * 2);
    expect(answered()).toHaveLength(2);
    expect(answered()[1]).toContain('by=call');
  });

  test('keep a tab’s answers out of sight for as long as the tab, past the five minutes a query no one reads is kept for: brought into view it draws them with every read refused', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
    dashboardBounds,
  }) => {
    await page.clock.install();
    const { first, chip } = await fourProjects(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`, 'byproj')}`);
    await expect(dashboard.rows).toHaveCount(2);
    await dashboard.go(dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`, 'bycall'));
    await expect(dashboard.rows).toHaveCount(TALLY.calls);

    // Past the five minutes a query no one reads is kept for, the engine refusing every read from then on.
    await page.clock.fastForward('06:00');
    await expectConsoleError(page, /409/);
    await dashboardBounds.set({ timeout_seconds: NONE_LEFT });
    await lineTab(dashboard, 'Project').click();
    await expect(lineTab(dashboard, 'Project')).toHaveAttribute('aria-selected', 'true');
    await expect(dashboard.rows).toHaveCount(2);
  });

  test('come back after a reload, each one’s state, the tab at hand and its scroll; Dashboard opens on the tab the browser holds; a window beside it keeps its own', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    await page.setViewportSize({ width: 1280, height: 500 });
    const { first, chip } = await fourProjects(people, projects, collection);
    await shell.open(`${projectAddress(first)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`, 'byproj')}`);
    await expect(dashboard.rows).toHaveCount(2);
    await dashboard.go(dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`, 'bycall'));
    await expect(dashboard.rows).toHaveCount(TALLY.calls);
    await dashboard.main.evaluate((main) => (main.scrollTop = 150));
    const left = await dashboard.scrollTop();
    expect(left).toBeGreaterThan(100);
    await expect.poll(() => keptScroll(page, 'bycall')).toBe(left);

    await page.reload();
    await expect(dashboard.lineNames).toHaveText(['Project', 'Call']);
    await expect(lineTab(dashboard, 'Call')).toHaveAttribute('aria-selected', 'true');
    await expect(dashboard.rows).toHaveCount(TALLY.calls);
    await expect.poll(() => dashboard.scrollTop()).toBe(left);
    await lineTab(dashboard, 'Project').click();
    await expect(dashboard.rows).toHaveCount(2);

    await shell.open(projectAddress(first));
    await expect(shell.dashboardTab).toHaveAttribute('href', `${projectAddress(first)}#dash`);
    await shell.dashboardTab.click();
    await expect(lineTab(dashboard, 'Project')).toHaveAttribute('aria-selected', 'true');
    await expect(dashboard.rows).toHaveCount(2);

    const other = await page.context().newPage();
    await other.goto(`${projectAddress(first)}#dash`);
    const beside = other.getByTestId('dashboard.tabs.tab.name');
    await expect(beside).toHaveText(['Project', 'Call']);
    await dashboard.newView.click();
    await expect(dashboard.lineNames).toHaveText(['Project', 'Call', 'New view']);
    await other.getByTestId('dashboard.new').click();
    await expect(beside).toHaveText(['Project', 'Call', 'New view']);
    await other.getByTestId('dashboard.tabs.close-all').click();
    await expect(beside).toHaveCount(0);
    await expect(dashboard.lineNames).toHaveText(['Project', 'Call', 'New view']);
    await other.close();
  });
});
