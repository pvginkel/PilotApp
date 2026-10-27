/**
 * A document a work item's session registers (F85.1, F65): on the timeline from its registration,
 * a review titled by its file's name, with no text and no close until the turn that ends its run
 * has read it (review 7), its card muted meanwhile, "Loads when the turn ends" under its name and
 * Pilot's dots ending it, then published as written, its title its text's, live. A read that
 * fails keeps its file's name and no text, *Did not load* beside it: it opens to "The document did
 * not load", closes with Reviewed, and its work item's session log says why (ruling D1). Its close
 * is written back to its file, and the close that leaves none of the run's documents open
 * continues the conversation as a new work item after the answered ones, from when Undo is gone
 * from every document of the run (review 1); a write-back the controller refuses is in the run's
 * session log, live, and fails that continuation's start with its reason (F125). One whose writer
 * Pilot asked about its blocks says so on the timeline, live (F86.8).
 */

import { test, expect } from '../support/fixtures';
import type { Controller } from '../support/controller';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';
import { documentAddress } from '../support/page-objects/overlay-page';

const TITLE = 'Surveying the camp';

// An invented line in `claude`'s shape (backend/tests/fixtures/raw/), naming its conversation, as
// every line `claude` prints does, so that the continuation carries it on.
const CONVERSATION = '7d2e4b91-3c5a-4f8e-b6d0-1a9c8e5f2b43';
const text = (id: string, words: string) =>
  JSON.stringify({
    type: 'assistant',
    message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] },
    parent_tool_use_id: null,
    session_id: CONVERSATION,
  });

const SURVEY_PATH = '/work/Example/survey.md';
const SURVEY = '# The survey\n\nNine of ten want the lake.\n';
// What a process in the environment writes over the survey's file after its read: only a write-back
// makes the file read SURVEY again.
const SURVEY_EDITED = '# The survey\n\nEdited after its read.\n';
const PITCH_PATH = '/work/Example/pitch.md';
const PITCH = '# Where do we pitch?\n\nThe lake or the hill.\n\n```question id=Q1\n```\n';
/** A decision block of the DSL, its options as given. */
const decision = (id: string, ...options: string[]) =>
  ['```decision id=' + id, 'options:', ...options.map((option) => `  - ${option}`), '```', ''].join('\n');
const KIT_PATH = '/work/Example/kit.md';
const KIT = `# The kit\n\n${decision('D1', 'Dome', 'Tunnel')}\n${decision('D2', 'Gas', 'Wood')}\n${decision('D3', 'Two', 'Four')}\n${decision('D4', 'Rope', 'Chain')}`;
// Over 150 words of its own, so that it leaves a card.
const ROUTE_PATH = '/work/Example/route.md';
const PUSH_PATH = '/work/Example/push.md';
const PUSH = '# Push the camp list?\n\n```decision id=C1\ntype: confirmation\nproposal: Push the camp list\nbecause: auto-pilot-off\n```\n';
const ROUTE = `# The route\n\n${'We walk the north shore to the ridge and camp below it. '.repeat(16)}\n\n${decision('D1', 'Shore', 'Ridge')}\n${decision('D2', 'Day', 'Night')}`;

interface Fixtures {
  people: People;
  projects: Projects;
}

/** A work item running in the environment its start created, in a project of the signed-in person's. */
async function running({ people, projects }: Fixtures) {
  const me = await people.signIn();
  const project = await projects.make({ name: makeUnique('Registered'), members: [me.handle!] });
  const work = await projects.startWork(project, { title: TITLE, brief: 'Survey the camp.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  const { id: environment } = await projects.environment(project, work);
  return { project, work, environment };
}

/** The session writes a file in its environment and registers it; answers the document's id. */
async function registered(controller: Controller, projects: Projects, environment: string, work: string, path: string, content: string) {
  await controller.putFile(environment, path, content);
  return projects.register(work, path);
}

/** The work item's turn ends, and its run with it. */
async function endRun(controller: Controller, environment: string) {
  await controller.play(environment, 'claude-1', [text('wrote', 'The survey is written and registered.')]);
  await controller.finish(environment, 'claude-1');
}

/** A `server` record the server writes of a registered document's file: the document, its path and the reason. */
interface FileEvent {
  type: 'read-failed' | 'write-back-refused';
  item: string;
  path: string;
  reason: string;
}

/** The session's one `server` record of the type. */
async function fileEvent(projects: Projects, sessionId: string, type: FileEvent['type']): Promise<FileEvent> {
  const { records } = await projects.records(sessionId);
  const found = records
    .flatMap((record) => (record.kind === 'server' ? [record.payload as FileEvent] : []))
    .filter((event) => event.type === type);
  expect(found).toHaveLength(1);
  return found[0];
}

/** The work item the run's documents continue in: the project's other one. */
async function continuationOf(projects: Projects, project: string, work: string): Promise<string> {
  const others = async () => (await projects.timeline(project)).items.filter((item) => item.kind === 'work' && item.id !== work);
  await expect.poll(async () => (await others()).length).toBe(1);
  return (await others())[0].id;
}

/** Returns once the continuation's session runs: its message sent on the run's conversation. */
async function continued(projects: Projects, project: string, continuation: string): Promise<void> {
  await expect.poll(async () => (await projects.work(project, continuation)).state).toBe('running');
}

test.describe('A registered document', () => {
  test('shows its file’s name on a muted card with Pilot’s dots and “Loads when the turn ends”, and takes no close, on its line or in the overlay, until its run’s end reads it, then its text’s title on a published card, live', async ({
    people,
    projects,
    controller,
    timeline,
    overlay,
    deploymentSse,
  }) => {
    const { project, work, environment } = await running({ people, projects });
    const survey = await registered(controller, projects, environment, work, SURVEY_PATH, SURVEY);
    const item = timeline.item(survey);

    await overlay.open(project, survey);
    await expect(overlay.title).toHaveText('survey.md');
    await expect(overlay.failed).toHaveText('The document did not load.');
    await expect(overlay.reviewed).toHaveCount(0);
    await expect(overlay.send).toHaveCount(0);

    await timeline.open(project);
    await deploymentSse.ensureConnected();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.title).toHaveText('survey.md');
    await expect(item.root).toHaveClass(/\bawaiting\b/);
    await expect(item.card.root).toHaveAttribute('data-read', 'awaiting');
    await expect(item.card.loads).toHaveText('Loads when the turn ends');
    await expect(item.writing).toBeVisible();
    await expect(item.card.didNotLoad).toHaveCount(0);
    await expect(item.card.open).toBeVisible();
    await expect(item.card.reviewed).toHaveCount(0);
    await expect(item.card.readTime).toHaveCount(0);

    await endRun(controller, environment);
    await expect(item.title).toHaveText('The survey');
    await expect(item.root).not.toHaveClass(/\bawaiting\b/);
    await expect(item.card.root).not.toHaveAttribute('data-read');
    await expect(item.card.loads).toHaveCount(0);
    await expect(item.writing).toHaveCount(0);
    await expect(item.card.didNotLoad).toHaveCount(0);
    await expect(item.card.readTime).toHaveText('1 min read');
    await expect(item.card.reviewed).toBeVisible();
    await expect(item.root).toHaveAttribute('data-state', 'open');
  });

  test('whose writer Pilot asked about its blocks says so, live: “Pilot asked the writer about D2 and D4” under an inline document’s title, under a card’s summary, under a one-ask item’s title and under a confirmation’s row', async ({
    people,
    projects,
    controller,
    timeline,
    deploymentSse,
  }) => {
    const { project, work, environment } = await running({ people, projects });
    const kit = await registered(controller, projects, environment, work, KIT_PATH, KIT);
    const route = await registered(controller, projects, environment, work, ROUTE_PATH, ROUTE);
    const pitch = await registered(controller, projects, environment, work, PITCH_PATH, PITCH);
    const push = await registered(controller, projects, environment, work, PUSH_PATH, PUSH);
    await endRun(controller, environment);
    await expect.poll(async () => (await projects.item(project, route)).awaiting_read).toBe(false);

    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const inline = timeline.item(kit);
    const card = timeline.item(route);
    await expect(inline.title).toHaveText('The kit');
    await expect(inline.document).toBeVisible();
    await expect(card.card.root).toBeVisible();
    await expect(inline.writerAsked).toHaveCount(0);
    await expect(card.writerAsked).toHaveCount(0);

    await projects.askWriter(kit, [
      { block: 'D4', question: 'Does “chain” mean the lock or the tow chain?' },
      { block: 'D2', question: 'Which stove does “gas” mean?' },
    ]);
    await expect(inline.writerAsked).toHaveText('Pilot asked the writer about D2 and D4');
    await expect(card.writerAsked).toHaveCount(0);

    await projects.askWriter(route, [{ block: 'D1', question: 'Is the shore path open in spring?' }]);
    await expect(card.card.root.getByTestId('timeline.item.writer-asked')).toHaveText('Pilot asked the writer about D1');
    await expect(inline.writerAsked).toHaveText('Pilot asked the writer about D2 and D4');

    await projects.askWriter(pitch, [{ block: 'Q1', question: 'Is the hill the one past the lake?' }]);
    await projects.askWriter(push, [{ block: 'C1', question: 'Which camp list does it push?' }]);
    await expect(timeline.item(pitch).title).toHaveText('Where do we pitch?');
    await expect(timeline.item(pitch).writerAsked).toHaveText('Pilot asked the writer about Q1');
    await expect(timeline.item(push).root).toHaveAttribute('data-kind', 'confirmation');
    await expect(timeline.item(push).writerAsked).toHaveText('Pilot asked the writer about C1');
  });

  test('whose read at its run’s end fails keeps its file’s name and no text, “Did not load” beside it, opens to “The document did not load”, closes with Reviewed, and its session log says why', async ({
    people,
    projects,
    controller,
    timeline,
    overlay,
    sessionLog,
    page,
  }) => {
    const { project, work, environment } = await running({ people, projects });
    const survey = await registered(controller, projects, environment, work, SURVEY_PATH, SURVEY);
    // The file is moved after it was registered.
    await controller.removeFile(environment, SURVEY_PATH);
    await endRun(controller, environment);
    await expect.poll(async () => (await projects.item(project, survey)).awaiting_read).toBe(false);
    const failure = await fileEvent(projects, work, 'read-failed');
    expect(failure).toMatchObject({ item: survey, path: SURVEY_PATH });

    await sessionLog.open(project, work);
    await expect(sessionLog.notices).toHaveText([`Could not read ${SURVEY_PATH} because ${failure.reason}`]);

    await timeline.open(project);
    const item = timeline.item(survey);
    await expect(item.title).toHaveText('survey.md');
    await expect(item.card.root).toHaveAttribute('data-read', 'failed');
    await expect(item.card.didNotLoad).toHaveText('Did not load');
    await expect(item.root).not.toHaveClass(/\bawaiting\b/);
    await expect(item.card.loads).toHaveCount(0);
    await expect(item.writing).toHaveCount(0);
    await expect(item.card.readTime).toHaveCount(0);
    await expect(item.card.summary).toHaveCount(0);
    await item.card.open.click();
    await expect(page).toHaveURL(documentAddress(project, survey));
    await expect(overlay.title).toHaveText('survey.md');
    await expect(overlay.failed).toHaveText('The document did not load.');
    await expect(overlay.reviewed).toBeVisible();
    await overlay.close.click();

    await item.card.reviewed.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineTitle).toHaveText('survey.md');
    // A failed read is closed as the run's documents are: its close continues the conversation.
    await continued(projects, project, await continuationOf(projects, project, work));
  });

  test('closed is written back to its file, and the last of its run’s to close continues the conversation as a new work item after them, Undo gone from every one of them', async ({
    people,
    projects,
    controller,
    timeline,
    deploymentSse,
  }) => {
    const { project, work, environment } = await running({ people, projects });
    const survey = await registered(controller, projects, environment, work, SURVEY_PATH, SURVEY);
    const pitch = await registered(controller, projects, environment, work, PITCH_PATH, PITCH);
    await endRun(controller, environment);
    await expect.poll(async () => (await projects.item(project, survey)).title).toBe('The survey');
    await expect.poll(async () => (await projects.item(project, pitch)).title).toBe('Where do we pitch?');
    await controller.putFile(environment, SURVEY_PATH, SURVEY_EDITED);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const surveyItem = timeline.item(survey);
    const pitchItem = timeline.item(pitch);

    // Undo stands while another document of the run is open, and its close writes it back again.
    await surveyItem.card.reviewed.click();
    await expect(surveyItem.root).toHaveAttribute('data-state', 'done');
    await expect.poll(() => controller.fileText(environment, SURVEY_PATH)).toBe(SURVEY);
    await surveyItem.undo.click();
    await expect(surveyItem.root).toHaveAttribute('data-state', 'open');
    await controller.putFile(environment, SURVEY_PATH, SURVEY_EDITED);
    await surveyItem.card.reviewed.click();
    await expect(surveyItem.root).toHaveAttribute('data-state', 'done');
    await expect(surveyItem.undo).toBeVisible();

    await pitchItem.block.answerField.fill('The lake');
    await pitchItem.block.answerSend.click();
    await expect(pitchItem.root).toHaveAttribute('data-state', 'done');
    const continuation = await continuationOf(projects, project, work);
    const continuationItem = timeline.item(continuation);
    await expect(continuationItem.title).toHaveText(TITLE);
    expect(await timeline.items.evaluateAll((items) => items.map((each) => each.getAttribute('data-item-id')))).toEqual([
      work,
      survey,
      pitch,
      continuation,
    ]);
    await expect(surveyItem.undo).toHaveCount(0);
    await expect(pitchItem.undo).toHaveCount(0);

    await continued(projects, project, continuation);
    expect(await controller.fileText(environment, SURVEY_PATH)).toBe(SURVEY);
    expect(await controller.fileText(environment, PITCH_PATH)).toContain('answer: The lake');
  });

  test('whose write-back the controller refuses says why in its session log, live, and fails the continuation’s start with the reason', async ({
    people,
    projects,
    controller,
    timeline,
    sessionLog,
  }) => {
    const { project, work, environment } = await running({ people, projects });
    const survey = await registered(controller, projects, environment, work, SURVEY_PATH, SURVEY);
    await endRun(controller, environment);
    await expect.poll(async () => (await projects.item(project, survey)).title).toBe('The survey');
    // Its path is a folder by the time it is closed.
    await controller.removeFile(environment, SURVEY_PATH);
    await controller.putFile(environment, `${SURVEY_PATH}/notes.md`, 'A note.\n');

    await sessionLog.open(project, work);
    await expect(sessionLog.notices).toHaveCount(0);
    await projects.reviewed(survey);
    await expect(sessionLog.notices).toHaveCount(1);
    const refusal = await fileEvent(projects, work, 'write-back-refused');
    expect(refusal).toMatchObject({ item: survey, path: SURVEY_PATH });
    await expect(sessionLog.notices).toHaveText([`Could not write ${SURVEY_PATH} back because ${refusal.reason}`]);

    const continuation = await continuationOf(projects, project, work);
    await expect.poll(async () => (await projects.work(project, continuation)).state).toBe('failed');
    await timeline.open(project);
    await expect(timeline.item(continuation).work.line).toHaveText(
      `Failed · Cannot write ${SURVEY_PATH} back because ${refusal.reason}`,
    );
  });
});
