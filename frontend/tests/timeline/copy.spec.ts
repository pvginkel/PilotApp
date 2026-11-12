/**
 * The copy buttons of the timeline and a document (D7): an action's prose as Pilot wrote it, from
 * its head beside Discuss; a code block's source, from its top right in any prose, under the mouse
 * off a phone and always on one; a document's text as written, front matter, prose and blocks, from
 * its opened head beside Discuss. Each shows a check for a moment once copied. A reply's copy in
 * the chat is in tests/chat/chat-tab.spec.ts.
 */

import type { Locator } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { allowClipboard, copied } from '../support/clipboard';
import { makeUnique } from '../support/helpers';

const COMMAND = 'kc lamp on --room "hall"\nkc lamp status';
const BEFORE = `Plug the **lamp** in, then run:\n\n\`\`\`sh\n${COMMAND}\n\`\`\``;
const AFTER = 'Tell me what it _says_.';
const ACTION = `${BEFORE}\n\n\`\`\`action id=A1\n\`\`\`\n\n${AFTER}\n`;
const DECISION = 'Which tent?\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const TENT = '```decision id=D1\noptions:\n  - Dome: up in five minutes\n  - Tunnel\nrecommend: Dome\n```';
const TRIP = `---\nsummary: Where we go.\n---\n\nWe leave on **Friday**.\n\n## Which tent?\n\n${TENT}\n\nWe pack on Thursday.\n`;
const PHONE = { width: 390, height: 844 };

const box = async (part: Locator) => (await part.boundingBox())!;
const opacity = (part: Locator) => part.evaluate((element) => getComputedStyle(element).opacity);

test.describe('An action’s copy', () => {
  test('stands in its head before Discuss, touching it, and copies its prose as Pilot wrote it, without its block; a check shows for a moment', async ({
    context,
    page,
    people,
    projects,
    timeline,
  }) => {
    await allowClipboard(context);
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Copy'), members: [me.handle!] });
    const action = await projects.place(id, { kind: 'action', title: 'Light the hall', text: ACTION });
    const decision = await projects.place(id, { kind: 'decision', title: 'The tent', text: DECISION });
    await timeline.open(id);
    const item = timeline.item(action);

    await expect(item.copy).toHaveAttribute('title', 'Copy the action’s text');
    await expect(item.copy).toHaveAccessibleName('Copy the action’s text');
    const [copy, discuss] = await Promise.all([box(item.copy), box(item.discuss)]);
    expect(copy.x + copy.width).toBeCloseTo(discuss.x, 0);
    expect(copy.y).toBeCloseTo(discuss.y, 0);
    await expect(item.copy).toHaveAttribute('data-copy-state', 'idle');
    await expect(item.copy.locator('.lucide-copy')).toBeVisible();

    await item.copy.click();
    await expect(item.copy).toHaveAttribute('data-copy-state', 'success');
    await expect(item.copy.locator('.lucide-check')).toBeVisible();
    expect(await copied(page)).toBe(`${BEFORE}\n\n${AFTER}`);
    await expect(item.copy).toHaveAttribute('data-copy-state', 'idle');
    await expect(item.copy.locator('.lucide-copy')).toBeVisible();

    // Only an action's head has one.
    await expect(timeline.item(decision).discuss).toBeVisible();
    await expect(timeline.item(decision).copy).toHaveCount(0);
  });
});

test.describe('A code block’s copy', () => {
  test('stands at the block’s top right under the mouse or with the focus, and copies its source without the newline that ends it', async ({
    context,
    page,
    people,
    projects,
    timeline,
  }) => {
    await allowClipboard(context);
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Code'), members: [me.handle!] });
    const action = await projects.place(id, { kind: 'action', title: 'Light the hall', text: ACTION });
    await timeline.open(id);
    const item = timeline.item(action);
    const code = item.text.locator('pre');

    await expect(item.codeCopies).toHaveCount(1);
    // The block ends its part, before the ask, flush as any part's last line does.
    expect(await item.text.locator('.code-block').evaluate((element) => getComputedStyle(element).marginBottom)).toBe('0px');
    const button = item.codeCopies.first();
    await page.mouse.move(0, 0);
    expect(await opacity(button)).toBe('0');
    await code.hover();
    expect(await opacity(button)).toBe('1');
    const [block, at] = await Promise.all([box(code), box(button)]);
    expect(at.y - block.y).toBeCloseTo(4, 0);
    expect(block.x + block.width - (at.x + at.width)).toBeCloseTo(4, 0);

    await button.click();
    await expect(button).toHaveAttribute('data-copy-state', 'success');
    expect(await copied(page)).toBe(COMMAND);

    // The keyboard's focus shows it with the mouse away.
    await expect(button).toHaveAttribute('data-copy-state', 'idle');
    await page.mouse.move(0, 0);
    await item.copy.focus();
    expect(await opacity(button)).toBe('0');
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    await expect(button).toBeFocused();
    expect(await opacity(button)).toBe('1');
  });
});

test.describe('A document’s copy', () => {
  test('stands in its opened head before Discuss and copies its text as written, its front matter, prose and blocks', async ({
    context,
    page,
    people,
    projects,
    overlay,
  }) => {
    await allowClipboard(context);
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Text'), members: [me.handle!] });
    const document = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    const { text } = await projects.document(document);
    await overlay.open(id, document);

    await expect(overlay.copy).toHaveAttribute('title', 'Copy the document’s text');
    const [copy, discuss] = await Promise.all([box(overlay.copy), box(overlay.discuss)]);
    expect(copy.x).toBeLessThan(discuss.x);
    expect(copy.y).toBeCloseTo(discuss.y, 0);

    await overlay.copy.click();
    await expect(overlay.copy).toHaveAttribute('data-copy-state', 'success');
    const got = await copied(page);
    expect(got).toBe(text);
    expect(got).toContain('summary: Where we go.');
    expect(got).toContain('We leave on **Friday**.\n\n## Which tent?');
    expect(got).toContain(TENT);
    expect(got).toContain('We pack on Thursday.');
    await expect(overlay.copy).toHaveAttribute('data-copy-state', 'idle');
  });
});

test.describe('On a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('an action’s copy and Discuss stand side by side at the end of its head’s first row, clear of its other parts, and a code block’s copy shows always, the code keeping clear of it', async ({
    context,
    page,
    people,
    projects,
    timeline,
  }) => {
    await allowClipboard(context);
    const me = await people.signIn();
    const ben = makeUnique('ben', 8);
    await people.other(ben, 'Ben Example');
    const id = await projects.makeWithSession({ name: makeUnique('Phone'), members: [me.handle!, ben] });
    const action = await projects.place(id, { kind: 'action', title: 'Light the hall', text: `---\nfor: ${ben}\nurgent: true\n---\n\n${ACTION}` });
    await timeline.open(id);
    const item = timeline.item(action);

    const [head, kind, copy, discuss] = await Promise.all([box(item.head), box(item.kind), box(item.copy), box(item.discuss)]);
    expect(copy.y).toBeCloseTo(discuss.y, 0);
    expect(copy.y).toBeCloseTo(head.y, 0);
    expect(copy.x + copy.width).toBeCloseTo(discuss.x, 0);
    expect(discuss.x + discuss.width).toBeCloseTo(head.x + head.width, 0);
    // Every other part of the head ends before the copy.
    const ends = await item.head.evaluate((element) =>
      Array.from(element.children)
        .filter((child) => !child.matches('.item-copy, .item-discuss'))
        .map((child) => child.getBoundingClientRect())
        .filter((rect) => rect.width > 0)
        .map((rect) => rect.right),
    );
    expect(ends.length).toBeGreaterThan(2);
    for (const end of ends) expect(end).toBeLessThanOrEqual(copy.x);
    expect(kind.y).toBeGreaterThanOrEqual(head.y);

    const button = item.codeCopies.first();
    const code = item.text.locator('pre');
    expect(await opacity(button)).toBe('1');
    await expect(code).toHaveCSS('padding-right', '36px');
    const [block, at] = await Promise.all([box(code), box(button)]);
    expect(at.x).toBeGreaterThanOrEqual(block.x + block.width - 36);
    await button.tap();
    await expect(button).toHaveAttribute('data-copy-state', 'success');
    expect(await copied(page)).toBe(COMMAND);
  });
});
