/**
 * Create project in a draft's head (F48): disabled with its reason while nothing is drafted, while
 * Pilot writes or while the draft names no slug (F48.1), never for an ask the draft leaves open;
 * pressed, the timeline opens at once with the opening first, the person's words, the draft's copy
 * and the material the definition chat attached on it (F48.2, F18.1, F18.2), the head the open
 * project's and the panel's tabs Chat and Documents, the project document first under Documents
 * (F37.4). The Chat tab shows the definition chat above its line, with no label (F130.1), and
 * Discuss opens a new chat below it (F48.2). The setup, Pilot's first background job, is a work item
 * of Pilot's own: its line, its session log, no env chip and no Stop or Resume (F59.1, F26.3), and a
 * quiet done line once its turn ends. A job placed while it runs, the one after a worker's turn,
 * waits its turn behind it, its line saying so, and goes on once the setup's turn ends (F59.2).
 * Failed, it offers Retry where a worker's Resume is: a fresh setup at the project's next place,
 * the failed line staying with its session log, saying it was retried and offering Retry no more;
 * a running or done job offers none (D2). Dead at the quota wall, it offers none while its nudge is
 * owed, and once a reading brings the quota back the nudge carries it on (F135.3; D078). Create pauses the new project, its setup let through: it
 * is pausing while the setup runs, a work item placed meanwhile held, "Paused", and paused once the
 * setup's turn ends, Pilot's line under the setup saying the project is ready, gone at the status
 * icon's resume, which lets the held work item go on (D083).
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import type { Chats } from '../support/chats';
import { rawTurn, type Controller } from '../support/controller';
import { makeUnique, makeUniqueToken } from '../support/helpers';
import type { ChatPage } from '../support/page-objects/chat-page';
import type { ProjectHeadPage } from '../support/page-objects/project-head-page';
import type { Projects } from '../support/projects';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '5c8e2a17-9b4d-4e63-a1f0-7d2b6c9e3f58';
const text = (id: string, words: string) =>
  JSON.stringify({
    type: 'assistant',
    message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] },
    parent_tool_use_id: null,
    session_id: CONVERSATION,
  });

const WORDS = 'Let us plan the summer trip by the lake.';
const REPLY = 'I drafted the trip; where you sleep is still open.';
const HOW = 'Hand the project to Pilot: it sets it up and starts the plan';
const SETUP = 'Setting up the project';
/** Claude's words at the week's wall, as the invented turn at the wall (`turn_wall`) ends. */
const LIMIT = 'Weekly limit reached ∙ resets Jan 4, 12am';
/** The title of the job after a worker's turn that registered nothing (backend/app/services/job_service.py). */
const NEXT = 'Deciding what is next';

const SLEEP = '## Where do we sleep?\n\n```decision id=D1\noptions:\n  - Tent\n  - Cabin\n```\n';
const draftText = (title: string, slug?: string) =>
  [...(slug === undefined ? [] : [`---\nslug: ${slug}\n---\n`]), `# ${title}\n`, 'A week by the lake.\n', SLEEP].join('\n');

interface Drafting {
  page: Page;
  projects: Projects;
  projectHead: ProjectHeadPage;
  controller: Controller;
  chats: Chats;
  definitionChat: ChatPage;
}

/**
 * A draft of the signed-in person's, open on its page: its definition chat's first message and
 * Pilot's reply, the draft saved with its title, its open ask and its slug, a file attached hung
 * on nothing, and the store ready for the project's folder. Answers its id, title and slug.
 */
async function drafted({ projects, projectHead, controller, chats, definitionChat }: Drafting, handle: string) {
  const { id, folder } = await projects.makeDraft({ members: [handle] });
  await projectHead.open(id);
  const opened = await chats.opening(id, folder);
  await definitionChat.field.fill(WORDS);
  await definitionChat.send.click();
  const session = await opened();
  const title = makeUnique('Summer trip');
  const slug = `summer-${makeUniqueToken().toLowerCase()}`;
  await projects.saveProjectDocument(id, 'draft', draftText(title, slug));
  await projects.attachToDraft(id, [{ title: 'Packing list', filename: 'packing.txt', content_type: 'text/plain', content: 'Tent, stove, lamp.\n' }]);
  await controller.play(chats.store, session, [text('one', REPLY)]);
  await controller.finish(chats.store, session, 'success', REPLY);
  await expect(projectHead.createButton).toBeEnabled();
  return { id, title, slug };
}

test.describe('Create project', () => {
  test('is disabled with its reason while nothing is drafted, while Pilot writes and while the draft names no slug, never for the ask it leaves open', async ({
    people,
    projects,
    projectHead,
    controller,
    chats,
    definitionChat,
  }) => {
    const me = await people.signIn();
    const { id, folder } = await projects.makeDraft({ members: [me.handle!] });
    await projectHead.open(id);
    const create = projectHead.createButton;
    await expect(create).toHaveText('Create project');
    await expect(create).toBeDisabled();
    await expect(create).toHaveAttribute('title', 'Cannot create New project because nothing is drafted');

    const opened = await chats.opening(id, folder);
    await definitionChat.field.fill(WORDS);
    await definitionChat.send.click();
    const session = await opened();
    await expect(create).toHaveAttribute('title', 'Cannot create New project because Pilot is writing');
    await expect(create).toBeDisabled();

    const title = makeUnique('Summer trip');
    await projects.saveProjectDocument(id, 'draft', draftText(title));
    await expect(create).toHaveAttribute('title', `Cannot create ${title} because Pilot is writing`);
    await controller.play(chats.store, session, [text('one', REPLY)]);
    await controller.finish(chats.store, session, 'success', REPLY);
    await expect(create).toHaveAttribute('title', `Cannot create ${title} because the draft names no slug`);
    await expect(create).toBeDisabled();

    // The draft's D1 stays open: no reason.
    await projects.saveProjectDocument(id, 'draft', draftText(title, `summer-${makeUniqueToken().toLowerCase()}`));
    await expect(create).toBeEnabled();
    await expect(create).toHaveAttribute('title', HOW);
    expect((await projects.head(id)).create_refusal).toBeNull();
  });

  test('opens the timeline at once with the opening first: the person’s words, the draft’s copy and the material attached on it; the head is the open project’s, the panel’s tabs Chat and Documents, the project document first', async ({
    page,
    people,
    projects,
    projectHead,
    controller,
    chats,
    definitionChat,
    timeline,
    panel,
  }) => {
    const me = await people.signIn();
    const { id, title, slug } = await drafted({ page, projects, projectHead, controller, chats, definitionChat }, me.handle!);
    await expect(panel.tabs).toHaveText(['Draft', /^Documents/]);
    await chats.ready(id, slug);

    await projectHead.create();

    await expect(timeline.opening).toBeVisible();
    await expect(definitionChat.root).toHaveCount(0);
    await expect(timeline.openingWho).toContainText('You started this project');
    await expect(timeline.openingWords).toHaveText(WORDS);
    await expect(timeline.openingAttachments).toHaveText([title, 'Packing list']);
    const setup = (await projects.timeline(id)).items.find((item) => item.work?.pilots_own)!;
    expect(setup.title).toBe(SETUP);
    const [opening, first] = await Promise.all([timeline.opening.boundingBox(), timeline.item(setup.id).root.boundingBox()]);
    expect(opening!.y + opening!.height).toBeLessThanOrEqual(first!.y);

    expect((await projects.head(id)).state).toBe('open');
    await expect(projectHead.name).toHaveText(title);
    await expect(projectHead.draft).toHaveCount(0);
    await expect(projectHead.createButton).toHaveCount(0);
    await expect(projectHead.draftPanelButton).toHaveCount(0);
    await expect(projectHead.autopilot).toBeVisible();
    await expect(projectHead.discussButton).toBeVisible();
    await expect(projectHead.handbookButton).toBeVisible();

    // The draft's Draft tab, remembered, reads as Chat.
    await expect(panel.tabs).toHaveText(['Chat', /^Documents/]);
    await expect(panel.root).toHaveAttribute('aria-label', 'The project’s chat and documents');
    await panel.documentsTab.click();
    await expect(panel.headings).toHaveText(['Attachments', 'In the timeline']);
    await expect(panel.projectDocument.root).toBeVisible();
    await expect(panel.projectDocument.title).toHaveText(title);
    await panel.projectDocument.root.click();
    await expect(page).toHaveURL(`/projects/${id}/project-document`);
  });

  test('leaves the definition chat in the Chat tab above its line, with no label, and Discuss opens a new chat below it', async ({
    page,
    people,
    projects,
    projectHead,
    controller,
    chats,
    definitionChat,
    chat,
    panel,
  }) => {
    const me = await people.signIn();
    const { id, slug } = await drafted({ page, projects, projectHead, controller, chats, definitionChat }, me.handle!);
    const setup = await chats.opening(id, slug);
    await projectHead.create();
    await setup();

    await expect(chat.tab).toHaveAttribute('aria-selected', 'true');
    await expect(chat.messageTexts).toHaveText([WORDS]);
    await expect(chat.texts).toHaveText([REPLY]);
    await expect(chat.closed).toHaveCount(1);
    await expect(chat.closed).toHaveAttribute('data-cause', 'created');
    await expect(chat.closed).toHaveText('');

    const opened = await chats.opening(id, slug);
    await panel.close.click();
    await projectHead.discussButton.click();
    await expect(chat.tab).toHaveAttribute('aria-selected', 'true');
    await chat.field.fill('What comes first?');
    await chat.send.click();
    await opened();
    expect((await chats.list(id)).chats.map((each) => [each.kind, each.close_cause])).toEqual([
      ['definition', 'created'],
      ['project', null],
    ]);
    await expect(chat.messageTexts).toHaveText([WORDS, 'What comes first?']);
    const [line, message] = await Promise.all([chat.closed.boundingBox(), chat.messages.last().boundingBox()]);
    expect(line!.y).toBeLessThan(message!.y);
  });
});

test.describe('The setup', () => {
  test('is a work item of Pilot’s own: its line and its session log, no env chip and no Stop or Resume; its turn ended, a quiet done line', async ({
    page,
    people,
    projects,
    projectHead,
    controller,
    chats,
    definitionChat,
    timeline,
    sessionLog,
  }) => {
    const me = await people.signIn();
    const { id, slug } = await drafted({ page, projects, projectHead, controller, chats, definitionChat }, me.handle!);
    const started = await chats.opening(id, slug);
    await projectHead.create();
    const session = await started();

    const setupId = (await projects.timeline(id)).items.find((item) => item.work?.pilots_own)!.id;
    // Its environment is the store's, once its start took it.
    await projects.environment(id, setupId);
    const setup = timeline.item(setupId);
    await expect(setup.title).toHaveText(SETUP);
    await expect(setup.work.running).toBeVisible();
    await expect(setup.work.line).toBeVisible();
    await expect(setup.work.sessionLog).toBeVisible();
    await expect(setup.work.environment).toHaveCount(0);
    await expect(setup.work.stop).toHaveCount(0);
    await expect(setup.work.resume).toHaveCount(0);

    await setup.work.sessionLog.click();
    await expect(sessionLog.item).toHaveText(SETUP);
    await expect(sessionLog.session).toHaveText(setupId);
    await expect(sessionLog.environment).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(sessionLog.overlay).toHaveCount(0);

    await controller.finish(chats.store, session, 'success', 'The plan is written.');
    await expect(setup.root).toHaveAttribute('data-state', 'done');
    await expect(setup.root).toHaveClass(/quiet/);
    await expect(setup.lineTitle).toHaveText(SETUP);
    await setup.open.click();
    await expect(page).toHaveURL(`/projects/${id}/sessions/${setupId}`);
  });

  test('a job placed while it runs, the one after a worker’s turn, waits its turn behind it, its line saying so, and goes on once its turn ends', async ({
    page,
    people,
    projects,
    projectHead,
    controller,
    chats,
    definitionChat,
    timeline,
  }) => {
    const me = await people.signIn();
    const { id, slug } = await drafted({ page, projects, projectHead, controller, chats, definitionChat }, me.handle!);
    const started = await chats.opening(id, slug);
    await projectHead.create();
    const session = await started();
    // Create pauses the project; resumed, the worker's start is not held.
    await projects.transition(id, 'resumed');
    const work = await projects.startWork(id, { title: 'Surveying the camp', brief: 'Survey the camp.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(id, work)).state).toBe('running');
    const { id: environment } = await projects.environment(id, work);

    await controller.finish(environment, 'claude-1');

    let jobId: string | undefined;
    await expect
      .poll(async () => {
        jobId = (await projects.timeline(id)).items.find((item) => item.work?.pilots_own && item.title === NEXT)?.id;
        return jobId;
      })
      .toBeDefined();
    const job = timeline.item(jobId!);
    await expect(job.title).toHaveText(NEXT);
    await expect(job.work.line).toHaveAttribute('data-state', 'held');
    await expect(job.work.cue).toHaveText('Waiting for the job before it');

    await controller.finish(chats.store, session, 'success', 'The plan is written.');
    await expect(job.work.running).toBeVisible();
    await expect(job.work.cue).not.toHaveText('Waiting for the job before it');
  });

  test('failed, it offers Retry; pressed, a fresh setup at the next place takes it on, the failed line saying so and offering Retry no more', async ({
    page,
    people,
    projects,
    projectHead,
    controller,
    chats,
    definitionChat,
    timeline,
  }) => {
    const me = await people.signIn();
    const { id, slug } = await drafted({ page, projects, projectHead, controller, chats, definitionChat }, me.handle!);
    const started = await chats.opening(id, slug);
    await projectHead.create();
    const session = await started();
    const setupId = (await projects.timeline(id)).items.find((item) => item.work?.pilots_own)!.id;
    const setup = timeline.item(setupId);
    await expect(setup.work.running).toBeVisible();
    await expect(setup.work.retry).toHaveCount(0);

    await controller.finish(chats.store, session, 'error', 'The model is overloaded.');
    await expect(setup.work.line).toHaveText('Failed · The model is overloaded.');
    await expect(setup.work.retry).toHaveText('Retry');
    await expect(setup.work.resume).toHaveCount(0);
    await expect(setup.work.retried).toHaveCount(0);

    const restarted = await chats.opening(id, slug);
    await setup.work.retry.click();
    const again = await restarted();
    await expect(setup.work.retry).toHaveCount(0);
    await expect(setup.work.sessionLog).toBeFocused();
    await expect(setup.work.retried).toContainText('Retried as a new job below');
    await expect(setup.work.line).toHaveText('Failed · The model is overloaded.');
    await expect(setup.root).toHaveAttribute('data-state', 'open');

    const items = (await projects.timeline(id)).items;
    const retryId = items.find((item) => item.work?.pilots_own && item.id !== setupId)!.id;
    expect(items.at(-1)!.id).toBe(retryId);
    const retry = timeline.item(retryId);
    await expect(retry.title).toHaveText(SETUP);
    await expect(retry.work.running).toBeVisible();
    await expect(retry.work.retry).toHaveCount(0);
    await expect(retry.work.retried).toHaveCount(0);

    await controller.finish(chats.store, again, 'success', 'The plan is written.');
    await expect(retry.root).toHaveAttribute('data-state', 'done');
    await expect(retry.work.retry).toHaveCount(0);
    await expect(setup.work.retry).toHaveCount(0);
  });

  test('dead at the quota wall, it offers no Retry while its nudge is owed; once there is quota again, the nudge carries it on, and it is done at that turn’s end', async ({
    page,
    people,
    projects,
    projectHead,
    controller,
    chats,
    definitionChat,
    timeline,
  }) => {
    const me = await people.signIn();
    const { id, slug } = await drafted({ page, projects, projectHead, controller, chats, definitionChat }, me.handle!);
    const started = await chats.opening(id, slug);
    await projectHead.create();
    const session = await started();
    const setupId = (await projects.timeline(id)).items.find((item) => item.work?.pilots_own)!.id;
    const setup = timeline.item(setupId);
    await expect(setup.work.running).toBeVisible();

    // The reading at its turn's end confirms the wall its stream shows.
    await controller.usage({ seven_day: 1 });
    await controller.play(chats.store, session, rawTurn('turn_wall'));
    await controller.finish(chats.store, session, 'error', LIMIT);
    await expect(setup.work.line).toHaveText(`Failed · ${LIMIT}`);
    await expect(setup.work.retry).toHaveCount(0);
    await expect(setup.work.resume).toHaveCount(0);
    expect((await projects.work(id, setupId)).nudge_owed).toBe(true);

    await controller.usage({ seven_day: 0.5 });
    await expect(setup.work.running).toBeVisible();
    await expect(setup.work.retry).toHaveCount(0);

    await controller.finish(chats.store, session, 'success', 'The plan is written.');
    await expect(setup.root).toHaveAttribute('data-state', 'done');
    await expect(setup.work.retry).toHaveCount(0);
  });
});

test.describe('The pause at Create', () => {
  test('pausing while the setup runs, a work item placed meanwhile held; paused once its turn ends, the ready line under the setup, gone at the resume, which lets the work item go on', async ({
    page,
    people,
    projects,
    projectHead,
    projectList,
    controller,
    chats,
    definitionChat,
    timeline,
  }) => {
    const me = await people.signIn();
    const { id, title, slug } = await drafted({ page, projects, projectHead, controller, chats, definitionChat }, me.handle!);
    const started = await chats.opening(id, slug);
    await projectHead.create();
    const session = await started();
    const setupId = (await projects.timeline(id)).items.find((item) => item.work?.pilots_own)!.id;
    const setup = timeline.item(setupId);
    await expect(setup.work.running).toBeVisible();
    const icon = projectList.statusIcon(title);
    await expect(icon.root).toHaveAttribute('data-status', 'pausing');

    const workId = await projects.startWork(id, { title: 'Pitching the tents', brief: 'Pitch the tents.', cwd: '/work/Example' });
    const work = timeline.item(workId);
    await expect(work.work.line).toHaveAttribute('data-state', 'held');
    await expect(work.work.cue).toHaveText('Paused');
    await expect(timeline.ready).toHaveCount(0);

    await controller.finish(chats.store, session, 'success', 'The plan is written.');
    await expect(setup.root).toHaveAttribute('data-state', 'done');
    await expect(icon.root).toHaveAttribute('data-status', 'paused');
    await expect(timeline.ready).toHaveText('The project is ready — resume the project to start it.');
    await expect(timeline.ready.getByRole('button')).toHaveCount(0);
    await expect(setup.root.locator('xpath=following-sibling::*[1]')).toHaveAttribute('data-testid', 'timeline.ready');
    expect((await projects.list()).find((tab) => tab.id === id)!.badge.count).toBe(0);

    const resumed = projectList.written(id, 'resumed');
    await icon.root.click();
    await resumed;
    await expect(timeline.ready).toHaveCount(0);
    await expect(work.work.running).toBeVisible();
    expect((await projects.timeline(id)).ready_after).toBeNull();
  });
});
