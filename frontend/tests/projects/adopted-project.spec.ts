/**
 * An adopted project (F152.8, F128.2): the project Pilot makes for a group of work done before it,
 * the first time a conversation's publication names the group. It is archived from its birth, so it
 * is listed with the archived projects, its row reading "Adopted" where an archived project has its
 * status, on a desk and on a phone; and it is never brought back, so its head has no menu. The
 * scenario's load publishes the conversations, one of which names the group.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

const PHONE = { width: 390, height: 844 };

test.describe('An adopted project', () => {
  test('is listed with the archived projects, its row reading “Adopted”, and its head has no menu', async ({
    people,
    projects,
    collection,
    projectList,
    projectHead,
  }) => {
    const me = await people.signIn();
    await people.serviceUser();
    const recipeBox = await projects.make({ name: makeUnique('Recipe box'), members: [me.handle!] });
    const [halving, counting, gears] = await collection.loadScenario('supper', { 'recipe-box': recipeBox });
    expect([halving.adopted_by, counting.adopted_by]).toEqual([null, null]);
    const adopted = gears.adopted_by!;
    await projectList.open(recipeBox);
    await expect(projectList.tab(adopted.name)).toHaveCount(0);

    await projectList.menuButton.click();
    await projectList.archivedItem.click();

    const row = projectList.tab(adopted.name, projectList.archived);
    await expect(row).toHaveCount(1);
    await expect(row.getByTestId('projects.tab.status')).toHaveText('Adopted');

    await row.click();
    await expect(projectHead.name).toHaveText(adopted.name);
    await expect(projectHead.archived).toHaveText('Archived');
    await expect(projectHead.menuButton).toHaveCount(0);
    expect((await projects.head(adopted.id)).state).toBe('adopted');
  });

  test('a second load finds the group’s project again: the Archived list holds it once', async ({ people, projects, collection, projectList }) => {
    const me = await people.signIn();
    await people.serviceUser();
    const recipeBox = await projects.make({ name: makeUnique('Recipe box'), members: [me.handle!] });
    const first = (await collection.loadScenario('supper', { 'recipe-box': recipeBox }))[2].adopted_by!;

    const second = (await collection.loadScenario('supper', { 'recipe-box': recipeBox }))[2].adopted_by!;

    expect(second).toEqual(first);
    await projectList.open(recipeBox);
    await projectList.menuButton.click();
    await projectList.archivedItem.click();
    await expect(projectList.tab(first.name, projectList.archived)).toHaveCount(1);
  });

  test.describe('on a phone', () => {
    test.use({ viewport: PHONE, hasTouch: true });

    test('is a row of the Archived view reading “Adopted”, and its head has no menu', async ({
      people,
      projects,
      collection,
      projectList,
      projectHead,
      shell,
    }) => {
      const me = await people.signIn();
      await people.serviceUser();
      const recipeBox = await projects.make({ name: makeUnique('Recipe box'), members: [me.handle!] });
      const adopted = (await collection.loadScenario('supper', { 'recipe-box': recipeBox }))[2].adopted_by!;
      await shell.open('/');
      await expect(projectList.tab(adopted.name)).toHaveCount(0);

      await projectList.menuButton.tap();
      await projectList.archivedItem.tap();

      const row = projectList.tab(adopted.name, projectList.archived);
      await expect(row).toHaveCount(1);
      await expect(row.getByTestId('projects.tab.status')).toHaveText('Adopted');

      await row.tap();
      await expect(projectHead.name).toHaveText(adopted.name);
      await expect(projectHead.archived).toBeVisible();
      await expect(projectHead.menuButton).toHaveCount(0);
    });
  });
});
