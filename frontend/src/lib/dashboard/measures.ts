/**
 * The measures, the view's columns (F163.4; the mockup's `heads.js` and `view.js`, `addMeasure`
 * and `catalogue`), on the page: each measure's name, which its heading reads (`measureWords`),
 * + Measure's list, a heading's panel's aggregates and grains, and what an add, a remove, a move and
 * a change in place make of the state. Pure, with no DOM; a measure's words are the catalogue's.
 *
 * + Measure lists each fact's figures under the fact's label, each at its own aggregate over its
 * fact's own rows, then the ratios, the built-in ones and the stored. A figure takes every
 * aggregate on its fact's counting figure and every one but the count on another
 * (`backend/app/dashboard/catalogue.py`, `aggregates_of`), over its fact's own rows or the items of
 * a part that fact offers (`backend/app/dashboard/reading.py`, `grain`), its fact's own written as
 * none.
 *
 * A custom ratio (F163.6) is a numerator over a denominator, each a figure's measure with a filter of
 * its own, written in the format the person picks: by default the one the engine gives a ratio no one
 * picked a format for, a share where its two figures have one format, else its numerator's
 * (`backend/app/dashboard/assembly.py`, `ratio_format`). A ratio removed leaves every state that
 * names it, as a measure, a threshold or a sort, as the server drops one by a key that is gone.
 */

import { measureWords, type Words } from './describe';
import { stateOf, type Catalogue } from './queries';
import type { Rows } from './rows-layout';
import { measureKey, readState, type ViewState } from './state';

type Measure = ViewState['measures'][number];
export type Simple = Extract<Measure, { kind: 'simple' }>;
type Format = NonNullable<Catalogue['ratios']>[number]['format'];

const COUNT = 'count';

/** The heading of + Measure's group of ratios. */
export const RATIOS = 'Ratios';

interface Entry {
  measure: Measure;
  label: string;
  /** What it is, its tooltip. */
  line: string | null;
}

interface MenuGroup {
  heading: string;
  entries: Entry[];
}

/** + Measure's list: each fact's figures under its label, then the ratios. */
export function measureMenu(measures: Catalogue | undefined): MenuGroup[] {
  const facts = measures?.facts ?? [];
  const figures = measures?.figures ?? [];
  return [
    ...facts.map((fact) => ({
      heading: fact.label,
      entries: figures
        .filter((figure) => figure.fact === fact.key)
        .map((figure): Entry => ({ measure: { kind: 'simple', figure: figure.key, aggregate: figure.aggregate, grain: null, filters: [] }, label: figure.label, line: figure.line })),
    })),
    { heading: RATIOS, entries: (measures?.ratios ?? []).map((ratio): Entry => ({ measure: { kind: 'ratio', key: ratio.key }, label: ratio.label, line: ratio.line })) },
  ].filter((group) => group.entries.length > 0);
}

const factOf = (measures: Catalogue | undefined, figure: string) => {
  const found = measures?.figures?.find((each) => each.key === figure);
  return found === undefined ? undefined : measures?.facts?.find((fact) => fact.key === found.fact);
};

/** The aggregates a measure of `figure` takes: every one on its fact's counting figure, every one but the count on another. */
export function aggregatesOf(measures: Catalogue | undefined, figure: string): NonNullable<Catalogue['aggregates']> {
  const counts = factOf(measures, figure)?.counts === figure;
  return (measures?.aggregates ?? []).filter((aggregate) => counts || aggregate.key !== COUNT);
}

/** The grains a measure of `figure` takes, by their keys: its fact's own rows first, then each part its fact offers. */
export function grainsOf(measures: Catalogue | undefined, dimensions: Catalogue | undefined, figure: string): NonNullable<Catalogue['grains']> {
  const fact = factOf(measures, figure);
  if (fact === undefined) return [];
  const grains = measures?.grains ?? [];
  const reached = grains.filter(
    (grain) => grain.key !== fact.grain && (grain.key === fact.key || (dimensions?.dimensions?.find((dimension) => dimension.key === grain.key)?.facts.includes(fact.key) ?? false)),
  );
  return [...grains.filter((grain) => grain.key === fact.grain), ...reached];
}

/** The grain `measure` reads, its fact's own when it is written as none. */
export function grainOf(measures: Catalogue | undefined, measure: Simple): string | null {
  return measure.grain ?? factOf(measures, measure.figure)?.grain ?? null;
}

/** `measure` over the items of `grain`, written as none where they are its fact's own rows. */
export function overGrain(measures: Catalogue | undefined, measure: Simple, grain: string): Simple {
  return { ...measure, grain: grain === factOf(measures, measure.figure)?.grain ? null : grain };
}

/** The view with `measure` at the end of its columns; one it shows already moves there. */
export function added(state: ViewState, measure: Measure): ViewState {
  const key = measureKey(measure);
  return { ...state, measures: [...state.measures.filter((each) => measureKey(each) !== key), measure] };
}

/** The view without the measure `key`, but for the last one, which stays. */
export function removed(state: ViewState, key: string): ViewState {
  const measures = state.measures.filter((each) => measureKey(each) !== key);
  return measures.length === 0 ? state : { ...state, measures };
}

/** The view with its measure at `from` moved to the place `to` among the columns, counted before it is taken out: from 0, before the first, to their count, after the last. */
export function moved(state: ViewState, from: number, to: number): ViewState {
  const measures = [...state.measures];
  const [measure] = measures.splice(from, 1);
  measures.splice(to > from ? to - 1 : to, 0, measure);
  return { ...state, measures };
}

/** The view with its measure at `index` changed in place to `measure`. */
export function changed(state: ViewState, index: number, measure: Measure): ViewState {
  return { ...state, measures: state.measures.map((each, at) => (at === index ? measure : each)) };
}

/** The name of each measure the rows answer, in their order: the page's own once the catalogue's measures have come, the answer's label before. */
export function measureNames(rows: Rows, words: Words): string[] {
  if (words.measures === undefined) return rows.measures.map((measure) => measure.label);
  const { measures } = readState(stateOf(rows.address));
  return rows.measures.map((answered, index) => (measures[index] === undefined ? answered.label : measureWords(measures[index], words)));
}

/** The formats a person picks a ratio's from, in the order offered (`CustomRatioWriteSchema`'s `format`). */
export const FORMATS: readonly Format[] = ['usd', 'tokens', 'count', 'seconds', 'share'];

/** The format of a ratio of `numerator` over `denominator` where no one picked one: a share where their figures have one format, else the numerator's. */
export function ratioFormat(measures: Catalogue | undefined, numerator: Simple, denominator: Simple): Format {
  const formatOf = (side: Simple) => measures?.figures?.find((figure) => figure.key === side.figure)?.format;
  const above = formatOf(numerator);
  return above === undefined || above === formatOf(denominator) ? 'share' : above;
}

/** A side of a ratio, as a state writes it after `m=`. */
export const sideOf = (written: string): Simple => readState(`m=${written}`).measures[0] as Simple;

const isRatio = (measure: Measure, key: string) => measure.kind === 'ratio' && measure.key === key;

/** Whether `state` names the ratio `key`: as a measure, or as a threshold's on the By's rows. */
export function namesRatio(state: ViewState, key: string): boolean {
  return state.measures.some((measure) => isRatio(measure, key)) || state.chips.some((chip) => chip.kind === 'rows' && isRatio(chip.measure, key));
}

/** The view without the ratio `key`: its column, its thresholds and a sort on it gone; with no measure left, the one a state with none takes. */
export function withoutRatio(state: ViewState, key: string): ViewState {
  const measures = state.measures.filter((measure) => !isRatio(measure, key));
  return {
    ...state,
    measures: measures.length > 0 ? measures : readState('').measures,
    chips: state.chips.filter((chip) => !(chip.kind === 'rows' && isRatio(chip.measure, key))),
    sort: state.sort?.column === measureKey({ kind: 'ratio', key }) ? null : state.sort,
  };
}
