/**
 * An action answered inline (F21): a paste-back field and Done, no Other (F21.1, F17.3); or its
 * options as buttons and Other, which sends the field (F21.2); what was pasted back the note, in the
 * growing field kept in the browser until sent (F115, F110, F133); and its done line, Done or the
 * option with the paste-back as its note (F21.5).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { slowNetwork } from '../support/network';

const ASK = 'Plug the lamp in.';
const ACTION = `${ASK}\n\n\`\`\`action id=A1\n\`\`\`\n`;
const OPTIONS = "```action id=A1\noptions:\n  - Works\n  - Doesn't\n```\n";
const PILOTS = (answer: string) =>
  `\`\`\`action id=A1\noptions:\n  - Works\n  - Doesn't\nanswer: ${answer}\nby: agent\nat: 2026-10-20T09:00:00Z\n\`\`\`\n`;
const UNSENT_KEY = 'pilot.unsent';

test.describe('An action without options', () => {
  test('is a paste-back field and Done, no Other; Done saves what was pasted back, as typed, as its note', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Action'), members: [me.handle!] });
    const action = await projects.place(id, { kind: 'action', title: 'Plug it in', text: ACTION });
    await timeline.open(id);
    const item = timeline.item(action);
    const { block } = item;

    await expect(item.kind).toHaveText('Action');
    await expect(item.text).toHaveText(ASK);
    await expect(block.paste).toHaveAttribute('placeholder', 'What to paste back, if anything');
    await expect(block.done).toHaveText('Done');
    await expect(block.done).toHaveClass(/\bbtn-primary\b/);
    await expect(block.other).toHaveCount(0);
    await expect(block.acts).toHaveCount(0);

    await block.paste.pressSequentially('Key stored');
    await block.paste.press('Enter');
    await block.paste.pressSequentially('under kv/camp');
    await block.done.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    // A Done says only what was pasted back.
    await expect(item.said).toHaveText('Key stored under kv/camp');
    const marked = await projects.block(id, action);
    expect(marked).toMatchObject({ answer: null, note: 'Key stored\nunder kv/camp', by: { kind: 'person', handle: me.handle } });
    expect(marked.done).not.toBeNull();
  });

  test('is marked Done by Ctrl+Enter in its field, with no note when nothing was pasted back', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Bare'), members: [me.handle!] });
    const action = await projects.place(id, { kind: 'action', title: 'Plug it in', text: ACTION });
    await timeline.open(id);
    const item = timeline.item(action);

    await item.block.paste.press('Control+Enter');
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.said).toHaveCount(0);
    expect((await projects.block(id, action)).note).toBeNull();
  });

  test('keeps its paste-back after a reload, until Done sends it', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Kept'), members: [me.handle!] });
    const action = await projects.place(id, { kind: 'action', title: 'Plug it in', text: ACTION });
    await timeline.open(id);
    const item = timeline.item(action);
    const kept = () => page.evaluate((key) => JSON.parse(localStorage.getItem(key) ?? '{}') as Record<string, string>, UNSENT_KEY);

    await item.block.paste.fill('It hums');
    await timeline.open(id);
    await expect(item.block.paste).toHaveValue('It hums');
    await item.block.done.click();
    await expect(item.said).toHaveText('It hums');
    expect(await kept()).not.toHaveProperty(`${action}/A1/paste`);
  });

  test('reads Done in its block, not boxed, while Done saves', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Saving'), members: [me.handle!] });
    const action = await projects.place(id, { kind: 'action', title: 'Plug it in', text: ACTION });
    await timeline.open(id);
    const item = timeline.item(action);
    const { block } = item;
    await expect(block.said).toHaveCount(0);

    const restore = await slowNetwork(page, 1_000);
    await block.done.click();
    const said = block.said.locator('.said');
    await expect(said).toHaveText('Done');
    // Read at once, while the write is on its way.
    expect(await said.getAttribute('class')).not.toMatch(/\bboxed\b/);
    await expect(block.done).toHaveCount(0);
    await restore();

    await expect(item.root).toHaveAttribute('data-state', 'done');
  });
});

test.describe('An action with options', () => {
  test('is its options as buttons, the first the primary, then Other, and no Done; an option saves the paste-back as its note', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Options'), members: [me.handle!] });
    const action = await projects.place(id, { kind: 'action', title: 'Try the lamp', text: OPTIONS });
    await timeline.open(id);
    const item = timeline.item(action);
    const { block } = item;

    await expect(block.acts).toHaveText(['Works', "Doesn't"]);
    await expect(block.acts.first()).toHaveClass(/\bbtn-primary\b/);
    await expect(block.acts.last()).not.toHaveClass(/\bbtn-primary\b/);
    await expect(block.other).toHaveText('Other…');
    await expect(block.done).toHaveCount(0);

    await block.paste.fill('The light stays off');
    // Ctrl+Enter sends nothing where several buttons send the field.
    await block.paste.press('Control+Enter');
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await block.act("Doesn't").click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.said).toHaveText("Doesn't · The light stays off");
    expect(await projects.block(id, action)).toMatchObject({ answer: "Doesn't", note: 'The light stays off', by: { handle: me.handle } });
  });

  test('sends Other’s words as the answer and the paste-back as the note', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Other'), members: [me.handle!] });
    const action = await projects.place(id, { kind: 'action', title: 'Try the lamp', text: OPTIONS });
    await timeline.open(id);
    const item = timeline.item(action);
    const { block } = item;

    await block.paste.fill('flicker at 12:03');
    await block.other.click();
    await expect(block.other).toHaveCount(0);
    await expect(block.field).toBeFocused();
    await expect(block.field).toHaveAttribute('placeholder', 'Other: in your own words');
    await block.field.fill('Half works');
    await block.field.press('Control+Enter');

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.said).toHaveText('Half works · flicker at 12:03');
    expect(await projects.block(id, action)).toMatchObject({ answer: 'Half works', note: 'flicker at 12:03' });
  });

  test('closes Other’s console on Esc, keeping the paste-back', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Esc'), members: [me.handle!] });
    const action = await projects.place(id, { kind: 'action', title: 'Try the lamp', text: OPTIONS });
    await timeline.open(id);
    const { block } = timeline.item(action);

    await block.paste.fill('flicker');
    await block.other.click();
    await block.field.press('Escape');
    await expect(block.console).toHaveCount(0);
    await expect(block.other).toBeVisible();
    await expect(block.paste).toHaveValue('flicker');
  });

  test('reads the option picked in its block, not boxed, while it saves', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Picked'), members: [me.handle!] });
    const action = await projects.place(id, { kind: 'action', title: 'Try the lamp', text: OPTIONS });
    await timeline.open(id);
    const item = timeline.item(action);
    const { block } = item;

    const restore = await slowNetwork(page, 1_000);
    await block.act('Works').click();
    const said = block.said.locator('.said');
    await expect(said).toHaveText('Works');
    // Read at once, while the write is on its way.
    expect(await said.getAttribute('class')).not.toMatch(/\bboxed\b/);
    await restore();

    await expect(item.said).toHaveText('Works');
  });

  test('reads Other’s words in its block, boxed, while they save', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Worded'), members: [me.handle!] });
    const action = await projects.place(id, { kind: 'action', title: 'Try the lamp', text: OPTIONS });
    await timeline.open(id);
    const item = timeline.item(action);
    const { block } = item;

    await block.other.click();
    await block.field.fill('Half works');
    const restore = await slowNetwork(page, 1_000);
    await block.field.press('Control+Enter');
    const said = block.said.locator('.said');
    await expect(said).toHaveText('Half works');
    await expect(said).toHaveClass(/\bboxed\b/);
    await restore();

    await expect(item.said).toHaveText('Half works');
  });

  test('answered by Pilot stays open, Pilot’s answer in its block, boxed only when it is no option', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Pilot’s'), members: [me.handle!] });
    const option = await projects.place(id, { kind: 'action', title: 'Try the lamp', text: PILOTS('Works') });
    const words = await projects.place(id, { kind: 'action', title: 'Try it again', text: PILOTS('Half works') });
    await timeline.open(id);

    for (const [action, answer, boxed] of [
      [option, 'Works', false],
      [words, 'Half works', true],
    ] as const) {
      const { root, block } = timeline.item(action);
      await expect(root).toHaveAttribute('data-state', 'open');
      await expect(block.who.locator('.avatar')).toHaveAttribute('title', 'Pilot');
      const said = block.said.locator('.said');
      await expect(said).toHaveText(answer);
      if (boxed) {
        await expect(said).toHaveClass(/\bboxed\b/);
      } else {
        await expect(said).not.toHaveClass(/\bboxed\b/);
      }
    }
  });
});
