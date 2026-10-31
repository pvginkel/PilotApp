/**
 * The Chat tab's composer (F44; the chat mockup's decision 7), under the transcript: the growing
 * field to five lines (F115), Enter breaking the line and Ctrl+Enter sending (F110), Send disabled
 * while the field is empty and the field waiting while the message is on its way; a message with no
 * chat open starts one, shown in the tab. While Pilot answers Send's place is Stop, in every member's
 * composer whoever sent the message, the field not waiting; Stop ends the turn where it is. The
 * focus stays in the field after Send and after Stop, and a message sent takes the chat back to its
 * end, wherever the reader had scrolled. The words are kept in the browser until sent,
 * keyed by the project (F133). In an archived project it takes no message and says why (F128.5).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { slowNetwork } from '../support/network';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '4d1f8a26-7c3e-4b95-a0e2-8f6b3c9d1e47';
const text = (id: string, words: string) =>
  JSON.stringify({
    type: 'assistant',
    message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] },
    parent_tool_use_id: null,
    session_id: CONVERSATION,
  });

const UNSENT_KEY = 'pilot.unsent';
const ROUTE = Array.from({ length: 40 }, (_, index) => `Stage ${index + 1}, by the lake.`).join('\n\n');
const ARCHIVED = 'The project is archived: bring it back to message Pilot.';

test.describe('The Chat tab’s composer', () => {
  test('sends with Ctrl+Enter and with Send, Enter breaking the line; the first message starts the chat in the tab; Send waits while the field is empty, the field while the message is on its way; the field grows to five lines; the focus stays in it', async ({
    page,
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Composer'), members: [me.handle!] });
    const read = chat.read();
    await timeline.open(project);
    await read;
    await expect(chat.empty).toBeVisible();
    await expect(chat.field).toHaveAttribute('placeholder', 'Message Pilot');
    await expect(chat.send).toBeDisabled();
    await expect(chat.send).toHaveAttribute('title', 'Send (Ctrl+Enter)');
    await chat.field.fill('  \n ');
    await expect(chat.send).toBeDisabled();

    // One line at rest, growing to five, then scrolling.
    await chat.field.fill('');
    const rest = (await chat.field.boundingBox())!.height;
    await chat.field.fill(Array.from({ length: 8 }, (_, index) => `Line ${index + 1}`).join('\n'));
    await expect.poll(async () => Math.round((await chat.field.boundingBox())!.height)).toBe(Math.round(rest + 4 * 24));
    await expect(chat.field).toHaveCSS('overflow-y', 'auto');

    await chat.field.fill('Which tent');
    await chat.field.press('Enter');
    await chat.field.pressSequentially('do we take?');
    await expect(chat.field).toHaveValue('Which tent\ndo we take?');
    await expect(chat.send).toBeEnabled();

    const opened = await chats.opening(project);
    const restore = await slowNetwork(page, 1_000);
    const sent = chat.acted('send');
    await chat.field.press('Control+Enter');
    await expect(chat.field).toHaveJSProperty('readOnly', true);
    await expect(chat.field).toHaveValue('Which tent\ndo we take?');
    await expect(chat.send).toBeDisabled();
    await sent;
    await restore();
    const session = await opened();
    await expect(chat.field).toHaveValue('');
    await expect(chat.field).toHaveJSProperty('readOnly', false);
    await expect(chat.field).toBeFocused();
    await expect(chat.empty).toHaveCount(0);
    await expect(chat.messageTexts).toHaveText(['Which tent do we take?']);
    const [started] = (await chats.list(project)).chats;
    const send = (await projects.records(started!.id)).records.find((record) => record.kind === 'send')!;
    expect(send).toMatchObject({ message: 'Which tent\ndo we take?' });

    // While Pilot answers, Stop stands in Send's place; once it is done, Send again.
    await expect(chat.stop).toBeVisible();
    await expect(chat.send).toHaveCount(0);
    await controller.play(chats.store, session, [text('dome', 'The dome.')]);
    await controller.finish(chats.store, session, 'success', 'The dome.');
    await expect(chat.stop).toHaveCount(0);
    await expect(chat.send).toBeDisabled();

    await chat.field.fill('And the stove?');
    const again = chat.acted('send');
    await chat.send.click();
    await again;
    await expect(chat.field).toBeFocused();
    await expect(chat.field).toHaveValue('');
    await expect(chat.messageTexts).toHaveText(['Which tent do we take?', 'And the stove?']);
    await chats.working(session);
    await controller.finish(chats.store, session, 'success', 'The gas one.');
    await expect(chat.send).toBeVisible();
  });

  test('puts Stop in Send’s place in every member’s composer while Pilot answers, whoever sent the message; the field does not wait, and Stop ends the turn where it is, the focus in the field', async ({
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const bea = await chats.other('Bea Example', makeUnique('bea', 8));
    const project = await projects.make({ name: makeUnique('Stop'), members: [me.handle!, bea.handle] });
    const read = chat.read();
    await timeline.open(project);
    await read;

    const { chat: id, session } = await chats.start(project, 'Survey the campsites.', bea);
    const live = chat.live(id);
    await expect(chat.stop).toBeVisible();
    await expect(chat.stop).toHaveAttribute('title', 'Stop Pilot’s answer');
    await expect(chat.send).toHaveCount(0);
    await live;

    // The next message is written meanwhile; Ctrl+Enter sends nothing while Pilot answers.
    await chat.field.fill('Only the lakeside ones.');
    await chat.field.press('Control+Enter');
    await expect(chat.field).toHaveValue('Only the lakeside ones.');
    await expect(chat.messages).toHaveCount(1);

    await controller.play(chats.store, session, [text('first', 'Three sites so far.')]);
    await expect(chat.texts).toHaveText(['Three sites so far.']);
    const stopped = chat.acted('stop');
    await chat.stop.click();
    await stopped;
    await expect(chat.field).toBeFocused();
    await expect(chat.replyEnds).toContainText(['· Stopped']);
    await expect(chat.stop).toHaveCount(0);
    await expect(chat.send).toBeEnabled();
    await expect(chat.field).toHaveValue('Only the lakeside ones.');

    // The words written meanwhile go out as the next message of the same chat.
    await chat.send.click();
    await expect(chat.messageTexts).toHaveText(['Survey the campsites.', 'Only the lakeside ones.']);
    await expect(chat.field).toHaveValue('');
    await expect(chat.field).toBeFocused();
    await chats.working(session);
    await controller.play(chats.store, session, [text('second', 'The lakeside ones, then.')]);
    await controller.finish(chats.store, session, 'success', 'The lakeside ones, then.');
    await expect(chat.replyEnds).toHaveCount(2);
  });

  test('takes the chat back to its end with a message sent, where the reader had scrolled up', async ({
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
    await controller.play(chats.store, session, [text('route', ROUTE)]);
    await controller.finish(chats.store, session, 'success', 'The route.');
    await expect(chat.send).toBeVisible();

    const up = chat.sticky(false);
    await chat.body.hover();
    await page.mouse.wheel(0, -600);
    await up;
    const toEnd = () => chat.body.evaluate((body) => body.scrollHeight - body.scrollTop - body.clientHeight);
    expect(await toEnd()).toBeGreaterThan(100);

    await chat.field.fill('And the tent?');
    const sent = chat.acted('send');
    await chat.send.click();
    await sent;
    await expect(chat.messageTexts).toHaveText(['Plan the route.', 'And the tent?']);
    await expect.poll(toEnd).toBeLessThan(2);
    await expect(chat.messages.last()).toBeInViewport();
    await chats.working(session);
    await controller.finish(chats.store, session, 'success', 'The dome.');
    await expect(chat.send).toBeVisible();
  });

  test('keeps the words not sent in the browser, keyed by the project, after a reload too, until they are sent', async ({
    page,
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Kept'), members: [me.handle!] });
    const other = await projects.make({ name: makeUnique('Other'), members: [me.handle!] });
    const kept = () => page.evaluate((key) => JSON.parse(localStorage.getItem(key) ?? '{}') as Record<string, string>, UNSENT_KEY);
    await timeline.open(project);

    await chat.field.fill('Which stove?');
    expect(await kept()).toEqual({ [`chat/${project}`]: 'Which stove?' });
    await page.reload();
    await expect(chat.field).toHaveValue('Which stove?');
    await timeline.open(other);
    await expect(chat.field).toHaveValue('');
    await timeline.open(project);
    await expect(chat.field).toHaveValue('Which stove?');

    const opened = await chats.opening(project);
    await chat.send.click();
    const session = await opened();
    await expect(chat.field).toHaveValue('');
    expect(await kept()).toEqual({});
    await controller.finish(chats.store, session, 'success', 'The gas one.');
  });

  test('takes no message in an archived project and says why, its words kept, until Bring back', async ({
    people,
    projects,
    timeline,
    chat,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Archived'), members: [me.handle!] });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    await chat.field.fill('Shall we go after all?');
    await expect(chat.archived).toHaveCount(0);

    await projects.transition(project, 'archived');
    await expect(chat.archived).toHaveText(ARCHIVED);
    await expect(chat.field).toBeDisabled();
    await expect(chat.field).toHaveValue('Shall we go after all?');
    await expect(chat.send).toBeDisabled();

    // Opened again, it reads the same.
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    await expect(chat.archived).toHaveText(ARCHIVED);
    await expect(chat.field).toBeDisabled();

    await projects.transition(project, 'brought_back');
    await expect(chat.archived).toHaveCount(0);
    await expect(chat.field).toBeEnabled();
    await expect(chat.send).toBeEnabled();
  });
});
