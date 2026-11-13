/**
 * An ask Pilot added that the chat calls off on a person's word (DB 297): the brain's `cancel_ask`
 * closes it as cancelled, by them, live. Its done line leads with the cancelled mark, its kind's
 * icon in the time's grey with a small cross at its foot (F13.1), and offers no Undo; its block
 * stays unanswered; the call's line in the chat is its effect, "Cancelled · <title>", going to the
 * item. A folded ask comes out of its fold with the close.
 */

import { cssColour } from '../support/contrast';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '7d2b9e41-3c6a-4f85-b1e7-9a4c5d8f2e06';
const line = (value: object) => JSON.stringify({ ...value, session_id: CONVERSATION });
const text = (id: string, words: string) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] }, parent_tool_use_id: null });
const toolUse = (id: string, name: string, input: object) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'tool_use', id, name, input }] }, parent_tool_use_id: null });

const TENT = 'Which tent?';
const DECISION = 'Which tent for the trip?\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const STOVE = 'Buy the gas';
const ACTION = 'Two canisters, before Friday.\n\n```action id=A1\n```\n';

test.describe('An ask the chat called off', () => {
  test('is done as cancelled by the person it was called off for, live: its line under the cancelled mark with no Undo, its block unanswered, the call’s line in the chat its effect; a folded one comes out of its fold, and the ask beside it stays open', async ({
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
    deploymentSse,
    page,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Called off'), members: [me.handle!] });
    const tent = await projects.place(project, { kind: 'decision', title: TENT, text: DECISION, by_pilot: true });
    const stove = await projects.place(project, { kind: 'action', title: STOVE, text: ACTION, by_pilot: true });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(tent);
    await item.kind.click();
    await expect(item.root).toHaveAttribute('data-folded', 'true');

    const placed = (await projects.timeline(project)).items.length;

    const { session } = await chats.start(project, 'Never mind the tent, we sleep in the hut.');
    await controller.play(chats.store, session, [
      text('hut', 'The hut it is.'),
      toolUse('toolu_cancel', 'mcp__pilot__cancel_ask', { item: tent, for: me.handle }),
    ]);
    await chats.cancel(project, tent, me.handle!, { toolUseId: 'toolu_cancel' });

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.undo).toHaveCount(0);
    const mark = item.lineKind;
    await expect(mark).toHaveAttribute('title', 'Cancelled');
    await expect(mark).toHaveClass('kind-icon cancelled');
    await expect(mark.locator('g[mask] > svg')).toHaveClass(/\blucide-message-circle-question\b/);
    await expect(mark).toHaveCSS('color', await item.lineTime.evaluate((time) => getComputedStyle(time).color));
    await expect(mark).not.toHaveCSS('color', await cssColour(page, 'hsl(var(--primary))'));
    await expect(chat.root.getByTestId('chat.tool').last()).toHaveText(`Cancelled · ${TENT}`);

    const closed = await projects.item(project, tent);
    expect([closed.done?.cause, closed.done?.by?.handle, closed.done?.undo, closed.folded]).toEqual(['cancelled', me.handle, false, false]);
    expect(closed.body!.flatMap((part) => (part.type === 'block' ? [part.block.answer] : []))).toEqual([null]);
    // The close the chat records places no job after it, and the other ask waits on as it did.
    expect((await projects.timeline(project)).items.length).toBe(placed);
    await expect(timeline.item(stove).root).toHaveAttribute('data-state', 'open');

    await controller.finish(chats.store, session, 'success', 'Called off.');
    await chats.idle(project);
  });
});
