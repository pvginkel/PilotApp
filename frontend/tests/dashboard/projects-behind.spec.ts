/**
 * The Projects screen behind the dashboard (F160.5): it shows nothing to what reads "this page
 * shows", so Esc closes nothing open in it but a dialog, which stands over the page whichever
 * screen shows, the shell's own keys acting on the dashboard still, and its project's chat, at its
 * end behind, marks no reply seen and moves at no key; and it still hears its events and stays
 * current, so that Projects shows what came meanwhile with nothing read again. Its beat and its
 * closing of notifications are the beat's and the device's specs'.
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { projectAddress } from '../support/projects';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '4c1f7a92-8e3d-4b56-a0d9-2f6e8b1c7a35';
const text = (id: string, words: string) =>
  JSON.stringify({
    type: 'assistant',
    message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] },
    parent_tool_use_id: null,
    session_id: CONVERSATION,
  });

/** A reply longer than the chat's view, so that a key moving up scrolls it. */
const ROUTE = Array.from({ length: 40 }, (_, index) => `Stage ${index + 1}, by the lake.`).join('\n\n');

const WORDS = Array.from({ length: 160 }, (_, index) => `word${index}`).join(' ');

/** The page's reads of the project's own API from the call on; read by the answer. */
function projectReads(page: Page, project: string): () => string[] {
  const reads: string[] = [];
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith(`/api/projects/${project}`)) reads.push(path);
  });
  return () => reads;
}

/** Nothing focused, so that a key goes to the page's body. */
const unfocus = (page: Page) => page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());

test.describe('The Projects screen behind the dashboard', () => {
  test('has nothing Esc closes while the dashboard shows, where the shell’s own keys still act; Esc closes it again once Projects shows', async ({
    page,
    people,
    projects,
    shell,
    timeline,
    projectHead,
    dashboard,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Behind'), members: [me.handle!] });
    await timeline.open(project);
    await shell.dashboardTab.click();
    await expect(dashboard.screen).toBeVisible();
    await shell.projectsTab.click();
    await projectHead.menuButton.click();
    await expect(projectHead.menu).toBeVisible();

    // Back to the dashboard by the browser, which leaves the menu open behind it.
    await page.goBack();
    await expect(page).toHaveURL(`${projectAddress(project)}#dash`);
    await expect(dashboard.screen).toBeVisible();
    await expect(projectHead.menu).toBeHidden();
    await expect(projectHead.menu).toHaveCount(1);
    await page.keyboard.press('?');
    await expect(shell.keys).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(shell.keys).toBeHidden();
    await page.keyboard.press('Escape');

    await page.goForward();
    await expect(shell.app).toBeVisible();
    await expect(projectHead.menu).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(projectHead.menu).toHaveCount(0);
  });

  test('has a dialog left open stand over the dashboard, where Esc closes it', async ({ page, people, projects, shell, timeline, projectHead, dashboard }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Behind'), members: [me.handle!] });
    await timeline.open(project);
    await shell.dashboardTab.click();
    await expect(dashboard.screen).toBeVisible();
    await shell.projectsTab.click();
    const dialog = projectHead.dialog('finish');
    await projectHead.choose('finish');
    await expect(dialog.root).toBeVisible();

    await page.goBack();
    await expect(dashboard.screen).toBeVisible();
    await expect(dialog.root).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(dialog.root).toHaveCount(0);
  });

  test('marks no reply seen at its chat’s end, and a key moves the chat nowhere; Projects shows the chat at its end, the reply marked seen there', async ({
    page,
    people,
    projects,
    controller,
    shell,
    timeline,
    chat,
    chats,
    dashboard,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Behind'), members: [me.handle!] });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    await expect(chat.tab).toHaveAttribute('aria-selected', 'true');
    const { session } = await chats.start(project, 'Plan the route.');
    const seen = chat.acted('read');
    await controller.play(chats.store, session, [text('route', ROUTE)]);
    await controller.finish(chats.store, session, 'success', 'The route.');
    await seen;

    await shell.dashboardTab.click();
    await expect(dashboard.screen).toBeVisible();
    await unfocus(page);
    for (const key of ['ArrowUp', 'PageUp', 'Home']) await page.keyboard.press(key);
    await chats.send(project, 'And the tent?');
    await chats.working(session);
    await controller.play(chats.store, session, [text('tent', 'The dome.')]);
    await controller.finish(chats.store, session, 'success', 'The dome.');
    await expect(chat.texts.last()).toHaveText('The dome.');
    await expect(chat.tabDot).toHaveCount(1);
    expect((await chats.list(project)).unread).toBe(true);

    // Still at its end, it marks the reply seen as it shows.
    const marked = chat.acted('read');
    await shell.projectsTab.click();
    await marked;
    await expect(chat.tabDot).toHaveCount(0);
    expect((await chats.list(project)).unread).toBe(false);

    // In view, the same key moves it up.
    await unfocus(page);
    const up = chat.sticky(false);
    await page.keyboard.press('PageUp');
    await up;
  });

  test('hears its events and stays current: what came while the dashboard showed is there as Projects shows, nothing read again', async ({
    page,
    people,
    projects,
    shell,
    timeline,
    dashboard,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Behind'), members: [me.handle!] });
    await projects.place(project, { kind: 'document', title: 'Alpha', text: `---\ntitle: Alpha\n---\n\n${WORDS}\n` });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const count = await timeline.items.count();

    await shell.dashboardTab.click();
    await expect(dashboard.screen).toBeVisible();
    await projects.place(project, { kind: 'document', title: 'Bravo', text: `---\ntitle: Bravo\n---\n\n${WORDS}\n` });
    await expect(timeline.items).toHaveCount(count + 1);
    await expect(shell.app).toBeHidden();

    const reads = projectReads(page, project);
    await shell.projectsTab.click();
    await expect(timeline.items.last()).toBeVisible();
    await expect(timeline.items).toHaveCount(count + 1);
    expect(reads()).toEqual([]);
  });
});
