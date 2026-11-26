/**
 * Save view and Reset, the global toolbar's two that are the tab's (F161.5, F162.1), with no
 * Refresh (F160.7): Save view asks a name, for everyone, and the tab takes it, the state kept whole,
 * its look-only parts with it; a saved view's name taken is replaced, a system view's has the saved
 * view stand beside it, the pane saying which (R40); Reset puts the tab back to what it opened with,
 * there to press only where the tab differs from it. A save that fails shows in the banner alone.
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { expectConsoleError, makeUnique } from '../support/helpers';
import { dashboardAddress, type DashboardPage } from '../support/page-objects/dashboard-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';

const SCRATCH = 't=qw&by=project&m=cost.sum&col=none';
const BY_MODEL = 't=qw&by=model&m=cost.sum&col=none';
/** A view with an open drawer, Relative and a zoom: look-only parts, which no answer reads. */
const LOOKING = 't=all&by=project&m=cost.sum&col=none&d=items&rel=1&z=1763600000,1763686400.5';
const SYSTEM_VIEW = 'Work types';

const historyLength = (page: Page) => page.evaluate(() => history.length);
const toast = (page: Page) => page.getByTestId('app-shell.toast.item');
const open = (dashboard: DashboardPage, list: Locator, name: string) => dashboard.view(list, name).getByTestId('dashboard.panel.view.open').click();

async function aProject(people: People, projects: Projects) {
  const me = await people.signIn();
  return projects.make({ name: makeUnique('Save'), members: [me.handle!] });
}

test.describe('Save view and Reset', () => {
  test('Save view asks a name, for everyone, and the tab takes it, the state kept whole, its drawer, Relative and zoom with it; Reset is there to press only where the tab differs from what it opened with, its press a new entry', async ({
    page,
    people,
    projects,
    shell,
    dashboard,
    savedViews,
  }) => {
    const project = await aProject(people, projects);
    const name = makeUnique('Kept');
    await shell.open(`${projectAddress(project)}${dashboardAddress(LOOKING, 'look')}`);
    await expect(dashboard.byHeading).toHaveText('Project');
    // The tab's close, the time, Reset, Save view, copy-plus.
    await expect(dashboard.toolbar.getByRole('button')).toHaveText(['', 'All time', 'Reset', 'Save view', '']);
    await expect(dashboard.toolbar.getByRole('button', { name: /refresh/i })).toHaveCount(0);
    await expect(dashboard.reset).toBeDisabled();

    await dashboard.saveView.click();
    await expect(dashboard.saveName).toBeFocused();
    await expect(dashboard.saveName).toHaveValue('');
    await expect(dashboard.save).toBeDisabled();
    await dashboard.saveName.fill(name);
    await expect(dashboard.saveNote).toHaveCount(0);
    await dashboard.save.click();
    await expect(toast(page)).toContainText(`Saved the view "${name}" for everyone`);
    await expect(dashboard.savePane).toHaveCount(0);
    await expect(dashboard.tab).toHaveText(name);
    const [saved] = await savedViews.named(name);
    expect(saved.address.slice('#dash/'.length).split('&')).toEqual(expect.arrayContaining(['d=items', 'rel=1', 'z=1763600000,1763686400.5']));
    await expect(dashboard.reset).toBeDisabled();

    const entries = await historyLength(page);
    await dashboard.go(dashboardAddress(BY_MODEL, 'look'));
    await expect(dashboard.byHeading).toHaveText('Model');
    await expect(dashboard.tab).toHaveText(name);
    await expect(dashboard.reset).toBeEnabled();
    await dashboard.reset.click();
    await expect(dashboard.byHeading).toHaveText('Project');
    await expect(page).toHaveURL(`${projectAddress(project)}#dash/look/${saved.address.slice('#dash/'.length)}`);
    await expect(dashboard.reset).toBeDisabled();
    expect(await historyLength(page)).toBe(entries + 2);

    await page.goBack();
    await expect(dashboard.byHeading).toHaveText('Model');
    await expect(dashboard.tab).toHaveText(name);
    await expect(dashboard.reset).toBeEnabled();
  });

  test('replaces the saved view of a name taken, the pane saying so; from a tab a system view opened it saves a view beside it under that name, the field holding the name and the pane saying so', async ({
    page,
    people,
    projects,
    shell,
    dashboard,
    savedViews,
  }) => {
    const project = await aProject(people, projects);
    const name = makeUnique('Taken');
    await savedViews.save(name, BY_MODEL);
    // Every spec of a worker shares its record: a saved view under the system view's name is this spec's alone.
    const forget = async () => {
      for (const view of await savedViews.named(SYSTEM_VIEW)) await savedViews.remove(view.id);
    };
    await forget();
    try {
      await shell.open(`${projectAddress(project)}${dashboardAddress(SCRATCH)}`);
      await expect(dashboard.byHeading).toHaveText('Project');
      await dashboard.saveView.click();
      await dashboard.saveName.fill(name);
      await expect(dashboard.saveNote).toHaveText(`Replaces the saved view "${name}".`);
      await dashboard.saveName.press('Enter');
      await expect(toast(page)).toContainText(`Replaced the saved view "${name}" for everyone`);
      const replaced = await savedViews.named(name);
      expect(replaced).toHaveLength(1);
      expect(replaced[0].address).toContain('by=project');
      await expect(dashboard.tab).toHaveText(name);

      await dashboard.newView.click();
      await open(dashboard, dashboard.systemViews, SYSTEM_VIEW);
      await expect(dashboard.lineNames).toHaveText([name, SYSTEM_VIEW]);
      await dashboard.saveView.click();
      await expect(dashboard.saveName).toHaveValue(SYSTEM_VIEW);
      await expect(dashboard.saveNote).toHaveText('A system view has this name: yours is saved beside it, in Saved views.');
      await dashboard.save.click();
      await expect(toast(page).last()).toContainText(`Saved the view "${SYSTEM_VIEW}" for everyone`);
      expect(await savedViews.named(SYSTEM_VIEW)).toHaveLength(1);
      await expect(dashboard.lineNames).toHaveText([name, SYSTEM_VIEW]);

      await dashboard.newView.click();
      await expect(dashboard.view(dashboard.systemViews, SYSTEM_VIEW)).toBeVisible();
      await expect(dashboard.view(dashboard.savedViews, SYSTEM_VIEW)).toBeVisible();
    } finally {
      await forget();
    }
  });

  test('fails a save into the banner alone, with no toast, the pane staying open', async ({ page, people, projects, shell, dashboard }) => {
    const project = await aProject(people, projects);
    await expectConsoleError(page, /400/);
    await shell.open(`${projectAddress(project)}${dashboardAddress('t=qw&by=projekt&m=cost.sum&col=none')}`);
    await expect(dashboard.bannerText).toContainText('"projekt" is no dimension');
    await dashboard.closeBanner.click();
    await expect(dashboard.banner).toHaveCount(0);

    await dashboard.saveView.click();
    await dashboard.saveName.fill(makeUnique('Refused'));
    await dashboard.save.click();
    await expect(dashboard.bannerText).toContainText('"projekt" is no dimension');
    await expect(dashboard.retry).toHaveCount(0);
    await expect(toast(page)).toHaveCount(0);
    await expect(dashboard.savePane).toBeVisible();
  });
});
