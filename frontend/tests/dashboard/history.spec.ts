/**
 * The dashboard's history (F160.4) and its links (F161.3): Back and Forward move a tab's state
 * alone and stay in their tab, its name and what Reset goes back to staying; a close adds no entry,
 * and Back into a closed tab opens it again as it was. A link, from outside the dashboard's own
 * moves, shows the tab already showing its state, read in the server's normal form, else opens a
 * tab of its own, never another state in a tab that is open; off a phone a dashboard link in a reply
 * of Pilot's opens on the page it is read on, the project kept behind.
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { dashboardAddress, type DashboardPage } from '../support/page-objects/dashboard-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';

const SCRATCH = 't=qw&by=project&m=cost.sum&col=none';
/** The start from scratch, its parts in another order: its normal form is the same. */
const SCRATCH_REWRITTEN = 'by=project&t=qw&col=none&m=cost.sum';
const BY_MODEL = 't=qw&by=model&m=cost.sum&col=none';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '7e2b9c41-5d8a-4f36-b1c7-3a9e6d2f8b54';
const text = (id: string, words: string) =>
  JSON.stringify({
    type: 'assistant',
    message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] },
    parent_tool_use_id: null,
    session_id: CONVERSATION,
  });

const historyLength = (page: Page) => page.evaluate(() => history.length);
const open = (dashboard: DashboardPage, list: Locator, name: string) => dashboard.view(list, name).getByTestId('dashboard.panel.view.open').click();
const lineTab = (dashboard: DashboardPage, name: string) => dashboard.lineTab(name).getByRole('tab');

async function aProject(people: People, projects: Projects) {
  const me = await people.signIn();
  return projects.make({ name: makeUnique('History'), members: [me.handle!] });
}

test.describe('The dashboard’s history', () => {
  test('Back and Forward move a tab’s state alone and stay in their tab, its name and what Reset goes back to staying', async ({
    page,
    people,
    projects,
    shell,
    dashboard,
    savedViews,
  }) => {
    const project = await aProject(people, projects);
    const name = makeUnique('Moved');
    await savedViews.save(name, SCRATCH);
    await shell.open(`${projectAddress(project)}#dash`);
    await open(dashboard, dashboard.savedViews, name);
    await expect(dashboard.tab).toHaveText(name);
    const [first] = await dashboard.keptTabs();
    await dashboard.go(dashboardAddress(BY_MODEL, first.id));
    await expect(dashboard.byHeading).toHaveText('Model');
    await dashboard.newView.click();
    await dashboard.scratch.click();
    await expect(dashboard.lineNames).toHaveText([name, 'Project']);

    await page.goBack();
    await expect(dashboard.panel).toBeVisible();
    await page.goBack();
    await expect(lineTab(dashboard, name)).toHaveAttribute('aria-selected', 'true');
    await expect(dashboard.lineNames).toHaveText([name, 'New view']);
    await expect(dashboard.byHeading).toHaveText('Model');
    await expect(dashboard.reset).toBeEnabled();
    await page.goBack();
    await expect(dashboard.byHeading).toHaveText('Project');
    await expect(lineTab(dashboard, name)).toHaveAttribute('aria-selected', 'true');
    await expect(dashboard.reset).toBeDisabled();
    await page.goForward();
    await expect(dashboard.byHeading).toHaveText('Model');
    await expect(dashboard.lineNames).toHaveText([name, 'New view']);
    await expect(dashboard.reset).toBeEnabled();
  });

  test('a tab’s close adds no entry; Back into a closed tab opens it again, its saved view’s name and what Reset goes back to with it', async ({
    page,
    people,
    projects,
    shell,
    dashboard,
    savedViews,
  }) => {
    const project = await aProject(people, projects);
    const name = makeUnique('Closed');
    await savedViews.save(name, SCRATCH);
    await shell.open(`${projectAddress(project)}#dash`);
    await open(dashboard, dashboard.savedViews, name);
    const [first] = await dashboard.keptTabs();
    await dashboard.go(dashboardAddress(BY_MODEL, first.id));
    await expect(dashboard.byHeading).toHaveText('Model');
    await dashboard.newView.click();
    await dashboard.scratch.click();
    await lineTab(dashboard, name).click();
    await expect(dashboard.byHeading).toHaveText('Model');

    const entries = await historyLength(page);
    await dashboard.lineTab(name).getByTestId('dashboard.tabs.tab.close').click();
    await expect(dashboard.line).toHaveCount(0);
    await expect(dashboard.tab).toHaveText('Project');
    expect(await historyLength(page)).toBe(entries);

    // The entry before the close's is the tab that showed after it, then the new tab's panel.
    await page.goBack();
    await expect(dashboard.byHeading).toHaveText('Project');
    await page.goBack();
    await expect(dashboard.panel).toBeVisible();
    await page.goBack();
    await expect(dashboard.lineNames).toHaveText(['New view', name]);
    await expect(lineTab(dashboard, name)).toHaveAttribute('aria-selected', 'true');
    await expect(dashboard.byHeading).toHaveText('Model');
    expect((await dashboard.keptTabs()).map((tab) => tab.id)).toContain(first.id);
    await dashboard.reset.click();
    await expect(dashboard.byHeading).toHaveText('Project');
    await expect(dashboard.lineNames).toHaveText(['New view', name]);
  });
});

test.describe('A dashboard link', () => {
  test('shows the tab already showing its state, read in the server’s normal form, the address written back in place to name it; else opens a tab of its own, never another state in a tab that is open', async ({
    page,
    people,
    projects,
    shell,
    dashboard,
  }) => {
    const project = await aProject(people, projects);
    await shell.open(`${projectAddress(project)}#dash`);
    await dashboard.scratch.click();
    await expect(dashboard.tab).toHaveText('Project');
    const [first] = await dashboard.keptTabs();
    const reads = dashboard.addressReads();

    await dashboard.follow(`#dash/${SCRATCH_REWRITTEN}`);
    await expect(page).toHaveURL(`${projectAddress(project)}#dash/${first.id}/${SCRATCH}`);
    expect(reads()).toEqual([SCRATCH_REWRITTEN]);
    await expect(dashboard.line).toHaveCount(0);
    expect(await dashboard.keptTabs()).toEqual([{ id: first.id, now: SCRATCH }]);

    await dashboard.follow(`#dash/${first.id}/${BY_MODEL}`);
    await expect(dashboard.lineNames).toHaveText(['Project', 'Model']);
    await expect(lineTab(dashboard, 'Model')).toHaveAttribute('aria-selected', 'true');
    const tabs = await dashboard.keptTabs();
    expect(tabs[0]).toEqual({ id: first.id, now: SCRATCH });
    expect(tabs[1]).toEqual({ id: expect.not.stringMatching(`^${first.id}$`), now: BY_MODEL });
    await expect(page).toHaveURL(`${projectAddress(project)}#dash/${tabs[1].id}/${BY_MODEL}`);

    await lineTab(dashboard, 'Project').click();
    await dashboard.follow(`#dash/${BY_MODEL}`);
    await expect(lineTab(dashboard, 'Model')).toHaveAttribute('aria-selected', 'true');
    await expect(dashboard.lineNames).toHaveText(['Project', 'Model']);
    await expect(page).toHaveURL(`${projectAddress(project)}#dash/${tabs[1].id}/${BY_MODEL}`);
  });

  test('in a reply of Pilot’s opens on the page it is read on, a new entry in a tab of its own, the project kept behind', async ({
    page,
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
    shell,
    dashboard,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Reply'), members: [me.handle!] });
    await timeline.open(project);
    const { session } = await chats.start(project, 'Where did the week go?');
    const reply = `See [the week by model](#dash/${BY_MODEL}) and [the guide](https://example.com/guide).`;
    await controller.play(chats.store, session, [text('week', reply)]);
    await controller.finish(chats.store, session, 'success', reply);
    const link = chat.texts.getByRole('link', { name: 'the week by model' });
    await expect(link).toHaveAttribute('href', `#dash/${BY_MODEL}`);
    await expect(link).not.toHaveAttribute('target');
    await expect(chat.texts.getByRole('link', { name: 'the guide' })).toHaveAttribute('target', '_blank');

    const entries = await historyLength(page);
    await link.click();
    await expect(dashboard.screen).toBeVisible();
    await expect(dashboard.tab).toHaveText('Model');
    const [tab] = await dashboard.keptTabs();
    await expect(page).toHaveURL(`${projectAddress(project)}#dash/${tab.id}/${BY_MODEL}`);
    expect(await historyLength(page)).toBe(entries + 1);
    expect(page.context().pages()).toHaveLength(1);

    await shell.projectsTab.click();
    await expect(page).toHaveURL(projectAddress(project));
    await expect(link).toBeVisible();
  });
});
