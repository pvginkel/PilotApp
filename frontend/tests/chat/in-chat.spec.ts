/**
 * *In the chat* (F42.3): a block answered in the chat carries it in its head, and a one-ask item's
 * done line after its answer, kept whole however long the answer — a button with the chat icon and
 * its label. It opens the side panel on the Chat tab, on top, with nothing quoted, loads the chats
 * before until the one holding the answer, and scrolls to the message that gave it and flashes it,
 * letting go of the chat's end, so the chat is not taken as seen there. A block answered in the app
 * has none. On a narrow screen a block head's In the chat and Answered keep their icons alone, so
 * Discuss stays in the head (F98.3).
 */

import { test, expect } from '../support/fixtures';
import type { Chats } from '../support/chats';
import type { Controller } from '../support/controller';
import { makeUnique } from '../support/helpers';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '4c8e1a72-9d3b-4f60-a5e2-7b1d6c9f0e34';
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

// A reply taller than the tab's view.
const ROUTE = Array.from({ length: 40 }, (_, index) => `Stage ${index + 1}, by the lake.`).join('\n\n');
const LONG_NOTE =
  'The dome: it stands up in five minutes, it is light enough to carry on the bike all the way up to the lake, and the rain runs off it.';

/** Pilot's reply to the message in flight, and the end of its turn. */
async function reply(controller: Controller, chats: Chats, session: string, id: string, words: string): Promise<void> {
  await controller.play(chats.store, session, [text(id, words)]);
  await controller.finish(chats.store, session, 'success', words);
}

test.describe('In the chat', () => {
  test.use({ viewport: { width: 1280, height: 600 } });

  test('on a document’s block head and a one-ask item’s done line goes to the message that gave the answer: the Chat tab on top, nothing quoted, the message in view and flashing, the chat’s end not taken as seen', async ({
    people,
    projects,
    controller,
    timeline,
    panel,
    chat,
    chats,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('In the chat'), members: [me.handle!] });
    const tent = await projects.place(project, { kind: 'decision', title: 'Which tent?', text: DECISION });
    const packing = await projects.place(project, { kind: 'document', title: 'Packing', text: PACKING });
    await projects.answer(packing, 'Q1', 'Twelve');
    // The chat runs while the panel shows the Documents tab: its replies unread.
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    await panel.documentsTab.click();
    const { session } = await chats.start(project, 'Gas for the stove.');
    await chats.answer(project, `${packing}/D1`, 'Gas', me.handle!, { toolUseId: 'toolu_stove' });
    await reply(controller, chats, session, 'stove', ROUTE);
    await chats.idle(project);
    await chats.send(project, 'And the dome.');
    await chats.working(session);
    await chats.answer(project, `${tent}/D1`, 'Dome', me.handle!, { note: LONG_NOTE, toolUseId: 'toolu_tent' });
    await reply(controller, chats, session, 'tent', ROUTE);
    await chats.idle(project);
    expect((await chats.list(project)).unread).toBe(true);

    // Each comes as the answer is recorded.
    const stove = timeline.item(packing).blockAt('D1');
    await expect(stove.inChat).toHaveText('In the chat');
    await expect(stove.inChat).toHaveAccessibleName('Go to the answer in the chat');
    await expect(stove.inChat.locator('.icon')).toBeVisible();
    expect((await stove.inChat.locator('.in-chat-label').boundingBox())!.width).toBeGreaterThan(30);
    // Answered in the app: no In the chat.
    const pegs = timeline.item(packing).blockAt('Q1');
    await expect(pegs.answered).toBeVisible();
    await expect(pegs.inChat).toHaveCount(0);

    const letGo = chat.sticky(false);
    await stove.inChat.click();
    await letGo;
    await expect(chat.tab).toHaveAttribute('aria-selected', 'true');
    await expect(chat.quote).toHaveCount(0);
    await expect(chat.messageTexts).toHaveText(['Gas for the stove.', 'And the dome.']);
    await expect(chat.messageTexts.first()).toHaveClass(/\bflash\b/);
    await expect(chat.messageTexts.first()).toHaveCSS('animation-name', 'fresh');
    await expect(chat.messages.first()).toBeInViewport();
    await expect(chat.messages.last()).not.toBeInViewport();
    expect((await chats.list(project)).unread).toBe(true);

    // The done line's, after the answer cut short, kept whole.
    const line = timeline.item(tent);
    await expect(line.root).toHaveAttribute('data-state', 'done');
    await expect(line.said).toContainText('Dome · The dome: it stands up');
    await expect(line.lineInChat).toHaveText('In the chat');
    const [said, button] = await Promise.all([line.said.boundingBox(), line.lineInChat.boundingBox()]);
    expect(button!.x + button!.width).toBeLessThanOrEqual(said!.x + said!.width + 0.5);
    expect(await line.lineInChat.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(0);
    expect(await line.said.locator('.said-text').evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);

    await line.lineInChat.click();
    await expect(chat.messageTexts.last()).toHaveClass(/\bflash\b/);
    await expect(chat.messages.last()).toBeInViewport();
    await expect(chat.messages.first()).not.toBeInViewport();
    expect((await chats.list(project)).unread).toBe(true);
  });

  test('in an earlier chat loads the chats before until the one holding it, and goes to the message there', async ({
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Earlier'), members: [me.handle!] });
    const tent = await projects.place(project, { kind: 'decision', title: 'Which tent?', text: DECISION });
    const first = await chats.start(project, 'The dome.');
    await chats.answer(project, `${tent}/D1`, 'Dome', me.handle!, { note: 'The dome.', toolUseId: 'toolu_tent' });
    await reply(controller, chats, first.session, 'tent', 'The dome, then.');
    await chats.idle(project);
    // Finish closes the chat; after Reopen the next message starts another.
    await projects.transition(project, 'finished');
    await projects.transition(project, 'reopened');
    const second = await chats.start(project, 'And the stove?');
    await reply(controller, chats, second.session, 'stove', ROUTE);
    await chats.idle(project);

    await timeline.open(project);
    await expect(chat.messageTexts).toHaveText(['And the stove?']);
    await expect(chat.before).toBeVisible();

    await timeline.item(tent).lineInChat.click();
    await expect(chat.messageTexts).toHaveText(['The dome.', 'And the stove?']);
    await expect(chat.closed).toHaveCount(1);
    await expect(chat.before).toHaveCount(0);
    await expect(chat.messageTexts.first()).toHaveClass(/\bflash\b/);
    await expect(chat.messages.first()).toBeInViewport();
    // Held there, not at the chat's end under the reply.
    expect(await chat.body.evaluate((body) => body.scrollHeight - body.scrollTop - body.clientHeight)).toBeGreaterThan(100);
  });
});

test.describe('In the chat on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('keeps its icon alone in a block head, as Answered does, Discuss staying there, and opens the Chat tab, the whole screen, at the message', async ({
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Phone'), members: [me.handle!] });
    const packing = await projects.place(project, { kind: 'document', title: 'Packing', text: PACKING });
    const { session } = await chats.start(project, 'Gas for the stove.');
    await chats.answer(project, `${packing}/D1`, 'Gas', me.handle!, { toolUseId: 'toolu_stove' });
    await reply(controller, chats, session, 'stove', ROUTE);
    await chats.idle(project);

    await timeline.open(project);
    const stove = timeline.item(packing).blockAt('D1');
    await expect(stove.inChat.locator('.icon')).toBeVisible();
    await expect(stove.answered.locator('.icon')).toBeVisible();
    for (const word of [stove.inChat.locator('.in-chat-label'), stove.answered.locator('.chip-label')]) {
      const box = (await word.boundingBox())!;
      expect(box.width).toBeLessThanOrEqual(1);
      expect(box.height).toBeLessThanOrEqual(1);
    }
    await expect(stove.discuss).toBeVisible();
    const [head, discuss] = await Promise.all([stove.head.boundingBox(), stove.discuss.boundingBox()]);
    expect(discuss!.y + discuss!.height).toBeLessThanOrEqual(head!.y + head!.height + 0.5);

    await stove.inChat.click();
    await expect(chat.root).toBeInViewport();
    await expect(chat.messageTexts.first()).toHaveClass(/\bflash\b/);
    await expect(chat.messages.first()).toBeInViewport();
  });
});
