/**
 * Pilot's jobs on the items they follow from (F59.1): no line of its own but the setup's; while it
 * is queued or runs, its button at the end of the item's line beside the time, the pulsing dot,
 * Pilot's mark and its title, shown always and adding no height; once ended, Pilot's mark among the
 * line's actions, first, under the mouse; failed or stopped, the button in the destructive colour
 * saying so, with Retry beside it, whose job then stands in its place. An open card carries it in
 * its head after the time. Each opens the job's session log, which still opens at its address
 * reached cold. On a phone a running job's button takes a row under the line's title, the ended
 * mark is left to the item's view, and the menu of a line with nothing behind it offers the job
 * beside Discuss (F13.7, F13.9).
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique, makeUniqueToken } from '../support/helpers';
import type { Projects } from '../support/projects';
import { sessionLogAddress } from '../support/page-objects/session-log-page';

const QUESTION = '```question id=Q1\n```\n';
/** The job after an item of Pilot's is closed (backend/app/services/job_service.py). */
const NEXT = 'Deciding what is next';
const PHONE = { width: 390, height: 844 };

const box = async (locator: Locator) => (await locator.boundingBox())!;
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
    await expect(item.wait.menu.getByRole('menuitem')).toHaveText([title, 'Discuss']);
    await item.wait.menuJob.tap();
    await expect(page).toHaveURL(sessionLogAddress(project, run));
    await expect(sessionLog.item).toHaveText(title);
    await expect(item.wait.menu).toHaveCount(0);
  });
});
