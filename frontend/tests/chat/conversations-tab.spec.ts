/**
 * The Conversations tab (F150.12): a tab of its own for the conversations sessions outside Pilot
 * hold with Pilot about the project, after Chat in the side panel and among the phone's tabs at the
 * bottom, shown once the project has had one. Each conversation is read-only under its head — the
 * environment whose session opened it, the session's name where it gave one, "Open" or "Closed" —
 * its transcript as a chat's, streamed: the caller's messages on the right under the environment's
 * name, Pilot's reply with its cue, its phantom and its end. While Pilot answers in one its head
 * carries Stop, any person's (F44), and stays at the top of the view while the conversation scrolls
 * under it. There is no composer, and the tab carries no unread dot. It shows from the earliest
 * conversation still open, or the latest; "Load previous" loads the one before, above "Conversation
 * closed · <time>". The Chat tab, its composer, its Stop and its unread dot read the project's
 * chats alone. The panel keeps the tab as the one the person picked, in the browser. Where its
 * read fails it says "The conversations did not load." (F113).
 */

import type { Locator } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { expectConsoleError, makeUnique } from '../support/helpers';

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its thread.
const THREAD = '6c1f8a34-2e7b-4d90-a5c3-8f4e1b7d2a69';
const line = (value: object) => JSON.stringify({ ...value, session_id: THREAD });
const text = (id: string, words: string) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] }, parent_tool_use_id: null });
const blockStart = () =>
  line({ type: 'stream_event', event: { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }, parent_tool_use_id: null });
const delta = (words: string) =>
  line({ type: 'stream_event', event: { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: words } }, parent_tool_use_id: null });

// A reply long enough to fill the tab's view.
const LONG = ['The fix, step by step:', '', ...Array.from({ length: 40 }, (_, index) => `${index + 1}. Step ${index + 1}, by the lake.`)].join('\n');

const boxOf = async (locator: Locator) => (await locator.boundingBox())!;

test.describe('The Conversations tab', () => {
  test('is no tab of a project no session has talked to Pilot about, and comes in after Chat once one has, with no dot; the Chat tab, its composer and its dot read the chats alone', async ({
    people,
    projects,
    controller,
    timeline,
    panel,
    chat,
    chats,
    conversations,
    conversationsTab,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Talk'), members: [me.handle!] });
    const read = conversationsTab.read();
    await timeline.open(project);
    await read;
    await expect(panel.head.getByRole('tab')).toHaveText(['Chat', 'Documents']);
    await expect(conversationsTab.tab).toHaveCount(0);

    const { caller } = await conversations.caller('RecipeBox-2', 'ui-sweep-triage');
    const { conversation, session } = await caller.start(project, 'How is the fix going?');
    await expect(panel.head.getByRole('tab')).toHaveText(['Chat', 'Conversations', 'Documents']);
    await expect(conversationsTab.tab).toHaveAttribute('aria-selected', 'false');

    // The Chat tab shows no chat, takes a message and offers no Stop, while Pilot answers the session.
    await expect(chat.tab).toHaveAttribute('aria-selected', 'true');
    await expect(chat.empty).toBeVisible();
    await expect(chat.messages).toHaveCount(0);
    await expect(chat.stop).toHaveCount(0);
    await expect(chat.send).toBeVisible();
    expect((await chats.list(project)).chats).toEqual([]);

    // Pilot's reply to the session leaves no dot, on either tab.
    await controller.play(chats.store, session, [text('one', 'Two tests to go.')]);
    await controller.finish(chats.store, session, 'success', 'Two tests to go.');
    await conversations.idle(project, conversation);
    await timeline.refocus();
    await expect(chat.tabDot).toHaveCount(0);
    await expect(conversationsTab.tab.locator('.unread')).toHaveCount(0);
    await expect(conversationsTab.tab).toHaveText('Conversations');
    expect((await chats.list(project)).unread).toBe(false);
  });

  test('shows a conversation read-only under its head, the environment, the session and Open, the caller’s message under the environment’s name, and streams Pilot’s reply; it has no composer, and stays the tab the person picked', async ({
    page,
    people,
    projects,
    controller,
    timeline,
    panel,
    chat,
    chats,
    conversations,
    conversationsTab,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Read'), members: [me.handle!] });
    const { caller } = await conversations.caller('RecipeBox-2', 'ui-sweep-triage');
    const { conversation: id, session } = await caller.start(project, 'How is the fix going?');
    await timeline.open(project);

    const live = conversationsTab.live(id);
    await conversationsTab.tab.click();
    await live;
    await expect(conversationsTab.tab).toHaveAttribute('aria-selected', 'true');
    await expect(chat.root).toHaveCount(0);
    const conversation = conversationsTab.conversation(id);
    await expect(conversationsTab.conversations).toHaveCount(1);
    await expect(conversation.environment).toHaveText('RecipeBox-2');
    await expect(conversation.session).toHaveText('· ui-sweep-triage');
    await expect(conversation.state).toHaveText('Open');
    await expect(conversation.messageTexts).toHaveText(['How is the fix going?']);
    await expect(conversation.names).toHaveText(['RecipeBox-2']);

    // Read-only: no field, no Send, anywhere in the panel.
    await expect(panel.root.getByTestId('chat.composer')).toHaveCount(0);
    await expect(panel.root.getByRole('textbox')).toHaveCount(0);

    // Pilot's reply streams as a chat's: the cue, the phantom, the text, its end.
    await expect(conversation.cue).toBeVisible();
    await controller.play(chats.store, session, [blockStart(), delta('Two tests ')]);
    await expect(conversation.phantom).toHaveText('Two tests');
    await controller.play(chats.store, session, [delta('to go.'), text('one', 'Two tests to go.')]);
    await expect(conversation.phantom).toHaveCount(0);
    await expect(conversation.texts).toHaveText(['Two tests to go.']);
    await expect(conversation.stop).toBeVisible();
    await controller.finish(chats.store, session, 'success', 'Two tests to go.');
    const { records } = await projects.records(id);
    await expect(conversation.replyEnds).toHaveText([clock(records.at(-1)!.at)]);
    await expect(conversation.cue).toHaveCount(0);
    await expect(conversation.stop).toHaveCount(0);

    // The caller's next message, and Pilot's answer to it, come in live.
    await conversations.idle(project, id);
    await caller.send(id, 'And the lint?');
    await expect(conversation.messageTexts).toHaveText(['How is the fix going?', 'And the lint?']);
    await chats.working(session);
    await controller.play(chats.store, session, [text('two', 'Clean.')]);
    await controller.finish(chats.store, session, 'success', 'Clean.');
    await expect(conversation.texts).toHaveText(['Two tests to go.', 'Clean.']);

    // The panel keeps the tab, in the browser, and shows it again after a reload.
    const kept = () => page.evaluate(() => (JSON.parse(localStorage.getItem('pilot')!) as { panels: Record<string, unknown> }).panels);
    expect((await kept())[project]).toEqual({ tab: 'conversations' });
    await timeline.open(project);
    await expect(conversationsTab.tab).toHaveAttribute('aria-selected', 'true');
    await expect(conversation.texts).toHaveText(['Two tests to go.', 'Clean.']);
    await expect(chat.root).toHaveCount(0);
  });

  test('carries Stop in a conversation’s head while Pilot answers in it, whose press ends the turn where it is and keeps the conversation open; the head stays at the top of the view while the conversation scrolls under it', async ({
    people,
    projects,
    controller,
    timeline,
    chats,
    conversations,
    conversationsTab,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Stop'), members: [me.handle!] });
    await timeline.open(project);
    const { caller } = await conversations.caller('RecipeBox-2');
    const { conversation: id, session } = await caller.start(project, 'Walk me through the fix.');
    const live = conversationsTab.live(id);
    await conversationsTab.tab.click();
    await live;
    const conversation = conversationsTab.conversation(id);
    // A session that named none: the environment alone.
    await expect(conversation.environment).toHaveText('RecipeBox-2');
    await expect(conversation.session).toHaveCount(0);
    await expect(conversation.stop).toBeVisible();
    await expect(conversation.stop).toHaveAttribute('title', 'Stop Pilot’s answer');

    await controller.play(chats.store, session, [text('long', LONG)]);
    await expect(conversation.texts).toHaveCount(1);
    // The view is at the reply's end, the message scrolled away, and the head still at its top.
    await expect(conversation.messageTexts.first()).not.toBeInViewport();
    const [view, head] = await Promise.all([boxOf(conversationsTab.body), boxOf(conversation.head)]);
    expect(head.y).toBeCloseTo(view.y, 0);
    expect(head.width).toBeCloseTo(view.width, 0);

    const stopped = conversationsTab.stopped();
    await conversation.stop.click();
    await stopped;
    await expect(conversation.stop).toHaveCount(0);
    await expect(conversation.replyEnds).toContainText(['· Stopped']);
    await expect(conversation.state).toHaveText('Open');
    await expect(conversation.closed).toHaveCount(0);
    const listed = (await conversations.list(project)).conversations;
    expect(listed.map((each) => [each.id, each.answering, each.closed_at])).toEqual([[id, false, null]]);

    // Its caller's next message goes on in the same conversation.
    await caller.send(id, 'Shorter, please.');
    await expect(conversation.messageTexts).toHaveText(['Walk me through the fix.', 'Shorter, please.']);
    await expect(conversation.stop).toBeVisible();
    await chats.working(session);
    await controller.finish(chats.store, session, 'success', 'Done.');
    await expect(conversation.stop).toHaveCount(0);
  });

  test('shows from the earliest conversation still open, a closed one above “Conversation closed” under Load previous, its head Closed, and one that opens while it shows below', async ({
    people,
    projects,
    controller,
    timeline,
    chats,
    conversations,
    conversationsTab,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Several'), members: [me.handle!] });
    const { caller: recipebox } = await conversations.caller('RecipeBox-2', 'monday');
    const first = await recipebox.start(project, 'Is the stock on?');
    await controller.play(chats.store, first.session, [text('stock', 'Simmering.')]);
    await controller.finish(chats.store, first.session, 'success', 'Simmering.');
    await conversations.idle(project, first.conversation);
    await recipebox.end(first.conversation);
    const second = await recipebox.start(project, 'And the bread?');
    await controller.play(chats.store, second.session, [text('bread', 'Proving.')]);
    await controller.finish(chats.store, second.session, 'success', 'Proving.');
    await conversations.idle(project, second.conversation);

    await timeline.open(project);
    const live = conversationsTab.live(second.conversation);
    await conversationsTab.tab.click();
    await live;
    await expect(conversationsTab.conversations).toHaveCount(1);
    await expect(conversationsTab.conversation(second.conversation).texts).toHaveText(['Proving.']);
    await expect(conversationsTab.conversation(second.conversation).state).toHaveText('Open');

    await expect(conversationsTab.before).toHaveText('Load previous');
    await conversationsTab.before.click();
    await expect(conversationsTab.before).toHaveCount(0);
    await expect(conversationsTab.heads.getByTestId('conversation.session')).toHaveText(['· monday', '· monday']);
    const closed = conversationsTab.conversation(first.conversation);
    await expect(closed.texts).toHaveText(['Simmering.']);
    await expect(closed.state).toHaveText('Closed');
    await expect(closed.stop).toHaveCount(0);
    const { conversations: listed } = await conversations.list(project);
    expect(listed.map((each) => each.close_cause)).toEqual(['ended', null]);
    await expect(closed.closed).toHaveText(`Conversation closed · ${clock(listed[0]!.closed_at!)}`);

    // Another session's conversation opens while the tab shows: it comes in below, beside the open one.
    const { caller: automation } = await conversations.caller('Automation');
    const third = await automation.start(project, 'Nightly pass: anything for me?');
    await expect(conversationsTab.conversations).toHaveCount(3);
    await expect(conversationsTab.heads.getByTestId('conversation.environment')).toHaveText(['RecipeBox-2', 'RecipeBox-2', 'Automation']);
    await expect(conversationsTab.conversation(third.conversation).messageTexts).toHaveText(['Nightly pass: anything for me?']);
    await expect(conversationsTab.conversation(third.conversation).names).toHaveText(['Automation']);
    await expect(conversationsTab.conversation(second.conversation).state).toHaveText('Open');
    await controller.finish(chats.store, third.session, 'success', 'Nothing.');
  });

  test('says “The conversations did not load.” where its read fails, and draws them once a later read lands', async ({
    page,
    people,
    projects,
    controller,
    timeline,
    chats,
    conversations,
    conversationsTab,
  }) => {
    const subject = makeUnique('subject');
    const me = await people.signIn({ subject });
    const project = await projects.make({ name: makeUnique('Failed'), members: [me.handle!] });
    const { caller } = await conversations.caller('RecipeBox-2');
    const { conversation: id, session } = await caller.start(project, 'Is the stock on?');
    await controller.play(chats.store, session, [text('stock', 'Simmering.')]);
    await controller.finish(chats.store, session, 'success', 'Simmering.');
    await conversations.idle(project, id);
    await timeline.open(project);
    await conversationsTab.tab.click();
    const conversation = conversationsTab.conversation(id);
    await expect(conversation.texts).toHaveText(['Simmering.']);

    // The browser's session now lacks the editor role, and the API refuses the list's next read.
    await expectConsoleError(page, /403/);
    await people.withoutRole({ subject });
    await timeline.refocus();
    await expect(conversationsTab.failed).toHaveText('The conversations did not load.');
    await expect(conversationsTab.conversations).toHaveCount(0);
    await expect(conversationsTab.tab).toHaveAttribute('aria-selected', 'true');

    await people.firstSignIn({ subject });
    await timeline.refocus();
    await expect(conversationsTab.failed).toHaveCount(0);
    await expect(conversation.texts).toHaveText(['Simmering.']);
    await expect(conversation.state).toHaveText('Open');
  });
});

test.describe('The Conversations tab on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('is no tab at the bottom of a project that has had no conversation, and stands after Chat once it has, with no dot; it shows the conversations between the head and the tabs, read-only, with Stop', async ({
    people,
    projects,
    controller,
    projectHead,
    timeline,
    panel,
    phoneTabs,
    chats,
    conversations,
    conversationsTab,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Phone'), members: [me.handle!] });
    const read = conversationsTab.read();
    await timeline.open(project);
    await read;
    await expect(phoneTabs.tabs).toHaveText(['Timeline', 'Chat', 'Plan', 'Documents']);
    await expect(phoneTabs.tab('conversations')).toHaveCount(0);

    const { caller } = await conversations.caller('RecipeBox-2', 'ui-sweep-triage');
    const { conversation: id, session } = await caller.start(project, 'How is the fix going?');
    await expect(phoneTabs.tabs).toHaveText(['Timeline', 'Chat', 'Conversations', 'Plan', 'Documents']);
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    // Its name stands within its tab, its icon over it, and it carries no dot and no count.
    const tab = phoneTabs.tab('conversations');
    const own = await boxOf(tab);
    const name = await tab.evaluate((button) => {
      const range = document.createRange();
      range.selectNode(button.lastChild!);
      const { x, width } = range.getBoundingClientRect();
      return { x, width };
    });
    expect(name.x).toBeGreaterThanOrEqual(own.x);
    expect(name.x + name.width).toBeLessThanOrEqual(own.x + own.width);
    await expect(tab.locator('.pill svg.icon')).toBeVisible();
    await expect(tab.locator('.unread, .ptab-count')).toHaveCount(0);

    const live = conversationsTab.live(id);
    await tab.click();
    await live;
    await expect(tab).toHaveAttribute('aria-selected', 'true');
    await expect(panel.head).toHaveCount(0);
    const [head, tabs, shown] = await Promise.all([boxOf(projectHead.root), boxOf(phoneTabs.root), boxOf(conversationsTab.root)]);
    expect(shown.x).toBe(0);
    expect(shown.width).toBe(390);
    expect(shown.y).toBeCloseTo(head.y + head.height, 0);
    expect(shown.y + shown.height).toBeCloseTo(tabs.y, 0);

    const conversation = conversationsTab.conversation(id);
    await expect(conversation.environment).toHaveText('RecipeBox-2');
    await expect(conversation.session).toHaveText('· ui-sweep-triage');
    await expect(conversation.messageTexts).toHaveText(['How is the fix going?']);
    await expect(panel.root.getByTestId('chat.composer')).toHaveCount(0);

    await controller.play(chats.store, session, [text('one', 'Two tests to go.')]);
    await expect(conversation.texts).toHaveText(['Two tests to go.']);
    const stopped = conversationsTab.stopped();
    await conversation.stop.click();
    await stopped;
    await expect(conversation.stop).toHaveCount(0);
    await expect(conversation.replyEnds).toContainText(['· Stopped']);
    await expect(phoneTabs.chatDot).toHaveCount(0);

    // Back from it shows the Timeline, as from any tab, and a reload keeps it.
    await tab.page().reload();
    await expect(tab).toHaveAttribute('aria-selected', 'true');
    await expect(conversation.texts).toHaveText(['Two tests to go.']);
    await tab.page().goBack();
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
  });
});
