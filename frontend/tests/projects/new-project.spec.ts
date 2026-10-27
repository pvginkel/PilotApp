/**
 * A new project in definition mode (F46): the plus beside Projects makes a draft and opens it, the
 * draft in the person's list as "New project" and "Draft" until its title names it (F46.1, F1.2,
 * F47.1), its head's draft form (F46.2), and its definition chat in the timeline's place, "Tell
 * Pilot what to manage" before the first message (F113), then its transcript and its composer as
 * the Chat tab has them (F38, F40, F44), the lines of what Pilot's tools changed included (F41).
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
const TELL_HOW =
  'A card, a handover, or the idea in your own words. Pilot drafts the project beside the chat as you talk, and nothing is created until you press Create project.';

const draftText = (title: string) => `# ${title}\n\nWhere we sleep.\n\n\`\`\`decision id=D1\noptions:\n  - Tent\n  - Cabin\n\`\`\`\n`;

test.describe('The plus', () => {
  test('makes a draft of the person’s and opens it: “New project” and “Draft” in their list and its head, and its definition chat in the timeline’s place, saying “Tell Pilot what to manage”, its composer under it', async ({
    page,
    people,
    projects,
    projectList,
    projectHead,
    timeline,
    panel,
    definitionChat,
  }) => {
    const me = await people.signIn();
    await page.goto('/');
    await waitForUiState(page, 'projects.list', 'ready');
    await expect(projectList.newProject).toHaveAttribute('title', 'New project');

    const created = projectList.created();
    await projectList.newProject.click();
    const id = (await created).fields!.project as string;

    await expect(page).toHaveURL(`/projects/${id}`);
    const head = await projects.head(id);
    expect([head.state, head.name, head.members.map((member) => member.handle)]).toEqual(['draft', null, [me.handle]]);
    const tab = projectList.tab('New project', projectList.mine);
    await expect(tab).toHaveAttribute('aria-current', 'page');
    await expect(tab.getByTestId('projects.tab.status')).toHaveText('Draft');
    await expect(projectHead.name).toHaveText('New project');
    await expect(projectHead.draft).toHaveText('Draft');

    await expect(definitionChat.empty.getByRole('heading')).toHaveText(TELL);
    await expect(definitionChat.empty.locator('p')).toHaveText(TELL_HOW);
    await expect(definitionChat.field).toBeEditable();
    await expect(definitionChat.send).toBeDisabled();
    await expect(timeline.root).toHaveCount(0);
    await expect(panel.root).toHaveCount(0);
  });
});

test.describe('A draft’s definition chat', () => {
  test('stands in the timeline’s place: the person’s message sent from its composer, Pilot’s reply and the line of an answer it recorded, while the draft’s title names the project in the list and the head', async ({
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
    await expect(page.getByTestId('panel')).toHaveCount(0);
  });
});
