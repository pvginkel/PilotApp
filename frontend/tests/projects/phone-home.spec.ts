/**
 * The phone's home (F98.5, F98.6, F1.6, F2.8, F128.2). On a phone the bare address is the home, the
 * page the phone opens on at launch: its head the top bar's block of colour, and the project list as
 * the side column has it, its groups closed until opened and no project marked as on screen; a row
 * the list's tab, the name and the ticket, the status icon, the running one pulsing, the step and
 * the badge. A row opens its project's Timeline over the home, never the tab it was left on; Back
 * from the Timeline shows the home, never the project before, so that one project leads to another
 * through it alone, and the head's arrow shows it from any tab, a new project's too. A reload keeps
 * where you were. A project's address reached cold lies over the home, the home's entry put under
 * it, and the profile page lies over it too. Archived opens from the list head's menu as a view of
 * its own pushed over the home and its head, an entry that a reload keeps, its arrow back, Esc and
 * Back taking it off. A dropped connection's tint lies over the home. Off a phone the bare address
 * still opens the project the browser remembers, and a window narrowed to a phone's width puts the
 * home under the project it shows.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { projectAddress } from '../support/projects';

const PHONE = { width: 390, height: 844 };
const step = (id: string, status: 'pending' | 'in_progress' | 'done') => ({ id, title: `Step ${id}`, status });

test.describe('The phone’s home', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('opens at launch: the list under the home’s head, its groups closed and no row on screen, a row its name and ticket, its status icon, the running one pulsing, its step and its badge', async ({
    page,
    people,
    projects,
    projectList,
    shell,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Home');
    const id = await projects.makeWithSession({ name, ticket: 'PL-7', tasks: [step('a', 'in_progress')], members: [me.handle!] });
    await projects.place(id, { kind: 'question', title: 'Which lake?', text: '```question id=Q1\n```\n' });
    const runningName = makeUnique('Running');
    const runningId = await projects.make({ name: runningName, tasks: [step('a', 'in_progress')], members: [me.handle!] });
    const work = await projects.startWork(runningId, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(runningId, work)).state).toBe('running');
    const otherName = makeUnique('Other');
    await projects.make({ name: otherName, members: ['ada'] });

    await shell.open('/');
    await expect(page).toHaveURL('/');
    await expect(shell.home).toBeVisible();
    await expect(shell.topBar).toHaveCount(0);
    await expect(shell.homeButton).toHaveCount(0);
    expect((await shell.homeList.boundingBox())!.y).toBeGreaterThanOrEqual((await shell.homeHead.boundingBox())!.height);
    await expect(projectList.head).toContainText('Projects');
    await expect(projectList.newProject).toBeVisible();

    const row = projectList.tab(name, shell.homeList);
    await expect(row.getByTestId('projects.tab.name')).toHaveText(name);
    await expect(row.getByTestId('projects.tab.ticket')).toHaveText('PL-7');
    await expect(row.getByTestId('projects.tab.step')).toHaveText('Step a');
    await expect(row.getByTestId('projects.tab.badge')).toHaveText('1');
    await expect(projectList.statusIcon(name).root).toBeVisible();
    const pulse = projectList.statusIcon(runningName).rest;
    await expect(pulse).toHaveAttribute('data-glyph', 'running');
    expect(await pulse.evaluate((element) => getComputedStyle(element).animationName)).toBe('live-pulse');
    await expect(shell.homeList.locator('[aria-current="page"]')).toHaveCount(0);

    // Each group closed until opened.
    const others = projectList.group('others');
    await expect(others.toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(projectList.tab(otherName)).toHaveCount(0);
    await others.toggle.tap();
    await expect(projectList.tab(otherName)).toBeVisible();

    await page.reload();
    await expect(page).toHaveURL('/');
    await expect(shell.home).toBeVisible();
  });

  test('a row opens its project’s Timeline over the home, never the tab it was left on; Back and the head’s arrow show the home, never the project before', async ({
    page,
    people,
    projects,
    projectList,
    projectHead,
    phoneTabs,
    shell,
  }) => {
    const me = await people.signIn();
    const a = makeUnique('A');
    const aId = await projects.makeWithSession({ name: a, members: [me.handle!] });
    const b = makeUnique('B');
    const bId = await projects.makeWithSession({ name: b, members: [me.handle!] });
    await shell.open('/');

    await projectList.tabName(a).tap();
    await expect(page).toHaveURL(projectAddress(aId));
    await expect(projectHead.name).toHaveText(a);
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(shell.home).toHaveCount(0);
    await phoneTabs.tab('chat').tap();
    await expect(phoneTabs.tab('chat')).toHaveAttribute('aria-selected', 'true');
    await page.reload();
    await expect(phoneTabs.tab('chat')).toHaveAttribute('aria-selected', 'true');

    await shell.homeButton.tap();
    await expect(page).toHaveURL('/');
    await expect(shell.home).toBeVisible();
    await projectList.tabName(b).tap();
    await expect(page).toHaveURL(projectAddress(bId));
    await page.goBack();
    await expect(page).toHaveURL('/');
    await expect(shell.home).toBeVisible();

    await projectList.tabName(a).tap();
    await expect(page).toHaveURL(projectAddress(aId));
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await shell.homeButton.tap();
    await expect(page).toHaveURL('/');
    await page.goForward();
    await expect(page).toHaveURL(projectAddress(aId));
    await page.goBack();
    await expect(page).toHaveURL('/');
  });

  test('a project’s address reached cold lies over the home, the home’s entry put under it, and so does the profile page, opened from the home’s avatar or reached cold', async ({
    page,
    people,
    projects,
    projectHead,
    profile,
    shell,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Cold');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });

    await page.goto(projectAddress(id));
    await expect(projectHead.name).toHaveText(name);
    await page.goBack();
    await expect(page).toHaveURL('/');
    await expect(shell.home).toBeVisible();
    await page.goForward();
    await expect(projectHead.name).toHaveText(name);

    await shell.open('/profile');
    await expect(profile.root).toBeVisible();
    await shell.homeButton.tap();
    await expect(page).toHaveURL('/');
    await expect(shell.home).toBeVisible();

    await shell.user.tap();
    await shell.profileItem.tap();
    await expect(page).toHaveURL('/profile');
    await page.goBack();
    await expect(page).toHaveURL('/');
    await expect(shell.home).toBeVisible();
  });

  test('the plus opens a new project over the home, its head’s arrow showing the home again', async ({ page, people, projectList, projectHead, shell }) => {
    await people.signIn();
    await shell.open('/');

    await projectList.newProject.tap();
    await expect(page).toHaveURL('/projects/draft-new');
    await expect(projectHead.name).toHaveText('New project');
    await expect(projectHead.root.getByTestId('shell.home-button')).toBeVisible();
    await shell.homeButton.tap();
    await expect(page).toHaveURL('/');
    await expect(shell.home).toBeVisible();
  });

  test('Archived opens from the list head’s menu as a view over the home and its head, a reload keeping it; its arrow, Esc and Back take it off, and its row opens the archived project over it', async ({
    page,
    people,
    projects,
    projectList,
    projectHead,
    shell,
  }) => {
    const me = await people.signIn();
    const mine = makeUnique('Mine');
    await projects.make({ name: mine, members: [me.handle!] });
    const archived = makeUnique('Archived');
    const archivedId = await projects.make({ name: archived, archived: true, members: [me.handle!] });
    await shell.open('/');
    await expect(projectList.tab(archived)).toHaveCount(0);

    await projectList.menuButton.tap();
    await projectList.archivedItem.tap();
    await expect(projectList.archived).toBeVisible();
    await expect(page).toHaveURL('/');
    await expect(shell.homeHead).toHaveCount(0);
    expect((await projectList.archived.boundingBox())!).toMatchObject({ x: 0, y: 0, width: PHONE.width });
    await expect(projectList.tab(archived, projectList.archived)).toBeVisible();
    await expect(projectList.tab(mine)).toHaveCount(0);
    await page.reload();
    await expect(projectList.tab(archived, projectList.archived)).toBeVisible();

    await projectList.archivedBack.tap();
    await expect(projectList.archived).toHaveCount(0);
    await expect(shell.homeHead).toBeVisible();
    await expect(projectList.tab(mine)).toBeVisible();
    await page.goForward();
    await expect(projectList.archived).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(projectList.archived).toHaveCount(0);
    await expect(shell.home).toBeVisible();
    await page.goForward();
    await expect(projectList.archived).toBeVisible();
    await page.goBack();
    await expect(projectList.archived).toHaveCount(0);
    await expect(shell.home).toBeVisible();

    await page.goForward();
    await projectList.tabName(archived).tap();
    await expect(page).toHaveURL(projectAddress(archivedId));
    await expect(projectHead.archived).toBeVisible();
    await shell.homeButton.tap();
    await expect(projectList.archived).toBeVisible();
  });

  test('a dropped connection’s tint lies over the home', async ({ page, people, shell, outage, deploymentSse }) => {
    await people.signIn();
    await shell.open('/');
    await deploymentSse.ensureConnected();
    await expect(shell.home).toBeVisible();

    await outage.drop();
    await expect(shell.connectionBadge).toBeVisible();
    expect(await shell.connection.boundingBox()).toMatchObject({ x: 0, y: 0, width: PHONE.width, height: PHONE.height });
    const head = (await shell.homeHead.boundingBox())!;
    expect(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.closest('[data-testid]')?.getAttribute('data-testid'), { x: head.x + 10, y: head.y + 10 })).toBe(
      'shell.connection',
    );
    await outage.end();
    await expect(shell.connection).toHaveCount(0, { timeout: 10_000 });
  });
});

test.describe('The bare address off a phone', () => {
  test('opens the project the browser remembers; narrowed to a phone’s width, the project lies over the home', async ({
    page,
    people,
    projects,
    projectList,
    projectHead,
    phoneTabs,
    shell,
  }) => {
    const me = await people.signIn();
    await projects.make({ name: makeUnique('A'), members: [me.handle!] });
    const bName = makeUnique('B');
    const bId = await projects.makeWithSession({ name: bName, members: [me.handle!] });
    await projectList.open(bId);
    // The browser writes the project it remembers as the project's page mounts, past the list's ready.
    await expect(projectHead.name).toHaveText(bName);
    await shell.open('/');
    await expect(page).toHaveURL(projectAddress(bId));
    await expect(shell.home).toHaveCount(0);

    await page.setViewportSize(PHONE);
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(page).toHaveURL(projectAddress(bId));
    await page.goBack();
    await expect(page).toHaveURL('/');
    await expect(shell.home).toBeVisible();
  });
});
