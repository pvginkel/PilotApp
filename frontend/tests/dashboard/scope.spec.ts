/**
 * The view's scope above its card (F162.3, F162.4): a row of the view drills into its value, the
 * drill path one segmented bar, All first, then a segment per level, its kind small and muted before
 * its value's words; a parent's press goes back to it with its By, All's clears the drill, each a
 * new entry (F160.4); a tab is named by its drill's last level (F161.2). An attribute's row keeps its
 * value in a chip; a Call's row drills into nothing. A level and a chip opened cold are named by a
 * lookup. A chip: its sign, a funnel where it filters and a diamond where it marks, which a press
 * flips; its words, its values cut before "n more" and every value in its tooltip, which open its
 * pane; its ×; at most 300 px wide; of a negated chip only "is not" marked out. The filter picker
 * lists the parts and the attributes, no time; a dimension's pane its values in scope, searched,
 * Is or Is not. The figures are the tally's, on two projects of the spec's own.
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import type { Collection } from '../support/collection';
import { makeUnique } from '../support/helpers';
import { dashboardAddress } from '../support/page-objects/dashboard-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';

/** The tally loaded on two projects of the person's: their ids and names, and the chip that keeps them. */
async function tally(people: People, projects: Projects, collection: Collection) {
  const me = await people.signIn();
  const recipes = makeUnique('Recipes');
  const bikes = makeUnique('Bikes');
  const recipeBox = await projects.make({ name: recipes, members: [me.handle!] });
  const bikeLog = await projects.make({ name: bikes, members: [me.handle!] });
  await collection.loadScenario('tally', { 'recipe-box': recipeBox, 'bike-log': bikeLog });
  return { recipeBox, recipes, bikes, chip: `c=project:${[recipeBox, bikeLog].sort().join(',')}` };
}

/** The keys of the rows of `by` the tally answers under `chip`, by their labels, in the answer's order. */
async function keysOf(page: Page, backendUrl: string, by: string, chip: string): Promise<{ key: string; label: string }[]> {
  const response = await page.request.get(`${backendUrl}/api/dashboard/rows`, { params: { state: `t=all&by=${by}&m=cost.sum&${chip}` } });
  expect(response.status(), await response.text()).toBe(200);
  return ((await response.json()) as { rows: { key: string; label: string }[] }).rows.map(({ key, label }) => ({ key, label }));
}

const historyLength = (page: Page) => page.evaluate(() => history.length);

/** The state the address names, its tab's id read off. */
const stateOf = (page: Page) => decodeURIComponent(new URL(page.url()).hash.replace(/^#dash\/[^/=]+\//, ''));

test.describe('The drill path', () => {
  test('a row drills into its value, the path naming each level and the tab the last; a parent’s press goes back to it with its By, All’s clears the drill, each a new entry', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, recipes, bikes, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await expect(dashboard.labels).toHaveText([bikes, recipes]);
    await expect(dashboard.pathSegments).toHaveText(['All']);
    await expect(dashboard.pathSegments).toHaveAttribute('aria-current', 'location');
    await expect(dashboard.tab).toHaveText('Project');
    const entries = await historyLength(page);

    await dashboard.row(recipes).click();

    await expect(dashboard.labels).toHaveText(['#2 Sort the spices', 'Project chat']);
    expect(stateOf(page)).toContain(`by=psession&m=cost.sum&dr=project:${recipeBox}@project&`);
    await expect(dashboard.pathKinds).toHaveText(['Project']);
    await expect(dashboard.pathValues).toHaveText([recipes]);
    await expect(dashboard.tab).toHaveText(recipes);
    expect(await historyLength(page)).toBe(entries + 1);
    const kind = dashboard.pathKinds.first();
    expect(Number.parseFloat(await kind.evaluate((element) => getComputedStyle(element).fontSize))).toBeLessThan(
      Number.parseFloat(await dashboard.pathValues.first().evaluate((element) => getComputedStyle(element).fontSize)),
    );

    await dashboard.row('#2 Sort the spices').click();

    await expect(dashboard.labels).toHaveText(['Turn 1 · brief', 'Turn 2 · continuation']);
    await expect(dashboard.allValues).toHaveText(['$0.86']);
    expect(stateOf(page)).toMatch(/&dr=psession:[^&]+@psession&/);
    await expect(dashboard.pathKinds).toHaveText(['Project', 'Pilot session']);
    await expect(dashboard.pathValues).toHaveText([recipes, '#2 Sort the spices']);
    await expect(dashboard.path).toHaveAttribute('title', `All › Project ${recipes} › Pilot session #2 Sort the spices`);
    await expect(dashboard.tab).toHaveText('#2 Sort the spices');

    await dashboard.pathSegments.nth(1).click();

    await expect(dashboard.labels).toHaveText(['#2 Sort the spices', 'Project chat']);
    expect(stateOf(page)).toContain(`by=psession&m=cost.sum&dr=project:${recipeBox}@project&`);
    expect(stateOf(page)).not.toContain('dr=psession');
    await expect(dashboard.pathValues).toHaveText([recipes]);

    await dashboard.pathSegments.first().click();

    await expect(dashboard.labels).toHaveText([bikes, recipes]);
    expect(stateOf(page)).not.toContain('dr=');
    expect(stateOf(page)).toContain('by=project&');
    await expect(dashboard.pathSegments).toHaveText(['All']);
    await expect(dashboard.tab).toHaveText('Project');
    expect(await historyLength(page)).toBe(entries + 4);

    await page.goBack();
    await expect(dashboard.pathValues).toHaveText([recipes]);
    await expect(dashboard.labels).toHaveText(['#2 Sort the spices', 'Project chat']);
  });

  test('a level opened cold is named by a lookup, in the path and on the tab', async ({ page, backendUrl, people, projects, collection, shell, dashboard }) => {
    const { recipeBox, recipes, chip } = await tally(people, projects, collection);
    const session = (await keysOf(page, backendUrl, 'psession', chip)).find((row) => row.label === '#2 Sort the spices')!.key;
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=pturn&m=cost.sum&dr=project:${recipeBox}@project&dr=psession:${session}@psession&${chip}`)}`);

    await expect(dashboard.labels).toHaveText(['Turn 1 · brief', 'Turn 2 · continuation']);
    await expect(dashboard.pathValues).toHaveText([recipes, '#2 Sort the spices']);
    await expect(dashboard.tab).toHaveText('#2 Sort the spices');
  });

  test('an attribute’s row keeps its value in a chip, the By back to the parts; a Call’s row drills into nothing', async ({ page, people, projects, collection, shell, dashboard }) => {
    const { recipeBox, recipes, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=source&m=cost.sum&${chip}`)}`);
    await expect(dashboard.row("Pilot's chats")).toHaveCount(1);

    await dashboard.row("Pilot's chats").click();

    await expect(dashboard.labels).toHaveText([recipes]);
    await expect(dashboard.allValues).toHaveText(['$0.25']);
    expect(stateOf(page)).toContain('by=project&');
    expect(stateOf(page)).toContain('&c=source:chat&');
    await expect(dashboard.chips.last()).toContainText("Source: Pilot's chats");
    await expect(dashboard.pathSegments).toHaveText(['All']);

    await dashboard.go(dashboardAddress(`t=all&by=call&m=cost.sum&${chip}`));
    await expect(dashboard.labels.first()).toHaveText('Call 1');
    await expect(dashboard.rows.first()).not.toHaveAttribute('role', 'button');
  });
});

test.describe('A filter’s chip', () => {
  test('names its values, cut before "n more", every value in its tooltip, at most 300 px wide; each named by a lookup', async ({ page, backendUrl, people, projects, collection, shell, dashboard }) => {
    const { recipeBox, recipes, bikes, chip } = await tally(people, projects, collection);
    const turns = await keysOf(page, backendUrl, 'pturn', chip);
    const pick = (label: string) => turns.find((turn) => turn.label === label)!.key;
    const four = [pick('Turn 2 · continuation'), pick('Turn 1 · person'), pick('Turn 2 · person'), turns[0].key];
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}&c=pturn:${four.join(',')}`)}`);
    await expect(dashboard.chips).toHaveCount(2);
    const [projectChip, turnChip] = [dashboard.chips.first(), dashboard.chips.last()];

    await expect(dashboard.chipWords(projectChip)).toContainText(recipes);
    await expect(dashboard.chipWords(projectChip)).toContainText(bikes);
    await expect(dashboard.chipWords(turnChip)).toHaveText('Pilot turn: Turn 2 · continuation, Turn 1 · person, 2 more');
    await expect(dashboard.chipWords(turnChip)).toHaveAttribute('title', /^Pilot turn: Turn 2 · continuation, Turn 1 · person, Turn 2 · person, Turn 1 · brief\n/);
    expect((await turnChip.boundingBox())!.width).toBeLessThanOrEqual(300);
    await expect(turnChip.getByTestId('dashboard.chip.kind')).toHaveAttribute('aria-label', /^Filters\./);
  });

  test('flips between a filter and a mark by its sign; its pane makes it Is not, only "is not" marked out; its × removes it, each a new entry', async ({ page, people, projects, collection, shell, dashboard }) => {
    const { recipeBox, recipes } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&c=project:${recipeBox}`)}`);
    await expect(dashboard.labels).toHaveText([recipes]);
    await expect(dashboard.chipWords(dashboard.chips)).toHaveText(`Project: ${recipes}`);
    await expect(dashboard.chips).toHaveClass(/\bfilter\b/);
    const entries = await historyLength(page);

    await dashboard.chips.getByTestId('dashboard.chip.kind').click();

    expect(stateOf(page)).toContain(`&c=~project:${recipeBox}&`);
    await expect(dashboard.chips).toHaveClass(/\bmark\b/);
    await expect(dashboard.row(`◇ ${recipes}`)).toHaveClass(/\bmarked\b/);
    expect(await dashboard.rows.count()).toBeGreaterThan(1);

    await dashboard.chips.getByTestId('dashboard.chip.kind').click();
    await expect(dashboard.chips).toHaveClass(/\bfilter\b/);
    await expect(dashboard.labels).toHaveText([recipes]);

    await dashboard.chipWords(dashboard.chips).click();
    await expect(dashboard.paneValue(recipes).getByRole('checkbox')).toBeChecked();
    await dashboard.paneIsNot.click();
    await dashboard.paneApply.click();

    expect(stateOf(page)).toContain(`&c=!project:${recipeBox}&`);
    await expect(dashboard.pane).toHaveCount(0);
    await expect(dashboard.chipWords(dashboard.chips)).toHaveText(`Project is not: ${recipes}`);
    const not = dashboard.chips.getByTestId('dashboard.chip.not');
    await expect(not).toHaveText('is not');
    expect(await not.evaluate((element) => getComputedStyle(element).fontWeight)).toBe('700');
    expect(await dashboard.chips.locator('.on').evaluate((element) => getComputedStyle(element).fontWeight)).not.toBe('700');
    await expect(dashboard.row(recipes)).toHaveCount(0);

    await dashboard.chips.getByTestId('dashboard.chip.remove').click();

    await expect(dashboard.chips).toHaveCount(0);
    expect(stateOf(page)).not.toContain('c=');
    expect(await historyLength(page)).toBe(entries + 4);
  });

  test('the picker lists the parts and the attributes and no time; a dimension’s pane its values in scope, searched, and adds a chip of those picked', async ({ page, people, projects, collection, shell, dashboard }) => {
    const { recipeBox, recipes, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await expect(dashboard.rows).toHaveCount(2);
    const entries = await historyLength(page);

    await dashboard.addFilter.click();

    // The tally declares one kind of work, the errand: a scenario loaded before it on the same
    // worker's record can leave its own kinds among the parts, so the parts are read as a subset.
    await expect(dashboard.filterGroup('Parts')).toContainText(['Project', 'Pilot session', 'Pilot turn', 'Sitting', 'Conversation', 'Call', 'Work unit', 'Errand']);
    await expect(dashboard.filterGroup('Attributes')).toContainText(['Source', 'Work type', 'Model']);
    for (const time of ['Quota week', 'Day', 'Weekday', 'Hour of day', 'Pilot session, in the order created']) {
      await expect(dashboard.filterDimensions.getByText(time, { exact: true })).toHaveCount(0);
    }

    await dashboard.filterGroup('Parts').getByText('Pilot session', { exact: true }).click();

    await expect(dashboard.paneLabels).toHaveText(['#2 Tidy the ride notes', '#2 Sort the spices', 'Project chat']);
    await expect(dashboard.paneAmounts).toHaveText(['$1.18 · 3', '$0.86 · 10', '$0.25 · 3']);
    await dashboard.paneSearch.fill('spices');
    await expect(dashboard.paneLabels).toHaveText(['#2 Sort the spices']);
    await dashboard.paneValue('#2 Sort the spices').getByRole('checkbox').check();
    await dashboard.paneApply.click();

    await expect(dashboard.labels).toHaveText([recipes]);
    await expect(dashboard.allValues).toHaveText(['$0.86']);
    expect(stateOf(page)).toMatch(/&c=psession:[^&]+&/);
    await expect(dashboard.chipWords(dashboard.chips.last())).toHaveText('Pilot session: #2 Sort the spices');
    expect(await historyLength(page)).toBe(entries + 1);
  });

  test('Esc in a dimension’s pane, its search focused as it opens, clears what is typed, then closes the pane, a chip’s pane too', async ({ people, projects, collection, shell, dashboard }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await expect(dashboard.rows).toHaveCount(2);
    await dashboard.addFilter.click();
    await dashboard.filterGroup('Parts').getByText('Pilot session', { exact: true }).click();
    await expect(dashboard.paneSearch).toBeFocused();
    await dashboard.paneSearch.fill('spices');
    await expect(dashboard.paneLabels).toHaveText(['#2 Sort the spices']);

    await dashboard.paneSearch.press('Escape');

    await expect(dashboard.paneSearch).toHaveValue('');
    await expect(dashboard.paneLabels).toHaveCount(3);
    await dashboard.paneSearch.press('Escape');
    await expect(dashboard.pane).toHaveCount(0);

    await dashboard.chipWords(dashboard.chips.first()).click();
    await expect(dashboard.paneSearch).toBeFocused();
    await dashboard.paneSearch.press('Escape');
    await expect(dashboard.pane).toHaveCount(0);
    await expect(dashboard.chips).toHaveCount(1);
  });
});

