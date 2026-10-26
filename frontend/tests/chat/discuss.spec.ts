/**
 * Discuss (F39): on every item head, done line, block of a document, confirmation card, overlay
 * head and session log it opens the side panel on the Chat tab, on top, and puts what it stands on
 * in the composer as a chip that can be dropped, which the sent message carries as its tag before
 * the words (F38.3, F39.3); the handbook's, the project document's and an attachment's overlay
 * quote the file by its path in the project's folder. The head's Discuss toggles the Chat tab with
 * nothing quoted (F2.3, F39.2). Either puts the focus in the composer's field.
 *
 * The unread dot (F43) stands on the head's Discuss and the Chat tab while a reply of Pilot's came
 * after the person last saw the chat to its end; the chat shown at its end is marked seen, so a
 * reply watched arriving leaves none, one arriving below where the reader scrolled stands until they
 * scroll to the end, and another device of the person drops its dot at its next read of the list.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { ChatPage } from '../support/page-objects/chat-page';
import { ProjectHeadPage } from '../support/page-objects/project-head-page';
import { attachmentAddress, TimelinePage } from '../support/page-objects/timeline-page';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '7b2e9c41-3f8d-4a65-b1c0-5d9e2a7f8c36';
const text = (id: string, words: string) =>
  JSON.stringify({
    type: 'assistant',
    message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] },
    parent_tool_use_id: null,
    session_id: CONVERSATION,
  });

const DECISION = 'Which tent for the trip?\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
// Two asks: a document of one ask is that ask's item.
const PACKING =
  'What we take.\n\n## Which stove?\n\n```decision id=D1\noptions:\n  - Gas\n  - Spirit\n```\n\n## How many pegs?\n\n```question id=Q1\n```\n';
const CONFIRM = 'The tag is cut.\n\n```decision id=C1\ntype: confirmation\nproposal: Push the release\nbecause: auto-pilot-off\n```\n';
const NOTES = { title: 'Tent notes', filename: 'tent-notes.md', content_type: 'text/markdown', content: '# Tent notes\n\nThe dome is lighter.\n' };

const ROUTE = Array.from({ length: 40 }, (_, index) => `Stage ${index + 1}, by the lake.`).join('\n\n');

const itemTag = (id: string, title: string) => `<quoted_item id="${id}">${title}</quoted_item id="${id}">`;
const pathTag = (path: string, title: string) => `<quoted_path path="${path}">${title}</quoted_path path="${path}">`;

test.describe('Discuss', () => {
  test('on an item’s head opens the Chat tab, on top, the item quoted over the field, the focus in it; the quote can be dropped, and the message sent carries it as its tag before the words', async ({
    people,
    projects,
    controller,
    timeline,
    panel,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Discuss'), members: [me.handle!] });
    const decision = await projects.place(project, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await timeline.open(project);
    await panel.close.click();
    await expect(panel.root).toHaveCount(0);

    const item = timeline.item(decision);
    await expect(item.discuss).toHaveAttribute('title', 'Discuss: quote this into the project’s chat');
    // A one-ask item's block is quoted through its item's head.
    await expect(item.block.discuss).toHaveCount(0);
    await item.discuss.click();
    await expect(chat.tab).toHaveAttribute('aria-selected', 'true');
    await expect(chat.quote).toHaveAttribute('data-quote', `item ${decision}`);
    await expect(chat.quoteLabel).toHaveText('Which tent?');
    await expect(chat.field).toBeFocused();

    await chat.quoteRemove.click();
    await expect(chat.quote).toHaveCount(0);
    await expect(chat.field).toBeFocused();

    await item.discuss.click();
    await expect(chat.quoteLabel).toHaveText('Which tent?');
    await chat.field.fill('Dome or tunnel?');
    const opened = await chats.opening(project);
    const sent = chat.acted('send');
    await chat.send.click();
    await sent;
    const session = await opened();
    await expect(chat.quote).toHaveCount(0);
    await expect(chat.field).toHaveValue('');
    await expect(chat.field).toBeFocused();
    await expect(chat.messages.getByTestId('chat.quote')).toHaveAttribute('data-quote', `item ${decision}`);
    await expect(chat.messages.getByTestId('chat.quote')).toHaveText('Which tent?');
    await expect(chat.messageTexts).toHaveText(['Dome or tunnel?']);
    const [started] = (await chats.list(project)).chats;
    const send = (await projects.records(started!.id)).records.find((record) => record.kind === 'send')!;
    expect(send).toMatchObject({ message: `${itemTag(decision, 'Which tent?')} Dome or tunnel?` });
    await controller.finish(chats.store, session, 'success', 'The dome.');
  });

  test('on a document’s block, a done line, a confirmation card and a work item quotes each, a block by its item and its id, its label its heading and the item’s title', async ({
    people,
    projects,
    timeline,
    chat,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Everywhere'), members: [me.handle!] });
    const packing = await projects.place(project, { kind: 'document', title: 'Packing', text: PACKING });
    const notice = await projects.place(project, { kind: 'notice', title: 'Storm tonight', text: 'Tie the tent down.\n' });
    const confirmation = await projects.place(project, { kind: 'confirmation', title: 'Ship 1.2?', text: CONFIRM });
    const work = await projects.startWork(project, { title: 'Survey the stylesheets', brief: 'Survey them.', cwd: '/work/Example' });
    await timeline.open(project);
    await timeline.item(notice).read.click();
    await expect(timeline.item(notice).line).toBeVisible();

    const block = timeline.item(packing).blockAt('D1');
    await expect(block.discuss).toHaveAttribute('title', 'Discuss: quote this block into the project’s chat');
    await block.discuss.click();
    await expect(chat.quote).toHaveAttribute('data-quote', `block ${packing}/D1`);
    await expect(chat.quoteLabel).toHaveText('Which stove? · Packing');

    await timeline.item(notice).lineDiscuss.click();
    await expect(chat.quote).toHaveAttribute('data-quote', `item ${notice}`);
    await expect(chat.quoteLabel).toHaveText('Storm tonight');

    await timeline.item(confirmation).discuss.click();
    await expect(chat.quote).toHaveAttribute('data-quote', `item ${confirmation}`);
    await expect(chat.quoteLabel).toHaveText('Ship 1.2?');

    await timeline.item(work).discuss.click();
    await expect(chat.quote).toHaveAttribute('data-quote', `item ${work}`);
    await expect(chat.quoteLabel).toHaveText('Survey the stylesheets');
    await expect(chat.field).toBeFocused();
  });

  test('on an overlay’s head quotes what it shows: a document the item, the handbook, the project document and an attachment by their paths, a session log its work item', async ({
    people,
    projects,
    timeline,
    overlay,
    sessionLog,
    chat,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Overlays'), members: [me.handle!] });
    const packing = await projects.place(project, { kind: 'document', title: 'Packing', text: PACKING });
    await projects.saveProjectDocument(project, 'handbook', '# Camping handbook\n\nHow the trip is planned.\n');
    await projects.saveProjectDocument(project, 'draft', '# The trip plan\n\nWhere we go.\n');
    await projects.endTurn(project);
    const [notes] = await projects.attach(packing, [NOTES]);
    const { batch } = (await projects.item(project, packing)).attachments[0]!;
    const work = await projects.startWork(project, { title: 'Survey the stylesheets', brief: 'Survey them.', cwd: '/work/Example' });

    await overlay.open(project, packing);
    await overlay.discuss.click();
    await expect(chat.quote).toHaveAttribute('data-quote', `item ${packing}`);
    await expect(chat.quoteLabel).toHaveText('Packing');

    await overlay.attachmentChip(notes!).click();
    await expect(overlay.attachment.prose).toContainText('The dome is lighter.');
    await overlay.discuss.click();
    await expect(chat.quote).toHaveAttribute('data-quote', `path attachments/${batch}/tent-notes.md`);
    await expect(chat.quoteLabel).toHaveText('Tent notes');

    await overlay.openProjectDocument(project, 'handbook');
    await overlay.discuss.click();
    await expect(chat.quote).toHaveAttribute('data-quote', 'path handbook.md');
    await expect(chat.quoteLabel).toHaveText('Camping handbook');

    await overlay.openProjectDocument(project, 'draft');
    await overlay.discuss.click();
    await expect(chat.quote).toHaveAttribute('data-quote', 'path project.md');
    await expect(chat.quoteLabel).toHaveText('The trip plan');

    await sessionLog.open(project, work);
    await expect(sessionLog.discuss).toHaveAttribute('title', 'Discuss: ask Pilot about this session');
    await sessionLog.discuss.click();
    await expect(chat.quote).toHaveAttribute('data-quote', `item ${work}`);
    await expect(chat.field).toBeFocused();

    // An attachment at its address under its item's.
    await overlay.close.click();
    await timeline.item(packing).attachment(notes!).click();
    await overlay.discuss.click();
    await expect(chat.quote).toHaveAttribute('data-quote', `path attachments/${batch}/tent-notes.md`);
  });

  test('sends a file quoted by its path as its path tag, the message opening with its line', async ({
    page,
    people,
    projects,
    controller,
    overlay,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Path'), members: [me.handle!] });
    const notice = await projects.place(project, { kind: 'notice', title: 'Sketches', text: 'The sketches are attached.\n' });
    const [notes] = await projects.attach(notice, [NOTES]);
    const { batch } = (await projects.item(project, notice)).attachments[0]!;
    const path = `attachments/${batch}/tent-notes.md`;
    await page.goto(attachmentAddress(project, notice, notes!));
    await overlay.discuss.click();
    await chat.field.fill('Is this current?');
    const opened = await chats.opening(project);
    await chat.send.click();
    const session = await opened();
    await expect(chat.messages.getByTestId('chat.quote')).toHaveAttribute('data-quote', `path ${path}`);
    const [started] = (await chats.list(project)).chats;
    const send = (await projects.records(started!.id)).records.find((record) => record.kind === 'send')!;
    expect(send).toMatchObject({ message: `${pathTag(path, 'Tent notes')} Is this current?` });
    await controller.finish(chats.store, session, 'success', 'It is.');
  });

  test('on the head toggles the Chat tab with nothing quoted, the focus in the field', async ({
    people,
    projects,
    projectHead,
    timeline,
    panel,
    chat,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Head'), members: [me.handle!] });
    const notice = await projects.place(project, { kind: 'notice', title: 'Storm tonight', text: 'Tie the tent down.\n' });
    await timeline.open(project);
    const discuss = projectHead.discussButton;
    await expect(discuss).toHaveAttribute('title', 'Discuss the project with Pilot');
    await expect(discuss).toHaveAttribute('aria-pressed', 'true');

    await discuss.click();
    await expect(panel.root).toHaveCount(0);
    await expect(discuss).toHaveAttribute('aria-pressed', 'false');

    await timeline.item(notice).discuss.click();
    await expect(chat.quote).toHaveCount(1);
    await panel.documentsTab.click();
    await expect(discuss).toHaveAttribute('aria-pressed', 'false');
    await expect(projectHead.documentsButton).toHaveAttribute('aria-pressed', 'true');

    await discuss.click();
    await expect(chat.tab).toHaveAttribute('aria-selected', 'true');
    await expect(discuss).toHaveAttribute('aria-pressed', 'true');
    await expect(chat.quote).toHaveCount(0);
    await expect(chat.field).toBeFocused();
  });
});

test.describe('Discuss below a wide window', () => {
  test.use({ viewport: { width: 1100, height: 800 } });

  test('in an overlay puts the panel over it, the focus in the field', async ({
    page,
    people,
    projects,
    overlay,
    panel,
    chat,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Narrow'), members: [me.handle!] });
    const packing = await projects.place(project, { kind: 'document', title: 'Packing', text: PACKING });
    await overlay.open(project, packing);
    await expect(panel.root).toHaveCount(0);

    await overlay.discuss.click();
    await expect(page.locator('.project')).toHaveAttribute('data-front', 'panel');
    await expect(panel.root).not.toHaveAttribute('inert');
    await expect(chat.quoteLabel).toHaveText('Packing');
    await expect(chat.field).toBeFocused();
    await expect(overlay.root).toBeVisible();
  });
});

test.describe('The unread dot', () => {
  test('stands on the head’s Discuss and the Chat tab once a reply came while the chat was not in view; the chat seen to its end takes it away, and another device drops it at its next read', async ({
    page,
    people,
    projects,
    controller,
    projectHead,
    timeline,
    panel,
    chat,
    chats,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Unread'), members: [me.handle!] });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    await panel.documentsTab.click();
    await expect(projectHead.discussDot).toHaveCount(0);
    await expect(chat.tabDot).toHaveCount(0);

    const { session } = await chats.start(project, 'Which tent?');
    await controller.play(chats.store, session, [text('dome', 'The dome.')]);
    await controller.finish(chats.store, session, 'success', 'The dome.');
    await expect(projectHead.discussDot).toBeVisible();
    await expect(chat.tabDot).toBeVisible();
    await expect(projectHead.discussButton).toHaveAccessibleName('Discuss the project with Pilot, a reply unread');
    expect((await chats.list(project)).unread).toBe(true);

    // The person's other device, its panel on the Documents tab as this one's.
    const other = await page.context().newPage();
    const otherHead = new ProjectHeadPage(other);
    await other.goto(`/projects/${project}`);
    await expect(otherHead.discussDot).toBeVisible();
    await expect(new ChatPage(other).tabDot).toBeVisible();

    const marked = chat.acted('read');
    await chat.tab.click();
    await marked;
    await expect(chat.texts).toHaveText(['The dome.']);
    await expect(chat.tabDot).toHaveCount(0);
    await expect(projectHead.discussDot).toHaveCount(0);
    expect((await chats.list(project)).unread).toBe(false);
    await panel.documentsTab.click();
    await expect(chat.tabDot).toHaveCount(0);
    await expect(projectHead.discussDot).toHaveCount(0);

    await new TimelinePage(other).refocus();
    await expect(otherHead.discussDot).toHaveCount(0);
    await other.close();
  });

  test('leaves none after a reply watched arriving at the chat’s end', async ({
    people,
    projects,
    controller,
    projectHead,
    timeline,
    panel,
    chat,
    chats,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Watched'), members: [me.handle!] });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    await expect(chat.tab).toHaveAttribute('aria-selected', 'true');

    const { session } = await chats.start(project, 'Which stove?');
    const marked = chat.acted('read');
    await controller.play(chats.store, session, [text('gas', 'The gas one.')]);
    await controller.finish(chats.store, session, 'success', 'The gas one.');
    await marked;
    await expect(chat.texts).toHaveText(['The gas one.']);
    expect((await chats.list(project)).unread).toBe(false);
    await expect(projectHead.discussDot).toHaveCount(0);
    await panel.documentsTab.click();
    await expect(chat.tabDot).toHaveCount(0);
    await expect(projectHead.discussDot).toHaveCount(0);
  });

  test('stands on the Chat tab while a reply came below where the reader scrolled, and goes once they scroll to the chat’s end', async ({
    page,
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Scrolled'), members: [me.handle!] });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const { session } = await chats.start(project, 'Plan the route.');
    const seen = chat.acted('read');
    await controller.play(chats.store, session, [text('route', ROUTE)]);
    await controller.finish(chats.store, session, 'success', 'The route.');
    await seen;

    const up = chat.sticky(false);
    await chat.body.hover();
    await page.mouse.wheel(0, -600);
    await up;
    await chats.send(project, 'And the tent?');
    await chats.working(session);
    await controller.play(chats.store, session, [text('tent', 'The dome.')]);
    await controller.finish(chats.store, session, 'success', 'The dome.');
    await expect(chat.tabDot).toBeVisible();

    const marked = chat.acted('read');
    await page.mouse.wheel(0, 100_000);
    await marked;
    await expect(chat.tabDot).toHaveCount(0);
    expect((await chats.list(project)).unread).toBe(false);
  });
});
