/**
 * Stop and Resume on a work item (F67): Stop, on an item that runs, starts or is held, asks first in
 * the item's actions' place, Esc and Cancel dismissing the question (UC, *Keys*); Stop it ends the
 * session where it is, the item "Stopped · <time>" and waiting on you, Resume in Stop's place.
 * Resume, on a stopped item, a failed start or a turn ended in error, carries it on in the same
 * item through the gate, held while the project is paused, disabled while it is archived; a held
 * start stopped starts no more. A refusal shows as the API words it.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));

const TITLE = 'Surveying the stylesheets';
const QUESTION = 'Stop the session? Its turn ends where it is; Resume sends it on.';

interface Fixtures {
  people: People;
  projects: Projects;
}

/** A project, signed in as its member. */
async function setUp({ people, projects }: Fixtures, { paused = false } = {}) {
  const me = await people.signIn();
  const name = makeUnique('Stop');
  const project = await projects.make({ name, members: [me.handle!], paused });
  return { name, project };
}

/** A work item started in the project, once its session reads `state`. */
async function startIn(projects: Projects, project: string, state = 'running', title = TITLE): Promise<string> {
  const work = await projects.startWork(project, { title, brief: 'Survey the stylesheets.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe(state);
  return work;
}

/** Resolves once the relay has recorded the result that ends the item's stopped turn: Resume is refused until then. */
async function turnEnded(projects: Projects, work: string): Promise<void> {
  await expect.poll(async () => (await projects.records(work)).records.at(-1)?.kind).toBe('result');
}

test.describe('Stop', () => {
  test('asks first in the actions’ place, Cancel taking the focus; Esc and Cancel dismiss the question, and nothing stops', async ({
    people,
    projects,
    timeline,
    page,
  }) => {
    const { project } = await setUp({ people, projects });
    const work = await startIn(projects, project);
    await timeline.open(project);
    const item = timeline.item(work).work;
    await expect(item.stop).toHaveText('Stop');
    await expect(item.resume).toHaveCount(0);

    await item.stop.click();
    await expect(item.stopConfirm.text).toHaveText(QUESTION);
    await expect(item.stopConfirm.yes).toHaveText('Stop it');
    await expect(item.stopConfirm.cancel).toHaveText('Cancel');
    await expect(item.stopConfirm.cancel).toBeFocused();
    await expect(item.sessionLog).toHaveCount(0);
    await expect(item.stop).toHaveCount(0);

    await page.keyboard.press('Escape');
    await expect(item.stopConfirm.root).toHaveCount(0);
    await expect(item.stop).toBeFocused();
    await expect(item.sessionLog).toBeVisible();

    await item.stop.click();
    await item.stopConfirm.cancel.click();
    await expect(item.stopConfirm.root).toHaveCount(0);
    await expect(item.stop).toBeFocused();
    expect((await projects.work(project, work)).state).toBe('running');
  });

  test('confirmed, stops the item where it is, “Stopped · <time>” waiting on you; Resume carries it on in the same item', async ({
    people,
    projects,
    timeline,
    projectList,
    deploymentSse,
  }) => {
    const { name, project } = await setUp({ people, projects });
    const work = await startIn(projects, project);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;
    await expect(projectList.badge(name)).toHaveCount(0);

    await item.stop.click();
    await item.stopConfirm.yes.click();
    await expect(item.line).toHaveAttribute('data-state', 'stopped');
    const { stopped_at } = await projects.work(project, work);
    await expect(item.line).toHaveText(`Stopped · ${clock(stopped_at!)}`);
    await expect(item.stopConfirm.root).toHaveCount(0);
    await expect(item.stop).toHaveCount(0);
    await expect(item.resume).toHaveText('Resume');
    await expect(item.sessionLog).toBeVisible();
    await expect(projectList.badge(name)).toHaveText('1');

    await turnEnded(projects, work);
    await item.resume.click();
    await expect(item.resume).toHaveCount(0);
    await expect(item.stop).toBeVisible();
    await expect(item.cue).toBeVisible();
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
    await expect(item.running).toBeVisible();
    await expect(timeline.items).toHaveCount(1);
    await expect(projectList.badge(name)).toHaveCount(0);
  });

  test('ends a start under way, the item “Stopped · <time>”; Resume starts it again', async ({
    people,
    projects,
    controller,
    timeline,
    deploymentSse,
  }) => {
    const { project } = await setUp({ people, projects });
    // The environment the start creates is held `provisioning`.
    await controller.settleCreates(null);
    const work = await startIn(projects, project, 'starting');
    const environment = await projects.environment(project, work);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;
    await expect(item.cue).toHaveText(`Preparing ${environment.name}`);

    await item.stop.click();
    await item.stopConfirm.yes.click();
    await expect(item.line).toHaveAttribute('data-state', 'stopped');
    const { stopped_at } = await projects.work(project, work);
    await expect(item.line).toHaveText(`Stopped · ${clock(stopped_at!)}`);
    await expect(item.stop).toHaveCount(0);

    // With no conversation to continue, the Resume is a fresh start: its environment is reset,
    // which settles as the environment's starts do.
    await controller.setStatus(environment.id, 'running');
    await controller.settleStarts(environment.id, 'running');
    await item.resume.click();
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
    await expect(item.running).toBeVisible();
    await expect(timeline.items).toHaveCount(1);
  });

  test('ends a held start, which starts no more once the project resumes; its Resume is held while paused, its line why', async ({
    people,
    projects,
    timeline,
    deploymentSse,
  }) => {
    const { project } = await setUp({ people, projects }, { paused: true });
    const work = await startIn(projects, project, 'held');
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;
    await expect(item.cue).toHaveText('Paused');

    await item.stop.click();
    await item.stopConfirm.yes.click();
    await expect(item.line).toHaveAttribute('data-state', 'stopped');
    const { stopped_at } = await projects.work(project, work);
    await expect(item.line).toHaveText(`Stopped · ${clock(stopped_at!)}`);

    // The gate releases its held starts in the order they were asked: one asked later has run.
    await projects.transition(project, 'resumed');
    await startIn(projects, project, 'running', 'Renaming the badge');
    expect((await projects.work(project, work)).state).toBe('stopped');

    await projects.transition(project, 'paused');
    await item.resume.click();
    await expect(item.line).toHaveAttribute('data-state', 'held');
    await expect(item.cue).toHaveText('Paused');
    await expect(item.stop).toBeVisible();

    await projects.transition(project, 'resumed');
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
    await expect(item.running).toBeVisible();
  });
});

test.describe('Resume', () => {
  test('shows on a failed start and on a turn ended in error, and starts each again', async ({
    people,
    projects,
    controller,
    timeline,
    deploymentSse,
  }) => {
    const { project } = await setUp({ people, projects });
    // The node at its cap refuses the create: the start fails with no environment.
    await controller.capped();
    const refused = await startIn(projects, project, 'failed');
    await controller.capped(false);
    const erred = await startIn(projects, project, 'running', 'Renaming the badge');
    const other = await projects.environment(project, erred);
    await timeline.open(project);
    await deploymentSse.ensureConnected();

    const failed = timeline.item(refused).work;
    await expect(failed.line).toHaveText(/^Failed · /);
    await expect(failed.environment).toHaveCount(0);
    await expect(failed.stop).toHaveCount(0);
    await failed.resume.click();
    await expect(failed.resume).toHaveCount(0);
    await expect.poll(async () => (await projects.work(project, refused)).state).toBe('running');
    await expect(failed.running).toBeVisible();

    await controller.finish(other.id, 'claude-1', 'error', 'The model is overloaded.');
    const ended = timeline.item(erred).work;
    await expect(ended.line).toHaveText('Failed · The model is overloaded.');
    await ended.resume.click();
    await expect(ended.resume).toHaveCount(0);
    await expect.poll(async () => (await projects.work(project, erred)).state).toBe('running');
    await expect(ended.cue).toBeVisible();
  });

  test('refused while the stopped turn is still ending, shows the API’s words and stays offered', async ({
    people,
    projects,
    controller,
    timeline,
    page,
    deploymentSse,
  }) => {
    const { project } = await setUp({ people, projects });
    const work = await startIn(projects, project);
    const { id: environment } = await projects.environment(project, work);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;

    // The interrupt meets the unreachable worker, so the stopped turn runs on.
    await controller.unreachable(environment);
    await item.stop.click();
    await item.stopConfirm.yes.click();
    await expect(item.line).toHaveAttribute('data-state', 'stopped');

    await item.resume.click();
    await expect(
      page.getByTestId('app-shell.toast.item').filter({ hasText: `Cannot resume ${TITLE} because its stopped turn is still ending` }),
    ).toBeVisible();
    await expect(item.resume).toBeEnabled();
    await expect(item.line).toHaveAttribute('data-state', 'stopped');

    await controller.unreachable(environment, false);
    await controller.finish(environment, 'claude-1', 'interrupted');
    await turnEnded(projects, work);
    await item.resume.click();
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  });

  test('stands disabled on the item Archive stopped, as the head’s switch does, until Bring back', async ({
    people,
    projects,
    timeline,
    deploymentSse,
  }) => {
    const { project } = await setUp({ people, projects });
    const work = await startIn(projects, project);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;

    await projects.transition(project, 'archived');
    await expect(item.line).toHaveAttribute('data-state', 'stopped');
    await expect(item.resume).toHaveText('Resume');
    await expect(item.resume).toBeDisabled();

    await projects.transition(project, 'brought_back');
    await expect(item.resume).toBeEnabled();
  });
});
