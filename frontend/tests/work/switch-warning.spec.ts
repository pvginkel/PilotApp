/**
 * The switch's warning triangle (F4.3): beside auto pilot's switch while a work item runs, starts or
 * waits at the gate that its start briefed under the other setting, its hover saying the change
 * applies to work started from now on and a running session keeps its grants; gone once no such
 * work item runs: the switch back, the turn ended, the session stopped.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

const WARNING = 'The change applies to work started from now on: a running session keeps the grants it was briefed with';
const WORK = { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' };

test.describe('The switch’s warning triangle', () => {
  test('stands while a running work item was briefed under the other setting, and goes with the switch back and at the turn’s end', async ({
    people,
    projects,
    controller,
    projectHead,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Briefed'), members: [me.handle!] });
    const work = await projects.startWork(project, WORK);
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
    const environment = await projects.environment(project, work);
    expect((await projects.work(project, work)).autopilot).toBe(false);
    await projectHead.open(project);
    await expect(projectHead.autopilotWarning).toHaveCount(0);

    await projectHead.autopilot.click();
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');
    await expect(projectHead.autopilotWarning).toBeVisible();
    await expect(projectHead.autopilotWarning).toHaveAttribute('title', WARNING);
    await expect(projectHead.autopilotWarning).toHaveAttribute('aria-label', WARNING);

    await projectHead.autopilot.click();
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');
    await expect(projectHead.autopilotWarning).toHaveCount(0);

    await projectHead.autopilot.click();
    await expect(projectHead.autopilotWarning).toBeVisible();
    // The turn ends: the item is done, and nothing briefed otherwise runs.
    await controller.finish(environment.id, 'claude-1');
    await expect(projectHead.autopilotWarning).toHaveCount(0);
  });

  test('a start held at the gate counts, and the triangle goes once it is stopped', async ({ people, projects, projectHead }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Held'), members: [me.handle!], autopilot: true, paused: true });
    const work = await projects.startWork(project, WORK);
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('held');
    await projectHead.open(project);
    await expect(projectHead.autopilotWarning).toHaveCount(0);

    await projectHead.autopilot.click();
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');
    await expect(projectHead.autopilotWarning).toBeVisible();

    await projects.stop(work);
    await expect(projectHead.autopilotWarning).toHaveCount(0);
  });
});
