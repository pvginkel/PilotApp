/**
 * The time a running work item still takes, as its badge (F156.7, F156.8): a clock and the time
 * left as the server rounds it, "20 min", "1 h", "3 h", with no tilde, after a running work item's
 * time, the running step's kind as published after it, and right after the project's name in its
 * head, never on the top bar; at rest words alone, with no hover and no press. Longer than usual
 * it is the alert, red with the clock's alert: an em dash where the time stood once the running
 * step has outrun every past one of its kind; the time left on a step the workflow marked; the
 * icon alone on such a step where the work item has no estimate. The alert's sentence drops under
 * it on hover off a phone and on a press, naming the work item in the head, and closes on Esc and
 * on a press elsewhere. A step's move reaches the work item's badge through the live event, with
 * no read of the timeline, and the head's follows it; nothing shows, and nothing in its place,
 * where the server gives no estimate, or once the work item stops. While a badge shows, the page
 * reads the estimates again each minute. Where the head's row would cut them, the badge and the
 * kind stand on a line of their own under it, as they always do on a phone, where the head's badge
 * stands after the name in its one line, the alert's sentence spans the page under the head and a
 * work item's its head, and the Plan tab shows none.
 *
 * Each test's steps are of a kind of its own: a kind's timings count across every project, and a
 * worker's specs share one database.
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { ProgressStep, Projects } from '../support/projects';

const TITLE = 'Running slice 049';
const PHONE = { width: 390, height: 844 };
const WIDE = { width: 1800, height: 800 };
const MINUTE = 60_000;

interface Fixtures {
  people: People;
  projects: Projects;
}

/** A project, signed in as its member, and a work item running in it. */
async function running({ people, projects }: Fixtures): Promise<{ project: string; work: string }> {
  const me = await people.signIn();
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
 * begun, then the past ones done in `seconds` each, which leaves the kind their timings, and one
 * running.
 */
async function publish(projects: Projects, work: string, published: Published): Promise<void> {
  const list = listOf(published);
  await projects.setProgress(
    work,
    list.map(({ code, label, kind }) => ({ code, label, kind })),
  );
  await projects.setProgress(work, list);
}

const box = async (locator: Locator) => (await locator.boundingBox())!;
// eslint-disable-next-line no-restricted-properties -- the page's clock, a real timestamp
const pageNow = (page: Page) => page.evaluate(() => Date.now());
const ALERT = /^It has run \d+ min, longer than such work usually takes: it may be stuck\.$/;
const alertOf = (title: string) => new RegExp(`^${title} has run \\d+ min, longer than such work usually takes: it may be stuck\\.$`);

test.describe('The time a running work item still takes', () => {
  test('shows after the running time as a clock and the time left, with no tilde, the running step’s kind after it, and right after the project’s name, never on the top bar; at rest it has no hover and no press; it moves with the list through the live event alone, and goes once the work item stops', async ({
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
    // A window wide enough for the work item's head to hold the badge and the kind in its row.
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
    await expect(item.work.etaKind).toHaveCount(0);

    // The fifth: the running step and the one not begun, at ten minutes each.
    await projects.setProgress(work, [
      ...listOf({ kind, past: 4 }).slice(0, 4),
      step('running', kind, { state: 'done', duration: 600 }),
      step('ahead-1', kind, { state: 'active' }),
      step('ahead-2', kind),
    ]);
    await expect(item.work.eta).toHaveText('20 min');
    await expect(item.work.eta).toHaveAttribute('role', 'img');
    await expect(item.work.eta).toHaveAccessibleName('20 min left');
    await expect(item.work.eta.locator('svg')).toHaveClass(/lucide-clock/);
    await expect(item.work.eta.locator('svg')).not.toHaveClass(/lucide-clock-alert/);
    await expect(item.work.eta).not.toHaveClass(/long/);
    await expect(item.work.etaKind).toHaveText(kind);
    await expect(projectHead.eta).toHaveText('20 min');
    await expect(projectHead.eta).toHaveAttribute('role', 'img');
    await expect(shell.topBar.locator('.eta-badge')).toHaveCount(0);

    // After the running time, in the head's row, before Session log; the kind after the badge.
    const [head, time, eta, etaKind, log] = await Promise.all(
      [item.head, item.work.running, item.work.eta, item.work.etaKind, item.work.sessionLog].map(box),
    );
    expect(head.height).toBeLessThan(40);
    expect(eta.x).toBeGreaterThanOrEqual(time.x + time.width);
    expect(etaKind.x).toBeGreaterThanOrEqual(eta.x + eta.width);
    expect(log.x).toBeGreaterThanOrEqual(etaKind.x + etaKind.width);
    expect(eta.height).toBe(22);
    // In the project's head, right after its name.
    expect(await projectHead.name.evaluate((name) => name.nextElementSibling!.querySelector('[data-testid="project.eta"]') !== null)).toBe(true);
    expect((await box(projectHead.eta)).height).toBe(22);

    // At rest nothing opens: no sentence on hover, none on a press.
    await item.work.eta.hover();
    await expect(item.work.etaSays).toHaveCount(0);
    await projectHead.eta.hover();
    await expect(projectHead.etaSays).toHaveCount(0);

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
    await expect(item.work.etaKind).toHaveCount(0);
    await expect(projectHead.eta).toHaveCount(0);
  });

  test('is the alert once the running step has outrun every past one of its kind: red, the clock’s alert and an em dash where the time stood; its sentence drops under it on hover and on a press, naming the work item in the head, and closes on Esc and on a press elsewhere', async ({
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
    await publish(projects, work, { kind, seconds: 0, ahead: 2 });

    for (const eta of [item.work.eta, projectHead.eta]) {
      await expect(eta).toHaveText('—');
      await expect(eta).toHaveClass(/long/);
      await expect(eta).toHaveRole('button');
      await expect(eta.locator('svg')).toHaveClass(/lucide-clock-alert/);
      await expect(eta).toHaveAttribute('aria-expanded', 'false');
    }
    await expect(item.work.etaKind).toHaveText(kind);
    const red = await item.work.eta.evaluate((badge) => getComputedStyle(badge).color);
    expect(red).toBe(await item.work.stop.locator('svg').evaluate((icon) => getComputedStyle(icon).color));

    // On hover, off a phone.
    await expect(item.work.etaSays).toBeHidden();
    await item.work.eta.hover();
    await expect(item.work.etaSays).toBeVisible();
    await expect(item.work.etaSays).toHaveText(ALERT);
    await expect(item.work.eta).toHaveAccessibleName(ALERT);
    await projectHead.eta.hover();
    await expect(item.work.etaSays).toBeHidden();
    await expect(projectHead.etaSays).toBeVisible();
    await expect(projectHead.etaSays).toHaveText(alertOf(TITLE));
    // Under its badge, from the badge's left.
    const [badge, says] = await Promise.all([projectHead.eta, projectHead.etaSays].map(box));
    expect(says.y).toBeGreaterThanOrEqual(badge.y + badge.height);
    expect(says.x).toBeCloseTo(badge.x, 0);
    await page.mouse.move(0, 0);
    await expect(projectHead.etaSays).toBeHidden();

    // On a press, which the keyboard makes too; Esc closes it.
    await item.work.eta.focus();
    await page.keyboard.press('Enter');
    await expect(item.work.eta).toHaveAttribute('aria-expanded', 'true');
    await expect(item.work.etaSays).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(item.work.eta).toHaveAttribute('aria-expanded', 'false');
    await expect(item.work.etaSays).toBeHidden();

    // A press on the badge opens and closes it, and a press elsewhere closes it.
    await projectHead.eta.click();
    await expect(projectHead.eta).toHaveAttribute('aria-expanded', 'true');
    await projectHead.eta.click();
    await expect(projectHead.eta).toHaveAttribute('aria-expanded', 'false');
    await projectHead.eta.click();
    await expect(projectHead.eta).toHaveAttribute('aria-expanded', 'true');
    await item.title.click();
    await expect(projectHead.eta).toHaveAttribute('aria-expanded', 'false');
    await expect(projectHead.etaSays).toBeHidden();
  });

  test('is the alert with the time left on a step the workflow marked, and the alert alone where the work item has no estimate; unmarked, such a work item shows nothing', async ({
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
    // Named by the time left it shows, then its sentence.
    const named = (sentence: RegExp) => new RegExp(`^10 min left\\. ${sentence.source.slice(1)}`);
    await expect(item.work.eta).toHaveAccessibleName(named(ALERT));
    await expect(projectHead.eta).toHaveAccessibleName(named(alertOf(TITLE)));
    await item.work.eta.click();
    await expect(item.work.etaSays).toBeVisible();
    await expect(item.work.etaSays).toHaveText(ALERT);
    await page.keyboard.press('Escape');
    await projectHead.eta.click();
    await expect(projectHead.etaSays).toBeVisible();
    await expect(projectHead.etaSays).toHaveText(alertOf(TITLE));
    await page.keyboard.press('Escape');

    // The running step a kind with no timing: no estimate, the mark's alert alone.
    const untimed = makeUnique('consult');
    await projects.setProgress(work, [...listOf({ kind }).slice(0, 5), step('running', untimed, { state: 'active', marked: true })]);
    for (const eta of [item.work.eta, projectHead.eta]) {
      await expect(eta).toHaveText('');
      await expect(eta).toHaveClass(/long/);
      await expect(eta.locator('svg')).toHaveClass(/lucide-clock-alert/);
    }
    await expect(item.work.etaKind).toHaveText(untimed);
    await item.work.eta.click();
    await expect(item.work.etaSays).toBeVisible();
    await expect(item.work.etaSays).toHaveText(ALERT);
    await expect(item.work.eta).toHaveAccessibleName(ALERT);

    // The mark taken back: nothing, and nothing in its place.
    await projects.setProgress(work, [...listOf({ kind }).slice(0, 5), step('running', untimed, { state: 'active' })]);
    await expect(item.work.eta).toHaveCount(0);
    await expect(item.work.etaKind).toHaveCount(0);
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

  test('stands with the kind on a line of their own under the head where its row would cut them, the row as it was, and back in the row once it holds them', async ({
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
    await expect(item.work.etaKind).toHaveText(kind);

    // A wide head holds them in its row.
    const row = await box(item.kind);
    expect((await box(item.head)).height).toBe(row.height);
    expect((await box(item.work.eta)).y).toBeLessThan(row.y + row.height);

    // A head too narrow for them: under the row, from its left; Session log, Stop and Discuss stay in the row, at its end.
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect.poll(async () => (await box(item.head)).height).toBe(2 * row.height);
    const [head, first, eta, etaKind, log, stop, discuss] = await Promise.all(
      [item.head, item.kind, item.work.eta, item.work.etaKind, item.work.sessionLog, item.work.stop, item.discuss].map(box),
    );
    expect(eta.y).toBeGreaterThanOrEqual(first.y + first.height);
    expect(eta.x).toBeCloseTo(head.x, 0);
    expect(etaKind.x).toBeGreaterThanOrEqual(eta.x + eta.width);
    expect(etaKind.y).toBeGreaterThanOrEqual(first.y + first.height - 1);
    for (const button of [log, stop, discuss]) expect(button.y).toBeLessThan(first.y + first.height);
    expect(discuss.x + discuss.width).toBeCloseTo(head.x + head.width, 0);

    // Wide again, they are back in the row.
    await page.setViewportSize(WIDE);
    await expect.poll(async () => (await box(item.head)).height).toBe(row.height);
    expect((await box(item.work.eta)).y).toBeLessThan(row.y + row.height);
  });
});

test.describe('The time a running work item still takes, on a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('stands after the name in the head’s one line and under a work item’s head, the kind beside it; the alert’s sentence opens on a press, the head’s spanning the page under the head and a work item’s its head; the Plan tab shows none', async ({
    people,
    projects,
    timeline,
    projectHead,
    phoneTabs,
    deploymentSse,
  }) => {
    const { project, work } = await running({ people, projects });
    // A kind as long as one may be.
    const kind = makeUnique('a-kind-the-workflow-names-at-length-for-its-code-writer-s', 6);
    expect(kind).toHaveLength(64);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work);
    await publish(projects, work, { kind, ahead: 1 });
    await expect(item.work.eta).toHaveText('20 min');
    await expect(projectHead.eta).toHaveText('20 min');
    await expect(item.work.etaKind).toHaveText(kind);

    // The head's one line: the badge after the name.
    const [bar, name, headEta] = await Promise.all([projectHead.root, projectHead.name, projectHead.eta].map(box));
    expect(bar.height).toBe(52);
    expect(headEta.x).toBeGreaterThanOrEqual(name.x + name.width);
    expect(headEta.y).toBeGreaterThan(bar.y);
    expect(headEta.y + headEta.height).toBeLessThan(bar.y + bar.height);
    expect(await projectHead.name.evaluate((heading) => heading.nextElementSibling!.querySelector('[data-testid="project.eta"]') !== null)).toBe(true);

    // A work item's: under its head's row, from its left, the kind beside it.
    const [head, first, eta, etaKind] = await Promise.all([item.head, item.kind, item.work.eta, item.work.etaKind].map(box));
    expect(eta.y).toBeGreaterThanOrEqual(first.y + first.height - 1);
    expect(eta.x).toBeCloseTo(head.x, 0);
    expect(etaKind.x).toBeGreaterThanOrEqual(eta.x + eta.width);
    expect(Math.abs(etaKind.y + etaKind.height / 2 - (eta.y + eta.height / 2))).toBeLessThan(2);
    // Cut short within the head.
    expect(etaKind.x + etaKind.width).toBeLessThanOrEqual(head.x + head.width + 0.5);
    expect(await item.work.etaKind.evaluate((words) => words.scrollWidth > words.clientWidth)).toBe(true);
    await expect(item.work.etaKind).toHaveAttribute('title', kind);

    // Longer than usual: the running step past every one of its kind, which took no time.
    const slow = makeUnique('gate-sweep');
    await publish(projects, work, { kind: slow, seconds: 0, tag: 'slow-' });
    await expect(item.work.eta).toHaveText('—');
    await expect(projectHead.eta).toHaveText('—');
    await expect(projectHead.etaSays).toBeHidden();
    await projectHead.eta.tap();
    await expect(projectHead.etaSays).toBeVisible();
    await expect(projectHead.etaSays).toHaveText(alertOf(TITLE));
    const says = await box(projectHead.etaSays);
    expect(says.x).toBe(8);
    expect(says.width).toBe(PHONE.width - 16);
    expect(says.y).toBeGreaterThanOrEqual(bar.y + bar.height);

    await projectHead.name.tap();
    await expect(projectHead.etaSays).toBeHidden();

    // A work item's spans its head, under it.
    await item.work.eta.tap();
    await expect(item.work.etaSays).toBeVisible();
    await expect(item.work.etaSays).toHaveText(ALERT);
    const [itemHead, itemSays] = await Promise.all([item.head, item.work.etaSays].map(box));
    expect(itemSays.x).toBeCloseTo(itemHead.x, 0);
    expect(itemSays.width).toBeCloseTo(itemHead.width, 0);
    expect(itemSays.y).toBeGreaterThanOrEqual(itemHead.y + itemHead.height);
    await projectHead.name.tap();
    await expect(item.work.etaSays).toBeHidden();

    // The Plan tab has no badge of its own.
    await projectHead.donut.tap();
    await expect(phoneTabs.plan.root).toBeVisible();
    await expect(phoneTabs.plan.root.locator('.eta-badge')).toHaveCount(0);
    await expect(projectHead.eta).toHaveText('—');
  });
});
