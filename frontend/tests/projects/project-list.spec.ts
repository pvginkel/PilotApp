/**
 * The project list (F1): the person's projects, then Other projects and Finished, each group with
 * its count and a remembered chevron; a tab's name, ticket id and status line; each project at its
 * own address, the bare address opening the one the browser remembers; the archived projects
 * (D012).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

const step = (id: string, status: 'pending' | 'in_progress' | 'done') => ({ id, title: `Step ${id}`, status });

test.describe('The project list', () => {
  test('lists the person’s projects first, then Other projects and Finished, each with its count', async ({
    people,
    projects,
    projectList,
  }) => {
    const me = await people.signIn();
    const mine = await projects.make({ name: makeUnique('Mine'), members: [me.handle!] });
    const draft = makeUnique('Draft');
    await projects.make({ name: draft, state: 'draft', members: [me.handle!] });
    const other = makeUnique('Other');
    await projects.make({ name: other, members: ['ada'] });
    const done = makeUnique('Done');
    await projects.make({ name: done, state: 'finished', members: [me.handle!] });
    const listed = await projects.list();
    await projectList.open(mine);

    await expect(projectList.head).toHaveText('Projects');
    await expect(projectList.mine.getByTestId('projects.tab.name')).toHaveText([listed.find((p) => p.id === mine)!.name!, draft]);
    const others = projectList.group('others');
    const finished = projectList.group('finished');
    await expect(others.toggle).toHaveText(`Other projects${listed.filter((p) => !p.member && p.state !== 'finished').length}`);
    await expect(finished.toggle).toHaveText(`Finished${listed.filter((p) => p.state === 'finished').length}`);
    // Closed while the project on screen is in neither.
    await expect(others.toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(others.root.getByTestId('projects.tab')).toHaveCount(0);
    await expect(finished.toggle).toHaveAttribute('aria-expanded', 'false');

    await others.toggle.click();
    await expect(others.toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(projectList.tab(other, others.root)).toBeVisible();
    await expect(projectList.tab('Recipe box', others.root)).toBeVisible();
    await finished.toggle.click();
    await expect(projectList.tab(done, finished.root)).toBeVisible();
    await expect(projectList.tab('Bike repair log', finished.root)).toBeVisible();
    // The archived project is not in the list.
    await expect(projectList.tab('Photo album')).toHaveCount(0);
  });

  test('a tab shows the name, the ticket id and the status line', async ({ people, projects, projectList }) => {
    const me = await people.signIn();
    const member = { members: [me.handle!] };
    const notStarted = makeUnique('Not started');
    const first = await projects.make({ name: notStarted, ticket: 'PL-7', tasks: [step('a', 'pending')], ...member });
    const named = makeUnique('Draft');
    await projects.make({ name: named, state: 'draft', ...member });
    await projects.make({ state: 'draft', ...member });
    const between = makeUnique('Between');
    await projects.make({ name: between, tasks: [step('a', 'done'), step('b', 'pending'), step('c', 'pending')], ...member });
    const one = makeUnique('One');
    await projects.make({ name: one, tasks: [step('a', 'done'), step('b', 'in_progress'), step('c', 'pending')], ...member });
    const two = makeUnique('Two');
    await projects.make({ name: two, tasks: [step('a', 'in_progress'), step('b', 'pending'), step('c', 'in_progress')], ...member });
    const all = makeUnique('All');
    await projects.make({ name: all, tasks: [step('a', 'done'), step('b', 'done')], ...member });
    await projectList.open(first);

    const status = (name: string) => projectList.tab(name).getByTestId('projects.tab.status');
    await expect(projectList.tab(notStarted).getByTestId('projects.tab.ticket')).toHaveText('PL-7');
    await expect(projectList.tab(named).getByTestId('projects.tab.ticket')).toHaveCount(0);
    await expect(status(notStarted)).toHaveText('Not started');
    await expect(status(named)).toHaveText('Draft');
    // A draft without a title yet.
    await expect(status('New project')).toHaveText('Draft');
    await expect(status(between)).toHaveText('1 of 3 done');
    await expect(status(one)).toHaveText('Step b');
    await expect(status(two)).toHaveText('Step a, …');
    await expect(status(all)).toHaveText('All steps done');
  });

  test('the tab of the project on screen is the current one', async ({ people, projects, projectList }) => {
    const me = await people.signIn();
    const a = makeUnique('A');
    const aId = await projects.make({ name: a, members: [me.handle!] });
    const b = makeUnique('B');
    const bId = await projects.make({ name: b, members: [me.handle!] });
    await projectList.open(aId);

    await expect(projectList.tab(a)).toHaveAttribute('aria-current', 'page');
    await expect(projectList.tab(b)).not.toHaveAttribute('aria-current', 'page');
    await projectList.tab(b).click();
    await expect(projectList.tab(b)).toHaveAttribute('aria-current', 'page');
    await expect(projectList.tab(b)).toHaveAttribute('href', `/projects/${bId}`);
    await expect(projectList.tab(a)).not.toHaveAttribute('aria-current', 'page');
  });
});

test.describe('A finished project’s tab', () => {
  test.use({ timezoneId: 'Pacific/Kiritimati' });

  test('reads “Finished <date>” in the browser’s time zone, the full stamp its tooltip', async ({
    page,
    people,
    projects,
    projectList,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Finished');
    const id = await projects.make({ name, state: 'finished', members: [me.handle!] });
    const finishedAt = (await projects.list()).find((p) => p.id === id)!.finished_at!;
    await projectList.open(id);

    // UTC+14, so the stamp's hour differs from UTC's whenever it runs.
    const [day, stamp] = await page.evaluate((at) => {
      const timeZone = 'Pacific/Kiritimati';
      return [
        new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone }).format(new Date(at)),
        new Intl.DateTimeFormat('en-GB', { dateStyle: 'full', timeStyle: 'long', timeZone }).format(new Date(at)),
      ];
    }, finishedAt);
    const time = projectList.tab(name).locator('time');
    await expect(projectList.tab(name).getByTestId('projects.tab.status')).toHaveText(`Finished ${day}`);
    await expect(time).toHaveAttribute('title', stamp);
    await expect(time).toHaveAttribute('title', /GMT\+14/);
    await expect(time).toHaveAttribute('datetime', finishedAt);
  });
});

test.describe('The groups’ chevrons', () => {
  test('are remembered in the browser', async ({ page, people, projects, projectList }) => {
    const me = await people.signIn();
    const mine = await projects.make({ name: makeUnique('Mine'), members: [me.handle!] });
    await projectList.open(mine);
    const others = projectList.group('others');
    const finished = projectList.group('finished');

    await others.toggle.click();
    await page.reload();
    await expect(others.toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(finished.toggle).toHaveAttribute('aria-expanded', 'false');
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('pilot')!).chevrons)).toEqual({
      others: true,
      finished: false,
    });

    await others.toggle.click();
    await finished.toggle.click();
    await page.reload();
    await expect(others.toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(finished.toggle).toHaveAttribute('aria-expanded', 'true');
  });

  test('a group opens by itself while the project on screen is in it, and falls back when it leaves', async ({
    people,
    projects,
    projectList,
  }) => {
    const me = await people.signIn();
    const mine = makeUnique('Mine');
    await projects.make({ name: mine, members: [me.handle!] });
    const other = makeUnique('Other');
    const otherId = await projects.make({ name: other, members: ['ada'] });
    const others = projectList.group('others');
    await projectList.open(otherId);

    await expect(others.toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(projectList.tab(other, others.root)).toHaveAttribute('aria-current', 'page');

    await projectList.tab(mine).click();
    await expect(others.toggle).toHaveAttribute('aria-expanded', 'false');

    // Opened by the person, it stays open whatever is on screen.
    await others.toggle.click();
    await projectList.tab(other).click();
    await projectList.tab(mine).click();
    await expect(others.toggle).toHaveAttribute('aria-expanded', 'true');
  });

  test('closed while its project is on screen, a group stays closed until another project comes on screen', async ({
    page,
    people,
    projects,
    projectList,
  }) => {
    const me = await people.signIn();
    const mine = makeUnique('Mine');
    await projects.make({ name: mine, members: [me.handle!] });
    const other = makeUnique('Other');
    const otherId = await projects.make({ name: other, members: ['ada'] });
    const others = projectList.group('others');
    await projectList.open(otherId);

    await others.toggle.click();
    await expect(others.toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(others.root.getByTestId('projects.tab')).toHaveCount(0);

    await projectList.tab(mine).click();
    await expect(others.toggle).toHaveAttribute('aria-expanded', 'false');
    await page.goBack();
    await expect(page).toHaveURL(`/projects/${otherId}`);
    await expect(others.toggle).toHaveAttribute('aria-expanded', 'true');
  });
});

test.describe('A project’s address', () => {
  test('the bare address opens the project the browser remembers', async ({ page, people, projects, projectList, shell }) => {
    const me = await people.signIn();
    const firstId = await projects.make({ name: makeUnique('First'), members: [me.handle!] });
    const second = makeUnique('Second');
    const secondId = await projects.make({ name: second, members: [me.handle!] });

    // Nothing remembered yet: the list's first.
    await shell.open('/');
    await expect(page).toHaveURL(`/projects/${firstId}`);

    await projectList.tab(second).click();
    await expect(page).toHaveURL(`/projects/${secondId}`);
    await shell.open('/');
    await expect(page).toHaveURL(`/projects/${secondId}`);
    await expect(projectList.tab(second)).toHaveAttribute('aria-current', 'page');
  });

  test('the bare address opens the list’s first when the remembered project left the list', async ({
    page,
    people,
    projects,
    projectList,
    shell,
  }) => {
    const me = await people.signIn();
    const firstId = await projects.make({ name: makeUnique('First'), members: [me.handle!] });
    const leavingId = await projects.make({ name: makeUnique('Leaving'), members: [me.handle!] });
    await projectList.open(leavingId);
    await projects.transition(leavingId, 'archived');

    await shell.open('/');
    await expect(page).toHaveURL(`/projects/${firstId}`);
  });
});

test.describe('The archived projects', () => {
  test('open from the list’s menu, drawn as tabs, with a back arrow to the list', async ({
    page,
    people,
    projects,
    projectList,
  }) => {
    const me = await people.signIn();
    const mine = makeUnique('Mine');
    const mineId = await projects.make({ name: mine, members: [me.handle!] });
    const archived = makeUnique('Archived');
    const archivedId = await projects.make({ name: archived, archived: true, tasks: [step('a', 'in_progress')], members: [me.handle!] });
    await projectList.open(mineId);
    await expect(projectList.tab(archived)).toHaveCount(0);

    await projectList.menuButton.click();
    await expect(projectList.menu).toBeVisible();
    await projectList.archivedItem.click();

    await expect(projectList.menu).toBeHidden();
    await expect(projectList.archived).toContainText('Archived');
    await expect(projectList.tab(mine)).toHaveCount(0);
    await expect(projectList.tab('Photo album', projectList.archived)).toBeVisible();
    await expect(projectList.tab(archived, projectList.archived).getByTestId('projects.tab.status')).toHaveText('Step a');

    await projectList.tab(archived).click();
    await expect(page).toHaveURL(`/projects/${archivedId}`);
    await expect(projectList.tab(archived)).toHaveAttribute('aria-current', 'page');

    await projectList.archivedBack.click();
    await expect(projectList.archived).toBeHidden();
    await expect(projectList.head).toHaveText('Projects');
    await expect(projectList.tab(mine, projectList.mine)).toBeVisible();
  });
});

test.describe('The list on a narrow window', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('switching projects closes the drawer', async ({ page, people, projects, projectList, shell }) => {
    const me = await people.signIn();
    const aId = await projects.make({ name: makeUnique('A'), members: [me.handle!] });
    const b = makeUnique('B');
    const bId = await projects.make({ name: b, members: [me.handle!] });
    await projectList.open(aId);

    await shell.drawerToggle.click();
    await expect(shell.side).toBeVisible();
    await projectList.tab(b).click();

    await expect(page).toHaveURL(`/projects/${bId}`);
    await expect(shell.side).toBeHidden();
    await expect(shell.scrim).toBeHidden();

    // Back on the project it was opened on, the drawer stays closed.
    await page.goBack();
    await expect(page).toHaveURL(`/projects/${aId}`);
    await expect(shell.side).toBeHidden();
    await expect(shell.scrim).toBeHidden();
  });
});

test.describe('Refetching', () => {
  test('the list reads the record again when the window comes back into focus, the stream down', async ({
    page,
    backendUrl,
    auth,
    people,
    projects,
    projectList,
    deploymentSse,
    toastHelper,
  }) => {
    const me = await people.signIn();
    const mine = await projects.make({ name: makeUnique('Mine'), members: [me.handle!] });
    await projectList.open(mine);
    await deploymentSse.ensureConnected();

    // A new project raises `project_changed`, which an open stream would bring in. The stream goes
    // down and stays down: its next connect is refused, and the session check that would open it
    // again fails.
    const refusal = await page.request.post(`${backendUrl}/api/testing/sse/force-callback-error?status=403`);
    expect(refusal.status()).toBe(204);
    await auth.forceError(500);
    await page.evaluate(() => window.__sseForceReconnect!());
    await toastHelper.expectErrorToast(/refresh the page/i);
    expect((await deploymentSse.getStatus()).isConnected).toBe(false);

    const later = makeUnique('Later');
    await projects.make({ name: later, members: [me.handle!] });
    await expect(projectList.tab(later)).toHaveCount(0);

    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange', { bubbles: true })));
    await expect(projectList.tab(later, projectList.mine)).toBeVisible();
  });
});

test.describe('With no project', () => {
  test('the centre reads “No projects yet”', async ({ page, people, projects, projectList, shell }) => {
    await people.signIn();
    // The worker's database holds the seed's projects: archived for the test, brought back after.
    const listed = await projects.list();
    for (const project of listed) await projects.transition(project.id, 'archived');
    try {
      await shell.open('/');
      await expect(projectList.empty).toHaveText('No projects yet');
      await expect(shell.centre.getByTestId('projects.empty')).toBeVisible();
      await expect(projectList.tabs).toHaveCount(0);
      await expect(page).toHaveURL('/');
    } finally {
      for (const project of listed) await projects.transition(project.id, 'brought_back');
    }
  });
});
