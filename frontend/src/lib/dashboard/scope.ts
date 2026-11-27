/**
 * A view's scope on the page (F162.3, F162.4; the mockup's `main.js`, `drillPatch`, `pushPatch`,
 * `jumpTo` and `backTo`, and `scope.js`, `renderDrill` and `chipParts`): what a click on a row of the
 * By drills into, what a step back up the drill path goes back to, and the words of the path's
 * levels and of a chip. Pure, with no DOM; a dimension's words are the catalogue's, a value's label
 * the caller's.
 *
 * A part's row is a level pushed onto the drill stack, the By moving one level down, the catalogue's
 * `next`, or its `next_null` from the row with none; a level of a dimension the stack holds already
 * replaces it and the levels under it. Each level keeps what was asked on screen as it was drilled
 * into (`drilledFrom`): the By, or a series' axis, its order dimension or its grain. An attribute's
 * row is a chip that keeps its value, in place of a plain one on it, the By moving to the
 * attribute's `next`, else to the parts' level under the stack. A drill from a series lands on rows
 * (F163.3). A Call's row drills into nothing here: it opens in the items' drawer, which is slice
 * 055's. A step back up to a level, or to All, drops the levels under it and puts back the By and
 * the presentation the next level was drilled from. A drill and a step back up leave the sort at
 * its default and the drawer's row let go, as the mockup's patches set `o: null` and `sel`.
 */

import { measureWords, type Words } from './describe';
import type { Catalogue } from './queries';
import { readState, writeState, type Chip, type Level, type ViewState } from './state';

/** The parts' level a view with no drill is By. */
const TOP = 'project';

type Dimensions = Catalogue | undefined;

const dimensionOf = (dimensions: Dimensions, key: string) => dimensions?.dimensions?.find((dimension) => dimension.key === key);

/** The first order dimension along the part `by`, the one a view in order reads where it names none. */
const firstOrder = (dimensions: Dimensions, by: string) => dimensions?.dimensions?.find((dimension) => dimension.group === 'order' && dimension.base === by)?.key;

/** The By of the parts' level under `levels`: the next level down from its last, the top part with none. */
function under(levels: readonly Level[], dimensions: Dimensions): string {
  const last = levels.at(-1);
  if (last === undefined) return TOP;
  const dimension = dimensionOf(dimensions, last.dimension);
  const below = last.value === null && dimension?.next_null ? dimension.next_null : dimension?.next;
  return below ?? last.dimension;
}

/** What was asked on screen: over time its grain, in order its order dimension, else the By. */
export function asked(state: ViewState, dimensions: Dimensions): string {
  if (state.presentation === 'time') return state.axis ?? state.by;
  if (state.presentation === 'order') return state.axis ?? firstOrder(dimensions, state.by) ?? state.by;
  return state.by;
}

/** What a drill and a step back up let go of. */
const LET_GO = { sort: null, selected: null, item: null, itemGrain: null } as const;

/** Whether a row of the view's By drills into its value. */
export function drills(state: ViewState, dimensions: Dimensions): boolean {
  const by = dimensionOf(dimensions, state.by);
  return by !== undefined && ((by.group === 'part' && (by.next !== null || by.next_null !== null)) || by.group === 'attribute');
}

/** The view drilled into the By's value `value`, none for the row with none; none where its row drills into nothing. */
export function drilled(state: ViewState, value: string | null, dimensions: Dimensions): ViewState | null {
  const by = dimensionOf(dimensions, state.by);
  if (by === undefined) return null;
  const series = state.presentation === 'order' || state.presentation === 'time';
  const shown = { presentation: series ? 'rows' : state.presentation, axis: series ? null : state.axis } as const;
  if (by.group === 'part') {
    const next = value === null && by.next_null ? by.next_null : by.next;
    if (next === null) return null;
    const held = state.levels.findIndex((level) => level.dimension === by.key);
    const levels = [...(held < 0 ? state.levels : state.levels.slice(0, held)), { dimension: by.key, value, drilledFrom: asked(state, dimensions) }];
    return { ...state, ...LET_GO, ...shown, levels, by: next };
  }
  if (by.group === 'attribute') {
    const chips = state.chips.filter((chip) => !(chip.kind === 'pin' && chip.dimension === by.key && !chip.negated && !chip.marked));
    const chip: Chip = { kind: 'pin', dimension: by.key, values: [value], negated: false, marked: false };
    return { ...state, ...LET_GO, ...shown, chips: [...chips, chip], by: by.next ?? under(state.levels, dimensions) };
  }
  return null;
}

/** The view stepped back up to its level `index`, or with -1 to All: as it was right after drilling into it. */
export function upTo(state: ViewState, index: number, dimensions: Dimensions): ViewState {
  const levels = state.levels.slice(0, index + 1);
  const from = state.levels[index + 1]?.drilledFrom ?? null;
  const dimension = from === null ? undefined : dimensionOf(dimensions, from);
  if (dimension?.group === 'order' && dimension.base !== null) {
    const axis = firstOrder(dimensions, dimension.base) === dimension.key ? null : dimension.key;
    return { ...state, ...LET_GO, levels, by: dimension.base, presentation: 'order', axis };
  }
  if (dimension?.group === 'time') return { ...state, ...LET_GO, levels, by: under(levels, dimensions), presentation: 'time', axis: dimension.key };
  return { ...state, ...LET_GO, levels, by: from ?? under(levels, dimensions) };
}

/**
 * Each level's words in the drill path, from its value's label: a label that places its value
 * ("030_self_hosting_bugs · PilotApp to GA") says in the path only the parts of it no level before
 * it said, and all of them where none is new.
 */
export function pathWords(labels: readonly string[]): string[] {
  const said = new Set<string>();
  return labels.map((label) => {
    const parts = label.split(' · ');
    const fresh = parts.filter((part) => !said.has(part));
    parts.forEach((part) => said.add(part));
    return (fresh.length > 0 ? fresh : parts).join(' · ');
  });
}

const SIGNS = { gt: '>', ge: '≥', lt: '<', le: '≤' } as const;

/** A dimension's value in words, its label; none for the row with none. */
export type LabelOf = (dimension: string, value: string | null) => string;

/** A dimension's value the scope shows, and the state its label is looked up in. */
export interface Named {
  dimension: string;
  value: string | null;
  scope: string;
}

/** A state of the view's time alone, and of `levels`. */
const scopeOf = (state: ViewState, levels: readonly Level[]) => writeState({ ...readState('t=qw'), time: state.time, levels });

/** The drill path's level `index`, looked up in the view's time and the levels down to it, among whose rows its value always is. */
export function levelNamed(state: ViewState, index: number): Named {
  const { dimension, value } = state.levels[index];
  return { dimension, value, scope: scopeOf(state, state.levels.slice(0, index + 1)) };
}

/**
 * The values the scope shows: the drill path's levels' (`levelNamed`), and the chips', looked up in
 * the view's time alone, since a chip may name a value the drill or another chip leaves out.
 */
export function valuesNamed(state: ViewState): Named[] {
  const time = scopeOf(state, []);
  return [
    ...state.levels.map((_, index) => levelNamed(state, index)),
    ...state.chips.flatMap((chip) => (chip.kind === 'pin' ? chip.values.map((value) => ({ dimension: chip.dimension, value, scope: time })) : [])),
  ];
}

/**
 * A chip's words, in four parts: what it is on, its "is not" where it is negated, what it names,
 * and how many more values it names than it shows, past three ("2 more"); and every value, for its
 * tooltip, where it names more than one.
 */
interface ChipWords {
  on: string;
  not: string;
  what: string;
  more: string;
  all: string | null;
}

/** The noun of one item of a measure's grain, its fact's own where it names none. */
function eachOf(measure: Extract<Chip, { kind: 'items' }>['measure'], words: Words): string {
  const part = words.measures;
  const grain = measure.grain ?? part?.facts?.find((fact) => fact.key === part.figures?.find((figure) => figure.key === measure.figure)?.fact)?.grain;
  return part?.grains?.find((each) => each.key === grain)?.one ?? grain ?? measure.figure;
}

export function chipWords(chip: Chip, label: LabelOf, words: Words): ChipWords {
  switch (chip.kind) {
    case 'outliers':
      return { on: 'By rows: outliers', not: '', what: '', more: '', all: null };
    case 'rows':
      return { on: `By rows: ${measureWords(chip.measure, words)} ${SIGNS[chip.operator]} ${chip.number}`, not: '', what: '', more: '', all: null };
    case 'items': {
      const each = eachOf(chip.measure, words);
      const figure = words.measures?.figures?.find((one) => one.key === chip.measure.figure)?.label ?? chip.measure.figure;
      return { on: `Each ${each}`, not: chip.negated ? 'not' : '', what: `: ${figure} ${SIGNS[chip.operator]} ${chip.number}`, more: '', all: null };
    }
    case 'pin': {
      const on = dimensionOf(words.dimensions, chip.dimension)?.label ?? chip.dimension;
      const not = chip.negated ? 'is not' : '';
      const values = chip.values.map((value) => label(chip.dimension, value));
      const many = values.length > 3;
      return {
        on,
        not,
        what: `: ${(many ? values.slice(0, 2) : values).join(', ')}`,
        more: many ? `${values.length - 2} more` : '',
        all: values.length > 1 ? `${on}${not ? ` ${not}` : ''}: ${values.join(', ')}` : null,
      };
    }
    default: {
      const unknown: never = chip;
      return unknown;
    }
  }
}

/** A chip's words as one line. */
export function chipText({ on, not, what, more }: ChipWords): string {
  return `${on}${not ? ` ${not}` : ''}${what}${more ? `, ${more}` : ''}`;
}

/** What a chip does, for its tooltip. */
export function chipDoes(chip: Chip): string {
  switch (chip.kind) {
    case 'outliers':
      return `The By's rows whose first measure is an outlier among them: ${chip.marked ? 'they are marked' : 'the other rows are dropped'}`;
    case 'rows':
      return `A threshold on the By's rows: ${chip.marked ? 'the rows that pass are marked' : 'the rows that fail it are dropped'}`;
    case 'items':
      return `A condition on each item, its figure over all its rows: ${chip.marked ? 'the rows that hold one that passes are marked' : `only the items that ${chip.negated ? 'fail' : 'pass'} it are in scope`}`;
    case 'pin':
      if (chip.marked) return 'Marks: it filters nothing, and what it names is highlighted';
      return chip.negated ? 'Filters: what it names is left out of scope' : 'Filters: only what it names is in scope';
    default: {
      const unknown: never = chip;
      return unknown;
    }
  }
}
