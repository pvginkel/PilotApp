/**
 * The dashboard's words (F160.11), with no page: a time day first in the engine's zone, whatever
 * the zone the spec runs in, the month's short name the page's own and a 24-hour clock, the year
 * where it is not this one; a figure in its format; a place in the address read off its hash; a
 * label cut to its room with the ellipsis, as a measure measures it. No browser, no backend and no
 * test suite lock: the modules are pure.
 */

import { expect, test } from '@playwright/test';
import { placeOf } from '@/lib/dashboard/address';
import { clip, type Measure } from '@/lib/dashboard/clip';
import { dayTime } from '@/lib/dashboard/dates';
import { figure, multiple, percent, whole } from '@/lib/dashboard/figures';

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
