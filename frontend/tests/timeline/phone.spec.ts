/**
 * The phone's option rows, block heads and item heads (F98.3): on a narrow window an option's line
 * goes under its label, Recommended staying at the label's end; a block head wraps what does not
 * fit, and Answered keeps its icon alone; an item's head keeps to its card on one line, Urgent its
 * triangle and *Edited* a pencil, their words kept for a screen reader, and the page scrolls no
 * wider than itself; on the narrowest an item's head wraps rather than leave its card. A wide
 * window keeps the line beside the label and every word.
 */

import type { Locator } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';
import type { TimelinePage } from '../support/page-objects/timeline-page';

const OPTIONS = 'options:\n  - Dome: up in five minutes, and light enough to carry on the bike\n  - Tunnel\n';
const DECISION = `Which tent for the trip?\n\n\`\`\`decision id=D1\n${OPTIONS}recommend: Dome\n\`\`\`\n`;
const PILOTS = `Which tent for the trip?\n\n\`\`\`decision id=D1\n${OPTIONS}answer: Tunnel\nby: agent\nat: 2026-10-20T09:00:00Z\n\`\`\`\n`;

const URGENT = [
  '---\nurgent: true\n---\n',
  '## Which tent?\n',
  '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n',
  '## Where do we pitch?\n',
  '```question id=Q1\n```\n',
].join('\n');

/**
 * A project with an urgent document of two asks that Pilot edited, and a running work item with its
 * environment, opened; answers the two items' ids.
 */
async function crowded(people: People, projects: Projects, timeline: TimelinePage): Promise<{ document: string; work: string }> {
  const me = await people.signIn();
  const id = await projects.makeWithSession({ name: makeUnique('Phone'), members: [me.handle!] });
  const document = await projects.place(id, { kind: 'document', title: 'The trip', text: URGENT });
  await projects.save(document, `${URGENT}\nWe pack light.\n`);
  await projects.endTurn(id);
  const work = await projects.startWork(id, { title: 'Survey the campsites', brief: 'Survey them.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(id, work)).state).toBe('running');
  await timeline.open(id);
  return { document, work };
}

/** The head's parts stand on one line, and none past the card's edge. */
async function expectOneLineInside(card: Locator, head: Locator): Promise<void> {
  const box = (await card.boundingBox())!;
  const tops = await head.locator('> *').evaluateAll((parts) =>
    parts.map((part) => part.getBoundingClientRect()).filter((rect) => rect.width > 1).map((rect) => rect.top + rect.height / 2),
  );
  expect(Math.max(...tops) - Math.min(...tops)).toBeLessThan(6);
  const right = await head.locator('> *').evaluateAll((parts) => Math.max(...parts.map((part) => part.getBoundingClientRect().right)));
  expect(right).toBeLessThanOrEqual(box.x + box.width);
  expect(await head.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(0);
}

/** A project with one decision on it, opened; answers the decision's id. */
async function opened(people: People, projects: Projects, timeline: TimelinePage, text: string): Promise<string> {
  const me = await people.signIn();
  const id = await projects.makeWithSession({ name: makeUnique('Phone'), members: [me.handle!] });
  const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text });
  await timeline.open(id);
  return decision;
}

test.describe('On a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('an option’s line sits under its label, Recommended at the label’s end', async ({ people, projects, timeline }) => {
    const decision = await opened(people, projects, timeline, DECISION);
    const dome = timeline.item(decision).block.option('Dome');
    await expect(dome).toBeVisible();

    const row = (await dome.boundingBox())!;
    const label = (await dome.locator('.label').boundingBox())!;
    const desc = (await dome.locator('.desc').boundingBox())!;
    const rec = (await dome.locator('.rec').boundingBox())!;
    expect(desc.y).toBeGreaterThanOrEqual(label.y + label.height - 1);
    expect(Math.abs(desc.x - label.x)).toBeLessThan(1);
    expect(rec.y).toBeLessThan(label.y + label.height);
    expect(rec.y + rec.height).toBeGreaterThan(label.y);
    expect(rec.x).toBeGreaterThan(label.x);
    expect(row.x + row.width - (rec.x + rec.width)).toBeLessThan(16);
  });

  test('a block head shows Answered as its icon, its word kept for a screen reader', async ({ people, projects, timeline }) => {
    const decision = await opened(people, projects, timeline, PILOTS);
    const { answered } = timeline.item(decision).block;
    await expect(answered).toBeVisible();
    await expect(answered.locator('.icon')).toBeVisible();
    await expect(answered).toHaveText('Answered');
    const word = (await answered.locator('.chip-label').boundingBox())!;
    expect(word.width).toBeLessThanOrEqual(1);
    expect(word.height).toBeLessThanOrEqual(1);
  });
});

/** As a phone's Chrome draws the page: its scrollbars overlaid on it, taking none of its width. */
test.describe('On a phone’s Chrome', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test('an item’s head keeps to its card on one line, Urgent its triangle and Edited a pencil, and the page scrolls no wider than itself', async ({
    people,
    projects,
    timeline,
  }) => {
    const { document, work } = await crowded(people, projects, timeline);
    const doc = timeline.item(document);
    const running = timeline.item(work);
    await expect(doc.edited).toBeVisible();
    await expect(running.work.running).toBeVisible();

    await expect(doc.kind).toHaveText('Document · 2');
    await expect(doc.urgent.locator('.icon')).toBeVisible();
    await expect(doc.urgent).toHaveText('Urgent');
    expect((await doc.urgent.locator('.chip-label').boundingBox())!.width).toBeLessThanOrEqual(1);
    await expect(doc.edited.locator('.avatar')).toBeVisible();
    await expect(doc.edited.locator('.edited-icon')).toBeVisible();
    await expect(doc.edited).toHaveText(/^Edited \d\d:\d\d$/);
    expect((await doc.edited.locator('.edited-label').boundingBox())!.width).toBeLessThanOrEqual(1);

    await expectOneLineInside(doc.root, doc.head);
    await expectOneLineInside(running.root, running.head);
    expect(await timeline.root.evaluate((feed) => feed.scrollWidth - feed.clientWidth)).toBe(0);
  });
});

test.describe('On the narrowest phone', () => {
  test.use({ viewport: { width: 280, height: 653 } });

  test('a block head wraps what does not fit onto a second row', async ({ people, projects, timeline }) => {
    const decision = await opened(people, projects, timeline, PILOTS);
    const { head, kind, who } = timeline.item(decision).block;
    await expect(who).toBeVisible();

    const kindBox = (await kind.boundingBox())!;
    const whoBox = (await who.boundingBox())!;
    expect(whoBox.y).toBeGreaterThanOrEqual(kindBox.y + kindBox.height - 1);
    expect(await head.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(0);
  });

  test('an item’s head wraps what does not fit, none of it leaving the card', async ({ people, projects, timeline }) => {
    const { document } = await crowded(people, projects, timeline);
    const doc = timeline.item(document);
    await expect(doc.edited).toBeVisible();

    const card = (await doc.root.boundingBox())!;
    const kind = (await doc.kind.boundingBox())!;
    const discuss = (await doc.discuss.boundingBox())!;
    expect(kind.height).toBeLessThan(30);
    expect(discuss.y).toBeGreaterThanOrEqual(kind.y + kind.height - 1);
    expect(discuss.x + discuss.width).toBeLessThanOrEqual(card.x + card.width);
    expect(await doc.head.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(0);
    expect(await timeline.root.evaluate((feed) => feed.scrollWidth - feed.clientWidth)).toBe(0);
  });
});

test.describe('On a wide window', () => {
  test('an option’s line stands beside its label, and Answered keeps its word', async ({ people, projects, timeline }) => {
    const decision = await opened(people, projects, timeline, PILOTS);
    const { block } = timeline.item(decision);
    await block.toggle.click();
    const dome = block.option('Dome');
    const label = (await dome.locator('.label').boundingBox())!;
    const desc = (await dome.locator('.desc').boundingBox())!;
    expect(Math.abs(desc.y - label.y)).toBeLessThan(2);
    expect(desc.x).toBeGreaterThanOrEqual(label.x + label.width);

    const word = block.answered.locator('.chip-label');
    await expect(word).toBeVisible();
    expect((await word.boundingBox())!.width).toBeGreaterThan(30);
  });

  test('an item’s head keeps Urgent’s word and Edited’s, with no pencil', async ({ people, projects, timeline }) => {
    const { document } = await crowded(people, projects, timeline);
    const doc = timeline.item(document);
    await expect(doc.edited).toBeVisible();

    await expect(doc.urgent.locator('.chip-label')).toBeVisible();
    await expect(doc.edited.locator('.edited-label')).toBeVisible();
    await expect(doc.edited.locator('.edited-icon')).toBeHidden();
  });
});
