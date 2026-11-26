/**
 * The dashboard's words (F160.11), with no page: a time day first in the engine's zone, whatever
 * the zone the spec runs in, the month's short name the page's own and a 24-hour clock, the year
 * where it is not this one; a figure in its format; a place in the address read off its hash; a
 * label cut to its room with the ellipsis, as a measure measures it; what a view draws, in the
 * catalogue's words (F161.4), its time as the time picker shows it collapsed; a bound typed in the
 * time picker, day first or ISO, and the time a view reads, exactly (F162.2). No browser, no
 * backend and no test suite lock: the modules are pure.
 */

import { expect, test } from '@playwright/test';
import { placeOf } from '@/lib/dashboard/address';
import { clip, type Measure } from '@/lib/dashboard/clip';
import { dayTime } from '@/lib/dashboard/dates';
import { describe as describeView, timeWords, type Words } from '@/lib/dashboard/describe';
import type { Catalogue } from '@/lib/dashboard/queries';
import { readState } from '@/lib/dashboard/state';
import { figure, multiple, percent, whole } from '@/lib/dashboard/figures';
import { boundKey, boundText, exactWords, inOrder, parseBound, startedWords } from '@/lib/dashboard/time';

test('a time reads its day and its time of day in the zone given, day first on a 24-hour clock', () => {
  const now = new Date('2026-11-26T12:00:00Z');
  expect(dayTime('2026-11-07T08:52:00Z', 'Europe/Amsterdam', now)).toBe('7 Nov 09:52');
  expect(dayTime('2026-11-07T08:52:00Z', 'America/New_York', now)).toBe('7 Nov 03:52');
  expect(dayTime('2026-09-01T22:05:30Z', 'Europe/Amsterdam', now)).toBe('2 Sep 00:05');
  expect(dayTime('2026-07-14T11:00:00Z', 'Europe/Amsterdam', now)).toBe('14 Jul 13:00');
});

test('a time of another year than now’s in the zone reads its year after its month', () => {
  expect(dayTime('2025-12-31T23:30:00Z', 'Europe/Amsterdam', new Date('2026-11-26T12:00:00Z'))).toBe('1 Jan 00:30');
  expect(dayTime('2025-12-31T22:30:00Z', 'Europe/Amsterdam', new Date('2026-11-26T12:00:00Z'))).toBe('31 Dec 2025 23:30');
});

test('a figure reads in its format', () => {
  expect(figure('usd', 2.285275)).toBe('$2.29');
  expect(figure('usd', 1234.5)).toBe('$1,234.50');
  expect(figure('count', 16)).toBe('16');
  expect(figure('count', 3.2)).toBe('3.2');
  expect(figure('count', 3.25)).toBe('3.25');
  expect(figure('count', 12345)).toBe('12,345');
  expect(figure('tokens', 950)).toBe('950');
  expect(figure('tokens', 1500)).toBe('1.5k');
  expect(figure('tokens', 45_000)).toBe('45k');
  expect(figure('tokens', 2_400_000)).toBe('2.4M');
  expect(figure('seconds', 42)).toBe('42s');
  expect(figure('seconds', 125)).toBe('2m 05s');
  expect(figure('seconds', 4_040)).toBe('1h 07m');
  expect(figure('share', 0.4)).toBe('40%');
  expect(figure('share', 0.045)).toBe('4.5%');
  expect(figure('usd', null)).toBe('–');
  expect(whole(2513)).toBe('2,513');
  expect(percent(0.5157)).toBe('52%');
  expect(multiple(1.0315)).toBe('1.0×');
  expect(multiple(0.9685)).toBe('0.97×');
  expect(multiple(12.4)).toBe('12×');
});

test('a dashboard address names its tab and its state, a link no tab', () => {
  expect(placeOf('#dash')).toEqual({ tab: null, state: null });
  expect(placeOf('#dash/t1')).toEqual({ tab: 't1', state: null });
  expect(placeOf('#dash/t1/t=qw&by=project')).toEqual({ tab: 't1', state: 't=qw&by=project' });
  expect(placeOf('#dash/t=qw&by=project')).toEqual({ tab: null, state: 't=qw&by=project' });
  expect(placeOf('#dash/t1/t=qw&c=repo:org%2Fname')).toEqual({ tab: 't1', state: 't=qw&c=repo:org%2Fname' });
});

test('a label is cut to its room with the ellipsis after its longest start that fits, and kept whole where it fits', () => {
  // Every character 6 pixels wide, a bold one 7.
  const measure: Measure = (text, _size, weight) => text.length * (weight > 400 ? 7 : 6);
  expect(clip('Main thread', 66, measure)).toBe('Main thread');
  expect(clip('Main thread', 65, measure)).toBe('Main thre…');
  expect(clip('Explore · Find where the jars are counted', 90, measure)).toBe('Explore · Find…');
  // The spaces before the cut go with it.
  expect(clip('Turn 1 · brief', 48, measure)).toBe('Turn 1…');
  expect(clip('Main thread', 65, measure, 12, 600)).toBe('Main thr…');
});

/** The catalogue's words a view is described in, as much of each part as the views below name. */
const WORDS: Words = {
  dimensions: {
    part: 'dimensions',
    dimensions: [
      { key: 'project', label: 'Project', group: 'part', base: null },
      { key: 'model', label: 'Model', group: 'attribute', base: null },
      { key: 'qweek', label: 'Quota week', group: 'time', base: null },
      { key: 'turn_seq', label: 'Pilot turn, in the order sent', group: 'order', base: 'pturn' },
      { key: 'pturn', label: 'Pilot turn', group: 'part', base: null },
    ],
  } as unknown as Catalogue,
  measures: {
    part: 'measures',
    figures: [
      { key: 'cost', label: 'Cost', aggregate: 'sum' },
      { key: 'ctx', label: 'Peak context', aggregate: 'max' },
    ],
    aggregates: [{ key: 'median', label: 'Median' }],
    ratios: [{ key: 'overhead', label: 'Overhead ratio' }],
  } as unknown as Catalogue,
  time: {
    part: 'time',
    ranges: [
      { key: 'd7', label: 'Last 7 days' },
      { key: 'qw', label: 'This quota week' },
      { key: 'lqw', label: 'Last quota week' },
      { key: 'all', label: 'All time' },
    ],
    quota_weeks: [
      { starts_at: '2026-11-12T09:00:00Z', week: 46, starts_on: null },
      { starts_at: '2026-11-05T09:00:00Z', week: 45, starts_on: null },
      { starts_at: '2026-11-01T09:00:00Z', week: null, starts_on: '2026-11-01' },
    ],
  } as unknown as Catalogue,
};

const described = (state: string) => describeView(readState(state), WORDS);

test('a view reads what it presents, its time and its measures, each aggregate not its figure’s own after it', () => {
  expect(described('t=all&by=project&m=cost.sum&m=ctx.max&col=none')).toBe('By Project · All time · Cost, Peak context');
  expect(described('t=all&by=model&p=table&m=cost.median&m=r:overhead&col=none')).toBe('Table by Model · All time · Cost (median), Overhead ratio');
  expect(described('t=all&by=project&p=lanes&m=cost.sum&col=none')).toBe('Lanes by Project · All time · Cost');
  expect(described('t=all&by=project&p=time,qweek&m=cost.sum&col=none')).toBe('Over time, by quota week · All time · Cost');
  expect(described('t=all&by=pturn&p=order&m=cost.sum&col=none')).toBe('Pilot turn, in the order sent · All time · Cost');
});

test('a view’s time reads its quota weeks by their numbers, a week cut short by its first day, and a range day first', () => {
  const year = new Date().getFullYear();
  const of = (day: string) => `${day}${year === 2026 ? '' : ' 2026'}`;
  expect(described('t=wk,2026-11-12T09%3A00%3A00Z&by=project&m=cost.sum&col=none')).toBe('By Project · Quota week 46 · Cost');
  expect(described('t=wk,2026-11-05T09%3A00%3A00Z,2026-11-12T09%3A00%3A00Z&by=project&m=cost.sum&col=none')).toBe('By Project · Quota weeks 45, 46 · Cost');
  expect(described('t=wk,2026-11-01T09%3A00%3A00Z&by=project&m=cost.sum&col=none')).toBe(`By Project · Quota week of ${of('1 Nov')} · Cost`);
  expect(described('t=c,2026-11-01T08%3A30,2026-11-07&by=project&m=cost.sum&col=none')).toBe(`By Project · ${of('1 Nov')} 08:30 – ${of('7 Nov')} · Cost`);
  expect(described('t=c,2026-11-01,&by=project&m=cost.sum&col=none')).toBe(`By Project · From ${of('1 Nov')} · Cost`);
  expect(described('t=c,,2026-11-07&by=project&m=cost.sum&col=none')).toBe(`By Project · Until ${of('7 Nov')} · Cost`);
});

test('a view reads a part’s key where the catalogue has not come yet', () => {
  expect(describeView(readState('t=qw&by=project&m=cost.sum&col=none'), { dimensions: undefined, measures: undefined, time: undefined })).toBe('By project · qw · cost');
});

test('a view’s time reads collapsed as this, the last and a picked quota week by its number, a range by its label, a range of one day as that day', () => {
  const year = new Date().getFullYear();
  const of = (day: string) => `${day}${year === 2026 ? '' : ' 2026'}`;
  const time = (state: string) => timeWords(readState(state).time, WORDS);
  expect(time('t=qw&by=project')).toBe('Quota week 46');
  expect(time('t=lqw&by=project')).toBe('Quota week 45');
  expect(time('t=d7&by=project')).toBe('Last 7 days');
  expect(time('t=wk,2026-11-05T09%3A00%3A00Z&by=project')).toBe('Quota week 45');
  expect(time('t=c,2026-11-07,2026-11-13&by=project')).toBe(`${of('7 Nov')} – ${of('13 Nov')}`);
  expect(time('t=c,2026-11-07,2026-11-07&by=project')).toBe(of('7 Nov'));
  expect(time('t=c,2026-11-07T09%3A00,2026-11-07T17%3A00&by=project')).toBe(`${of('7 Nov')} 09:00 – ${of('7 Nov')} 17:00`);
  // The running week cut short, with no Thursday in it.
  const cut: Words = { ...WORDS, time: { ...WORDS.time!, quota_weeks: WORDS.time!.quota_weeks!.slice(2) } };
  expect(timeWords(readState('t=qw&by=project').time, cut)).toBe(`Quota week of ${of('1 Nov')}`);
});

test('a bound is typed day first or ISO, a time of day after it or none, a day with no year this year’s; anything else reads as none', () => {
  const read = (text: string) => {
    const bound = parseBound(text, 2026);
    return bound == null ? bound : boundKey(bound);
  };
  expect(read('12 Nov 2026')).toBe('2026-11-12');
  expect(read('12 november 2026')).toBe('2026-11-12');
  expect(read('12 Nov')).toBe('2026-11-12');
  expect(read('12-11-2026')).toBe('2026-11-12');
  expect(read('12/11')).toBe('2026-11-12');
  expect(read('12.11.26')).toBe('2026-11-12');
  expect(read('2026-11-12')).toBe('2026-11-12');
  expect(read(' 12 Nov 2026  11:00 ')).toBe('2026-11-12T11:00');
  expect(read('2026-11-12T08:05')).toBe('2026-11-12T08:05');
  expect(read('12/11 8.30')).toBe('2026-11-12T08:30');
  expect(read('3 okt')).toBe('2026-10-03');
  expect(read('')).toBeNull();
  expect(read('   ')).toBeNull();
  for (const wrong of ['31 Nov 2026', '2026-13-01', '12 Nox', 'yesterday', '12 Nov 24:00', '12 Nov 11:60', '11:00']) expect(read(wrong), wrong).toBeUndefined();
  expect(boundText(parseBound('2026-11-12', 2026)!)).toBe('12 Nov 2026');
  expect(boundText(parseBound('12/11 8:30', 2026)!)).toBe('12 Nov 2026 08:30');
});

test('a range holds a moment where it starts before it ends, an end that is a day holding it whole', () => {
  const bound = (text: string) => parseBound(text, 2026)!;
  expect(inOrder(bound('12 Nov'), bound('12 Nov'))).toBe(true);
  expect(inOrder(bound('12 Nov 17:00'), bound('12 Nov'))).toBe(true);
  expect(inOrder(bound('12 Nov 11:00'), bound('12 Nov 11:00'))).toBe(false);
  expect(inOrder(bound('13 Nov'), bound('12 Nov'))).toBe(false);
  expect(inOrder(bound('13 Nov'), bound('13 Nov 00:00'))).toBe(false);
  expect(inOrder(bound('13 Nov'), bound('13 Nov 00:01'))).toBe(true);
});

test('the time a view reads reads exactly in the zone, two spans that touch one, an end past now “now” but for a range’s own', () => {
  const now = new Date('2026-11-27T12:00:00Z');
  const zone = 'Europe/Amsterdam';
  expect(exactWords(null, zone, false, now)).toBe('All time');
  expect(exactWords([], zone, false, now)).toBeNull();
  expect(exactWords([{ start: '2026-11-26T10:00:00Z', end: '2026-12-03T10:00:00Z' }], zone, false, now)).toBe('Thu 26 Nov 2026 11:00 – now, Europe/Amsterdam');
  expect(
    exactWords(
      [
        { start: '2026-11-12T10:00:00Z', end: '2026-11-19T10:00:00Z' },
        { start: '2026-11-19T10:00:00Z', end: '2026-11-26T10:00:00Z' },
      ],
      zone,
      false,
      now,
    ),
  ).toBe('Thu 12 Nov 2026 11:00 – Thu 26 Nov 2026 11:00, Europe/Amsterdam');
  expect(exactWords([{ start: null, end: '2026-12-07T23:00:00Z' }], zone, true, now)).toBe('The start – Tue 8 Dec 2026 00:00, Europe/Amsterdam');
  expect(startedWords('2026-11-26T10:00:00Z', zone, now)).toBe('Thu 26 Nov 11:00');
  expect(startedWords('2025-12-31T23:30:00Z', zone, now)).toBe('Thu 1 Jan 00:30');
});
