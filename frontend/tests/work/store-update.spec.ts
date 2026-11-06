/**
 * The store's update (F144.2, F144.4): while it holds, a job of Pilot's placed is held, its button on
 * the item it follows from says so in its state, and its session log "Waiting for Pilot’s update",
 * and goes on at the update's lift; a job running when the update is made is stopped by Pilot, its
 * button stopped and its session log's tail "Stopped by Pilot for its update · <time>", and at the
 * lift the server retries it, the item showing the retry, running, in its place (F144.3, F59.1).
 * Each job runs in the store, which the update resets: the spec puts back what its tree held before
 * the lift releases a start there.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { sessionLogAddress } from '../support/page-objects/session-log-page';
import type { Projects } from '../support/projects';
import { TICKS_MS } from '../support/store-update';

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));

const QUESTION = '```question id=Q1\n```\n';

/** Pilot's question in the project, answered: the question, and the job its close placed. */
async function answered(projects: Projects, project: string): Promise<{ question: string; job: string }> {
  const question = await projects.place(project, { kind: 'question', title: 'Which lake?', text: QUESTION, by_pilot: true });
  await projects.answer(question, 'Q1', 'Lake Como');
  let job: string | undefined;
  await expect
    .poll(async () => {
      job = (await projects.timeline(project)).items.find((item) => item.work?.pilots_own)?.id;
      return job;
    })
    .toBeDefined();
  return { question, job: job! };
}

test.describe('The store’s update', () => {
  test('holds a job of Pilot’s placed while it stands, its button and its log saying so, and lets it go on at its lift', async ({
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

    const { question, job: jobId } = await answered(projects, project);
    expect(await projects.work(project, jobId)).toMatchObject({ state: 'held', held_reason: 'store_update' });
    const job = timeline.item(question).job;
    await expect(job.root).toHaveAttribute('data-state', 'held');
    await expect(job.root).toHaveAttribute('data-form', 'running');
    await job.root.click();
    await expect(sessionLog.cue).toHaveText('Waiting for Pilot’s update');
    await page.keyboard.press('Escape');

    await storeUpdate.reset();
    await chats.ready(project);
    await storeUpdate.lift();
    await expect(job.root).toHaveAttribute('data-state', 'running');
  });

  test('stops a job of Pilot’s running when it is made, by Pilot, its button and its log’s tail saying so, and at its lift retries it, the retry in its place', async ({
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
    const { question, job: jobId } = await answered(projects, project);
    await expect.poll(async () => (await projects.work(project, jobId)).state).toBe('running');
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const job = timeline.item(question).job;
    await expect(job.root).toHaveAttribute('data-state', 'running');

    await storeUpdate.make();
    // The server takes the update up at its timer's next tick.
    await expect(job.root).toHaveAttribute('data-state', 'stopped', { timeout: TICKS_MS });
    const stopped = await projects.work(project, jobId);
    expect(stopped.stopped_by?.kind).toBe('agent');
    const at = clock(stopped.stopped_at!);
    await expect(job.root).toHaveAttribute('data-form', 'stopped');
    await expect(job.root).toHaveText('Deciding what is next · Stopped');
    await job.root.click();
    await expect(sessionLog.tail).toHaveText(`Stopped by Pilot for its update · ${at}`);
    await expect(sessionLog.tail).toHaveAttribute('data-mark', 'stopped');
    await page.keyboard.press('Escape');

    await storeUpdate.reset();
    await chats.ready(project);
    await storeUpdate.lift();
    let retryId: string | undefined;
    await expect
      .poll(async () => {
        retryId = (await projects.timeline(project)).items.find((item) => item.work?.pilots_own && item.id !== jobId)?.id;
        return retryId;
      })
      .toBeDefined();
    await expect(job.root).toHaveAttribute('href', sessionLogAddress(project, retryId!));
    await expect(job.root).toHaveAttribute('data-state', 'running');
    await expect(timeline.item(jobId).root).toHaveCount(0);
    await expect(timeline.item(retryId!).root).toHaveCount(0);
  });
});
