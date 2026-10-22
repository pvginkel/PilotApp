/**
 * The phone's option rows and block heads (F98.3): on a narrow window an option's line goes under
 * its label, Recommended staying at the label's end; a block head wraps what does not fit, and
 * Answered keeps its icon alone. A wide window keeps the line beside the label and Answered's word.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';
import type { TimelinePage } from '../support/page-objects/timeline-page';

const OPTIONS = 'options:\n  - Dome: up in five minutes, and light enough to carry on the bike\n  - Tunnel\n';
const DECISION = `Which tent for the trip?\n\n\`\`\`decision id=D1\n${OPTIONS}recommend: Dome\n\`\`\`\n`;
const PILOTS = `Which tent for the trip?\n\n\`\`\`decision id=D1\n${OPTIONS}answer: Tunnel\nby: agent\nat: 2026-10-20T09:00:00Z\n\`\`\`\n`;

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
});
