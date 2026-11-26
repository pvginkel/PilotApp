/**
 * The view's time in the global toolbar (F162.1, F162.2): collapsed, its words, "Quota week 46",
 * "Last 7 days", "7 Nov – 13 Nov", its title the time the view reads exactly; its picker, From and
 * To over a month's calendar with Apply, typed day first or ISO, a time of day optional, an empty
 * one an open bound; a pick on the calendar keeping a time of day only where one was typed; at the
 * right the catalogue's ranges, then its quota weeks, newest first; at the foot the zone and when
 * the running quota week started. A time set is a new entry (F160.4) and reads the view again. The
 * figures are the tally's (`TALLY`), on two projects of the spec's own, over the 4,040 s before its
 * load.
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import type { Collection } from '../support/collection';
import { makeUnique } from '../support/helpers';
import { dashboardAddress } from '../support/page-objects/dashboard-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';
import type { components } from '@/lib/api/generated/types';

type Catalogue = components['schemas']['CatalogueResponseSchema.b67cf98'];

const ZONE = 'Europe/Amsterdam';
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

const historyLength = (page: Page) => page.evaluate(() => history.length);

/** The moment `days` days before now. */
const daysAgo = (days: number) => new Date(new Date().getTime() - days * 86_400_000);

/** An instant's wall time in the engine's zone, Europe/Amsterdam by default. */
function amsterdam(at: Date) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', { timeZone: ZONE, hourCycle: 'h23', weekday: 'short', year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      .formatToParts(at)
      .map((part) => [part.type, part.value]),
  );
  return { weekday: parts.weekday, year: Number(parts.year), month: Number(parts.month), day: Number(parts.day), clock: `${parts.hour}:${parts.minute}` };
}

/** A day as the page words it, the year where it is not this one: "7 Nov". */
const dayWords = (year: number, month: number, day: number) => `${day} ${MONTHS[month - 1]}${year === amsterdam(new Date()).year ? '' : ` ${year}`}`;

/** The tally loaded on two projects of the person's: the first's id, and the chip that keeps them. */
async function tally(people: People, projects: Projects, collection: Collection) {
  const me = await people.signIn();
  const recipeBox = await projects.make({ name: makeUnique('Recipes'), members: [me.handle!] });
  const bikeLog = await projects.make({ name: makeUnique('Bikes'), members: [me.handle!] });
  await collection.loadScenario('tally', { 'recipe-box': recipeBox, 'bike-log': bikeLog });
  return { recipeBox, chip: `c=project:${[recipeBox, bikeLog].sort().join(',')}` };
}

/** The catalogue's time, as the server holds it now. */
async function timePart(page: Page, backendUrl: string): Promise<Catalogue> {
  const response = await page.request.get(`${backendUrl}/api/dashboard/catalogue?part=time`);
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()) as Catalogue;
}

/** A quota week in the page's words: its number, or the day a week cut short starts on. */
function weekWords(week: NonNullable<Catalogue['quota_weeks']>[number]): string {
  if (week.week !== null) return String(week.week);
  const [year, month, day] = week.starts_on!.split('-').map(Number);
  return `of ${dayWords(year, month, day)}`;
}

/** The time part of the address. */
const timeOf = (page: Page) => new URL(page.url()).hash.match(/[/&]t=([^&]*)/)?.[1];

test.describe('The view’s time', () => {
  test('reads collapsed in a few words, its title the time the view reads exactly', async ({ page, backendUrl, people, projects, collection, shell, dashboard }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    const running = (await timePart(page, backendUrl)).quota_weeks!.find((week) => week.running)!;
    const year = amsterdam(new Date()).year;
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);

    await expect(dashboard.allValues).toHaveText(['$2.29']);
    await expect(dashboard.timeWords).toHaveText('All time');
    await expect(dashboard.time).toHaveAttribute('title', 'All time');

    await dashboard.go(dashboardAddress(`t=d7&by=project&m=cost.sum&${chip}`));
    await expect(dashboard.timeWords).toHaveText('Last 7 days');
    const start = amsterdam(daysAgo(6));
    await expect(dashboard.time).toHaveAttribute('title', `${start.weekday} ${start.day} ${MONTHS[start.month - 1]} ${start.year} 00:00 – now, ${ZONE}`);

    await dashboard.go(dashboardAddress(`t=qw&by=project&m=cost.sum&${chip}`));
    await expect(dashboard.timeWords).toHaveText(`Quota week ${weekWords(running)}`);

    await dashboard.go(dashboardAddress(`t=c,${year}-01-07,${year}-01-13&by=project&m=cost.sum&${chip}`));
    await expect(dashboard.timeWords).toHaveText('7 Jan – 13 Jan');
  });

  test('opens on the catalogue’s ranges, then its quota weeks newest first, the zone and when the running week started at its foot; a pick of one is a new entry, the view read again', async ({
    page,
    backendUrl,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    const part = await timePart(page, backendUrl);
    const weeks = part.quota_weeks!;
    const running = weeks.find((week) => week.running)!;
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await expect(dashboard.allValues).toHaveText(['$2.29']);

    await dashboard.time.click();
    await expect(dashboard.timePicker).toBeVisible();
    await expect(dashboard.ranges).toHaveText(part.ranges!.map((range) => range.label));
    await expect(dashboard.ranges.filter({ hasText: 'All time' })).toHaveAttribute('aria-pressed', 'true');
    await expect(dashboard.weeks).toHaveCount(weeks.length);
    await expect(dashboard.weeks.first()).toContainText(`Week ${weekWords(weeks[0])}`);
    expect(weeks[0].running).toBe(true);
    const started = amsterdam(new Date(running.starts_at));
    await expect(dashboard.timeFoot).toContainText(`Times in ${ZONE}`);
    await expect(dashboard.timeFoot).toContainText(`This quota week started ${started.weekday} ${dayWords(started.year, started.month, started.day)} ${started.clock}`);
    // All time has no bound: the fields open empty, and Apply has no range to apply.
    await expect(dashboard.from).toHaveValue('');
    await expect(dashboard.to).toHaveValue('');
    await expect(dashboard.apply).toBeDisabled();

    const entries = await historyLength(page);
    const reads = dashboard.rowsReads();
    await dashboard.ranges.filter({ hasText: 'Last 2 days' }).click();

    await expect(dashboard.timePicker).toHaveCount(0);
    await expect(dashboard.timeWords).toHaveText('Last 2 days');
    await expect.poll(() => timeOf(page)).toBe('d2');
    expect(await historyLength(page)).toBe(entries + 1);
    await expect.poll(() => reads().some((state) => state.startsWith('t=d2&'))).toBe(true);
    await expect(dashboard.allValues).toHaveText(['$2.29']);

    await dashboard.time.click();
    await dashboard.weeks.first().click();
    await expect.poll(() => timeOf(page)).toBe(`wk,${encodeURIComponent(running.starts_at)}`);
    await expect(dashboard.timeWords).toHaveText(`Quota week ${weekWords(running)}`);
    await dashboard.time.click();
    await expect(dashboard.weeks.first()).toHaveAttribute('aria-pressed', 'true');
    await expect(dashboard.ranges.filter({ hasText: 'Last 2 days' })).toHaveAttribute('aria-pressed', 'false');
    await page.keyboard.press('Escape');
    await expect(dashboard.timePicker).toHaveCount(0);

    await page.goBack();
    await expect(dashboard.timeWords).toHaveText('Last 2 days');
  });

  test('takes From and To typed day first or ISO, a time of day optional, an empty one an open bound, and refuses neither and a range that ends before it starts', async ({
    page,
    people,
    projects,
    collection,
    shell,
    dashboard,
  }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    const today = amsterdam(new Date());
    const before = amsterdam(daysAgo(3));
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=all&by=project&m=cost.sum&${chip}`)}`);
    await expect(dashboard.allValues).toHaveText(['$2.29']);

    await dashboard.time.click();
    await dashboard.from.fill(`${before.day}/${before.month}/${before.year}`);
    await expect(dashboard.apply).toBeEnabled();
    await dashboard.apply.click();

    const pad = (value: number) => String(value).padStart(2, '0');
    const iso = `${before.year}-${pad(before.month)}-${pad(before.day)}`;
    await expect.poll(() => timeOf(page)).toBe(`c,${iso},`);
    await expect(dashboard.timeWords).toHaveText(`From ${dayWords(before.year, before.month, before.day)}`);
    await expect(dashboard.allValues).toHaveText(['$2.29']);

    // A range opens on its own bounds, each as a field shows it.
    await dashboard.time.click();
    await expect(dashboard.from).toHaveValue(`${before.day} ${MONTHS[before.month - 1]} ${before.year}`);
    await expect(dashboard.to).toHaveValue('');
    await dashboard.from.fill('');
    await expect(dashboard.apply).toBeDisabled();
    await dashboard.to.fill('nonsense');
    await expect(dashboard.to).toHaveAttribute('aria-invalid', 'true');
    await expect(dashboard.apply).toBeDisabled();
    await dashboard.from.fill(`${today.year}-${pad(today.month)}-${pad(today.day)} 08:30`);
    await dashboard.to.fill(`${before.day} ${MONTHS[before.month - 1]}`);
    await expect(dashboard.from).toHaveAttribute('aria-invalid', 'false');
    await expect(dashboard.to).toHaveAttribute('aria-invalid', before.year === today.year ? 'true' : 'false');
    await dashboard.from.fill('');
    await dashboard.to.fill('2 Jan 2001 17:45');
    await expect(dashboard.to).toHaveAttribute('aria-invalid', 'false');
    await dashboard.to.press('Enter');

    await expect.poll(() => timeOf(page)).toBe('c,,2001-01-02T17%3A45');
    await expect(dashboard.timeWords).toHaveText('Until 2 Jan 2001 17:45');
    await expect(dashboard.empty).toBeVisible();
  });

  test('picks two days on the calendar, the earlier the start, each field keeping a time of day only where one was typed', async ({ page, people, projects, collection, shell, dashboard }) => {
    const { recipeBox, chip } = await tally(people, projects, collection);
    const today = amsterdam(new Date());
    const last = today.month === 1 ? { year: today.year - 1, month: 12 } : { year: today.year, month: today.month - 1 };
    const named = (day: number) => `${day} ${MONTHS[last.month - 1]} ${last.year}`;
    await shell.open(`${projectAddress(recipeBox)}${dashboardAddress(`t=d7&by=project&m=cost.sum&${chip}`)}`);
    await expect(dashboard.allValues).toHaveText(['$2.29']);

    // A range of the catalogue's opens on its bounds to the minute, its end now: a pick drops their times.
    await dashboard.time.click();
    const start = amsterdam(daysAgo(6));
    await expect(dashboard.from).toHaveValue(`${start.day} ${MONTHS[start.month - 1]} ${start.year} 00:00`);
    await expect(dashboard.month).toHaveText(`${MONTH_NAMES[today.month - 1]} ${today.year}`);
    await expect(dashboard.monthAfter).toBeDisabled();
    await expect(dashboard.day(today.day)).toHaveClass(/\btoday\b/);
    if (today.day < 28) await expect(dashboard.day(today.day + 1)).toBeDisabled();
    await dashboard.monthBefore.click();
    await expect(dashboard.month).toHaveText(`${MONTH_NAMES[last.month - 1]} ${last.year}`);
    await dashboard.day(12).click();
    await dashboard.day(10).click();
    await expect(dashboard.from).toHaveValue(named(10));
    await expect(dashboard.to).toHaveValue(named(12));
    for (const day of [10, 12]) await expect(dashboard.day(day)).toHaveAttribute('aria-pressed', 'true');
    await expect(dashboard.day(11)).toHaveClass(/\bin\b/);
    await expect(dashboard.day(13)).not.toHaveClass(/\bin\b/);

    // A time of day typed in From is kept by a pick; To, with none typed, takes the day whole.
    await dashboard.from.fill(`1 ${MONTHS[last.month - 1]} ${last.year} 08:30`);
    await dashboard.day(9).click();
    await dashboard.day(5).click();
    await expect(dashboard.from).toHaveValue(`${named(5)} 08:30`);
    await expect(dashboard.to).toHaveValue(named(9));
    const entries = await historyLength(page);
    await dashboard.apply.click();

    const pad = (value: number) => String(value).padStart(2, '0');
    const month = `${last.year}-${pad(last.month)}`;
    await expect.poll(() => timeOf(page)).toBe(`c,${month}-05T08%3A30,${month}-09`);
    expect(await historyLength(page)).toBe(entries + 1);
    await expect(dashboard.timeWords).toHaveText(`${dayWords(last.year, last.month, 5)} 08:30 – ${dayWords(last.year, last.month, 9)}`);
  });
});
