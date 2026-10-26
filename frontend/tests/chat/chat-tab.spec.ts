/**
 * The side panel's Chat tab (F38, F40, F44, F130.1), on 008's rendering of a reply. The panel opens
 * on it, the first of its two tabs, until the person picks another (F38.1). It shows the project's
 * latest chat, streamed: each person's message on the right in the primary's tint, its time and
 * avatar under it and another person's name before the time (F38.2; the chat mockup's decision 13),
 * a quote it opens with over it and one inside it a chip, each going to what it quotes (F39.3);
 * Pilot's reply bare in the column, the server's lines while the session comes up in the cue alone
 * (F40.2), the phantom while a block streams (F40.4), then its time and avatar, "· Stopped" by a
 * stopped turn's and its reason in red and "· Failed" by a failed one's (F44); a date divider over
 * each day's first message. A chat that opens while the tab shows comes in; another person's turn
 * streams to every viewer alike. With no chat open the latest closed one shows above "Chat closed ·
 * <time>", and the next message starts a new chat below it; "The chat before · <day>" at the top
 * loads that chat above what is in view and leaves the view where it is (F130.1). Nothing stands in
 * it while its read is under way, and "The chat did not load." where it fails (F113). On a phone it
 * is the same column, the composer under it (F98.3; the composer's own specs: composer.spec.ts).
 */

import { test, expect } from '../support/fixtures';
import { expectConsoleError, makeUnique } from '../support/helpers';
import { slowNetwork } from '../support/network';
import { addressOf } from '../support/page-objects/timeline-page';

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));
const dayOf = (at: string) =>
  new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long', timeZone: ZONE }).format(new Date(at));

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '9b2e4c71-3a5d-4f8e-b6c0-2d7a1e5f9c38';
const line = (value: object) => JSON.stringify({ ...value, session_id: CONVERSATION });
const text = (id: string, words: string) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] }, parent_tool_use_id: null });
const blockStart = () =>
  line({ type: 'stream_event', event: { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }, parent_tool_use_id: null });
const delta = (words: string) =>
  line({ type: 'stream_event', event: { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: words } }, parent_tool_use_id: null });

const EMPTY = 'Ask Pilot about this project: how a session is going, what an item means, a change to the plan. Discuss on an item quotes it here.';

// A reply long enough to fill the tab's view.
const LONG = ['The route, stage by stage:', '', ...Array.from({ length: 30 }, (_, index) => `${index + 1}. Stage ${index + 1}, by the lake.`)].join('\n');

test.describe('The Chat tab', () => {
  test('is the panel’s first tab and the one it opens on, says what to ask while the project has no chat, and stays the tab the person picked, kept in the browser', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
    panel,
    chat,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Tabs'), members: [me.handle!] });
    const read = chat.read();
    await timeline.open(project);
    await read;

    await expect(panel.head.getByRole('tab')).toHaveText(['Chat', 'Documents']);
    await expect(chat.tab).toHaveAttribute('aria-selected', 'true');
    await expect(panel.documentsTab).toHaveAttribute('aria-selected', 'false');
    await expect(projectHead.documentsButton).toHaveAttribute('aria-pressed', 'false');
    await expect(chat.empty).toHaveText(EMPTY);
    await expect(chat.failed).toHaveCount(0);

    await panel.documentsTab.click();
    await expect(chat.root).toHaveCount(0);
    await expect(panel.projectDocument.root).toBeVisible();
    await expect(projectHead.documentsButton).toHaveAttribute('aria-pressed', 'true');
    const kept = () => page.evaluate(() => (JSON.parse(localStorage.getItem('pilot')!) as { panels: Record<string, unknown> }).panels);
    expect((await kept())[project]).toEqual({ open: true, tab: 'documents' });

    await timeline.open(project);
    await expect(panel.documentsTab).toHaveAttribute('aria-selected', 'true');
    await chat.tab.click();
    await expect(chat.empty).toHaveText(EMPTY);
    expect((await kept())[project]).toEqual({ open: true, tab: 'chat' });
  });

  test('streams a chat that opens while it shows: the person’s message on the right under the day, the server’s lines in the cue alone, the phantom, then the reply bare in the column over its time and Pilot’s avatar', async ({
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn({ name: 'Ada Example' });
    const project = await projects.make({ name: makeUnique('Chat'), members: [me.handle!] });
    const read = chat.read();
    await timeline.open(project);
    await read;
    await expect(chat.empty).toBeVisible();

    const { chat: id, session } = await chats.start(project, 'Which tent do we take?');
    await expect(chat.messageTexts).toHaveText(['Which tent do we take?']);
    await expect(chat.empty).toHaveCount(0);
    const sent = (await projects.records(id)).records.find((record) => record.kind === 'send')!;
    await expect(chat.days).toHaveText([dayOf(sent.at)]);
    // Their own message carries no name: its time, and their avatar.
    await expect(chat.names).toHaveCount(0);
    await expect(chat.messageEnds.locator('time')).toHaveText([clock(sent.at)]);
    await expect(chat.messageEnds.locator('.avatar')).toHaveAttribute('title', 'Ada Example');
    // The server's lines while the session comes up show in the cue, and nowhere else.
    await expect(chat.cue).toHaveText('Creating the session');
    await expect(chat.texts).toHaveCount(0);
    await expect(chat.replyEnds).toHaveCount(0);

    await controller.play(chats.store, session, [blockStart(), delta('The dome ')]);
    await expect(chat.phantom).toHaveText('The dome');
    await expect(chat.cue).toHaveText('Writing');
    await controller.play(chats.store, session, [delta('is lighter.'), text('one', 'The dome is lighter.')]);
    await expect(chat.phantom).toHaveCount(0);
    await expect(chat.texts).toHaveText(['The dome is lighter.']);
    await controller.finish(chats.store, session, 'success', 'The dome is lighter.');
    const { records } = await projects.records(id);
    await expect(chat.replyEnds).toHaveText([clock(records.at(-1)!.at)]);
    await expect(chat.replyEnds.locator('.avatar')).toHaveAttribute('title', 'Pilot');
    await expect(chat.cue).toHaveCount(0);

    // The message on the right, at least 9 % of the column free on its left; the reply from its left.
    const [column, message, reply] = await Promise.all([chat.body, chat.messageTexts.first(), chat.texts.first()].map(async (each) => (await each.boundingBox())!));
    expect(message.x).toBeGreaterThan(column.x + column.width * 0.09);
    expect(message.x + message.width).toBeGreaterThan(column.x + column.width - 32);
    expect(reply.x).toBeLessThan(column.x + 32);
  });

  test('shows another person’s message with their name before its time and their avatar, and streams their turn to the viewer as to them', async ({
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn({ name: 'Ada Example' });
    const bea = await chats.other('Bea Example', makeUnique('bea', 8));
    const project = await projects.make({ name: makeUnique('Watched'), members: [me.handle!, bea.handle] });
    const read = chat.read();
    await timeline.open(project);
    await read;

    const { chat: id, session } = await chats.start(project, 'Can we go in May?', bea);
    await expect(chat.messageTexts).toHaveText(['Can we go in May?']);
    await expect(chat.names).toHaveText(['Bea Example']);
    await expect(chat.messageEnds.locator('.avatar')).toHaveAttribute('title', 'Bea Example');
    const live = chat.live(id);
    await expect(chat.cue).toHaveText('Creating the session');
    await live;
    await controller.play(chats.store, session, [blockStart(), delta('May works ')]);
    await expect(chat.phantom).toHaveText('May works');
    await controller.play(chats.store, session, [delta('for both of you.'), text('may', 'May works for both of you.')]);
    await expect(chat.texts).toHaveText(['May works for both of you.']);
    await controller.finish(chats.store, session, 'success', 'May works for both of you.');
    await expect(chat.replyEnds).toHaveCount(1);

    // The viewer's own message in the same chat: no name, and the two in their order.
    await chats.send(project, 'Then May it is.');
    await expect(chat.messageTexts).toHaveText(['Can we go in May?', 'Then May it is.']);
    await expect(chat.names).toHaveText(['Bea Example']);
    await chats.working(session);
    await controller.play(chats.store, session, [text('noted', 'Noted.')]);
    await controller.finish(chats.store, session, 'success', 'Noted.');
    await expect(chat.texts).toHaveText(['May works for both of you.', 'Noted.']);
    await expect(chat.replyEnds).toHaveCount(2);
    await expect(chat.days).toHaveCount(1);
  });

  test('shows a quote a message opens with over it and one inside it as a chip, each going to what it quotes; the words as written', async ({
    page,
    people,
    projects,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Quoted'), members: [me.handle!] });
    const packing = await projects.place(project, {
      kind: 'document',
      title: 'Packing',
      text: '## Which tent?\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n',
    });
    const words = [
      `<quoted_item id="${packing}">Packing</quoted_item id="${packing}">`,
      'Is *this* still open, or settled in',
      `<quoted_block id="${packing}/D1">Which tent?</quoted_block id="${packing}/D1">?`,
      '<quoted_path path="notes.md">Notes</quoted_path path="notes.md">',
    ].join(' ');
    await chats.start(project, words);
    await timeline.open(project);

    await expect(chat.quotes).toHaveText(['Packing', 'Which tent?']);
    await expect(chat.quotes.first()).toHaveAttribute('data-quote', `item ${packing}`);
    await expect(chat.messageTexts).toHaveText(
      'Is *this* still open, or settled in Which tent?? <quoted_path path="notes.md">Notes</quoted_path path="notes.md">',
    );
    const [line, text] = await Promise.all([chat.quotes.first().boundingBox(), chat.messageTexts.boundingBox()]);
    expect(line!.y + line!.height).toBeLessThanOrEqual(text!.y);
    await expect(chat.messageTexts.getByTestId('chat.quote')).toHaveText(['Which tent?']);

    await chat.messageTexts.getByTestId('chat.quote').click();
    await expect(page).toHaveURL(addressOf(project, packing, 'D1'));
    await page.goBack();
    await chat.quotes.first().click();
    await expect(page).toHaveURL(addressOf(project, packing));
  });

  test('shows a stopped turn as it streamed, its half-written block gone, with “· Stopped” by its time; a failed one its reason in red and “· Failed”', async ({
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Stopped'), members: [me.handle!] });
    await timeline.open(project);
    const { chat: id, session } = await chats.start(project, 'Survey the campsites.');
    const live = chat.live(id);
    await expect(chat.cue).toHaveText('Creating the session');
    await live;

    await controller.play(chats.store, session, [text('first', 'Three sites so far.'), blockStart(), delta('The fourth ')]);
    await expect(chat.phantom).toHaveText('The fourth');
    await chats.stop(project);
    await expect(chat.phantom).toHaveCount(0);
    await expect(chat.texts).toHaveText(['Three sites so far.']);
    const stopped = (await projects.records(id)).records.at(-1)!;
    await expect(chat.replyEnds).toHaveText([`${clock(stopped.at)}· Stopped`]);

    await chats.send(project, 'Carry on.');
    await chats.working(session);
    await controller.finish(chats.store, session, 'error', 'The model is overloaded.');
    await expect(chat.failures).toHaveText(['The model is overloaded.']);
    await expect(chat.failures.locator('[class*="text-destructive"]')).toHaveCount(1);
    const failed = (await projects.records(id)).records.at(-1)!;
    await expect(chat.replyEnds.last()).toHaveText(`${clock(failed.at)}· Failed`);
    await expect(chat.replyEnds.last().getByText('· Failed')).toHaveClass(/text-destructive-text/);
  });

  test('Archive closes the chat open then, its “Chat closed · <time>” coming while the tab shows', async ({ people, projects, controller, timeline, chat, chats }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Archived'), members: [me.handle!] });
    await timeline.open(project);
    const { session } = await chats.start(project, 'Wrap it up.');
    await controller.play(chats.store, session, [text('done', 'All wrapped up.')]);
    await controller.finish(chats.store, session, 'success', 'All wrapped up.');
    await expect(chat.replyEnds).toHaveCount(1);
    await expect(chat.closed).toHaveCount(0);

    await projects.transition(project, 'archived');
    const [closed] = (await chats.list(project)).chats;
    expect(closed!.close_cause).toBe('archived');
    await expect(chat.closed).toHaveText(`Chat closed · ${clock(closed!.closed_at!)}`);
    await expect(chat.texts).toHaveText(['All wrapped up.']);
  });
});

test.describe('The Chat tab’s closed chats', () => {
  test.use({ viewport: { width: 1280, height: 600 } });

  test('shows a closed chat above “Chat closed · <time>” and the next message’s chat below it; opened again, the latest alone, “The chat before · <day>” loading that chat above what is in view and leaving the view where it is', async ({
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Closed'), members: [me.handle!] });
    await timeline.open(project);
    const first = await chats.start(project, 'Plan the route.');
    await controller.play(chats.store, first.session, [text('route', LONG)]);
    await controller.finish(chats.store, first.session, 'success', LONG);
    await expect(chat.replyEnds).toHaveCount(1);

    // Finish closes the chat; after Reopen the next message starts another, below the line.
    await projects.transition(project, 'finished');
    const [closed] = (await chats.list(project)).chats;
    await expect(chat.closed).toHaveText(`Chat closed · ${clock(closed!.closed_at!)}`);
    await projects.transition(project, 'reopened');
    const second = await chats.start(project, 'And the tent?');
    await controller.play(chats.store, second.session, [text('tent', 'The dome.')]);
    await controller.finish(chats.store, second.session, 'success', 'The dome.');
    await expect(chat.messageTexts).toHaveText(['Plan the route.', 'And the tent?']);
    await expect(chat.lines.and(chat.root.getByTestId('chat.closed').or(chat.messages))).toHaveCount(3);
    const [above, line, below] = await Promise.all(
      [chat.messages.first(), chat.closed, chat.messages.last()].map(async (each) => (await each.boundingBox())!.y),
    );
    expect(above).toBeLessThan(line!);
    expect(line).toBeLessThan(below!);
    await expect(chat.before).toHaveCount(0);

    // Opened again: the latest chat alone, the one before behind *load more*.
    await timeline.open(project);
    await expect(chat.texts).toHaveText(['The dome.']);
    await expect(chat.messageTexts).toHaveText(['And the tent?']);
    await expect(chat.closed).toHaveCount(0);
    await expect(chat.before).toHaveText(`The chat before · ${dayOf(closed!.opened_at)}`);
    const at = await chat.top(chat.messages.first());

    await chat.before.click();
    await expect(chat.messageTexts).toHaveText(['Plan the route.', 'And the tent?']);
    await expect(chat.texts.first()).toContainText('Stage 30, by the lake.');
    await expect(chat.closed).toHaveCount(1);
    await expect(chat.before).toHaveCount(0);
    await expect.poll(async () => Math.abs((await chat.top(chat.messages.last())) - at)).toBeLessThanOrEqual(1);
    expect(await chat.top(chat.messages.first())).toBeLessThan(0);
  });
});

test.describe('The Chat tab’s read', () => {
  // Below 1200 px the panel starts closed: the project is read before the tab opens.
  test.use({ viewport: { width: 1100, height: 800 } });

  test('draws nothing while it is on its way, then says what to ask where the project has no chat', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
    panel,
    chat,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Pending'), members: [me.handle!] });
    await timeline.open(project);
    await projectHead.documentsButton.click();
    await expect(panel.projectDocument.root).toBeVisible();

    const restore = await slowNetwork(page, 1_000);
    const read = chat.read();
    await chat.tab.click();
    await expect(chat.root).toBeVisible();
    await expect(chat.empty).toHaveCount(0);
    await expect(chat.failed).toHaveCount(0);
    await expect(chat.lines).toHaveCount(0);

    await read;
    await restore();
    await expect(chat.empty).toHaveText(EMPTY);
    await expect(chat.failed).toHaveCount(0);
  });

  test('says “The chat did not load.” where it fails, and draws the chat once a later read lands', async ({
    page,
    auth,
    people,
    projects,
    projectHead,
    timeline,
    controller,
    chat,
    chats,
  }) => {
    const subject = makeUnique('subject');
    const me = await people.signIn({ subject });
    const project = await projects.make({ name: makeUnique('Failed'), members: [me.handle!] });
    const { session } = await chats.start(project, 'Is the tent packed?');
    await controller.play(chats.store, session, [text('packed', 'It is packed.')]);
    await controller.finish(chats.store, session, 'success', 'It is packed.');
    await timeline.open(project);
    await projectHead.documentsButton.click();

    // The browser's session now lacks the editor role, and the API refuses the tab's read.
    await expectConsoleError(page, /403/);
    await auth.createSession({ subject, name: 'Test Person', roles: [] });
    await chat.tab.click();
    await expect(chat.failed).toHaveText('The chat did not load.');
    await expect(chat.messages).toHaveCount(0);
    await expect(chat.empty).toHaveCount(0);

    // The same person with the role again, whose browser's connection the chat's stream takes.
    await people.firstSignIn({ subject });
    await timeline.refocus();
    await expect(chat.failed).toHaveCount(0);
    await expect(chat.messageTexts).toHaveText(['Is the tent packed?']);
    await expect(chat.texts).toHaveText(['It is packed.']);
  });
});

test.describe('The Chat tab on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('is the same column, the whole screen: the message on the right, the reply bare from the left, nothing more collapsed', async ({
    people,
    projects,
    projectHead,
    controller,
    timeline,
    panel,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Phone'), members: [me.handle!] });
    const { session } = await chats.start(project, 'Which tent do we take?');
    await controller.play(chats.store, session, [text('one', 'The dome is lighter.')]);
    await controller.finish(chats.store, session, 'success', 'The dome is lighter.');
    await timeline.open(project);
    await projectHead.documentsButton.click();
    await chat.tab.click();

    await expect(chat.messageTexts).toHaveText(['Which tent do we take?']);
    await expect(chat.texts).toHaveText(['The dome is lighter.']);
    await expect(chat.days).toHaveCount(1);
    await expect(chat.messageEnds).toHaveCount(1);
    await expect(chat.replyEnds).toHaveCount(1);
    const [side, message, reply] = await Promise.all([panel.root, chat.messageTexts.first(), chat.texts.first()].map(async (each) => (await each.boundingBox())!));
    expect(side.x).toBe(0);
    expect(side.width).toBeCloseTo(390, 0);
    expect(message.x + message.width).toBeGreaterThan(390 - 40);
    expect(message.x).toBeGreaterThan(390 * 0.09);
    expect(reply.x).toBeLessThan(32);
    // The composer under it, across the column at the screen's foot.
    const composer = (await chat.composer.boundingBox())!;
    expect(composer.x).toBe(0);
    expect(composer.width).toBeCloseTo(390, 0);
    expect(composer.y + composer.height).toBeCloseTo(side.y + side.height, 0);
  });
});
