/**
 * A busy button (F148): a press that writes disables its button at once and, once the write has
 * waited a third of a second, turns its icon into the spinner, Lucide's loader turning, until the
 * server answers, so that a quick write never flashes one; a button with no icon has the spinner
 * at its start, a document's option row at its end, the row chosen and the others faded; a
 * one-ask item's Send carries it, the block's buttons standing through the save; the kind's fold
 * too, the kind left enabled. One press that writes at a time: another while one waits does
 * nothing.
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { slowNetwork } from '../support/network';

const SPINNER = '.lucide-loader-circle';
const NOTICE = 'The site opens in May.\n';
const QUESTION = 'Where do we pitch?\n\n```question id=Q1\n```\n';
const TENT = '```decision id=D1\noptions:\n  - Dome: up in five minutes\n  - Tunnel\n```\n';
// More than one ask: a press on a row answers, where a document of one ask only chooses.
const TRIP = ['## Which tent?\n', TENT, '## Where do we pitch?\n', '```question id=Q1\n```\n'].join('\n');
const CONFIRMATION = 'The tag is cut.\n\n```decision id=C1\ntype: confirmation\nproposal: Push the release\nbecause: auto-pilot-off\n```\n';
// A confirmation among two asks: its Yes, a button with no icon, is the answer.
const RELEASE = [CONFIRMATION, '## Where do we pitch?\n', '```question id=Q1\n```\n'].join('\n');

/** How the next press on `testId` stands a tenth of a second after its click, read later by `early()`. */
async function probe(page: Page, testId: string): Promise<void> {
  await page.evaluate((id) => {
    const look = (event: Event) => {
      const button = (event.target as Element).closest(`[data-testid="${id}"]`);
      if (button === null) return;
      document.removeEventListener('click', look, true);
      window.setTimeout(() => {
        const disabled = (button as HTMLButtonElement).disabled;
        const spinner = button.querySelector('.lucide-loader-circle') !== null;
        document.body.dataset.early = JSON.stringify({ disabled, spinner });
      }, 100);
    };
    document.addEventListener('click', look, true);
  }, testId);
}

async function early(page: Page): Promise<{ disabled: boolean; spinner: boolean }> {
  return JSON.parse((await page.locator('body').getAttribute('data-early'))!) as { disabled: boolean; spinner: boolean };
}

/** Whether the button's first element, or its last, is the spinner. */
const spinnerAt = (button: Locator, end: 'first' | 'last') =>
  button.evaluate((element, at) => (at === 'first' ? element.firstElementChild : element.lastElementChild)?.matches('.lucide-loader-circle') ?? false, end);

test.describe('A busy button', () => {
  test('is disabled at once and, once its write has waited, has the spinner in its icon’s place until the server answers: a notice’s Read', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Busy read'), members: [me.handle!] });
    const notice = timeline.item(await projects.place(id, { kind: 'notice', title: 'News', text: NOTICE }));
    await timeline.open(id);
    await expect(notice.read.locator('.lucide-check')).toBeVisible();

    await probe(page, 'timeline.item.read');
    const restore = await slowNetwork(page, 1_500);
    await notice.read.click();
    await expect(notice.read).toBeDisabled();
    await expect(notice.read.locator(SPINNER)).toBeVisible();
    await expect(notice.read.locator('.lucide-check')).toHaveCount(0);
    // A tenth of a second in: disabled, and no spinner yet, so that a quick write never flashes one.
    expect(await early(page)).toEqual({ disabled: true, spinner: false });
    await restore();

    await expect(notice.root).toHaveAttribute('data-state', 'done');
  });

  test('takes one press that writes at a time: another while one waits does nothing', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('One press'), members: [me.handle!] });
    const firstId = await projects.place(id, { kind: 'notice', title: 'First', text: NOTICE });
    const secondId = await projects.place(id, { kind: 'notice', title: 'Second', text: NOTICE });
    const first = timeline.item(firstId);
    const second = timeline.item(secondId);
    await timeline.open(id);
    const writes: string[] = [];
    page.on('request', (request) => {
      const { pathname } = new URL(request.url());
      if (request.method() === 'POST' && pathname.startsWith('/api/items/')) writes.push(pathname);
    });

    const restore = await slowNetwork(page, 1_500);
    await first.read.click();
    await expect(first.read).toBeDisabled();
    await second.read.click();
    await expect(second.read).toBeEnabled();
    await restore();

    await expect(first.root).toHaveAttribute('data-state', 'done');
    await expect(second.root).toHaveAttribute('data-state', 'open');
    expect(writes).toEqual([`/api/items/${firstId}/read`]);
    await second.read.click();
    await expect(second.root).toHaveAttribute('data-state', 'done');
  });

  test('has the spinner in its icon’s place: a question’s Send, Lucide’s send, its answer boxed beside it while it saves', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Busy send'), members: [me.handle!] });
    const question = timeline.item(await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION }));
    await timeline.open(id);
    const { block } = question;
    await block.answerField.fill('The north shore');
    await expect(block.answerSend.locator('.lucide-send')).toBeVisible();

    const restore = await slowNetwork(page, 1_500);
    await block.answerSend.click();
    await expect(block.said.locator('.said')).toHaveText('The north shore');
    await expect(block.said.locator('.said')).toHaveClass(/\bboxed\b/);
    await expect(block.answerSend).toBeDisabled();
    await expect(block.answerSend.locator(SPINNER)).toBeVisible();
    expect(await spinnerAt(block.answerSend, 'first')).toBe(true);
    await expect(block.answerSend.locator('.lucide-send')).toHaveCount(0);
    await restore();

    await expect(question.root).toHaveAttribute('data-state', 'done');
    await expect(question.said).toHaveText('The north shore');
  });

  test('with no icon has the spinner at its start: a document’s Yes', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Busy yes'), members: [me.handle!] });
    const release = timeline.item(await projects.place(id, { kind: 'document', title: 'The release', text: RELEASE }));
    await timeline.open(id);
    const push = release.blockAt('C1');
    await expect(push.yes.locator('svg')).toHaveCount(0);

    const restore = await slowNetwork(page, 1_500);
    await push.yes.click();
    await expect(push.yes).toBeDisabled();
    await expect(push.yes.locator(SPINNER)).toBeVisible();
    expect(await spinnerAt(push.yes, 'first')).toBe(true);
    await restore();

    await expect(push.answered).toBeVisible();
    await expect(push.yes.locator(SPINNER)).toHaveCount(0);
  });

  test('in a document’s option row has the spinner at the row’s end, the row chosen and the others faded', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Busy row'), members: [me.handle!] });
    const trip = timeline.item(await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP }));
    await timeline.open(id);
    const tent = trip.blockAt('D1');

    const restore = await slowNetwork(page, 1_500);
    await tent.option('Tunnel').click();
    await expect(tent.option('Tunnel')).toHaveClass(/\bchosen\b/);
    await expect(tent.option('Tunnel').locator(SPINNER)).toBeVisible();
    expect(await spinnerAt(tent.option('Tunnel'), 'last')).toBe(true);
    await expect(tent.option('Dome')).toHaveClass(/\bfaded\b/);
    await expect(tent.option('Dome')).toBeDisabled();
    await expect(tent.option('Dome').locator(SPINNER)).toHaveCount(0);
    await restore();

    await expect(tent.option('Tunnel')).toHaveAttribute('data-chosen', 'true');
    await expect(tent.option('Tunnel').locator(SPINNER)).toHaveCount(0);
    await expect(tent.option('Dome')).toBeEnabled();
  });

  test('in a one-ask item is its Send, the block’s buttons standing disabled through the save, the one chosen still chosen', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Busy confirm'), members: [me.handle!] });
    const item = timeline.item(await projects.place(id, { kind: 'confirmation', title: 'Ship it?', text: CONFIRMATION }));
    await timeline.open(id);
    const { confirm } = item;
    await confirm.yes.click();

    const restore = await slowNetwork(page, 1_500);
    await confirm.answerSend.click();
    await expect(confirm.answerSend).toBeDisabled();
    await expect(confirm.answerSend.locator(SPINNER)).toBeVisible();
    await expect(confirm.answerSend.locator('.lucide-send')).toHaveCount(0);
    await expect(confirm.yes).toBeDisabled();
    await expect(confirm.yes).toHaveAttribute('data-chosen', 'true');
    await expect(confirm.no).toBeDisabled();
    await expect(confirm.yes.locator(SPINNER)).toHaveCount(0);
    await restore();

    await expect(item.root).toHaveAttribute('data-state', 'done');
  });

  test('in the kind’s fold has the spinner in the kind’s icon, the kind left enabled', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Busy fold'), members: [me.handle!] });
    const item = timeline.item(await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION }));
    await timeline.open(id);

    const restore = await slowNetwork(page, 1_500);
    await item.kind.click();
    await expect(item.kind.locator(SPINNER)).toBeVisible();
    await expect(item.kind).toBeEnabled();
    await restore();

    await expect(item.root).toHaveAttribute('data-folded', 'true');
    await expect(item.kind.locator(SPINNER)).toHaveCount(0);
  });
});
