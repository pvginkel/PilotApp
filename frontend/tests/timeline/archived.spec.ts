/**
 * An archived project takes Bring back alone (D012): every close on its timeline stands disabled —
 * a decision's options, a question's field and Send, an action's paste-back and Done, a
 * confirmation's check and cross, a notice's Read, a review's Reviewed, on its card and in the
 * overlay, and a document's *Send answers* — and a done item's Undo is gone, until Bring back.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

const DECISION = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const QUESTION = '```question id=Q1\n```\n';
const ACTION = '```action id=A1\n```\n';
const CONFIRMATION = '```decision id=C1\ntype: confirmation\nproposal: Book the site\nbecause: auto-pilot-off\n```\n';

test.describe('An archived project’s timeline', () => {
  test('stands every close disabled and drops Undo, as the API refuses them, until Bring back', async ({
    people,
    projects,
    timeline,
    overlay,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Shelved'), members: [me.handle!] });
    const decision = timeline.item(await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION }));
    const question = timeline.item(await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION }));
    const action = timeline.item(await projects.place(id, { kind: 'action', title: 'Pay the deposit', text: ACTION }));
    const confirmation = timeline.item(await projects.place(id, { kind: 'confirmation', title: 'Book it?', text: CONFIRMATION }));
    const notice = timeline.item(await projects.place(id, { kind: 'notice', title: 'News', text: 'The site opens in May.\n' }));
    const review = timeline.item(await projects.place(id, { kind: 'review', title: 'The plan', text: 'Read the plan through.\n' }));
    const document = timeline.item(await projects.place(id, { kind: 'document', title: 'Packing', text: 'Pack the tent.\n' }));
    const answeredId = await projects.place(id, { kind: 'question', title: 'Which month?', text: QUESTION });
    await projects.answer(answeredId, 'Q1', 'May');
    const answered = timeline.item(answeredId);
    const closes = [
      decision.block.option('Dome'),
      question.block.answerField,
      question.block.answerSend,
      action.block.paste,
      action.block.done,
      confirmation.confirm.yes,
      confirmation.confirm.no,
      notice.read,
      review.card.reviewed,
      document.send,
    ];
    await timeline.open(id);
    await deploymentSse.ensureConnected();
    await expect(answered.undo).toBeVisible();

    await projects.transition(id, 'archived');
    for (const close of closes) await expect(close).toBeDisabled();
    await expect(answered.undo).toHaveCount(0);
    await review.card.open.click();
    await expect(overlay.reviewed).toBeDisabled();
    await overlay.close.click();

    await projects.transition(id, 'brought_back');
    // The question's Send waits for words; the rest take a click at once.
    await question.block.answerField.fill('North');
    for (const close of closes) await expect(close).toBeEnabled();
    await expect(answered.undo).toBeVisible();
  });
});
