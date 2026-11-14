/**
 * A done work item's full debrief (F26.10): Full debrief in the debrief's head, in reach however
 * long the debrief runs, shows it at its address under the debrief's, off a phone in the same frame,
 * taller, with no entry in the browser's history, its head's arrow back to the debrief; on a phone
 * a view pushed over the debrief's. First its sections as a table, a row per section in the order
 * given — the same name further on a row of its own — its name on one line cut short with an
 * ellipsis, its rounds and its time, a row going to its section; then the sections, each entry in
 * the order given with its role and its time and nothing that labels it: its words as prose, a
 * pass or a fail as a muted line, the fail in the warning's colour, an entry with neither muted;
 * the entry with a why opening its round with it. The sections, their rounds and their times are
 * the read's (D159).
 */

import { randomUUID } from 'node:crypto';
import type { Locator } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { cssColour } from '../support/contrast';
import type { Controller } from '../support/controller';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import { projectAddress, type DebriefEntry, type Projects } from '../support/projects';
import { debriefAddress, fullDebriefAddress, type DebriefPage } from '../support/page-objects/debrief-page';

const TITLE = 'Surveying the stylesheets';
const LONG = 'P1 · The schema and its migration, with a name long enough to be cut short in the table';

// Invented accounts, in the shapes the workflow gives: a section of its own, one of two rounds, an
// entry with neither words nor a result, a check's results, and a check's name again further on.
const ENTRIES: DebriefEntry[] = [
  { section: 'The preparer', round: 1, role: 'plan-preparer', duration: 1020, words: 'A clear slice, which made this pleasant.' },
  { section: LONG, round: 1, role: 'code-writer', duration: 2400, words: 'The migration went in **cleanly**.\n\nThe review found one thing.' },
  { section: LONG, round: 1, role: 'code-reviewer', duration: 600, words: 'One finding: the downgrade kept the column.' },
  { section: LONG, round: 2, role: 'code-writer', duration: 300, words: 'A small fix, and a fair one.', why: 'The reviewer found the downgrade kept the column' },
  { section: 'P2 · The screens', round: 1, role: 'code-writer', duration: 6000 },
  { section: 'Completion check', round: 1, role: 'sweep', duration: 540, passed: true },
  { section: 'Completion check', round: 1, role: 'consult', duration: 45, words: 'It felt done to me.' },
  { section: 'Completion check', round: 2, role: 'sweep', duration: 1140, passed: false, why: 'The consult committed a fix, so the sweep runs again' },
  { section: 'Completion check', round: 2, role: 'test-fixer', duration: 1380, words: 'A longer wait settled it, though it felt like a patch.' },
  { section: 'P3 · An appended phase', round: 1, role: 'code-writer', duration: 900, words: 'Quick and plain.' },
  { section: 'Completion check', round: 4, role: 'sweep', duration: 0, passed: true, why: 'Red again: the consult added P3' },
];

const NAMES = ['The preparer', LONG, 'P2 · The screens', 'Completion check', 'P3 · An appended phase', 'Completion check'];

interface Fixtures {
  people: People;
  projects: Projects;
  controller: Controller;
}

/** A project with a work item done whose session gave a debrief of `entries`. */
async function debriefed({ people, projects, controller }: Fixtures, words = 'It went well, if slowly.', entries = ENTRIES) {
  const me = await people.signIn();
  const project = await projects.make({ name: makeUnique('Debrief'), members: [me.handle!] });
  const work = await projects.startWork(project, { title: TITLE, brief: 'Survey the stylesheets.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  const { id: environment } = await projects.environment(project, work);
  await projects.debrief(work, words, entries);
  await controller.finish(environment, 'claude-1');
  await expect.poll(async () => (await projects.item(project, work)).done?.cause).toBe('turn_ended');
  return { project, work };
}

/** How far a section's top stands below its body's. */
async function offsetIn(debrief: DebriefPage, section: Locator): Promise<number> {
  const [at, body] = await Promise.all([section.boundingBox(), debrief.body.boundingBox()]);
  return at!.y - body!.y;
}

test.describe('Off a phone, the full debrief', () => {
  // Tall enough that the full debrief's frame stands taller than the session log's.
  test.use({ viewport: { width: 1280, height: 1000 } });

  test('is the debrief’s Full debrief, in its head however long the debrief runs; it shows in the same frame, taller, with no entry in the history: “Full debrief” over the item’s title, its arrow back to the debrief; Esc closes it and gives the focus back to the Debrief', async ({
    page,
    people,
    projects,
    controller,
    timeline,
    debrief,
  }) => {
    const words = Array.from({ length: 40 }, (_, at) => `Paragraph ${at + 1} of how it went.`).join('\n\n');
    const { project, work } = await debriefed({ people, projects, controller }, words);
    await timeline.open(project);
    const item = timeline.item(work);
    const entries = await page.evaluate(() => history.length);

    await item.debrief.click();
    await expect(debrief.text).toBeVisible();
    await expect(debrief.full).toHaveText('Full debrief');
    await expect(debrief.full).toHaveAttribute('href', fullDebriefAddress(project, work));
    await expect(debrief.full.locator('svg.lucide-chevron-right')).toBeVisible();
    const frame = (await debrief.overlay.boundingBox())!;
    // In the head, in reach at the debrief's end.
    await debrief.body.evaluate((body) => (body.scrollTop = body.scrollHeight));
    await expect(debrief.text.locator('p').last()).toBeInViewport();
    const [full, head] = await Promise.all([debrief.full.boundingBox(), debrief.head.boundingBox()]);
    expect(full!.y).toBeGreaterThanOrEqual(head!.y);
    expect(full!.y + full!.height).toBeLessThanOrEqual(head!.y + head!.height);

    await debrief.full.click();
    await expect(page).toHaveURL(fullDebriefAddress(project, work));
    await expect(debrief.title).toHaveText('Full debrief');
    await expect(debrief.title.locator('svg.lucide-notebook-pen')).toBeVisible();
    await expect(debrief.item).toHaveText(TITLE);
    await expect(debrief.ended).toHaveCount(0);
    await expect(debrief.full).toHaveCount(0);
    await expect(debrief.text).toHaveCount(0);
    await expect(debrief.rows).toHaveCount(NAMES.length);
    await expect(debrief.overlay).toBeFocused();
    // Its body starts at its top.
    expect(await debrief.body.evaluate((body) => body.scrollTop)).toBe(0);
    const tall = (await debrief.overlay.boundingBox())!;
    expect(tall.x).toBe(frame.x);
    expect(tall.width).toBe(frame.width);
    expect(frame.height).toBe(560);
    expect(tall.height).toBe(640);
    // The arrow stands left of the titles, the cross at the head's end.
    await expect(debrief.back).toHaveAttribute('title', 'Back to the debrief');
    await expect(debrief.back).toHaveAccessibleName('Back');
    await expect(debrief.back.locator('svg.lucide-arrow-left')).toBeVisible();
    const [back, title, close] = await Promise.all([debrief.back, debrief.title, debrief.close].map(async (each) => (await each.boundingBox())!));
    expect(back.x + back.width).toBeLessThanOrEqual(title.x);
    expect(close.x).toBeGreaterThan(title.x + title.width);
    expect(await page.evaluate(() => history.length)).toBe(entries);

    await debrief.back.click();
    await expect(page).toHaveURL(debriefAddress(project, work));
    await expect(debrief.text).toBeVisible();
    await expect(debrief.back).toHaveCount(0);
    expect(await debrief.overlay.boundingBox()).toEqual(frame);
    expect(await page.evaluate(() => history.length)).toBe(entries);

    await debrief.full.click();
    await expect(debrief.rows).toHaveCount(NAMES.length);
    await page.keyboard.press('Escape');
    await expect(debrief.overlay).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(project));
    await expect(item.debrief).toBeFocused();
    expect(await page.evaluate(() => history.length)).toBe(entries);
  });

  test('opens at its own address; a done work item’s whose session gave none, or no work item’s, reads “The debrief did not load”', async ({
    page,
    people,
    projects,
    controller,
    debrief,
  }) => {
    const { project, work } = await debriefed({ people, projects, controller });
    await page.goto(fullDebriefAddress(project, work));
    await expect(debrief.title).toHaveText('Full debrief');
    await expect(debrief.rowNames).toHaveText(NAMES);
    await debrief.close.click();
    await expect(page).toHaveURL(projectAddress(project));

    const other = await projects.startWork(project, { title: 'Another survey', brief: 'Survey it again.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(project, other)).state).toBe('running');
    const { id: environment } = await projects.environment(project, other);
    await controller.finish(environment, 'claude-1');
    await expect.poll(async () => (await projects.item(project, other)).done?.cause).toBe('turn_ended');
    await page.goto(fullDebriefAddress(project, other));
    await expect(debrief.failed).toHaveText('The debrief did not load.');
    await page.goto(fullDebriefAddress(project, randomUUID()));
    await expect(debrief.failed).toHaveText('The debrief did not load.');
  });

  test('starts with its sections as a table, a row each in the order given, the same name further on a row of its own: its name on one line, cut short with an ellipsis, its whole name its tooltip; its rounds, more than one in bold; its time; a row, or its name from the keyboard, goes to its section', async ({
    page,
    people,
    projects,
    controller,
    debrief,
  }) => {
    const { project, work } = await debriefed({ people, projects, controller });
    await page.goto(fullDebriefAddress(project, work));

    await expect(debrief.index.locator('th')).toHaveText(['Section', 'Rounds', 'Time']);
    await expect(debrief.rowNames).toHaveText(NAMES);
    await expect(debrief.rowRounds).toHaveText(['1', '2', '1', '2', '1', '1']);
    await expect(debrief.rowRounds.locator('b')).toHaveText(['2', '2']);
    await expect(debrief.rowTimes).toHaveText(['17m', '55m', '1h 40m', '52m', '15m', '<1m']);
    // The table goes before the sections.
    const [index, first] = await Promise.all([debrief.index.boundingBox(), debrief.sections.first().boundingBox()]);
    expect(index!.y + index!.height).toBeLessThanOrEqual(first!.y);

    const long = debrief.rowNames.nth(1);
    await expect(debrief.rows.nth(1).locator('td').first()).toHaveAttribute('title', LONG);
    await expect(long).toHaveCSS('text-overflow', 'ellipsis');
    await expect(long).toHaveCSS('white-space', 'nowrap');
    expect(await long.evaluate((name) => name.scrollWidth > name.clientWidth)).toBe(true);
    // One line, as high as a short name's.
    const [cut, short] = await Promise.all([long.boundingBox(), debrief.rowNames.first().boundingBox()]);
    expect(cut!.height).toBe(short!.height);
    // The table fits the frame: the numbers' columns stand in it.
    const [table, body] = await Promise.all([debrief.index.boundingBox(), debrief.body.boundingBox()]);
    expect(table!.x + table!.width).toBeLessThanOrEqual(body!.x + body!.width);

    // Its time's cell goes there as its name does.
    await debrief.rowTimes.nth(1).click();
    await expect.poll(() => offsetIn(debrief, debrief.sections.nth(1))).toBeCloseTo(8, 0);
    await debrief.body.evaluate((each) => (each.scrollTop = 0));
    await debrief.rowNames.first().focus();
    await page.keyboard.press('Enter');
    await expect.poll(() => offsetIn(debrief, debrief.sections.first())).toBeCloseTo(8, 0);
  });

  test('then shows its sections, each entry in the order given with its role and its time and nothing that labels it: its words as prose, a pass or a fail as a muted line, the fail in the warning’s colour in both themes, an entry with neither muted; the entry with a why opens its round with it', async ({
    page,
    people,
    projects,
    controller,
    debrief,
  }) => {
    const { project, work } = await debriefed({ people, projects, controller });
    await page.goto(fullDebriefAddress(project, work));

    await expect(debrief.sectionNames).toHaveText(NAMES);
    const [preparer, phase, timedOut, check, appended, again] = NAMES.map((_, at) => debrief.sections.nth(at));

    await expect(debrief.entries(preparer).getByTestId('debrief.entry.role')).toHaveText(['plan-preparer']);
    await expect(debrief.entries(preparer).getByTestId('debrief.entry.time')).toHaveText(['17m']);

    // Words: the role in bold, then the time, then the words as prose.
    const entries = debrief.entries(phase);
    await expect(entries.getByTestId('debrief.entry.role')).toHaveText(['code-writer', 'code-reviewer', 'code-writer']);
    await expect(entries.getByTestId('debrief.entry.time')).toHaveText(['40m', '10m', '5m']);
    await expect(entries.first().locator('.db-text p')).toHaveText(['The migration went in cleanly.', 'The review found one thing.']);
    await expect(entries.first().locator('.db-text strong')).toHaveText('cleanly');
    await expect(entries.first().locator('.db-who')).toHaveText(/^code-writer\s*40m$/);
    await expect(entries.first().getByTestId('debrief.entry.role')).toHaveCSS('font-weight', '700');
    await expect(entries.getByTestId('debrief.entry.result')).toHaveCount(0);
    // Round 2's why stands before the entry that opens it, and only there.
    expect(await debrief.lineKinds(phase)).toEqual(['entry', 'entry', 'round', 'entry']);
    await expect(phase.getByTestId('debrief.round')).toHaveText(/^Round 2\s*The reviewer found the downgrade kept the column$/);
    await expect(phase.getByTestId('debrief.round.why')).toHaveText('The reviewer found the downgrade kept the column');
    expect(await debrief.lineKinds(preparer)).toEqual(['entry']);

    // Neither words nor a result: its role and its time alone.
    const silent = debrief.entries(timedOut);
    await expect(silent.locator('.db-who')).toHaveText(/^code-writer\s*1h 40m$/);
    await expect(silent.locator('.db-text')).toHaveCount(0);

    // A check: results and words, round 2 opened by its why.
    const checks = debrief.entries(check);
    await expect(checks.getByTestId('debrief.entry.role')).toHaveText(['sweep', 'consult', 'sweep', 'test-fixer']);
    await expect(checks.getByTestId('debrief.entry.time')).toHaveText(['9m', '<1m', '19m', '23m']);
    await expect(checks.getByTestId('debrief.entry.result')).toHaveText(['passed', 'failed']);
    await expect(checks.nth(0).locator('.db-who')).toHaveText(/^sweep\s*9m\s*passed$/);
    await expect(checks.nth(0).locator('.db-text')).toHaveCount(0);
    expect(await debrief.lineKinds(check)).toEqual(['entry', 'entry', 'round', 'entry', 'entry']);
    await expect(check.getByTestId('debrief.round.why')).toHaveText('The consult committed a fix, so the sweep runs again');

    await expect(debrief.entries(appended).locator('.db-text')).toHaveText('Quick and plain.');
    // The same name further on is a section of its own, its round as given.
    expect(await debrief.lineKinds(again)).toEqual(['round', 'entry']);
    await expect(again.getByTestId('debrief.round')).toHaveText(/^Round 4\s*Red again: the consult added P3$/);
    await expect(debrief.entries(again).locator('.db-who')).toHaveText(/^sweep\s*<1m\s*passed$/);

    for (const scheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await expect(page.locator('html')).toHaveAttribute('data-theme', scheme);
      const [foreground, muted, warning] = await Promise.all([
        cssColour(page, 'hsl(var(--foreground))'),
        cssColour(page, 'hsl(var(--muted-foreground))'),
        cssColour(page, 'hsl(var(--warning-text))'),
      ]);
      expect(muted).not.toBe(warning);
      await expect(entries.first().getByTestId('debrief.entry.role')).toHaveCSS('color', foreground);
      await expect(entries.first().getByTestId('debrief.entry.time')).toHaveCSS('color', muted);
      await expect(silent.getByTestId('debrief.entry.role')).toHaveCSS('color', muted);
      await expect(checks.nth(0).getByTestId('debrief.entry.role')).toHaveCSS('color', muted);
      await expect(checks.nth(0).getByTestId('debrief.entry.result')).toHaveCSS('color', muted);
      await expect(checks.nth(2).getByTestId('debrief.entry.result')).toHaveCSS('color', warning);
      await expect(phase.getByTestId('debrief.round.why')).toHaveCSS('color', foreground);
      await expect(phase.getByTestId('debrief.round').locator('.round-n')).toHaveCSS('color', muted);
    }
  });
});

test.describe('On a phone, the full debrief', () => {
  const PHONE = { width: 390, height: 844 };
  test.use({ viewport: PHONE, hasTouch: true });

  test('is a view pushed over the debrief’s at the debrief’s Full debrief, over the whole screen, its arrow back to the debrief; its table fits the screen and a row goes to its section', async ({
    page,
    people,
    projects,
    controller,
    timeline,
    debrief,
    projectHead,
    phoneTabs,
  }) => {
    const { project, work } = await debriefed({ people, projects, controller });
    await timeline.open(project);

    await timeline.item(work).debrief.tap();
    await expect(page).toHaveURL(debriefAddress(project, work));
    await expect(debrief.full).toBeVisible();
    await debrief.full.tap();
    await expect(page).toHaveURL(fullDebriefAddress(project, work));
    await expect(debrief.title).toHaveText('Full debrief');
    await expect(debrief.close).toHaveCount(0);
    await expect(debrief.back).toHaveAttribute('title', 'Back');
    const [view, head, tabs] = await Promise.all([debrief.overlay, projectHead.root, phoneTabs.root].map(async (each) => (await each.boundingBox())!));
    expect(view).toMatchObject({ x: 0, y: head.y, width: PHONE.width });
    expect(view.y + view.height).toBe(tabs.y + tabs.height);

    const [table, body] = await Promise.all([debrief.index.boundingBox(), debrief.body.boundingBox()]);
    expect(table!.x + table!.width).toBeLessThanOrEqual(body!.x + body!.width);
    expect(await debrief.rowNames.nth(1).evaluate((name) => name.scrollWidth > name.clientWidth)).toBe(true);
    await debrief.rows.nth(1).tap();
    await expect.poll(() => offsetIn(debrief, debrief.sections.nth(1))).toBeCloseTo(8, 0);

    await debrief.back.tap();
    await expect(page).toHaveURL(debriefAddress(project, work));
    await expect(debrief.text).toHaveText('It went well, if slowly.');
    await debrief.back.tap();
    await expect(debrief.overlay).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(project));
  });
});
