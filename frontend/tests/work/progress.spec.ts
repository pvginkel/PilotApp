/**
 * A work item's progress (F145.2, F145.3, F145.4): the steps its run publishes, through
 * `set_progress` while its turn runs, shown in the row under its line as the progress button, the
 * plan's donut and the first active step's label, ", …" when more are active, else read as the
 * plan's step button reads; its popover lists the steps in order, done ones ticked, active ones
 * highlighted, how many are done in its heading, no notes, and closes on an outside click or Esc. A
 * change moves the button and an open popover through the live event, with no read of the
 * timeline's own; an emptied list takes the button away. It shows on every open item that
 * published a list, stopped, held, failed or halted at its turn's end, beside Resume where it has
 * one, goes with the row while Stop asks, and the done line never has it. At the timeline's end
 * its popover opens above it; on a phone it keeps its label.
 */

import type { Locator } from '@playwright/test';
import { rawTurn } from '../support/controller';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';

type State = 'pending' | 'active' | 'done';

const step = (code: string, state?: State) => ({ code, label: `Step ${code}`, state });

const HALT_FILE = '/work/.quota-limit-halt-requested';

interface Fixtures {
  people: People;
  projects: Projects;
}

/** A project, signed in as its member, and a work item running in it. */
async function running({ people, projects }: Fixtures, { paused = false } = {}): Promise<{ project: string; work: string }> {
  const me = await people.signIn();
  const project = await projects.make({ name: makeUnique('Progress'), members: [me.handle!], paused });
  const work = await projects.startWork(project, { title: 'Running slice 034', brief: 'Run the slice.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  return { project, work };
}

/** The donut's parts, in order. */
async function ringParts(ring: Locator): Promise<(string | null)[]> {
  return ring.locator('circle').evaluateAll((circles) => circles.map((circle) => circle.getAttribute('class')));
}

/** The test ids of the row's buttons, in order. */
async function rowButtons(row: Locator): Promise<(string | null)[]> {
  return row.locator('button').evaluateAll((buttons) => buttons.map((button) => button.getAttribute('data-testid')));
}

/** Resolves once the relay has recorded the result that ends the item's stopped turn: Resume is refused until then. */
async function turnEnded(projects: Projects, work: string): Promise<void> {
  await expect.poll(async () => (await projects.records(work)).records.at(-1)?.kind).toBe('result');
}

test.describe('The progress button', () => {
  test('shows once the run publishes its steps, the plan’s donut and the first active step, “, …” when more are, else as the plan’s button reads, moved through the live event alone, and goes once the list is emptied', async ({
    page,
    people,
    projects,
    timeline,
    deploymentSse,
  }) => {
    const { project, work } = await running({ people, projects });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;
    await expect(item.running).toBeVisible();
    await expect(item.row).toHaveCount(0);
    let reads = 0;
    page.on('request', (request) => {
      if (request.url().includes(`/api/projects/${project}/timeline`)) reads += 1;
    });

    expect(await projects.setProgress(work, [step('a', 'done'), step('b', 'active'), step('c')])).toEqual([
      { code: 'a', label: 'Step a', state: 'done' },
      { code: 'b', label: 'Step b', state: 'active' },
      { code: 'c', label: 'Step c', state: 'pending' },
    ]);
    await expect(item.progress).toHaveText('Step b');
    await expect(item.row).toHaveText('Step b');
    await expect.poll(() => ringParts(item.progressRing)).toEqual(['done', 'now', 'rest']);
    await expect(item.progress).toHaveAttribute('title', '1 of 3 steps done · in progress: Step b');
    await expect(item.progress).toHaveAttribute('aria-expanded', 'false');

    const cases: [ReturnType<typeof step>[], string, string[]][] = [
      [[step('a', 'done'), step('b', 'active'), step('c', 'active')], 'Step b, …', ['done', 'now']],
      [[step('a', 'pending'), step('b', 'pending')], 'Not started', ['rest']],
      [[step('a', 'done'), step('b', 'pending')], '1 of 2 done', ['done', 'rest']],
      [[step('a', 'done'), step('b', 'done')], 'All steps done', ['done']],
    ];
    for (const [steps, reading, parts] of cases) {
      await projects.setProgress(work, steps);
      await expect(item.progress).toHaveText(reading);
      await expect.poll(() => ringParts(item.progressRing)).toEqual(parts);
    }

    await projects.setProgress(work, []);
    await expect(item.progress).toHaveCount(0);
    await expect(item.row).toHaveCount(0);
    expect(reads).toBe(0);
  });

  test('goes with the row while Stop asks and comes back with it; stays on the stopped item beside Resume, on its held start and on the run resumed', async ({
    people,
    projects,
    timeline,
    deploymentSse,
  }) => {
    const { project, work } = await running({ people, projects });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;
    await projects.setProgress(work, [step('a', 'done'), step('b', 'active')]);
    await expect(item.progress).toHaveText('Step b');

    await item.stop.click();
    await expect(item.stopConfirm.root).toBeVisible();
    await expect(item.row).toHaveCount(0);
    await expect(item.progress).toHaveCount(0);
    await item.stopConfirm.cancel.click();
    await expect(item.progress).toHaveText('Step b');

    await item.stop.click();
    await item.stopConfirm.yes.click();
    await expect(item.line).toHaveAttribute('data-state', 'stopped');
    await expect(item.resume).toBeVisible();
    expect(await rowButtons(item.row)).toEqual(['timeline.work.progress', 'timeline.work.resume']);

    await turnEnded(projects, work);
    await projects.transition(project, 'paused');
    await item.resume.click();
    await expect(item.line).toHaveAttribute('data-state', 'held');
    await expect(item.stop).toBeVisible();
    await expect(item.row).toHaveText('Step b');

    await projects.transition(project, 'resumed');
    await expect(item.running).toBeVisible();
    await expect(item.progress).toHaveText('Step b');
    expect((await projects.work(project, work)).progress).toEqual([
      { code: 'a', label: 'Step a', state: 'done' },
      { code: 'b', label: 'Step b', state: 'active' },
    ]);
  });

  test('stays on a turn ended in error, beside Resume', async ({ people, projects, controller, timeline, deploymentSse }) => {
    const { project, work } = await running({ people, projects });
    const environment = await projects.environment(project, work);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;
    await projects.setProgress(work, [step('a', 'active')]);
    await expect(item.progress).toHaveText('Step a');

    await controller.finish(environment.id, 'claude-1', 'error', 'The model is overloaded.');
    await expect(item.line).toHaveAttribute('data-state', 'failed');
    expect(await rowButtons(item.row)).toEqual(['timeline.work.progress', 'timeline.work.resume']);
    await expect(item.progress).toHaveText('Step a');
  });

  test('stays on a run halted at its turn’s end, alone in the row, and the done line has none', async ({
    people,
    projects,
    controller,
    timeline,
    deploymentSse,
  }) => {
    const { project, work } = await running({ people, projects });
    const environment = await projects.environment(project, work);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const tile = timeline.item(work);
    const item = tile.work;
    // The turn's lines played: its conversation, which the nudge goes on.
    await controller.play(environment.id, 'claude-1', rawTurn('turn_text'));
    await projects.setProgress(work, [step('a', 'done'), step('b', 'active')]);
    await expect(item.progress).toHaveText('Step b');

    await controller.usage({ seven_day: 0.92, five_hour: 0.1 });
    await expect.poll(() => controller.fileText(environment.id, HALT_FILE)).toBe('');
    await controller.finish(environment.id, 'claude-1', 'success', 'Halfway.');
    await expect(item.cue).toHaveText('Halted at the week’s limit');
    await expect(tile.root).toHaveAttribute('data-state', 'open');
    expect(await rowButtons(item.row)).toEqual(['timeline.work.progress']);
    await expect(item.progress).toHaveText('Step b');

    await controller.usage({ seven_day: 0.5, five_hour: 0.1 });
    await expect(item.running).toBeVisible();
    await expect(item.progress).toHaveText('Step b');
    await controller.finish(environment.id, 'claude-1');
    await expect(tile.root).toHaveAttribute('data-state', 'done');
    await expect(item.progress).toHaveCount(0);
    await expect(item.row).toHaveCount(0);
  });
});

test.describe('Its popover', () => {
  test('lists the steps in order, done ones ticked, active ones highlighted, how many are done in its heading, no notes; moves while open; closes on Esc and on an outside click', async ({
    page,
    people,
    projects,
    timeline,
    deploymentSse,
  }) => {
    const { project, work } = await running({ people, projects });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const tile = timeline.item(work);
    const item = tile.work;
    await projects.setProgress(work, [step('a', 'done'), step('b', 'active'), step('c'), step('d', 'active')]);
    await expect(item.steps.root).toHaveCount(0);

    await item.progress.click();
    await expect(item.steps.root).toBeVisible();
    await expect(item.steps.root).toHaveAccessibleName('Progress');
    await expect(item.progress).toHaveAttribute('aria-expanded', 'true');
    await expect(item.steps.heading).toHaveText('Progress · 1 of 4 done');
    await expect(item.steps.items).toHaveText(['Step a', 'Step b', 'Step c', 'Step d']);
    expect(await item.steps.items.evaluateAll((steps) => steps.map((element) => element.dataset.state))).toEqual(['done', 'now', 'pending', 'now']);
    await expect(item.steps.items.nth(0).locator('.mark svg')).toHaveCount(1);
    await expect(item.steps.items.locator('.mark svg')).toHaveCount(1);
    await expect(item.steps.items.nth(1).locator('.mark')).toHaveAccessibleName('In progress');
    await expect(item.steps.items.nth(2).locator('.mark')).toHaveAccessibleName('Not started');
    await expect(item.steps.root.getByTestId('timeline.work.steps.step.notes-button')).toHaveCount(0);
    const background = (index: number) => item.steps.items.nth(index).evaluate((element) => getComputedStyle(element).backgroundColor);
    const highlighted = await background(1);
    expect(highlighted).not.toBe(await background(2));
    expect(await background(3)).toBe(highlighted);
    expect(await background(0)).toBe(await background(2));

    // A step added where the work grew, a round a step of its own.
    await projects.setProgress(work, [step('a', 'done'), step('b', 'done'), step('d', 'active'), step('b-2')]);
    await expect(item.steps.heading).toHaveText('Progress · 2 of 4 done');
    await expect(item.steps.items).toHaveText(['Step a', 'Step b', 'Step d', 'Step b-2']);
    await expect(item.progress).toHaveText('Step d');

    await page.keyboard.press('Escape');
    await expect(item.steps.root).toHaveCount(0);
    await item.progress.click();
    await expect(item.steps.root).toBeVisible();
    // A press in the timeline's corner, outside the card.
    await timeline.root.click({ position: { x: 4, y: 4 } });
    await expect(item.steps.root).toHaveCount(0);

    await item.progress.click();
    await expect(item.steps.root).toBeVisible();
    await projects.setProgress(work, []);
    await expect(item.progress).toHaveCount(0);
    await expect(item.steps.root).toHaveCount(0);
  });

  test('at the timeline’s end, opens above its button, within the timeline', async ({ people, projects, timeline, deploymentSse }) => {
    const { project, work } = await running({ people, projects });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;
    await projects.setProgress(
      work,
      Array.from({ length: 10 }, (_, index) => step(`s${index}`, index === 0 ? 'active' : 'pending')),
    );
    await item.progress.click();
    await expect(item.steps.items).toHaveCount(10);

    const [feed, button, pop] = await Promise.all([timeline.root, item.progress, item.steps.root].map(async (locator) => (await locator.boundingBox())!));
    expect(pop.y + pop.height).toBeLessThanOrEqual(button.y);
    expect(pop.y).toBeGreaterThanOrEqual(feed.y);
    expect(await item.steps.root.evaluate((element) => element.scrollHeight <= element.clientHeight)).toBe(true);
  });
});

test.describe('On the phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test('the progress button keeps its label beside the donut, and its popover stays within the window', async ({
    people,
    projects,
    timeline,
    deploymentSse,
  }) => {
    const { project, work } = await running({ people, projects });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const tile = timeline.item(work);
    const item = tile.work;
    await projects.setProgress(work, [step('a', 'done'), step('review-2', 'active')]);

    await expect(item.progressRing).toBeVisible();
    await expect(item.progressName).toBeVisible();
    await expect(item.progressName).toHaveText('Step review-2');
    const [card, button] = await Promise.all([tile.root, item.progress].map(async (locator) => (await locator.boundingBox())!));
    expect(button.x).toBeGreaterThanOrEqual(card.x);
    expect(button.x + button.width).toBeLessThanOrEqual(card.x + card.width);

    await item.progress.tap();
    const pop = (await item.steps.root.boundingBox())!;
    expect(pop.x).toBeGreaterThanOrEqual(0);
    expect(pop.x + pop.width).toBeLessThanOrEqual(390);
  });
});
