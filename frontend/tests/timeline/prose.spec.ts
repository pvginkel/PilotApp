/**
 * Prose headings (A7): a heading reads as one, the three steps of the type scale over the body's
 * for h1 to h3 and the body's size for h4 to h6, all of them bold; and it keeps its space above
 * wherever it falls, a heading that opens a later part of a text included, after a prose part, a
 * block, an item's ask or a reply's steps. Only a text's first part starts flush. A writer's reply
 * to a clarification is in tests/work/clarification.spec.ts.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { headingOf, scaleOf } from '../support/prose';

const SIZES = 'Before them.\n\n# One\n\n## Two\n\n### Three\n\n#### Four\n\n##### Five\n\n###### Six\n\nAfter them.\n';
const TENT = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```';
// Two blocks, so that it is a document and no one-ask item; each block's section a part of its own.
const PARTS = [
  '---\ntitle: The trip\n---\n',
  '## Start\n\nWe leave on Friday.\n',
  '## Which tent?\n\nThe dome is lighter.\n',
  `${TENT}\n`,
  '### After the block\n\nWe pack on Thursday.\n',
  '## How many nights?\n',
  '```question id=Q1\n```\n',
].join('\n');
const ACTION = 'Plug the lamp in.\n\n```action id=A1\n```\n\n## Afterwards\n\nTell me what it says.\n';
const PHONE = { width: 390, height: 844 };

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '2c7f9a41-5e3b-4d86-9a1c-6b0e4f8d2a57';
const line = (value: object) => JSON.stringify({ ...value, session_id: CONVERSATION });
const text = (id: string, words: string) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] }, parent_tool_use_id: null });
const toolUse = (id: string, name: string, input: object) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'tool_use', id, name, input }] }, parent_tool_use_id: null });
const toolResult = (id: string, content: string) =>
  line({ type: 'user', message: { role: 'user', content: [{ tool_use_id: id, type: 'tool_result', content }] }, parent_tool_use_id: null });

test.describe('A prose heading', () => {
  test('is bold and sized by the type scale: h1 to h3 its three steps over the body’s, h4 to h6 the body’s, off a phone and on one', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Sizes'), members: [me.handle!] });
    const placed = await projects.place(id, { kind: 'document', title: 'The sizes', text: SIZES });
    await timeline.open(id);
    const document = timeline.item(placed).root.getByTestId('timeline.item.document');
    const heading = (name: string) => headingOf(document.getByRole('heading', { name, exact: true }));
    const words = document.getByText('After them.');

    for (const viewport of [page.viewportSize()!, PHONE]) {
      await page.setViewportSize(viewport);
      const [base, lg, xl, xxl] = await Promise.all(['--text-base', '--text-lg', '--text-xl', '--text-2xl'].map((name) => scaleOf(document, name)));
      expect(base).toBeLessThan(lg);
      await expect(words).toHaveCSS('font-size', `${base}px`);
      await expect(words).toHaveCSS('font-weight', '400');
      const [one, two, three, four, five, six] = await Promise.all(['One', 'Two', 'Three', 'Four', 'Five', 'Six'].map(heading));
      expect([one.size, two.size, three.size]).toEqual([xxl, xl, lg]);
      expect([four.size, five.size, six.size]).toEqual([base, base, base]);
      for (const each of [one, two, three, four, five, six]) {
        expect(each.weight).toBe('600');
        // Each stands under the heading before it by its own space.
        expect(each.above).toBeGreaterThan(each.size);
        expect(each.gap).toBeGreaterThanOrEqual(each.above - 0.5);
      }
    }
  });

  test('that opens a later part of a document keeps its space above, after a prose part and after a block, inline and in the document’s tab; the first part starts flush', async ({
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Parts'), members: [me.handle!] });
    const placed = await projects.place(id, { kind: 'document', title: 'The trip', text: PARTS });
    await timeline.open(id);

    for (const document of [timeline.item(placed).root.getByTestId('timeline.item.document'), overlay.document]) {
      if (document === overlay.document) await overlay.open(id, placed);
      const start = await headingOf(document.getByRole('heading', { name: 'Start' }));
      expect(start).toMatchObject({ opens: true, first: true, above: 0, gap: 0 });

      const tent = await headingOf(document.getByRole('heading', { name: 'Which tent?' }));
      expect(tent).toMatchObject({ opens: true, first: false });
      expect(tent.above).toBeCloseTo(1.4 * tent.size, 1);
      expect(tent.gap).toBeGreaterThanOrEqual(tent.above - 0.5);

      const after = await headingOf(document.getByRole('heading', { name: 'After the block' }));
      expect(after).toMatchObject({ opens: true, first: false });
      expect(after.above).toBeCloseTo(1.2 * after.size, 1);
      expect(after.gap).toBeGreaterThanOrEqual(after.above - 0.5);
    }
  });

  test('that opens an item’s text after its ask keeps its space above', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Ask'), members: [me.handle!] });
    const placed = await projects.place(id, { kind: 'action', title: 'Light the hall', text: ACTION });
    await timeline.open(id);

    const afterwards = await headingOf(timeline.item(placed).root.getByRole('heading', { name: 'Afterwards' }));
    expect(afterwards).toMatchObject({ opens: true, first: false });
    expect(afterwards.above).toBeCloseTo(1.4 * afterwards.size, 1);
    expect(afterwards.gap).toBeGreaterThanOrEqual(afterwards.above - 0.5);
  });

  test('that opens a reply’s text after its steps keeps its space above; the reply’s first text starts flush', async ({
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Reply'), members: [me.handle!] });
    await timeline.open(project);
    const { session } = await chats.start(project, 'Where does the cue live?');
    await controller.play(chats.store, session, [
      text('one', '## Looking\n\nIn the chat’s folder.'),
      toolUse('read', 'Read', { file_path: '/work/Example/README.md' }),
      toolResult('read', '# Example'),
      text('two', '## Found\n\nIt is in the reply.'),
    ]);
    await controller.finish(chats.store, session, 'success', 'Found.');
    await expect(chat.texts).toHaveCount(2);

    const looking = await headingOf(chat.texts.getByRole('heading', { name: 'Looking' }));
    expect(looking).toMatchObject({ opens: true, first: true, above: 0 });
    const found = await headingOf(chat.texts.getByRole('heading', { name: 'Found' }));
    expect(found).toMatchObject({ opens: true, first: false });
    expect(found.above).toBeCloseTo(1.4 * found.size, 1);
    expect(found.gap).toBeGreaterThanOrEqual(found.above - 0.5);
  });
});
