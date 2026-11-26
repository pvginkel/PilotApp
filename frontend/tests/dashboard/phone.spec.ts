/**
 * Not on a phone (F160.9): no screens' tabs and no dashboard, its module never read; a dashboard
 * address shows the app, its hash taken off in place, on Back into such an entry too; a window
 * narrowed to a phone's width keeps a dashboard drawn, out of sight and inert; a dashboard link in a
 * reply of Pilot's stands as its words, with no link.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { projectAddress } from '../support/projects';

const PHONE = { width: 390, height: 844 };
/** A dashboard address of a tab and its view's state, as a link names one. */
const VIEW = '#dash/t1/t=qw&by=project&m=cost.sum&col=none';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '9d3b6e14-2a7c-4f85-b0e1-6c8a4d2f9e57';
const text = (id: string, words: string) =>
  JSON.stringify({
    type: 'assistant',
    message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] },
    parent_tool_use_id: null,
    session_id: CONVERSATION,
  });

test.describe('On a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('a dashboard address shows the app at its path, its hash taken off in place, with no screens’ tabs and no dashboard, its module never read', async ({
    page,
    people,
    projects,
    shell,
    phoneTabs,
    dashboard,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Phone'), members: [me.handle!] });
    const moduleReads = dashboard.moduleReads();

    await shell.open(`${projectAddress(project)}${VIEW}`);
    await expect(page).toHaveURL(projectAddress(project));
    await expect(phoneTabs.root).toBeVisible();
    await expect(shell.screens).toHaveCount(0);
    await expect(dashboard.screen).toHaveCount(0);

    // Under the project only the home's entry, which it lies over.
    await page.goBack();
    await expect(page).toHaveURL('/');
    await expect(shell.home).toBeVisible();

    // Within the page, as a link goes there.
    await page.goto(`/${VIEW}`);
    await expect(page).toHaveURL('/');
    await expect(shell.home).toBeVisible();
    await expect(dashboard.screen).toHaveCount(0);
    expect(moduleReads()).toBe(0);
  });

  test('a dashboard link in a reply of Pilot’s stands as its words, with no link, where another link stays one', async ({
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Phone'), members: [me.handle!] });
    const { session } = await chats.start(project, 'Where did the week go?');
    const reply = 'See [the week by project](#dash/t=qw&by=project&m=cost.sum&col=none) and [the guide](https://example.com/guide).';
    await controller.play(chats.store, session, [text('week', reply)]);
    await controller.finish(chats.store, session, 'success', reply);
    await timeline.open(project);

    await phoneTabs.tab('chat').tap();
    await expect(chat.texts).toHaveText(['See the week by project and the guide.']);
    await expect(chat.texts.locator('a')).toHaveCount(1);
    await expect(chat.texts.locator('a')).toHaveText('the guide');
    await expect(chat.texts.locator('a')).toHaveAttribute('href', 'https://example.com/guide');
  });
});

test.describe('A window narrowed to a phone’s width', () => {
  test('keeps the dashboard drawn, out of sight and inert, and shows the app at its address, the hash taken off in place', async ({
    page,
    people,
    projects,
    shell,
    timeline,
    phoneTabs,
    dashboard,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Narrowed'), members: [me.handle!] });
    await timeline.open(project);
    await shell.dashboardTab.click();
    await expect(dashboard.screen).toBeVisible();

    await page.setViewportSize(PHONE);
    await expect(page).toHaveURL(projectAddress(project));
    await expect(phoneTabs.root).toBeVisible();
    await expect(dashboard.screen).toBeHidden();
    await expect(dashboard.screen).toHaveAttribute('inert', '');
  });

  test('shows the app on Back into a dashboard’s entry, its hash taken off there too', async ({ page, people, projects, shell, timeline, phoneTabs, dashboard }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Narrowed'), members: [me.handle!] });
    await timeline.open(project);
    await shell.dashboardTab.click();
    await expect(dashboard.screen).toBeVisible();
    await shell.projectsTab.click();
    await expect(shell.app).toBeVisible();
    // Narrowed on the project, the phone's home is put in its entry's place, the project over it.
    await page.setViewportSize(PHONE);
    await expect(phoneTabs.root).toBeVisible();
    await page.goBack();
    await expect(shell.home).toBeVisible();
    const addresses: string[] = [];
    page.on('framenavigated', (frame) => {
      if (frame === page.mainFrame()) addresses.push(new URL(frame.url()).pathname + new URL(frame.url()).hash);
    });

    await page.goBack();
    await expect(page).toHaveURL(projectAddress(project));
    await expect(phoneTabs.root).toBeVisible();
    expect(addresses[0]).toBe(`${projectAddress(project)}#dash`);
    await expect(dashboard.screen).toBeHidden();
  });
});
