/**
 * What failed is a banner under the global toolbar (F160.8): a refusal of the engine's shows its
 * reason there, with Retry, the previous answer staying drawn; the banner closes, and a read that
 * goes well takes it away.
 */

import { test, expect } from '../support/fixtures';
import { expectConsoleError, makeUnique } from '../support/helpers';
import { dashboardAddress } from '../support/page-objects/dashboard-page';
import { projectAddress } from '../support/projects';

test.describe('The dashboard’s banner', () => {
  test('shows a refusal’s reason under the toolbar, the previous answer staying drawn; Retry asks again, and the banner closes', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const me = await people.signIn();
    const recipeBox = await projects.make({ name: makeUnique('Recipes'), members: [me.handle!] });
    const bikeLog = await projects.make({ name: makeUnique('Bikes'), members: [me.handle!] });
    await collection.loadScenario('tally', { 'recipe-box': recipeBox, 'bike-log': bikeLog });
    const chip = `c=project:${recipeBox},${bikeLog}`;
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await expect(dashboard.rows).toHaveCount(2);
    await expect(dashboard.banner).toHaveCount(0);
    await expectConsoleError(page, /400/);
    const refused = `t=all&by=projekt&m=cost.sum&${chip}`;
    const reads = dashboard.addressReads();

    await dashboard.go(dashboardAddress(refused));

    await expect(dashboard.bannerText).toContainText('- by=projekt: "projekt" is no dimension. Did you mean "project"?');
    await expect(dashboard.toolbar.locator('xpath=following-sibling::*[1]')).toHaveAttribute('data-testid', 'dashboard.banner');
    await expect(dashboard.rows).toHaveCount(2);
    await expect(dashboard.allValues).toHaveText(['$2.29']);
    expect(reads()).toEqual([refused]);

    await dashboard.retry.click();
    await expect.poll(() => reads()).toEqual([refused, refused]);
    await expect(dashboard.bannerText).toContainText('"projekt" is no dimension');

    await dashboard.closeBanner.click();
    await expect(dashboard.banner).toHaveCount(0);
    await expect(dashboard.rows).toHaveCount(2);
  });
});
