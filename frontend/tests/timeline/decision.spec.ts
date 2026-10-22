/**
 * A decision answered inline (F19): its options as full-width rows, a proposal as one row that
 * agrees, Other's console in the growing text field (F17.2, F19.4, F115, F110, F133), each answer
 * saved as given and the item's done (F32.1, F32.3); and its block as an answer Pilot gave or a
 * deferral reads it: closed, opening to every option, with who answered in its head (F31).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { slowNetwork } from '../support/network';
import type { Projects } from '../support/projects';
import type { components } from '@/lib/api/generated/types';

type Block = components['schemas']['TimelineSchema.1fdd8ae.BlockSchema'];
type BlockPart = components['schemas']['TimelineSchema.1fdd8ae.BlockPartSchema'];

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));

const ASK = 'Which tent for the trip?';
const AFTER = 'We leave on Friday.';
const OPTIONS = 'options:\n  - Dome: up in five minutes\n  - Tunnel\n';
const DECISION = `${ASK}\n\n\`\`\`decision id=D1\n${OPTIONS}recommend: Dome\n\`\`\`\n\n${AFTER}\n`;
const PROPOSAL = '```decision id=D1\nproposal: Take the dome\n```\n';
const PILOTS = (answer: string) =>
  `\`\`\`decision id=D1\n${OPTIONS}answer: ${answer}\nby: agent\nat: 2026-10-20T09:00:00Z\nnote: The forecast is dry.\n\`\`\`\n`;
const DEFERRED = (to: string) =>
  `\`\`\`decision id=D1\n${OPTIONS}answer: deferred\nby: agent\nat: 2026-10-20T09:00:00Z\nto: ${to}\nnote: Decide once the van is booked.\n\`\`\`\n`;

const UNSENT_KEY = 'pilot.unsent';

/** An item's one block as the API reads it. */
async function blockOf(projects: Projects, project: string, item: string): Promise<Block> {
  const found = (await projects.timeline(project)).items.find((each) => each.id === item)!;
  return (found.body!.find((part) => part.type === 'block') as BlockPart).block;
}

test.describe('A decision', () => {
  test('stands inline in its prose, its options full-width rows of a label and its line, Recommended on the recommendation, Other last', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Options'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await timeline.open(id);

    const item = timeline.item(decision);
    const { block } = item;
    await expect(item.text).toHaveText(ASK);
    await expect(item.root.locator('.item-after')).toHaveText(AFTER);
    // The prose that asks, the block, the prose after it, in that order.
    expect(
      await item.root.locator('.item-body > *').evaluateAll((parts) => parts.map((part) => part.className || part.tagName)),
    ).toEqual(['item-head', 'item-title', 'fold', 'block solo open', 'item-after']);

    await expect(block.head).toHaveCount(0);
    await expect(block.options).toHaveCount(2);
    const dome = block.option('Dome');
    await expect(dome.locator('.label')).toHaveText('Dome');
    await expect(dome.locator('.desc')).toHaveText('up in five minutes');
    await expect(dome.locator('.rec')).toHaveText('Recommended');
    await expect(dome).toHaveClass(/\brecommended\b/);
    const tunnel = block.option('Tunnel');
    await expect(tunnel.locator('.desc')).toHaveCount(0);
    await expect(tunnel.locator('.rec')).toHaveCount(0);
    await expect(block.other.locator('.label')).toHaveText('Other');
    await expect(block.other.locator('.desc')).toHaveText('Something else');
    expect(await block.root.locator('.options > *').evaluateAll((rows) => rows.map((row) => row.getAttribute('data-testid')))).toEqual([
      'timeline.block.option',
      'timeline.block.option',
      'timeline.block.other',
    ]);

    const width = (await block.root.locator('.options').boundingBox())!.width;
    for (const row of [dome, tunnel, block.other]) {
      expect((await row.boundingBox())!.width).toBeCloseTo(width, 0);
    }
  });

  test('saves the option picked as given, the row filling and the others fading while it saves, then reads as its done line', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Picked'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await timeline.open(id);
    const item = timeline.item(decision);
    const { block } = item;

    const restore = await slowNetwork(page, 1_000);
    await block.option('Tunnel').click();
    await expect(block.option('Tunnel')).toHaveClass(/\bchosen\b/);
    await expect(block.option('Tunnel')).toBeDisabled();
    await expect(block.option('Dome')).toHaveClass(/\bfaded\b/);
    await expect(block.option('Dome')).toBeDisabled();
    await expect(block.other).toHaveCount(0);
    await restore();

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.said).toHaveText('Tunnel');
    const answered = await blockOf(projects, id, decision);
    expect(answered).toMatchObject({ answer: 'Tunnel', note: null, via: 'app', by: { kind: 'person', handle: me.handle } });
  });

  test('agrees to a proposal through its one row, tinted as the recommendation, Other under it', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Proposal'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'The dome?', text: PROPOSAL });
    await timeline.open(id);
    const item = timeline.item(decision);
    const { block } = item;

    await expect(block.options).toHaveCount(1);
    const row = block.options.first();
    await expect(row).toHaveText('Take the dome');
    await expect(row).toHaveClass(/\bsingle\b/);
    await expect(row).toHaveClass(/\brecommended\b/);
    await expect(block.other).toBeVisible();

    await row.click();
    await expect(item.said).toHaveText('Agree');
    expect((await blockOf(projects, id, decision)).answer).toBe('Agree');
  });
});

test.describe('Other’s console', () => {
  test('takes Other’s place with its field, Send and a cross; Enter breaks the line and Ctrl+Enter sends the words as typed', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Words'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await timeline.open(id);
    const item = timeline.item(decision);
    const { block } = item;

    await block.other.click();
    await expect(block.other).toHaveCount(0);
    await expect(block.console).toBeVisible();
    await expect(block.field).toBeFocused();
    await expect(block.field).toHaveAttribute('placeholder', 'Other: in your own words');
    await expect(block.send).toBeDisabled();
    await expect(block.cancel).toHaveAttribute('title', 'Cancel (Esc)');

    await block.field.pressSequentially('Neither:');
    await block.field.press('Enter');
    await block.field.pressSequentially('the van.');
    await expect(block.field).toHaveValue('Neither:\nthe van.');
    await expect(item.root).toHaveAttribute('data-state', 'open');

    await block.field.press('Control+Enter');
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.said).toHaveText('Neither: the van.');
    expect((await blockOf(projects, id, decision)).answer).toBe('Neither:\nthe van.');
  });

  test('closes on its cross and on Esc in its field, keeping what was typed, after a reload too, until Send sends it', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Kept'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await timeline.open(id);
    const item = timeline.item(decision);
    const { block } = item;
    const kept = () => page.evaluate((key) => JSON.parse(localStorage.getItem(key) ?? '{}') as Record<string, string>, UNSENT_KEY);

    await block.other.click();
    await block.field.fill('Not yet');
    await block.cancel.click();
    await expect(block.console).toHaveCount(0);
    await expect(block.other.locator('.desc')).toHaveText('Something else');

    await block.other.click();
    await expect(block.field).toHaveValue('Not yet');
    await block.field.press('Escape');
    await expect(block.console).toHaveCount(0);
    expect(await kept()).toMatchObject({ [`${decision}/D1/other`]: 'Not yet' });

    await timeline.open(id);
    await block.other.click();
    await expect(block.field).toHaveValue('Not yet');
    await block.send.click();
    await expect(item.said).toHaveText('Not yet');
    expect(await kept()).not.toHaveProperty(`${decision}/D1/other`);
  });

  test('lies under everything else in Esc’s order: Esc elsewhere closes the keys list first, then the console', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Order'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await timeline.open(id);
    const { block } = timeline.item(decision);

    await block.other.click();
    await block.field.fill('The van');
    await timeline.item(decision).title.click();
    await expect(block.field).not.toBeFocused();
    await page.keyboard.press('?');
    await expect(page.getByTestId('shell.keys')).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(page.getByTestId('shell.keys')).toBeHidden();
    await expect(block.console).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(block.console).toHaveCount(0);
  });

  test('grows from one line to eight, then scrolls, and keeps Send in view at the foot of the timeline', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Grows'), members: [me.handle!] });
    for (let index = 0; index < 6; index += 1) {
      await projects.place(id, { kind: 'notice', title: `Notice ${index + 1}`, text: 'A notice that takes\n\na few lines.\n' });
    }
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await timeline.open(id);
    const { block } = timeline.item(decision);
    await block.other.click();

    const measure = () =>
      block.field.evaluate((field: HTMLTextAreaElement) => {
        const style = getComputedStyle(field);
        return { height: field.offsetHeight, line: parseFloat(style.lineHeight), overflow: style.overflowY, scrolls: field.scrollHeight > field.clientHeight };
      });
    const rest = await measure();
    expect(rest).toMatchObject({ overflow: 'hidden', scrolls: false });

    await block.field.fill('One\nTwo\nThree');
    const three = await measure();
    expect(three.height).toBeCloseTo(rest.height + 2 * rest.line, 0);
    expect(three.overflow).toBe('hidden');

    await block.field.fill(Array.from({ length: 12 }, (_, index) => `Line ${index + 1}`).join('\n'));
    const most = await measure();
    expect(most.height).toBeCloseTo(rest.height + 7 * rest.line, 0);
    expect(most).toMatchObject({ overflow: 'auto', scrolls: true });

    const feed = (await timeline.root.boundingBox())!;
    const send = (await block.send.boundingBox())!;
    expect(send.y + send.height).toBeLessThanOrEqual(feed.y + feed.height);
    expect(send.y).toBeGreaterThanOrEqual(feed.y);
  });
});

test.describe('An answer Pilot gave', () => {
  test('reads closed under a head with Pilot’s avatar, opens to every option on its chevron or its answer, and gives way to the person’s', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Settled'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: PILOTS('Dome') });
    await timeline.open(id);
    const item = timeline.item(decision);
    const { block } = item;

    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(block.kind).toHaveText('Decision');
    await expect(block.answered).toHaveText('Answered');
    await expect(block.time).toHaveText(clock('2026-10-20T09:00:00Z'));
    await expect(block.who.locator('.avatar')).toHaveAttribute('title', 'Pilot');
    await expect(block.toggle).toHaveAttribute('aria-expanded', 'false');

    // Closed: the chosen option alone, its note under it.
    await expect(block.options).toHaveCount(1);
    await expect(block.options.locator('.label')).toHaveText('Dome');
    await expect(block.options.locator('.desc')).toHaveText('up in five minutes');
    await expect(block.note).toHaveText('The forecast is dry.');
    await expect(block.note.locator('svg')).toHaveClass(/\blucide-sticky-note\b/);
    await expect(block.other).toHaveCount(0);

    await block.toggle.click();
    await expect(block.toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(block.options).toHaveCount(2);
    await expect(block.option('Dome')).toHaveAttribute('data-chosen', 'true');
    await expect(block.option('Dome').getByTestId('timeline.block.note')).toHaveText('The forecast is dry.');
    for (const row of [block.option('Tunnel'), block.other]) {
      await expect(row).toBeEnabled();
      await expect(row).not.toHaveClass(/\bfaded\b/);
    }

    await block.toggle.click();
    await expect(block.options).toHaveCount(1);
    await block.options.click();
    await expect(block.options).toHaveCount(2);

    await block.option('Tunnel').click();
    await expect(item.said).toHaveText('Tunnel');
    expect(await blockOf(projects, id, decision)).toMatchObject({ answer: 'Tunnel', note: null, by: { handle: me.handle } });
  });

  test('in free words is Other’s row, which reopens the console with them for Cmd+Enter to send', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Pilot’s words'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: PILOTS('The van, not a tent') });
    await timeline.open(id);
    const { block } = timeline.item(decision);

    await expect(block.options).toHaveCount(1);
    await expect(block.options.locator('.label')).toHaveText('Other');
    await expect(block.options.locator('.desc')).toHaveText('The van, not a tent');

    await block.options.click();
    await expect(block.other).toHaveAttribute('data-chosen', 'true');
    await expect(block.other.locator('.desc')).toHaveText('The van, not a tent');
    await block.other.click();
    await expect(block.field).toHaveValue('The van, not a tent');
    await block.field.press('Meta+Enter');
    await expect(timeline.item(decision).said).toHaveText('The van, not a tent');
    expect(await blockOf(projects, id, decision)).toMatchObject({ answer: 'The van, not a tent', by: { handle: me.handle } });
  });
});

test.describe('A deferred block', () => {
  test('reads “Deferred to <task>” under who deferred, its note under it; opened, every option, none chosen', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({
      name: makeUnique('Deferred'),
      members: [me.handle!],
      tasks: [{ id: 'ship', title: 'Ship it', status: 'pending' }],
    });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DEFERRED('ship') });
    await timeline.open(id);
    const { block } = timeline.item(decision);

    await expect(block.deferred.locator('.said')).toHaveText('Deferred to Ship it');
    await expect(block.deferred.locator('em')).toHaveText('Ship it');
    await expect(block.deferred.getByTestId('timeline.block.note')).toHaveText('Decide once the van is booked.');
    await expect(block.who.locator('.avatar')).toHaveAttribute('title', 'Pilot');
    await expect(block.options).toHaveCount(0);
    await expect(block.other).toHaveCount(0);

    await block.toggle.click();
    await expect(block.deferred).toBeVisible();
    await expect(block.options).toHaveCount(2);
    await expect(block.root.locator('[data-chosen="true"]')).toHaveCount(0);
    await expect(block.other.locator('.desc')).toHaveText('Something else');
  });

  test('to the plan reads “Deferred to the project’s end”', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Loose end'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DEFERRED('plan') });
    await timeline.open(id);

    await expect(timeline.item(decision).block.deferred.locator('.said')).toHaveText("Deferred to the project's end");
  });
});
