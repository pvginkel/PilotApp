/**
 * The work items' harness (design 2 §12): the worker's backend drives a fake controller of its
 * own, from which a spec's work items, placed by repository through the record's testing route,
 * get environments of Pilot's own, created or taken, and in which it plays their turns, and which
 * it makes unreachable and answering again.
 */

import { test, expect } from '../support/fixtures';
import { rawTurn } from '../support/controller';
import { makeUnique } from '../support/helpers';
import { slugOf } from '../support/projects';

const BRIEF = 'Rename the badge.';
const WORK = { title: 'Renaming the badge', brief: BRIEF, cwd: '/work/Example' };
// Two of the backend's scheduler ticks (SCHEDULER_TICK_SECONDS, 10 s), past the expect timeout's one.
const RELEASE_TIMEOUT_MS = 20_000;

test.describe('The fake controller', () => {
  test('a work item runs its turn to its end in the environment its start created, named after its project', async ({
    people,
    projects,
    controller,
    conditions,
  }) => {
    expect(await conditions.read()).toEqual([]);
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Harness'), members: [me.handle!] });

    const work = await projects.startWork(id, WORK);
    await expect.poll(async () => (await projects.work(id, work)).state).toBe('running');
    const { id: environment, name } = await projects.environment(id, work);
    expect(name).toBe(slugOf(id));

    const lines = rawTurn('turn_text');
    await controller.play(environment, 'claude-1', lines);
    await controller.finish(environment, 'claude-1');
    await expect.poll(async () => (await projects.item(id, work)).done?.cause).toBe('turn_ended');
    expect((await projects.work(id, work)).state).toBe('idle');

    const { records } = await projects.records(work);
    // A stream_event line is a partial, never a record.
    const printed = lines.filter((line) => (JSON.parse(line) as { type: string }).type !== 'stream_event');
    expect(records.filter((record) => record.kind === 'claude')).toHaveLength(printed.length);
    expect(records.at(-1)?.kind).toBe('result');
  });

  test('a work item of the repository takes the environment another one’s end freed, named after its own project', async ({
    people,
    projects,
    controller,
  }) => {
    const me = await people.signIn();
    const first = await projects.make({ name: makeUnique('Freed'), members: [me.handle!] });
    // Held until its row is in, so that the fleet stream reports it `running`: the fake's create
    // settles within its answer otherwise, before Pilot has a row the report could update.
    await controller.settleCreates(null);
    const done = await projects.startWork(first, WORK);
    const { id: environment } = await projects.environment(first, done);
    await controller.settleCreates('running');
    await controller.settleStarts(environment, 'running');
    await controller.setStatus(environment, 'running');
    await expect.poll(async () => (await projects.work(first, done)).state).toBe('running');
    await controller.finish(environment, 'claude-1');
    await expect.poll(async () => (await projects.item(first, done)).done?.cause).toBe('turn_ended');
    // The delete timer's next tick releases the freed environment, its name cleared, under its
    // row's lock, which a take passes over to create instead: the start waits for the release.
    await expect
      .poll(async () => (await projects.work(first, done)).environment, { timeout: RELEASE_TIMEOUT_MS })
      .toEqual({ id: environment, name: environment });

    const second = await projects.make({ name: makeUnique('Taking'), members: [me.handle!] });
    const work = await projects.startWork(second, WORK);
    await expect.poll(async () => (await projects.work(second, work)).state).toBe('running');
    const taken = { id: environment, name: slugOf(second) };
    expect((await projects.work(second, work)).environment).toEqual(taken);
    // The done item names its environment as its row stands.
    expect((await projects.work(first, done)).environment).toEqual(taken);
  });

  test('the controller unreachable holds a start, and it runs once the controller answers again', async ({
    people,
    projects,
    controller,
    conditions,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Outage'), members: [me.handle!] });

    await controller.outage(true, 'ingress');
    expect((await conditions.read()).map((condition) => condition.code)).toEqual(['outage']);
    const work = await projects.startWork(id, WORK);
    const held = await projects.work(id, work);
    expect(held.state).toBe('held');
    expect(held.held_reason).toBe('controller_unreachable');
    // Held before its take, it has no environment yet.
    expect(held.environment).toBeNull();

    await controller.outage(false);
    await expect.poll(async () => (await projects.work(id, work)).state).toBe('running');
  });
});

test.describe('The fake controller, its streams dropped', () => {
  test.describe.configure({ mode: 'serial' });

  test('a spec that drops every stream goes on with the controller answering', async ({ controller, conditions }) => {
    await controller.dropStreams();
    expect(await conditions.read()).toEqual([]);
  });

  test('the next spec starts with the controller answering', async ({ conditions }) => {
    expect(await conditions.read()).toEqual([]);
  });
});
