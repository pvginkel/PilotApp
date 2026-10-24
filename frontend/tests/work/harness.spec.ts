/**
 * The work items' harness (design 2 §12): the worker's backend drives a fake controller of its
 * own, in whose environments a spec starts work items through the record's testing route and plays
 * their turns, and which it makes unreachable and answering again.
 */

import { test, expect } from '../support/fixtures';
import { rawTurn } from '../support/controller';
import { makeUnique } from '../support/helpers';

const BRIEF = 'Rename the badge.';

test.describe('The fake controller', () => {
  test('a work item started in its environment runs its turn to its end', async ({ people, projects, controller, conditions }) => {
    expect(await conditions.read()).toEqual([]);
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Harness'), members: [me.handle!] });
    const environment = await controller.environment();

    const work = await projects.startWork(id, { environment_id: environment, title: 'Renaming the badge', brief: BRIEF, cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(id, work)).state).toBe('running');
    expect((await projects.work(id, work)).environment).toEqual({ id: environment, name: environment });

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

  test('the controller unreachable holds a start, and it runs once the controller answers again', async ({
    people,
    projects,
    controller,
    conditions,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Outage'), members: [me.handle!] });
    const environment = await controller.environment();

    await controller.outage(true, 'ingress');
    expect((await conditions.read()).map((condition) => condition.code)).toEqual(['outage']);
    const work = await projects.startWork(id, { environment_id: environment, title: 'Renaming the badge', brief: BRIEF, cwd: '/work/Example' });
    const held = await projects.work(id, work);
    expect(held.state).toBe('held');
    expect(held.held_reason).toBe('controller_unreachable');

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
