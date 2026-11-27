/**
 * The measures' rules on the page (F163.4, F161.6), held with no page, the modules being pure. A
 * measure's name, which its heading reads: a figure's label, its aggregate where it is not the
 * figure's own, "per" the part its items are, a count of a part's items the part's noun, its own
 * filters after it; a ratio's name. + Measure's list: each fact's figures under its label, then
 * the ratios. A heading's panel: the aggregates a figure takes, the count on its fact's counting
 * figure alone, and the grains, its fact's own rows first, then each part its fact offers. A
 * measure added at the end, one shown moving there; removed, the last staying; moved; changed in
 * place. A By's sort kept within a tab: a sort picked remembered for the By, a move landing on a
 * By taking the one remembered for it, the first being the state the tab opened with; one on a
 * measure hidden forgotten, the opened one's among them; a measure changed in place taking the
 * sorts on it along. A custom ratio's format where no one picked one: a share where its two
 * figures have one format, else its numerator's; a ratio removed leaving a state that names it.
 * No browser, no backend.
 */

import { expect, test } from '@playwright/test';
import { measureWords, type Words } from '@/lib/dashboard/describe';
import { added, aggregatesOf, changed, grainsOf, measureMenu, moved, namesRatio, overGrain, ratioFormat, removed, sideOf, withoutRatio } from '@/lib/dashboard/measures';
import type { Catalogue } from '@/lib/dashboard/queries';
import { drilled, upTo } from '@/lib/dashboard/scope';
import { settle, sortedBy, type Sorts } from '@/lib/dashboard/sorts';
import { measureKey, readState, writeState, type ViewState } from '@/lib/dashboard/state';

type Dimension = NonNullable<Catalogue['dimensions']>[number];

function dimension(key: string, group: Dimension['group'], more: Partial<Dimension> = {}): Dimension {
  return { key, label: key, group, line: `${key}'s line`, null: `(No ${key})`, facts: ['call'], values: null, one: null, many: null, next: null, next_null: null, base: null, focus: false, unit: null, ...more };
}

const DIMENSIONS = {
  part: 'dimensions',
  dimensions: [
    dimension('project', 'part', { label: 'Project', facts: ['call', 'turn'], next: 'psession' }),
    dimension('psession', 'part', { label: 'Pilot session', facts: ['call', 'turn'], next: 'pturn' }),
    dimension('pturn', 'part', { label: 'Pilot turn', facts: ['call', 'turn'], next: 'conversation' }),
    dimension('conversation', 'part', { label: 'Conversation', next: 'call' }),
    dimension('call', 'part', { label: 'Call' }),
    dimension('source', 'attribute', { label: 'Source', facts: ['call', 'turn'] }),
  ],
} as Catalogue;

const figure = (key: string, label: string, fact: string, aggregate = 'sum') => ({
  key,
  label,
  fact,
  line: `${label}'s line`,
  format: 'usd' as const,
  aggregate,
  aggregates: [],
  token_kinds: null,
  stacks: true,
});

const MEASURES = {
  part: 'measures',
  facts: [
    { key: 'call', label: 'Calls', counts: 'calls', grain: 'call' },
    { key: 'turn', label: 'Pilot turns', counts: 'turns', grain: 'pturn' },
  ],
  figures: [figure('cost', 'Cost', 'call'), figure('calls', 'Calls', 'call', 'count'), figure('turns', 'Pilot turns', 'turn', 'count'), figure('turn_time', 'Turn wall-clock', 'turn')],
  aggregates: [
    { key: 'sum', label: 'Sum', line: '' },
    { key: 'median', label: 'Median', line: '' },
    { key: 'count', label: 'Count', line: '' },
  ],
  grains: [
    { key: 'project', one: 'project', many: 'projects', figures: [], shows: [] },
    { key: 'psession', one: 'Pilot session', many: 'Pilot sessions', figures: [], shows: [] },
    { key: 'pturn', one: 'Pilot turn', many: 'Pilot turns', figures: [], shows: [] },
    { key: 'conversation', one: 'conversation', many: 'conversations', figures: [], shows: [] },
    { key: 'call', one: 'call', many: 'calls', figures: [], shows: [] },
  ],
  ratios: [{ key: 'per_call', label: 'Cost per call', line: 'The cost over the number of Calls', format: 'usd', origin: null, numerator: 'cost.sum', denominator: 'calls.count' }],
} as Catalogue;

const WORDS: Words = { dimensions: DIMENSIONS, measures: MEASURES, time: undefined };

const named = (written: string) => measureWords(readState(`m=${written}`).measures[0], WORDS);

const keys = (state: ViewState) => state.measures.map(measureKey);

test.describe('A measure’s name', () => {
  test('is its figure’s label, its aggregate after it where it is not the figure’s own, “per” the part its items are, a count of a part’s items the part’s noun', () => {
    expect(named('cost.sum')).toBe('Cost');
    expect(named('calls.count')).toBe('Calls');
    expect(named('cost.median')).toBe('Cost (median)');
    expect(named('cost.median.conversation')).toBe('Cost per conversation (median)');
    expect(named('cost.sum.conversation')).toBe('Cost per conversation (sum)');
    expect(named('calls.count.conversation')).toBe('Conversations');
    expect(named('cost.sum(source=chat|pilot)')).toBe('Cost, where Source is chat or pilot');
    expect(named('cost.sum(!source=work)')).toBe('Cost, where Source is not work');
    expect(named('r:per_call')).toBe('Cost per call');
    expect(named('r:Spend:cost.sum/turns.count')).toBe('Spend');
  });
});

test.describe('+ Measure’s list', () => {
  test('holds each fact’s figures under its label, each at its own aggregate over its fact’s own rows, then the ratios', () => {
    const groups = measureMenu(MEASURES);
    expect(groups.map((group) => [group.heading, group.entries.map((entry) => `${entry.label} ${measureKey(entry.measure)}`)])).toEqual([
      ['Calls', ['Cost cost.sum', 'Calls calls.count']],
      ['Pilot turns', ['Pilot turns turns.count', 'Turn wall-clock turn_time.sum']],
      ['Ratios', ['Cost per call r:per_call']],
    ]);
  });
});

test.describe('A heading’s panel', () => {
  test('offers a figure every aggregate on its fact’s counting figure and every one but the count on another', () => {
    expect(aggregatesOf(MEASURES, 'cost').map((aggregate) => aggregate.key)).toEqual(['sum', 'median']);
    expect(aggregatesOf(MEASURES, 'calls').map((aggregate) => aggregate.key)).toEqual(['sum', 'median', 'count']);
  });

  test('offers its fact’s own rows first, then each part its fact offers, its own written as none', () => {
    expect(grainsOf(MEASURES, DIMENSIONS, 'cost').map((grain) => grain.key)).toEqual(['call', 'project', 'psession', 'pturn', 'conversation']);
    expect(grainsOf(MEASURES, DIMENSIONS, 'turns').map((grain) => grain.key)).toEqual(['pturn', 'project', 'psession']);
    const cost = readState('m=cost.median').measures[0] as Extract<ViewState['measures'][number], { kind: 'simple' }>;
    expect(measureKey(overGrain(MEASURES, cost, 'conversation'))).toBe('cost.median.conversation');
    expect(measureKey(overGrain(MEASURES, overGrain(MEASURES, cost, 'conversation'), 'call'))).toBe('cost.median');
  });
});

test.describe('The measures', () => {
  const state = readState('m=cost.sum&m=calls.count&m=turns.count');

  test('take one added at their end, one shown moving there', () => {
    expect(keys(added(state, { kind: 'ratio', key: 'per_call' }))).toEqual(['cost.sum', 'calls.count', 'turns.count', 'r:per_call']);
    expect(keys(added(state, state.measures[0]))).toEqual(['calls.count', 'turns.count', 'cost.sum']);
  });

  test('let one go, but for the last', () => {
    expect(keys(removed(state, 'calls.count'))).toEqual(['cost.sum', 'turns.count']);
    const one = readState('m=cost.sum');
    expect(removed(one, 'cost.sum')).toBe(one);
  });

  test('move one to a place counted before it is taken out, and change one in place', () => {
    expect(keys(moved(state, 2, 0))).toEqual(['turns.count', 'cost.sum', 'calls.count']);
    expect(keys(moved(state, 0, 3))).toEqual(['calls.count', 'turns.count', 'cost.sum']);
    expect(keys(moved(state, 0, 2))).toEqual(['calls.count', 'cost.sum', 'turns.count']);
    expect(keys(changed(state, 1, readState('m=calls.median').measures[0]))).toEqual(['cost.sum', 'calls.median', 'turns.count']);
  });
});

test.describe('A By’s sort within a tab', () => {
  const link = readState('t=all&by=project&m=cost.sum&m=calls.count&col=none&o=asc,calls.count');
  const memory = (sorts: Sorts = {}) => ({ sorts, opened: link });

  test('is its opened state’s first, put back by a step back up the drill path; a sort picked is remembered for the By the view asks', () => {
    const down = drilled(link, 'p1', DIMENSIONS)!;
    const there = settle(memory(), link, down, DIMENSIONS);
    expect(there.state.by).toBe('psession');
    expect(there.state.sort).toBeNull();
    expect(there.sorts).toEqual({});

    const picked = settle(memory(there.sorts), there.state, { ...there.state, sort: sortedBy({ direction: 'desc', column: 'cost.sum' }, 'cost.sum') }, DIMENSIONS);
    expect(picked.state.sort).toEqual({ direction: 'asc', column: 'cost.sum' });
    expect(picked.sorts).toEqual({ psession: { direction: 'asc', column: 'cost.sum' } });

    const back = settle(memory(picked.sorts), picked.state, upTo(picked.state, -1, DIMENSIONS), DIMENSIONS);
    expect(back.state.by).toBe('project');
    expect(back.state.sort).toEqual({ direction: 'asc', column: 'calls.count' });

    const again = settle(memory(back.sorts), back.state, drilled(back.state, 'p1', DIMENSIONS)!, DIMENSIONS);
    expect(again.state.sort).toEqual({ direction: 'asc', column: 'cost.sum' });
  });

  test('keeps the time and the chips’ moves to themselves: the sort stands as the state has it', () => {
    const one = readState('t=all&by=project&m=cost.sum&col=none');
    const moved = settle({ sorts: { project: { direction: 'asc', column: 'cost.sum' } }, opened: null }, one, { ...one, time: { kind: 'preset', key: 'qw' } }, DIMENSIONS);
    expect(moved.state.sort).toBeNull();
  });

  test('forgets a sort on a measure hidden, the one the tab opened with among them, and the view’s', () => {
    const sorted = readState(writeState({ ...link, sort: { direction: 'desc', column: 'calls.count' } }));
    const hidden = settle(memory({ psession: { direction: 'desc', column: 'calls.count' } }), sorted, removed(sorted, 'calls.count'), DIMENSIONS);
    expect(hidden.state.sort).toBeNull();
    expect(hidden.sorts).toEqual({ project: null, psession: null });

    const shown = added(hidden.state, readState('m=calls.count').measures[0]);
    const down = settle(memory(hidden.sorts), shown, drilled(shown, 'p1', DIMENSIONS)!, DIMENSIONS);
    const up = settle(memory(down.sorts), down.state, upTo(down.state, -1, DIMENSIONS), DIMENSIONS);
    expect(up.state.sort).toBeNull();
  });

  test('takes the sorts on a measure changed in place, its aggregate or its grain, along with it', () => {
    const median = readState('m=calls.median').measures[0];
    const next = settle(memory({ psession: { direction: 'desc', column: 'cost.sum' } }), link, changed(link, 1, median), DIMENSIONS);
    expect(next.state.sort).toEqual({ direction: 'asc', column: 'calls.median' });
    expect(next.sorts).toEqual({ project: { direction: 'asc', column: 'calls.median' }, psession: { direction: 'desc', column: 'cost.sum' } });
  });
});

test.describe('A heading’s press', () => {
  test('sorts by its column the largest first, then the other way', () => {
    expect(sortedBy({ direction: 'desc', column: 'cost.sum' }, 'calls.count')).toEqual({ direction: 'desc', column: 'calls.count' });
    expect(sortedBy({ direction: 'desc', column: 'calls.count' }, 'calls.count')).toEqual({ direction: 'asc', column: 'calls.count' });
    expect(sortedBy({ direction: 'asc', column: 'calls.count' }, 'calls.count')).toEqual({ direction: 'desc', column: 'calls.count' });
  });
});

test.describe('A custom ratio', () => {
  const formatted = { ...MEASURES, figures: MEASURES.figures!.map((each) => ({ ...each, format: each.key === 'calls' || each.key === 'turns' ? ('count' as const) : ('usd' as const) })) } as Catalogue;

  test('is written where no one picked a format as a share where its two figures have one format, else in its numerator’s', () => {
    expect(ratioFormat(formatted, sideOf('calls.count'), sideOf('turns.count'))).toBe('share');
    expect(ratioFormat(formatted, sideOf('cost.sum'), sideOf('turn_time.sum'))).toBe('share');
    expect(ratioFormat(formatted, sideOf('cost.sum'), sideOf('calls.count'))).toBe('usd');
    expect(ratioFormat(formatted, sideOf('calls.count'), sideOf('cost.median.conversation(source=chat)'))).toBe('count');
  });

  test('removed, leaves a state that names it: its column, its threshold on the By’s rows and a sort on it, the view with no measure left taking the one a state with none takes', () => {
    const state = readState('t=all&by=project&m=cost.sum&m=r:person_spend&c=@rows,gt,1,r:person_spend&c=~@rows,gt,2,r:per_call&o=desc,r%3Aperson_spend');
    expect(namesRatio(state, 'person_spend')).toBe(true);
    expect(namesRatio(state, 'person')).toBe(false);
    expect(writeState(withoutRatio(state, 'person_spend'))).toBe('t=all&by=project&m=cost.sum&c=~@rows,gt,2,r:per_call&col=none');

    const alone = readState('m=r:person_spend&c=@items,gt,1,cost.sum&o=desc,label');
    expect(writeState(withoutRatio(alone, 'person_spend'))).toBe('t=qw&by=project&m=cost.sum&c=@items,gt,1,cost.sum&col=none&o=desc,label');
    expect(namesRatio(readState('c=@rows,lt,2,r:person_spend'), 'person_spend')).toBe(true);
    expect(namesRatio(readState('m=r:person_spend:cost.sum/calls.count'), 'person_spend')).toBe(false);
  });
});
