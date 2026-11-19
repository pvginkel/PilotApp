/**
 * The debrief's notice (F26.12, F26.13, F26.14): placed by the server once the pre-ruling pass after
 * the turn of the work item whose debrief completes its subject has ended, never at that work
 * item's done, an open box of its own, the Debrief's notebook and
 * "Notice" in its head, "Debrief · <subject>" its title; then each work item it carries, in
 * timeline order, its title and the time its stage took (F26.17); then Pilot's notable events as
 * Markdown, where the pass wrote any (F52.4); then Details, closed whenever the box is first drawn,
 * holding per work item a head with the item's title and the time its turn ended, the stage
 * session's debrief whole as prose, and Full debrief and Session log under it, opening where the
 * work item's Debrief and session log open, on a phone views pushed over the tabs; Read under the
 * whole. Read, it is
 * its line, the title and the time it was read with nothing behind it, and Undo reopens it; it
 * folds and Discuss quotes it as any item; it waits on nobody, left out of the badge and the
 * project's status, while "N open above" counts it until it is read (D186). The work items' lines
 * keep their Debrief (F26.6).
 */

import type { Locator, Page } from '@playwright/test';
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
const NOTABLE = 'The phone’s layout cost a round **again**, as it did in slice 057.\n\n- The review sent the page back once.\n- The plan left the layout open.';
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

/** A CSS length of an element as the page computed it, in pixels. */
const pixels = (locator: Locator, property: 'fontSize' | 'borderLeftWidth' | 'paddingLeft') =>
  locator.evaluate((element, property) => parseFloat(getComputedStyle(element)[property]), property);

/** A fold's or an unfold's write has settled. */
const settled = (page: Page, form: 'timeline.fold' | 'timeline.unfold') =>
  waitTestEvent<FormTestEvent>(page, 'form', (event) => event.formId === form && event.phase === 'success');

test.describe('The debrief’s notice', () => {
  test('is an open box of its own after the run that completes its subject: the Debrief’s notebook and “Notice” in its head, “Debrief · <subject>” its title, then each work item it carries, in timeline order, with the time its stage took, and Details, closed, right under them where Pilot wrote no lines; Details opens, per work item, its title, the time its turn ended, its debrief whole as prose, Full debrief and Session log, and Less closes them; Read under the whole; the work items’ lines keep their Debrief', async ({
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

    // The box opens with the work items it carries, each with its stage's time.
    await expect(item.stages).toHaveCount(2);
    expect(await item.stages.evaluateAll((each) => each.map((stage) => stage.getAttribute('data-item-id')))).toEqual([planning, run]);
    await expect(item.stage(planning).title).toHaveText(PLANNING);
    await expect(item.stage(run).title).toHaveText(RUN);
    for (const work of [planning, run]) {
      // A spec's turn ends within seconds.
      expect((await projects.item(project, notice)).debriefs!.find((each) => each.id === work)!.stage_time).toBeLessThan(60);
      await expect(item.stage(work).time).toHaveText('<1m');
    }
    const [title, stages] = await Promise.all([item.title.boundingBox(), item.stage(planning).root.locator('span').first().boundingBox()]);
    expect(stages!.y).toBeGreaterThanOrEqual(title!.y + title!.height);

    // Pilot wrote no lines: Details stands right under the times, closed.
    await expect(item.notable).toHaveCount(0);
    await expect(item.debriefDetails).toHaveText('Details');
    await expect(item.debriefDetails).toHaveAttribute('aria-expanded', 'false');
    await expect(item.debriefDetails.locator('svg.lucide-chevron-down')).toBeVisible();
    await expect(item.debriefs).toHaveCount(0);
    const [lastStage, details] = await Promise.all([item.stage(run).time.boundingBox(), item.debriefDetails.boundingBox()]);
    expect(details!.y).toBeGreaterThanOrEqual(lastStage!.y + lastStage!.height);
    expect(details!.y - (lastStage!.y + lastStage!.height)).toBeLessThan(12);

    await item.debriefDetails.click();
    await expect(item.debriefDetails).toHaveText('Less');
    await expect(item.debriefDetails).toHaveAttribute('aria-expanded', 'true');
    await expect(item.debriefDetails.locator('svg.lucide-chevron-up')).toBeVisible();
    await expect(item.debriefs).toHaveCount(2);
    expect(await item.debriefs.evaluateAll((each) => each.map((carried) => carried.getAttribute('data-item-id')))).toEqual([planning, run]);
    // The times stay above what Details holds.
    await expect(item.stages).toHaveCount(2);
    const first = await item.carried(planning).root.boundingBox();
    expect(first!.y).toBeGreaterThan(details!.y);
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

    await item.debriefDetails.click();
    await expect(item.debriefDetails).toHaveText('Details');
    await expect(item.debriefs).toHaveCount(0);
    await expect(item.stages).toHaveCount(2);
    await expect(item.read).toBeVisible();
  });

  test('shows Pilot’s notable events as Markdown between the times and Details, each carried work item’s in timeline order, and lines the pass writes later show in it with no reload', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
  }) => {
    const { project, planning, run, notice } = await plannedAndRun({ people, projects, controller, chats });
    await timeline.open(project);
    const item = timeline.item(notice);
    await expect(item.stages).toHaveCount(2);
    await expect(item.notable).toHaveCount(0);

    // A Retry of the pass writes its lines on a notice placed already.
    await projects.writeNotable(run, NOTABLE);
    await expect(item.notable.locator('p')).toHaveText('The phone’s layout cost a round again, as it did in slice 057.');
    await expect(item.notable.locator('strong')).toHaveText('again');
    await expect(item.notable.locator('li')).toHaveText(['The review sent the page back once.', 'The plan left the layout open.']);
    // Between the times and Details, which stays closed and holds none of them.
    const [stage, lines, details] = await Promise.all([item.stage(run).time.boundingBox(), item.notable.boundingBox(), item.debriefDetails.boundingBox()]);
    expect(lines!.y).toBeGreaterThanOrEqual(stage!.y + stage!.height);
    expect(details!.y).toBeGreaterThanOrEqual(lines!.y + lines!.height);
    await expect(item.debriefDetails).toHaveAttribute('aria-expanded', 'false');
    await expect(item.debriefs).toHaveCount(0);
    await item.debriefDetails.click();
    await expect(item.debriefs).toHaveCount(2);
    await expect(item.debriefs.getByText('The review sent the page back once.')).toHaveCount(0);
    await expect(item.notable.locator('li')).toHaveCount(2);

    // Lines written again replace the ones that stood there; the planning's come first.
    await projects.writeNotable(run, 'The run stopped for the first time.');
    await expect(item.notable.locator('p')).toHaveText('The run stopped for the first time.');
    await projects.writeNotable(planning, 'The planning took three rounds.');
    await expect(item.notable.locator('p')).toHaveText(['The planning took three rounds.', 'The run stopped for the first time.']);
  });

  test('Details is closed whenever the box is drawn anew, whether it is open the page’s own: open, it is closed after a reload', async ({
    page,
    people,
    projects,
    controller,
    chats,
    timeline,
  }) => {
    const { project, run, notice } = await plannedAndRun({ people, projects, controller, chats });
    await projects.writeNotable(run, NOTABLE);
    await timeline.open(project);
    const item = timeline.item(notice);

    await expect(item.debriefDetails).toHaveAttribute('aria-expanded', 'false');
    await item.debriefDetails.click();
    await expect(item.debriefs).toHaveCount(2);
    // A live read of the timeline leaves it as the person set it.
    await projects.writeNotable(run, 'The run stopped for the first time.');
    await expect(item.notable.locator('p')).toHaveText('The run stopped for the first time.');
    await expect(item.debriefs).toHaveCount(2);

    await page.reload();
    await expect(item.stages).toHaveCount(2);
    await expect(item.debriefDetails).toHaveText('Details');
    await expect(item.debriefDetails).toHaveAttribute('aria-expanded', 'false');
    await expect(item.debriefs).toHaveCount(0);
  });

  test('under Details no line stands left of a work item’s part, and its title line is sized between the body’s text and the box’s title', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
  }) => {
    const { project, planning, run, notice } = await plannedAndRun({ people, projects, controller, chats });
    await timeline.open(project);
    const item = timeline.item(notice);
    await item.debriefDetails.click();

    for (const work of [planning, run]) {
      const carried = item.carried(work);
      expect(await pixels(carried.root, 'borderLeftWidth')).toBe(0);
      expect(await pixels(carried.root, 'paddingLeft')).toBe(0);
      // Its text starts where the box's title does.
      const [title, head, text] = await Promise.all([item.title.boundingBox(), carried.title.boundingBox(), carried.text.boundingBox()]);
      expect(head!.x).toBe(title!.x);
      expect(text!.x).toBe(title!.x);
      const [body, line, time, box] = await Promise.all([
        pixels(carried.text.locator('p').first(), 'fontSize'),
        pixels(carried.title, 'fontSize'),
        pixels(carried.ended, 'fontSize'),
        pixels(item.title, 'fontSize'),
      ]);
      expect(line).toBeGreaterThan(body);
      expect(line).toBeLessThan(box);
      expect(time).toBe(line);
    }
  });

  test('gives a stage’s time as the full debrief gives one, in minutes, and in hours and minutes from an hour on: the seed’s notice', async ({
    people,
    projects,
    timeline,
  }) => {
    await people.signIn();
    const recipes = await projects.seeded('Recipe box');
    const notice = (await projects.timeline(recipes)).items.find((each) => each.kind === 'debrief_notice')!;
    expect(notice.debriefs!.map((each) => each.stage_time)).toEqual([1380, 6000]);
    await timeline.open(recipes);
    const item = timeline.item(notice.id);

    await expect(item.stages.getByTestId('timeline.debrief.stage.title')).toHaveText(['Planning the recipe card page', 'Building the recipe card page']);
    await expect(item.stages.getByTestId('timeline.debrief.stage.time')).toHaveText(['23m', '1h 40m']);
    // Pilot's lines on its run.
    await expect(item.notable.locator('strong')).toHaveText('Second slice in a row');
    await expect(item.notable.locator('li')).toHaveCount(2);
  });

  test('is placed once the pass after the run’s turn has ended, never at the run’s done: the page shows it then, with no reload, the lines the pass wrote in it', async ({
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
    // The pass's lines show nowhere before its end.
    await projects.writeNotable(work, NOTABLE);
    expect(await noticesIn(projects, project)).toEqual([]);
    await expect(timeline.root.locator('[data-kind="debrief_notice"]')).toHaveCount(0);

    await pass.end();
    const [notice] = await noticesIn(projects, project);
    await expect(timeline.item(notice).title).toHaveText(`Debrief · ${SUBJECT}`);
    await expect(timeline.item(notice).stages).toHaveCount(1);
    await expect(timeline.item(notice).stage(work).title).toHaveText(RUN);
    await expect(timeline.item(notice).notable.locator('strong')).toHaveText('again');
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
    await item.debriefDetails.click();

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
    await expect(item.stages).toHaveCount(1);
    await expect(item.stage(work).title).toHaveText('Surveying the stylesheets');
    await item.debriefDetails.click();
    await expect(item.debriefs).toHaveCount(1);
    await expect(item.carried(work).title).toHaveText('Surveying the stylesheets');
  });

  test('under Details, Full debrief opens the work item’s full debrief and Session log its session log, where its Debrief and its line open them; Esc gives the focus back, Details open as it was', async ({
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
    await item.debriefDetails.click();

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

  test('Read closes it to its line, its title and the time it was read with nothing behind it, Undo and Discuss under the mouse; Undo reopens it, its Details closed', async ({
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
    await item.debriefDetails.click();
    await expect(item.debriefs).toHaveCount(2);

    await item.read.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineTitle).toHaveText(`Debrief · ${SUBJECT}`);
    await expect(item.lineTitle).not.toHaveAttribute('href');
    await expect(item.lineKind.locator('svg.lucide-notebook-pen')).toBeVisible();
    const done = (await projects.item(project, notice)).done!;
    expect(done.cause).toBe('marked');
    await expect(item.lineTime).toHaveAttribute('datetime', done.at);
    await expect(item.stages).toHaveCount(0);
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
    await expect(item.stages).toHaveCount(2);
    await expect(item.debriefDetails).toHaveAttribute('aria-expanded', 'false');
    await expect(item.debriefs).toHaveCount(0);
    await expect(item.read).toBeEnabled();
  });

  test('folds as any open item, and Discuss quotes it, Pilot’s lines in it, as any item, by its id under its title', async ({
    page,
    people,
    projects,
    controller,
    chats,
    timeline,
    chat,
  }) => {
    const { project, run, notice } = await plannedAndRun({ people, projects, controller, chats });
    await projects.writeNotable(run, NOTABLE);
    await timeline.open(project);
    const item = timeline.item(notice);

    await expect(item.kind).toHaveAttribute('title', 'Fold, for everyone');
    const folding = settled(page, 'timeline.fold');
    await item.kind.click();
    await folding;
    await expect(item.root).toHaveAttribute('data-folded', 'true');
    await expect(item.fold).toHaveAttribute('inert', '');
    await expect(item.debriefDetails).toHaveAttribute('aria-expanded', 'false');
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

  test('is the same box, the times, Pilot’s lines and Details; under it no line left of a work item’s part, its title line between the body’s text and the box’s title; Full debrief and Session log push their views over the tabs, and Back takes each off', async ({
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
    await projects.writeNotable(run, NOTABLE);
    await timeline.open(project);
    const item = timeline.item(notice);

    await expect(item.kind).toHaveText('Notice');
    await expect(item.title).toHaveText(`Debrief · ${SUBJECT}`);
    await expect(item.stages).toHaveCount(2);
    await expect(item.stage(run).title).toHaveText(RUN);
    await expect(item.stage(run).time).toHaveText('<1m');
    await expect(item.notable.locator('li')).toHaveCount(2);
    await expect(item.debriefDetails).toHaveText('Details');
    await expect(item.debriefs).toHaveCount(0);
    await item.debriefDetails.tap();
    await expect(item.debriefDetails).toHaveText('Less');
    await expect(item.debriefs).toHaveCount(2);
    await expect(item.read).toBeVisible();
    // Within the screen's width, a stage's time whole beside its title.
    const box = (await item.root.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(PHONE.width);
    const time = (await item.stage(run).time.boundingBox())!;
    expect(time.x + time.width).toBeLessThanOrEqual(box.x + box.width);
    const carried = item.carried(run);
    expect(await pixels(carried.root, 'borderLeftWidth')).toBe(0);
    expect(await pixels(carried.root, 'paddingLeft')).toBe(0);
    const [body, line, title] = await Promise.all([
      pixels(carried.text.locator('p').first(), 'fontSize'),
      pixels(carried.title, 'fontSize'),
      pixels(item.title, 'fontSize'),
    ]);
    expect(line).toBeGreaterThan(body);
    expect(line).toBeLessThan(title);

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

