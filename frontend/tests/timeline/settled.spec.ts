/**
 * A section Pilot settled (F31.5): a block's own section (F30.9) whose answer is Pilot's, settled
 * or deferred, is one line — Pilot's mark, the heading's words, the answer as the closed block
 * shows it, the note a muted line under them, each clipped — in the inline document, the
 * overlay's body and the done view, consecutive lines one list. A click opens the whole section,
 * the block in it read closed; a segment (F33) and the block's address (F97) open it too, a card's
 * block address in the overlay at the block. A person's replacement opens it for good, and Undo
 * leaves it open; the counts, the bar and *Send answers* count it as the answered block it is.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { addressOf } from '../support/page-objects/timeline-page';

const AT = 'at: 2026-10-20T09:00:00Z';
const LONG_NOTE = 'Lake Garda has the shortest drive of the three, a shop at the gate and room for the van. '.repeat(4).trim();
const TENT = `\`\`\`decision id=D1\noptions:\n  - Dome\n  - Tunnel\nanswer: Dome\nby: agent\n${AT}\nnote: Rain is forecast.\n\`\`\`\n`;
const PITCH = `\`\`\`question id=Q1\nanswer: Lake Garda\nby: agent\n${AT}\nnote: ${LONG_NOTE}\n\`\`\`\n`;
const VAN = '```action id=A1\n```\n';
const BIKES = `\`\`\`decision id=D3\noptions:\n  - Two\n  - Four\nanswer: deferred\nby: agent\n${AT}\nto: plan\nnote: Once we know who comes.\n\`\`\`\n`;
const TRIP = [
  'We leave on Friday.\n',
  '## Which **tent**?\n',
  'The forecast says rain all weekend.\n',
  TENT,
  '## Where do we pitch?\n',
  PITCH,
  '## Book the van\n',
  VAN,
  '## How many bikes?\n',
  BIKES,
].join('\n');
const WORDS = (count: number) => Array.from({ length: count }, (_, index) => `word${index}`).join(' ');
const PARAGRAPHS = Array.from({ length: 30 }, (_, index) => `Paragraph ${index + 1} of the trip.`).join('\n\n');
/** A card's text: past the inline line, its settled section far down. */
const LONG_TRIP = [`${WORDS(160)}\n`, '## Book the van\n', VAN, `${PARAGRAPHS}\n`, '## How many bikes?\n', BIKES].join('\n');

const classesOf = (parts: Element[]) => parts.map((part) => part.className);

test.describe('A section Pilot settled', () => {
  test('is one line in the inline document: Pilot’s mark, the heading’s words, the answer, the note clipped under them; consecutive lines one list', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Settled'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await timeline.open(id);
    const item = timeline.item(trip);

    expect(await item.document.locator('> *').evaluateAll(classesOf)).toEqual([
      'prose',
      'settled-lines',
      'prose',
      'block open',
      'settled-lines',
    ]);
    await expect(item.settled.first().getByTestId('timeline.settled.line')).toHaveCount(2);
    await expect(item.settled.last().getByTestId('timeline.settled.line')).toHaveCount(1);

    const tent = item.settledLine('D1');
    await expect(tent.avatar).toHaveAttribute('title', 'Pilot');
    await expect(tent.heading).toHaveText('Which tent?');
    await expect(tent.heading.locator('strong')).toHaveText('tent');
    await expect(tent.answer).toHaveText('Dome');
    await expect(tent.note).toHaveText('Rain is forecast.');
    const pitch = item.settledLine('Q1');
    await expect(pitch.heading).toHaveText('Where do we pitch?');
    await expect(pitch.answer).toHaveText('Lake Garda');
    await expect(pitch.note).toHaveText(LONG_NOTE);
    const bikes = item.settledLine('D3');
    await expect(bikes.avatar).toHaveAttribute('title', 'Pilot');
    await expect(bikes.answer).toHaveText("Deferred to the project's end");
    await expect(bikes.note).toHaveText('Once we know who comes.');

    // The note is a line of its own under the line's first, clipped to it.
    const first = (await pitch.heading.boundingBox())!;
    const note = (await pitch.note.boundingBox())!;
    expect(note.y).toBeGreaterThanOrEqual(first.y + first.height - 1);
    expect(note.height).toBeLessThan(first.height);
    expect(await pitch.note.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);

    // Nothing of a collapsed section is drawn but its line, and the person's own block stands whole.
    await expect(item.blocks).toHaveCount(1);
    await expect(item.blockAt('A1').root).toBeVisible();
    await expect(item.document).not.toContainText('The forecast says rain all weekend.');
    await expect(item.document.locator('h2')).toHaveText(['Book the van']);

    // The kind's count, the bar and Send answers count each as the answered block it is.
    await expect(item.kind).toHaveText('Document · 4');
    await expect(item.segments).toHaveCount(4);
    for (const block of ['D1', 'Q1', 'D3']) await expect(item.segment(block)).toHaveClass(/\bdone\b/);
    await expect(item.segment('A1')).not.toHaveClass(/\bdone\b/);
    await expect(item.send).toBeDisabled();
  });

  test('opens to the whole section on a click, its block read closed, and stays open as the timeline is read again', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Click'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await timeline.open(id);
    const item = timeline.item(trip);

    await item.settledLine('D1').root.click();
    expect(await item.document.locator('> *').evaluateAll(classesOf)).toEqual([
      'prose',
      'prose',
      'block answered',
      'settled-lines',
      'prose',
      'block open',
      'settled-lines',
    ]);
    await expect(item.document.locator('h2').first()).toHaveText('Which tent?');
    await expect(item.document).toContainText('The forecast says rain all weekend.');
    const tent = item.blockAt('D1');
    await expect(tent.root).toHaveAttribute('data-closed', 'true');
    await expect(tent.options).toHaveCount(1);
    await expect(tent.options.locator('.label')).toHaveText('Dome');
    await expect(tent.note).toHaveText('Rain is forecast.');
    await expect(tent.who.locator('.avatar')).toHaveAttribute('title', 'Pilot');
    await expect(item.settledLines).toHaveCount(2);

    await timeline.refocus();
    await expect(tent.root).toBeVisible();
    await expect(item.settledLine('D1').root).toHaveCount(0);
  });

  test('opens on a segment, which goes to its block and flashes it', async ({ page, people, projects, timeline }) => {
    await page.setViewportSize({ width: 1280, height: 520 });
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Segment'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await timeline.open(id);
    const item = timeline.item(trip);

    await item.segment('Q1').click();
    const pitch = item.blockAt('Q1');
    await expect(pitch.root).toHaveClass(/\bflash\b/);
    await expect(pitch.root).toBeInViewport();
    await expect(item.settledLine('Q1').root).toHaveCount(0);
    await expect(item.settledLine('D1').root).toBeVisible();
  });

  test('opens for good once a person replaces Pilot’s answer, and Undo of the sent document leaves it open', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Replaced'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await timeline.open(id);
    const item = timeline.item(trip);
    await expect(item.settledLine('D1').root).toBeVisible();

    await projects.answer(trip, 'D1', 'Tunnel');
    await timeline.refocus();
    await expect(item.blockAt('D1').option('Tunnel')).toHaveAttribute('data-chosen', 'true');
    await expect(item.settledLine('D1').root).toHaveCount(0);
    await expect(item.settledLine('Q1').root).toBeVisible();

    // From the record, not the page: a fresh page draws it open.
    await page.reload();
    await expect(item.blockAt('D1').root).toBeVisible();
    await expect(item.settledLine('D1').root).toHaveCount(0);

    await projects.markDone(trip, 'A1');
    await projects.send(trip);
    await timeline.refocus();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await projects.undo(trip);
    await timeline.refocus();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.blockAt('D1').option('Tunnel')).toHaveAttribute('data-chosen', 'true');
    await expect(item.settledLine('D1').root).toHaveCount(0);
    await expect(item.settledLine('Q1').root).toBeVisible();
    await expect(item.settledLine('D3').root).toBeVisible();
  });

  test('draws as any block where it is no settled section: before every heading, two blocks under one, a person’s answer', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Unsettled'), members: [me.handle!] });
    const text = [TENT, '## Two asks\n', PITCH, BIKES, '## Book the van\n', VAN].join('\n');
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text });
    await projects.markDone(trip, 'A1');
    await timeline.open(id);
    const item = timeline.item(trip);

    await expect(item.blocks).toHaveCount(4);
    await expect(item.settledLines).toHaveCount(0);
    await expect(item.blockAt('A1').said).toHaveText('Done');
  });
});

test.describe('A section Pilot settled in the overlay', () => {
  test('is its line in the body, and a segment in the head opens it and goes to the block', async ({ page, people, projects, overlay }) => {
    await page.setViewportSize({ width: 1280, height: 420 });
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Overlay'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await overlay.open(id, trip);

    expect(await overlay.document.locator('> *').evaluateAll(classesOf)).toEqual([
      'prose',
      'settled-lines',
      'prose',
      'block open',
      'settled-lines',
    ]);
    await expect(overlay.settledLine('D1').heading).toHaveText('Which tent?');
    await expect(overlay.settledLine('D3').answer).toHaveText("Deferred to the project's end");
    await expect(overlay.blocks).toHaveCount(1);
    await expect(overlay.segments).toHaveCount(4);

    await overlay.segment('D3').click();
    const bikes = overlay.blockAt('D3');
    await expect(bikes.root).toHaveClass(/\bflash\b/);
    await expect(bikes.root).toBeInViewport();
    await expect(bikes.deferred).toContainText("Deferred to the project's end");
    await expect(overlay.settledLine('D3').root).toHaveCount(0);

    await overlay.settledLine('Q1').root.click();
    await expect(overlay.blockAt('Q1').said.locator('.said')).toHaveText('Lake Garda');
    await expect(overlay.settledLines).toHaveCount(1);
  });

  test('is its line in the done view, as Done fixed it, and opens there on a click', async ({ page, people, projects, timeline, overlay }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Done view'), members: [me.handle!] });
    const text = ['We leave on Friday.\n', '## Which tent?\n', TENT, '## How many bikes?\n', BIKES].join('\n');
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text });
    await projects.doneByPilot(trip);
    await timeline.open(id);

    await timeline.item(trip).open.click();
    await expect(page).toHaveURL(`/projects/${id}/documents/${trip}`);
    await expect(overlay.doneChip).toHaveText('Done');
    await expect(overlay.settled).toHaveCount(1);
    await expect(overlay.settledLines).toHaveCount(2);
    await expect(overlay.blocks).toHaveCount(0);

    await overlay.settledLine('D1').root.click();
    const tent = overlay.blockAt('D1');
    await expect(tent.root).toHaveAttribute('data-closed', 'true');
    await expect(tent.options).toHaveCount(1);
    await expect(tent.options.locator('.label')).toHaveText('Dome');
    await expect(overlay.settledLines).toHaveCount(1);
  });
});

test.describe('A settled section’s block address', () => {
  test('of an inline document goes to the block on the timeline, its section open', async ({ page, people, projects, timeline }) => {
    await page.setViewportSize({ width: 1280, height: 520 });
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Inline address'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    for (let index = 0; index < 6; index += 1) {
      await projects.place(id, { kind: 'notice', title: `Notice ${index + 1}`, text: 'A notice.\n\nOf a few lines.\n' });
    }

    await timeline.openAt(id, trip, 'Q1');
    const item = timeline.item(trip);
    const pitch = item.blockAt('Q1');
    await expect(pitch.root).toHaveClass(/\bflash\b/);
    await expect(pitch.root).toBeInViewport();
    await expect(item.settledLine('Q1').root).toHaveCount(0);
    await expect(item.settledLine('D1').root).toBeVisible();
    await expect(page.getByTestId('overlay')).toHaveCount(0);
  });

  test('of a card opens it in the overlay at the block, its section open, and closing returns to the project’s address', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    await page.setViewportSize({ width: 1280, height: 520 });
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Card address'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The long trip', text: LONG_TRIP });
    await timeline.open(id);
    await expect(timeline.item(trip).card.root).toBeVisible();

    await timeline.openAt(id, trip, 'D3');
    const bikes = overlay.blockAt('D3');
    await expect(bikes.root).toHaveClass(/\bflash\b/);
    await expect(bikes.root).toBeInViewport();
    expect(await overlay.scrollTop()).toBeGreaterThan(0);
    await expect(overlay.settledLines).toHaveCount(0);
    await expect(page).toHaveURL(addressOf(id, trip, 'D3'));

    await overlay.close.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(`/projects/${id}`);
    await expect(timeline.item(trip).card.root).toBeInViewport();
  });
});
