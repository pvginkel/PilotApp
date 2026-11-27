/**
 * The custom ratios (F163.6, F155.1, F155.3): made and changed in + Measure, with the built-in ones,
 * a person's with a pencil and a × on hover, and New ratio…; a name, a numerator and a denominator,
 * each side a figure with its aggregate, its items and filters of its own, and the format the
 * person picks, by default a share where the two figures have one format, else the numerator's. A
 * new one joins the view's columns, the entry in place; a change shows in every view that shows it,
 * keeping the note the form does not show, Edit… in its heading's panel changing it too; a name
 * another ratio has is said under the field. A remove asks in a dialog, and the ratio leaves every
 * open tab, now and as it opened. A ratio loaded from the workflow's file stands there as a built-in
 * one does, with no pencil, no × and no Edit…. A threshold on a custom ratio is on the By's rows.
 * The figures are the tally's (`TALLY`), on two projects of the spec's own: 16 Calls and 5 Pilot
 * turns, 3 and 1 on Bikes, 13 and 4 on Recipes.
 */

import type { Page, Request } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import type { Collection } from '../support/collection';
import { makeUnique } from '../support/helpers';
import { dashboardAddress, type DashboardPage } from '../support/page-objects/dashboard-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';

/** The tally loaded on two projects of the person's, and the chip that keeps them. */
async function tally(people: People, projects: Projects, collection: Collection) {
  const me = await people.signIn();
  const recipes = makeUnique('Recipes');
  const recipeBox = await projects.make({ name: recipes, members: [me.handle!] });
  const bikeLog = await projects.make({ name: makeUnique('Bikes'), members: [me.handle!] });
  await collection.loadScenario('tally', { 'recipe-box': recipeBox, 'bike-log': bikeLog });
  return { recipeBox, recipes, chip: `c=project:${[recipeBox, bikeLog].sort().join(',')}` };
}

const historyLength = (page: Page) => page.evaluate(() => history.length);

/** The heading's panel of the measure named `name` opened, by its menu's sign, which shows under the pointer. */
async function openPanel(dashboard: DashboardPage, name: string): Promise<void> {
  await dashboard.measure(name).head.hover();
  await dashboard.measure(name).menu.click();
}

/** The state the address names, its tab's id read off. */
const stateOf = (page: Page) => decodeURIComponent(new URL(page.url()).hash.replace(/^#dash\/[^/=]+\//, ''));

const toast = (page: Page) => page.getByTestId('app-shell.toast.item');

const isWrite = (method: string) => (request: Request) => request.method() === method && new URL(request.url()).pathname.startsWith('/api/dashboard/custom-ratios');

test.describe('A custom ratio', () => {
  test('is made by New ratio… in + Measure, of two figures and the format picked, for everyone, and joins the view’s columns, the entry in place; a threshold on it is on the By’s rows', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}&col=none`)}`);
    await expect(dashboard.allValues).toHaveText(['$2.29']);
    const entries = await historyLength(page);

    await dashboard.addMeasure.click();
    await dashboard.newRatio.click();

    await expect(dashboard.ratioName).toBeFocused();
    const numerator = dashboard.ratioSide('numerator');
    const denominator = dashboard.ratioSide('denominator');
    await expect(numerator.figure).toHaveValue('cost');
    await expect(numerator.aggregate).toHaveValue('sum');
    await expect(denominator.figure).toHaveValue('calls');
    await expect(denominator.aggregate).toHaveValue('count');
    // Cost in dollars over a count: the numerator's.
    await expect(dashboard.ratioFormat).toHaveValue('usd');

    await numerator.figure.selectOption('calls');
    await expect(numerator.aggregate).toHaveValue('count');
    await denominator.figure.selectOption('turns');
    // Two counts: a share.
    await expect(dashboard.ratioFormat).toHaveValue('share');
    await dashboard.ratioFormat.selectOption('count');
    const name = makeUnique('Calls a turn');
    await dashboard.ratioName.fill(name);
    const made = page.waitForRequest(isWrite('POST'));
    await dashboard.ratioSave.click();

    expect((await made).postDataJSON()).toEqual({ name, numerator: 'calls.count', denominator: 'turns.count', format: 'count' });
    await expect(toast(page)).toContainText(`Added the ratio "${name}" for everyone`);
    await expect(dashboard.ratioForm).toHaveCount(0);
    await expect(dashboard.measureHeadings).toHaveText(['Cost', name]);
    await expect(dashboard.allValues).toHaveText(['$2.29', '3.2']);
    await expect(dashboard.values(dashboard.rows.first())).toHaveText(['$1.18', '3']);
    await expect(dashboard.values(dashboard.rows.last())).toHaveText(['$1.11', '3.25']);
    expect(stateOf(page)).toMatch(/&m=r:person_calls_a_turn\w*&/);
    expect(await historyLength(page)).toBe(entries);

    await openPanel(dashboard, name);
    await dashboard.measurePaneFilter.click();
    await expect(dashboard.thresholdRowsAlone).toBeVisible();
    await dashboard.thresholdNumber.fill('3.1');
    await dashboard.thresholdApply.click();

    await expect(dashboard.chipWords(dashboard.chips.last())).toHaveText(`By rows: ${name} > 3.1`);
    await expect(dashboard.labels).toHaveText([/^Recipes/]);
  });

  test('takes on each side a filter of its own, picked in a dimension’s pane among those that reach its figure, Is or Is not, with no mark and no quick filter', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, recipes, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}&col=none`)}`);
    await expect(dashboard.allValues).toHaveText(['$2.29']);

    await dashboard.addMeasure.click();
    await dashboard.newRatio.click();
    const numerator = dashboard.ratioSide('numerator');
    await numerator.addFilter.click();

    await expect(dashboard.filterGroup('Parts').getByText('Project', { exact: true })).toBeVisible();
    await dashboard.filterGroup('Parts').getByText('Project', { exact: true }).click();
    await dashboard.paneValue(recipes).getByRole('checkbox').check();
    await expect(dashboard.paneMark).toHaveCount(0);
    await expect(dashboard.paneQuickFilter).toHaveCount(0);
    await dashboard.paneApply.click();

    await expect(numerator.filters).toHaveText([`Project is ${recipes}`]);
    const name = makeUnique('Recipes a call');
    await dashboard.ratioName.fill(name);
    const made = page.waitForRequest(isWrite('POST'));
    await dashboard.ratioSave.click();

    expect((await made).postDataJSON()).toEqual({ name, numerator: `cost.sum(project=${recipeBox})`, denominator: 'calls.count', format: 'usd' });
    await expect(dashboard.measureHeadings).toHaveText(['Cost', name]);
    // Recipes' cost, $1.11, over every Call, 16, and over its own 13.
    await expect(dashboard.allValues).toHaveText(['$2.29', '$0.07']);
    await expect(dashboard.values(dashboard.rows.last())).toHaveText(['$1.11', '$0.09']);
  });

  test('of a person’s has a pencil and a × in + Measure and Edit… in its heading’s panel, changing it for everyone, the views that show it showing it changed; a name another has is said under the field; a built-in one has neither', async ({
    page,
    people,
    projects,
    collection,
    customRatios,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    const note = 'What a billed call costs';
    const spend = await customRatios.make({ name: makeUnique('Spend a call'), numerator: 'cost.sum', denominator: 'calls.count', format: 'usd', note });
    const other = await customRatios.make({ name: makeUnique('Spend a turn'), numerator: 'cost.sum', denominator: 'turns.count', format: 'usd' });
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=r:${spend.key}&m=r:per_call&${chip}&col=none`)}`);
    await expect(dashboard.measureHeadings).toHaveText(['Cost', spend.name, 'Cost per call']);
    await expect(dashboard.allValues).toHaveText(['$2.29', '$0.14', '$0.14']);

    await dashboard.addMeasure.click();
    const builtIn = dashboard.addMeasureRow('Cost per call');
    await expect(builtIn.pick).toBeVisible();
    await expect(builtIn.edit).toHaveCount(0);
    await expect(builtIn.remove).toHaveCount(0);
    const mine = dashboard.addMeasureRow(spend.name);
    // Shown under the pointer alone: toBeVisible holds at opacity 0.
    for (const act of [mine.edit, mine.remove]) await expect(act).toHaveCSS('opacity', '0');
    await mine.row.hover();
    for (const act of [mine.edit, mine.remove]) await expect(act).toHaveCSS('opacity', '1');
    await mine.edit.click();

    await expect(dashboard.ratioName).toHaveValue(spend.name);
    await expect(dashboard.ratioSide('numerator').figure).toHaveValue('cost');
    await expect(dashboard.ratioSide('denominator').figure).toHaveValue('calls');
    await expect(dashboard.ratioFormat).toHaveValue('usd');
    await dashboard.ratioName.fill(other.name);
    await dashboard.ratioSave.click();
    await expect(dashboard.ratioTaken).toHaveText('Another ratio has that name');
    await expect(dashboard.banner).toHaveCount(0);

    const renamed = makeUnique('Spend a Pilot turn');
    await dashboard.ratioName.fill(renamed);
    await expect(dashboard.ratioTaken).toHaveCount(0);
    await dashboard.ratioSide('denominator').figure.selectOption('turns');
    // The format picked stays.
    await expect(dashboard.ratioFormat).toHaveValue('usd');
    const changed = page.waitForRequest(isWrite('PUT'));
    await dashboard.ratioSave.click();

    // The note, which the form does not show, kept.
    expect((await changed).postDataJSON()).toEqual({ name: renamed, numerator: 'cost.sum', denominator: 'turns.count', format: 'usd', note });
    await expect(toast(page)).toContainText(`Changed the ratio "${renamed}" for everyone`);
    await expect(dashboard.ratioForm).toHaveCount(0);
    await expect(dashboard.addMeasureRow(renamed).pick).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(dashboard.measureHeadings).toHaveText(['Cost', renamed, 'Cost per call']);
    // $2.29 over 5 Pilot turns.
    await expect(dashboard.allValues).toHaveText(['$2.29', '$0.46', '$0.14']);

    await openPanel(dashboard, 'Cost per call');
    await expect(dashboard.measurePaneFilter).toBeVisible();
    await expect(dashboard.measurePaneEdit).toHaveCount(0);
    await dashboard.measurePaneClose.click();

    await openPanel(dashboard, renamed);
    await dashboard.measurePaneEdit.click();
    await expect(dashboard.ratioName).toHaveValue(renamed);
    await expect(dashboard.ratioSide('denominator').figure).toHaveValue('turns');
    await dashboard.ratioBack.click();
    await expect(dashboard.measurePaneName).toHaveText(renamed);
  });

  test('of a person’s, removed after the dialog’s question, leaves every open tab, now and as it opened', async ({ page, people, projects, collection, customRatios, shell, dashboard }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    const spend = await customRatios.make({ name: makeUnique('Spend a call'), numerator: 'cost.sum', denominator: 'calls.count', format: 'usd' });
    const ratio = `r:${spend.key}`;
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=${ratio}&${chip}&col=none&o=desc,${encodeURIComponent(ratio)}`)}`);
    await expect(dashboard.measureHeadings).toHaveText(['Cost', spend.name]);
    await dashboard.follow(`#dash/t=all&by=project&m=${ratio}&${chip}&c=@rows,gt,0.1,${ratio}&col=none`);
    await expect(dashboard.lineTabs).toHaveCount(2);
    await expect(dashboard.measureHeadings).toHaveText([spend.name]);
    await expect(dashboard.labels).toHaveText([/^Bikes/]);

    await dashboard.addMeasure.click();
    const mine = dashboard.addMeasureRow(spend.name);
    await mine.row.hover();
    await mine.remove.click();

    await expect(dashboard.addMeasure).toHaveAttribute('aria-expanded', 'false');
    await expect(dashboard.ratioRemoveDialog.getByTestId('dashboard.ratio.remove-dialog.title')).toHaveText(`Remove the ratio "${spend.name}"?`);
    const removed = page.waitForRequest(isWrite('DELETE'));
    await dashboard.ratioRemoveDialog.getByTestId('dashboard.ratio.remove-dialog.confirm').click();
    await removed;

    await expect(toast(page)).toContainText(`Removed the ratio "${spend.name}" for everyone`);
    await expect(dashboard.measureHeadings).toHaveText(['Cost']);
    await expect(dashboard.chips).toHaveCount(1);
    await expect(dashboard.labels).toHaveText([/^Bikes/, /^Recipes/]);
    expect(stateOf(page)).not.toContain(ratio);
    expect((await dashboard.keptTabs()).map((tab) => tab.now ?? '').filter((now) => now.includes(ratio))).toEqual([]);
    await expect(dashboard.reset).toBeDisabled();

    await dashboard.lineTabs.first().click();
    await expect(dashboard.measureHeadings).toHaveText(['Cost']);
    expect(stateOf(page)).not.toContain(ratio);
    await expect(dashboard.reset).toBeDisabled();
    await dashboard.addMeasure.click();
    await expect(dashboard.addMeasureRow(spend.name).row).toHaveCount(0);
  });

  test('loaded from the workflow’s file stands in + Measure as a built-in one does, with no pencil and no ×, and its heading’s panel has no Edit…', async ({
    people,
    projects,
    collection,
    customRatios,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    const loaded = makeUnique('Spend a turn, loaded');
    await customRatios.loadWorkflow([{ key: 'spec_per_turn', name: loaded, numerator: 'cost.sum', denominator: 'turns.count' }]);
    const mine = await customRatios.make({ name: makeUnique('Spend a call'), numerator: 'cost.sum', denominator: 'calls.count', format: 'usd' });
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=r:spec_per_turn&${chip}&col=none`)}`);
    await expect(dashboard.measureHeadings).toHaveText(['Cost', loaded]);
    await expect(dashboard.allValues).toHaveText(['$2.29', '$0.46']);

    await openPanel(dashboard, loaded);
    await expect(dashboard.measurePaneFilter).toBeVisible();
    await expect(dashboard.measurePaneEdit).toHaveCount(0);
    await dashboard.measurePaneClose.click();

    await dashboard.addMeasure.click();
    const workflows = dashboard.addMeasureRow(loaded);
    await workflows.row.hover();
    await expect(workflows.edit).toHaveCount(0);
    await expect(workflows.remove).toHaveCount(0);
    const persons = dashboard.addMeasureRow(mine.name);
    for (const act of [persons.edit, persons.remove]) await expect(act).toHaveCSS('opacity', '0');
    await persons.row.hover();
    for (const act of [persons.edit, persons.remove]) await expect(act).toHaveCSS('opacity', '1');
  });
});
