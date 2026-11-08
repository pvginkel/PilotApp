/**
 * A document a work item's session registers (F85.1, F65): on the timeline from its registration,
 * a review titled by its file's name, with no text and no close until the turn that ends its run
 * has read it (review 7). Meanwhile, and while the pass after that turn runs, it is Pilot's line
 * (F13.7): a dashed circle in its kind's place, its title, what Pilot does on it going to the work
 * that does it, the pulse while the pass runs, the pass no line of its own and no job's button
 * beside Pilot's; then published as written, its title its text's, its kind's icon back, the pass's
 * mark in its head, live (F59.1). Opened meanwhile, it reads only, under the gold strip saying what
 * Pilot does on it (F28.9): awaiting its read, that nothing of it has been read yet, with no Stop;
 * under its pass, *Stop and take over*, which stops the pass, shown stopped with Retry in the head
 * of each document it covers, and hands every one of them to the person, live. A read that
 * fails keeps its file's name and no text, *Did not load* beside it: it opens to "The document did
 * not load", closes with Reviewed, and its work item's session log says why (ruling D1). Its close
 * is written back to its file, and the close that leaves none of the run's documents open
 * continues the conversation as a new work item after the answered ones, from when Undo is gone
 * from every document of the run (review 1); a write-back the controller refuses is in the run's
 * session log, live, and fails that continuation's start with its reason (F125). A block whose
 * writer Pilot asked about it carries the mark in its head on the timeline, live, a one-ask item's
 * and a confirmation's in the item's head, and the mark opens the document at the questions (F52.2).
 */

import { test, expect } from '../support/fixtures';
import type { Chats } from '../support/chats';
import { coloursOf, hue } from '../support/contrast';
import type { Controller } from '../support/controller';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';
import { clarificationAddress, documentAddress } from '../support/page-objects/overlay-page';
import { sessionLogAddress } from '../support/page-objects/session-log-page';
import { addressOf } from '../support/page-objects/timeline-page';

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

/**
 * The work item's turn ends, and its run with it; the pass its end places once the run's documents
 * are read starts in the store and ends, the documents then the person's.
 */
async function endRun(controller: Controller, chats: Chats, project: string, environment: string) {
  const passed = await chats.passing(project);
  await endTurn(controller, environment);
  await passed();
}

/** The work item's turn ends, and its run with it. */
async function endTurn(controller: Controller, environment: string) {
  await controller.play(environment, 'claude-1', [text('wrote', 'The survey is written and registered.')]);
  await controller.finish(environment, 'claude-1');
}

/** Pilot's own job on the project's timeline: the pass after the run's turn. */
async function passOf(projects: Projects, project: string): Promise<string> {
  const job = async () => (await projects.timeline(project)).items.find((item) => item.work?.pilots_own)?.id;
  await expect.poll(job).toBeDefined();
  return (await job())!;
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

/** The work item the run's documents continue in: the project's other one, Pilot's own jobs aside, the one after the run's turn among them. */
async function continuationOf(projects: Projects, project: string, work: string): Promise<string> {
  const others = async () =>
    (await projects.timeline(project)).items.filter((item) => item.kind === 'work' && item.id !== work && !item.work?.pilots_own);
  await expect.poll(async () => (await others()).length).toBe(1);
  return (await others())[0].id;
}

/** Returns once the continuation's session runs: its message sent on the run's conversation. */
async function continued(projects: Projects, project: string, continuation: string): Promise<void> {
  await expect.poll(async () => (await projects.work(project, continuation)).state).toBe('running');
}

test.describe('A registered document', () => {
  test('is Pilot’s line until its run’s end reads it and the pass after it ends: its file’s name opening nothing, “Awaiting the run” going to the work item, no pulse and no Open, its Discuss under the mouse as a done line’s, and in the overlay the strip saying nothing of it has been read yet, with no Stop and no close; then its text’s title opening the document, Open under the mouse, and “Pre-ruling” pulsing, opening the pass’s session log, the pass no line of its own and no job’s button beside it; then its kind’s icon on a published card, the ended pass’s mark in its head, live', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
    overlay,
    deploymentSse,
    page,
  }) => {
    const { project, work, environment } = await running({ people, projects });
    const survey = await registered(controller, projects, environment, work, SURVEY_PATH, SURVEY);
    const item = timeline.item(survey);

    await overlay.open(project, survey);
    await expect(overlay.title).toHaveText('survey.md');
    await expect(overlay.strip.root).toHaveAttribute('data-doing', 'awaiting_run');
    await expect(overlay.strip.text).toHaveText('Nothing of this document has been read yet.');
    await expect(overlay.strip.stop).toHaveCount(0);
    await expect(overlay.unread).toHaveText('Its text shows here once Pilot has read it.');
    await expect(overlay.failed).toHaveCount(0);
    await expect(overlay.foot).toHaveCount(0);

    await timeline.open(project);
    await deploymentSse.ensureConnected();
    await expect(item.root).toHaveAttribute('data-state', 'pilots');
    await expect(item.lineKind.locator('svg')).toHaveClass(/\blucide-circle-dashed\b/);
    await expect(item.lineTitle).toHaveText('survey.md');
    await expect(item.pilots.root).toHaveText('Awaiting the run');
    await expect(item.pilots.root).toHaveAttribute('title', `Go to the work item: ${TITLE}`);
    await expect(item.pilots.pulse).toHaveCount(0);
    // Its actions show as a done line’s, while the mouse is on it (F13.8).
    await page.mouse.move(1, 1);
    await expect(item.open).toHaveCount(0);
    await expect(item.lineDiscuss).toBeHidden();
    await expect(item.lineTitle).not.toHaveAttribute('href');
    await item.line.hover();
    await expect(item.lineDiscuss).toBeVisible();
    await expect(item.lineTime).toBeVisible();
    await expect(item.card.root).toHaveCount(0);
    await expect(item.writing).toHaveCount(0);
    await item.pilots.root.click();
    await expect(page).toHaveURL(addressOf(project, work));

    const pass = await chats.pass(project);
    await endTurn(controller, environment);
    await pass.running();
    const job = await passOf(projects, project);
    await expect(item.lineTitle).toHaveText('The survey');
    await expect(item.root).toHaveAttribute('data-state', 'pilots');
    await expect(item.pilots.root).toHaveText('Pre-ruling');
    await expect(item.pilots.root).toHaveAttribute('href', sessionLogAddress(project, job));
    await expect(item.pilots.pulse).toBeVisible();
    await expect(item.lineTitle).toHaveAttribute('href', documentAddress(project, survey));
    await item.line.hover();
    await expect(item.open).toBeVisible();
    // The line's one button is the pass's: no job's beside it, and the pass no line of its own (F59.1, R26).
    await expect(item.job.root).toHaveCount(0);
    await expect(timeline.item(job).root).toHaveCount(0);

    await pass.end();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.line).toHaveCount(0);
    await expect(item.title).toHaveText('The survey');
    await expect(item.kind.locator('svg')).toHaveClass(/\blucide-book-open\b/);
    await expect(item.card.root).not.toHaveAttribute('data-read');
    await expect(item.writing).toHaveCount(0);
    await expect(item.card.didNotLoad).toHaveCount(0);
    await expect(item.card.readTime).toHaveText('1 min read');
    await expect(item.card.reviewed).toBeVisible();
    await expect(item.job.root).toHaveAttribute('data-form', 'ended');
    await expect(item.job.root).toHaveAttribute('href', sessionLogAddress(project, job));
    await expect(item.job.root).toBeVisible();
  });

  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

    test('is Pilot’s line as a done line is there: no Open or Discuss on it, a tap on it before its read opening the menu of its Discuss, and once read its document as a view', async ({
      people,
      projects,
      controller,
      chats,
      timeline,
      overlay,
      deploymentSse,
      page,
    }) => {
      const { project, work, environment } = await running({ people, projects });
      const survey = await registered(controller, projects, environment, work, SURVEY_PATH, SURVEY);
      await timeline.open(project);
      await deploymentSse.ensureConnected();
      const item = timeline.item(survey);

      await expect(item.root).toHaveAttribute('data-state', 'pilots');
      await expect(item.lineTitle).toHaveText('survey.md');
      await expect(item.open).toHaveCount(0);
      await expect(item.lineDiscuss).toHaveCount(0);
      await item.lineKind.tap();
      await expect(item.lineMenu.getByRole('menuitem')).toHaveText(['Discuss']);
      await expect(page).toHaveURL(projectAddress(project));
      await item.lineKind.tap();
      await expect(item.lineMenu).toHaveCount(0);

      const pass = await chats.pass(project);
      await endTurn(controller, environment);
      await pass.running();
      await expect(item.lineTitle).toHaveText('The survey');
      await expect(item.open).toHaveCount(0);
      await expect(item.lineDiscuss).toHaveCount(0);
      await item.lineKind.tap();
      await expect(page).toHaveURL(documentAddress(project, survey));
      await expect(overlay.discuss).toBeVisible();
      await expect(item.lineMenu).toHaveCount(0);
    });
  });

  test('whose writer Pilot asked about a block carries the mark, live, in the block’s head inline, in the item’s head of a one-ask item and a confirmation, and none on a card nor any line under a title; the mark opens the document at the questions', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
    overlay,
    deploymentSse,
    page,
  }) => {
    const { project, work, environment } = await running({ people, projects });
    const kit = await registered(controller, projects, environment, work, KIT_PATH, KIT);
    const route = await registered(controller, projects, environment, work, ROUTE_PATH, ROUTE);
    const pitch = await registered(controller, projects, environment, work, PITCH_PATH, PITCH);
    const push = await registered(controller, projects, environment, work, PUSH_PATH, PUSH);
    await endRun(controller, chats, project, environment);
    await expect.poll(async () => (await projects.item(project, route)).awaiting_read).toBe(false);

    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const inline = timeline.item(kit);
    const card = timeline.item(route);
    await expect(inline.title).toHaveText('The kit');
    await expect(inline.document).toBeVisible();
    await expect(card.card.root).toBeVisible();
    await expect(inline.blockAt('D2').writerAsked).toHaveCount(0);

    await projects.askWriter(kit, [
      { block: 'D4', question: 'Does “chain” mean the lock or the tow chain?' },
      { block: 'D2', question: 'Which stove does “gas” mean?' },
    ]);
    await expect(inline.blockAt('D2').writerAsked).toHaveText('Pilot asked the writer');
    await expect(inline.blockAt('D4').writerAsked).toHaveText('Pilot asked the writer');
    await expect(inline.blockAt('D1').writerAsked).toHaveCount(0);
    await expect(inline.writerAsked).toHaveCount(0);

    await projects.askWriter(route, [{ block: 'D1', question: 'Is the shore path open in spring?' }]);
    await projects.askWriter(pitch, [{ block: 'Q1', question: 'Is the hill the one past the lake?' }]);
    await projects.askWriter(push, [{ block: 'C1', question: 'Which camp list does it push?' }]);
    const one = timeline.item(pitch);
    await expect(one.title).toHaveText('Where do we pitch?');
    await expect(one.head.getByTestId('timeline.item.writer-asked')).toHaveText('Pilot asked the writer');
    await expect(one.writerAsked).toHaveAttribute('href', clarificationAddress(project, pitch));
    await expect(one.block.writerAsked).toHaveCount(0);
    const confirmation = timeline.item(push);
    await expect(confirmation.root).toHaveAttribute('data-kind', 'confirmation');
    await expect(confirmation.head.getByTestId('timeline.item.writer-asked')).toHaveText('Pilot asked the writer');
    // Asked before the one-ask item, whose mark has come.
    await expect(card.root.getByText('Pilot asked the writer')).toHaveCount(0);
    for (const item of [inline, card, one, confirmation]) await expect(item.root).not.toContainText('Pilot asked the writer about');

    await one.writerAsked.click();
    await expect(page).toHaveURL(clarificationAddress(project, pitch));
    await expect(overlay.clarification().question('Q1').text).toHaveText('Is the hill the one past the lake?');
    await expect(overlay.clarificationBox).toBeInViewport();
    await expect(overlay.blockAt('Q1').writerAsked).toHaveText('Pilot asked the writer');
  });

  test('opened while its pass pre-rules it reads only, under the gold strip: what Pilot does and Stop and take over, every control drawn and taking nothing, no foot; Stop and take over stops the pass, shown stopped with Retry in the head of every document the pass covers, each of them the person’s, live', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
    overlay,
    deploymentSse,
    page,
  }) => {
    const { project, work, environment } = await running({ people, projects });
    const kit = await registered(controller, projects, environment, work, KIT_PATH, KIT);
    const pitch = await registered(controller, projects, environment, work, PITCH_PATH, PITCH);
    const pass = await chats.pass(project);
    await endTurn(controller, environment);
    await pass.running();
    const job = await passOf(projects, project);

    await overlay.open(project, kit);
    await deploymentSse.ensureConnected();
    await expect(overlay.title).toHaveText('The kit');
    await expect(overlay.strip.root).toHaveAttribute('data-doing', 'pre_ruling');
    await expect(overlay.strip.text).toHaveText(
      'Pilot is pre-ruling this document: it settles what it may, and what is left comes to you.',
    );
    await expect(overlay.strip.link).toHaveCount(0);
    await expect(overlay.strip.stop).toHaveText('Stop and take over');
    await expect(overlay.strip.stop).toBeEnabled();
    // The pass in its head too, over the strip (F28.10).
    await expect(overlay.job.root).toHaveAttribute('data-form', 'running');
    await expect(overlay.job.root).toHaveAttribute('href', sessionLogAddress(project, job));
    const dome = overlay.blockAt('D1').option('Dome');
    await expect(overlay.blockAt('D1').options).toHaveCount(2);
    await expect(dome).toBeDisabled();
    await expect(overlay.blocks.locator('button.option:enabled')).toHaveCount(0);
    await expect(overlay.foot).toHaveCount(0);
    // Under the head, over the body.
    const head = (await overlay.head.boundingBox())!;
    const strip = (await overlay.strip.root.boundingBox())!;
    const body = (await overlay.body.boundingBox())!;
    expect(strip.y).toBeCloseTo(head.y + head.height, 0);
    expect(body.y).toBeCloseTo(strip.y + strip.height, 0);
    // Gold, as the gold bar is: its words at 4.5:1 or better on it, in either theme.
    for (const scheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await expect(page.locator('html')).toHaveAttribute('data-theme', scheme);
      const { ratio, background } = await coloursOf(overlay.strip.root);
      expect(ratio, `the strip's contrast in ${scheme}`).toBeGreaterThanOrEqual(4.5);
      expect(Math.abs(hue(background) - 44), `the strip's hue in ${scheme}`).toBeLessThan(5);
    }

    await overlay.strip.stop.click();
    await expect(overlay.strip.root).toHaveCount(0);
    await expect(dome).toBeEnabled();
    await expect(overlay.send).toBeVisible();
    await expect(overlay.job.root).toHaveAttribute('data-form', 'stopped');
    await expect(overlay.job.retry).toBeVisible();
    for (const document of [kit, pitch]) {
      const stopped = timeline.item(document).job;
      await expect(stopped.root).toHaveAttribute('data-form', 'stopped');
      await expect(stopped.root).toHaveAttribute('href', sessionLogAddress(project, job));
      await expect(stopped.root).toContainText('Stopped');
      await expect(stopped.pulse).toHaveCount(0);
      await expect(stopped.retry).toBeVisible();
    }
    expect((await projects.work(project, job)).state).toBe('stopped');
    expect((await projects.item(project, pitch)).pilots_work).toBeNull();
    await dome.click();
    await expect(overlay.blockAt('D1').answered).toBeVisible();
  });

  test('whose read at its run’s end fails keeps its file’s name and no text, “Did not load” beside it, opens to “The document did not load”, closes with Reviewed, and its session log says why', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
    overlay,
    docTabs,
    sessionLog,
    page,
  }) => {
    const { project, work, environment } = await running({ people, projects });
    const survey = await registered(controller, projects, environment, work, SURVEY_PATH, SURVEY);
    // The file is moved after it was registered.
    await controller.removeFile(environment, SURVEY_PATH);
    await endRun(controller, chats, project, environment);
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
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.writing).toHaveCount(0);
    await expect(item.card.readTime).toHaveCount(0);
    await expect(item.card.summary).toHaveCount(0);
    await item.card.open.click();
    await expect(page).toHaveURL(documentAddress(project, survey));
    await expect(overlay.title).toHaveText('survey.md');
    await expect(overlay.failed).toHaveText('The document did not load.');
    await expect(overlay.strip.root).toHaveCount(0);
    await expect(overlay.reviewed).toBeVisible();
    await docTabs.document(survey).close.click();

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
    chats,
    timeline,
    deploymentSse,
  }) => {
    const { project, work, environment } = await running({ people, projects });
    const survey = await registered(controller, projects, environment, work, SURVEY_PATH, SURVEY);
    const pitch = await registered(controller, projects, environment, work, PITCH_PATH, PITCH);
    await endRun(controller, chats, project, environment);
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
    await surveyItem.line.hover();
    await surveyItem.undo.click();
    await expect(surveyItem.root).toHaveAttribute('data-state', 'open');
    await controller.putFile(environment, SURVEY_PATH, SURVEY_EDITED);
    await surveyItem.card.reviewed.click();
    await expect(surveyItem.root).toHaveAttribute('data-state', 'done');
    await surveyItem.line.hover();
    await expect(surveyItem.undo).toBeVisible();

    await pitchItem.block.answerField.fill('The lake');
    await pitchItem.block.answerSend.click();
    await expect(pitchItem.root).toHaveAttribute('data-state', 'done');
    const continuation = await continuationOf(projects, project, work);
    const continuationItem = timeline.item(continuation);
    await expect(continuationItem.title).toHaveText(TITLE);
    // Pilot's job after the run's turn, placed once the run's documents were read (design 3 D2), the
    // pass on them, shows on them, no line of its own (F59.1).
    const job = (await projects.timeline(project)).items.find((item) => item.work?.pilots_own)!.id;
    expect(await timeline.items.evaluateAll((items) => items.map((each) => each.getAttribute('data-item-id')))).toEqual([
      work,
      survey,
      pitch,
      continuation,
    ]);
    await expect(pitchItem.job.root).toHaveAttribute('href', sessionLogAddress(project, job));
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
    chats,
    timeline,
    sessionLog,
  }) => {
    const { project, work, environment } = await running({ people, projects });
    const survey = await registered(controller, projects, environment, work, SURVEY_PATH, SURVEY);
    await endRun(controller, chats, project, environment);
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

test.describe('A registered document on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('is Pilot’s line with what Pilot does on a row of its own under the title', async ({ people, projects, controller, timeline }) => {
    const { project, work, environment } = await running({ people, projects });
    const survey = await registered(controller, projects, environment, work, SURVEY_PATH, SURVEY);
    await timeline.open(project);
    const item = timeline.item(survey);
    await expect(item.pilots.root).toHaveText('Awaiting the run');

    const title = (await item.lineTitle.boundingBox())!;
    const button = (await item.pilots.root.boundingBox())!;
    expect(button.y).toBeGreaterThanOrEqual(title.y + title.height - 1);
    expect(button.x).toBeLessThan(title.x + 10);
  });

  test('opened while its pass pre-rules it has the strip under its head across the screen, Stop and take over under its words at the right', async ({
    people,
    projects,
    controller,
    chats,
    overlay,
  }) => {
    const { project, work, environment } = await running({ people, projects });
    const kit = await registered(controller, projects, environment, work, KIT_PATH, KIT);
    const pass = await chats.pass(project);
    await endTurn(controller, environment);
    await pass.running();

    await overlay.open(project, kit);
    await expect(overlay.strip.stop).toBeVisible();
    const head = (await overlay.head.boundingBox())!;
    const strip = (await overlay.strip.root.boundingBox())!;
    const words = (await overlay.strip.text.boundingBox())!;
    const stop = (await overlay.strip.stop.boundingBox())!;
    expect(strip.y).toBeCloseTo(head.y + head.height, 0);
    expect(strip.x).toBe(head.x);
    expect(strip.width).toBe(head.width);
    expect(stop.y).toBeGreaterThanOrEqual(words.y + words.height - 1);
    expect(stop.x + stop.width).toBeCloseTo(strip.x + strip.width - 14, 0);
    await pass.end();
  });
});
