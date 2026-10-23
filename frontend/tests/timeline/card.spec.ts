/**
 * A document's card (F24.2): a document over about 150 words of its own, and every review however
 * short (F25.1), leaves a card on the timeline, none of its text drawn: its head, *Unsent* in it
 * while it has an answer and no Done (D026); its title, its summary (F34), its count chips, what
 * is still the person's by kind, what Pilot settled and what it deferred; its segment bar (F33), or
 * "N min read" for a text with no block; Open, which reads Continue while it reads *Unsent*; and on
 * a review Reviewed (F25.2). Open opens it in the overlay at its address, and a segment opens the
 * overlay at its block's address, at the block, which flashes; a section Pilot settled is its line
 * there (F31.5). Pilot's dots end it while Pilot writes it (F35), and *Edited <time>* stands in its
 * head once a later turn changed it (F28.7).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { documentAddress } from '../support/page-objects/overlay-page';
import { addressOf } from '../support/page-objects/timeline-page';
import type { Projects } from '../support/projects';
import type { components } from '@/lib/api/generated/types';

type TimelineItem = components['schemas']['TimelineSchema.1fdd8ae.TimelineItemSchema'];

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));

const SUMMARY = 'Where we go, what we take and who drives.';
const WORDS = (count: number) => Array.from({ length: count }, (_, index) => `word${index}`).join(' ');
const PARAGRAPHS = Array.from({ length: 30 }, (_, index) => `Paragraph ${index + 1} of the trip.`).join('\n\n');
const TENT = '```decision id=D1\noptions:\n  - Dome: up in five minutes\n  - Tunnel\nrecommend: Dome\n```\n';
const STOVE = '```decision id=D2\noptions:\n  - Gas\n  - Wood\n```\n';
const PITCH = '```question id=Q1\ndefault: Lake Garda\n```\n';
const PILOTS_PITCH = '```question id=Q1\nanswer: Lake Garda\nby: agent\nat: 2026-10-20T09:00:00Z\n```\n';
const VAN = '```action id=A1\n```\n';
const DEFERRED_BIKES = '```decision id=D3\noptions:\n  - Two\n  - Four\nanswer: deferred\nby: agent\nat: 2026-10-20T09:00:00Z\nto: plan\n```\n';

/** A text over the inline line: its summary, its filler and its blocks, each under a heading. */
function longText(blocks: [string, string][]): string {
  const sections = blocks.map(([heading, block]) => `## ${heading}\n\n${block}`);
  return [`---\nsummary: ${SUMMARY}\n---\n`, WORDS(160), ...sections].join('\n\n');
}

const TRIP = longText([
  ['Which tent?', TENT],
  ['Which stove?', STOVE],
  ['Where do we pitch?', PITCH],
  ['Book the van', VAN],
  ['How many bikes?', DEFERRED_BIKES],
]);

/** An item as the project's timeline reads it. */
async function itemOf(projects: Projects, project: string, item: string): Promise<TimelineItem> {
  return (await projects.timeline(project)).items.find((each) => each.id === item)!;
}

test.describe('A larger document', () => {
  test('leaves a card: its title, its summary, its count chips, the segment bar and Open, and none of its text', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Card'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The long trip', text: TRIP });
    await timeline.open(id);
    const item = timeline.item(trip);

    await expect(item.kind).toHaveText('Document · 5');
    await expect(item.card.root).toBeVisible();
    await expect(item.title).toHaveText('The long trip');
    await expect(item.card.summary).toHaveText(SUMMARY);
    // The deferral counts apart from the decisions still the person's, and makes no Unsent.
    await expect(item.card.counts).toHaveText(['2 decisions', '1 question', '1 action', '1 deferred']);
    await expect(item.segments).toHaveCount(5);
    await expect(item.segment('D3')).toHaveClass(/\bdone\b/);
    await expect(item.segment('D1')).not.toHaveClass(/\bdone\b/);
    await expect(item.segment('D1')).toHaveAttribute('title', 'Which tent? · open');
    await expect(item.card.readTime).toHaveCount(0);
    await expect(item.card.open).toHaveText('Open');
    await expect(item.card.open).toHaveAttribute('href', documentAddress(id, trip));
    await expect(item.card.reviewed).toHaveCount(0);
    await expect(item.unsent).toHaveCount(0);

    await expect(item.document).toHaveCount(0);
    await expect(item.text).toHaveCount(0);
    await expect(item.blocks).toHaveCount(0);
    await expect(item.send).toHaveCount(0);
    expect(await item.root.locator('.item-body > *').evaluateAll((parts) => parts.map((part) => part.className))).toEqual([
      'item-head',
      'doc-card',
    ]);
  });

  test('reads Continue and Unsent once it has an answer, a person’s or Pilot’s, its counts as they were', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Continue'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The long trip', text: TRIP });
    const pilots = await projects.place(id, {
      kind: 'document',
      title: 'Where we pitch',
      text: longText([
        ['Which tent?', TENT],
        ['Where do we pitch?', PILOTS_PITCH],
      ]),
    });
    await timeline.open(id);
    const item = timeline.item(trip);
    await expect(item.card.open).toHaveText('Open');

    await projects.answer(trip, 'D1', 'Dome');
    await timeline.refocus();
    await expect(item.card.open).toHaveText('Continue');
    await expect(item.unsent).toHaveText('Unsent');
    await expect(item.segment('D1')).toHaveClass(/\bdone\b/);
    await expect(item.card.counts).toHaveText(['2 decisions', '1 question', '1 action', '1 deferred']);

    // Pilot's answer counts apart from what is still the person's, and is an answer to send.
    const settled = timeline.item(pilots);
    await expect(settled.card.counts).toHaveText(['1 decision', '1 settled by Pilot']);
    await expect(settled.card.open).toHaveText('Continue');
    await expect(settled.unsent).toHaveText('Unsent');
  });

  test('Open opens it in the overlay at its address, and closing the overlay returns to the project’s', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Open'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The long trip', text: TRIP });
    await timeline.open(id);

    await timeline.item(trip).card.open.click();
    await expect(page).toHaveURL(documentAddress(id, trip));
    await expect(overlay.title).toHaveText('The long trip');
    await expect(overlay.summary).toHaveText(SUMMARY);
    // Pilot's deferral is its section's line (F31.5).
    await expect(overlay.blocks).toHaveCount(4);
    await expect(overlay.settledLine('D3').answer).toHaveText("Deferred to the project's end");

    await overlay.close.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(`/projects/${id}`);
    await expect(timeline.item(trip).card.root).toBeVisible();
  });

  test('a segment opens the overlay at its block’s address, the block flashing in view', async ({ page, people, projects, timeline, overlay }) => {
    await page.setViewportSize({ width: 1280, height: 520 });
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Segment'), members: [me.handle!] });
    const text = `---\ntitle: The long trip\n---\n\n${TENT}\n${PARAGRAPHS}\n\n${PITCH}\n${PARAGRAPHS}\n\n${VAN}`;
    const trip = await projects.place(id, { kind: 'document', title: 'The long trip', text });
    await timeline.open(id);

    await timeline.item(trip).segment('A1').click();
    await expect(page).toHaveURL(addressOf(id, trip, 'A1'));
    const van = overlay.blockAt('A1').root;
    await expect(van).toHaveClass(/\bflash\b/);
    await expect(van).toBeInViewport();
    expect(await overlay.scrollTop()).toBeGreaterThan(0);
    await expect(overlay.blockAt('D1').root).not.toBeInViewport();
  });

  test('with no block reads “N min read” in place of the bar', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Read time'), members: [me.handle!] });
    const notes = await projects.place(id, { kind: 'document', title: 'Packing notes', text: WORDS(600) });
    await timeline.open(id);
    const item = timeline.item(notes);

    const { read_minutes: minutes } = await itemOf(projects, id, notes);
    expect(minutes).toBeGreaterThan(1);
    await expect(item.card.readTime).toHaveText(`${minutes} min read`);
    await expect(item.segments).toHaveCount(0);
    await expect(item.card.counts).toHaveCount(0);
    await expect(item.card.open).toHaveText('Open');
  });

  test('ends in Pilot’s dots while Pilot writes it, and once the turn ended, Edited <time> stands in its head', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Writing'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The long trip', text: TRIP });
    await projects.save(trip, `${TRIP}\nWe pack light.\n`);
    await timeline.open(id);
    const item = timeline.item(trip);

    await expect(item.writing).toBeVisible();
    expect(await item.root.locator('.item-body > *').evaluateAll((parts) => parts.map((part) => part.className))).toEqual([
      'item-head',
      'doc-card',
      'typing',
    ]);
    await expect(item.edited).toHaveCount(0);

    await projects.endTurn(id);
    await timeline.open(id);
    await expect(item.writing).toHaveCount(0);
    const { edited_at: edited } = await itemOf(projects, id, trip);
    await expect(item.edited).toHaveText(`Edited ${clock(edited!)}`);
    await expect(item.edited.locator('.avatar')).toHaveAttribute('title', 'Pilot');
  });
});

test.describe('A review', () => {
  test('is a card however short: its title, its summary, “N min read”, Open and Reviewed, which makes it its done line', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Review'), members: [me.handle!] });
    const plan = await projects.place(id, {
      kind: 'review',
      title: 'The plan',
      text: `---\nsummary: ${SUMMARY}\n---\n\nRead the plan through.\n`,
    });
    const long = await projects.place(id, { kind: 'review', title: 'The long plan', text: WORDS(600) });
    await timeline.open(id);
    const item = timeline.item(plan);

    await expect(item.kind).toHaveText('Review');
    await expect(item.title).toHaveText('The plan');
    await expect(item.card.summary).toHaveText(SUMMARY);
    await expect(item.card.readTime).toHaveText('1 min read');
    await expect(item.card.counts).toHaveCount(0);
    await expect(item.segments).toHaveCount(0);
    await expect(item.card.open).toHaveText('Open');
    await expect(item.unsent).toHaveCount(0);
    await expect(item.text).toHaveCount(0);
    const { read_minutes: minutes } = await itemOf(projects, id, long);
    expect(minutes).toBeGreaterThan(1);
    await expect(timeline.item(long).card.readTime).toHaveText(`${minutes} min read`);
    await expect(timeline.item(long).card.summary).toHaveCount(0);

    await item.card.reviewed.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineTitle).toHaveText('The plan');
    expect((await itemOf(projects, id, plan)).done).not.toBeNull();
  });
});
