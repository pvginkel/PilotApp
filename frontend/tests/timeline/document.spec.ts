/**
 * A document inline (F24.1): its head "Document · N", its title, its prose with every block
 * answered in place, each in a panel of its own whose head names its kind (F31.1), and the segment
 * bar beside *Send answers* (F33), a segment going to its block; its answers changing until it is
 * sent (F32.2); *Unsent* while it has an answer and no Done, Pilot's included, never for a deferral,
 * a recommendation or a held save (D026); *Send answers* enabling once every block is answered or
 * recommended, and listing the unanswered recommended blocks in a dialog whose Confirm records them
 * (F24.3, F32.5); a confirmation block answered Yes and No in its block form (F22.7); Pilot's dots
 * while it writes (F35) and *Edited <time>* once a later turn changed it (F28.7); and a document
 * Pilot settled whole and marked Done, a done line from the start.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { Projects } from '../support/projects';
import type { components } from '@/lib/api/generated/types';

type Block = components['schemas']['TimelineSchema.1fdd8ae.BlockSchema'];
type TimelineItem = components['schemas']['TimelineSchema.1fdd8ae.TimelineItemSchema'];

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));

const TENT = '```decision id=D1\noptions:\n  - Dome: up in five minutes\n  - Tunnel\nrecommend: Dome\n```\n';
const PITCH = '```question id=Q1\ndefault: Lake Garda\n```\n';
const VAN = '```action id=A1\n```\n';
const TRIP = [
  'We leave on Friday.\n',
  '## Which tent?\n',
  TENT,
  '## Where do we pitch?\n',
  PITCH,
  '## Book the van\n',
  VAN,
  'We pack on Thursday.\n',
].join('\n');
const PILOTS_TENT = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nanswer: Dome\nby: agent\nat: 2026-10-20T09:00:00Z\n```\n';
const DEFERRED_TENT = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nanswer: deferred\nby: agent\nat: 2026-10-20T09:00:00Z\nto: plan\n```\n';
const PILOTS_PITCH = '```question id=Q1\nanswer: Lake Garda\nby: agent\nat: 2026-10-20T09:00:00Z\n```\n';
const CONFIRMING = [
  'The tag is cut and the notes are written.\n',
  '```decision id=C1\ntype: confirmation\nproposal: Push the release to production\nbecause: auto-pilot-off\n```\n',
  '```question id=Q1\n```\n',
].join('\n');

/** An item as the API reads it. */
async function itemOf(projects: Projects, project: string, item: string): Promise<TimelineItem> {
  return (await projects.timeline(project)).items.find((each) => each.id === item)!;
}

/** A document's block as the API reads it. */
async function blockOf(projects: Projects, project: string, item: string, block: string): Promise<Block> {
  const found = await itemOf(projects, project, item);
  return found.body!.flatMap((part) => (part.type === 'block' ? [part.block] : [])).find((each) => each.id === block)!;
}

test.describe('A short document', () => {
  test('stands inline: its title, its prose and every block in a panel of its own in their order, the segment bar beside Send answers', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Inline'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await timeline.open(id);
    const item = timeline.item(trip);

    await expect(item.kind).toHaveText('Document · 3');
    await expect(item.title).toHaveText('The trip');
    expect(await item.document.locator('> *').evaluateAll((parts) => parts.map((part) => part.className))).toEqual([
      'prose',
      'prose',
      'block open',
      'prose',
      'block open',
      'prose',
      'block open',
      'prose',
    ]);
    await expect(item.document.locator('> .prose').first()).toHaveText('We leave on Friday.');
    await expect(item.document.locator('> .prose').nth(1).locator('h2')).toHaveText('Which tent?');
    await expect(item.document.locator('> .prose').last()).toHaveText('We pack on Thursday.');

    // Each block's head names its kind, as the item's head does not; none is answered.
    await expect(item.blockAt('D1').kind).toHaveText('Decision');
    await expect(item.blockAt('D1').options).toHaveCount(2);
    await expect(item.blockAt('Q1').kind).toHaveText('Question');
    await expect(item.blockAt('Q1').answerField).toHaveAttribute('placeholder', 'Default: Lake Garda');
    await expect(item.blockAt('A1').kind).toHaveText('Action');
    await expect(item.blockAt('A1').done).toHaveText('Done');
    await expect(item.root.getByTestId('timeline.block.answered')).toHaveCount(0);

    await expect(item.segments).toHaveCount(3);
    expect(await item.segments.evaluateAll((segments) => segments.map((segment) => segment.getAttribute('title')))).toEqual([
      'Which tent? · open',
      'Where do we pitch? · open',
      'Book the van · open',
    ]);
    // The action has no recommendation: nothing sends until it is done.
    await expect(item.send).toHaveText('Send answers');
    await expect(item.send).toBeDisabled();
    const bar = (await item.root.getByTestId('timeline.segments').boundingBox())!;
    const send = (await item.send.boundingBox())!;
    expect(send.x).toBeGreaterThan(bar.x + bar.width);
    expect(Math.abs(send.y + send.height / 2 - (bar.y + bar.height / 2))).toBeLessThan(2);

    await expect(item.unsent).toHaveCount(0);
    await expect(item.edited).toHaveCount(0);
    await expect(item.writing).toHaveCount(0);
  });

  test('takes each answer in place and keeps it open to change until sent; its segment fills, and the document reads Unsent', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Answers'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await timeline.open(id);
    const item = timeline.item(trip);
    const tent = item.blockAt('D1');

    await tent.option('Tunnel').click();
    await expect(item.unsent).toHaveText('Unsent');
    await expect(item.segment('D1')).toHaveClass(/\bdone\b/);
    await expect(item.segment('D1')).toHaveAttribute('title', 'Which tent? · answered');
    await expect(item.segment('Q1')).not.toHaveClass(/\bdone\b/);
    await expect(tent.answered).toBeVisible();
    await expect(tent.option('Tunnel')).toHaveAttribute('data-chosen', 'true');
    // A person's answer stays open until Done: every option takes another answer.
    await expect(tent.option('Dome')).toBeEnabled();
    expect(await blockOf(projects, id, trip, 'D1')).toMatchObject({ answer: 'Tunnel', by: { kind: 'person', handle: me.handle } });

    await tent.option('Dome').click();
    await expect(tent.option('Dome')).toHaveAttribute('data-chosen', 'true');
    await expect(tent.option('Tunnel')).toBeEnabled();
    await expect.poll(async () => (await blockOf(projects, id, trip, 'D1')).answer).toBe('Dome');

    const pitch = item.blockAt('Q1');
    await pitch.answerField.fill('The north shore');
    await pitch.answerSend.click();
    await expect(item.segment('Q1')).toHaveClass(/\bdone\b/);
    await expect(pitch.answerField).toHaveValue('The north shore');
    await expect(pitch.answerField).toBeEditable();

    await expect(item.send).toBeDisabled();
    await item.blockAt('A1').done.click();
    await expect(item.segment('A1')).toHaveClass(/\bdone\b/);
    await expect(item.blockAt('A1').said).toHaveText('Done');
    await expect(item.send).toBeEnabled();
    await expect(item.root).toHaveAttribute('data-state', 'open');
  });

  test('sends at once when every block is answered, and is its done line', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Sent'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await projects.answer(trip, 'D1', 'Tunnel');
    await projects.answer(trip, 'Q1', 'The north shore');
    await projects.markDone(trip, 'A1');
    await timeline.open(id);
    const item = timeline.item(trip);

    await item.send.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(timeline.sendDialog.root).toHaveCount(0);
    await expect(item.lineTitle).toHaveText('The trip');
    await expect(item.said).toHaveCount(0);
    const done = await itemOf(projects, id, trip);
    expect(done.done).toMatchObject({ cause: 'marked', by: { kind: 'person', handle: me.handle } });
    expect(await blockOf(projects, id, trip, 'D1')).toMatchObject({ answer: 'Tunnel', via: 'app' });
  });

  test('lists the unanswered recommended blocks in a dialog: Cancel leaves them, Confirm records each recommendation as the answer', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Recommended'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await projects.markDone(trip, 'A1');
    await timeline.open(id);
    const item = timeline.item(trip);
    const { sendDialog } = timeline;

    // An action's Done is an answer.
    await expect(item.unsent).toBeVisible();
    await expect(item.send).toBeEnabled();
    await item.send.click();
    await expect(sendDialog.root).toBeVisible();
    await expect(sendDialog.lines).toHaveText(['Which tent? · Dome', 'Where do we pitch? · Lake Garda']);
    await expect(sendDialog.confirm).toHaveText('Confirm');
    await expect(sendDialog.cancel).toBeFocused();

    await sendDialog.cancel.click();
    await expect(sendDialog.root).toHaveCount(0);
    await expect(item.root).toHaveAttribute('data-state', 'open');
    expect((await blockOf(projects, id, trip, 'D1')).answer).toBeNull();

    await item.send.click();
    await sendDialog.confirm.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(sendDialog.root).toHaveCount(0);
    const answer = { by: { kind: 'person', handle: me.handle }, via: 'recommended' };
    expect(await blockOf(projects, id, trip, 'D1')).toMatchObject({ answer: 'Dome', ...answer });
    expect(await blockOf(projects, id, trip, 'Q1')).toMatchObject({ answer: 'Lake Garda', ...answer });
  });

  test('names a proposal and a confirmation in the dialog by what Yes and Agree do', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Proposals'), members: [me.handle!] });
    const text = [
      '```decision id=D1\nproposal: Take the dome\n```\n',
      '```decision id=C1\ntype: confirmation\nproposal: Book the van\nbecause: auto-pilot-off\n```\n',
    ].join('\n');
    const plans = await projects.place(id, { kind: 'document', title: 'The plans', text });
    await timeline.open(id);

    await timeline.item(plans).send.click();
    await expect(timeline.sendDialog.lines).toHaveText(['Decision · Agree: Take the dome', 'Confirm · Yes: Book the van']);
  });

  test('reads Unsent for Pilot’s answer, but not for a deferral alone, a recommendation or a held save', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Unsent'), members: [me.handle!] });
    const answered = await projects.place(id, { kind: 'document', title: 'Pilot answered', text: `${PILOTS_TENT}\n${PITCH}` });
    const deferred = await projects.place(id, { kind: 'document', title: 'Pilot deferred', text: `${DEFERRED_TENT}\n${PITCH}` });
    const recommended = await projects.place(id, { kind: 'document', title: 'Recommended', text: `${TENT}\n${PITCH}` });
    const held = await projects.place(id, { kind: 'document', title: 'Held', text: `${TENT}\n${PITCH}` });
    const save = await projects.save(held, '```decision id=D1\noptions:\n  - Dome\n  - Dome\n```\n');
    expect(save.held).toBe(true);
    await timeline.open(id);

    await expect(timeline.item(answered).unsent).toHaveText('Unsent');
    await expect(timeline.item(answered).blockAt('D1').who.locator('.avatar')).toHaveAttribute('title', 'Pilot');
    await expect(timeline.item(deferred).blockAt('D1').deferred).toBeVisible();
    await expect(timeline.item(deferred).segment('D1')).toHaveClass(/\bdone\b/);
    await expect(timeline.item(deferred).unsent).toHaveCount(0);
    await expect(timeline.item(recommended).unsent).toHaveCount(0);
    await expect(timeline.item(held).root).toHaveAttribute('data-concept', 'true');
    await expect(timeline.item(held).unsent).toHaveCount(0);
  });

  test('a segment goes to its block and flashes it', async ({ page, people, projects, timeline }) => {
    await page.setViewportSize({ width: 1280, height: 420 });
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Segments'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await timeline.open(id);
    const item = timeline.item(trip);
    const tent = item.blockAt('D1').root;
    await expect(tent).not.toBeInViewport();

    await item.segment('D1').click();
    await expect(tent).toHaveClass(/\bflash\b/);
    await expect(tent).toBeInViewport();
  });

  test('a document over about 150 words does not stand inline', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Long'), members: [me.handle!] });
    const words = Array.from({ length: 160 }, (_, index) => `word${index}`).join(' ');
    const long = await projects.place(id, { kind: 'document', title: 'The long trip', text: `${words}\n\n${TENT}\n${PITCH}` });
    await timeline.open(id);
    const item = timeline.item(long);

    await expect(item.kind).toHaveText('Document · 2');
    await expect(item.title).toHaveText('The long trip');
    await expect(item.card.root).toBeVisible();
    await expect(item.document).toHaveCount(0);
    await expect(item.send).toHaveCount(0);
  });
});

test.describe('A confirmation block in a document', () => {
  test('is answered Yes through its check, the document staying open and Unsent', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Block yes'), members: [me.handle!] });
    const release = await projects.place(id, { kind: 'document', title: 'The release', text: CONFIRMING });
    await timeline.open(id);
    const item = timeline.item(release);
    const confirm = item.blockAt('C1');

    await expect(confirm.kind).toHaveText('Confirm');
    await expect(confirm.root.getByTestId('timeline.confirm.proposal')).toHaveText('Push the release to production');
    await confirm.yes.click();
    await expect(confirm.yes).toHaveClass(/\bchosen\b/);
    await expect(confirm.answered).toBeVisible();
    await expect(item.unsent).toBeVisible();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(confirm.no).toBeEnabled();
    expect(await blockOf(projects, id, release, 'C1')).toMatchObject({ answer: 'Yes', note: null, by: { kind: 'person', handle: me.handle } });
  });

  test('is answered No through its cross, with the reason its console takes as the note', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Block no'), members: [me.handle!] });
    const release = await projects.place(id, { kind: 'document', title: 'The release', text: CONFIRMING });
    await timeline.open(id);
    const item = timeline.item(release);
    const confirm = item.blockAt('C1');

    await confirm.no.click();
    await confirm.noField.fill('Wait for the freeze to end.');
    await confirm.noSend.click();
    await expect(confirm.no).toHaveClass(/\bchosen\b/);
    await expect(confirm.note).toHaveText('Wait for the freeze to end.');
    await expect(item.unsent).toBeVisible();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    expect(await blockOf(projects, id, release, 'C1')).toMatchObject({
      answer: 'No',
      note: 'Wait for the freeze to end.',
      by: { kind: 'person', handle: me.handle },
    });
  });
});

test.describe('Pilot and a document', () => {
  test('its dots stand at the end of the text while Pilot writes it, and once the turn ended, Edited <time> in its head', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Writing'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await projects.save(trip, `${TRIP}\nWe pack light.\n`);
    await timeline.open(id);
    const item = timeline.item(trip);

    await expect(item.writing).toBeVisible();
    await expect(item.writing.locator('.avatar')).toHaveAttribute('title', 'Pilot');
    await expect(item.writing.locator('.dots > span')).toHaveCount(3);
    expect(await item.root.locator('.item-body > *').evaluateAll((parts) => parts.map((part) => part.className))).toEqual([
      'item-head',
      'item-title',
      'inline-doc',
      'typing',
      'item-actions doc-actions',
    ]);
    await expect(item.edited).toHaveCount(0);

    await projects.endTurn(id);
    await timeline.open(id);
    await expect(item.writing).toHaveCount(0);
    const { edited_at: edited } = await itemOf(projects, id, trip);
    await expect(item.edited).toHaveText(`Edited ${clock(edited!)}`);
    await expect(item.edited.locator('.avatar')).toHaveAttribute('title', 'Pilot');
    await expect(item.document.locator('> .prose').last()).toContainText('We pack light.');
  });

  test('its dots stand at the end of a one-ask item and a confirmation while Pilot writes them', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Writing asks'), members: [me.handle!] });
    const question = await projects.place(id, { kind: 'question', title: 'Where?', text: PITCH });
    const confirmation = await projects.place(id, {
      kind: 'confirmation',
      title: 'Ship it?',
      text: '```decision id=C1\ntype: confirmation\nproposal: Push the release\nbecause: auto-pilot-off\n```\n',
    });
    await projects.save(question, `Where do we pitch?\n\n${PITCH}`);
    await projects.save(confirmation, 'The tag is cut.\n\n```decision id=C1\ntype: confirmation\nproposal: Push the release\nbecause: auto-pilot-off\n```\n');
    await timeline.open(id);

    for (const each of [question, confirmation]) {
      const item = timeline.item(each);
      await expect(item.writing).toBeVisible();
      expect(await item.root.locator('.item-body > *').evaluateAll((parts) => parts.at(-1)!.className)).toBe('typing');
    }
  });

  test('a document Pilot settled whole and marked Done is a done line from the start', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Settled'), members: [me.handle!] });
    const settled = await projects.place(id, { kind: 'document', title: 'Settled', text: `${DEFERRED_TENT}\n${PILOTS_PITCH}` });
    await projects.doneByPilot(settled);
    await timeline.open(id);
    const item = timeline.item(settled);

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineTitle).toHaveText('Settled');
    await expect(item.said).toHaveCount(0);
    expect((await itemOf(projects, id, settled)).done).toMatchObject({ cause: 'settled', by: { kind: 'agent' } });
  });
});
