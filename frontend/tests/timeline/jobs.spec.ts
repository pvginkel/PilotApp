/**
 * Pilot's jobs on the items they follow from (F59.1): no line of its own but the setup's; while it
 * is queued or runs, its button at the end of the item's line beside the time, the pulsing dot,
 * Pilot's mark and its title, shown always and adding no height, a work item's quiet line's
 * included, the job after its run's turn; once ended, Pilot's mark among the
 * line's actions, first, under the mouse; failed or stopped, the button in the destructive colour
 * saying so, with Retry beside it, whose job then stands in its place. An open card carries it in
 * its head after the time, its dot going with it where the head wraps. Each opens the job's session log, which still opens at its address
 * reached cold. On a phone a running job's button takes a row under the line's title, the ended
 * mark is left to the item's view, and the menu of a line with nothing behind it offers the job
 * beside Discuss (F13.7, F13.9). An opened document's head carries the job and the item's Undo
 * before Discuss, and a worker's run's session log's head the job after its turn (F28.10): off a
 * phone the job's log lies over the tab showing, or takes the log's place; on a phone a running
 * job takes a row under the view's top line, and its log is a view pushed over the one it opens
 * from.
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique, makeUniqueToken } from '../support/helpers';
import type { Projects } from '../support/projects';
import { documentAddress } from '../support/page-objects/overlay-page';
import { sessionLogAddress } from '../support/page-objects/session-log-page';
import { dotsEndingARow } from '../support/page-objects/timeline-page';

const QUESTION = '```question id=Q1\n```\n';
/** The job after an item of Pilot's is closed (backend/app/services/job_service.py). */
const NEXT = 'Deciding what is next';
const PHONE = { width: 390, height: 844 };

const box = async (locator: Locator) => (await locator.boundingBox())!;
const middle = (at: { y: number; height: number }) => at.y + at.height / 2;
/** The mouse off every line, on the top bar. */
const away = (page: Page) => page.mouse.move(1, 1);

/** The job a close of Pilot's question placed, once placed. */
async function jobIn(projects: Projects, project: string, besides: string[] = []): Promise<string> {
  const job = async () => (await projects.timeline(project)).items.find((item) => item.work?.pilots_own && !besides.includes(item.id))?.id;
  await expect.poll(job).toBeDefined();
  return (await job())!;
}

/** The colour the destructive words are drawn in, as the page computes it. */
const destructive = (page: Page) =>
  page.evaluate(() => {
    const probe = document.createElement('span');
    probe.style.color = 'hsl(var(--destructive-text))';
    document.body.append(probe);
    const colour = getComputedStyle(probe).color;
    probe.remove();
    return colour;
  });

test.describe('Pilot’s job on a line', () => {
  test('stands at its end beside the time while it runs, the dot, Pilot’s mark and its title, shown always and adding no height; once ended, Pilot’s mark first among the actions under the mouse; each opening its session log; never a line of its own; live', async ({
    page,
    people,
    projects,
    chats,
    controller,
    timeline,
    sessionLog,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('On its line'), members: [me.handle!] });
    const started = await chats.opening(project);
    const question = await projects.place(project, { kind: 'question', title: 'Which lake?', text: QUESTION, by_pilot: true });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(question);
    const job = item.job;

    await item.block.answerField.fill('Lake Como');
    await item.block.answerSend.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    const session = await started();
    const jobId = await jobIn(projects, project);
    await expect(timeline.item(jobId).root).toHaveCount(0);
    await away(page);
    await expect(job.root).toBeVisible();
    await expect(job.root).toHaveAttribute('data-form', 'running');
    await expect(job.root).toHaveAttribute('data-state', 'running');
    await expect(job.root).toHaveText(NEXT);
    await expect(job.pulse).toBeVisible();
    await expect(job.root.locator('.avatar')).toBeVisible();
    await expect(job.retry).toHaveCount(0);
    const [button, time, title] = await Promise.all([box(job.root), box(item.lineTime), box(item.lineTitle)]);
    expect(button.x).toBeGreaterThan(title.x + title.width - 1);
    expect(time.x - (button.x + button.width)).toBeGreaterThanOrEqual(0);
    expect(time.x - (button.x + button.width)).toBeLessThanOrEqual(10);
    const running = (await box(item.line)).height;

    await job.root.click();
    await expect(page).toHaveURL(sessionLogAddress(project, jobId));
    await expect(sessionLog.item).toHaveText(NEXT);
    await sessionLog.close.click();
    await expect(sessionLog.overlay).toHaveCount(0);

    await controller.finish(chats.store, session, 'success', 'Nothing is next.');
    await expect(job.root).toHaveAttribute('data-form', 'ended');
    await away(page);
    await expect(job.root).toBeHidden();
    expect((await box(item.line)).height).toBe(running);
    await item.line.hover();
    await expect(job.root).toBeVisible();
    await expect(job.root).toHaveAccessibleName(`Pilot’s job: ${NEXT}`);
    await expect(job.root.locator('.avatar')).toHaveCount(0);
    await expect(job.root.locator('svg')).toHaveCount(1);
    expect((await box(job.root)).x).toBeLessThan((await box(item.open)).x);
    expect((await box(item.line)).height).toBe(running);
    await job.root.click();
    await expect(page).toHaveURL(sessionLogAddress(project, jobId));
    await expect(sessionLog.item).toHaveText(NEXT);

    // Its session log at its address, reached cold.
    await sessionLog.open(project, jobId);
    await expect(sessionLog.item).toHaveText(NEXT);
    await expect(sessionLog.tail).toHaveAttribute('data-mark', 'ended');
  });

  test('failed, says so in the destructive colour with Retry beside it; Retry puts the fresh job in its place, the focus on its button from the keyboard, and neither has a line of its own', async ({
    page,
    people,
    projects,
    chats,
    controller,
    timeline,
    sessionLog,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Failed job'), members: [me.handle!] });
    const started = await chats.opening(project);
    const question = await projects.place(project, { kind: 'question', title: 'Which lake?', text: QUESTION, by_pilot: true });
    await projects.answer(question, 'Q1', 'Lake Como');
    const session = await started();
    const failedId = await jobIn(projects, project);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(question);
    const job = item.job;
    await expect(job.root).toHaveAttribute('data-state', 'running');

    await controller.finish(chats.store, session, 'error', 'The model is overloaded.');
    await away(page);
    await expect(job.root).toHaveAttribute('data-form', 'failed');
    await expect(job.root).toHaveText(`${NEXT} · Failed`);
    await expect(job.pulse).toHaveCount(0);
    await expect(job.root).toHaveCSS('color', await destructive(page));
    await expect(job.retry).toBeVisible();
    await expect(job.retry).toHaveText('Retry');
    // The error is its session log's to say.
    await job.root.click();
    await expect(sessionLog.tail).toHaveAttribute('data-mark', 'failed');
    await expect(sessionLog.overlay).toContainText('The model is overloaded.');
    await sessionLog.close.click();
    await expect(sessionLog.overlay).toHaveCount(0);

    const restarted = await chats.opening(project);
    await job.retry.focus();
    await page.keyboard.press('Enter');
    await restarted();
    const retryId = await jobIn(projects, project, [failedId]);
    await expect(job.root).toHaveAttribute('href', sessionLogAddress(project, retryId));
    await expect(job.root).toHaveAttribute('data-form', 'running');
    await expect(job.root).toBeFocused();
    await expect(job.retry).toHaveCount(0);
    await expect(timeline.item(failedId).root).toHaveCount(0);
    await expect(timeline.item(retryId).root).toHaveCount(0);
    expect((await projects.work(project, failedId)).retried?.id).toBe(retryId);
  });
});

test.describe('Pilot’s job on a work item’s quiet line', () => {
  test('after the run’s turn stands on its line, adding no height to it, running or ended', async ({
    page,
    people,
    projects,
    chats,
    controller,
    timeline,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Quiet job'), members: [me.handle!] });
    const started = await chats.opening(project);
    const work = await projects.startWork(project, { title: 'Surveying the camp', brief: 'Survey the camp.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
    const { id: environment } = await projects.environment(project, work);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work);

    await controller.finish(environment, 'claude-1');
    const session = await started();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.root).toHaveClass(/\bquiet\b/);
    await expect(item.job.root).toHaveAttribute('data-form', 'running');
    await expect(item.job.root).toHaveText(NEXT);
    await away(page);
    const running = await box(item.line);

    await controller.finish(chats.store, session, 'success', 'Nothing is next.');
    await expect(item.job.root).toHaveAttribute('data-form', 'ended');
    await away(page);
    expect((await box(item.line)).height).toBe(running.height);
    await item.line.hover();
    await expect(item.job.root).toBeVisible();
    expect((await box(item.line)).height).toBe(running.height);
  });
});

test.describe('Pilot’s job on an open card', () => {
  test('stands in its head after the time: a wait’s run while it runs, then its ended mark, shown always', async ({
    page,
    people,
    projects,
    chats,
    controller,
    timeline,
    waits,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('In the head'), members: [me.handle!] });
    const card = `W${makeUniqueToken(6).toUpperCase()}-1`;
    const wait = await waits.add(project, { kind: 'card_wait', title: 'The night shift takes the card', cards: [card], states: ['Done'] });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(wait);
    await expect(item.job.root).toHaveCount(0);

    expect(await waits.transition({ card, from: 'In Progress', to: 'Done', by: 'pieter' })).toBe(1);
    const opened = await chats.opening(project);
    const run = await waits.run(wait);
    const session = await opened();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.head.getByTestId('timeline.job')).toHaveAttribute('data-form', 'running');
    await expect(item.job.root).toHaveAttribute('href', sessionLogAddress(project, run));
    await expect(item.job.pulse).toBeVisible();
    await expect(timeline.item(run).root).toHaveCount(0);
    const [time, button] = await Promise.all([box(item.time), box(item.job.root)]);
    expect(button.x).toBeGreaterThan(time.x + time.width);
    // On a narrow phone the job goes to the head's second row, its dot with it.
    const wide = page.viewportSize()!;
    await page.setViewportSize({ width: 280, height: 653 });
    // At this width the page mounts the phone's project in the desk's place, and a head read while
    // the desk's is taken down has no box.
    await expect
      .poll(async () => {
        const [job, at] = await Promise.all([item.job.root.boundingBox(), item.time.boundingBox()]);
        return job && at ? job.y - at.y : Number.NaN;
      })
      .toBeGreaterThan(20);
    expect(await dotsEndingARow(item.head)).toBe(0);
    await page.setViewportSize(wide);

    await controller.finish(chats.store, session);
    await expect(item.job.root).toHaveAttribute('data-form', 'ended');
    await away(page);
    await expect(item.job.root).toBeVisible();
    await item.job.root.click();
    await expect(page).toHaveURL(sessionLogAddress(project, run));
  });
});

test.describe('Pilot’s job on a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('running, takes a row of its own under the line’s title, its dot near the title’s left edge; ended, leaves the line', async ({
    people,
    projects,
    chats,
    controller,
    timeline,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Phone job'), members: [me.handle!] });
    const started = await chats.opening(project);
    const question = await projects.place(project, { kind: 'question', title: 'Which lake?', text: QUESTION, by_pilot: true });
    await projects.answer(question, 'Q1', 'Lake Como');
    const session = await started();
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(question);

    await expect(item.job.root).toHaveAttribute('data-form', 'running');
    const [title, button, dot] = await Promise.all([box(item.lineTitle), box(item.job.root), box(item.job.pulse)]);
    expect(button.y).toBeGreaterThanOrEqual(title.y + title.height - 1);
    expect(dot.x - title.x).toBeGreaterThanOrEqual(0);
    expect(dot.x - title.x).toBeLessThanOrEqual(8);

    await controller.finish(chats.store, session, 'success', 'Nothing is next.');
    await expect(item.job.root).toHaveCount(0);
  });

  test('on a wait’s done line, its menu offers the job beside Discuss, opening its session log', async ({
    page,
    people,
    projects,
    chats,
    controller,
    timeline,
    waits,
    sessionLog,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Menu job'), members: [me.handle!] });
    const card = `W${makeUniqueToken(6).toUpperCase()}-1`;
    const wait = await waits.add(project, { kind: 'card_wait', title: 'The card is done', cards: [card], states: ['Done'] });
    expect(await waits.transition({ card, from: 'In Progress', to: 'Done', by: 'pieter' })).toBe(1);
    const opened = await chats.opening(project);
    const run = await waits.run(wait);
    // Pilot closes the wait in its run's turn, which then ends.
    const session = await opened();
    await waits.close(wait, 'The card read Done');
    await controller.finish(chats.store, session);
    await expect.poll(async () => (await projects.item(project, wait)).job?.work.state).toBe('idle');
    const { title } = (await projects.item(project, wait)).job!;
    await timeline.open(project);
    const item = timeline.item(wait);

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await item.lineTitle.tap();
    await expect(item.lineMenu.getByRole('menuitem')).toHaveText([title, 'Discuss']);
    await item.lineMenuJob.tap();
    await expect(page).toHaveURL(sessionLogAddress(project, run));
    await expect(sessionLog.item).toHaveText(title);
    await expect(item.lineMenu).toHaveCount(0);
  });
});

/** A document of Pilot's, nothing in it to answer. */
const ROUTE = { kind: 'document', title: 'The route', text: 'We take the high road over the pass.\n', by_pilot: true } as const;

/** A document of Pilot's, sent, which places Pilot's job on it. */
async function sentDocument(projects: Projects, project: string): Promise<string> {
  const document = await projects.place(project, ROUTE);
  await projects.send(document);
  return document;
}

/** A worker's run started in the project, once it runs, and its environment. */
async function runningWork(projects: Projects, project: string): Promise<{ work: string; environment: string }> {
  const work = await projects.startWork(project, { title: 'Surveying the camp', brief: 'Survey the camp.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  const { id: environment } = await projects.environment(project, work);
  return { work, environment };
}

test.describe('Pilot’s job in what opens', () => {
  test('stands in an opened document’s tab’s head before the item’s Undo and Discuss, level with the title’s line; its session log lies over the tab, in the same place and of the same size as over the timeline, and closing it shows the document again; the head’s Undo withdraws the job', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    sessionLog,
    docTabs,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Opened job'), members: [me.handle!], paused: true });
    const document = await sentDocument(projects, project);
    const jobId = await jobIn(projects, project);
    await timeline.open(project);
    const item = timeline.item(document);
    await item.lineTitle.click();
    await expect(overlay.title).toHaveText('The route');
    // Over the timeline, the tab line showing as it does over the tab.
    await docTabs.first.click();
    await item.job.root.click();
    await expect(sessionLog.item).toHaveText(NEXT);
    const overTimeline = await box(sessionLog.overlay);
    await sessionLog.close.click();

    await docTabs.document(document).show.click();
    await expect(page).toHaveURL(documentAddress(project, document));
    await expect(overlay.title).toHaveText('The route');
    const job = overlay.job;
    await expect(job.root).toHaveAttribute('data-form', 'running');
    await expect(job.root).toHaveAttribute('data-state', 'held');
    await expect(job.root).toHaveText(NEXT);
    await expect(job.pulse).toBeVisible();
    await expect(overlay.undo).toHaveAccessibleName('Undo');
    const [title, button, undo, discuss] = await Promise.all([box(overlay.title), box(job.root), box(overlay.undo), box(overlay.discuss)]);
    expect(button.x).toBeGreaterThan(title.x + title.width);
    expect(undo.x).toBeGreaterThanOrEqual(button.x + button.width);
    expect(discuss.x).toBeGreaterThanOrEqual(undo.x + undo.width - 10);
    for (const each of [button, undo]) expect(Math.abs(middle(each) - middle(title))).toBeLessThanOrEqual(1);

    await job.root.click();
    await expect(page).toHaveURL(sessionLogAddress(project, jobId));
    await expect(sessionLog.item).toHaveText(NEXT);
    await expect(sessionLog.cue).toHaveText('Paused');
    const tab = page.locator('[data-testid="overlay"][role="tabpanel"]');
    await expect(tab.getByTestId('overlay.title')).toHaveText('The route');
    expect(await box(sessionLog.overlay)).toEqual(overTimeline);
    await sessionLog.close.click();
    await expect(sessionLog.overlay).toHaveCount(0);
    await expect(page).toHaveURL(documentAddress(project, document));
    await expect(overlay.title).toHaveText('The route');

    await overlay.undo.click();
    await expect(overlay.doneChip).toHaveCount(0);
    await expect(overlay.send).toBeVisible();
    await expect(job.root).toHaveCount(0);
    await expect(overlay.undo).toHaveCount(0);
    expect((await projects.item(project, document)).job).toBeNull();
  });

  test('follows the job live in an opened document’s head: running, failed with Retry, a Retry’s job in its place, then its ended mark, opening its session log', async ({
    page,
    people,
    projects,
    chats,
    controller,
    overlay,
    sessionLog,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Head job'), members: [me.handle!] });
    const started = await chats.opening(project);
    const document = await projects.place(project, ROUTE);
    await overlay.open(project, document);
    await deploymentSse.ensureConnected();
    const job = overlay.job;
    await expect(job.root).toHaveCount(0);

    await projects.send(document);
    const session = await started();
    const failedId = await jobIn(projects, project);
    await expect(job.root).toHaveAttribute('data-form', 'running');
    await expect(job.root).toHaveAttribute('href', sessionLogAddress(project, failedId));

    await controller.finish(chats.store, session, 'error', 'The model is overloaded.');
    await expect(job.root).toHaveAttribute('data-form', 'failed');
    await expect(job.root).toHaveText(`${NEXT} · Failed`);
    await expect(job.root).toHaveCSS('color', await destructive(page));
    await expect(job.pulse).toHaveCount(0);
    await expect(job.retry).toHaveText('Retry');

    const restarted = await chats.opening(project);
    await job.retry.click();
    const again = await restarted();
    const retryId = await jobIn(projects, project, [failedId]);
    await expect(job.root).toHaveAttribute('href', sessionLogAddress(project, retryId));
    await expect(job.root).toHaveAttribute('data-form', 'running');
    await expect(job.retry).toHaveCount(0);

    await controller.finish(chats.store, again, 'success', 'Nothing is next.');
    await expect(job.root).toHaveAttribute('data-form', 'ended');
    await expect(job.root).toHaveAccessibleName(`Pilot’s job: ${NEXT}`);
    await expect(job.root.locator('svg')).toHaveCount(1);
    await job.root.click();
    await expect(page).toHaveURL(sessionLogAddress(project, retryId));
    await expect(sessionLog.tail).toHaveAttribute('data-mark', 'ended');
  });

  test('stands in a worker’s run’s session log’s head after its turn, before the cross and level with the title, live; its own log, which carries none, takes the popover’s place', async ({
    page,
    people,
    projects,
    chats,
    controller,
    sessionLog,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Log head job'), members: [me.handle!] });
    const started = await chats.opening(project);
    const { work, environment } = await runningWork(projects, project);
    await sessionLog.open(project, work);
    await deploymentSse.ensureConnected();
    const job = sessionLog.job;
    await expect(job.root).toHaveCount(0);

    await controller.finish(environment, 'claude-1');
    const session = await started();
    const jobId = await jobIn(projects, project);
    await expect(job.root).toHaveAttribute('data-form', 'running');
    await expect(job.root).toHaveText(NEXT);
    await expect(job.pulse).toBeVisible();
    const [title, button, close, place] = await Promise.all([box(sessionLog.title), box(job.root), box(sessionLog.close), box(sessionLog.overlay)]);
    expect(close.x).toBeGreaterThanOrEqual(button.x + button.width);
    expect(Math.abs(middle(button) - middle(title))).toBeLessThanOrEqual(1);

    await job.root.click();
    await expect(page).toHaveURL(sessionLogAddress(project, jobId));
    await expect(sessionLog.item).toHaveText(NEXT);
    await expect(job.root).toHaveCount(0);
    expect(await box(sessionLog.overlay)).toEqual(place);
    await controller.finish(chats.store, session, 'success', 'Nothing is next.');
    await expect(sessionLog.tail).toHaveAttribute('data-mark', 'ended');

    await sessionLog.open(project, work);
    await expect(job.root).toHaveAttribute('data-form', 'ended');
    await expect(job.root).toHaveAttribute('href', sessionLogAddress(project, jobId));
  });
});

test.describe('Pilot’s job in what opens on a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('running, takes a row of its own under a document view’s top line, its dot level with the title, Undo and Discuss staying on the top line; its log a view pushed over the document’s, Back showing the document again', async ({
    page,
    people,
    projects,
    overlay,
    sessionLog,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Phone head'), members: [me.handle!], paused: true });
    const document = await sentDocument(projects, project);
    const jobId = await jobIn(projects, project);
    await overlay.open(project, document);
    const job = overlay.job;

    await expect(job.root).toHaveAttribute('data-form', 'running');
    const [back, title, sub, button, dot, undo, discuss] = await Promise.all(
      [overlay.back, overlay.title, overlay.sub, job.root, job.pulse, overlay.undo, overlay.discuss].map(box),
    );
    expect(button.y).toBeGreaterThanOrEqual(Math.max(back.y + back.height, sub.y + sub.height) - 1);
    expect(Math.abs(dot.x - title.x)).toBeLessThanOrEqual(1);
    for (const each of [undo, discuss]) expect(each.y + each.height).toBeLessThanOrEqual(button.y);

    await job.root.tap();
    await expect(page).toHaveURL(sessionLogAddress(project, jobId));
    await expect(sessionLog.item).toHaveText(NEXT);
    await overlay.back.tap();
    await expect(page).toHaveURL(documentAddress(project, document));
    await expect(overlay.title).toHaveText('The route');
    await expect(job.root).toHaveAttribute('data-form', 'running');
  });

  test('running, takes a row of its own under a worker’s run’s log view’s top line; its log a view pushed over the run’s, Back showing the run’s again', async ({
    page,
    people,
    projects,
    chats,
    controller,
    overlay,
    sessionLog,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Phone log job'), members: [me.handle!] });
    const started = await chats.opening(project);
    const { work, environment } = await runningWork(projects, project);
    await controller.finish(environment, 'claude-1');
    await started();
    const jobId = await jobIn(projects, project);
    await sessionLog.open(project, work);
    const job = sessionLog.job;

    await expect(job.root).toHaveAttribute('data-form', 'running');
    const [title, sub, button, dot] = await Promise.all([sessionLog.title, sessionLog.sub, job.root, job.pulse].map(box));
    expect(button.y).toBeGreaterThanOrEqual(sub.y + sub.height - 1);
    expect(Math.abs(dot.x - title.x)).toBeLessThanOrEqual(1);

    await job.root.tap();
    await expect(page).toHaveURL(sessionLogAddress(project, jobId));
    await expect(sessionLog.item).toHaveText(NEXT);
    await overlay.back.tap();
    await expect(page).toHaveURL(sessionLogAddress(project, work));
    await expect(sessionLog.item).toHaveText('Surveying the camp');
  });
});
