/**
 * The tally (F122.2): the scenario for exact figures, loaded on a spec's two projects, answers the
 * dashboard's figures the screen's specs assert, whatever else the worker's database holds, the seed's
 * history among it; and a walk after its load sends its event, one with nothing published since
 * none.
 */

import { test, expect } from '../support/fixtures';
import { TALLY } from '../support/collection';
import { makeUnique } from '../support/helpers';

test.describe('The tally', () => {
  test('answers its figures on its two projects alone, by project', async ({ page, backendUrl, people, projects, collection }) => {
    const me = await people.signIn();
    const recipeBox = await projects.make({ name: makeUnique('Recipes'), members: [me.handle!] });
    const bikeLog = await projects.make({ name: makeUnique('Bikes'), members: [me.handle!] });

    const threads = await collection.loadScenario('tally', { 'recipe-box': recipeBox, 'bike-log': bikeLog });

    expect(threads.map((thread) => thread.adopted_by)).toEqual([null, null, null, null]);
    const state = `t=all&by=project&m=cost.sum&m=calls.count&m=turns.count&c=project:${recipeBox},${bikeLog}`;
    const response = await page.request.get(`${backendUrl}/api/dashboard/rows`, { params: { state } });
    expect(response.status(), await response.text()).toBe(200);
    const rows = (await response.json()) as { all: { values: number[] }; rows: { key: string; values: number[] }[] };
    expect(rows.all.values).toEqual([TALLY.cost, TALLY.calls, TALLY.turns]);
    expect(Object.fromEntries(rows.rows.map((row) => [row.key, row.values]))).toEqual({
      [recipeBox]: TALLY.recipeBox,
      [bikeLog]: TALLY.bikeLog,
    });
  });

  test('a walk after its load sends the walk’s event, and the next one none', async ({ people, projects, collection }) => {
    const me = await people.signIn();
    const recipeBox = await projects.make({ name: makeUnique('Recipes'), members: [me.handle!] });
    const bikeLog = await projects.make({ name: makeUnique('Bikes'), members: [me.handle!] });
    await collection.loadScenario('tally', { 'recipe-box': recipeBox, 'bike-log': bikeLog });

    expect((await collection.walk()).announced).toBe(true);
    expect((await collection.walk()).announced).toBe(false);
  });
});
