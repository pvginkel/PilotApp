/**
 * A draft's side panel (F46.2, F46.3): the head's draft-panel toggle opens and closes it, and its
 * tabs are Draft and Documents, open or closed and on which tab the draft's own in the browser
 * (F1.6, F133); until set, it stands open beside the definition chat on a wide window, on Draft.
 * The Draft tab shows `project.md` as Pilot writes it, live: "Empty" before the first save, then its
 * title, its prose and its asks, Pilot's dots while the turn runs and what Create project does once
 * it ended; a link in it to a document Pilot attached opens that in the overlay, and nothing else
 * in it links (F47.3). Its asks are answered in place, as the timeline answers an ask of the same
 * kind, and written into `project.md` (F47.4); an ask Pilot changes or deletes is drawn as the draft
 * now stands. The definition chat stands in the timeline's place, so a draft's ask's ties to it land
 * there: Discuss quotes the ask into its composer (F39.1), an ask answered in it shows *In the chat*
 * going to the message (F42.3), and the answer's effect line, as a quote's chip, goes back to the ask
 * in the Draft tab (F41, F39.3). The Documents tab lists what Pilot attached so far, hung on nothing
 * (F36.6), each opening in the overlay. Below a wide window the panel lies over the definition chat,
 * and Discuss on an ask closes it.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique, waitForUiState } from '../support/helpers';
import { isOnTop } from '../support/page-objects/panel-page';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '2b6e9d41-7c3a-4f18-9e5d-3a8c1f6b0d27';
const text = (id: string, words: string) =>
  JSON.stringify({
    type: 'assistant',
    message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] },
    parent_tool_use_id: null,
    session_id: CONVERSATION,
  });

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const stamp = (at: string) =>
  new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: ZONE }).format(new Date(at));

const SLEEP = '## Where do we sleep?\n\n```decision id=D1\noptions:\n  - Tent\n  - Cabin\n```\n';
const COUNT = '## How many go?\n\n```question id=Q1\n```\n';
const VAN = '## Book the van\n\n```action id=A1\n```\n';
const draftText = (title: string, ...asks: string[]) => [`# ${title}\n`, 'A week by the lake.\n', ...asks].join('\n');

const EMPTY = 'Empty. Pilot writes the project here as you talk, and nothing is set up until you press Create project.';
const FOOT = 'Change anything in the chat. Create project hands it to Pilot, which sets it up and starts the plan.';


test.describe('A draft’s panel', () => {
  test('stands open beside the definition chat on a wide window, on its Draft tab; the head’s toggle closes and opens it, and its state and tab are the draft’s own in the browser', async ({
    page,
    people,
    projects,
    projectHead,
    panel,
    definitionChat,
  }) => {
    const me = await people.signIn();
    const { id } = await projects.makeDraft({ members: [me.handle!] });
    const { id: other } = await projects.makeDraft({ members: [me.handle!] });
    await projectHead.open(id);

    await expect(panel.tabs).toHaveText(['Draft', 'Documents']);
    await expect(panel.draftTab).toHaveAttribute('aria-selected', 'true');
    await expect(panel.root).toHaveAttribute('aria-label', 'The draft and its documents');
    const toggle = projectHead.draftPanelButton;
    await expect(toggle).toHaveAttribute('title', 'The draft: what Pilot will set up');
    await expect(toggle).toHaveAccessibleName('The draft');
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');
    // Beside the chat, not over it.
    const [chatBox, panelBox] = await Promise.all([definitionChat.root.boundingBox(), panel.root.boundingBox()]);
    expect(chatBox!.x + chatBox!.width).toBeLessThanOrEqual(panelBox!.x + 0.5);
    await expect(projectHead.discussButton).toHaveCount(0);
    await expect(projectHead.documentsButton).toHaveCount(0);

    await panel.documentsTab.click();
    await expect(panel.documentsTab).toHaveAttribute('aria-selected', 'true');
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await toggle.click();
    await expect(panel.draftTab).toHaveAttribute('aria-selected', 'true');
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');
    await toggle.click();
    await expect(panel.root).toHaveCount(0);
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');

    await page.reload();
    await waitForUiState(page, 'project.head', 'ready');
    await expect(panel.root).toHaveCount(0);
    await projectHead.open(other);
    await expect(panel.draftTab).toHaveAttribute('aria-selected', 'true');
    await panel.documentsTab.click();
    await projectHead.open(id);
    await expect(panel.root).toHaveCount(0);
    await projectHead.open(other);
    await expect(panel.documentsTab).toHaveAttribute('aria-selected', 'true');
  });
});

test.describe('The Draft tab', () => {
  test('reads Empty before the first save; a save shows live, its title, prose and asks, Pilot’s dots while its turn runs, then what Create project does', async ({
    people,
    projects,
    projectHead,
    panel,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const { id } = await projects.makeDraft({ members: [me.handle!] });
    const read = panel.readDraft();
    await projectHead.open(id);
    await read;
    await deploymentSse.ensureConnected();
    await expect(panel.draft.empty).toHaveText(EMPTY);
    await expect(panel.draft.root).toHaveCount(0);

    const title = makeUnique('Summer trip');
    await projects.saveProjectDocument(id, 'draft', draftText(title, SLEEP, COUNT));
    await expect(panel.draft.title).toHaveText(title);
    await expect(panel.draft.prose).toHaveText(['A week by the lake.', 'Where do we sleep?', 'How many go?']);
    await expect(panel.draft.blocks).toHaveCount(2);
    await expect(panel.draftBlock('D1').options).toHaveText(['Tent', 'Cabin']);
    await expect(panel.draft.writing).toBeVisible();
    await expect(panel.draft.foot).toHaveCount(0);
    await expect(panel.draft.empty).toHaveCount(0);

    await projects.endTurn(id);
    await expect(panel.draft.writing).toHaveCount(0);
    await expect(panel.draft.foot).toHaveText(FOOT);
  });

  test('a link to a document Pilot attached opens it in the overlay, whose Discuss quotes it into the definition chat; nothing else in it links, another link or a ticket id', async ({
    page,
    backendUrl,
    people,
    projects,
    projectHead,
    links,
    panel,
    overlay,
    definitionChat,
  }) => {
    await links.set({ ticket_url_template: `${backendUrl}/tickets/{id}` });
    const me = await people.signIn();
    const { id } = await projects.makeDraft({ members: [me.handle!] });
    const {
      batch,
      ids: [handover],
    } = await projects.attachToDraft(id, [{ title: 'Handover', filename: 'handover.md', content_type: 'text/markdown', content: '# Handover\n\nThe lake.\n' }]);
    const words = `See [the handover](attachments/${batch}/handover.md), [the site](https://example.com/site) and RB-12.\n`;
    await projects.saveProjectDocument(id, 'draft', `# The trip\n\n${words}`);
    await projects.endTurn(id);
    await projectHead.open(id);

    await expect(panel.draft.prose).toHaveText('See the handover, the site and RB-12.');
    await expect(panel.draft.root.getByRole('link')).toHaveText(['the handover']);
    await expect(panel.draft.links).toHaveText(['the handover']);

    await panel.draft.links.click();
    await expect(page).toHaveURL(`/projects/${id}/attachments/${handover}`);
    await expect(overlay.title).toHaveText('Handover');
    await expect(overlay.sub).toHaveText('Attachment of the draft');
    await expect(overlay.attachment.prose).toContainText('The lake.');

    // The definition chat lies under the overlay: Discuss closes it.
    await overlay.discuss.click();
    await expect(page).toHaveURL(`/projects/${id}`);
    await expect(overlay.root).toHaveCount(0);
    await expect(definitionChat.quote).toHaveAttribute('data-quote', `path attachments/${batch}/handover.md`);
    await expect(definitionChat.field).toBeFocused();
  });

  test('answers its asks in place, each as the timeline answers its kind, written into project.md; an ask Pilot changes or deletes is drawn as the draft now stands', async ({
    people,
    projects,
    projectHead,
    panel,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const { id } = await projects.makeDraft({ members: [me.handle!] });
    const title = makeUnique('Asks');
    await projects.saveProjectDocument(id, 'draft', draftText(title, SLEEP, COUNT, VAN));
    await projects.endTurn(id);
    await projectHead.open(id);
    await deploymentSse.ensureConnected();
    await expect(panel.draft.blocks).toHaveCount(3);

    // Pilot reworks the draft: Where to sleep gets a third option, How many is gone.
    await projects.saveProjectDocument(
      id,
      'draft',
      draftText(title, '## Where do we sleep?\n\n```decision id=D1\noptions:\n  - Tent\n  - Cabin\n  - Hut\n```\n', VAN),
    );
    await projects.endTurn(id);
    await expect(panel.draftBlock('D1').options).toHaveText(['Tent', 'Cabin', 'Hut']);
    await expect(panel.draftBlock('Q1').root).toHaveCount(0);
    await expect(panel.draft.blocks).toHaveCount(2);

    const sleep = panel.draftBlock('D1');
    await expect(sleep.kind).toHaveText('Decision');
    await expect(sleep.other).toBeVisible();
    let answered = panel.answered('answer');
    await sleep.option('Cabin').click();
    await answered;
    await expect(sleep.option('Cabin')).toHaveAttribute('data-chosen', 'true');
    await expect(sleep.answered).toBeVisible();
    // Answered in the draft, it is the person's until Create: it takes another answer.
    await expect(sleep.option('Tent')).toBeEnabled();
    answered = panel.answered('answer');
    await sleep.option('Tent').click();
    await answered;
    await expect(sleep.option('Tent')).toHaveAttribute('data-chosen', 'true');

    const van = panel.draftBlock('A1');
    await van.paste.fill('Booked for the 3rd');
    answered = panel.answered('done');
    await van.done.click();
    await answered;

    const blocks = (await projects.draft(id)).body.flatMap((part) => (part.type === 'block' ? [part.block] : []));
    expect(blocks.find((block) => block.id === 'D1')).toMatchObject({ answer: 'Tent', via: 'app', by: { kind: 'person', handle: me.handle } });
    expect(blocks.find((block) => block.id === 'A1')).toMatchObject({ note: 'Booked for the 3rd', by: { kind: 'person', handle: me.handle } });
    expect(blocks.find((block) => block.id === 'A1')!.done).not.toBeNull();
  });
});

test.describe('A draft’s ask and its definition chat', () => {
  test('Discuss quotes the ask into the definition chat’s composer, the focus in its field; sent, the quote’s chip goes back to the ask in the Draft tab', async ({
    people,
    projects,
    projectHead,
    panel,
    definitionChat,
    chats,
  }) => {
    const me = await people.signIn();
    const { id, folder } = await projects.makeDraft({ members: [me.handle!] });
    const title = makeUnique('Discussed');
    await projects.saveProjectDocument(id, 'draft', draftText(title, SLEEP));
    await projects.endTurn(id);
    await projectHead.open(id);

    const sleep = panel.draftBlock('D1');
    await expect(sleep.discuss).toHaveAttribute('title', 'Discuss: quote this block into the project’s chat');
    await sleep.discuss.click();
    await expect(definitionChat.quote).toHaveAttribute('data-quote', 'block project.md/D1');
    await expect(definitionChat.quoteLabel).toHaveText(`Where do we sleep? · ${title}`);
    await expect(definitionChat.field).toBeFocused();
    await expect(panel.draftTab).toHaveAttribute('aria-selected', 'true');

    const opened = await chats.opening(id, folder);
    await definitionChat.field.fill('A tent, surely?');
    const sent = definitionChat.acted('send');
    await definitionChat.send.click();
    await sent;
    await opened();
    await expect(definitionChat.quotes).toHaveCount(1);
    await expect(definitionChat.quote).toHaveCount(0);

    await panel.documentsTab.click();
    await definitionChat.quotes.click();
    await expect(panel.draftTab).toHaveAttribute('aria-selected', 'true');
    await expect(sleep.root).toHaveClass(/\bflash\b/);
    await expect(sleep.root).toHaveCSS('animation-name', 'fresh');
  });

  test('answered in the chat, the ask shows In the chat, going to the message that gave it in the definition chat; the answer’s effect line goes back to the ask', async ({
    people,
    projects,
    projectHead,
    controller,
    panel,
    definitionChat,
    chats,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const { id, folder } = await projects.makeDraft({ members: [me.handle!] });
    const title = makeUnique('In the chat');
    await projects.saveProjectDocument(id, 'draft', draftText(title, SLEEP));
    await projects.endTurn(id);
    await projectHead.open(id);
    await deploymentSse.ensureConnected();

    const opened = await chats.opening(id, folder);
    await chats.send(id, 'The tent.');
    const session = await opened();
    await controller.play(chats.store, session, [text('tent', 'The tent it is.')]);
    // The chat's answer needs its turn in flight on the server, not only in the fake: the reply shows first.
    await expect(definitionChat.texts).toHaveText(['The tent it is.']);
    await chats.answer(id, 'project.md/D1', 'Tent', me.handle!, { note: 'The tent.', toolUseId: 'toolu_tent' });
    await controller.finish(chats.store, session, 'success', 'The tent it is.');
    await chats.idle(id);

    const sleep = panel.draftBlock('D1');
    await expect(sleep.inChat).toHaveText('In the chat');
    await expect(sleep.option('Tent')).toHaveAttribute('data-chosen', 'true');
    await sleep.inChat.click();
    await expect(definitionChat.messageTexts.first()).toHaveClass(/\bflash\b/);
    await expect(definitionChat.messageTexts.first()).toHaveCSS('animation-name', 'fresh');
    await expect(definitionChat.messages.first()).toBeInViewport();

    await panel.documentsTab.click();
    await definitionChat.replies.getByText(`Answered · D1 · ${title}`).click();
    await expect(panel.draftTab).toHaveAttribute('aria-selected', 'true');
    await expect(sleep.root).toHaveClass(/\bflash\b/);
    await expect(sleep.root).toHaveCSS('animation-name', 'fresh');
  });
});

test.describe('A draft’s Documents tab', () => {
  test('lists what Pilot attached so far, newest first, the files of one call under one row, each opening in the overlay; “None yet” before any', async ({
    page,
    people,
    projects,
    projectHead,
    panel,
    overlay,
  }) => {
    const me = await people.signIn();
    const { id } = await projects.makeDraft({ members: [me.handle!] });
    const { id: bare } = await projects.makeDraft({ members: [me.handle!] });
    const {
      ids: [card],
    } = await projects.attachToDraft(id, [{ title: 'The card', filename: 'card.txt', content_type: 'text/plain', content: 'RB-12\n' }]);
    const { batch, ids: pair } = await projects.attachToDraft(id, [
      { title: 'Handover', filename: 'handover.md', content_type: 'text/markdown', content: '# Handover\n' },
      { title: 'Map', filename: 'map.txt', content_type: 'text/plain', content: 'North.\n' },
    ]);

    await projectHead.open(bare);
    await panel.documentsTab.click();
    await expect(panel.noAttachments).toHaveText('None yet. Pilot attaches here what you point it at in the chat: a card, a handover, a design.');
    await expect(panel.count).toHaveCount(0);

    await projectHead.open(id);
    await panel.documentsTab.click();
    await expect(panel.headings).toHaveText(['Attachments']);
    await expect(panel.projectDocument.root).toHaveCount(0);
    await expect(panel.noDocuments).toHaveCount(0);
    await expect(panel.count).toHaveText('3');
    await expect(panel.attachments.getByTestId('panel.row.title')).toHaveText(['Handover', 'Map', 'The card']);
    const timeline = await projects.timeline(id);
    const copiedAt = timeline.unhung_attachments.find((each) => each.id === card)!.copied_at;
    await expect(panel.attachment(card).sub).toHaveText(stamp(copiedAt));
    await expect(panel.batches).toHaveCount(1);
    const together = panel.batch(batch);
    const pairAt = timeline.unhung_attachments.find((each) => each.id === pair[0])!.copied_at;
    await expect(together.head.sub).toHaveText(stamp(pairAt));
    await expect(together.files.getByTestId('panel.row.sub')).toHaveText(['handover.md', 'map.txt']);

    await panel.attachment(card).root.click();
    await expect(page).toHaveURL(`/projects/${id}/attachments/${card}`);
    await expect(overlay.title).toHaveText('The card');
    await expect(overlay.sub).toHaveText('Attachment of the draft');
    await expect(overlay.attachment.text).toHaveText('RB-12');
  });
});

test.describe('A draft’s panel below a wide window', () => {
  test.use({ viewport: { width: 1000, height: 700 } });

  test('stands closed until the head’s toggle opens it over the definition chat; Discuss on an ask closes it, the quote in the composer', async ({
    people,
    projects,
    projectHead,
    panel,
    definitionChat,
  }) => {
    const me = await people.signIn();
    const { id } = await projects.makeDraft({ members: [me.handle!] });
    const title = makeUnique('Narrow');
    await projects.saveProjectDocument(id, 'draft', draftText(title, SLEEP));
    await projects.endTurn(id);
    await projectHead.open(id);
    await expect(panel.root).toHaveCount(0);

    await projectHead.draftPanelButton.click();
    await expect(panel.draftTab).toHaveAttribute('aria-selected', 'true');
    expect(await isOnTop(panel.draft.root)).toBe(true);

    await panel.draftBlock('D1').discuss.click();
    await expect(panel.root).toHaveCount(0);
    await expect(definitionChat.quote).toHaveAttribute('data-quote', 'block project.md/D1');
    await expect(definitionChat.field).toBeFocused();
  });
});
