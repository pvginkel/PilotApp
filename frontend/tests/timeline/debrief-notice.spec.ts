/**
 * The debrief's notice (F26.12, F26.13, F26.14): placed by the server once the pre-ruling pass after
 * the turn of the work item whose debrief completes its subject has ended, never at that work
 * item's done, an open box of its own, the Debrief's notebook and
 * "Notice" in its head, "Debrief · <subject>" its title; per work item it carries, in timeline
 * order, a head with the item's title and the time its turn ended, the stage session's debrief
 * whole as prose, and Full debrief and Session log under it, opening where the work item's Debrief
 * and session log open, on a phone views pushed over the tabs; Read under the whole. Read, it is
 * its line, the title and the time it was read with nothing behind it, and Undo reopens it; it
 * folds and Discuss quotes it as any item; it waits on nobody, left out of the badge and the
 * project's status, while "N open above" counts it until it is read (D186). The work items' lines
 * keep their Debrief (F26.6).
 */

import type { Page } from '@playwright/test';
import type { FormTestEvent } from '@/lib/test/test-events';
import { test, expect } from '../support/fixtures';
import type { Chats } from '../support/chats';
import type { Controller } from '../support/controller';
import { makeUnique, makeUniqueToken, waitTestEvent } from '../support/helpers';
import { fullDebriefAddress } from '../support/page-objects/debrief-page';
import { sessionLogAddress } from '../support/page-objects/session-log-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';

const SUBJECT = 'Slice 058 · The search page';
const PLANNING = 'Planning slice 058 · The search page';
const RUN = 'Running slice 058 · The search page';
const PLANNED = 'A clear slice to plan.\n\nThe **review** asked one question.';
const RAN = 'It went well, if slowly.';
const PHONE = { width: 390, height: 844 };

interface Fixtures {
  people: People;
  projects: Projects;
  controller: Controller;
  /** The job Pilot's server places after each work item's turn runs in the store and ends there. */
  chats: Chats;
}

/**
 * A work item started in the project, done at its turn's end, its session having given `words` as
 * its debrief, about `about`, and the pass after its turn ended, whose end places the notice.
 */
async function debriefed(
  { projects, controller, chats }: Fixtures,
  project: string,
  title: string,
  words: string,
  about: { subject?: string; completes?: boolean },
): Promise<string> {
  const work = await projects.startWork(project, { title, brief: 'Survey the search page.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  const { id: environment } = await projects.environment(project, work);
  await projects.debrief(work, words, undefined, about);
  const passed = await chats.passing(project);
  await controller.finish(environment, 'claude-1');
  await expect.poll(async () => (await projects.item(project, work)).done?.cause).toBe('turn_ended');
  await passed();
  return work;
}

/** The project's debrief's notices, in timeline order. */
async function noticesIn(projects: Projects, project: string): Promise<string[]> {
  return (await projects.timeline(project)).items.filter((item) => item.kind === 'debrief_notice').map((item) => item.id);
}

/**
 * A project whose slice was planned and then run, each work item's debrief about the slice, the
 * planning's not completing it: the end of the run's pass placed one notice carrying both.
 */
async function plannedAndRun(fixtures: Fixtures) {
  const { people, projects } = fixtures;
  const me = await people.signIn();
  const name = makeUnique('Debriefs');
  const project = await projects.make({ name, members: [me.handle!] });
  const planning = await debriefed(fixtures, project, PLANNING, PLANNED, { subject: SUBJECT, completes: false });
  expect(await noticesIn(projects, project)).toEqual([]);
  const run = await debriefed(fixtures, project, RUN, RAN, { subject: SUBJECT });
  const [notice] = await noticesIn(projects, project);
  expect(notice).toBeDefined();
  return { name, project, planning, run, notice };
}

/** A fold's or an unfold's write has settled. */
const settled = (page: Page, form: 'timeline.fold' | 'timeline.unfold') =>
  waitTestEvent<FormTestEvent>(page, 'form', (event) => event.formId === form && event.phase === 'success');

test.describe('The debrief’s notice', () => {
  test('is an open box of its own after the run that completes its subject: the Debrief’s notebook and “Notice” in its head, “Debrief · <subject>” its title, per work item it carries, in timeline order, its title, the time its turn ended, its debrief whole as prose, Full debrief and Session log; Read under the whole; the work items’ lines keep their Debrief', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
  }) => {
    const { project, planning, run, notice } = await plannedAndRun({ people, projects, controller, chats });
    await timeline.open(project);
    const item = timeline.item(notice);

    await expect(item.root).toHaveAttribute('data-kind', 'debrief_notice');
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.root).toHaveClass(/\bopen\b/);
    await expect(item.kind).toHaveText('Notice');
    await expect(item.kind.locator('svg.lucide-notebook-pen')).toBeVisible();
    await expect(item.urgent).toHaveCount(0);
    await expect(item.title).toHaveText(`Debrief · ${SUBJECT}`);
    // Placed last, after the run and the pass whose end placed it.
    const order = await timeline.items.evaluateAll((items) => items.map((each) => each.getAttribute('data-item-id')));
    expect(order.filter((id) => [planning, run, notice].includes(id!))).toEqual([planning, run, notice]);
    expect(order.at(-1)).toBe(notice);

    await expect(item.debriefs).toHaveCount(2);
    expect(await item.debriefs.evaluateAll((each) => each.map((carried) => carried.getAttribute('data-item-id')))).toEqual([planning, run]);
    for (const [work, title, paragraphs] of [
      [planning, PLANNING, ['A clear slice to plan.', 'The review asked one question.']],
      [run, RUN, [RAN]],
    ] as const) {
      const carried = item.carried(work);
      const done = (await projects.item(project, work)).done!;
      await expect(carried.title).toHaveText(title);
      await expect(carried.ended).toHaveAttribute('datetime', done.at);
      await expect(carried.ended).toHaveText(await timeline.item(work).lineTime.innerText());
      await expect(carried.text.locator('p')).toHaveText([...paragraphs]);
      await expect(carried.full).toHaveText('Full debrief');
      await expect(carried.full).toHaveAttribute('href', fullDebriefAddress(project, work));
      await expect(carried.sessionLog).toHaveText('Session log');
      await expect(carried.sessionLog).toHaveAttribute('href', sessionLogAddress(project, work));
      // The work item's own line keeps its Debrief.
      await expect(timeline.item(work).root).toHaveAttribute('data-state', 'done');
      await expect(timeline.item(work).debrief).toBeVisible();
    }
    await expect(item.carried(planning).text.locator('strong')).toHaveText('review');

    // Read under the whole, after the last work item it carries.
    await expect(item.read).toHaveText('Read');
    const [last, read] = await Promise.all([item.carried(run).root.boundingBox(), item.read.boundingBox()]);
    expect(read!.y).toBeGreaterThan(last!.y + last!.height);
  });

  test('is placed once the pass after the run’s turn has ended, never at the run’s done: the page shows it then, with no reload', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Passing'), members: [me.handle!] });
    const work = await projects.startWork(project, { title: RUN, brief: 'Survey the search page.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
    const { id: environment } = await projects.environment(project, work);
    await projects.debrief(work, RAN, undefined, { subject: SUBJECT });
    const pass = await chats.pass(project);
    await controller.finish(environment, 'claude-1');
    await expect.poll(async () => (await projects.item(project, work)).done?.cause).toBe('turn_ended');

    // The run is done and its pass at work: no notice yet.
    await pass.running();
    expect(await noticesIn(projects, project)).toEqual([]);
    await timeline.open(project);
    await expect(timeline.item(work).root).toHaveAttribute('data-state', 'done');
    await expect(timeline.root.locator('[data-kind="debrief_notice"]')).toHaveCount(0);

    await pass.end();
    const [notice] = await noticesIn(projects, project);
    await expect(timeline.item(notice).title).toHaveText(`Debrief · ${SUBJECT}`);
    await expect(timeline.item(notice).debriefs).toHaveCount(1);
    expect(await timeline.items.last().getAttribute('data-item-id')).toBe(notice);
  });

  test('gives the time a work item it carries ended with its date once that is an earlier day, as a wait’s Since does', async ({
    page,
    people,
    projects,
    controller,
    chats,
    timeline,
  }) => {
    const { project, planning, run, notice } = await plannedAndRun({ people, projects, controller, chats });
    const ended = await Promise.all([planning, run].map(async (work) => (await projects.item(project, work)).done!.at));

    // The page opened on the day after the run's turn ended.
    await page.clock.install({ time: new Date(Date.parse(ended[1]) + 24 * 60 * 60_000) });
    await timeline.open(project);
    const item = timeline.item(notice);

    for (const [work, at] of [
      [planning, ended[0]],
      [run, ended[1]],
    ] as const) {
      const dated = await page.evaluate(
        (at) => new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(at)),
        at,
      );
      await expect(item.carried(work).ended).toHaveAttribute('datetime', at);
      await expect(item.carried(work).ended).toHaveText(dated);
    }
  });

  test('a debrief that names no subject gets a notice of its own, titled with its work item’s title', async ({ people, projects, controller, chats, timeline }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Unnamed'), members: [me.handle!] });
    const work = await debriefed({ people, projects, controller, chats }, project, 'Surveying the stylesheets', RAN, {});
    const [notice] = await noticesIn(projects, project);
    await timeline.open(project);
    const item = timeline.item(notice);

    await expect(item.title).toHaveText('Debrief · Surveying the stylesheets');
    await expect(item.debriefs).toHaveCount(1);
    await expect(item.carried(work).title).toHaveText('Surveying the stylesheets');
  });

  test('Full debrief opens the work item’s full debrief and Session log its session log, where its Debrief and its line open them; Esc gives the focus back', async ({
    page,
    people,
    projects,
    controller,
    chats,
    timeline,
    debrief,
    sessionLog,
  }) => {
    const { project, planning, run, notice } = await plannedAndRun({ people, projects, controller, chats });
    await timeline.open(project);
    const item = timeline.item(notice);

    await item.carried(run).full.click();
    await expect(page).toHaveURL(fullDebriefAddress(project, run));
    await expect(debrief.title).toHaveText('Full debrief');
    await expect(debrief.item).toHaveText(RUN);
    await expect(debrief.rows).toHaveCount(1);
    await page.keyboard.press('Escape');
    await expect(debrief.overlay).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(project));
    await expect(item.carried(run).full).toBeFocused();

    await item.carried(planning).sessionLog.click();
    await expect(page).toHaveURL(sessionLogAddress(project, planning));
    await expect(sessionLog.item).toHaveText(PLANNING);
    await page.keyboard.press('Escape');
    await expect(sessionLog.overlay).toHaveCount(0);
    await expect(item.carried(planning).sessionLog).toBeFocused();
  });

  test('Read closes it to its line, its title and the time it was read with nothing behind it, Undo and Discuss under the mouse; Undo reopens it', async ({
    page,
    people,
    projects,
    controller,
    chats,
    timeline,
  }) => {
    const { project, notice } = await plannedAndRun({ people, projects, controller, chats });
    await timeline.open(project);
    const item = timeline.item(notice);

    await item.read.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineTitle).toHaveText(`Debrief · ${SUBJECT}`);
    await expect(item.lineTitle).not.toHaveAttribute('href');
    await expect(item.lineKind.locator('svg.lucide-notebook-pen')).toBeVisible();
    const done = (await projects.item(project, notice)).done!;
    expect(done.cause).toBe('marked');
    await expect(item.lineTime).toHaveAttribute('datetime', done.at);
    await expect(item.debriefs).toHaveCount(0);
    await item.line.hover();
    await expect(item.open).toHaveCount(0);
    await expect(item.undo).toBeVisible();
    await expect(item.lineDiscuss).toBeVisible();
    // A click on its title opens nothing.
    await item.lineTitle.click();
    await expect(page).toHaveURL(projectAddress(project));

    await item.undo.click();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.debriefs).toHaveCount(2);
    await expect(item.read).toBeEnabled();
  });

  test('folds as any open item, and Discuss quotes it by its title', async ({ page, people, projects, controller, chats, timeline, chat }) => {
    const { project, notice } = await plannedAndRun({ people, projects, controller, chats });
    await timeline.open(project);
    const item = timeline.item(notice);

    await expect(item.kind).toHaveAttribute('title', 'Fold, for everyone');
    const folding = settled(page, 'timeline.fold');
    await item.kind.click();
    await folding;
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    await expect(item.fold).toHaveAttribute('inert', '');
    const unfolding = settled(page, 'timeline.unfold');
    await item.root.click();
    await unfolding;
    await expect(item.root).toHaveAttribute('data-folded', 'false');

    await item.discuss.click();
    await expect(chat.quote).toHaveAttribute('data-quote', `item ${notice}`);
    await expect(chat.quoteLabel).toHaveText(`Debrief · ${SUBJECT}`);
  });

  test.describe('in a short window', () => {
    test.use({ viewport: { width: 1280, height: 600 } });

    test('waits on nobody: the badge and the project’s status leave it out, while “N open above” counts it until it is read', async ({
      people,
      projects,
      controller,
      timeline,
      projectList,
      waits,
      chats,
    }) => {
      const { name, project, notice } = await plannedAndRun({ people, projects, controller, chats });
      // Idle: no plan, nothing running and nothing waiting on anyone.
      expect((await projects.list()).find((tab) => tab.name === name)!.status).toBe('idle');
      // Waits Pilot closed after it, done lines, put it out of view above.
      const key = `W${makeUniqueToken(6).toUpperCase()}`;
      for (let index = 0; index < 14; index += 1) {
        const wait = await waits.add(project, { kind: 'card_wait', title: `Card ${index + 1} is done`, cards: [`${key}-${index + 1}`], states: ['Done'] });
        await waits.close(wait, 'Done.');
      }
      await timeline.open(project);
      await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
      const item = timeline.item(notice);

      await expect(projectList.statusIcon(name).root).toHaveAttribute('data-status', 'idle');
      await expect(projectList.badge(name)).toHaveCount(0);
      await expect(item.root).toHaveAttribute('data-actionable', 'true');
      await expect(item.root).not.toBeInViewport();
      await expect(timeline.openAbove).toHaveText('1 open above');

      await timeline.openAbove.click();
      await expect(item.root).toBeInViewport();
      await item.read.click();
      await expect(item.root).toHaveAttribute('data-state', 'done');
      await expect(item.root).toHaveAttribute('data-actionable', 'false');
      await timeline.root.evaluate((feed) => feed.scrollTo({ top: feed.scrollHeight }));
      await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
      await expect(item.root).not.toBeInViewport();
      await expect(timeline.openAbove).toHaveCount(0);
      await expect(projectList.statusIcon(name).root).toHaveAttribute('data-status', 'idle');
    });
  });
});

test.describe('The debrief’s notice on a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('is the same box; Full debrief and Session log push their views over the tabs, and Back takes each off', async ({
    page,
    people,
    projects,
    controller,
    chats,
    timeline,
    debrief,
    sessionLog,
    projectHead,
    phoneTabs,
  }) => {
    const { project, planning, run, notice } = await plannedAndRun({ people, projects, controller, chats });
    await timeline.open(project);
    const item = timeline.item(notice);

    await expect(item.kind).toHaveText('Notice');
    await expect(item.title).toHaveText(`Debrief · ${SUBJECT}`);
    await expect(item.debriefs).toHaveCount(2);
    await expect(item.read).toBeVisible();
    // Within the screen's width.
    const box = (await item.root.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(PHONE.width);

    await item.carried(run).full.tap();
    await expect(page).toHaveURL(fullDebriefAddress(project, run));
    await expect(debrief.title).toHaveText('Full debrief');
    await expect(debrief.item).toHaveText(RUN);
    const [view, head, tabs] = await Promise.all([debrief.overlay, projectHead.root, phoneTabs.root].map(async (each) => (await each.boundingBox())!));
    expect(view).toMatchObject({ x: 0, y: head.y, width: PHONE.width });
    expect(view.y + view.height).toBe(tabs.y + tabs.height);
    await debrief.back.tap();
    await expect(debrief.overlay).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(project));

    await item.carried(planning).sessionLog.tap();
    await expect(page).toHaveURL(sessionLogAddress(project, planning));
    await expect(sessionLog.item).toHaveText(PLANNING);
    await sessionLog.overlay.getByTestId('overlay.back').tap();
    await expect(sessionLog.overlay).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(project));
  });

  test('read, its line keeps Undo alone among its actions, and a tap on it opens the menu of its Discuss, nothing being behind it; Undo reopens it', async ({
    page,
    people,
    projects,
    controller,
    chats,
    timeline,
    overlay,
  }) => {
    const { project, notice } = await plannedAndRun({ people, projects, controller, chats });
    await timeline.open(project);
    const item = timeline.item(notice);

    await item.read.tap();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.undo).toBeVisible();
    await expect(item.open).toHaveCount(0);
    await expect(item.lineDiscuss).toHaveCount(0);
    await item.lineTitle.tap();
    await expect(item.lineMenu.getByRole('menuitem')).toHaveText(['Discuss']);
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(project));
    await item.lineTitle.tap();
    await expect(item.lineMenu).toHaveCount(0);

    await item.undo.tap();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.read).toBeVisible();
  });
});

