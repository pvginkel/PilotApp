/**
 * A document opened (F28): a document at its own address opens in its tab, in the timeline's place
 * under the tab line, the side panel beside it (F28.1, F97; the tabs whole in
 * tests/projects/doc-tabs.spec.ts). Its head holds the title, bold, the
 * project, the step, at most two lines, the segment bar, *Unsent* or *Done*, and *Edited <time>*
 * (F28.2, F28.7, D026),
 * Discuss level with the title's line, in its tab as in a phone's view;
 * its body the summary as its lead, the prose and every block answered in place, and Pilot's dots
 * (F28.3); its foot "Done · <stamp> · <who>", Reviewed, or *Send answers*, which closes its tab (F28.4).
 * It stays live and keeps its scroll; a read that fails reads "The document did not load" (F113).
 * A done line's Open shows the document as it was done (F13.3), its answers closed (F31.2), a
 * finished project's included, with neither *Edited* nor Pilot's dots where Done fixed the text.
 * Switching projects closes it (F1.6), and on a phone it is a view, the whole screen over the head
 * and its drawer's button, with no maximize or cross, its arrow back taking it off (F98.4; the views
 * whole in tests/projects/phone-views.spec.ts). Esc closes what lies over it, and never its tab.
 */

import { randomUUID } from 'node:crypto';
import type { Locator } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { documentAddress } from '../support/page-objects/overlay-page';
import { projectAddress, type Projects } from '../support/projects';
import type { components } from '@/lib/api/generated/types';

type TimelineItem = components['schemas']['TimelineSchema.1fdd8ae.TimelineItemSchema'];

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));
const stamp = (at: string) =>
  new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: ZONE }).format(new Date(at));

const TENT = '```decision id=D1\noptions:\n  - Dome: up in five minutes\n  - Tunnel\nrecommend: Dome\n```\n';
const PITCH = '```question id=Q1\ndefault: Lake Garda\n```\n';
const VAN = '```action id=A1\n```\n';
const SUMMARY = 'Where we go, what we take and who drives.';
const TRIP = [
  `---\nsummary: ${SUMMARY}\n---\n`,
  'We leave on Friday.\n',
  '## Which tent?\n',
  TENT,
  '## Where do we pitch?\n',
  PITCH,
  '## Book the van\n',
  VAN,
  'We pack on Thursday.\n',
].join('\n');
const DECISION = 'Which tent for the trip?\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const PILOTS_DECISION =
  'Which tent for the trip?\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nanswer: Tunnel\nby: agent\nat: 2026-10-20T09:00:00Z\n```\n';
const DEFERRED_TENT = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nanswer: deferred\nby: agent\nat: 2026-10-20T09:00:00Z\nto: plan\n```\n';
const PILOTS_PITCH = '```question id=Q1\nanswer: Lake Garda\nby: agent\nat: 2026-10-20T09:00:00Z\n```\n';
const BUILD = [{ id: 'build', title: 'Build the card', status: 'in_progress' as const }];
// A step's title of 25 words, the most a plan's save takes, longer than two lines of any head.
const LONG_STEP = `Build the card ${Array.from({ length: 22 }, (_, index) => `wordwordword${index}`).join(' ')}`;

/** How many lines an element shows, and whether its text is cut. */
const linesOf = (element: Locator) =>
  element.evaluate((shown) => ({
    lines: Math.round(shown.clientHeight / parseFloat(getComputedStyle(shown).lineHeight)),
    cut: shown.scrollHeight > shown.clientHeight,
  }));

/** The button's middle is the title's line's, which is not the head's. */
async function expectLevelWithTitle(button: Locator, title: Locator, head: Locator): Promise<void> {
  const middle = (box: { y: number; height: number }) => box.y + box.height / 2;
  const [at, line, whole] = [(await button.boundingBox())!, (await title.boundingBox())!, (await head.boundingBox())!];
  expect(Math.abs(middle(whole) - middle(line))).toBeGreaterThan(4);
  expect(Math.abs(middle(at) - middle(line))).toBeLessThanOrEqual(1);
}

/** An item as the project's timeline reads it. */
async function itemOf(projects: Projects, project: string, item: string): Promise<TimelineItem> {
  return (await projects.timeline(project)).items.find((each) => each.id === item)!;
}

test.describe('A document’s address', () => {
  test('opens it in its tab in its project’s timeline’s place: its title, project, step and segment bar in its head, the summary leading its body, then its prose and blocks', async ({
    page,
    people,
    projectList,
    projects,
    shell,
    timeline,
    overlay,
    docTabs,
    panel,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Overlay');
    const id = await projects.makeWithSession({ name, members: [me.handle!], tasks: BUILD });
    const text = TRIP.replace('---\n', '---\nstep: build\n');
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text });
    await overlay.open(id, trip);

    await expect(page).toHaveURL(documentAddress(id, trip));
    await expect(overlay.root).toBeVisible();
    await expect(timeline.item(trip).root).toBeAttached();
    await expect(projectList.tab(name)).toHaveAttribute('aria-current', 'page');

    await expect(overlay.title).toHaveText('The trip');
    await expect(overlay.project).toHaveText(name);
    await expect(overlay.step).toHaveText('Build the card');
    expect(await linesOf(overlay.step)).toEqual({ lines: 1, cut: false });
    await expect(overlay.segments).toHaveCount(3);
    // The title bold, Discuss level with its line and not the middle of the head under it.
    expect(await overlay.title.evaluate((title) => getComputedStyle(title).fontWeight)).toBe('600');
    await expectLevelWithTitle(overlay.discuss, overlay.title, overlay.head);
    await expect(overlay.unsent).toHaveCount(0);
    await expect(overlay.doneChip).toHaveCount(0);
    await expect(overlay.edited).toHaveCount(0);

    await expect(overlay.summary).toHaveText(SUMMARY);
    expect(await overlay.body.locator('.column > *').evaluateAll((parts) => parts.map((part) => part.className))).toEqual([
      'lead',
      'sheet-doc',
    ]);
    expect(await overlay.document.locator('> *').evaluateAll((parts) => parts.map((part) => part.className))).toEqual([
      'prose',
      'prose',
      'block open',
      'prose',
      'block open',
      'prose',
      'block open',
      'prose',
    ]);
    await expect(overlay.blockAt('D1').kind).toHaveText('Decision');
    await expect(overlay.blockAt('Q1').answerField).toHaveAttribute('placeholder', 'Default: Lake Garda');
    await expect(overlay.blockAt('A1').done).toHaveText('Done');
    await expect(overlay.writing).toHaveCount(0);
    // The action has no recommendation: nothing sends until it is done.
    await expect(overlay.send).toHaveText('Send answers');
    await expect(overlay.send).toBeDisabled();

    // In the timeline's place under the tab line, left of the side panel, which stands open at the
    // window's right (F28.1, F98.1).
    const viewport = page.viewportSize()!;
    const box = (await overlay.root.boundingBox())!;
    const side = (await panel.root.boundingBox())!;
    const app = (await shell.app.boundingBox())!;
    const line = (await docTabs.root.boundingBox())!;
    expect(box.x + box.width).toBe(side.x);
    expect(side.x + side.width).toBe(viewport.width);
    expect(box.y).toBeCloseTo(line.y + line.height, 0);
    expect(box.y + box.height).toBe(app.y + app.height);
  });

  test('cuts a long plan step in its head at two lines, ellipsized, its whole title its tooltip', async ({ people, projects, overlay }) => {
    const me = await people.signIn();
    const tasks = [{ id: 'build', title: LONG_STEP, status: 'in_progress' as const }];
    const id = await projects.makeWithSession({ name: makeUnique('Long step'), members: [me.handle!], tasks });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP.replace('---\n', '---\nstep: build\n') });
    await overlay.open(id, trip);

    await expect(overlay.step).toHaveText(LONG_STEP);
    await expect(overlay.step).toHaveAttribute('title', LONG_STEP);
    expect(await linesOf(overlay.step)).toEqual({ lines: 2, cut: true });
    expect(await overlay.step.evaluate((step) => getComputedStyle(step).webkitLineClamp)).toBe('2');
  });

  test('reads “The document did not load” for an address that names no document of the project', async ({
    page,
    people,
    projects,
    overlay,
    docTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Missing'), members: [me.handle!] });
    const other = await projects.makeWithSession({ name: makeUnique('Elsewhere'), members: [me.handle!] });
    const elsewhere = await projects.place(other, { kind: 'document', title: 'Elsewhere', text: TRIP });

    for (const address of [documentAddress(id, randomUUID()), documentAddress(id, elsewhere)]) {
      await page.goto(address);
      await expect(overlay.failed).toHaveText('The document did not load.');
      await expect(overlay.title).toHaveCount(0);
      await expect(overlay.foot).toHaveCount(0);
      await expect(docTabs.titles).toHaveText(['Document']);
      await docTabs.closeAll.click();
      await expect(page).toHaveURL(projectAddress(id));
    }
  });
});

test.describe('A document in its tab', () => {
  test('takes each answer in place, reads Unsent, and a segment goes to its block there and flashes it; Send answers sends and closes its tab', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    await page.setViewportSize({ width: 1280, height: 420 });
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Answer'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await overlay.open(id, trip);

    const van = overlay.blockAt('A1');
    await expect(van.root).not.toBeInViewport();
    // Under the reduced-motion setting the suite's pages take, the scroll jumps: read in the click's
    // own task, it is there at once, where a glide would not have moved yet.
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const body = await overlay.body.elementHandle();
    const moved = await overlay.segment('A1').evaluate((segment, body) => {
      const before = body!.scrollTop;
      (segment as HTMLElement).click();
      return body!.scrollTop - before;
    }, body);
    expect(moved).toBeGreaterThan(0);
    await expect(van.root).toHaveClass(/\bflash\b/);
    await expect(van.root).toBeInViewport();
    await expect(timeline.item(trip).blockAt('A1').root).not.toHaveClass(/\bflash\b/);

    await van.done.click();
    await expect(overlay.segment('A1')).toHaveClass(/\bdone\b/);
    await expect(overlay.unsent).toHaveText('Unsent');
    await overlay.blockAt('D1').option('Tunnel').click();
    await expect(overlay.segment('D1')).toHaveClass(/\bdone\b/);
    await expect(overlay.blockAt('D1').option('Tunnel')).toHaveAttribute('data-chosen', 'true');
    await overlay.blockAt('Q1').answerField.fill('The north shore');
    await overlay.blockAt('Q1').answerSend.click();
    await expect(overlay.segment('Q1')).toHaveClass(/\bdone\b/);

    await overlay.send.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(id));
    await expect(timeline.item(trip).root).toHaveAttribute('data-state', 'done');
    expect((await itemOf(projects, id, trip)).done).toMatchObject({ cause: 'marked', by: { kind: 'person', handle: me.handle } });
  });

  test('asks over its tab before it sends with recommendations: Esc closes the dialog alone, Confirm sends and closes the tab', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Recommend'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await projects.markDone(trip, 'A1');
    await overlay.open(id, trip);
    const { sendDialog } = timeline;

    await overlay.send.click();
    await expect(sendDialog.lines).toHaveText(['Which tent? · Dome', 'Where do we pitch? · Lake Garda']);
    await page.keyboard.press('Escape');
    await expect(sendDialog.root).toHaveCount(0);
    await expect(overlay.root).toBeVisible();

    await overlay.send.click();
    await sendDialog.confirm.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(id));
    expect((await itemOf(projects, id, trip)).done).toMatchObject({ cause: 'marked' });
  });

  test('a review has Reviewed in its foot, and once reviewed stays open, Done', async ({ people, projects, overlay }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Review'), members: [me.handle!] });
    const review = await projects.place(id, { kind: 'review', title: 'The plan', text: 'Read the plan through.\n' });
    await overlay.open(id, review);

    await expect(overlay.reviewed).toHaveText('Reviewed');
    await expect(overlay.send).toHaveCount(0);
    await overlay.reviewed.click();
    await expect(overlay.doneChip).toHaveText('Done');
    await expect(overlay.reviewed).toHaveCount(0);
    const { done } = await itemOf(projects, id, review);
    await expect(overlay.done).toHaveText(`Done · ${stamp(done!.at)}`);
    await expect(overlay.root).toBeVisible();
  });

  test('stays live and keeps its scroll: Pilot’s save shows with its dots, and read again after the turn, Edited <time>', async ({
    page,
    people,
    projects,
    overlay,
    deploymentSse,
  }) => {
    await page.setViewportSize({ width: 1280, height: 520 });
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Live'), members: [me.handle!] });
    const paragraphs = Array.from({ length: 30 }, (_, index) => `Paragraph ${index + 1} of the trip.`).join('\n\n');
    const text = `---\ntitle: The long trip\n---\n\n${paragraphs}\n\n${TENT}\n${PITCH}`;
    const trip = await projects.place(id, { kind: 'document', title: 'The long trip', text });
    await overlay.open(id, trip);
    await deploymentSse.ensureConnected();
    await overlay.body.evaluate((body) => body.scrollTo({ top: 300 }));
    expect(await overlay.scrollTop()).toBe(300);

    await projects.save(trip, `${text}\nWe pack light.\n`);
    await expect(overlay.writing).toBeVisible();
    await expect(overlay.document).toContainText('We pack light.');
    expect(await overlay.scrollTop()).toBe(300);
    await expect(overlay.edited).toHaveCount(0);

    await projects.endTurn(id);
    await overlay.open(id, trip);
    await expect(overlay.writing).toHaveCount(0);
    const { edited_at: edited } = await itemOf(projects, id, trip);
    await expect(overlay.edited).toHaveText(`Edited ${clock(edited!)}`);
    await expect(overlay.edited.locator('.avatar')).toHaveAttribute('title', 'Pilot');
  });
});

test.describe('A done line’s Open', () => {
  test('shows the document in its tab as Done fixed it, Done in its head and foot', async ({ page, people, projects, timeline, overlay }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('As done'), members: [me.handle!] });
    const notes = await projects.place(id, { kind: 'document', title: 'Packing notes', text: 'We leave on Friday.\n' });
    await projects.send(notes);
    await projects.save(notes, '---\ntitle: Packing notes\n---\n\nWe leave on Friday.\n\nA lantern too.\n');
    const { body, done } = await itemOf(projects, id, notes);
    expect(body!.at(-1)).toMatchObject({ type: 'prose', markdown: expect.stringContaining('A lantern too.') });
    await timeline.open(id);
    const { line, open } = timeline.item(notes);

    await expect(open).toHaveAttribute('aria-label', 'Open');
    await expect(open).toHaveAttribute('href', documentAddress(id, notes));
    await line.hover();
    await open.click();
    await expect(page).toHaveURL(documentAddress(id, notes));
    await expect(overlay.title).toHaveText('Packing notes');
    await expect(overlay.document).toHaveText('We leave on Friday.');
    await expect(overlay.doneChip).toHaveText('Done');
    // The person's own Done names no one.
    await expect(overlay.done).toHaveText(`Done · ${stamp(done!.at)}`);
    await expect(overlay.send).toHaveCount(0);
  });

  test('of a document Pilot changed after Done has neither Pilot’s dots nor Edited <time>, which tell of the text as it stands', async ({
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Changed'), members: [me.handle!] });
    const notes = await projects.place(id, { kind: 'document', title: 'Packing notes', text: 'We leave on Friday.\n' });
    await projects.send(notes);
    await projects.save(notes, '---\ntitle: Packing notes\n---\n\nWe leave on Friday.\n\nA lantern too.\n');
    expect(await itemOf(projects, id, notes)).toMatchObject({ writing: true, done: { cause: 'marked' } });
    await timeline.open(id);
    await timeline.item(notes).lineTitle.click();

    await expect(overlay.document).toHaveText('We leave on Friday.');
    await expect(overlay.writing).toHaveCount(0);

    await projects.endTurn(id);
    expect((await itemOf(projects, id, notes)).edited_at).not.toBeNull();
    await overlay.open(id, notes);
    await expect(overlay.document).toHaveText('We leave on Friday.');
    await expect(overlay.doneChip).toHaveText('Done');
    await expect(overlay.edited).toHaveCount(0);
  });

  test('of a done one-ask item shows its chosen option alone, opening to every option, all disabled', async ({
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('One ask'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await projects.answer(decision, 'D1', 'Tunnel');
    await timeline.open(id);
    await timeline.item(decision).lineTitle.click();
    const block = overlay.blockAt('D1');

    await expect(overlay.document.locator('.prose')).toHaveText('Which tent for the trip?');
    await expect(block.root).toHaveAttribute('data-closed', 'true');
    await expect(block.options).toHaveCount(1);
    await expect(block.options).toContainText('Tunnel');
    await expect(block.options).toHaveClass(/\bchosen\b/);
    await expect(block.other).toHaveCount(0);

    await block.toggle.click();
    await expect(block.root).toHaveAttribute('data-closed', 'false');
    await expect(block.options).toHaveCount(2);
    for (const option of await block.options.all()) await expect(option).toBeDisabled();
    await expect(block.other).toHaveCount(0);
    await expect(block.option('Tunnel')).toHaveAttribute('data-chosen', 'true');
    await expect(overlay.foot.locator('button')).toHaveCount(0);
  });

  test('of a finished project’s item shows Pilot’s chosen option alone, opening to every option, all disabled', async ({
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Finished'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: PILOTS_DECISION });
    await projects.transition(id, 'finished');
    await timeline.open(id);
    await timeline.item(decision).lineTitle.click();
    const block = overlay.blockAt('D1');

    expect((await itemOf(projects, id, decision)).done).toMatchObject({ cause: 'finished' });
    await expect(block.root).toHaveAttribute('data-closed', 'true');
    await expect(block.options).toHaveCount(1);
    await expect(block.options).toContainText('Tunnel');
    await expect(block.who.locator('.avatar')).toHaveAttribute('title', 'Pilot');

    await block.toggle.click();
    await expect(block.options).toHaveCount(2);
    for (const option of await block.options.all()) await expect(option).toBeDisabled();
    await expect(block.other).toHaveCount(0);
    await expect(overlay.doneChip).toHaveText('Done');
  });

  test('of a document Pilot settled and marked Done names Pilot in its foot', async ({ people, projects, timeline, overlay }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('By Pilot'), members: [me.handle!] });
    const settled = await projects.place(id, { kind: 'document', title: 'Settled', text: `${DEFERRED_TENT}\n${PILOTS_PITCH}` });
    await projects.doneByPilot(settled);
    await timeline.open(id);
    await timeline.item(settled).lineTitle.click();

    const { done } = await itemOf(projects, id, settled);
    await expect(overlay.done).toHaveText(`Done · ${stamp(done!.at)} · Pilot`);
    await expect(overlay.blockAt('D1').deferred).toBeVisible();
  });
});

test.describe('Esc over a document’s tab', () => {
  test('closes the keys list, and never the tab', async ({ page, people, projects, overlay, shell }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Keys'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await overlay.open(id, trip);

    await page.keyboard.press('?');
    await expect(shell.keys).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(shell.keys).toBeHidden();
    await expect(overlay.root).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(overlay.root).toBeVisible();
    await expect(page).toHaveURL(documentAddress(id, trip));
  });
});

test.describe('On a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('a document is a view, the whole screen, with no maximize or cross, its arrow back taking it off', async ({ page, people, projects, shell, overlay }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Phone'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await overlay.open(id, trip);

    await expect(overlay.root).toBeVisible();
    expect(await overlay.title.evaluate((title) => getComputedStyle(title).fontWeight)).toBe('600');
    await expectLevelWithTitle(overlay.discuss, overlay.title, overlay.head);
    const box = (await overlay.root.boundingBox())!;
    const app = (await shell.app.boundingBox())!;
    expect(box.x).toBe(0);
    expect(box.width).toBe(390);
    expect(box.y).toBe(app.y);
    expect(box.y + box.height).toBe(app.y + app.height);
    await expect(overlay.maximize).toHaveCount(0);
    await expect(overlay.close).toHaveCount(0);
    await overlay.back.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(id));
  });

  test('a document’s view lies over the head and its drawer’s button, which its arrow back gives back to switch projects', async ({
    page,
    people,
    projects,
    projectList,
    shell,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('First'), members: [me.handle!] });
    const otherName = makeUnique('Second');
    const other = await projects.makeWithSession({ name: otherName, members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await overlay.open(id, trip);
    await expect(overlay.root).toBeVisible();

    // It lies over the head, the drawer's button under it, with no top bar's to open it from.
    expect(
      await shell.drawerToggle.evaluate((button) => {
        const box = button.getBoundingClientRect();
        return button.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
      }),
    ).toBe(false);
    await overlay.back.click();
    await expect(overlay.root).toHaveCount(0);

    await shell.drawerToggle.click();
    await projectList.tab(otherName).click();
    await expect(page).toHaveURL(projectAddress(other));
    await expect(overlay.root).toHaveCount(0);
    await expect(overlay.backdrop).toHaveCount(0);
  });
});
