/**
 * The usage halts (F135.1, F135.4, F135.7, F141.5): while the latest reading puts the week's share at
 * or over the first limit, or the five-hour share at or over its limit, the gate holds a work item's
 * start, its line saying which halt, in its session log too; each halt that holds shows on the gold
 * bar after the outage's, the week's first, its line giving the share, the reading's age and what
 * the halt does to running work by its window's setting (F135.6) — a badge in the top bar off a
 * phone, the week's a button opening its line in a popover, the five-hour's and the outage's their
 * line their title; on a phone a line with the badge's words alone, opening its whole line in a flyout,
 * the week's with its overrule. A reading under the limit lifts it, and the held start goes
 * on. The reading is the fake controller's, on the backend's fleet stream.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';

const PHONE = { width: 390, height: 844 };
const CLOCK = String.raw`\d\d:\d\d`;
// The suite's backends keep the week's halt at its default setting, the cooperative stop, and give
// the five-hour halt the hard stop (tests/support/backend-env-extensions.ts).
const HOLDS = String.raw`none starts until a reading puts it under the limit; chats and Pilot’s own jobs go on\.`;
const WEEK_DOES = String.raw`The running work items are asked to stop at their next step, and ${HOLDS}`;
const FIVE_HOUR_DOES = String.raw`Pilot has stopped every running work item, and ${HOLDS}`;

const WEEK_BADGE = new RegExp(`^Halted at the week’s limit since ${CLOCK}$`);
const FIVE_HOUR_BADGE = new RegExp(`^Halted at the five-hour limit since ${CLOCK}$`);
// A fresh reading's line gives its share alone; a stale one's, the reading's age.
const weekLine = (percent: number, age = '') =>
  new RegExp(
    `^Work items have been halted at the week’s usage limit since ${CLOCK}\\. ${percent}% of the week’s quota is used${age}\\. ${WEEK_DOES}$`,
  );
const AS_OF = `, as of ${CLOCK}`;
const fiveHourLine = (percent: number) =>
  new RegExp(
    `^Work items have been halted at the five-hour usage limit since ${CLOCK}\\. ${percent}% of the five-hour window’s quota is used\\. ${FIVE_HOUR_DOES}$`,
  );

interface Fixtures {
  people: People;
  projects: Projects;
}

/** A project, signed in as its member. */
async function setUp({ people, projects }: Fixtures): Promise<string> {
  const me = await people.signIn();
  return projects.make({ name: makeUnique('Halts'), members: [me.handle!] });
}

/** A work item started in the project, once its session reads `state`. */
async function startIn(projects: Projects, project: string, state: string): Promise<string> {
  const work = await projects.startWork(project, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe(state);
  return work;
}

test.describe('The usage halts', () => {
  test('the week’s holds a work item’s start, its line and its log saying so, shows on the gold bar, and lifts at a reading under the limit', async ({
    people,
    projects,
    controller,
    timeline,
    sessionLog,
    shell,
    page,
  }) => {
    const project = await setUp({ people, projects });
    await controller.usage({ seven_day: 0.92, five_hour: 0.1 });
    const work = await startIn(projects, project, 'held');
    await timeline.open(project);

    const item = timeline.item(work).work;
    await expect(item.line).toHaveAttribute('data-state', 'held');
    await expect(item.cue).toHaveText('Halted at the week’s limit');
    await expect(item.environment).toHaveCount(0);
    await item.sessionLog.click();
    await expect(sessionLog.cue).toHaveText('Halted at the week’s limit');
    await page.keyboard.press('Escape');

    await expect(shell.goldBadge('week_halt')).toHaveText(WEEK_BADGE);
    await expect(shell.goldBadge('five_hour_halt')).toHaveCount(0);
    await shell.goldBadge('week_halt').click();
    await expect(shell.goldText(shell.goldPopover)).toHaveText(weekLine(92));

    // A reading at or over the limit keeps it; its share moves on the bar.
    await controller.usage({ seven_day: 0.95, five_hour: 0.1 });
    await expect(shell.goldText(shell.goldPopover)).toHaveText(weekLine(95));
    await expect(item.cue).toHaveText('Halted at the week’s limit');

    // A stale reading keeps its figures and the halt; its line gives the reading's age.
    await controller.usageStale();
    await expect(shell.goldText(shell.goldPopover)).toHaveText(weekLine(95, AS_OF));
    await expect(item.cue).toHaveText('Halted at the week’s limit');

    await controller.usage({ seven_day: 0.3, five_hour: 0.1 });
    await expect(shell.goldBadge('week_halt')).toHaveCount(0);
    await expect(item.running).toBeVisible();
    await expect(item.environment).toBeVisible();
  });

  test('the five-hour holds a work item’s start, its line saying so, and shows on the gold bar, a line on a phone', async ({
    people,
    projects,
    controller,
    timeline,
    shell,
    page,
  }) => {
    const project = await setUp({ people, projects });
    await controller.usage({ seven_day: 0.5, five_hour: 0.8 });
    const work = await startIn(projects, project, 'held');
    await timeline.open(project);

    await expect(timeline.item(work).work.cue).toHaveText('Halted at the five-hour limit');
    await expect(shell.goldBadge('five_hour_halt')).toHaveText(FIVE_HOUR_BADGE);
    await expect(shell.goldBadge('five_hour_halt')).toHaveAttribute('title', fiveHourLine(80));

    await page.setViewportSize(PHONE);
    await expect(shell.goldLine('five_hour_halt')).toHaveText('Halted at the five-hour limit');
    await shell.goldLine('five_hour_halt').click();
    await expect(shell.goldText(shell.goldFlyout)).toHaveText(fiveHourLine(80));
  });

  test('both show, the outage’s first, then the week’s, then the five-hour’s, and a held start says the week’s', async ({
    people,
    projects,
    controller,
    timeline,
    shell,
    page,
  }) => {
    // The backend reads the controller answering at its fleet stream's reconnect, whose backoff
    // grows while the outage holds.
    test.setTimeout(90_000);
    const project = await setUp({ people, projects });
    await controller.usage({ seven_day: 0.9, five_hour: 0.75 });
    const work = await startIn(projects, project, 'held');
    await controller.outage(true, 'ingress');
    await timeline.open(project);

    await expect(timeline.item(work).work.cue).toHaveText('Halted at the week’s limit');
    const badges = shell.goldBadges.getByTestId('shell.gold-badges.badge');
    await expect(badges).toHaveCount(3);
    expect(await badges.evaluateAll((each) => each.map((badge) => badge.getAttribute('data-condition')))).toEqual([
      'outage',
      'week_halt',
      'five_hour_halt',
    ]);
    await expect(shell.goldBadge('five_hour_halt')).toHaveAttribute('title', fiveHourLine(75));
    // The week's alone carries an overrule: its badge is a button, the others badges alone.
    await expect(shell.goldBadges.getByRole('button')).toHaveCount(1);
    await expect(shell.goldBadge('week_halt')).toHaveRole('button');
    await shell.goldBadge('week_halt').click();
    await expect(shell.goldText(shell.goldPopover)).toHaveText(weekLine(90));
    await page.keyboard.press('Escape');

    await page.setViewportSize(PHONE);
    const lines = shell.goldBar.getByTestId('shell.gold-bar.line');
    // The phone's frame draws its gold bar once the width has crossed.
    await expect(lines).toHaveCount(3);
    expect(await lines.evaluateAll((each) => each.map((line) => line.getAttribute('data-condition')))).toEqual([
      'outage',
      'week_halt',
      'five_hour_halt',
    ]);
    // Each opens its whole line in its flyout; the week's alone carries an overrule.
    await expect(shell.goldBar.getByRole('button')).toHaveCount(3);
    await shell.goldLine('week_halt').click();
    await expect(shell.goldText(shell.goldFlyout)).toHaveText(weekLine(90));
    await expect(shell.goldOverrule(shell.goldFlyout)).toBeVisible();
    await page.keyboard.press('Escape');
    await shell.goldLine('five_hour_halt').click();
    await expect(shell.goldText(shell.goldFlyout)).toHaveText(fiveHourLine(75));
    await expect(shell.goldFlyout.getByRole('button')).toHaveCount(0);
    await page.keyboard.press('Escape');
    await shell.goldLine('outage').click();
    await expect(shell.goldText(shell.goldFlyout)).toHaveText(/^The controller has been unreachable since /);
    await expect(shell.goldFlyout.getByRole('button')).toHaveCount(0);
  });
});
