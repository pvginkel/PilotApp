/**
 * An open item's fold on the timeline (F12.3; the UI pile's M7): the kind in its head is the button
 * that folds it in its place, to its head and about three lines, the last fading out, everything in
 * it taking nothing; a press or Enter anywhere on it unfolds it. Every open box folds, and no done
 * line, nor the opening. The fold is the item's, the record's: it shows live on every other page and
 * over a reload, the item's close clears it, so that an Undo brings it back unfolded, and an
 * archived project's items keep theirs and take no press. The item alone, a phone's view, has no
 * fold.
 */

import type { Locator, Page } from '@playwright/test';
import type { FormTestEvent } from '@/lib/test/test-events';
import { test, expect } from '../support/fixtures';
import { makeUnique, waitTestEvent } from '../support/helpers';
import { createDeploymentSseHelper } from '../support/helpers/deployment-sse';
import { TimelinePage } from '../support/page-objects/timeline-page';
import { projectAddress } from '../support/projects';

const DECISION = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const QUESTION = '```question id=Q1\n```\n';
const ACTION = '```action id=A1\n```\n';
const CONFIRMATION = 'The tag is cut.\n\n```decision id=C1\ntype: confirmation\nproposal: Push the release to production\nbecause: auto-pilot-off\n```\n';
const TRIP = `## Which tent?\n\n${DECISION}\n## Where do we pitch?\n\n${QUESTION}`;
const LONG = Array.from({ length: 12 }, (_, index) => `Paragraph ${index + 1}: tie the tent down before the wind turns.`).join('\n\n') + '\n';
const HOUR = 60 * 60 * 1000;
// eslint-disable-next-line no-restricted-properties -- A wait's times are real ones, counted from now.
const ahead = (ms: number) => new Date(Date.now() + ms).toISOString();
const PHONE = { width: 390, height: 844 };

const heightOf = async (locator: Locator) => (await locator.boundingBox())!.height;
/** Whether the control takes the focus when given it: one under a fold, inert, takes none. */
const takesFocus = (control: Locator) =>
  control.evaluate((each: HTMLElement) => {
    each.focus();
    return document.activeElement === each;
  });
/** A fold's or an unfold's write has settled: until then the app takes no other press that writes (use-press.ts). */
const settled = (page: Page, form: 'timeline.fold' | 'timeline.unfold') =>
  waitTestEvent<FormTestEvent>(page, 'form', (event) => event.formId === form && event.phase === 'success');

test.describe('An open item’s fold', () => {
  test('the kind in its head folds it to its head and about three lines, the last fading out, live on another page; folded, its controls take nothing and a press anywhere on it unfolds it', async ({
    context,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Fold'), members: [me.handle!] });
    const notice = await projects.place(id, { kind: 'notice', title: 'Storm tonight', text: LONG });
    const other = await context.newPage();
    const otherItem = new TimelinePage(other).item(notice);
    await other.goto(projectAddress(id));
    await expect(otherItem.root).toHaveAttribute('data-folded', 'false');
    await createDeploymentSseHelper(other).ensureConnected();
    await timeline.open(id);
    const item = timeline.item(notice);

    await expect(item.kind).toHaveJSProperty('tagName', 'BUTTON');
    await expect(item.kind).toHaveText('Notice');
    await expect(item.kind).toHaveAttribute('title', 'Fold, for everyone');
    await expect(item.kind).toHaveAttribute('aria-expanded', 'true');
    await expect(item.kind).toHaveCSS('cursor', 'pointer');
    await expect(item.root).toHaveAttribute('data-folded', 'false');
    await expect(item.root).not.toHaveAttribute('role', 'button');
    const whole = await heightOf(item.root);

    await item.kind.click();
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    await expect(item.root).toHaveClass(/\bfolded\b/);
    await expect(item.root).toHaveAttribute('role', 'button');
    await expect(item.root).toHaveAttribute('aria-expanded', 'false');
    await expect(item.root).toHaveAttribute('title', 'Unfold');
    await expect(item.root).toHaveCSS('cursor', 'pointer');
    await expect(item.fold).toHaveAttribute('inert', '');
    // Its head, its title and one line of its text more, the box's padding with them.
    const folded = await heightOf(item.root);
    expect(folded).toBeLessThan(whole / 2);
    expect(folded).toBeGreaterThan(80);
    expect(folded).toBeLessThan(140);
    await expect(item.kind).toBeVisible();
    await expect(item.title).toBeVisible();
    // The body fades out to its foot, and its title's margin is dropped.
    const body = item.fold.locator('.item-body');
    expect(await body.evaluate((each) => getComputedStyle(each).maskImage)).toContain('linear-gradient');
    await expect(body).toHaveCSS('overflow', 'hidden');
    await expect(item.title).toHaveCSS('margin-bottom', '0px');
    expect((await projects.item(id, notice)).folded).toBe(true);
    // The fold is the item's: the other page shows it, with no press of its own.
    await expect(otherItem.root).toHaveAttribute('data-folded', 'true');

    // A press on its kind, drawn and inert, is a press on the box, and neither folds it again nor marks it.
    const kind = (await item.kind.boundingBox())!;
    await item.root.click({ position: { x: kind.x - (await item.root.boundingBox())!.x + 4, y: 20 } });
    await expect(item.root).toHaveAttribute('data-folded', 'false');
    await expect(item.fold).not.toHaveAttribute('inert', '');
    await expect(item.root).not.toHaveAttribute('role', 'button');
    await expect(item.root).toHaveAttribute('data-state', 'open');
    expect(await heightOf(item.root)).toBe(whole);
    expect((await projects.item(id, notice)).folded).toBe(false);
    await expect(otherItem.root).toHaveAttribute('data-folded', 'false');

    // The other page's fold shows here.
    await otherItem.kind.click();
    await expect(otherItem.root).toHaveAttribute('data-folded', 'true');
    await expect(item.root).toHaveAttribute('data-folded', 'true');
  });

  test('a control under the fold takes nothing: a press where a notice’s Read stands unfolds it and marks nothing', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Inert'), members: [me.handle!] });
    const notice = await projects.place(id, { kind: 'notice', title: 'Storm tonight', text: 'Tie the tent down.\n' });
    await timeline.open(id);
    const item = timeline.item(notice);

    await item.kind.click();
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    // Its controls are drawn, and none takes the focus.
    await expect(item.read).toHaveCount(1);
    await expect(item.discuss).toHaveCount(1);
    for (const control of [item.kind, item.discuss, item.read]) expect(await takesFocus(control)).toBe(false);

    // A press where Discuss is drawn, inert.
    const discuss = (await item.discuss.boundingBox())!;
    await page.mouse.click(discuss.x + discuss.width / 2, discuss.y + discuss.height / 2);
    await expect(item.root).toHaveAttribute('data-folded', 'false');
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.read).toBeEnabled();
    expect((await projects.item(id, notice)).done).toBeNull();
  });

  test('Enter on the kind folds it, the focus on the box; Enter on the box unfolds it, the focus on its kind again; the fold stays over a reload', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Keys'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await timeline.open(id);
    const item = timeline.item(decision);

    await item.kind.focus();
    await page.keyboard.press('Enter');
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    await expect(item.root).toBeFocused();
    await settled(page, 'timeline.fold');

    await page.keyboard.press('Enter');
    await expect(item.root).toHaveAttribute('data-folded', 'false');
    await expect(item.kind).toBeFocused();
    await settled(page, 'timeline.unfold');

    await page.keyboard.press('Enter');
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    await settled(page, 'timeline.fold');
    await page.keyboard.press('Space');
    await expect(item.root).toHaveAttribute('data-folded', 'false');
    await settled(page, 'timeline.unfold');

    await item.kind.click();
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    await timeline.open(id);
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    await expect(item.fold).toHaveAttribute('inert', '');
  });

  test('every open box folds: a decision, a question, an action, a confirmation, a document inline, a review’s card and a wait; a done line and the opening have no fold', async ({
    page,
    people,
    projects,
    timeline,
    waits,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Boxes'), members: [me.handle!] });
    const boxes: [string, string][] = [
      [await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION }), 'Decision'],
      [await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION }), 'Question'],
      [await projects.place(id, { kind: 'action', title: 'Book the van', text: ACTION }), 'Action'],
      [await projects.place(id, { kind: 'confirmation', title: 'Push it?', text: CONFIRMATION }), 'Confirm'],
      [await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP }), 'Document · 2'],
      [await projects.place(id, { kind: 'review', title: 'The plan', text: 'Read the plan through.\n' }), 'Review'],
      [await waits.add(id, { kind: 'timed_wait', title: 'The site opens', due_at: ahead(3 * HOUR) }), 'Wait'],
    ];
    const notice = await projects.place(id, { kind: 'notice', title: 'Storm tonight', text: 'Tie the tent down.\n' });
    await timeline.open(id);

    for (const [box, kind] of boxes) {
      const item = timeline.item(box);
      await expect(item.kind).toHaveText(kind);
      await expect(item.kind).toHaveJSProperty('tagName', 'BUTTON');
      await item.kind.click();
      await expect(item.root).toHaveAttribute('data-folded', 'true');
      await settled(page, 'timeline.fold');
      await expect(item.fold).toHaveAttribute('inert', '');
      expect(await takesFocus(item.discuss)).toBe(false);
    }
    for (const [box] of boxes) expect((await projects.item(id, box)).folded).toBe(true);
    for (const [box] of boxes) {
      const item = timeline.item(box);
      await item.root.click();
      await expect(item.root).toHaveAttribute('data-folded', 'false');
      await settled(page, 'timeline.unfold');
    }

    const line = timeline.item(notice);
    await line.read.click();
    await expect(line.root).toHaveAttribute('data-state', 'done');
    await expect(line.root).toHaveAttribute('data-folded', 'false');
    await expect(line.kind).toHaveCount(0);
    await expect(line.root.locator('button.kind')).toHaveCount(0);
    await expect(timeline.opening.locator('button.kind')).toHaveCount(0);
    await expect(timeline.opening).not.toHaveAttribute('data-folded');
  });

  test('a work item folds, its Stop and its session log put away with it', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Work'), members: [me.handle!] });
    const work = await projects.startWork(id, { title: 'Surveying the camp', brief: 'Survey.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(id, work)).state).toBe('running');
    await timeline.open(id);
    const item = timeline.item(work);

    await expect(item.kind).toHaveText('Work');
    await expect(item.work.stop).toBeVisible();
    await item.kind.click();
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    await expect(item.fold).toHaveAttribute('inert', '');
    for (const control of [item.work.stop, item.work.sessionLog]) expect(await takesFocus(control)).toBe(false);
    expect((await projects.work(id, work)).state).toBe('running');

    await item.root.click();
    await expect(item.root).toHaveAttribute('data-folded', 'false');
    await expect(item.work.stop).toBeEnabled();
  });

  test('the archive question folds under a finished project’s end', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Asked'), members: [me.handle!] });
    await projects.transition(id, 'finished');
    const question = (await projects.timeline(id)).items.at(-1)!;
    await timeline.open(id);
    const item = timeline.item(question.id);

    await expect(item.root).toHaveAttribute('data-kind', 'archive_question');
    await item.kind.click();
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    for (const control of [item.archiveQuestion.archive, item.archiveQuestion.keep]) expect(await takesFocus(control)).toBe(false);

    await item.root.click();
    await expect(item.root).toHaveAttribute('data-folded', 'false');
    await expect(item.archiveQuestion.archive).toBeEnabled();
  });

  test('its close clears it: answered while folded it is its done line, and its Undo brings it back open and unfolded', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Closed'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await timeline.open(id);
    const item = timeline.item(decision);
    await item.kind.click();
    await expect(item.root).toHaveAttribute('data-folded', 'true');

    await projects.answer(decision, 'D1', 'Dome');
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.root).toHaveAttribute('data-folded', 'false');
    await expect(item.root).not.toHaveAttribute('role', 'button');
    await expect(item.said).toHaveText('Dome');
    expect((await projects.item(id, decision)).folded).toBe(false);

    await item.line.hover();
    await item.undo.click();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.root).toHaveAttribute('data-folded', 'false');
    await expect(item.block.option('Dome')).toBeEnabled();
  });

  test('the address of a folded item’s block goes to its box and flashes it, the block under the cut', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Address'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    for (let index = 0; index < 12; index += 1) await projects.place(id, { kind: 'notice', title: `Notice ${index + 1}`, text: LONG });
    await timeline.open(id);
    const item = timeline.item(trip);
    await item.root.scrollIntoViewIfNeeded();
    await item.kind.click();
    await expect(item.root).toHaveAttribute('data-folded', 'true');

    await timeline.openAt(id, trip, 'Q1');
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    await expect(item.root).toHaveClass(/\bfresh\b/);
    await expect(item.root).toBeInViewport({ ratio: 1 });
    await expect(item.blockAt('Q1').root).not.toHaveClass(/\bflash\b/);
  });

  test('an archived project’s item keeps its fold and takes no press, its kind no button', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Archived'), members: [me.handle!] });
    const folded = await projects.place(id, { kind: 'notice', title: 'Storm tonight', text: 'Tie the tent down.\n' });
    const open = await projects.place(id, { kind: 'notice', title: 'Calm tomorrow', text: 'Air the tent.\n' });
    await timeline.open(id);
    await timeline.item(folded).kind.click();
    await expect(timeline.item(folded).root).toHaveAttribute('data-folded', 'true');

    await projects.transition(id, 'archived');
    await timeline.open(id);
    const item = timeline.item(folded);
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    await expect(item.fold).toHaveAttribute('inert', '');
    await expect(item.root).not.toHaveAttribute('role', 'button');
    await expect(item.root).not.toHaveAttribute('tabindex');
    await expect(item.root).not.toHaveCSS('cursor', 'pointer');
    await expect(timeline.item(open).kind).toHaveJSProperty('tagName', 'SPAN');
    await expect(timeline.item(open).kind).toHaveText('Notice');
  });
});

test.describe('An open item’s fold on a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('a tap on the kind folds it and a tap on it unfolds it, as off a phone', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Phone'), members: [me.handle!] });
    const notice = await projects.place(id, { kind: 'notice', title: 'Storm tonight', text: LONG });
    await timeline.open(id);
    const item = timeline.item(notice);
    const whole = await heightOf(item.root);

    await item.kind.tap();
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    await expect(item.fold).toHaveAttribute('inert', '');
    expect(await heightOf(item.root)).toBeLessThan(whole / 2);

    await item.root.tap();
    await expect(item.root).toHaveAttribute('data-folded', 'false');
    expect(await heightOf(item.root)).toBe(whole);
  });

  test('the item alone has no fold: a folded item opened at its address is drawn whole, its kind no button', async ({ people, projects, timeline, overlay }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Alone'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await timeline.open(id);
    await timeline.item(decision).kind.click();
    await expect(timeline.item(decision).root).toHaveAttribute('data-folded', 'true');

    await timeline.openAt(id, decision);
    const alone = timeline.item(decision, overlay.alone);
    await expect(alone.root).toHaveAttribute('data-folded', 'false');
    await expect(alone.fold).not.toHaveAttribute('inert', '');
    await expect(alone.kind).toHaveJSProperty('tagName', 'SPAN');
    await expect(alone.block.option('Dome')).toBeEnabled();
    expect((await projects.item(id, decision)).folded).toBe(true);
  });
});
