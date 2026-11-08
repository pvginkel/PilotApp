/**
 * A new project in definition mode (F46): the plus beside Projects opens a new project's definition
 * chat with nothing behind it on the server, "Tell Pilot what to manage" (F113), its composer under
 * it, the draft's head's form over it (F46.2) and the panel's Draft and Documents beside it, empty;
 * on a phone the tabs at the bottom, a draft's. Its first message makes the draft (slice 037's asks
 * D1), which then stands in the person's list as "New project" and "Draft" until its title names it
 * (F46.1, F1.2, F47.1), at its address, `draft-<number>`; leaving before sending, or a first message
 * the server refuses, makes none. A draft's definition chat stands in the timeline's place, its
 * transcript and its composer as the Chat tab has them (F38, F40, F44), the lines of what Pilot's
 * tools changed included (F41). Beside it the panel stands on its Draft tab (draft-panel.spec.ts).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique, waitForUiState } from '../support/helpers';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '7d3f1b28-6e4a-4c95-8a0d-5b2e9f7c1a46';
const text = (id: string, words: string) =>
  JSON.stringify({
    type: 'assistant',
    message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] },
    parent_tool_use_id: null,
    session_id: CONVERSATION,
  });

const TELL = 'Tell Pilot what to manage';
const NO_ATTACHMENTS = 'None yet. Pilot attaches here what you point it at in the chat: a card, a handover, a design.';
const TELL_HOW =
  'A card, a handover, or the idea in your own words. Pilot drafts the project beside the chat as you talk, and nothing is created until you press Create project.';

const draftText = (title: string) => `# ${title}\n\nWhere we sleep.\n\n\`\`\`decision id=D1\noptions:\n  - Tent\n  - Cabin\n\`\`\`\n`;

test.describe('The plus', () => {
  test('opens a new project’s definition chat with nothing behind it on the server: “New project” and “Draft” in its head, “Tell Pilot what to manage” in the timeline’s place, its composer under it, the focus in its field, and the panel’s empty Draft and Documents; leaving it makes no project, its words kept for the next', async ({
    page,
    people,
    projects,
    projectList,
    projectHead,
    timeline,
    panel,
    definitionChat,
  }) => {
    await people.signIn();
    await page.goto('/');
    await waitForUiState(page, 'projects.list', 'ready');
    await expect(projectList.newProject).toHaveAttribute('title', 'New project');

    await projectList.newProject.click();
    await expect(page).toHaveURL('/projects/draft-new');
    await expect(projectHead.name).toHaveText('New project');
    await expect(projectHead.draft).toHaveText('Draft');
    await expect(definitionChat.empty.getByRole('heading')).toHaveText(TELL);
    await expect(definitionChat.empty.locator('p')).toHaveText(TELL_HOW);
    await expect(definitionChat.field).toBeEditable();
    await expect(definitionChat.field).toBeFocused();
    await expect(definitionChat.send).toBeDisabled();
    await expect(timeline.root).toHaveCount(0);
    await expect(panel.tabs).toHaveText(['Draft', 'Documents']);
    await expect(panel.draftTab).toHaveAttribute('aria-selected', 'true');
    await expect(panel.draft.empty).toBeVisible();
    await panel.documentsTab.click();
    await expect(panel.noAttachments).toHaveText(NO_ATTACHMENTS);
    await expect(projectList.mine.getByTestId('projects.tab')).toHaveCount(0);
    expect((await projects.list()).filter((tab) => tab.member)).toEqual([]);

    await definitionChat.field.fill('Let us plan the summer trip.');
    await expect(definitionChat.send).toBeEnabled();
    await page.goBack();
    await expect(page).not.toHaveURL('/projects/draft-new');
    expect((await projects.list()).filter((tab) => tab.member)).toEqual([]);

    await projectList.newProject.click();
    await expect(definitionChat.field).toHaveValue('Let us plan the summer trip.');
    await page.reload();
    await expect(definitionChat.field).toHaveValue('Let us plan the summer trip.');
    expect((await projects.list()).filter((tab) => tab.member)).toEqual([]);
  });

  test('makes the draft with its first message and shows it at its address in the entry’s place: “New project” and “Draft” in the person’s list, the message in its definition chat, Pilot answering, the focus in its field', async ({
    page,
    people,
    projects,
    projectList,
    projectHead,
    controller,
    definitionChat,
    chats,
  }) => {
    const me = await people.signIn();
    await page.goto('/');
    await waitForUiState(page, 'projects.list', 'ready');
    await projectList.newProject.click();
    await expect(page).toHaveURL('/projects/draft-new');

    const opened = await chats.openingNew();
    await definitionChat.field.fill('Let us plan the summer trip.');
    const created = projectList.created();
    await definitionChat.send.click();
    const id = (await created).fields!.project as string;

    const head = await projects.head(id);
    expect([head.state, head.name, head.members.map((member) => member.handle)]).toEqual(['draft', null, [me.handle]]);
    expect(head.address).toMatch(/^draft-\d+$/);
    await expect(page).toHaveURL(`/projects/${head.address}`);
    const session = await opened(head.address);
    const tab = projectList.tab('New project', projectList.mine);
    await expect(tab).toHaveAttribute('aria-current', 'page');
    await expect(tab.getByTestId('projects.tab.status')).toHaveText('Draft');
    await expect(projectHead.name).toHaveText('New project');
    await expect(projectHead.draft).toHaveText('Draft');
    await expect(definitionChat.messageTexts).toHaveText(['Let us plan the summer trip.']);
    await expect(definitionChat.empty).toHaveCount(0);
    await expect(definitionChat.stop).toBeVisible();
    await expect(definitionChat.field).toHaveValue('');
    await expect(definitionChat.field).toBeFocused();
    expect((await chats.list(id)).chats.map((chat) => chat.kind)).toEqual(['definition']);

    // The plus's chat starts empty again: what was sent left it.
    await projectList.newProject.click();
    await expect(definitionChat.field).toHaveValue('');
    await controller.finish(chats.store, session, 'success', 'Noted.');
  });

  test('makes no draft of a first message the server refuses: the refusal toasted, the words kept in the field, the page where it was', async ({
    page,
    people,
    projects,
    projectList,
    definitionChat,
    storeUpdate,
    toastHelper,
  }) => {
    await people.signIn();
    await page.goto('/');
    await waitForUiState(page, 'projects.list', 'ready');
    await projectList.newProject.click();
    await storeUpdate.make();

    await definitionChat.field.fill('Which stove?');
    await definitionChat.send.click();
    await toastHelper.expectErrorToast('Cannot send a message to Pilot in the untitled project because Pilot is updating');
    await expect(definitionChat.field).toHaveValue('Which stove?');
    await expect(page).toHaveURL('/projects/draft-new');
    await expect(definitionChat.empty).toBeVisible();
    expect((await projects.list()).filter((tab) => tab.member)).toEqual([]);
    await expect(projectList.mine.getByTestId('projects.tab')).toHaveCount(0);
  });

  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

    test('opens the new project’s chat under a draft’s tabs, Chat, Draft and Documents, the Draft empty; its first message makes the draft, at its Chat', async ({
      page,
      people,
      projects,
      projectList,
      projectHead,
      controller,
      panel,
      definitionChat,
      chats,
      phoneTabs,
      shell,
    }) => {
      await people.signIn();
      await page.goto('/');
      await waitForUiState(page, 'projects.list', 'ready');
      await shell.drawerToggle.tap();
      await projectList.newProject.tap();
      await expect(page).toHaveURL('/projects/draft-new');
      await expect(projectHead.name).toHaveText('New project');
      await expect(phoneTabs.tabs).toHaveText(['Chat', 'Draft', 'Documents']);
      await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
      await expect(definitionChat.empty.getByRole('heading')).toHaveText(TELL);

      await phoneTabs.tab('draft').tap();
      await expect(phoneTabs.tab('draft')).toHaveAttribute('aria-selected', 'true');
      await expect(panel.draft.empty).toBeVisible();
      await expect(definitionChat.root).toBeHidden();
      await phoneTabs.tab('documents').tap();
      await expect(panel.noAttachments).toHaveText(NO_ATTACHMENTS);
      await page.goBack();
      await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
      await expect(page).toHaveURL('/projects/draft-new');

      const opened = await chats.openingNew();
      await definitionChat.field.fill('A week by the lake.');
      const created = projectList.created();
      await definitionChat.send.tap();
      const id = (await created).fields!.project as string;
      const { address } = await projects.head(id);
      await expect(page).toHaveURL(`/projects/${address}`);
      const session = await opened(address);
      await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
      await expect(definitionChat.messageTexts).toHaveText(['A week by the lake.']);
      await controller.finish(chats.store, session, 'success', 'Noted.');
    });
  });
});

test.describe('A draft’s definition chat', () => {
  test('stands in the timeline’s place: the person’s message sent from its composer, Pilot’s reply and the line of an answer it recorded, while the draft’s title names the project in the list and the head', async ({
    people,
    projects,
    projectList,
    projectHead,
    controller,
    definitionChat,
    chats,
  }) => {
    const me = await people.signIn();
    const { id, folder } = await projects.makeDraft({ members: [me.handle!] });
    const read = definitionChat.read();
    await projectList.open(id);
    await read;
    await expect(definitionChat.empty.getByRole('heading')).toHaveText(TELL);

    // The transcript in the timeline's column, the composer's field under its text.
    const [column, field] = await Promise.all(
      [definitionChat.root.getByTestId('chat'), definitionChat.field].map(async (each) => (await each.boundingBox())!),
    );
    expect(column.width).toBeLessThanOrEqual(820);
    expect(field.x).toBeCloseTo(column.x + 24, 0);
    expect(field.x + field.width).toBeLessThan(column.x + column.width - 24);

    const opened = await chats.opening(id, folder);
    await definitionChat.field.fill('Let us plan the summer trip.');
    const sent = definitionChat.acted('send');
    await definitionChat.send.click();
    await sent;
    const session = await opened();
    await expect(definitionChat.messageTexts).toHaveText(['Let us plan the summer trip.']);
    await expect(definitionChat.empty).toHaveCount(0);
    await expect(definitionChat.stop).toBeVisible();
    expect((await chats.list(id)).chats.map((chat) => chat.kind)).toEqual(['definition']);

    const title = makeUnique('Summer trip');
    await projects.saveProjectDocument(id, 'draft', draftText(title));
    await expect(projectHead.name).toHaveText(title);
    await expect(projectList.tab(title, projectList.mine).getByTestId('projects.tab.status')).toHaveText('Draft');

    await controller.play(chats.store, session, [text('one', 'I drafted the trip: the tent it is.')]);
    await chats.answer(id, 'project.md/D1', 'Tent', me.handle!, { toolUseId: 'toolu_tent' });
    await controller.finish(chats.store, session, 'success', 'I drafted the trip: the tent it is.');
    await expect(definitionChat.texts).toHaveText(['I drafted the trip: the tent it is.']);
    await expect(definitionChat.replies.getByText(`Answered · D1 · ${title}`)).toBeVisible();
    await expect(definitionChat.send).toBeVisible();
  });
});
