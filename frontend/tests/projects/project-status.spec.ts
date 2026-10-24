/**
 * A tab's status icon (F1.3, F141.1) and the pause (F141.2): the project's status as one icon in
 * the live dot's place, on no draft and no finished project, the running glyph pulsing as the dot
 * did; a click, a key or a tap on the phone pauses a project that is not paused and resumes one
 * paused or pausing, with no dialog and the icon changing at once, the pause glyph under the
 * pointer before a pause and the play glyph before a resume; a pause while work runs is pausing
 * until its turn ends; a work item started while paused is held until the resume; an archived
 * project's icon is its status alone.
 */

import { test, expect } from '../support/fixtures';
import type { Controller } from '../support/controller';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';

const step = (id: string, status: 'pending' | 'in_progress' | 'done') => ({ id, title: `Step ${id}`, status });
const QUESTION = '```question id=Q1\n```\n';

interface Fixtures {
  people: People;
  projects: Projects;
  controller: Controller;
}

/** A project, signed in as its member, with a work item running in an environment of the fake's. */
async function running({ people, projects, controller }: Fixtures) {
  const me = await people.signIn();
  const name = makeUnique('Running');
  const project = await projects.make({ name, members: [me.handle!], tasks: [step('a', 'in_progress')] });
  const environment = await controller.environment();
  const work = await projects.startWork(project, {
    environment_id: environment,
    title: 'Surveying the stylesheets',
    brief: 'Survey the stylesheets.',
    cwd: '/work/Example',
  });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  return { name, project, environment, work };
}

test.describe('A tab’s status icon', () => {
  test('is the project’s status, on no draft and no finished project', async ({ people, projects, projectList }) => {
    const me = await people.signIn();
    const member = { members: [me.handle!] };
    const idle = makeUnique('Idle');
    const idleId = await projects.make({ name: idle, tasks: [step('a', 'done'), step('b', 'pending')], ...member });
    const done = makeUnique('Done');
    await projects.make({ name: done, tasks: [step('a', 'done')], ...member });
    const paused = makeUnique('Paused');
    await projects.make({ name: paused, tasks: [step('a', 'pending')], paused: true, ...member });
    const waiting = makeUnique('Waiting');
    const waitingId = await projects.makeWithSession({ name: waiting, ...member });
    await projects.place(waitingId, { kind: 'question', title: 'Which lake?', text: QUESTION });
    const draft = makeUnique('Draft');
    await projects.make({ name: draft, state: 'draft', ...member });
    const finished = makeUnique('Finished');
    await projects.make({ name: finished, state: 'finished', ...member });
    await projectList.open(idleId);

    const listed = await projects.list();
    const statusOf = (name: string) => listed.find((tab) => tab.name === name)!.status;
    for (const [name, status, label] of [
      [idle, 'idle', 'Idle · Pause the project'],
      [done, 'done', 'Every step done · Pause the project'],
      [paused, 'paused', 'Paused · Resume the project'],
      [waiting, 'waiting_on_you', 'Waiting on you · Pause the project'],
    ] as const) {
      expect(statusOf(name)).toBe(status);
      const icon = projectList.statusIcon(name);
      await expect(icon.root).toHaveAttribute('data-status', status);
      await expect(icon.root).toHaveAttribute('role', 'button');
      await expect(icon.root).toHaveAttribute('aria-label', label);
      await expect(icon.rest).toHaveAttribute('data-glyph', status);
      await expect(icon.rest).toBeVisible();
      await expect(icon.hover).toBeHidden();
    }
    // The badge stands beside it.
    await expect(projectList.badge(waiting)).toHaveText('1');
    // The status line is the tab's text as before.
    await expect(projectList.tab(idle).getByTestId('projects.tab.status')).toHaveText('1 of 2 done');

    await expect(projectList.statusIcon(draft).root).toHaveCount(0);
    await projectList.group('finished').toggle.click();
    await expect(projectList.tab(finished)).toBeVisible();
    await expect(projectList.statusIcon(finished).root).toHaveCount(0);
    expect(statusOf(draft)).toBeNull();
    expect(statusOf(finished)).toBeNull();
  });

  test('a click pauses at once with no dialog, the pause glyph under the pointer, and a click resumes, the play glyph there; the tab is not opened', async ({
    page,
    people,
    projects,
    projectList,
  }) => {
    const me = await people.signIn();
    const shownId = await projects.make({ name: makeUnique('Shown'), members: [me.handle!] });
    const name = makeUnique('Pause');
    const id = await projects.make({ name, members: [me.handle!], tasks: [step('a', 'pending')] });
    await projectList.open(shownId);
    const icon = projectList.statusIcon(name);
    await expect(icon.root).toHaveAttribute('data-status', 'idle');

    await icon.root.hover();
    await expect(icon.hover).toBeVisible();
    await expect(icon.hover).toHaveAttribute('data-glyph', 'pause');
    await expect(icon.rest).toBeHidden();

    const paused = projectList.written(id, 'paused');
    await icon.root.click();
    await expect(icon.hover).toHaveAttribute('data-glyph', 'play');
    await expect(icon.rest).toHaveAttribute('data-glyph', 'paused');
    await paused;

    await expect(icon.root).toHaveAttribute('data-status', 'paused');
    await expect(icon.root).toHaveAttribute('aria-busy', 'false');
    await expect(icon.hover).toHaveAttribute('data-glyph', 'play');
    await expect(page).toHaveURL(`/projects/${shownId}`);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect((await projects.head(id)).status).toBe('paused');

    const resumed = projectList.written(id, 'resumed');
    await icon.root.click();
    await resumed;
    await expect(icon.root).toHaveAttribute('data-status', 'idle');
    await expect(icon.hover).toHaveAttribute('data-glyph', 'pause');
    await expect(page).toHaveURL(`/projects/${shownId}`);
    expect((await projects.head(id)).status).toBe('idle');

    // Away from the pointer, the status's own glyph.
    await page.mouse.move(0, 0);
    await expect(icon.rest).toBeVisible();
    await expect(icon.rest).toHaveAttribute('data-glyph', 'idle');
    await expect(icon.hover).toBeHidden();
  });

  test('Enter pauses and Space resumes, the tab not opened', async ({ page, people, projects, projectList }) => {
    const me = await people.signIn();
    const shownId = await projects.make({ name: makeUnique('Shown'), members: [me.handle!] });
    const name = makeUnique('Keys');
    const id = await projects.make({ name, members: [me.handle!] });
    await projectList.open(shownId);
    const icon = projectList.statusIcon(name);

    await icon.root.focus();
    const paused = projectList.written(id, 'paused');
    await page.keyboard.press('Enter');
    await paused;
    await expect(icon.root).toHaveAttribute('data-status', 'paused');

    const resumed = projectList.written(id, 'resumed');
    await page.keyboard.press(' ');
    await resumed;
    await expect(icon.root).toHaveAttribute('data-status', 'idle');
    await expect(page).toHaveURL(`/projects/${shownId}`);
  });

  test('running, the glyph pulses; a pause is pausing until the turn ends, then paused; a resume while pausing cancels it', async ({
    page,
    people,
    projects,
    controller,
    projectList,
  }) => {
    const { name, project, environment } = await running({ people, projects, controller });
    await projectList.open(project);
    const icon = projectList.statusIcon(name);
    await expect(icon.root).toHaveAttribute('data-status', 'running');
    await expect(icon.rest).toHaveAttribute('data-glyph', 'running');
    expect(await icon.rest.evaluate((element) => getComputedStyle(element).animationName)).toBe('pulse');

    const paused = projectList.written(project, 'paused');
    await icon.root.click();
    await paused;
    await expect(icon.root).toHaveAttribute('data-status', 'pausing');
    await expect(icon.root).toHaveAttribute('aria-label', 'Pausing · Resume the project');

    const resumed = projectList.written(project, 'resumed');
    await icon.root.click();
    await resumed;
    await expect(icon.root).toHaveAttribute('data-status', 'running');

    const pausedAgain = projectList.written(project, 'paused');
    await icon.root.click();
    await pausedAgain;
    await expect(icon.root).toHaveAttribute('data-status', 'pausing');
    // The turn runs to its end; the tab follows without a read of its own.
    await page.mouse.move(0, 0);
    await controller.finish(environment, 'claude-1');
    await expect(icon.root).toHaveAttribute('data-status', 'paused');
    await expect(icon.rest).toHaveAttribute('data-glyph', 'paused');
  });

  test('a work item started while paused is held, its line saying so, and runs once the icon resumes the project', async ({
    people,
    projects,
    controller,
    projectList,
    timeline,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Held');
    const project = await projects.make({ name, members: [me.handle!] });
    const environment = await controller.environment();
    await timeline.open(project);
    const icon = projectList.statusIcon(name);
    const paused = projectList.written(project, 'paused');
    await icon.root.click();
    await paused;

    const work = await projects.startWork(project, {
      environment_id: environment,
      title: 'Surveying the stylesheets',
      brief: 'Survey the stylesheets.',
      cwd: '/work/Example',
    });
    const item = timeline.item(work).work;
    await expect(item.line).toHaveAttribute('data-state', 'held');
    await expect(item.cue).toHaveText('Paused');

    const resumed = projectList.written(project, 'resumed');
    await icon.root.click();
    await resumed;
    await expect(item.line).toHaveAttribute('data-state', 'running');
    await expect(icon.root).toHaveAttribute('data-status', 'running');
  });

  test('on an archived project is its status alone, not the pause', async ({ people, projects, projectList }) => {
    const me = await people.signIn();
    const name = makeUnique('Archived');
    await projects.make({ name, members: [me.handle!], archived: true, paused: true });
    const shownId = await projects.make({ name: makeUnique('Shown'), members: [me.handle!] });
    await projectList.open(shownId);
    await projectList.menuButton.click();
    await projectList.archivedItem.click();

    const icon = projectList.statusIcon(name, projectList.archived);
    await expect(icon.root).toHaveAttribute('data-status', 'paused');
    await expect(icon.root).toHaveAttribute('role', 'img');
    await expect(icon.root).toHaveAttribute('aria-label', 'Paused');
    await expect(icon.hover).toHaveCount(0);
  });
});

test.describe('A tab’s status icon on the phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('a tap pauses and a tap resumes, the drawer staying open on the project shown', async ({ page, people, projects, projectList, shell }) => {
    const me = await people.signIn();
    const shownId = await projects.make({ name: makeUnique('Shown'), members: [me.handle!] });
    const name = makeUnique('Tap');
    const id = await projects.make({ name, members: [me.handle!] });
    await projectList.open(shownId);
    await shell.drawerToggle.tap();
    await expect(shell.side).toBeVisible();
    const icon = projectList.statusIcon(name);

    const paused = projectList.written(id, 'paused');
    await icon.root.tap();
    await paused;
    await expect(icon.root).toHaveAttribute('data-status', 'paused');
    await expect(shell.side).toBeVisible();
    await expect(page).toHaveURL(`/projects/${shownId}`);

    const resumed = projectList.written(id, 'resumed');
    await icon.root.tap();
    await resumed;
    await expect(icon.root).toHaveAttribute('data-status', 'idle');
  });
});
