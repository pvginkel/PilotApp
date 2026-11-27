/**
 * The scope's rules on the page (F162.3, F162.4), held with no page, the module being pure: a
 * part's row pushes a level and moves the By one level down, from the row with none to the part's
 * own next for none, a level of a dimension the stack holds replacing it and those under it, each
 * level keeping what was asked as it was drilled into; an attribute's row keeps its value in a chip,
 * in place of a plain one on it, the By moving to the attribute's next or else the parts' level
 * under the stack; a drill from a series lands on rows; a Call's row drills into nothing; a step back
 * up puts back the By and the presentation the next level was drilled from; a drill and a step let
 * go of the sort and the drawer's row. A level is named by a lookup in the view's time and the
 * levels down to it, a chip's value in the view's time alone. In the path a level says only what no
 * level before it said; a chip's values are cut past three, before "n more". No browser, no backend.
 */

import { expect, test } from '@playwright/test';
import type { Catalogue } from '@/lib/dashboard/queries';
import { chipText, chipWords, drilled, drills, pathWords, upTo, valuesNamed } from '@/lib/dashboard/scope';
import { readState, writeState, type Chip } from '@/lib/dashboard/state';

type Dimension = NonNullable<Catalogue['dimensions']>[number];

/** A dimension of the catalogue's, as much of it as the rules read. */
function dimension(key: string, group: Dimension['group'], more: Partial<Dimension> = {}): Dimension {
  return { key, label: key, group, line: '', null: `(No ${key})`, facts: ['call'], values: null, one: null, many: null, next: null, next_null: null, base: null, focus: false, unit: null, ...more };
}

const DIMENSIONS = {
  part: 'dimensions',
  dimensions: [
    dimension('project', 'part', { label: 'Project', next: 'psession', next_null: 'sitting' }),
    dimension('psession', 'part', { label: 'Pilot session', next: 'pturn', next_null: 'conversation' }),
    dimension('pturn', 'part', { next: 'conversation' }),
    dimension('sitting', 'part', { next: 'conversation' }),
    dimension('conversation', 'part', { next: 'call' }),
    dimension('call', 'part'),
    dimension('source', 'attribute', { label: 'Source' }),
    dimension('work_type', 'attribute', { next: 'psession' }),
    dimension('qweek', 'time', { next: 'day' }),
    dimension('day', 'time'),
    dimension('session_start', 'order', { base: 'psession', next: 'pturn' }),
    dimension('turn_seq', 'order', { base: 'pturn' }),
  ],
} as Catalogue;

const view = (written: string) => readState(written);

const drill = (written: string, value: string | null) => {
  const next = drilled(view(written), value, DIMENSIONS);
  return next === null ? null : writeState(next);
};

test.describe('A drill', () => {
  test('into a part’s row pushes its level, drilled from the By, and moves the By one level down, letting go of the sort and the drawer’s row', () => {
    expect(drill('t=qw&by=project&m=cost.sum&col=none&o=asc,cost.sum&sel=p1', 'p1')).toBe('t=qw&by=psession&m=cost.sum&dr=project:p1@project&col=none');
    expect(drill('t=qw&by=psession&m=cost.sum&dr=project:p1@project&col=none', 's1')).toBe(
      't=qw&by=pturn&m=cost.sum&dr=project:p1@project&dr=psession:s1@psession&col=none',
    );
  });

  test('into the row with none moves the By to the part’s own next for none', () => {
    expect(drill('t=qw&by=project&m=cost.sum&col=none', null)).toBe('t=qw&by=sitting&m=cost.sum&dr=project:~@project&col=none');
  });

  test('into a dimension the stack holds already replaces its level and those under it', () => {
    expect(drill('t=qw&by=project&m=cost.sum&dr=project:p1@project&dr=psession:s1@psession&col=none', 'p2')).toBe('t=qw&by=psession&m=cost.sum&dr=project:p2@project&col=none');
  });

  test('from a series lands on rows, the level keeping the series’ grain or order', () => {
    expect(drill('t=l8&by=project&p=time,qweek&m=cost.sum&col=source', 'p1')).toBe('t=l8&by=psession&m=cost.sum&dr=project:p1@qweek&col=source');
    expect(drill('t=qw&by=psession&p=order&m=cost.sum&col=none', 's1')).toBe('t=qw&by=pturn&m=cost.sum&dr=psession:s1@session_start&col=none');
  });

  test('into an attribute’s row keeps its value in a chip, in place of a plain one on it, the By its next or the parts’ level under the stack', () => {
    expect(drill('t=qw&by=source&m=cost.sum&dr=project:p1@project&c=source:work&c=~source:pilot&col=none', 'chat')).toBe(
      't=qw&by=psession&m=cost.sum&dr=project:p1@project&c=~source:pilot&c=source:chat&col=none',
    );
    expect(drill('t=qw&by=work_type&m=cost.sum&col=none', 'job')).toBe('t=qw&by=psession&m=cost.sum&c=work_type:job&col=none');
  });

  test('into a Call’s row drills into nothing: it opens in the items’ drawer', () => {
    expect(drills(view('t=qw&by=call&m=cost.sum&col=none'), DIMENSIONS)).toBe(false);
    expect(drill('t=qw&by=call&m=cost.sum&col=none', 'c1')).toBeNull();
    expect(drills(view('t=qw&by=conversation&m=cost.sum&col=none'), DIMENSIONS)).toBe(true);
  });
});

test.describe('A step back up the drill path', () => {
  const deep = 't=qw&by=pturn&m=cost.sum&dr=project:p1@project&dr=psession:s1@psession&col=none&o=asc,cost.sum';
  const up = (written: string, index: number) => writeState(upTo(view(written), index, DIMENSIONS));

  test('to a level drops those under it and puts back the By the next was drilled from; to All clears the drill', () => {
    expect(up(deep, 0)).toBe('t=qw&by=psession&m=cost.sum&dr=project:p1@project&col=none');
    expect(up(deep, -1)).toBe('t=qw&by=project&m=cost.sum&col=none');
  });

  test('to a level drilled from a series puts the series back', () => {
    expect(up('t=l8&by=psession&m=cost.sum&dr=project:p1@qweek&col=source', -1)).toBe('t=l8&by=project&p=time,qweek&m=cost.sum&col=source');
    expect(up('t=qw&by=pturn&m=cost.sum&dr=psession:s1@session_start&col=none', -1)).toBe('t=qw&by=psession&p=order&m=cost.sum&col=none');
    expect(up('t=qw&by=conversation&m=cost.sum&dr=pturn:t1@turn_seq&col=none', -1)).toBe('t=qw&by=pturn&p=order&m=cost.sum&col=none');
  });
});

test('a level is looked up in the view’s time and the levels down to it, a chip’s value in the view’s time alone', () => {
  expect(valuesNamed(view('t=all&by=pturn&m=calls.count&dr=project:p1@project&dr=psession:s1@psession&c=!source:chat,work&c=@outliers&col=model'))).toEqual([
    { dimension: 'project', value: 'p1', scope: 't=all&by=project&m=cost.sum&dr=project:p1@project&col=none' },
    { dimension: 'psession', value: 's1', scope: 't=all&by=project&m=cost.sum&dr=project:p1@project&dr=psession:s1@psession&col=none' },
    { dimension: 'source', value: 'chat', scope: 't=all&by=project&m=cost.sum&col=none' },
    { dimension: 'source', value: 'work', scope: 't=all&by=project&m=cost.sum&col=none' },
  ]);
});

test.describe('The scope’s words', () => {
  test('a level in the path says only the parts of its label no level before it said, and all of them where none is new', () => {
    expect(pathWords(['030_self_hosting_bugs · PilotApp to GA', '030_self_hosting_bugs · Phase 3', 'Phase 3'])).toEqual(['030_self_hosting_bugs · PilotApp to GA', 'Phase 3', 'Phase 3']);
    expect(pathWords(['Recipes', '#2 Sort the spices', 'Turn 1 · brief'])).toEqual(['Recipes', '#2 Sort the spices', 'Turn 1 · brief']);
  });

  const words = { dimensions: DIMENSIONS, measures: undefined, time: undefined };
  const label = (_: string, value: string | null) => (value === null ? '(none)' : value.toUpperCase());
  const pin = (values: (string | null)[], negated = false): Chip => ({ kind: 'pin', dimension: 'source', values, negated, marked: false });

  test('a chip names its values up to three, past that two and how many more, every value in its tooltip; a negated chip’s "is not" apart', () => {
    expect(chipText(chipWords(pin(['a', 'b', 'c']), label, words))).toBe('Source: A, B, C');
    const many = chipWords(pin(['a', 'b', 'c', 'd'], true), label, words);
    expect(many).toEqual({ on: 'Source', not: 'is not', what: ': A, B', more: '2 more', all: 'Source is not: A, B, C, D' });
    expect(chipText(many)).toBe('Source is not: A, B, 2 more');
    expect(chipWords(pin(['a']), label, words).all).toBeNull();
  });
});
