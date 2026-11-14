/**
 * A button that starts Pilot's work (F59.3; ui-conventions, "Buttons that write or start work"):
 * under the mouse its icon gives way to Pilot's mark without the avatar's circle, Lucide's play at
 * its foot, and comes back off it; a phone, with no hover, shows none. Which buttons is the server's
 * reading per item, `close_starts_work`: of a one-ask item of Pilot's own its Send, a question's
 * carrying Lucide's send, and none of its options; a document's Send answers and its dialog's
 * Confirm; a review's Reviewed; never a notice's Read, nor an item a worker's run added. A stopped
 * work item's Resume always, its Close never, nor Stop. Pressed, the spinner takes the icon's
 * place, the mark's with it.
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { slowNetwork } from '../support/network';
import type { Projects } from '../support/projects';

const MARK = '.job-glyph';
const SPINNER = '.lucide-loader-circle';
const PHONE = { width: 390, height: 844 };
const TENT = '```decision id=D1\noptions:\n  - Dome: up in five minutes\n  - Tunnel\n```\n';
const QUESTION = 'Where do we pitch?\n\n```question id=Q1\n```\n';
const NOTICE = 'The site opens in May.\n';
const SURVEY = 'The lake and the forest compared.\n';
// Two asks, each recommended: Send answers takes them as they stand, through its dialog.
const TRIP = [
  '## Which tent?\n',
  '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nrecommend: Dome\n```\n',
  '## Which stove?\n',
  '```decision id=D2\noptions:\n  - Gas\n  - Wood\nrecommend: Gas\n```\n',
].join('\n');

/** The mouse off every button, on the top bar. */
const away = (page: Page) => page.mouse.move(1, 1);

/** Under the mouse `button` shows the job's mark in its icon's place, `icon`; off it, its icon. */
async function expectMarked(page: Page, button: Locator, icon: string) {
  await away(page);
  await expect(button.locator(icon)).toBeVisible();
  await expect(button.locator(MARK)).toBeHidden();
  await button.hover();
  await expect(button.locator(MARK)).toBeVisible();
  await expect(button.locator(icon)).toBeHidden();
  await away(page);
  await expect(button.locator(icon)).toBeVisible();
  await expect(button.locator(MARK)).toBeHidden();
}

/** `button` carries no mark: under the mouse it keeps what it shows. */
async function expectUnmarked(button: Locator) {
  await button.hover();
  await expect(button.locator(MARK)).toHaveCount(0);
}

/** A work item of the project that a person stopped, its stopped turn ended. */
async function stoppedIn(projects: Projects, project: string): Promise<string> {
  const work = await projects.startWork(project, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  await projects.stop(work);
  await expect.poll(async () => (await projects.records(work)).records.at(-1)?.kind).toBe('result');
  return work;
}

test.describe('A button that starts Pilot’s work', () => {
  test('of an item of Pilot’s own, as the server reads it: a one-ask item’s Send alone, a question’s with Lucide’s send, a document’s Send answers and its Confirm, a review’s Reviewed; never an option nor a notice’s Read; pressed, the spinner in the mark’s place', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Starts work'), members: [me.handle!] });
    const own = (kind: 'decision' | 'question' | 'notice' | 'review' | 'document', title: string, text: string) =>
      projects.place(id, { kind, title, text, by_pilot: true });
    const decisionId = await own('decision', 'Which tent?', TENT);
    const questionId = await own('question', 'Where?', QUESTION);
    const noticeId = await own('notice', 'News', NOTICE);
    const reviewId = await own('review', 'The survey', SURVEY);
    const tripId = await own('document', 'The trip', TRIP);
    const read = async (itemId: string) => (await projects.item(id, itemId)).close_starts_work;
    expect(await Promise.all([decisionId, questionId, noticeId, reviewId, tripId].map(read))).toEqual([true, true, false, true, true]);
    await timeline.open(id);

    const decision = timeline.item(decisionId).block;
    await decision.option('Tunnel').click();
    await expectMarked(page, decision.answerSend, '.lucide-send');
    for (const option of await decision.options.all()) await expectUnmarked(option);

    const question = timeline.item(questionId).block;
    await question.answerField.fill('The north shore');
    await expectMarked(page, question.answerSend, '.lucide-send');

    const notice = timeline.item(noticeId);
    await expectUnmarked(notice.read);
    await expect(notice.read.locator('.lucide-check')).toBeVisible();

    await expectMarked(page, timeline.item(reviewId).card.reviewed, '.lucide-check');

    const trip = timeline.item(tripId);
    await expectMarked(page, trip.send, '.lucide-check');
    await trip.send.click();
    await expectMarked(page, timeline.sendDialog.confirm, '.lucide-check');
    await expectUnmarked(timeline.sendDialog.cancel);
    await timeline.sendDialog.cancel.click();
    await expect(timeline.sendDialog.root).toHaveCount(0);

    // Pressed under the mouse, the spinner takes the icon's place, the mark's with it.
    await question.answerSend.hover();
    const restore = await slowNetwork(page, 1_500);
    await question.answerSend.click();
    await expect(question.answerSend.locator(SPINNER)).toBeVisible();
    await expect(question.answerSend.locator(MARK)).toHaveCount(0);
    await expect(question.answerSend.locator('.lucide-send')).toHaveCount(0);
    await restore();
    await expect(timeline.item(questionId).root).toHaveAttribute('data-state', 'done');
  });

  test('of an item a worker’s run added, none: its Send keeps its icon under the mouse', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Starts none'), members: [me.handle!] });
    const decisionId = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: TENT });
    expect((await projects.item(id, decisionId)).close_starts_work).toBe(false);
    await timeline.open(id);
    const block = timeline.item(decisionId).block;

    await block.option('Tunnel').click();
    await expectUnmarked(block.answerSend);
    await expect(block.answerSend.locator('.lucide-send')).toBeVisible();
    await away(page);
  });

  test('a stopped work item’s Resume, its Close none; once resumed, its Stop none', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Resume starts'), members: [me.handle!] });
    const work = await stoppedIn(projects, id);
    await timeline.open(id);
    const item = timeline.item(work).work;

    await expectMarked(page, item.resume, '.lucide-play');
    await expectUnmarked(item.close);

    await item.resume.click();
    await expect(item.stop).toBeVisible();
    await expectUnmarked(item.stop);
  });
});

test.describe('On a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('no button shows the mark: with no hover, a stopped work item’s Resume keeps its icon', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Phone resume'), members: [me.handle!] });
    const work = await stoppedIn(projects, id);
    await timeline.open(id);
    const item = timeline.item(work).work;
    expect(await page.evaluate(() => window.matchMedia('(hover: hover)').matches)).toBe(false);

    await item.resume.hover();

    await expect(item.resume.locator('.lucide-play')).toBeVisible();
    await expect(item.resume.locator(MARK)).toBeHidden();
  });
});
