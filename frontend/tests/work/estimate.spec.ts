/**
 * The time a running work item still takes, as its badge (F156.7, F156.8): a clock and the time
 * left as the server rounds it, "20 min", "1 h", "3 h", with no tilde, alone after a running work
 * item's time and right after the project's name in its head, never on the top bar. Longer than
 * usual it is the alert, red with the clock's alert: an em dash where the time stood once the
 * running step has outrun every past one of its kind; the time left on a step the workflow marked;
 * the icon alone on such a step where the work item has no estimate. Every badge, at rest or red,
 * opens its figures (F156.13) on hover off a phone and on a press, closed by Esc, a press elsewhere
 * or the badge: a red badge's sentence first (F156.14), naming the work item in the head and "It"
 * on the work item, the marked one on a step its run marks, outrun or not; else in the head the
 * work item's title; then *So far*, *Normal* and *Slow* for each running step by its kind and for
 * the run, as the server gives them, and under them each step's longest; a badge at rest with no
 * row to show opens nothing. A step's move reaches the work item's badge through the live event,
 * with no read of the timeline, and the head's follows it; nothing shows, and nothing in its place,
 * where the server gives no estimate, or once the work item stops. While a badge shows, the page
 * reads the estimates again each minute. Where the head's row would cut it, the badge stands on a
 * line of its own under it, as it always does on a phone, where the head's badge stands after the
 * name in its one line, the figures span the page under the head and under a work item's badge,
 * and the Plan tab shows none.
 *
 * Each test's steps are of a kind of its own: a kind's timings count across every project, and a
 * worker's specs share one database.
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { ProgressStep, Projects } from '../support/projects';
import type { etaPopParts } from '../support/page-objects/timeline-page';

const TITLE = 'Running slice 049';
const PHONE = { width: 390, height: 844 };
const WIDE = { width: 1800, height: 800 };
const MINUTE = 60_000;

interface Fixtures {
  people: People;
  projects: Projects;
}

/** A kind's timings, each `seconds` long, left before the run under test begins. */
interface Priced {
  kind: string;
  seconds: number;
}

/**
 * A project, signed in as its member, and a work item running in it; the kinds `priced` names
 * timed first by a work item of another project, so that the run's prices stand at its start.
 */
async function running({ people, projects }: Fixtures, priced: Priced[] = []): Promise<{ project: string; work: string }> {
  const me = await people.signIn();
  if (priced.length > 0) {
    const elsewhere = await projects.make({ name: makeUnique('Timed'), members: [me.handle!] });
    const timed = await projects.startWork(elsewhere, { title: 'Timed', brief: 'Time the kinds.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(elsewhere, timed)).state).toBe('running');
    const list = priced.flatMap(({ kind }, index) => Array.from({ length: 5 }, (_, number) => step(`timed-${index}-${number + 1}`, kind)));
    await projects.setProgress(timed, list);
    await projects.setProgress(
      timed,
      list.map((done) => ({ ...done, state: 'done', duration: priced.find(({ kind }) => kind === done.kind)!.seconds })),
    );
  }
  const project = await projects.make({ name: makeUnique('Estimate'), members: [me.handle!] });
  const work = await projects.startWork(project, { title: TITLE, brief: 'Run the slice.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  return { project, work };
}

const step = (code: string, kind: string, more: Partial<ProgressStep> = {}): ProgressStep => ({ code, label: `Step ${code}`, kind, ...more });

interface Published {
  /** The kind of every step. */
  kind: string;
  /** The steps that went done before the one that runs, and the seconds each took. */
  past?: number;
  seconds?: number;
  /** The steps not begun after it. */
  ahead?: number;
  /** The running step carries the workflow's mark. */
  marked?: boolean;
  /** What every step's code begins with: a second list of one work item names its steps anew, a code keeping its state and its one timing. */
  tag?: string;
}

/** The list of a run under way: `past` done steps, the one that runs, `ahead` not begun. */
function listOf({ kind, past = 5, seconds = 600, ahead = 0, marked = false, tag = '' }: Published): ProgressStep[] {
  return [
    ...Array.from({ length: past }, (_, number) => step(`${tag}past-${number + 1}`, kind, { state: 'done', duration: seconds })),
    step(`${tag}running`, kind, { state: 'active', ...(marked ? { marked: true } : {}) }),
    ...Array.from({ length: ahead }, (_, number) => step(`${tag}ahead-${number + 1}`, kind)),
  ];
}

/**
 * Publishes the work item's list as a run does, every step listed ahead: first all of them not
 * begun, then in the states `list` gives them.
 */
async function publishList(projects: Projects, work: string, list: ProgressStep[]): Promise<void> {
  await projects.setProgress(
    work,
    list.map(({ code, label, kind }) => ({ code, label, kind })),
  );
  await projects.setProgress(work, list);
}

/** `publishList` of `listOf`: the past steps done in `seconds` each, which leaves the kind their timings, and one running. */
const publish = (projects: Projects, work: string, published: Published) => publishList(projects, work, listOf(published));

type EtaPop = ReturnType<typeof etaPopParts>;

/** A row of the figures as its cells read: its name, *So far*, *Normal* and *Slow*. */
const cells = (row: Locator) => row.locator('th, td');
const redLine = (minutes: string, kind: string, timings: number) => `Red past ${minutes}: no ${kind} step of the last ${timings} ran longer.`;
/** What the pop holds, in order, by the class of each part: the sentence, the title, the table, the lines under it. */
const partsOf = (pop: EtaPop) => pop.root.evaluate((root) => Array.from(root.children, (part) => part.className));

const box = async (locator: Locator) => (await locator.boundingBox())!;
// eslint-disable-next-line no-restricted-properties -- the page's clock, a real timestamp
const pageNow = (page: Page) => page.evaluate(() => Date.now());
const OUTRUN = /^It has run \d+ min, longer than such work usually takes: it may be stuck\.$/;
const outrunOf = (title: string) => new RegExp(`^${title} has run \\d+ min, longer than such work usually takes: it may be stuck\\.$`);
const MARKED = /^It has run \d+ min, and its run marks this step as in trouble: it may be stuck\.$/;
const markedOf = (title: string) => new RegExp(`^${title} has run \\d+ min, and its run marks this step as in trouble: it may be stuck\\.$`);

test.describe('The time a running work item still takes', () => {
  test('shows after the running time as a clock and the time left, alone, with no tilde, and right after the project’s name, never on the top bar; at rest with no row to show it has no hover and no press; it moves with the list through the live event alone, and goes once the work item stops', async ({
    page,
    people,
    projects,
    timeline,
    projectHead,
    shell,
    deploymentSse,
  }) => {
    const { project, work } = await running({ people, projects });
    const kind = makeUnique('code-writer');
    // A window wide enough for the work item's head to hold the badge in its row.
    await page.setViewportSize(WIDE);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work);
    await expect(item.work.running).toBeVisible();
    await expect(item.work.eta).toHaveCount(0);
    await expect(projectHead.eta).toHaveCount(0);
    let reads = 0;
    page.on('request', (request) => {
      if (request.url().includes(`/api/projects/${project}/timeline`)) reads += 1;
    });

    // Fewer than five timings of the kind: no estimate, and nothing in its place.
    await publish(projects, work, { kind, past: 4, ahead: 1 });
    await expect(item.work.progress).toBeVisible();
    await expect(item.work.eta).toHaveCount(0);

    // The fifth, with no step running: the two not begun at ten minutes each, and no row to show,
    // the kind having had no timing when the run began.
    await projects.setProgress(work, [
      ...listOf({ kind, past: 4 }).slice(0, 4),
      step('running', kind, { state: 'done', duration: 600 }),
      step('ahead-1', kind),
      step('ahead-2', kind),
    ]);
    await expect(item.work.eta).toHaveText('20 min');
    await expect(item.work.eta).toHaveAttribute('role', 'img');
    await expect(item.work.eta).toHaveAccessibleName('20 min left');
    await expect(item.work.eta.locator('svg')).toHaveClass(/lucide-clock/);
    await expect(item.work.eta.locator('svg')).not.toHaveClass(/lucide-clock-alert/);
    await expect(item.work.eta).not.toHaveClass(/long/);
    await expect(projectHead.eta).toHaveText('20 min');
    await expect(projectHead.eta).toHaveAttribute('role', 'img');
    await expect(shell.topBar.locator('.eta-badge')).toHaveCount(0);

    // After the running time, in the head's row, before Session log, nothing after it.
    const [head, time, eta, log] = await Promise.all([item.head, item.work.running, item.work.eta, item.work.sessionLog].map(box));
    expect(head.height).toBeLessThan(40);
    expect(eta.x).toBeGreaterThanOrEqual(time.x + time.width);
    expect(log.x).toBeGreaterThanOrEqual(eta.x + eta.width);
    expect(await item.work.eta.evaluate((badge) => badge.closest('.work-eta')!.childElementCount)).toBe(1);
    expect(eta.height).toBe(22);
    // In the project's head, right after its name.
    expect(await projectHead.name.evaluate((name) => name.nextElementSibling!.querySelector('[data-testid="project.eta"]') !== null)).toBe(true);
    expect((await box(projectHead.eta)).height).toBe(22);

    // No row to show: nothing opens, on hover or on a press.
    await item.work.eta.hover();
    await expect(item.work.etaPop.root).toHaveCount(0);
    await item.work.eta.click();
    await expect(item.work.etaPop.root).toHaveCount(0);
    await projectHead.eta.hover();
    await expect(projectHead.etaPop.root).toHaveCount(0);

    // To 89 minutes an hour, from 90 the nearest hour.
    const more = (ahead: number) => [
      ...listOf({ kind, past: 4 }).slice(0, 4),
      step('running', kind, { state: 'done' }),
      step('ahead-1', kind, { state: 'active' }),
      ...Array.from({ length: ahead }, (_, number) => step(`ahead-${number + 2}`, kind)),
    ];
    await projects.setProgress(work, more(5));
    await expect(item.work.eta).toHaveText('1 h');
    await expect(projectHead.eta).toHaveText('1 h');
    await projects.setProgress(work, more(17));
    await expect(item.work.eta).toHaveText('3 h');
    await expect(item.work.eta).toHaveAccessibleName('3 h left');
    await expect(projectHead.eta).toHaveText('3 h');
    expect(reads).toBe(0);

    // Stopped, it runs no more: no badge, and nothing in its place.
    await projects.stop(work);
    await expect(item.work.resume).toBeVisible();
    await expect(item.work.eta).toHaveCount(0);
    await expect(projectHead.eta).toHaveCount(0);
  });

  test('opens its figures at rest, on hover and on a press, closed by Esc, a press elsewhere and the badge: in the head the work item’s title first, then So far, Normal and Slow for each running step by its kind and for the run, in minutes under an hour and hours and minutes from one, and each step’s longest under them; inside the timeline', async ({
    page,
    people,
    projects,
    timeline,
    projectHead,
    deploymentSse,
  }) => {
    const kind = makeUnique('code-writer');
    const other = makeUnique('code-reviewer');
    const { project, work } = await running({ people, projects }, [
      { kind, seconds: 600 },
      { kind: other, seconds: 300 },
    ]);
    await page.setViewportSize(WIDE);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work);
    // Five steps done at ten minutes each, the sixth running, the seventh not begun.
    await publish(projects, work, { kind, ahead: 1 });
    await expect(item.work.eta).toHaveText('20 min');

    for (const [eta, pop] of [
      [item.work.eta, item.work.etaPop],
      [projectHead.eta, projectHead.etaPop],
    ] as const) {
      await expect(eta).toHaveRole('button');
      await expect(eta).toHaveAccessibleName('20 min left');
      await expect(eta).toHaveAttribute('aria-expanded', 'false');
      await expect(eta).not.toHaveClass(/long/);
      await expect(pop.root).toBeHidden();
      await expect(pop.says).toHaveCount(0);
      await expect(cells(pop.table.locator('thead tr'))).toHaveText(['', 'So far', 'Normal', 'Slow']);
      // The step's ten timings, five of the other project's and its own five: its normal, slow and
      // longest ten minutes. The run's seven steps at the kind's price, its slow 1.6 times that, to
      // the nearest five from an hour; its so far its five steps and the running one's time.
      await expect(pop.steps).toHaveCount(1);
      await expect(cells(pop.steps)).toHaveText([kind, /^\d+ min$/, '10 min', '10 min']);
      await expect(cells(pop.run)).toHaveText(['The run', /^5\d min$/, '1 h 10 min', '1 h 50 min']);
      await expect(pop.red).toHaveText([redLine('10 min', kind, 10)]);
    }
    // On the work item the table first; in the head the work item's title.
    await expect(item.work.etaPop.title).toHaveCount(0);
    expect(await partsOf(item.work.etaPop)).toEqual(['eta-figures', 'eta-red']);
    await expect(projectHead.etaPop.title).toHaveText(TITLE);
    expect(await partsOf(projectHead.etaPop)).toEqual(['eta-title', 'eta-figures', 'eta-red']);

    // On hover, off a phone, under its badge from the badge's left; the title within the table's width.
    await item.work.eta.hover();
    await expect(item.work.etaPop.root).toBeVisible();
    await projectHead.eta.hover();
    await expect(item.work.etaPop.root).toBeHidden();
    await expect(projectHead.etaPop.root).toBeVisible();
    const [badge, pop, title, table] = await Promise.all(
      [projectHead.eta, projectHead.etaPop.root, projectHead.etaPop.title, projectHead.etaPop.table].map(box),
    );
    expect(pop.y).toBeGreaterThanOrEqual(badge.y + badge.height);
    expect(pop.x).toBeCloseTo(badge.x, 0);
    expect(title.width).toBeLessThanOrEqual(table.width + 0.5);
    await page.mouse.move(0, 0);
    await expect(projectHead.etaPop.root).toBeHidden();

    // On a press, which the keyboard makes too; Esc closes it.
    await item.work.eta.focus();
    await page.keyboard.press('Enter');
    await expect(item.work.eta).toHaveAttribute('aria-expanded', 'true');
    await expect(item.work.etaPop.root).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(item.work.eta).toHaveAttribute('aria-expanded', 'false');
    await expect(item.work.etaPop.root).toBeHidden();

    // A press on the badge opens and closes it, and a press elsewhere closes it.
    await projectHead.eta.click();
    await expect(projectHead.eta).toHaveAttribute('aria-expanded', 'true');
    await projectHead.eta.click();
    await expect(projectHead.eta).toHaveAttribute('aria-expanded', 'false');
    await projectHead.eta.click();
    await expect(projectHead.eta).toHaveAttribute('aria-expanded', 'true');
    await item.title.click();
    await expect(projectHead.eta).toHaveAttribute('aria-expanded', 'false');
    await expect(projectHead.etaPop.root).toBeHidden();

    // Two steps running: a row each and a line each, in the list's order, the other kind's at its
    // five minutes; the run's steps each at its kind's price, its so far the ten steps done.
    await publishList(projects, work, [
      ...listOf({ kind, tag: 'two-' }).slice(0, 5),
      step('two-running', kind, { state: 'active' }),
      step('two-other', other, { state: 'active' }),
      step('two-ahead', kind),
    ]);
    await expect(item.work.etaPop.steps).toHaveCount(2);
    await expect(cells(item.work.etaPop.steps.nth(0))).toHaveText([kind, /^\d+ min$/, '10 min', '10 min']);
    await expect(cells(item.work.etaPop.steps.nth(1))).toHaveText([other, /^\d+ min$/, '5 min', '5 min']);
    await expect(cells(item.work.etaPop.run)).toHaveText(['The run', /^1 h 4\d min$/, '1 h 15 min', '2 h']);
    await expect(item.work.etaPop.red).toHaveText([redLine('10 min', kind, 15), redLine('5 min', other, 5)]);

    // A badge far right in a narrow timeline: its figures moved left, whole inside the timeline.
    await page.setViewportSize({ width: 1360, height: 800 });
    await expect.poll(async () => (await box(item.head)).height).toBeLessThan(40);
    await item.work.eta.hover();
    await expect(item.work.etaPop.root).toBeVisible();
    const [feed, narrowBadge, narrowPop, narrowTable] = await Promise.all(
      [timeline.root, item.work.eta, item.work.etaPop.root, item.work.etaPop.table].map(box),
    );
    expect(narrowPop.x).toBeLessThan(narrowBadge.x);
    expect(narrowPop.x + narrowPop.width).toBeCloseTo(feed.x + feed.width - 8, 0);
    expect(narrowTable.x).toBeGreaterThan(narrowPop.x);
    expect(narrowTable.x + narrowTable.width).toBeLessThan(narrowPop.x + narrowPop.width);
  });

  test('is the alert once the running step has outrun every past one of its kind: red, the clock’s alert and an em dash where the time stood; its figures open with its sentence first, naming the work item in the head, its time the run’s so far', async ({
    page,
    people,
    projects,
    timeline,
    projectHead,
    deploymentSse,
  }) => {
    const { project, work } = await running({ people, projects });
    const kind = makeUnique('gate-sweep');
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work);
    // Five steps done in no time, two not begun; the run so far no time at all.
    await publish(projects, work, { kind, seconds: 0, ahead: 2 });

    for (const eta of [item.work.eta, projectHead.eta]) {
      await expect(eta).toHaveText('—');
      await expect(eta).toHaveClass(/long/);
      await expect(eta).toHaveRole('button');
      await expect(eta.locator('svg')).toHaveClass(/lucide-clock-alert/);
      await expect(eta).toHaveAttribute('aria-expanded', 'false');
    }
    const red = await item.work.eta.evaluate((badge) => getComputedStyle(badge).color);
    expect(red).toBe(await item.work.stop.locator('svg').evaluate((icon) => getComputedStyle(icon).color));

    // On hover, off a phone: the sentence, then the step's row past its longest, and the line under it.
    await expect(item.work.etaPop.root).toBeHidden();
    await item.work.eta.hover();
    await expect(item.work.etaPop.root).toBeVisible();
    await expect(item.work.etaPop.says).toHaveText(OUTRUN);
    await expect(item.work.eta).toHaveAccessibleName(OUTRUN);
    expect(await partsOf(item.work.etaPop)).toEqual(['eta-says', 'eta-figures', 'eta-red']);
    await expect(cells(item.work.etaPop.steps)).toHaveText([kind, /^\d+ min$/, '0 min', '0 min']);
    await expect(item.work.etaPop.run).toHaveCount(0);
    await expect(item.work.etaPop.red).toHaveText([redLine('0 min', kind, 5)]);
    await projectHead.eta.hover();
    await expect(item.work.etaPop.root).toBeHidden();
    await expect(projectHead.etaPop.root).toBeVisible();
    await expect(projectHead.etaPop.says).toHaveText(outrunOf(TITLE));
    await expect(projectHead.etaPop.title).toHaveCount(0);
    expect(await partsOf(projectHead.etaPop)).toEqual(['eta-says', 'eta-figures', 'eta-red']);
    // Under its badge, from the badge's left; the sentence within the table's width.
    const [badge, pop, says, table] = await Promise.all(
      [projectHead.eta, projectHead.etaPop.root, projectHead.etaPop.says, projectHead.etaPop.table].map(box),
    );
    expect(pop.y).toBeGreaterThanOrEqual(badge.y + badge.height);
    expect(pop.x).toBeCloseTo(badge.x, 0);
    expect(says.width).toBeLessThanOrEqual(table.width + 0.5);
    expect(says.height).toBeGreaterThan(30);
    await page.mouse.move(0, 0);
    await expect(projectHead.etaPop.root).toBeHidden();

    // On a press, which the keyboard makes too; Esc closes it.
    await item.work.eta.focus();
    await page.keyboard.press('Enter');
    await expect(item.work.eta).toHaveAttribute('aria-expanded', 'true');
    await expect(item.work.etaPop.root).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(item.work.eta).toHaveAttribute('aria-expanded', 'false');
    await expect(item.work.etaPop.root).toBeHidden();

    // A press on the badge opens and closes it, and a press elsewhere closes it.
    await projectHead.eta.click();
    await expect(projectHead.eta).toHaveAttribute('aria-expanded', 'true');
    await projectHead.eta.click();
    await expect(projectHead.eta).toHaveAttribute('aria-expanded', 'false');
    await projectHead.eta.click();
    await expect(projectHead.eta).toHaveAttribute('aria-expanded', 'true');
    await item.title.click();
    await expect(projectHead.eta).toHaveAttribute('aria-expanded', 'false');
    await expect(projectHead.etaPop.root).toBeHidden();
  });

  test('is the alert with the time left on a step the workflow marked, its sentence the mark’s, which it keeps once the step has also outrun every past one of its kind, the badge then an em dash; the alert alone where the work item has no estimate, its sentence alone; unmarked, such a work item shows nothing', async ({
    page,
    people,
    projects,
    timeline,
    projectHead,
    deploymentSse,
  }) => {
    const { project, work } = await running({ people, projects });
    const kind = makeUnique('code-writer');
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work);
    await publish(projects, work, { kind, marked: true });

    for (const eta of [item.work.eta, projectHead.eta]) {
      await expect(eta).toHaveText('10 min');
      await expect(eta).toHaveClass(/long/);
      await expect(eta).toHaveRole('button');
      await expect(eta.locator('svg')).toHaveClass(/lucide-clock-alert/);
    }
    // Named by the time left it shows, then its sentence; its time the run's five steps.
    const named = (sentence: RegExp) => new RegExp(`^10 min left\\. ${sentence.source.slice(1)}`);
    await expect(item.work.eta).toHaveAccessibleName(named(MARKED));
    await expect(projectHead.eta).toHaveAccessibleName(named(markedOf(TITLE)));
    await item.work.eta.click();
    await expect(item.work.etaPop.root).toBeVisible();
    await expect(item.work.etaPop.says).toHaveText(MARKED);
    await expect(item.work.etaPop.says).toHaveText(/^It has run 5\d min,/);
    await expect(cells(item.work.etaPop.steps)).toHaveText([kind, /^\d+ min$/, '10 min', '10 min']);
    await page.keyboard.press('Escape');
    await projectHead.eta.click();
    await expect(projectHead.etaPop.root).toBeVisible();
    await expect(projectHead.etaPop.says).toHaveText(markedOf(TITLE));
    await page.keyboard.press('Escape');

    // Marked and outrun, its kind's steps having taken no time: the em dash, and the mark's sentence.
    const quick = makeUnique('gate-sweep');
    await publish(projects, work, { kind: quick, seconds: 0, marked: true, tag: 'quick-' });
    for (const eta of [item.work.eta, projectHead.eta]) {
      await expect(eta).toHaveText('—');
      await expect(eta).toHaveClass(/long/);
    }
    await expect(item.work.eta).toHaveAccessibleName(MARKED);
    await expect(projectHead.eta).toHaveAccessibleName(markedOf(TITLE));
    await item.work.eta.click();
    await expect(item.work.etaPop.says).toHaveText(MARKED);
    await expect(cells(item.work.etaPop.steps)).toHaveText([quick, /^\d+ min$/, '0 min', '0 min']);
    await page.keyboard.press('Escape');

    // The mark taken back and set again, the badge the em dash throughout: the head's sentence
    // follows the work item's at once, not at the minute's read.
    for (const [marked, says, headSays] of [
      [false, OUTRUN, outrunOf(TITLE)],
      [true, MARKED, markedOf(TITLE)],
    ] as const) {
      await projects.setProgress(work, listOf({ kind: quick, seconds: 0, marked, tag: 'quick-' }));
      await expect(item.work.eta).toHaveAccessibleName(says);
      await expect(projectHead.eta).toHaveAccessibleName(headSays);
      await expect(projectHead.eta).toHaveText('—');
    }

    // The running step alone on the list, of a kind with no timing: no estimate and no row, the
    // mark's alert alone, its sentence alone in its pop, at most 300px wide.
    const untimed = makeUnique('consult');
    await projects.setProgress(work, [step('running', untimed, { state: 'active', marked: true })]);
    for (const eta of [item.work.eta, projectHead.eta]) {
      await expect(eta).toHaveText('');
      await expect(eta).toHaveClass(/long/);
      await expect(eta.locator('svg')).toHaveClass(/lucide-clock-alert/);
    }
    await item.work.eta.click();
    await expect(item.work.etaPop.root).toBeVisible();
    await expect(item.work.etaPop.says).toHaveText(MARKED);
    await expect(item.work.eta).toHaveAccessibleName(MARKED);
    expect(await partsOf(item.work.etaPop)).toEqual(['eta-says']);
    expect((await box(item.work.etaPop.root)).width).toBeLessThanOrEqual(300);

    // The mark taken back: nothing, and nothing in its place.
    await projects.setProgress(work, [step('running', untimed, { state: 'active' })]);
    await expect(item.work.eta).toHaveCount(0);
    await expect(projectHead.eta).toHaveCount(0);
  });

  test('is read again each minute while it shows, by the page’s clock, with no event and no read of the timeline or the head', async ({
    page,
    people,
    projects,
    timeline,
    projectHead,
    deploymentSse,
  }) => {
    const { project, work } = await running({ people, projects });
    const kind = makeUnique('code-writer');
    await page.clock.install();
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work);
    // Every past step of the kind took five seconds: within them the step that runs has a time left.
    await publish(projects, work, { kind, seconds: 5 });
    await expect(item.work.eta).toHaveText('5 min');
    await expect(projectHead.eta).toHaveText('5 min');

    // Past them the server reads the step as longer than usual, and tells no page.
    await expect.poll(async () => (await projects.estimates(project)).estimate?.longer_than_usual).toBe('outrun');
    await expect(item.work.eta).toHaveText('5 min');
    const read: string[] = [];
    const reads = ['', '/timeline', '/estimates'].map((under) => `/api/projects/${project}${under}`);
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname;
      if (reads.includes(path)) read.push(path);
    });

    // The wall clock alone moves the minute on: the stream's silence watch reads the monotonic one,
    // and a stream opened again reads the timeline and the head.
    await page.clock.setSystemTime((await pageNow(page)) + MINUTE);
    await expect(item.work.eta).toHaveText('—');
    await expect(item.work.eta).toHaveClass(/long/);
    await expect(projectHead.eta).toHaveText('—');
    expect(read).toEqual([`/api/projects/${project}/estimates`]);
  });

  test('stands on a line of its own under the head where its row would cut it, the row as it was, and back in the row once it holds it', async ({
    page,
    people,
    projects,
    timeline,
    deploymentSse,
  }) => {
    const { project, work } = await running({ people, projects });
    const kind = makeUnique('code-writer');
    await page.setViewportSize(WIDE);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work);
    await publish(projects, work, { kind });
    await expect(item.work.eta).toHaveText('10 min');

    // A wide head holds it in its row.
    const row = await box(item.kind);
    expect((await box(item.head)).height).toBe(row.height);
    expect((await box(item.work.eta)).y).toBeLessThan(row.y + row.height);

    // A head too narrow for it: under the row, from its left; Session log, Stop and Discuss stay in the row, at its end.
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect.poll(async () => (await box(item.head)).height).toBe(2 * row.height);
    const [head, first, eta, log, stop, discuss] = await Promise.all(
      [item.head, item.kind, item.work.eta, item.work.sessionLog, item.work.stop, item.discuss].map(box),
    );
    expect(eta.y).toBeGreaterThanOrEqual(first.y + first.height);
    expect(eta.x).toBeCloseTo(head.x, 0);
    for (const button of [log, stop, discuss]) expect(button.y).toBeLessThan(first.y + first.height);
    expect(discuss.x + discuss.width).toBeCloseTo(head.x + head.width, 0);

    // Wide again, it is back in the row.
    await page.setViewportSize(WIDE);
    await expect.poll(async () => (await box(item.head)).height).toBe(row.height);
    expect((await box(item.work.eta)).y).toBeLessThan(row.y + row.height);
  });
});

test.describe('The time a running work item still takes, on a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('stands after the name in the head’s one line and alone under a work item’s head; its figures open on a press, the head’s and a work item’s spanning the page under the badge, the table whole in them, a long kind wrapping; the Plan tab shows none', async ({
    people,
    projects,
    timeline,
    projectHead,
    phoneTabs,
    deploymentSse,
  }) => {
    // A kind as long as one may be.
    const kind = makeUnique('a-kind-the-workflow-names-at-length-for-its-code-writer-s', 6);
    expect(kind).toHaveLength(64);
    const { project, work } = await running({ people, projects }, [{ kind, seconds: 600 }]);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work);
    await publish(projects, work, { kind, ahead: 1 });
    await expect(item.work.eta).toHaveText('20 min');
    await expect(projectHead.eta).toHaveText('20 min');

    // The head's one line: the badge after the name.
    const [bar, name, headEta] = await Promise.all([projectHead.root, projectHead.name, projectHead.eta].map(box));
    expect(bar.height).toBe(52);
    expect(headEta.x).toBeGreaterThanOrEqual(name.x + name.width);
    expect(headEta.y).toBeGreaterThan(bar.y);
    expect(headEta.y + headEta.height).toBeLessThan(bar.y + bar.height);
    expect(await projectHead.name.evaluate((heading) => heading.nextElementSibling!.querySelector('[data-testid="project.eta"]') !== null)).toBe(true);

    // A work item's: under its head's row, from its left, alone.
    const [head, first, eta] = await Promise.all([item.head, item.kind, item.work.eta].map(box));
    expect(eta.y).toBeGreaterThanOrEqual(first.y + first.height - 1);
    expect(eta.x).toBeCloseTo(head.x, 0);
    expect(await item.work.eta.evaluate((badge) => badge.closest('.work-eta')!.childElementCount)).toBe(1);

    // A press opens the head's: the page's width under the head, 8px in from each side, the title
    // first, the table whole within it, the long kind wrapping in its row.
    await expect(projectHead.etaPop.root).toBeHidden();
    await projectHead.eta.tap();
    await expect(projectHead.etaPop.root).toBeVisible();
    await expect(projectHead.etaPop.title).toHaveText(TITLE);
    await expect(cells(projectHead.etaPop.steps)).toHaveText([kind, /^\d+ min$/, '10 min', '10 min']);
    await expect(cells(projectHead.etaPop.run)).toHaveText(['The run', /^5\d min$/, '1 h 10 min', '1 h 50 min']);
    const fits = async (pop: EtaPop) => {
      const [whole, table, kindCell] = await Promise.all([pop.root, pop.table, pop.steps.locator('th')].map(box));
      expect(whole.x).toBe(8);
      expect(whole.width).toBe(PHONE.width - 16);
      expect(table.x).toBeGreaterThan(whole.x);
      expect(table.x + table.width).toBeLessThan(whole.x + whole.width);
      expect(kindCell.height).toBeGreaterThan(30);
      return whole;
    };
    const headPop = await fits(projectHead.etaPop);
    expect(headPop.y).toBeGreaterThanOrEqual(bar.y + bar.height);
    await projectHead.name.tap();
    await expect(projectHead.etaPop.root).toBeHidden();

    // A work item's spans the page under its badge too.
    await item.work.eta.tap();
    await expect(item.work.etaPop.root).toBeVisible();
    await expect(item.work.etaPop.title).toHaveCount(0);
    const itemPop = await fits(item.work.etaPop);
    expect(itemPop.y).toBeGreaterThanOrEqual(eta.y + eta.height);
    await projectHead.name.tap();
    await expect(item.work.etaPop.root).toBeHidden();

    // Longer than usual: the running step past every one of its kind, which took no time.
    const slow = makeUnique('gate-sweep');
    await publish(projects, work, { kind: slow, seconds: 0, tag: 'slow-' });
    await expect(item.work.eta).toHaveText('—');
    await expect(projectHead.eta).toHaveText('—');
    await projectHead.eta.tap();
    await expect(projectHead.etaPop.says).toBeVisible();
    await expect(projectHead.etaPop.says).toHaveText(outrunOf(TITLE));
    await projectHead.name.tap();
    await item.work.eta.tap();
    await expect(item.work.etaPop.says).toHaveText(OUTRUN);
    await projectHead.name.tap();
    await expect(item.work.etaPop.root).toBeHidden();

    // The Plan tab has no badge of its own.
    await projectHead.donut.tap();
    await expect(phoneTabs.plan.root).toBeVisible();
    await expect(phoneTabs.plan.root.locator('.eta-badge')).toHaveCount(0);
    await expect(projectHead.eta).toHaveText('—');
  });
});
