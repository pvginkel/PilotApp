/**
 * A notice's Read (F23), its one button (F17.3), the app's own state (F23.1); and Undo (F14.1) in
 * the line of an answer or a mark, whoever gave it, while the record offers it: the item open again,
 * its answer gone, to be answered anew (F32.3, decision 6).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

const QUESTION = '```question id=Q1\n```\n';
const ACTION = '```action id=A1\n```\n';
const DECISION = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';

test.describe('A notice', () => {
  test('is its text and Read, no Other; Read marks it done, its line its title alone', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Notice'), members: [me.handle!] });
    const notice = await projects.place(id, { kind: 'notice', title: 'Storm tonight', text: 'Tie the tent down.\n' });
    await timeline.open(id);
    const item = timeline.item(notice);

    await expect(item.kind).toHaveText('Notice');
    await expect(item.text).toHaveText('Tie the tent down.');
    await expect(item.read).toHaveText('Read');
    await expect(item.read).toHaveClass(/\bbtn-primary\b/);
    await expect(item.root.getByRole('button')).toHaveCount(1);

    await item.read.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineTitle).toHaveText('Storm tonight');
    await expect(item.said).toHaveCount(0);
    const done = (await projects.timeline(id)).items.find((each) => each.id === notice)!.done!;
    expect(done).toMatchObject({ cause: 'marked', by: { handle: me.handle }, undo: true });
  });
});

test.describe('Undo', () => {
  test('stands in the line of an answer and opens the item again, its answer gone, to be answered anew', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Undo'), members: [me.handle!] });
    const question = await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    await timeline.open(id);
    const item = timeline.item(question);

    await item.block.answerField.fill('Lake Como');
    await item.block.answerSend.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.undo).toHaveAttribute('title', 'Undo, until a session has taken it');
    await expect(item.undo).toHaveAttribute('aria-label', 'Undo');
    await expect(item.undo.locator('svg')).toHaveClass(/\blucide-undo2\b/);

    await item.undo.click();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.block.answerField).toHaveValue('');
    expect(await projects.block(id, question)).toMatchObject({ answer: null, by: null, note: null });

    await item.block.answerField.fill('Lake Garda');
    await item.block.answerSend.click();
    await expect(item.said).toHaveText('Lake Garda');
  });

  test('takes back a mark too: an action’s Done and a notice’s Read', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Marks'), members: [me.handle!] });
    const action = await projects.place(id, { kind: 'action', title: 'Plug it in', text: ACTION });
    const notice = await projects.place(id, { kind: 'notice', title: 'Storm tonight', text: 'Tie the tent down.\n' });
    await projects.markDone(action, 'A1', 'It hums');
    await timeline.open(id);
    await timeline.item(notice).read.click();
    await expect(timeline.item(notice).root).toHaveAttribute('data-state', 'done');

    for (const marked of [action, notice]) {
      await timeline.item(marked).undo.click();
      await expect(timeline.item(marked).root).toHaveAttribute('data-state', 'open');
    }
    await expect(timeline.item(action).block.done).toBeVisible();
    await expect(timeline.item(notice).read).toBeVisible();
    expect(await projects.block(id, action)).toMatchObject({ done: null, note: null, by: null });
  });

  test('takes back the other person’s answer as well as one’s own', async ({ people, projects, timeline }) => {
    const ben = await people.signIn({ name: 'Ben Example' });
    const id = await projects.makeWithSession({ name: makeUnique('Theirs'), members: [ben.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await projects.answer(decision, 'D1', 'Tunnel');
    await people.signIn();
    await timeline.open(id);
    const item = timeline.item(decision);

    await expect(item.said.locator('.avatar')).toHaveAttribute('title', 'Ben Example');
    await item.undo.click();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.block.options).toHaveCount(2);
    await expect(item.block.root.locator('[data-chosen="true"]')).toHaveCount(0);
  });

  test('is in no line of a finished project: an ask Finish closed unanswered, or one answered before', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Closed'), members: [me.handle!] });
    const answered = await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    const closed = await projects.place(id, { kind: 'question', title: 'Which road?', text: QUESTION });
    await projects.answer(answered, 'Q1', 'Lake Como');
    await projects.transition(id, 'finished');
    await timeline.open(id);

    const items = (await projects.timeline(id)).items;
    const offers = (item: string) => items.find((each) => each.id === item)!.done!.undo;
    expect(offers(closed)).toBe(false);
    expect(offers(answered)).toBe(false);
    await expect(timeline.item(closed).line).toBeVisible();
    await expect(timeline.item(closed).undo).toHaveCount(0);
    await expect(timeline.item(answered).line).toBeVisible();
    await expect(timeline.item(answered).undo).toHaveCount(0);
  });
});
