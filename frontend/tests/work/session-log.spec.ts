/**
 * A work item's session log (F69): the overlay at its own address over its project's timeline,
 * its head "Session log" over the item's title, its environment's link once its start has one, and
 * its session's id; its
 * body the session's records as the chat renders a reply — a run of calls, a sub-agent's card,
 * the phantom fading in and gone at its record, each effect of a call as its line where the call
 * ran (F41) — streamed while it is open; its tail the working
 * cue while the session is held, starts or runs, else "Stopped by you · <time>", the environment
 * stopped under it or in error, "The turn ended · <time>" or "Failed · <time>" under the error
 * (F69.2, F125).
 * It follows the item through a Resume, sticks to its end until the reader scrolls up, and Esc
 * closes it.
 */

import { randomUUID } from 'node:crypto';
import { test, expect } from '../support/fixtures';
import { rawTurn } from '../support/controller';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';
import { sessionLogAddress } from '../support/page-objects/session-log-page';

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const clock = (at: string) => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: ZONE }).format(new Date(at));

const TITLE = 'Surveying the stylesheets';
const KUBECODER = 'https://kubecoder.example';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/). Each names its conversation,
// as every line `claude` prints does, so that a Resume continues it.
const CONVERSATION = '3f6c2a8e-5b1d-4c7e-9a2f-8d4b6e1c0a57';
const line = (value: object) => JSON.stringify({ ...value, session_id: CONVERSATION });
const text = (id: string, words: string) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] }, parent_tool_use_id: null });
const toolUse = (id: string, name: string, input: object) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'tool_use', id, name, input }] }, parent_tool_use_id: null });
const toolResult = (id: string, content: string) =>
  line({ type: 'user', message: { role: 'user', content: [{ tool_use_id: id, type: 'tool_result', content }] }, parent_tool_use_id: null });
const blockStart = () =>
  line({ type: 'stream_event', event: { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }, parent_tool_use_id: null });
const delta = (words: string) =>
  line({ type: 'stream_event', event: { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: words } }, parent_tool_use_id: null });

// Files the session writes in its environment, registered and attached as its worker does.
const SURVEY_PATH = '/work/Example/survey.md';
const SURVEY = '# The survey\n\nNine of ten want the lake.\n';
const NOTES_PATH = '/work/Example/camp-notes.txt';
const ROUTE_PATH = '/work/Example/route.txt';

interface Fixtures {
  people: People;
  projects: Projects;
}

/** A project, signed in as its member, and its work item's start. */
async function started({ people, projects }: Fixtures, { paused = false, state = 'running' } = {}) {
  const me = await people.signIn();
  const project = await projects.make({ name: makeUnique('Log'), members: [me.handle!], paused });
  return { project, start: () => startIn(projects, project, state) };
}

/** A work item started in the project, once its session runs, or as far as its start goes. */
async function startIn(projects: Projects, project: string, state: string): Promise<string> {
  const work = await projects.startWork(project, { title: TITLE, brief: 'Survey the stylesheets.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe(state);
  return work;
}


test.describe('A work item’s session log', () => {
  test('opened from a running item shows its head, then streams its records as the chat renders a reply — the cue, a run of calls, a sub-agent’s card, the phantom — to the turn’s end', async ({
    people,
    projects,
    controller,
    links,
    sessionLog,
  }) => {
    await links.set({ environment_link_base_url: KUBECODER });
    const { project, start } = await started({ people, projects });
    const work = await start();
    const { id: environment, name } = await projects.environment(project, work);
    await sessionLog.open(project, work);

    await expect(sessionLog.title).toHaveText('Session log');
    await expect(sessionLog.item).toHaveText(TITLE);
    await expect(sessionLog.environment).toHaveText(name);
    await expect(sessionLog.environment).toHaveAttribute('href', `${KUBECODER}/environments/${environment}/ssh/open`);
    await expect(sessionLog.session).toHaveText(work);
    // The server's lines while the session comes up show in the cue alone.
    await expect(sessionLog.cue).toHaveText('Creating the session');
    await expect(sessionLog.tail).toHaveCount(0);

    // Consecutive calls are one line, its running call's words while one runs.
    await controller.play(environment, 'claude-1', [
      toolUse('toolu_read', 'Read', { file_path: '/work/Example/README.md' }),
      toolResult('toolu_read', '# Example'),
      toolUse('toolu_ls', 'Bash', { command: 'ls', description: 'List the files' }),
    ]);
    await expect(sessionLog.runs).toHaveText('Running List the files · 2 steps');
    await expect(sessionLog.cue).toHaveText('Working');
    await controller.play(environment, 'claude-1', [toolResult('toolu_ls', 'README.md')]);
    await expect(sessionLog.runs).toHaveText('Read a file, ran a command · 2 steps');
    await expect(sessionLog.tools).toHaveCount(0);
    await sessionLog.runs.getByRole('button').click();
    await expect(sessionLog.tools).toHaveText(['Read …/Example/README.md', 'Ran List the files']);

    // A sub-agent is a card under its call, done once it reported.
    await controller.play(environment, 'claude-1', rawTurn('turn_subagent'));
    await expect(sessionLog.agents).toHaveText('Explore agent · Survey the stylesheets');
    await expect(sessionLog.agents.getByLabel('Done')).toBeVisible();
    await expect(sessionLog.texts.last()).toHaveText('There are two stylesheets.');

    // The phantom streams the block under way, and its record replaces it.
    await controller.play(environment, 'claude-1', [blockStart(), delta('The readme is ')]);
    await expect(sessionLog.phantom).toHaveText('The readme is');
    await expect(sessionLog.cue).toHaveText('Writing');
    await controller.play(environment, 'claude-1', [delta('a two-line stub.'), text('final', 'The readme is a two-line stub.')]);
    await expect(sessionLog.phantom).toHaveCount(0);
    await expect(sessionLog.texts.last()).toHaveText('The readme is a two-line stub.');

    await controller.finish(environment, 'claude-1');
    await expect.poll(async () => (await projects.item(project, work)).done?.cause).toBe('turn_ended');
    const { done } = await projects.item(project, work);
    await expect(sessionLog.tail).toHaveText(`The turn ended · ${clock(done!.at)}`);
    await expect(sessionLog.cue).toHaveCount(0);
  });

  test('shows each effect of its session’s calls as one line where the call ran — “Registered · inbox/<n>”, “Attached · <title>” — whether its record comes before the call’s line or after it, one whose call no record shows where its record stands, and a click goes to its item', async ({
    people,
    projects,
    controller,
    sessionLog,
    page,
  }) => {
    const { project, start } = await started({ people, projects });
    const work = await start();
    const { id: environment } = await projects.environment(project, work);
    await controller.putFile(environment, SURVEY_PATH, SURVEY);
    await controller.putFile(environment, NOTES_PATH, 'Bring the long pegs.\n');
    await controller.putFile(environment, ROUTE_PATH, 'North shore, then the ridge.\n');
    await sessionLog.open(project, work);

    // The call's line, then its effect: the line is the effect from then on.
    await controller.play(environment, 'claude-1', [
      text('survey', 'The survey is written.'),
      toolUse('toolu_register', 'mcp__pilot__register_document', { path: SURVEY_PATH }),
    ]);
    await expect(sessionLog.steps).toHaveCount(2);
    const survey = await projects.register(work, SURVEY_PATH, 'toolu_register');
    const registered = `Registered · inbox/${(await projects.item(project, survey)).seq}`;
    await expect(sessionLog.steps).toHaveText(['The survey is written.', registered]);
    await expect(sessionLog.tools).toHaveText([registered]);
    await controller.play(environment, 'claude-1', [toolResult('toolu_register', `{"id": "${survey}"}`)]);

    // The effect, then its call's line: it stands in its record's place until the line takes it.
    await controller.play(environment, 'claude-1', [text('notes', 'The notes go on the work item.')]);
    await expect(sessionLog.steps).toHaveCount(3);
    await projects.workerAttach(work, NOTES_PATH, { toolUseId: 'toolu_attach' });
    await expect(sessionLog.effects).toHaveText(['Attached · camp-notes.txt']);
    await controller.play(environment, 'claude-1', [
      toolUse('toolu_attach', 'mcp__pilot__attach_file', { path: NOTES_PATH }),
      toolResult('toolu_attach', '{"ids": []}'),
    ]);
    await expect(sessionLog.effects).toHaveCount(0);
    await expect(sessionLog.tools).toHaveText([registered, 'Attached · camp-notes.txt']);
    await expect(sessionLog.steps).toHaveText(['The survey is written.', registered, 'The notes go on the work item.', 'Attached · camp-notes.txt']);

    // A call whose client sent no tool-use id: its effect stands where its record does.
    await controller.play(environment, 'claude-1', [text('route', 'The route goes on the survey.')]);
    await expect(sessionLog.steps).toHaveCount(5);
    await projects.workerAttach(work, ROUTE_PATH, { to: survey });
    await expect(sessionLog.effects).toHaveText(['Attached · route.txt']);
    await expect(sessionLog.steps.last()).toHaveText('Attached · route.txt');

    await sessionLog.tools.getByRole('button', { name: registered }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project}/items/${survey}$`));
    await expect(sessionLog.overlay).toHaveCount(0);
  });

  test('opened from a done item shows its records as they streamed and "The turn ended · <time>"; Esc closes it', async ({
    page,
    people,
    projects,
    controller,
    sessionLog,
  }) => {
    const { project, start } = await started({ people, projects });
    const work = await start();
    const { id: environment } = await projects.environment(project, work);
    await controller.play(environment, 'claude-1', rawTurn('turn_tool'));
    await controller.finish(environment, 'claude-1');
    await expect.poll(async () => (await projects.item(project, work)).done?.cause).toBe('turn_ended');
    const { done } = await projects.item(project, work);

    await sessionLog.open(project, work);
    await expect(sessionLog.tools).toHaveText(['Read …/Example/README.md']);
    await expect(sessionLog.texts).toHaveText(['The readme is a two-line stub.']);
    await expect(sessionLog.phantom).toHaveCount(0);
    await expect(sessionLog.cue).toHaveCount(0);
    await expect(sessionLog.tail).toHaveText(`The turn ended · ${clock(done!.at)}`);

    await page.keyboard.press('Escape');
    await expect(sessionLog.overlay).toHaveCount(0);
    await expect(page).toHaveURL(`/projects/${project}`);
  });

  test('stopped by you reads "Stopped by you · <time>", and a Resume carries it on under the stopped turn', async ({
    people,
    projects,
    controller,
    sessionLog,
  }) => {
    const { project, start } = await started({ people, projects });
    const work = await start();
    const { id: environment } = await projects.environment(project, work);
    await sessionLog.open(project, work);
    await controller.play(environment, 'claude-1', [text('looking', 'Looking at the stylesheets.')]);
    await expect(sessionLog.texts).toHaveText(['Looking at the stylesheets.']);

    const stopped = await projects.stop(work);
    await expect(sessionLog.tail).toHaveText(`Stopped by you · ${clock(stopped.stopped_at!)}`);
    await expect(sessionLog.tail).toHaveAttribute('data-mark', 'stopped');
    await expect(sessionLog.cue).toHaveCount(0);

    // Resume is refused until the interrupt's result has ended the stopped turn.
    await expect.poll(async () => (await projects.records(work)).records.at(-1)?.kind).toBe('result');
    await projects.resume(work);
    await expect(sessionLog.tail).toHaveCount(0);
    await expect(sessionLog.cue).toBeVisible();
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
    await controller.play(environment, 'claude-1', [text('two', 'There are two stylesheets.')]);
    await expect(sessionLog.turns).toHaveCount(2);
    await expect(sessionLog.turnEnds).toHaveText([/^\d\d:\d\d · Stopped$/]);
    await expect(sessionLog.texts).toHaveText(['Looking at the stylesheets.', 'There are two stylesheets.']);

    await controller.finish(environment, 'claude-1');
    await expect(sessionLog.tail).toHaveText(/^The turn ended · \d\d:\d\d$/);
  });

  test('an environment stopped under the turn names the cause in its tail', async ({ people, projects, controller, sessionLog }) => {
    const { project, start } = await started({ people, projects });
    const work = await start();
    const { id: environment, name } = await projects.environment(project, work);
    await sessionLog.open(project, work);

    await controller.setStatus(environment, 'stopped');
    await expect.poll(async () => (await projects.work(project, work)).stopped_cause).toBe('environment_stopped');
    const stopped = await projects.work(project, work);
    await expect(sessionLog.tail).toHaveText(`${name} was stopped · ${clock(stopped.stopped_at!)}`);
    await expect(sessionLog.cue).toHaveCount(0);
  });

  test('an environment in error under the turn names it in its tail, and a Resume starts it again and carries the conversation on', async ({
    people,
    projects,
    controller,
    sessionLog,
  }) => {
    const { project, start } = await started({ people, projects });
    const work = await start();
    const { id: environment, name } = await projects.environment(project, work);
    await sessionLog.open(project, work);
    await controller.play(environment, 'claude-1', [text('looking', 'Looking at the stylesheets.')]);
    await expect(sessionLog.texts).toHaveText(['Looking at the stylesheets.']);

    await controller.setStatus(environment, 'error');
    await expect.poll(async () => (await projects.work(project, work)).stopped_cause).toBe('environment_error');
    const stopped = await projects.work(project, work);
    await expect(sessionLog.tail).toHaveText(`${name} is in error · ${clock(stopped.stopped_at!)}`);
    await expect(sessionLog.cue).toHaveCount(0);

    // Held `starting`, so that the Resume's line shows it starts the environment, where a fresh
    // start would reset it and read "Preparing".
    await controller.settleStarts(environment, null);
    await projects.resume(work);
    await expect(sessionLog.cue).toHaveText(`Starting ${name}`);
    await controller.setStatus(environment, 'running');
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
    expect((await projects.work(project, work)).environment).toEqual({ id: environment, name });
    await controller.play(environment, 'claude-2', [text('two', 'There are two stylesheets.')]);
    await expect(sessionLog.turns).toHaveCount(2);
    await expect(sessionLog.texts).toHaveText(['Looking at the stylesheets.', 'There are two stylesheets.']);
  });

  test('an environment restarting under the turn says so in the cue, and the turn carries on in a new session', async ({
    people,
    projects,
    controller,
    sessionLog,
  }) => {
    const { project, start } = await started({ people, projects });
    const work = await start();
    const { id: environment, name } = await projects.environment(project, work);
    await sessionLog.open(project, work);
    await controller.play(environment, 'claude-1', [text('looking', 'Looking at the stylesheets.')]);
    await expect(sessionLog.texts).toHaveText(['Looking at the stylesheets.']);

    await controller.restart(environment);
    await expect(sessionLog.cue).toHaveText(`${name} is restarting`);
    await controller.setStatus(environment, 'running');
    await expect.poll(async () => (await projects.work(project, work)).current_line?.state).toBe('thinking');
    await controller.play(environment, 'claude-2', [text('two', 'There are two stylesheets.')]);
    await expect(sessionLog.texts).toHaveText(['Looking at the stylesheets.', 'There are two stylesheets.']);
    await expect(sessionLog.turns).toHaveCount(2);
    await expect(sessionLog.turnEnds).toHaveText([/^\d\d:\d\d$/]);

    await controller.finish(environment, 'claude-2');
    await expect(sessionLog.tail).toHaveText(/^The turn ended · \d\d:\d\d$/);
  });

  test('a turn ended in error shows its reason in red over "Failed · <time>"', async ({ people, projects, controller, sessionLog }) => {
    const { project, start } = await started({ people, projects });
    const work = await start();
    const { id: environment } = await projects.environment(project, work);
    await sessionLog.open(project, work);

    await controller.finish(environment, 'claude-1', 'error', 'The model is overloaded.');
    await expect(sessionLog.failures).toHaveText(['The model is overloaded.']);
    const result = (await projects.records(work)).records.at(-1)!;
    expect(result.kind).toBe('result');
    await expect(sessionLog.tail).toHaveText(`Failed · ${clock(result.at)}`);
    await expect(sessionLog.tail).toHaveAttribute('data-mark', 'failed');
  });

  test('a failed start shows the start’s error over "Failed"', async ({ people, projects, controller, sessionLog }) => {
    const { project, start } = await started({ people, projects }, { state: 'failed' });
    // The node at its cap refuses the create: the start fails with no environment.
    await controller.capped();
    const work = await start();
    const { error } = await projects.work(project, work);

    await sessionLog.open(project, work);
    await expect(sessionLog.failures).toHaveText([error!]);
    await expect(sessionLog.tail).toHaveText(/^Failed · \d\d:\d\d$/);
    await expect(sessionLog.session).toHaveText(work);
    await expect(sessionLog.environment).toHaveCount(0);
  });

  test('a start the pause holds reads "Paused" in the cue, and names no environment before its take', async ({ people, projects, sessionLog }) => {
    const { project, start } = await started({ people, projects }, { paused: true, state: 'held' });
    const work = await start();

    await sessionLog.open(project, work);
    await expect(sessionLog.cue).toHaveText('Paused');
    await expect(sessionLog.tail).toHaveCount(0);
    await expect(sessionLog.session).toHaveText(work);
    await expect(sessionLog.environment).toHaveCount(0);
  });

  test('sticks to its end while it grows, lets go when the reader scrolls up, and sticks again once they scroll back down', async ({
    page,
    people,
    projects,
    controller,
    sessionLog,
  }) => {
    const { project, start } = await started({ people, projects });
    const work = await start();
    const { id: environment } = await projects.environment(project, work);
    await sessionLog.open(project, work);
    const long = (n: number) => Array.from({ length: 60 }, (_, i) => `Paragraph ${i + 1} of survey ${n}.`).join('\n\n');

    await controller.play(environment, 'claude-1', [text('one', long(1))]);
    await expect(sessionLog.texts).toHaveCount(1);
    await expect.poll(async () => (await sessionLog.scroll()).fromBottom).toBeLessThanOrEqual(1);

    await sessionLog.body.hover();
    const unstuck = sessionLog.sticky(false);
    await page.mouse.wheel(0, -600);
    await unstuck;
    await controller.play(environment, 'claude-1', [text('two', long(2))]);
    await expect(sessionLog.texts).toHaveCount(2);
    // Not pinned: the text grew under the view.
    await expect.poll(async () => (await sessionLog.scroll()).fromBottom).toBeGreaterThan(1000);

    const stuck = sessionLog.sticky(true);
    await page.mouse.wheel(0, 100_000);
    await stuck;
    await controller.play(environment, 'claude-1', [text('three', long(3))]);
    await expect(sessionLog.texts).toHaveCount(3);
    await expect.poll(async () => (await sessionLog.scroll()).fromBottom).toBeLessThanOrEqual(1);
  });

  test('an address that names no work item of the project reads "The session log did not load"', async ({
    page,
    people,
    projects,
    sessionLog,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Log'), members: [me.handle!] });

    await page.goto(sessionLogAddress(project, randomUUID()));
    await expect(sessionLog.failed).toHaveText('The session log did not load.');
  });
});
