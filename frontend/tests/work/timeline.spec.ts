/**
 * A work item on the timeline (F26): open, its head with the env chip opening the environment once
 * its start has one and the running time, "17m", while its turn runs (F26.1, F12), and its one line
 * (F26.2), live as the server moves it (F80.2) — the server's own words while the session comes up
 * or its environment restarts, the working state and the latest step — a call whose input streams
 * in by its verb alone — why the gate holds its start (F141.5), a slot among it (F143.4),
 * "Stopped · <time>" with the cause of a stop made elsewhere (F71), a failure's error (F125) — and
 * its Session log (F26.3). Done, it is a quieter line, its Open the session log, with
 * no Undo and its attachments' indicator (F13.5, F26.6, F13.6), and so is every work item of a
 * finished project (F5.3). A run of work items stands under its last member's dividers (F9.1).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import { slugOf, type Projects } from '../support/projects';
import { sessionLogAddress } from '../support/page-objects/session-log-page';

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));

const TITLE = 'Surveying the stylesheets';
const KUBECODER = 'https://kubecoder.example';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/).
const line = (value: object) => JSON.stringify(value);
const toolUse = (id: string, name: string, input: object) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'tool_use', id, name, input }] }, parent_tool_use_id: null });
const toolResult = (id: string, content: string) =>
  line({ type: 'user', message: { role: 'user', content: [{ tool_use_id: id, type: 'tool_result', content }] }, parent_tool_use_id: null });
const blockStart = () =>
  line({ type: 'stream_event', event: { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }, parent_tool_use_id: null });
const toolStart = (id: string, name: string) =>
  line({ type: 'stream_event', event: { type: 'content_block_start', index: 0, content_block: { type: 'tool_use', id, name, input: {} } }, parent_tool_use_id: null });

interface Fixtures {
  people: People;
  projects: Projects;
}

/** A project, signed in as its member. */
async function setUp({ people, projects }: Fixtures, { paused = false } = {}) {
  const me = await people.signIn();
  return projects.make({ name: makeUnique('Work'), members: [me.handle!], paused });
}

/** A work item started in the project, once its session reads `state`. */
async function startIn(projects: Projects, project: string, state = 'running', title = TITLE): Promise<string> {
  const work = await projects.startWork(project, { title, brief: 'Survey the stylesheets.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe(state);
  return work;
}

test.describe('An open work item', () => {
  test('comes up with the server’s words, then runs under its env chip and its running time, “0m”, its line the working state and the latest step, live', async ({
    people,
    projects,
    controller,
    links,
    timeline,
    sessionLog,
    page,
    deploymentSse,
  }) => {
    await links.set({ environment_link_base_url: KUBECODER });
    const project = await setUp({ people, projects });
    // The environment the start creates is held `provisioning`.
    await controller.settleCreates(null);
    await timeline.open(project);
    await deploymentSse.ensureConnected();

    const work = await projects.startWork(project, { title: TITLE, brief: 'Survey.', cwd: '/work/Example' });
    const item = timeline.item(work);
    await expect(item.kind).toHaveText('Work');
    await expect(item.title).toHaveText(TITLE);
    const { id: environment, name } = await projects.environment(project, work);
    expect(name).toBe(slugOf(project));
    await expect(item.work.environment).toHaveText(name);
    await expect(item.work.environment).toHaveAttribute('href', `${KUBECODER}/environments/${environment}/ssh/open`);
    await expect(item.work.cue).toHaveText(`Preparing ${name}`);
    await expect(item.work.running).toHaveCount(0);

    await controller.setStatus(environment, 'running');
    await expect(item.work.running).toHaveText('0m');
    await expect(item.work.running).toHaveAccessibleName('Running for 0m');
    await expect(item.work.running).toHaveAttribute('title', 'Running for 0m');
    await expect(item.work.running.locator('.pulse')).toBeVisible();
    await expect(item.work.cue).toHaveText('Creating the session');
    await expect(item.work.step).toHaveCount(0);

    await controller.play(environment, 'claude-1', [toolUse('toolu_read', 'Read', { file_path: '/work/Example/README.md' })]);
    await expect(item.work.cue).toHaveText('Working');
    await expect(item.work.step).toHaveText('Reading …/Example/README.md');
    await controller.play(environment, 'claude-1', [toolResult('toolu_read', '# Example')]);
    await expect(item.work.cue).toHaveText('Thinking');
    await expect(item.work.step).toHaveText('Read …/Example/README.md');
    await controller.play(environment, 'claude-1', [blockStart()]);
    await expect(item.work.cue).toHaveText('Writing');
    await controller.play(environment, 'claude-1', [
      toolUse('toolu_agent', 'Task', { subagent_type: 'Explore', description: 'Survey the stylesheets', prompt: 'Find them.' }),
    ]);
    await expect(item.work.cue).toHaveText('Waiting for the Explore agent');
    await expect(item.work.step).toHaveText('Survey the stylesheets');

    await item.work.sessionLog.click();
    await expect(page).toHaveURL(sessionLogAddress(project, work));
    await expect(sessionLog.item).toHaveText(TITLE);
  });

  test('names the call whose input streams in by its running verb alone, never the finished call before it, and its target once its line arrives', async ({
    people,
    projects,
    controller,
    timeline,
  }) => {
    const project = await setUp({ people, projects });
    const work = await startIn(projects, project);
    const { id: environment } = await projects.environment(project, work);
    await timeline.open(project);
    const item = timeline.item(work).work;

    await controller.play(environment, 'claude-1', [
      toolUse('toolu_read', 'Read', { file_path: '/work/Example/README.md' }),
      toolResult('toolu_read', '# Example'),
    ]);
    await expect(item.step).toHaveText('Read …/Example/README.md');
    await controller.play(environment, 'claude-1', [toolStart('toolu_edit', 'Edit')]);
    await expect(item.cue).toHaveText('Working');
    await expect(item.step).toHaveText('Editing');
    await controller.play(environment, 'claude-1', [
      toolUse('toolu_edit', 'Edit', { file_path: '/work/Example/README.md', old_string: 'Example', new_string: 'Sample' }),
    ]);
    await expect(item.step).toHaveText('Editing …/Example/README.md');

    // No search pattern is drawn before the call's line gives one.
    await controller.play(environment, 'claude-1', [toolResult('toolu_edit', 'Edited.'), toolStart('toolu_grep', 'Grep')]);
    await expect(item.step).toHaveText('Searching for');
    await controller.play(environment, 'claude-1', [toolUse('toolu_grep', 'Grep', { pattern: 'badge' })]);
    await expect(item.step).toHaveText('Searching for “badge”');
  });

  test('held by the pause reads “Paused” with no env chip before its take, and comes up once the project resumes', async ({
    people,
    projects,
    timeline,
  }) => {
    const project = await setUp({ people, projects }, { paused: true });
    const work = await startIn(projects, project, 'held');
    await timeline.open(project);

    const item = timeline.item(work);
    await expect(item.work.line).toHaveAttribute('data-state', 'held');
    await expect(item.work.cue).toHaveText('Paused');
    await expect(item.work.running).toHaveCount(0);
    await expect(item.work.environment).toHaveCount(0);

    await projects.transition(project, 'resumed');
    await expect(item.work.running).toHaveText('0m');
    await expect(item.work.cue).toHaveText('Creating the session');
    await expect(item.work.environment).toHaveText((await projects.environment(project, work)).name);
  });

  test('held while the controller is unreachable reads “Waiting for the controller”', async ({ people, projects, controller, timeline }) => {
    const project = await setUp({ people, projects });
    await controller.outage(true, 'ingress');
    const work = await startIn(projects, project, 'held');
    await timeline.open(project);

    await expect(timeline.item(work).work.cue).toHaveText('Waiting for the controller');
    await controller.outage(false);
    await expect(timeline.item(work).work.running).toBeVisible();
  });

  test('held for a slot reads “Waiting for a slot · N running”, in its session log too, and comes up once a work item ends', async ({
    people,
    projects,
    controller,
    timeline,
    sessionLog,
    page,
  }) => {
    const project = await setUp({ people, projects });
    // The worker's backends hold a project's fourth work item while three run.
    const running: string[] = [];
    for (const title of ['Surveying the badges', 'Surveying the icons', 'Surveying the fonts']) running.push(await startIn(projects, project, 'running', title));
    const work = await startIn(projects, project, 'held');
    await timeline.open(project);

    const item = timeline.item(work).work;
    await expect(item.line).toHaveAttribute('data-state', 'held');
    await expect(item.cue).toHaveText('Waiting for a slot · 3 running');
    await expect(item.environment).toHaveCount(0);
    await item.sessionLog.click();
    await expect(sessionLog.cue).toHaveText('Waiting for a slot · 3 running');
    await page.keyboard.press('Escape');
    await expect(sessionLog.overlay).toHaveCount(0);

    const { id: environment } = await projects.environment(project, running[0]!);
    await controller.finish(environment, 'claude-1');
    await expect(item.running).toBeVisible();
    await expect(item.environment).toBeVisible();
  });

  test('stopped reads “Stopped · <time>”, and a stop made elsewhere names its cause, an environment in error among them', async ({
    people,
    projects,
    controller,
    timeline,
  }) => {
    const project = await setUp({ people, projects });
    const mine = await startIn(projects, project);
    const theirs = await startIn(projects, project, 'running', 'Renaming the badge');
    const other = await projects.environment(project, theirs);
    const erred = await startIn(projects, project, 'running', 'Renaming the icon');
    const broken = await projects.environment(project, erred);
    await timeline.open(project);
    await expect(timeline.item(mine).work.running).toBeVisible();

    const stopped = await projects.stop(mine);
    await expect(timeline.item(mine).work.line).toHaveText(`Stopped · ${clock(stopped.stopped_at!)}`);
    await expect(timeline.item(mine).work.line).toHaveAttribute('data-state', 'stopped');
    await expect(timeline.item(mine).work.running).toHaveCount(0);
    await expect(timeline.item(mine).root).toHaveAttribute('data-state', 'open');

    await controller.setStatus(other.id, 'stopped');
    await expect.poll(async () => (await projects.work(project, theirs)).stopped_cause).toBe('environment_stopped');
    const { stopped_at } = await projects.work(project, theirs);
    await expect(timeline.item(theirs).work.line).toHaveText(`Stopped · ${clock(stopped_at!)} · ${other.name} was stopped`);

    await controller.setStatus(broken.id, 'error');
    await expect.poll(async () => (await projects.work(project, erred)).stopped_cause).toBe('environment_error');
    const halted = await projects.work(project, erred);
    await expect(timeline.item(erred).work.line).toHaveText(`Stopped · ${clock(halted.stopped_at!)} · ${broken.name} is in error`);
    await expect(timeline.item(erred).work.resume).toBeVisible();
  });

  test('reads its environment restarting under the turn, and moves on once it is back', async ({ people, projects, controller, timeline }) => {
    const project = await setUp({ people, projects });
    const work = await startIn(projects, project);
    const environment = await projects.environment(project, work);
    await timeline.open(project);

    await controller.restart(environment.id);
    await expect(timeline.item(work).work.cue).toHaveText(`${environment.name} is restarting`);
    await controller.setStatus(environment.id, 'running');
    await expect(timeline.item(work).work.cue).toHaveText('Thinking');
  });

  test('a failed start and a turn ended in error read “Failed” with the error, shown as a stopped one is', async ({
    people,
    projects,
    controller,
    timeline,
  }) => {
    const project = await setUp({ people, projects });
    // The node at its cap refuses the create: the start fails with no environment.
    await controller.capped();
    const refused = await startIn(projects, project, 'failed');
    await controller.capped(false);
    const erred = await startIn(projects, project, 'running', 'Renaming the badge');
    const other = await projects.environment(project, erred);
    await timeline.open(project);

    const { error } = await projects.work(project, refused);
    await expect(timeline.item(refused).work.line).toHaveText(`Failed · ${error!}`);
    await expect(timeline.item(refused).work.line).toHaveClass(/\bended\b/);
    await expect(timeline.item(refused).work.environment).toHaveCount(0);

    await controller.finish(other.id, 'claude-1', 'error', 'The model is overloaded.');
    await expect(timeline.item(erred).work.line).toHaveText('Failed · The model is overloaded.');
    await expect(timeline.item(erred).root).toHaveAttribute('data-state', 'open');
  });
});

test.describe('A done work item', () => {
  test('is a quieter line: the time its turn ended, its attachments’ indicator, Open the session log, and no Undo', async ({
    people,
    projects,
    controller,
    timeline,
    sessionLog,
    page,
  }) => {
    const project = await setUp({ people, projects });
    const work = await startIn(projects, project);
    const { id: environment } = await projects.environment(project, work);
    const [attachment] = await projects.attach(work, [
      { title: 'The survey', filename: 'survey.md', content_type: 'text/markdown', content: '# The survey\n' },
    ]);
    await controller.finish(environment, 'claude-1');
    await expect.poll(async () => (await projects.item(project, work)).done?.cause).toBe('turn_ended');
    const { done } = await projects.item(project, work);
    await timeline.open(project);

    const item = timeline.item(work);
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.root).toHaveClass(/\bquiet\b/);
    await expect(item.lineTitle).toHaveText(TITLE);
    await expect(item.lineTime).toHaveText(clock(done!.at));
    await expect(item.lineAttachment).toHaveAttribute('data-attachment-id', attachment);
    await expect(item.undo).toHaveCount(0);
    await expect(item.open).toHaveAttribute('href', sessionLogAddress(project, work));

    await item.open.click();
    await expect(page).toHaveURL(sessionLogAddress(project, work));
    await expect(sessionLog.tail).toHaveText(`The turn ended · ${clock(done!.at)}`);
  });

  test('is every work item of a finished project, a running one stopped and closed by Finish', async ({ people, projects, timeline }) => {
    const project = await setUp({ people, projects });
    const work = await startIn(projects, project);
    await projects.transition(project, 'finished');
    await timeline.open(project);

    await expect(timeline.item(work).root).toHaveAttribute('data-state', 'done');
    await expect(timeline.item(work).root).toHaveClass(/\bquiet\b/);
    await expect(timeline.item(work).work.line).toHaveCount(0);
    await expect(timeline.finishedEnd).toBeVisible();
  });
});

test.describe('A run of work items', () => {
  test('stands under its last member’s step divider, placed before the run, with none between its members', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({
      name: makeUnique('Run'),
      members: [me.handle!],
      tasks: [
        { id: 'build', title: 'Build the card', status: 'in_progress' },
        { id: 'ship', title: 'Ship it', status: 'pending' },
      ],
    });
    await projects.place(project, { kind: 'notice', title: 'Built one', text: '---\nstep: build\n---\n\nOne.\n' });
    const brief = { brief: 'Survey.', cwd: '/work/Example' };
    const building = await projects.startWork(project, { title: 'Building', step: 'build', ...brief });
    const shipping = await projects.startWork(project, { title: 'Shipping', step: 'ship', ...brief });
    // The route places the item by the session started last; placed while that session's start still
    // writes, its insert can deadlock against the start (close-out B11).
    for (const work of [building, shipping]) await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
    await projects.place(project, { kind: 'notice', title: 'Shipped', text: '---\nstep: ship\n---\n\nTwo.\n' });
    await timeline.open(project);

    const rows = (await timeline.rowsRead()).filter(([kind]) => kind !== 'timeline.divider.day' && kind !== 'timeline.opening');
    expect(rows).toEqual([
      ['timeline.divider.step', 'Build the card'],
      ['timeline.item', expect.stringContaining('Built one')],
      ['timeline.divider.step', 'Ship it'],
      ['timeline.item', expect.stringContaining('Building')],
      ['timeline.item', expect.stringContaining('Shipping')],
      ['timeline.item', expect.stringContaining('Shipped')],
    ]);
  });
});
