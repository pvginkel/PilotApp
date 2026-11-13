/**
 * A stopped work item closed for good (DB decision 78; slice 042's D1): Close stands beside Resume
 * in a stopped item's row, never a failed one's, and asks first in the row's place, as Stop does,
 * Cancel taking the focus, Esc and Cancel dismissing the question with the focus back on Close.
 * Close it closes the item for good: done, cancelled by the person, its quiet line led by the
 * cancelled mark, its kind's icon in the time's grey with a small cross at its foot (F13.1), with
 * no Undo and no Resume; it waits on nobody, so the badge loses it; and the server refuses a
 * Resume of it. It closes no document: one its stopped run registered, Pilot's line until then,
 * is read at the close and is the person's, open with its text, and no job follows. Pilot's `stop_work` with a reason stops a running item and closes it in the same
 * act, its line carrying the reason under its title, live. Close stands disabled while the project
 * is archived.
 */

import type { Locator } from '@playwright/test';
import { cssColour } from '../support/contrast';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';

const TITLE = 'Surveying the stylesheets';
const QUESTION = 'Close it for good? It takes no Resume afterwards, and what it put to you stays open.';
const REASON = 'Replaced by the survey that takes the print sheets in';
const PITCH_PATH = '/work/Example/pitch.md';
const PITCH = '# Where do we pitch?\n\nThe lake or the hill.\n\n```question id=Q1\n```\n';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '2f6c8a13-5d7e-4b90-a1c4-6e8f0b2d4a57';
const line = (value: object) => JSON.stringify({ ...value, session_id: CONVERSATION });
const toolUse = (id: string, name: string, input: object) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'tool_use', id, name, input }] }, parent_tool_use_id: null });

interface Fixtures {
  people: People;
  projects: Projects;
}

/** A project, signed in as its member. */
async function setUp({ people, projects }: Fixtures) {
  const me = await people.signIn();
  const name = makeUnique('Close');
  const project = await projects.make({ name, members: [me.handle!] });
  return { me, name, project };
}

/** A work item started in the project, once its session reads `state`. */
async function startIn(projects: Projects, project: string, state = 'running'): Promise<string> {
  const work = await projects.startWork(project, { title: TITLE, brief: 'Survey the stylesheets.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe(state);
  return work;
}

/** A work item of the project that a person stopped, its stopped turn ended. */
async function stoppedIn(projects: Projects, project: string): Promise<string> {
  const work = await startIn(projects, project);
  await projects.stop(work);
  await expect.poll(async () => (await projects.records(work)).records.at(-1)?.kind).toBe('result');
  return work;
}

/** The classes of the item body's parts, in order. */
async function bodyParts(item: Locator): Promise<string[]> {
  return item.locator('.item-body > *').evaluateAll((parts) => parts.map((part) => part.className));
}

test.describe('Close', () => {
  test('stands beside Resume on a stopped item and asks first in the row’s place, Cancel taking the focus; Esc and Cancel dismiss the question, the focus back on Close, and nothing closes', async ({
    people,
    projects,
    timeline,
    page,
  }) => {
    const { project } = await setUp({ people, projects });
    const work = await stoppedIn(projects, project);
    await timeline.open(project);
    const tile = timeline.item(work);
    const item = tile.work;
    await expect(item.row).toHaveText('ResumeClose');
    await expect(item.close).toHaveText('Close');
    await expect(item.close.locator('svg')).toHaveClass(/\blucide-x\b/);

    await item.close.click();
    await expect(item.closeConfirm.text).toHaveText(QUESTION);
    await expect(item.closeConfirm.yes).toHaveText('Close it');
    await expect(item.closeConfirm.cancel).toHaveText('Cancel');
    await expect(item.closeConfirm.cancel).toBeFocused();
    expect(await bodyParts(tile.root)).toEqual(['item-head', 'item-title', 'work-line ended', 'item-actions confirm']);
    await expect(item.resume).toHaveCount(0);
    await expect(item.close).toHaveCount(0);

    await page.keyboard.press('Escape');
    await expect(item.closeConfirm.root).toHaveCount(0);
    await expect(item.close).toBeFocused();
    await expect(item.row).toHaveText('ResumeClose');

    await item.close.click();
    await item.closeConfirm.cancel.click();
    await expect(item.closeConfirm.root).toHaveCount(0);
    await expect(item.close).toBeFocused();
    const open = await projects.item(project, work);
    expect([open.done, open.work?.state]).toEqual([null, 'stopped']);
  });

  test('confirmed, closes the item for good: its quiet line under the grey cancelled mark with no Undo and no Resume, the focus on its title, the badge without it; the server refuses its Resume', async ({
    people,
    projects,
    timeline,
    projectList,
    deploymentSse,
    backendUrl,
    page,
  }) => {
    const { me, name, project } = await setUp({ people, projects });
    const work = await stoppedIn(projects, project);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const tile = timeline.item(work);
    const item = tile.work;
    await expect(projectList.badge(name)).toHaveText('1');

    await item.close.click();
    await item.closeConfirm.yes.click();

    await expect(tile.root).toHaveAttribute('data-state', 'done');
    await expect(tile.root).toHaveClass(/\bquiet\b/);
    await expect(item.closeConfirm.root).toHaveCount(0);
    await expect(item.resume).toHaveCount(0);
    await expect(item.close).toHaveCount(0);
    await expect(tile.undo).toHaveCount(0);
    await expect(tile.lineTitle).toHaveText(TITLE);
    await expect(tile.lineTitle).toBeFocused();
    // The line leads with the cancelled mark, grey on a work item's quiet line too.
    const mark = tile.lineKind;
    await expect(mark).toHaveAttribute('title', 'Cancelled');
    await expect(mark).toHaveClass('kind-icon cancelled');
    await expect(mark.locator('g[mask] > svg')).toHaveClass(/\blucide-terminal\b/);
    await expect(mark.locator('svg.icon > path')).toHaveAttribute('d', 'm15 15 7 7M22 15l-7 7');
    await expect(mark).toHaveCSS('color', await cssColour(page, 'hsl(var(--muted-foreground))'));
    // A person's Close writes no reason.
    await expect(item.closeNote).toHaveCount(0);
    await expect(projectList.badge(name)).toHaveCount(0);

    const closed = await projects.item(project, work);
    expect([closed.done?.cause, closed.done?.by?.handle, closed.done?.undo, closed.work?.state, closed.work?.note]).toEqual([
      'cancelled',
      me.handle,
      false,
      'stopped',
      null,
    ]);
    const resume = await page.request.post(`${backendUrl}/api/sessions/${work}/resume`);
    expect(resume.status()).toBe(409);
    expect(((await resume.json()) as { error: string }).error).toBe(`Cannot resume ${TITLE} because it is closed for good`);
  });

  test('has the document its stopped run registered read: Pilot’s line while the item stands stopped, open and the person’s with its text once it is closed, and no job after it', async ({
    people,
    projects,
    controller,
    timeline,
    projectList,
    deploymentSse,
  }) => {
    const { name, project } = await setUp({ people, projects });
    const work = await startIn(projects, project);
    const { id: environment } = await projects.environment(project, work);
    await controller.putFile(environment, PITCH_PATH, PITCH);
    const pitch = await projects.register(work, PITCH_PATH);
    await projects.stop(work);
    await expect.poll(async () => (await projects.records(work)).records.at(-1)?.kind).toBe('result');
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const tile = timeline.item(work);
    const document = timeline.item(pitch);
    // A stopped run has read nothing: its document awaits its read.
    await expect(document.root).toHaveAttribute('data-state', 'pilots');

    await tile.work.close.click();
    await tile.work.closeConfirm.yes.click();

    await expect(tile.root).toHaveAttribute('data-state', 'done');
    await expect(document.root).toHaveAttribute('data-state', 'open');
    await expect(document.title).toHaveText('Where do we pitch?');
    // The closed item waits on nobody; its document waits on the person.
    await expect(projectList.badge(name)).toHaveText('1');
    const items = (await projects.timeline(project)).items.filter((item) => item.kind !== 'opening');
    expect(items.map((item) => [item.id, item.done?.cause ?? null])).toEqual([
      [work, 'cancelled'],
      [pitch, null],
    ]);
  });

  test('is not offered on a failed item, which keeps Resume alone', async ({ people, projects, controller, timeline }) => {
    const { project } = await setUp({ people, projects });
    // The node at its cap refuses the create: the start fails with no environment.
    await controller.capped();
    const failed = await startIn(projects, project, 'failed');
    await controller.capped(false);
    await timeline.open(project);
    const item = timeline.item(failed).work;

    await expect(item.row).toHaveText('Resume');
    await expect(item.close).toHaveCount(0);
  });

  test('stands disabled on the item Archive stopped, as Resume does, until Bring back', async ({ people, projects, timeline, deploymentSse }) => {
    const { project } = await setUp({ people, projects });
    const work = await startIn(projects, project);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;

    await projects.transition(project, 'archived');
    await expect(item.close).toHaveText('Close');
    await expect(item.close).toBeDisabled();

    await projects.transition(project, 'brought_back');
    await expect(item.close).toBeEnabled();
  });
});

test.describe('A work item Pilot closed', () => {
  test('is stopped where it ran and closed in the same act, live: its line under the cancelled mark with Pilot’s reason under its title, the call’s line in the chat its effect', async ({
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Closed'), members: [me.handle!] });
    const work = await startIn(projects, project);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const tile = timeline.item(work);
    await expect(tile.work.running).toBeVisible();

    const { session } = await chats.start(project, 'The other survey takes the print sheets in; drop this one.');
    await controller.play(chats.store, session, [toolUse('toolu_stop', 'mcp__pilot__stop_work', { item: work, reason: REASON })]);
    await chats.stopWork(project, work, { reason: REASON, toolUseId: 'toolu_stop' });

    await expect(tile.root).toHaveAttribute('data-state', 'done');
    await expect(tile.lineKind).toHaveClass('kind-icon cancelled');
    await expect(tile.work.closeNote).toHaveText(REASON);
    await expect(tile.undo).toHaveCount(0);
    await expect(chat.root.getByTestId('chat.tool').last()).toHaveText(`Closed · ${TITLE}`);

    const closed = await projects.item(project, work);
    expect([closed.done?.cause, closed.done?.by?.kind, closed.done?.undo, closed.work?.state, closed.work?.note]).toEqual([
      'cancelled',
      'agent',
      false,
      'stopped',
      REASON,
    ]);
    expect(closed.work?.stopped_by?.kind).toBe('agent');

    await controller.finish(chats.store, session, 'success', 'Closed it.');
    await chats.idle(project);
  });
});
