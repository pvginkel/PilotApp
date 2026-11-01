/**
 * The store's update (F144.2, F144.4): while it holds, a job of Pilot's placed is held, its line and
 * its session log "Waiting for Pilot’s update", and goes on at the update's lift; a job running when
 * the update is made is stopped by Pilot, its line "Stopped for Pilot’s update · <time>" and its
 * session log's tail "Stopped by Pilot for its update · <time>", and at the lift the server retries
 * it, the line saying so, the retry running below it (F144.3). Each job runs in the store, which the
 * update resets: the spec puts back what its tree held before the lift releases a start there.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { Projects } from '../support/projects';
import { TICKS_MS } from '../support/store-update';

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));

const QUESTION = '```question id=Q1\n```\n';

/** Pilot's question in the project, answered: answers the job its close placed. */
async function answered(projects: Projects, project: string): Promise<string> {
  const question = await projects.place(project, { kind: 'question', title: 'Which lake?', text: QUESTION, by_pilot: true });
  await projects.answer(question, 'Q1', 'Lake Como');
  let job: string | undefined;
  await expect
    .poll(async () => {
      job = (await projects.timeline(project)).items.find((item) => item.work?.pilots_own)?.id;
      return job;
    })
    .toBeDefined();
  return job!;
}

test.describe('The store’s update', () => {
  test('holds a job of Pilot’s placed while it stands, its line and its log saying so, and lets it go on at its lift', async ({
    people,
    projects,
    chats,
    storeUpdate,
    timeline,
    sessionLog,
    page,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Held'), members: [me.handle!] });
    await storeUpdate.make();
    await timeline.open(project);

    const jobId = await answered(projects, project);
    expect(await projects.work(project, jobId)).toMatchObject({ state: 'held', held_reason: 'store_update' });
    const job = timeline.item(jobId).work;
    await expect(job.line).toHaveAttribute('data-state', 'held');
    await expect(job.cue).toHaveText('Waiting for Pilot’s update');
    await job.sessionLog.click();
    await expect(sessionLog.cue).toHaveText('Waiting for Pilot’s update');
    await page.keyboard.press('Escape');

    await storeUpdate.reset();
    await chats.ready(project);
    await storeUpdate.lift();
    await expect(job.running).toBeVisible();
    await expect(job.cue).not.toHaveText('Waiting for Pilot’s update');
  });

  test('stops a job of Pilot’s running when it is made, by Pilot, its line and its log’s tail saying so, and at its lift retries it as a new job below', async ({
    people,
    projects,
    chats,
    storeUpdate,
    timeline,
    sessionLog,
    deploymentSse,
    page,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Stopped'), members: [me.handle!] });
    await chats.ready(project);
    const jobId = await answered(projects, project);
    await expect.poll(async () => (await projects.work(project, jobId)).state).toBe('running');
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const job = timeline.item(jobId).work;
    await expect(job.running).toBeVisible();

    await storeUpdate.make();
    // The server takes the update up at its timer's next tick.
    await expect(job.line).toHaveAttribute('data-state', 'stopped', { timeout: TICKS_MS });
    const stopped = await projects.work(project, jobId);
    expect(stopped.stopped_by?.kind).toBe('agent');
    const at = clock(stopped.stopped_at!);
    await expect(job.line).toHaveText(`Stopped for Pilot’s update · ${at}`);
    await job.sessionLog.click();
    await expect(sessionLog.tail).toHaveText(`Stopped by Pilot for its update · ${at}`);
    await expect(sessionLog.tail).toHaveAttribute('data-mark', 'stopped');
    await page.keyboard.press('Escape');

    await storeUpdate.reset();
    await chats.ready(project);
    await storeUpdate.lift();
    await expect(job.retried).toContainText('Retried as a new job below');
    await expect(job.line).toHaveText(`Stopped for Pilot’s update · ${at}`);
    const retryId = (await projects.timeline(project)).items.find((item) => item.work?.pilots_own && item.id !== jobId)!.id;
    const retry = timeline.item(retryId).work;
    await expect(retry.running).toBeVisible();
    await expect(retry.retried).toHaveCount(0);
  });
});
