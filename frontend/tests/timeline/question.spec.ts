/**
 * A question answered inline (F20): the growing field (F115), "Your answer" or "Default: …", and
 * Send, Enter breaking the line and Ctrl+Enter sending (F110), what was typed kept in the browser
 * until sent (F133); the answer boxed (F20.2) and saved as given, the item's done (F32.1, F32.3);
 * and either person answering one meant for the other (F107.1).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { slowNetwork } from '../support/network';

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));

const ASK = 'Where do we pitch?';
const QUESTION = `${ASK}\n\n\`\`\`question id=Q1\n\`\`\`\n`;
const DEFAULTED = '```question id=Q1\ndefault: Lake Garda\n```\n';
const PILOTS = '```question id=Q1\nanswer: Lake Garda\nby: agent\nat: 2026-10-20T09:00:00Z\nnote: The closest one.\n```\n';
const UNSENT_KEY = 'pilot.unsent';

test.describe('A question', () => {
  test('is a field, “Your answer”, and Send, held until something is typed; Enter breaks the line and Ctrl+Enter sends it as typed', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Question'), members: [me.handle!] });
    const question = await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    await timeline.open(id);
    const item = timeline.item(question);
    const { block } = item;

    await expect(item.kind).toHaveText('Question');
    await expect(item.text).toHaveText(ASK);
    await expect(block.head).toHaveCount(0);
    await expect(block.answerField).toHaveAttribute('placeholder', 'Your answer');
    await expect(block.answerSend).toHaveText('Send');
    await expect(block.answerSend).toBeDisabled();
    await expect(block.other).toHaveCount(0);

    await block.answerField.pressSequentially('Lake Como,');
    await block.answerField.press('Enter');
    await block.answerField.pressSequentially('the north shore.');
    await expect(block.answerField).toHaveValue('Lake Como,\nthe north shore.');
    await expect(block.answerSend).toBeEnabled();
    await expect(item.root).toHaveAttribute('data-state', 'open');

    await block.answerField.press('Control+Enter');
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.said).toHaveText('Lake Como, the north shore.');
    expect(await projects.block(id, question)).toMatchObject({
      answer: 'Lake Como,\nthe north shore.',
      note: null,
      via: 'app',
      by: { kind: 'person', handle: me.handle },
    });
  });

  test('reads “Default: …” from its default, which Send gives while the field is empty', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Default'), members: [me.handle!] });
    const question = await projects.place(id, { kind: 'question', title: 'Which lake?', text: DEFAULTED });
    await timeline.open(id);
    const item = timeline.item(question);

    await expect(item.block.answerField).toHaveAttribute('placeholder', 'Default: Lake Garda');
    await expect(item.block.answerField).toHaveValue('');
    await expect(item.block.answerSend).toBeEnabled();
    await item.block.answerSend.click();
    await expect(item.said).toHaveText('Lake Garda');
    expect((await projects.block(id, question)).answer).toBe('Lake Garda');
  });

  test('boxes the answer from Send until its done line draws', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Boxed'), members: [me.handle!] });
    const question = await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    await timeline.open(id);
    const item = timeline.item(question);
    const { block } = item;

    await block.answerField.fill('Lake Como');
    const restore = await slowNetwork(page, 1_000);
    await block.answerSend.click();
    await expect(block.answerField).toHaveCount(0);
    await expect(block.said.locator('.said')).toHaveText('Lake Como');
    await expect(block.said.locator('.said')).toHaveClass(/\bboxed\b/);
    await restore();

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.said).toHaveText('Lake Como');
  });

  test('keeps what was typed after a reload, until Send sends it', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Kept'), members: [me.handle!] });
    const question = await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    await timeline.open(id);
    const item = timeline.item(question);
    const kept = () => page.evaluate((key) => JSON.parse(localStorage.getItem(key) ?? '{}') as Record<string, string>, UNSENT_KEY);

    await item.block.answerField.fill('Lake Como');
    expect(await kept()).toMatchObject({ [`${question}/Q1/answer`]: 'Lake Como' });
    await timeline.open(id);
    await expect(item.block.answerField).toHaveValue('Lake Como');

    await item.block.answerSend.click();
    await expect(item.said).toHaveText('Lake Como');
    expect(await kept()).not.toHaveProperty(`${question}/Q1/answer`);
  });

  test('grows its field from one line with what is typed, Send level with its foot', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Grows'), members: [me.handle!] });
    const question = await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    await timeline.open(id);
    const { block } = timeline.item(question);

    const height = () => block.answerField.evaluate((field: HTMLTextAreaElement) => field.offsetHeight);
    const line = await block.answerField.evaluate((field) => parseFloat(getComputedStyle(field).lineHeight));
    const rest = await height();
    await block.answerField.fill('One\nTwo\nThree');
    expect(await height()).toBeCloseTo(rest + 2 * line, 0);

    const field = (await block.answerField.boundingBox())!;
    const send = (await block.answerSend.boundingBox())!;
    expect(send.y + send.height).toBeCloseTo(field.y + field.height, 0);
  });

  test('answered by Pilot reads boxed and closed, and opens to the field holding it, for the person’s answer to replace', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Pilot’s'), members: [me.handle!] });
    const question = await projects.place(id, { kind: 'question', title: 'Which lake?', text: PILOTS });
    await timeline.open(id);
    const item = timeline.item(question);
    const { block } = item;

    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(block.kind).toHaveText('Question');
    await expect(block.answered).toHaveText('Answered');
    await expect(block.time).toHaveText(clock('2026-10-20T09:00:00Z'));
    await expect(block.who.locator('.avatar')).toHaveAttribute('title', 'Pilot');
    await expect(block.said.locator('.said')).toHaveText('Lake Garda');
    await expect(block.said.locator('.said')).toHaveClass(/\bboxed\b/);
    await expect(block.note).toHaveText('The closest one.');
    await expect(block.answerField).toHaveCount(0);

    await block.toggle.click();
    await expect(block.said).toHaveCount(0);
    await expect(block.answerField).toHaveValue('Lake Garda');
    await block.answerField.fill('Lake Como');
    await block.answerField.press('Meta+Enter');
    await expect(item.said).toHaveText('Lake Como');
    expect(await projects.block(id, question)).toMatchObject({ answer: 'Lake Como', note: null, by: { handle: me.handle } });
  });

  test('meant for the other person is answered by either', async ({ people, projects, timeline }) => {
    const ben = makeUnique('ben', 8);
    await people.other(ben, 'Ben Example');
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Hers'), members: [me.handle!, ben] });
    const question = await projects.place(id, { kind: 'question', title: 'Which bike?', text: `---\nfor: ${ben}\n---\n\n${QUESTION}` });
    await timeline.open(id);
    const item = timeline.item(question);

    await expect(item.forUser).toHaveText('for Ben Example');
    await item.block.answerField.fill('The red one');
    await item.block.answerSend.click();
    await expect(item.said).toHaveText('The red one');
    expect((await projects.block(id, question)).by).toMatchObject({ handle: me.handle });
  });
});
