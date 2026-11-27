/**
 * A filter on a measure, made from its column (F162.5, F162.6): Filter… in a heading's panel opens
 * the threshold's pane in the panel's place, its head's arrow the way back to it; a threshold joins
 * the scope's chips, a new entry, and its chip's words open the pane to change it or remove it. On
 * the By's rows it keeps or marks the rows that pass, a ratio's among them, which is on the By's
 * rows alone; on each item, Is or Is not, its pane makes a quick filter under a name, for everyone,
 * where the By's rows' makes none. The figures are the tally's (`TALLY`), on two projects of the
 * spec's own: cost per call $0.39 on Bikes and $0.09 on Recipes, one Call of $1.05 among them.
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
  const recipeBox = await projects.make({ name: makeUnique('Recipes'), members: [me.handle!] });
  const bikeLog = await projects.make({ name: makeUnique('Bikes'), members: [me.handle!] });
  await collection.loadScenario('tally', { 'recipe-box': recipeBox, 'bike-log': bikeLog });
  return { recipeBox, chip: `c=project:${[recipeBox, bikeLog].sort().join(',')}` };
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

const isMade = (request: Request) => request.method() === 'POST' && new URL(request.url()).pathname === '/api/dashboard/quick-filters';

test.describe('A filter on a measure', () => {
  test('on a ratio, by Filter… in its heading’s panel, is on the By’s rows alone, the pane’s arrow going back to the panel; it joins the chips, a new entry, and its words open it to change it, to mark and to remove it', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&m=r:per_call&${chip}&col=none`)}`);
    await expect(dashboard.labels).toHaveText([/^Bikes/, /^Recipes/]);
    await expect(dashboard.values(dashboard.rows.first())).toHaveText(['$1.18', '$0.39']);

    await openPanel(dashboard, 'Cost per call');
    await dashboard.measurePaneFilter.click();

    await expect(dashboard.thresholdName).toHaveText('Filter by Cost per call');
    await expect(dashboard.thresholdRowsAlone).toBeVisible();
    await expect(dashboard.thresholdItems).toHaveCount(0);
    await expect(dashboard.thresholdQuickFilter).toHaveCount(0);
    await expect(dashboard.thresholdNumber).toBeFocused();
    await expect(dashboard.thresholdApply).toBeDisabled();

    await dashboard.thresholdBack.click();
    await expect(dashboard.measurePaneName).toHaveText('Cost per call');
    await expect(dashboard.threshold).toHaveCount(0);

    await dashboard.measurePaneFilter.click();
    await dashboard.thresholdNumber.fill('0.3');
    const entries = await historyLength(page);
    await dashboard.thresholdApply.click();

    await expect(dashboard.measurePane).toHaveCount(0);
    await expect(dashboard.chipWords(dashboard.chips.last())).toHaveText('By rows: Cost per call > 0.3');
    await expect(dashboard.labels).toHaveText([/^Bikes/]);
    expect(stateOf(page)).toContain('c=@rows,gt,0.3,r:per_call');
    expect(await historyLength(page)).toBe(entries + 1);

    await dashboard.chipWords(dashboard.chips.last()).click();
    await expect(dashboard.thresholdNumber).toHaveValue('0.3');
    await expect(dashboard.thresholdOperator('gt')).toHaveAttribute('aria-pressed', 'true');
    await expect(dashboard.thresholdBack).toHaveCount(0);
    await dashboard.thresholdOperator('lt').click();
    await dashboard.thresholdApply.click();

    await expect(dashboard.chipWords(dashboard.chips.last())).toHaveText('By rows: Cost per call < 0.3');
    await expect(dashboard.labels).toHaveText([/^Recipes/]);
    expect(stateOf(page)).toContain('c=@rows,lt,0.3,r:per_call');

    await dashboard.chipWords(dashboard.chips.last()).click();
    await dashboard.thresholdMark.click();
    await dashboard.thresholdApply.click();

    // A row marked has the mark's sign before its label.
    await expect(dashboard.labels).toHaveText([/^Bikes/, /^◇ Recipes/]);
    await expect(page.locator('[data-testid="dashboard.row"].marked')).toHaveCount(1);
    expect(stateOf(page)).toContain('c=~@rows,lt,0.3,r:per_call');

    await dashboard.chipWords(dashboard.chips.last()).click();
    await dashboard.thresholdRemove.click();
    await expect(dashboard.chips).toHaveCount(1);
    await expect(page.locator('[data-testid="dashboard.row"].marked')).toHaveCount(0);
  });

  test('on each item, Is or Is not, keeps the items that pass or those that fail; its pane makes a quick filter under a name, for everyone, where the By’s rows’ offers none', async ({
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

    await openPanel(dashboard, 'Cost');
    await dashboard.measurePaneFilter.click();

    await expect(dashboard.thresholdRows).toHaveAttribute('aria-pressed', 'true');
    await expect(dashboard.thresholdQuickFilter).toHaveCount(0);
    await expect(dashboard.thresholdIsNot).toHaveCount(0);
    await dashboard.thresholdItems.click();
    await expect(dashboard.thresholdItems).toHaveText('Each call');
    await expect(dashboard.thresholdIsNot).toBeVisible();
    await dashboard.thresholdNumber.fill('1');
    await dashboard.thresholdApply.click();

    await expect(dashboard.chipWords(dashboard.chips.last())).toHaveText('Each call: Cost > 1');
    await expect(dashboard.allValues).toHaveText(['$1.05']);
    await expect(dashboard.rows).toHaveCount(1);
    expect(stateOf(page)).toContain('c=@items,gt,1,cost.sum');

    await dashboard.chipWords(dashboard.chips.last()).click();
    await expect(dashboard.thresholdItems).toHaveAttribute('aria-pressed', 'true');
    await dashboard.thresholdIsNot.click();
    await dashboard.thresholdApply.click();

    await expect(dashboard.chipWords(dashboard.chips.last())).toHaveText('Each call not: Cost > 1');
    await expect(dashboard.allValues).toHaveText(['$1.23']);
    await expect(dashboard.rows).toHaveCount(2);
    expect(stateOf(page)).toContain('c=!@items,gt,1,cost.sum');
    const before = stateOf(page);
    const entries = await historyLength(page);

    await dashboard.chipWords(dashboard.chips.last()).click();
    await dashboard.thresholdQuickFilter.click();
    await expect(dashboard.quickFilterName).toHaveValue('Each call not: Cost > 1');
    await expect(dashboard.quickFilterName).toBeFocused();
    const name = makeUnique('Spec cheap calls');
    await dashboard.quickFilterName.fill(name);
    const made = page.waitForRequest(isMade);
    await dashboard.quickFilterSave.click();

    expect((await made).postDataJSON()).toEqual({ label: name, chip: '!@items,gt,1,cost.sum', amount: 'cost' });
    await expect(dashboard.threshold).toHaveCount(0);
    await expect(toast(page)).toContainText(`Added the quick filter "${name}" for everyone`);
    const cheap = dashboard.quickFilter(name);
    await expect(cheap.count).toHaveText('15');
    await expect(cheap.amount).toHaveText('$1.23');
    expect(stateOf(page)).toBe(before);
    expect(await historyLength(page)).toBe(entries);

    await dashboard.chipWords(dashboard.chips.last()).click();
    await dashboard.thresholdRows.click();
    await expect(dashboard.thresholdQuickFilter).toHaveCount(0);
    await expect(dashboard.thresholdIsNot).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(dashboard.threshold).toHaveCount(0);

    await cheap.item.hover();
    await cheap.remove.click();
    await dashboard.quickFilterRemoveDialog.getByTestId('dashboard.quick-filter.remove-dialog.confirm').click();
    await expect(cheap.item).toHaveCount(0);
  });
});
