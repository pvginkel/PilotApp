/**
 * A usage halt's hard stop (F135.6): the suite's backends give the five-hour halt the hard stop
 * (tests/support/backend-env-extensions.ts). When it holds, every running work item is stopped as
 * Stop stops one, by Pilot: its line "Stopped at the five-hour limit · <time>", or the week's once
 * the week's halt holds too, the halt read at display, the week's first, "the usage limit" once
 * neither does; its session log's tail "Stopped by Pilot at the usage limit · <time>"; Resume in
 * Stop's place; and it waits on nobody, so no badge counts it (DB 225, 269). Its nudge carries it on
 * once nothing holds it, its project's pause among what does (DB 232).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));

test.describe('The hard stop', () => {
  test('stops a running work item by Pilot, its line naming the halt that holds, its tail Pilot at the usage limit, waiting on nobody, until its nudge', async ({
    people,
    projects,
    controller,
    timeline,
    sessionLog,
    projectList,
    deploymentSse,
    page,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Hard stop');
    const project = await projects.make({ name, members: [me.handle!] });
    const work = await projects.startWork(project, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;
    await expect(item.running).toBeVisible();

    await controller.usage({ seven_day: 0.5, five_hour: 0.8 });

    await expect(item.line).toHaveAttribute('data-state', 'stopped');
    const stopped = await projects.work(project, work);
    expect(stopped.stopped_by?.kind).toBe('agent');
    const at = clock(stopped.stopped_at!);
    await expect(item.line).toHaveText(`Stopped at the five-hour limit · ${at}`);
    await expect(item.stop).toHaveCount(0);
    await expect(item.resume).toHaveText('Resume');
    await expect(projectList.badge(name)).toHaveCount(0);

    await item.sessionLog.click();
    await expect(sessionLog.tail).toHaveText(`Stopped by Pilot at the usage limit · ${at}`);
    await expect(sessionLog.tail).toHaveAttribute('data-mark', 'stopped');
    await page.keyboard.press('Escape');

    // The week's halt holds too: the line names it, the week's first.
    await controller.usage({ seven_day: 0.92, five_hour: 0.8 });
    await expect(item.line).toHaveText(`Stopped at the week’s limit · ${at}`);

    // Neither halt holds, and the project's pause holds its nudge.
    await projects.transition(project, 'paused');
    await controller.usage({ seven_day: 0.5, five_hour: 0.1 });
    await expect(item.line).toHaveText(`Stopped at the usage limit · ${at}`);
    await expect(projectList.badge(name)).toHaveCount(0);

    // Nothing holds it: its nudge carries it on.
    await projects.transition(project, 'resumed');
    await expect(item.running).toBeVisible();
    await expect(item.stop).toBeVisible();
    await expect(item.resume).toHaveCount(0);
  });
});
