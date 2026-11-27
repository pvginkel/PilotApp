/**
 * The card's head's rules on the page (F163.2, F163.3, F163.7), held with no page, the modules being
 * pure. By's list: the parts and the attributes in the catalogue's order, each its count once it has
 * come, those with one value or none hidden behind "n hidden" and shown muted where the list is
 * unfolded or searched, the By at hand and a favorite never hidden, the favorites rising to
 * Favorites in the list's own order. Color's: By's with no counts and none hidden, None and Token
 * kind under a rule after it, None taking no star. A By picked lets go of the sort and the drawer's
 * row, a series in order or lanes the By cannot have falling back to rows; a presentation picked
 * keeps the sort but a series' on its axis; a color picked lets go of its values lit. The table's
 * text: every row, the All row first, each measure's figure and its n, the share, the color's split,
 * the instant where the By's values have one, tab-separated or comma-separated and quoted. No
 * browser, no backend.
 */

import { expect, test } from '@playwright/test';
import { byList, byPicked, colored, colorList, presented, type Group } from '@/lib/dashboard/head';
import type { Catalogue } from '@/lib/dashboard/queries';
import type { Rows } from '@/lib/dashboard/rows-layout';
import { readState, writeState } from '@/lib/dashboard/state';
import { tableText } from '@/lib/dashboard/table';

type Dimension = NonNullable<Catalogue['dimensions']>[number];

/** A dimension of the catalogue's, as much of it as the rules read. */
function dimension(key: string, group: Dimension['group'], more: Partial<Dimension> = {}): Dimension {
  return { key, label: key, group, line: `${key}'s line`, null: `(No ${key})`, facts: ['call'], values: null, one: null, many: null, next: null, next_null: null, base: null, focus: false, unit: null, ...more };
}

const DIMENSIONS = {
  part: 'dimensions',
  dimensions: [
    dimension('project', 'part', { label: 'Project' }),
    dimension('psession', 'part', { label: 'Pilot session' }),
    dimension('pturn', 'part', { label: 'Pilot turn' }),
    dimension('call', 'part', { label: 'Call' }),
    dimension('source', 'attribute', { label: 'Source' }),
    dimension('model', 'attribute', { label: 'Model' }),
    dimension('rewind', 'attribute', { label: 'Rewind' }),
    dimension('turn_cause', 'attribute', { label: 'Turn cause' }),
    dimension('qweek', 'time', { label: 'Quota week' }),
    dimension('session_start', 'order', { label: 'Pilot session, in the order created', base: 'psession' }),
  ],
} as Catalogue;

/** Each group's heading and its entries' labels, a muted one's marked `(muted)`, a starred one's `*`. */
const shape = (groups: Group[]) =>
  groups.map((group) => [group.heading, group.entries.map((entry) => `${entry.label}${entry.starred ? '*' : ''}${entry.muted ? ' (muted)' : ''}`)]);

const COUNTS = new Map([
  ['project', 1],
  ['psession', 3],
  ['call', 0],
  ['source', 2],
  ['model', 1],
  ['rewind', 1],
]);

test.describe('By’s list', () => {
  test('holds the parts and the attributes in the catalogue’s order, no time or order dimension, each its count once it has come', () => {
    const { groups, hidden } = byList(DIMENSIONS, { by: 'project', favourites: [], counts: new Map(), search: '', unfolded: false });
    expect(shape(groups)).toEqual([
      ['Parts', ['Project', 'Pilot session', 'Pilot turn', 'Call']],
      ['Attributes', ['Source', 'Model', 'Rewind', 'Turn cause']],
    ]);
    expect(groups.flatMap((group) => group.entries.map((entry) => entry.count))).toEqual(Array(8).fill(null));
    expect(groups[0].entries[0].on).toBe(true);
    expect(groups[0].entries[0].line).toBe("project's line");
    expect(hidden).toBe(0);
  });

  test('hides those with one value or none behind "n hidden", the By at hand and a favorite never; unfolded or searched it shows them muted', () => {
    const folded = byList(DIMENSIONS, { by: 'project', favourites: ['model'], counts: COUNTS, search: '', unfolded: false });
    expect(shape(folded.groups)).toEqual([
      ['Favorites', ['Model*']],
      ['Parts', ['Project', 'Pilot session', 'Pilot turn']],
      ['Attributes', ['Source', 'Turn cause']],
    ]);
    expect(folded.hidden).toBe(2);
    expect(folded.groups[1].entries.map((entry) => entry.count)).toEqual([1, 3, null]);

    const unfolded = byList(DIMENSIONS, { by: 'project', favourites: ['model'], counts: COUNTS, search: '', unfolded: true });
    expect(shape(unfolded.groups)).toEqual([
      ['Favorites', ['Model*']],
      ['Parts', ['Project', 'Pilot session', 'Pilot turn', 'Call (muted)']],
      ['Attributes', ['Source', 'Rewind (muted)', 'Turn cause']],
    ]);
    expect(unfolded.hidden).toBe(0);

    const searched = byList(DIMENSIONS, { by: 'project', favourites: [], counts: COUNTS, search: ' RE ', unfolded: false });
    expect(shape(searched.groups)).toEqual([['Attributes', ['Rewind (muted)']]]);
    expect(searched.hidden).toBe(0);
    expect(byList(DIMENSIONS, { by: 'project', favourites: [], counts: COUNTS, search: 'nothing', unfolded: false }).groups).toEqual([]);
  });

  test('lifts its favorites to Favorites at the top in the list’s own order, whatever the order starred', () => {
    const { groups } = byList(DIMENSIONS, { by: 'source', favourites: ['turn_cause', 'call', 'project'], counts: new Map(), search: '', unfolded: false });
    expect(shape(groups)).toEqual([
      ['Favorites', ['Project*', 'Call*', 'Turn cause*']],
      ['Parts', ['Pilot session', 'Pilot turn']],
      ['Attributes', ['Source', 'Model', 'Rewind']],
    ]);
  });
});

test.describe('Color’s list', () => {
  test('is By’s with no counts and none hidden, None and Token kind under a rule after it, None alone taking no star', () => {
    const groups = colorList(DIMENSIONS, { color: null, favourites: [], search: '' });
    expect(shape(groups)).toEqual([
      ['Parts', ['Project', 'Pilot session', 'Pilot turn', 'Call']],
      ['Attributes', ['Source', 'Model', 'Rewind', 'Turn cause']],
      [null, ['None', 'Token kind']],
    ]);
    const [none, tokenKind] = groups[2].entries;
    expect([none.key, none.on, none.stars]).toEqual([null, true, false]);
    expect([tokenKind.key, tokenKind.stars]).toEqual(['token_kind', true]);
    expect(groups.flatMap((group) => group.entries.map((entry) => entry.count))).toEqual(Array(10).fill(null));
  });

  test('lifts its favorites, Token kind among them, to Favorites in the list’s own order; a search finds None and Token kind too', () => {
    expect(shape(colorList(DIMENSIONS, { color: 'model', favourites: ['token_kind', 'model'], search: '' }))).toEqual([
      ['Favorites', ['Model*', 'Token kind*']],
      ['Parts', ['Project', 'Pilot session', 'Pilot turn', 'Call']],
      ['Attributes', ['Source', 'Rewind', 'Turn cause']],
      [null, ['None']],
    ]);
    expect(shape(colorList(DIMENSIONS, { color: null, favourites: [], search: 'n' }))).toEqual([
      ['Parts', ['Pilot session', 'Pilot turn']],
      ['Attributes', ['Rewind', 'Turn cause']],
      [null, ['None', 'Token kind']],
    ]);
  });
});

const written = (state: string) => readState(state);

test.describe('A pick in the head', () => {
  test('of a By lets go of the sort and the drawer’s row, keeping rows, a table and a series over time', () => {
    expect(writeState(byPicked(written('t=qw&by=project&m=cost.sum&col=none&o=asc,cost.sum&d=items&sel=p1&ig=call&it=conversation,c1'), 'model', DIMENSIONS))).toBe(
      't=qw&by=model&m=cost.sum&col=none&d=items',
    );
    expect(writeState(byPicked(written('t=qw&by=project&p=table&m=cost.sum&col=none'), 'model', DIMENSIONS))).toBe('t=qw&by=model&p=table&m=cost.sum&col=none');
    expect(writeState(byPicked(written('t=l8&by=project&p=time,qweek&m=cost.sum&col=none'), 'source', DIMENSIONS))).toBe('t=l8&by=source&p=time,qweek&m=cost.sum&col=none');
  });

  test('of a By falls back to rows from a series in order where it has no order dimension, and from lanes where it is no part', () => {
    expect(writeState(byPicked(written('t=qw&by=psession&p=order&m=cost.sum&col=none'), 'model', DIMENSIONS))).toBe('t=qw&by=model&m=cost.sum&col=none');
    expect(writeState(byPicked(written('t=qw&by=project&p=lanes&m=cost.sum&col=none'), 'source', DIMENSIONS))).toBe('t=qw&by=source&m=cost.sum&col=none');
    expect(writeState(byPicked(written('t=qw&by=project&p=lanes&m=cost.sum&col=none'), 'psession', DIMENSIONS))).toBe('t=qw&by=psession&p=lanes&m=cost.sum&col=none');
  });

  test('of a presentation keeps the sort, but a series’ on its axis, and lets go of the drawer’s row', () => {
    expect(writeState(presented(written('t=qw&by=project&m=cost.sum&col=none&o=asc,cost.sum&sel=p1'), 'table'))).toBe('t=qw&by=project&p=table&m=cost.sum&col=none&o=asc,cost.sum');
    expect(writeState(presented(written('t=qw&by=project&p=table&m=cost.sum&col=none&o=desc,n'), 'rows'))).toBe('t=qw&by=project&m=cost.sum&col=none&o=desc,n');
    expect(writeState(presented(written('t=l8&by=project&p=time,qweek&m=cost.sum&col=none&o=asc,axis'), 'rows'))).toBe('t=l8&by=project&m=cost.sum&col=none');
  });

  test('of a color lets go of the color’s values lit', () => {
    expect(writeState(colored(written('t=qw&by=project&m=cost.sum&col=source&lit=chat'), 'model'))).toBe('t=qw&by=project&m=cost.sum&col=model');
    expect(writeState(colored(written('t=qw&by=project&m=cost.sum&col=source'), null))).toBe('t=qw&by=project&m=cost.sum&col=none');
  });
});

/** An answer of the rows route, as much of it as the table reads. */
function answer(more: Partial<Rows> = {}): Rows {
  return {
    address: '#dash/t=all&by=project&m=cost.sum&m=calls.count&col=source',
    look: [],
    notes: [],
    by: { key: 'project', label: 'Project', group: 'part' },
    measures: [
      { key: 'cost.sum', label: 'Cost', format: 'usd', aggregate: 'sum', grain: null, median: 1, refused: null, stand_in: null, stacks: true },
      { key: 'calls.count', label: 'Calls', format: 'count', aggregate: 'count', grain: null, median: 2, refused: null, stand_in: null, stacks: false },
    ],
    color: {
      key: 'source',
      label: 'Source',
      values: [
        { key: 'chat', label: 'Chat', total: 1.5, others: 0 },
        { key: 'pilot', label: null, total: 0.5, others: 0 },
      ],
    },
    all: { values: [2, 4], n: [4, 4], split: [[1.5, 0.5], null], marks: null },
    rows: [
      { key: 'p1', label: 'Recipes, "the box"', at: null, values: [1.5, 3], n: [3, 3], split: [[1.5, 0], null], marks: null, marked: false, focus: false },
      { key: 'p2', label: null, at: null, values: [0.5, 1], n: [1, 1], split: [[0, 0.5], null], marks: null, marked: false, focus: false },
    ],
    sort: { column: 'cost.sum', direction: 'desc' },
    total_rows: 2,
    window: null,
    zone: 'Europe/Amsterdam',
    ...more,
  } as Rows;
}

test.describe('The table’s text', () => {
  test('holds every row, the All row first: each measure’s figure and its n, the share where the first measure sums, the first stacked measure split by the color', () => {
    expect(tableText(answer(), '\t').split('\n')).toEqual([
      'Project\tCost\tn\tCalls\tn\tShare\tChat\tpilot',
      'All\t2\t4\t4\t4\t1\t1.5\t0.5',
      'Recipes, "the box"\t1.5\t3\t3\t3\t0.75\t1.5\t0',
      'p2\t0.5\t1\t1\t1\t0.25\t0\t0.5',
    ]);
  });

  test('quotes a cell with a comma or a quote in a CSV, and puts a tab or a line break in a cell as a space for the clipboard', () => {
    const rows = answer({ color: null, rows: [{ ...answer().rows[0], label: 'Tab\there\nand there' }, answer().rows[1]] });
    expect(tableText(answer({ color: null }), ',').split('\n')[2]).toBe('"Recipes, ""the box""",1.5,3,3,3,0.75');
    expect(tableText(rows, '\t').split('\n')[2]).toBe('Tab here and there\t1.5\t3\t3\t3\t0.75');
  });

  test('has no share where the first measure neither sums nor counts, and the instant after the label where the By’s values have one', () => {
    const median = answer().measures.map((measure, j) => (j === 0 ? { ...measure, aggregate: 'median' as const, stacks: false } : measure));
    const rows = answer({ measures: median, color: null, rows: answer().rows.map((row, i) => ({ ...row, at: i === 0 ? '2026-11-07T08:52:00Z' : null })) });
    expect(tableText(rows, ',').split('\n')).toEqual(['Project,At,Cost,n,Calls,n', 'All,,2,4,4,4', '"Recipes, ""the box""",2026-11-07T08:52:00Z,1.5,3,3,3', 'p2,,0.5,1,1,1']);
  });
});
