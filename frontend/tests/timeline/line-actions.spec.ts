/**
 * A done line's actions under the mouse (F13.8): what the line says shows always, its actions — Open,
 * Undo, Discuss — only while the mouse is on the line or the focus in it, taking no room until then
 * and adding no height, and always on a screen with no hover wider than a phone; its title opens
 * what is behind the line, the document in its tab or a work item's session log in its popover.
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { documentAddress } from '../support/page-objects/overlay-page';
import { sessionLogAddress } from '../support/page-objects/session-log-page';

const DECISION = 'Which tent do we take?\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const NOTES = { title: 'Tent notes', filename: 'tent-notes.md', content_type: 'text/markdown', content: '# Tents\n' };

const height = async (locator: Locator) => (await locator.boundingBox())!.height;
const box = async (locator: Locator) => (await locator.boundingBox())!;
/** The mouse off every line, on the top bar. */
const away = (page: Page) => page.mouse.move(1, 1);

test.describe('A done line’s actions', () => {
  test('show only under the mouse or with the focus in the line, taking no room and adding no height; what it says shows always', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Under the mouse'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await projects.attach(decision, [NOTES]);
    await projects.answer(decision, 'D1', 'Tunnel', 'Lighter to carry');
    await timeline.open(id);
    const item = timeline.item(decision);
    const actions = [item.open, item.undo, item.lineDiscuss];

    await away(page);
    await expect(item.root).toHaveAttribute('data-state', 'done');
    for (const action of actions) {
      await expect(action).toHaveCount(1);
      await expect(action).toBeHidden();
    }
    for (const said of [item.lineKind, item.lineTitle, item.said, item.lineAttachment, item.lineTime]) await expect(said).toBeVisible();
    const [line, title, attachment] = await Promise.all([box(item.line), box(item.lineTitle), box(item.lineAttachment)]);

    await item.line.hover();
    for (const action of actions) await expect(action).toBeVisible();
    expect(await height(item.line)).toBe(line.height);
    // The actions take the title's room, before the indicator, which stays and touches them.
    expect((await box(item.lineTitle)).width).toBeLessThan(title.width - 3 * 20);
    expect((await box(item.lineAttachment)).x).toBe(attachment.x);
    const discuss = await box(item.lineDiscuss);
    expect(discuss.x + discuss.width).toBeCloseTo(attachment.x, 0);
    for (const action of actions) {
      const { y, height: tall } = await box(action);
      expect(y).toBeGreaterThanOrEqual(line.y);
      expect(y + tall).toBeLessThanOrEqual(line.y + line.height);
    }

    await away(page);
    for (const action of actions) await expect(action).toBeHidden();
    expect((await box(item.lineTitle)).width).toBe(title.width);
    expect((await box(item.lineAttachment)).x).toBe(attachment.x);

    // From the keyboard: the focus on the title shows them, and Tab goes on through them.
    await item.lineTitle.focus();
    await expect(item.open).toBeVisible();
    await page.keyboard.press('Tab');
    await expect(item.open).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(item.undo).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(item.lineDiscuss).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(item.lineAttachment).toBeFocused();
    await expect(item.lineDiscuss).toBeVisible();
    expect(await height(item.line)).toBe(line.height);
  });

  test('add no height to a work item’s quiet line', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Quiet'), members: [me.handle!] });
    const work = await projects.startWork(id, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
    await projects.transition(id, 'finished');
    await timeline.open(id);
    const item = timeline.item(work);

    await away(page);
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.root).toHaveClass(/\bquiet\b/);
    await expect(item.open).toBeHidden();
    const line = await height(item.line);
    await item.line.hover();
    await expect(item.open).toBeVisible();
    await expect(item.lineDiscuss).toBeVisible();
    expect(await height(item.line)).toBe(line);
  });

  test('take the focus back from the session log Open opened, from the keyboard or the mouse', async ({ page, people, projects, timeline, sessionLog }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Back to Open'), members: [me.handle!] });
    const work = await projects.startWork(id, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
    await projects.transition(id, 'finished');
    await timeline.open(id);
    const item = timeline.item(work);

    await away(page);
    await item.lineTitle.focus();
    await page.keyboard.press('Tab');
    await expect(item.open).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(sessionLog.overlay).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(sessionLog.overlay).toHaveCount(0);
    await expect(item.open).toBeFocused();
    await expect(item.open).toBeVisible();

    await item.line.hover();
    await item.open.click();
    await expect(sessionLog.overlay).toBeFocused();
    await away(page);
    await page.keyboard.press('Escape');
    await expect(sessionLog.overlay).toHaveCount(0);
    await expect(item.open).toBeFocused();
    await expect(item.open).toBeVisible();
  });

  test.describe('on a screen with no hover wider than a phone', () => {
    test.use({ hasTouch: true });

    test('show always', async ({ page, people, projects, timeline }) => {
      const me = await people.signIn();
      const id = await projects.makeWithSession({ name: makeUnique('No hover'), members: [me.handle!] });
      const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
      await projects.answer(decision, 'D1', 'Tunnel');
      await timeline.open(id);
      const item = timeline.item(decision);

      expect(await page.evaluate(() => window.matchMedia('(hover: hover)').matches)).toBe(false);
      await expect(item.root).toHaveAttribute('data-state', 'done');
      for (const action of [item.open, item.undo, item.lineDiscuss]) await expect(action).toBeVisible();
    });
  });
});

test.describe('A done line’s title', () => {
  test('opens its document in a tab, from the mouse or the keyboard, a link named by the title', async ({ page, people, projects, timeline, docTabs }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Title'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await projects.answer(decision, 'D1', 'Tunnel');
    await timeline.open(id);
    const item = timeline.item(decision);

    const link = item.line.getByRole('link', { name: 'Which tent?' });
    await expect(link).toHaveAttribute('href', documentAddress(id, decision));
    await expect(link).toHaveAttribute('data-testid', 'timeline.line.title');
    await expect(link).toHaveAttribute('title', 'Which tent?');
    await item.lineTitle.click();
    await expect(page).toHaveURL(documentAddress(id, decision));
    await expect(docTabs.document(decision).root).toBeVisible();
    await expect(page.locator('[data-testid="overlay"][role="tabpanel"]')).toBeVisible();

    await docTabs.document(decision).close.click();
    await expect(page).toHaveURL(`/projects/${id}`);
    await item.lineTitle.focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(documentAddress(id, decision));
    await expect(docTabs.document(decision).root).toBeVisible();
  });

  test('of a work item opens its session log in the popover', async ({ page, people, projects, timeline, sessionLog }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Log'), members: [me.handle!] });
    const work = await projects.startWork(id, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
    await projects.transition(id, 'finished');
    await timeline.open(id);
    const item = timeline.item(work);

    await expect(item.lineTitle).toHaveAttribute('href', sessionLogAddress(id, work));
    await item.lineTitle.click();
    await expect(page).toHaveURL(sessionLogAddress(id, work));
    await expect(sessionLog.overlay).toBeVisible();
    await expect(sessionLog.item).toHaveText('Surveying the stylesheets');
  });
});
