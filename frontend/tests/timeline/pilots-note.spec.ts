/**
 * Pilot's note on a block (F168.1): inside a block that is the person's, between its head and its
 * controls, at the top of an open one-ask panel, which draws no head; an amber triangle whose
 * tooltip says the note is Pilot's, its text, the answer it suggests and the note beside it; the
 * block's head, its segment, the option's Recommended and the document's card as they were. Once
 * the block is answered, one line, what Pilot suggested or the start of its text, which its chevron
 * opens whole and folds again, nothing putting it away (F168.3). Its button takes what it
 * suggests into the block as the person's own: in a document the answer with its note, in a one-ask
 * item the choice and the note its Send carries, on an action a note alone in the paste-back
 * (F168.2). A block Pilot's note suggests
 * another answer on takes no default: *Send answers* waits on it, its tooltip naming it (F168.4);
 * a note that agrees, or one on a block with no recommendation, changes nothing there. None shows
 * on a block Pilot answered, or on a confirmation. A claimed action's note, held and handed back,
 * is `tests/work/claimed.spec.ts`'s.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

const TENT = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nrecommend: Dome\n```\n';
const PITCH = '```question id=Q1\ndefault: Lake Garda\n```\n';
const VAN = '```action id=A1\n```\n';
const TRIP = ['We leave on Friday.\n', '## Which tent?\n', TENT, '## Where do we pitch?\n', PITCH, '## Book the van\n', VAN].join('\n');
const PILOTS_TENT = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nanswer: Dome\nby: agent\nat: 2026-10-20T09:00:00Z\n```\n';

const WIND = 'The forecast for the weekend gives gusts of 60 km/h on the lake.';
const STAKES = 'Take the long stakes.';
const UNTAKEN = 'Pilot’s own note on this ask, not the writer’s';
const DIFFERS = 'Pilot’s note on Which tent? suggests another answer than recommended: answer it first';
const FERRY = 'The ferry runs on Sundays.';
const CARD = 'Booked with the club’s card.';
const BELL = 'A borrowed bell tent';

test.describe('Pilot’s note on a block', () => {
  test('stands inside a block of a document that is the person’s, between its head and its controls: its triangle saying it is Pilot’s, its text, the answer it suggests and the note beside it; the head, the segment and the option’s Recommended as they were', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Noted'), members: [me.handle!] });
    const trip = await projects.place(project, { kind: 'document', title: 'The trip', text: TRIP });
    await projects.note(trip, { block: 'D1', text: WIND, suggested_answer: 'Tunnel', suggested_note: STAKES });
    await projects.note(trip, { block: 'A1', suggested_note: 'Booked with the club’s card.' });
    await timeline.open(project);

    const item = timeline.item(trip);
    const tent = item.blockAt('D1');
    expect(await tent.root.locator('> *').evaluateAll((parts) => parts.map((part) => part.className))).toEqual([
      'block-head',
      'pilot-note',
      'block-controls',
    ]);
    await expect(tent.pilotsNote.mark).toHaveAttribute('title', UNTAKEN);
    await expect(tent.pilotsNote.mark).toHaveAttribute('data-late', 'false');
    await expect(tent.pilotsNote.text).toHaveText(WIND);
    await expect(tent.pilotsNote.root).toContainText('Pilot would answer');
    await expect(tent.pilotsNote.answer).toHaveText('Tunnel');
    await expect(tent.pilotsNote.note).toHaveText(STAKES);
    await expect(tent.pilotsNote.toggle).toHaveCount(0);
    await expect(tent.head.locator('.pn-mark')).toHaveCount(0);
    await expect(tent.head).not.toContainText('Pilot');
    await expect(tent.option('Dome').locator('.rec')).toHaveText('Recommended');
    await expect(tent.option('Tunnel')).not.toHaveClass(/\brecommended\b/);
    await expect(item.segment('D1')).toHaveAttribute('title', 'Which tent? · open');
    await expect(item.segment('D1')).not.toHaveClass(/\bdone\b/);

    // A suggested note alone, on an action.
    const van = item.blockAt('A1');
    await expect(van.pilotsNote.text).toHaveCount(0);
    await expect(van.pilotsNote.answer).toHaveCount(0);
    await expect(van.pilotsNote.root).toContainText('Pilot would add');
    await expect(van.pilotsNote.note).toHaveText('Booked with the club’s card.');

    // A block with no note of Pilot's shows nothing of it.
    await expect(item.blockAt('Q1').pilotsNote.root).toHaveCount(0);
  });

  test('once its block is answered is one line: the triangle, what Pilot suggested or the start of its text, and a chevron that opens it whole, a long note whole, and folds it to its line again; nothing else puts it away', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Noted'), members: [me.handle!] });
    const trip = await projects.place(project, { kind: 'document', title: 'The trip', text: TRIP });
    const long = `${WIND}\n\n${'The campsite closes its gate at ten and opens it at seven. '.repeat(12)}\n\n- The north field is flat.\n- The south field floods.`;
    await projects.note(trip, { block: 'D1', text: WIND, suggested_answer: 'Tunnel', suggested_note: STAKES });
    await projects.note(trip, { block: 'Q1', text: long });
    await projects.answer(trip, 'Q1', 'Lake Como');
    await timeline.open(project);

    const item = timeline.item(trip);
    const tent = item.blockAt('D1');
    await expect(tent.pilotsNote.root).toHaveAttribute('data-line', 'false');
    await tent.option('Dome').click();
    await expect(tent.answered).toBeVisible();
    await expect(tent.pilotsNote.root).toHaveAttribute('data-line', 'true');
    await expect(tent.pilotsNote.line).toHaveText('Pilot would have answered Tunnel');
    await expect(tent.pilotsNote.mark).toHaveAttribute('title', UNTAKEN);
    await expect(tent.pilotsNote.text).toHaveCount(0);

    const pitch = item.blockAt('Q1');
    expect(await pitch.root.locator('> *').evaluateAll((parts) => parts.map((part) => part.className))).toEqual([
      'block-head',
      'pilot-note one',
      'block-controls',
    ]);
    await expect(pitch.pilotsNote.line).toHaveText(WIND);
    await expect(pitch.pilotsNote.toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(pitch.pilotsNote.root.locator('button')).toHaveCount(1);
    await pitch.pilotsNote.toggle.click();
    await expect(pitch.pilotsNote.root).toHaveAttribute('data-line', 'false');
    await expect(pitch.pilotsNote.text.locator('p')).toHaveCount(2);
    await expect(pitch.pilotsNote.text.locator('li')).toHaveText(['The north field is flat.', 'The south field floods.']);
    await expect(pitch.pilotsNote.text.locator('li').last()).toBeVisible();
    await expect(pitch.pilotsNote.root.locator('button')).toHaveCount(1);
    await expect(pitch.pilotsNote.toggle).toHaveAttribute('aria-expanded', 'true');
    await pitch.pilotsNote.toggle.click();
    await expect(pitch.pilotsNote.line).toHaveText(WIND);

    // The line itself opens it too.
    await tent.pilotsNote.line.click();
    await expect(tent.pilotsNote.answer).toHaveText('Tunnel');
    await expect(tent.pilotsNote.note).toHaveText(STAKES);
  });

  test('in a one-ask item stands at the top of its panel, which draws no head, and with its item done, under the head of its block opened, one line', async ({
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Noted'), members: [me.handle!] });
    const tent = await projects.place(project, { kind: 'decision', title: 'Which tent?', text: TENT });
    await projects.note(tent, { block: 'D1', text: WIND, suggested_answer: 'Tunnel' });
    await timeline.open(project);

    const block = timeline.item(tent).block;
    expect(await block.root.locator('> *').evaluateAll((parts) => parts.map((part) => part.className))).toEqual(['pilot-note', 'block-controls']);
    await expect(block.pilotsNote.text).toHaveText(WIND);
    await expect(block.pilotsNote.answer).toHaveText('Tunnel');

    await projects.answer(tent, 'D1', 'Tunnel');
    await overlay.open(project, tent);
    const opened = overlay.blockAt('D1');
    expect(await opened.root.locator('> *').evaluateAll((parts) => parts.map((part) => part.className))).toEqual([
      'block-head',
      'pilot-note one',
      'block-controls',
    ]);
    await expect(opened.pilotsNote.line).toHaveText('Pilot would have answered Tunnel');
  });

  test('shows on no block Pilot answered, and on no confirmation, on its card or opened', async ({
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Noted'), members: [me.handle!] });
    const trip = await projects.place(project, { kind: 'document', title: 'The trip', text: TRIP });
    await projects.note(trip, { block: 'D1', text: WIND });
    await projects.save(trip, TRIP.replace(TENT, PILOTS_TENT));
    expect((await projects.document(trip)).body!.flatMap((part) => (part.type === 'block' ? [part.block] : []))[0].pilots_note?.text).toBe(WIND);
    const push = await projects.place(project, {
      kind: 'confirmation',
      title: 'Push the release?',
      text: '```decision id=C1\ntype: confirmation\nproposal: Push the release to production\nbecause: auto-pilot-off\n```\n',
    });
    await projects.note(push, { block: 'C1', text: WIND });
    await timeline.open(project);

    const tent = timeline.item(trip).blockAt('D1');
    await expect(tent.answered).toBeVisible();
    await expect(tent.who.getByTitle('Pilot')).toBeVisible();
    await expect(tent.pilotsNote.root).toHaveCount(0);

    const confirmation = timeline.item(push);
    await expect(confirmation.confirm.yes).toBeVisible();
    await expect(confirmation.block.pilotsNote.root).toHaveCount(0);
    await overlay.open(project, push);
    await expect(overlay.blockAt('C1').yes).toBeVisible();
    await expect(overlay.blockAt('C1').pilotsNote.root).toHaveCount(0);
  });

  test('leaves the card of a larger document as it was', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Noted'), members: [me.handle!] });
    const text = `${'We walk the north shore to the ridge and camp below it. '.repeat(16)}\n\n${TRIP}`;
    const trip = await projects.place(project, { kind: 'document', title: 'The trip', text });
    await projects.note(trip, { block: 'D1', text: WIND, suggested_answer: 'Tunnel' });
    await timeline.open(project);

    const card = timeline.item(trip).card;
    await expect(card.counts).toHaveText(['1 decision', '1 question', '1 action']);
    await expect(card.root).not.toContainText('Pilot');
    await expect(card.root.locator('.pn-mark')).toHaveCount(0);
  });
});

test.describe('Send answers and Pilot’s note', () => {
  test('waits on an open block Pilot’s note suggests another answer on, as on one with no recommendation, its tooltip naming the block, and sends once the person answers it', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Noted'), members: [me.handle!] });
    const trip = await projects.place(project, { kind: 'document', title: 'The trip', text: TRIP });
    await projects.note(trip, { block: 'D1', suggested_answer: 'Tunnel' });
    await projects.markDone(trip, 'A1');
    await timeline.open(project);

    const item = timeline.item(trip);
    await expect(item.send).toBeDisabled();
    await expect(item.send).toHaveAttribute('title', DIFFERS);
    await expect(item.blockAt('D1').option('Dome').locator('.rec')).toHaveText('Recommended');

    await item.blockAt('D1').option('Tunnel').click();
    await expect(item.send).toBeEnabled();
    await expect(item.send).toHaveAttribute('title', 'Send the answers to Pilot');
    await item.send.click();
    await expect(timeline.sendDialog.lines).toHaveText(['Where do we pitch? · Lake Garda']);
    await timeline.sendDialog.confirm.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
  });

  test('takes the recommendation where Pilot’s note suggests the same answer, and a note on a block with no recommendation changes nothing', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Noted'), members: [me.handle!] });
    const trip = await projects.place(project, { kind: 'document', title: 'The trip', text: TRIP.replace('default: Lake Garda\n', '') });
    await projects.note(trip, { block: 'D1', text: WIND, suggested_answer: 'Dome' });
    await projects.note(trip, { block: 'Q1', suggested_answer: 'Lake Como' });
    await projects.markDone(trip, 'A1');
    await timeline.open(project);

    const item = timeline.item(trip);
    await expect(item.send).toBeDisabled();
    await expect(item.send).toHaveAttribute('title', 'Answer every block that has no recommendation first');

    await item.blockAt('Q1').answerField.fill('Lake Como');
    await item.blockAt('Q1').answerSend.click();
    await expect(item.send).toBeEnabled();
    await item.send.click();
    await expect(timeline.sendDialog.lines).toHaveText(['Which tent? · Dome']);
    await timeline.sendDialog.confirm.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    expect((await projects.document(trip)).body!.flatMap((part) => (part.type === 'block' ? [part.block] : []))[0].answer).toBe('Dome');
  });
});

test.describe('Taking Pilot’s note', () => {
  test('in a document answers the block as the person’s own, its note with it, words no option has as free words, until another answer; on an action puts a note alone in the paste-back, the Done still the person’s', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Noted'), members: [me.handle!] });
    const trip = await projects.place(project, { kind: 'document', title: 'The trip', text: TRIP });
    await projects.note(trip, { block: 'D1', text: WIND, suggested_answer: 'Tunnel', suggested_note: STAKES });
    await projects.note(trip, { block: 'Q1', suggested_answer: 'Lake Como', suggested_note: FERRY });
    await projects.note(trip, { block: 'A1', suggested_note: CARD });
    await timeline.open(project);
    const blocks = async () => (await projects.document(trip)).body!.flatMap((part) => (part.type === 'block' ? [part.block] : []));

    const item = timeline.item(trip);
    const tent = item.blockAt('D1');
    await expect(tent.pilotsNote.take).toHaveText('Take this answer');
    await expect(tent.pilotsNote.take).toHaveAttribute('title', /its note with it/);
    await tent.pilotsNote.take.click();
    await expect(tent.answered).toBeVisible();
    await expect(tent.option('Tunnel')).toHaveAttribute('data-chosen', 'true');
    await expect(tent.note).toHaveText(STAKES);
    expect((await blocks())[0]).toMatchObject({ answer: 'Tunnel', note: STAKES, by: { kind: 'person' } });
    // Taken, the note is its line, and opened offers nothing more to take.
    await expect(tent.pilotsNote.line).toHaveText('Pilot would have answered Tunnel');
    await tent.pilotsNote.toggle.click();
    await expect(tent.pilotsNote.take).toHaveCount(0);
    // Another answer is the person's to give, and the note offers its own again.
    await tent.option('Dome').click();
    await expect(tent.option('Dome')).toHaveAttribute('data-chosen', 'true');
    await expect(tent.pilotsNote.take).toBeVisible();

    const pitch = item.blockAt('Q1');
    await pitch.pilotsNote.take.click();
    await expect(pitch.answered).toBeVisible();
    expect((await blocks())[1]).toMatchObject({ answer: 'Lake Como', note: FERRY });

    const van = item.blockAt('A1');
    await expect(van.pilotsNote.take).toHaveText('Take this note');
    await van.pilotsNote.take.click();
    await expect(van.paste).toHaveValue(CARD);
    await expect(van.answered).toHaveCount(0);
    expect((await blocks())[2].done).toBeNull();
    await van.paste.fill(`${CARD} Pick it up on Friday.`);
    await van.done.click();
    await expect(van.answered).toBeVisible();
    expect((await blocks())[2]).toMatchObject({ note: `${CARD} Pick it up on Friday.` });
    await expect(van.pilotsNote.root).toHaveAttribute('data-line', 'true');

    // Words no option has are free words, Other's row chosen with them.
    await projects.note(trip, { block: 'D1', suggested_answer: BELL });
    await timeline.open(project);
    await tent.pilotsNote.toggle.click();
    await tent.pilotsNote.take.click();
    await expect(tent.other).toHaveAttribute('data-chosen', 'true');
    await expect(tent.other).toContainText(BELL);
    // The row shows chosen from the click, while the answer saves.
    await expect.poll(async () => (await blocks())[0]).toMatchObject({ answer: BELL, note: null });
  });

  test('in a one-ask decision chooses the answer and puts its note in the field its Send carries, both the person’s to change and kept over a reload; words no option has open Other with them', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Noted'), members: [me.handle!] });
    const tent = await projects.place(project, { kind: 'decision', title: 'Which tent?', text: TENT });
    await projects.note(tent, { block: 'D1', text: WIND, suggested_answer: 'Tunnel', suggested_note: STAKES });
    await timeline.open(project);

    const item = timeline.item(tent);
    const block = item.block;
    await expect(block.noteField).toHaveCount(0);
    await expect(block.pilotsNote.take).toHaveAttribute('title', /before you send it/);
    await block.pilotsNote.take.click();
    await expect(block.option('Tunnel')).toHaveAttribute('data-chosen', 'true');
    await expect(block.noteField).toHaveValue(STAKES);
    await expect(block.answerSend).toBeEnabled();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    expect((await projects.block(project, tent)).answer).toBeNull();

    await block.option('Dome').click();
    await block.noteField.fill('');
    await expect(block.noteField).toBeVisible();
    await block.noteField.fill(`${STAKES} And a mallet.`);
    await timeline.open(project);
    await expect(block.option('Dome')).toHaveAttribute('data-chosen', 'true');
    await expect(block.noteField).toHaveValue(`${STAKES} And a mallet.`);
    await block.answerSend.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    expect(await projects.block(project, tent)).toMatchObject({ answer: 'Dome', note: `${STAKES} And a mallet.` });

    const other = await projects.place(project, { kind: 'decision', title: 'Which tent, again?', text: TENT });
    await projects.note(other, { block: 'D1', suggested_answer: BELL });
    await timeline.open(project);
    const again = timeline.item(other).block;
    await again.pilotsNote.take.click();
    await expect(again.console).toBeVisible();
    await expect(again.field).toHaveValue(BELL);
    await expect(again.noteField).toHaveCount(0);
    await again.answerSend.click();
    await expect(timeline.item(other).root).toHaveAttribute('data-state', 'done');
    expect(await projects.block(project, other)).toMatchObject({ answer: BELL, note: null });
  });

  test('in a one-ask question puts the answer in its field, and in a one-ask action chooses the option, the note in the field its Send carries', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Noted'), members: [me.handle!] });
    const pitch = await projects.place(project, { kind: 'question', title: 'Where do we pitch?', text: PITCH });
    await projects.note(pitch, { block: 'Q1', suggested_answer: 'Lake Como', suggested_note: FERRY });
    const van = await projects.place(project, { kind: 'action', title: 'Book the van', text: '```action id=A1\noptions:\n  - Booked\n  - Not needed\n```\n' });
    await projects.note(van, { block: 'A1', suggested_answer: 'Booked', suggested_note: CARD });
    await timeline.open(project);

    const question = timeline.item(pitch).block;
    await question.pilotsNote.take.click();
    await expect(question.answerField).toHaveValue('Lake Como');
    await expect(question.noteField).toHaveValue(FERRY);
    expect((await projects.block(project, pitch)).answer).toBeNull();
    await question.answerSend.click();
    await expect(timeline.item(pitch).root).toHaveAttribute('data-state', 'done');
    expect(await projects.block(project, pitch)).toMatchObject({ answer: 'Lake Como', note: FERRY });

    const action = timeline.item(van).block;
    await action.pilotsNote.take.click();
    await expect(action.act('Booked')).toHaveAttribute('data-chosen', 'true');
    await expect(action.paste).toHaveValue(CARD);
    await expect(action.noteField).toHaveCount(0);
    expect((await projects.block(project, van)).answer).toBeNull();
    await action.answerSend.click();
    await expect(timeline.item(van).root).toHaveAttribute('data-state', 'done');
    expect(await projects.block(project, van)).toMatchObject({ answer: 'Booked', note: CARD });
  });
});
