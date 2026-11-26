/**
 * A view's state (F159) on the page: the view whole, as the address carries it after `#dash/`, read
 * into its parts and written back in the server's normal form (`backend/app/dashboard/state.py`),
 * each part in its place, each value encoded as the server encodes it and each list in the server's
 * order, so that what the page writes is the address the server answers. Its look-only parts are the
 * server's `LOOK`: no answer of the engine reads them, so the state without them keys what the page
 * asks.
 *
 * The page reads the forms the server writes, its answers' `address`, a saved view's and its own
 * writes, in any order of their parts, a part left out taking its default. A spelling the server
 * reads through the catalogue (a figure's default aggregate, a fact's own grain written out, a By
 * that is a time or an order dimension) is the server's to normalise, through `GET
 * /api/dashboard/address`: read here, one throws `StateFormError` and another reads otherwise than
 * the server reads it. What the server refuses, and the words of its refusal, are the server's
 * alone (F154.2).
 *
 * Pure, with no DOM: a spec with no page holds it to the file of states,
 * `backend/dashboard-states/states.json` (`tests/dashboard/state.spec.ts`).
 */

const PREFIX = '#dash/';

/** A value of none, as a state writes it. */
const NULL = '~';

/** A state's parts, in the order the normal form writes them. */
const PARTS = [
  't', 'by', 'p', 'm', 'dr', 'c', 'b', 'col', 'o', 'd', 'sel', 'ig', 'it', 'call', 'f', 'rel', 'mk',
  'dw', 'roll', 'lit', 'ev', 'z',
] as const;

type PartKey = (typeof PARTS)[number];

/** The parts a state holds more than once, each in its place. */
const REPEATED: readonly PartKey[] = ['m', 'dr', 'c'];

/** The look-only parts, the server's `LOOK`. */
const LOOK: readonly PartKey[] = ['d', 'rel', 'mk', 'dw', 'lit', 'ev', 'z'];

const PRESENTATIONS = ['rows', 'order', 'time', 'lanes', 'table'] as const;
const DOTS = ['all', 'out', 'none'] as const;
/** The parts of what a series draws that are on unless turned off, in the order `dw` writes them. */
const SWITCHES = ['cols', 'med', 'band'] as const;
const OPERATORS = ['gt', 'ge', 'lt', 'le'] as const;
const DIRECTIONS = ['asc', 'desc'] as const;

/** A bound of a range: a date, or a time of day, both in the dashboard's zone. */
const BOUND = /^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?$/;

/** A number in a form Python's `float` reads, its finiteness checked apart. */
const NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

const WHOLE = /^-?\d+$/;

/** A dimension's value as the server writes it, decoded; none for the row with none. */
type Value = string | null;

type Presentation = (typeof PRESENTATIONS)[number];
type Operator = (typeof OPERATORS)[number];

type Time =
  /** A time range by its key in the catalogue. */
  | { kind: 'preset'; key: string }
  /** Quota weeks, each by the instant it starts, as the server writes it. */
  | { kind: 'weeks'; starts: readonly string[] }
  /** From one bound to the other, an end that is a date holding its day; none on a side, open there. */
  | { kind: 'between'; start: string | null; end: string | null };

/** A measure's own filter: a dimension's values, or all but them. */
interface Filter {
  dimension: string;
  values: readonly Value[];
  negated: boolean;
}

/** A figure under an aggregate, its items those of `grain`, none being its fact's own. */
interface Simple {
  kind: 'simple';
  figure: string;
  aggregate: string;
  grain: string | null;
  filters: readonly Filter[];
}

type Measure =
  | Simple
  /** A ratio of the catalogue, built in or stored. */
  | { kind: 'ratio'; key: string }
  /** A ratio written out in the state, with its name. */
  | { kind: 'written'; name: string; numerator: Simple; denominator: Simple };

/** A level of the drill stack, and the dimension asked when it was drilled into. */
interface Level {
  dimension: string;
  value: Value;
  drilledFrom: string | null;
}

type Chip =
  /** A dimension's values kept, all but them kept (`negated`), or marked. */
  | { kind: 'pin'; dimension: string; values: readonly Value[]; negated: boolean; marked: boolean }
  /** A threshold on the By's rows, a ratio's among them. */
  | { kind: 'rows'; operator: Operator; number: number; measure: Measure; marked: boolean }
  /** A condition on each item of the measure's grain. */
  | {
      kind: 'items';
      operator: Operator;
      number: number;
      measure: Simple;
      negated: boolean;
      marked: boolean;
    }
  /** The By's rows whose first measure is an outlier among them. */
  | { kind: 'outliers'; marked: boolean };

/** A view's whole state, every part as the page reads it. */
interface ViewState {
  time: Time;
  by: string;
  presentation: Presentation;
  /** In order, its order dimension where it is not the By's first; over time, its grain. */
  axis: string | null;
  measures: readonly Measure[];
  levels: readonly Level[];
  chips: readonly Chip[];
  quickFilters: readonly string[];
  color: string | null;
  sort: { direction: (typeof DIRECTIONS)[number]; column: string } | null;
  drawer: boolean;
  /** The row of the By the drawer lists, its value none for the row with none. */
  selected: { value: Value } | null;
  itemGrain: string | null;
  item: { grain: string; key: Value } | null;
  call: number | null;
  focus: { dimension: string; key: Value } | null;
  relative: boolean;
  /** The kinds of marker shown, none being every kind. */
  markers: readonly string[] | null;
  draw: { dots: (typeof DOTS)[number] | null; cols: boolean; med: boolean; band: boolean };
  roll: { read: number; before: number };
  /** The color's values lit, `…` among them the other values; none being all. */
  lit: readonly Value[] | null;
  /** The kinds of event that depart from the presentation's default; none, every kind at it. */
  events: readonly { kind: string; drawn: boolean }[] | null;
  /** The window of the lanes or of a series on a line, in epoch seconds. */
  zoom: readonly [number, number] | null;
}

/** Every part at its default, as the server's `State()` has it: what a part left out of a state
 * reads as, and the measures a state with none takes. */
const DEFAULT: ViewState = {
  time: { kind: 'preset', key: 'qw' },
  by: 'project',
  presentation: 'rows',
  axis: null,
  measures: [{ kind: 'simple', figure: 'cost', aggregate: 'sum', grain: null, filters: [] }],
  levels: [],
  chips: [],
  quickFilters: [],
  color: null,
  sort: null,
  drawer: false,
  selected: null,
  itemGrain: null,
  item: null,
  call: null,
  focus: null,
  relative: false,
  markers: null,
  draw: { dots: null, cols: true, med: true, band: true },
  roll: { read: 10, before: 15 },
  lit: null,
  events: null,
  zoom: null,
};

/** A state the page does not read: not in the server's forms, `part` the first it cannot read. */
export class StateFormError extends Error {
  readonly part: string;

  constructor(part: string) {
    super(`"${part}" is in none of the forms a view's state is read in on the page`);
    this.name = 'StateFormError';
    this.part = part;
  }
}

// ------------------------------------------------------------------ values

/** A value as the server writes it: `encodeURIComponent` with ! ' ( ) * ~ encoded too. */
function enc(value: string): string {
  return encodeURIComponent(value).replace(
    /[!'()*~]/g,
    (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

function dec(written: string, part: string): string {
  try {
    return decodeURIComponent(written);
  } catch (error) {
    if (error instanceof URIError) throw new StateFormError(part);
    throw error;
  }
}

function writeValue(value: Value): string {
  return value === null ? NULL : enc(value);
}

function readValue(written: string, part: string): Value {
  return written === NULL ? null : dec(written, part);
}

/** A number as the server writes it, Python's `repr`: a whole one without its fraction, one under
 * 1e-4 with its exponent, `1e-05`. */
function number(value: number): string {
  if (Number.isInteger(value)) return BigInt(value).toString();
  const sign = value < 0 ? '-' : '';
  const [mantissa, exponent] = Math.abs(value).toExponential().split('e');
  const digits = mantissa.replace('.', '');
  const point = Number(exponent) + 1;
  if (point <= -4) {
    const shown = String(1 - point).padStart(2, '0');
    return `${sign}${mantissa}e-${shown}`;
  }
  if (point <= 0) return `${sign}0.${'0'.repeat(-point)}${digits}`;
  return `${sign}${digits.slice(0, point)}.${digits.slice(point)}`;
}

function readNumber(written: string, part: string): number {
  const read = NUMBER.test(written) ? Number(written) : NaN;
  if (!Number.isFinite(read)) throw new StateFormError(part);
  return read;
}

function oneOf<T extends string>(choices: readonly T[], written: string, part: string): T {
  const found = choices.find((choice) => choice === written);
  if (found === undefined) throw new StateFormError(part);
  return found;
}

/** `written` split at its first `separator`; a `StateFormError` where it has none. */
function cut(written: string, separator: string, part: string): [string, string] {
  const at = written.indexOf(separator);
  if (at < 0) throw new StateFormError(part);
  return [written.slice(0, at), written.slice(at + separator.length)];
}

function named(written: string, part: string): string {
  if (!written) throw new StateFormError(part);
  return written;
}

// ------------------------------------------------------------------ reading

/** The state `written` means, an address's `#dash/` before it read off; `StateFormError` where a
 * part is in none of the server's forms. */
export function readState(written: string): ViewState {
  const parts = new Map<PartKey, string[]>();
  const body = written.startsWith(PREFIX) ? written.slice(PREFIX.length) : written;
  for (const whole of body.split('&')) {
    if (!whole) continue;
    const [key, value] = cut(whole, '=', whole);
    const part = PARTS.find((one) => one === key);
    if (part === undefined) throw new StateFormError(whole);
    const found = parts.get(part) ?? [];
    if (found.length > 0 && !REPEATED.includes(part)) throw new StateFormError(whole);
    parts.set(part, [...found, value]);
  }
  const all = (key: PartKey) =>
    (parts.get(key) ?? []).map((value): [string, string] => [value, `${key}=${value}`]);
  const one = <T>(key: PartKey, read: (value: string, part: string) => T, absent: T): T => {
    const value = parts.get(key)?.[0];
    return value === undefined ? absent : read(value, `${key}=${value}`);
  };
  const [presentation, axis] = one('p', readPresentation, [DEFAULT.presentation, DEFAULT.axis]);
  const measures = all('m').map(([value, part]) => readMeasure(value, part));
  return {
    time: one('t', readTime, DEFAULT.time),
    by: one('by', named, DEFAULT.by),
    presentation,
    axis,
    measures: measures.length > 0 ? measures : DEFAULT.measures,
    levels: all('dr').map(([value, part]) => readLevel(value, part)),
    chips: all('c').map(([value, part]) => readChip(value, part)),
    quickFilters: one('b', readKeys, DEFAULT.quickFilters),
    color: one('col', (value, part) => (value === 'none' ? null : named(value, part)), DEFAULT.color),
    sort: one('o', readSort, DEFAULT.sort),
    drawer: one('d', (value, part) => oneOf(['items'], value, part) === 'items', DEFAULT.drawer),
    selected: one('sel', (value, part) => ({ value: readValue(value, part) }), DEFAULT.selected),
    itemGrain: one('ig', named, DEFAULT.itemGrain),
    item: one('it', readItem, DEFAULT.item),
    call: one('call', readWhole, DEFAULT.call),
    focus: one('f', readFocus, DEFAULT.focus),
    relative: one('rel', (value, part) => oneOf(['0', '1'], value, part) === '1', DEFAULT.relative),
    markers: one('mk', (value) => (value === 'none' ? [] : value.split(',').filter(Boolean)), DEFAULT.markers),
    draw: one('dw', readDraw, DEFAULT.draw),
    roll: one('roll', readRoll, DEFAULT.roll),
    lit: one('lit', readLit, DEFAULT.lit),
    events: one('ev', readEvents, DEFAULT.events),
    zoom: one('z', readZoom, DEFAULT.zoom),
  };
}

function readKeys(value: string, part: string): string[] {
  return value.split(',').filter(Boolean).map((key) => dec(key, part));
}

function readSort(value: string, part: string): ViewState['sort'] {
  const [direction, column] = cut(value, ',', part);
  return { direction: oneOf(DIRECTIONS, direction, part), column: dec(column, part) };
}

function readItem(value: string, part: string): ViewState['item'] {
  const [grain, key] = cut(value, ',', part);
  return { grain: named(grain, part), key: readValue(key, part) };
}

function readWhole(value: string, part: string): number {
  if (!WHOLE.test(value)) throw new StateFormError(part);
  return Number(value);
}

function readFocus(value: string, part: string): ViewState['focus'] {
  const [dimension, key] = cut(value, ':', part);
  return { dimension: named(dimension, part), key: readValue(key, part) };
}

function readLit(value: string, part: string): Value[] {
  return value.split(',').filter(Boolean).map((lit) => readValue(lit, part));
}

function readEvents(value: string, part: string): ViewState['events'] {
  return value
    .split(',')
    .filter(Boolean)
    .map((kind) => {
      const off = kind.startsWith('-');
      return { kind: dec(off ? kind.slice(1) : kind, part), drawn: !off };
    });
}

function readZoom(value: string, part: string): ViewState['zoom'] {
  const window = value.split(',');
  if (window.length !== 2) throw new StateFormError(part);
  const [low, high] = window.map((side) => readNumber(side, part));
  if (!(low < high)) throw new StateFormError(part);
  return [low, high];
}

function readTime(value: string, part: string): Time {
  const [head, ...rest] = value.split(',');
  if (head === 'wk') {
    if (rest.length === 0) throw new StateFormError(part);
    return { kind: 'weeks', starts: rest.map((start) => dec(start, part)) };
  }
  if (head === 'c') {
    if (rest.length !== 2) throw new StateFormError(part);
    const [start, end] = rest.map((side) => {
      const text = dec(side, part);
      if (text && !BOUND.test(text)) throw new StateFormError(part);
      return text || null;
    });
    return { kind: 'between', start, end };
  }
  if (rest.length > 0) throw new StateFormError(part);
  return { kind: 'preset', key: named(head, part) };
}

function readPresentation(value: string, part: string): [Presentation, string | null] {
  const [head, ...rest] = value.split(',');
  const presentation = oneOf(PRESENTATIONS, head, part);
  const axis = rest.length === 1 ? named(rest[0], part) : null;
  const takes =
    presentation === 'order'
      ? rest.length <= 1
      : presentation === 'time'
        ? axis !== null
        : rest.length === 0;
  if (!takes) throw new StateFormError(part);
  return [presentation, axis];
}

function readSimple(written: string, part: string): Simple {
  const open = written.indexOf('(');
  const head = open < 0 ? written : written.slice(0, open);
  const inside = open < 0 ? null : written.slice(open + 1);
  if (inside !== null && !inside.endsWith(')')) throw new StateFormError(part);
  const [figure, aggregate, grain, ...more] = head.split('.');
  if (!figure || !aggregate || grain === '' || more.length > 0) throw new StateFormError(part);
  const filters = (inside ?? '')
    .slice(0, -1)
    .split(';')
    .filter(Boolean)
    .map((filter) => {
      const negated = filter.startsWith('!');
      const [dimension, values] = cut(negated ? filter.slice(1) : filter, '=', part);
      return {
        dimension: named(dimension, part),
        values: values.split('|').map((one) => readValue(one, part)),
        negated,
      };
    });
  return { kind: 'simple', figure, aggregate, grain: grain ?? null, filters };
}

function readMeasure(written: string, part: string): Measure {
  if (!written.startsWith('r:')) return readSimple(written, part);
  const rest = written.slice(2);
  if (!rest.includes(':')) return { kind: 'ratio', key: named(rest, part) };
  const [name, sides] = cut(rest, ':', part);
  const [numerator, denominator] = cut(sides, '/', part);
  if (denominator.includes('/')) throw new StateFormError(part);
  return {
    kind: 'written',
    name: dec(name, part),
    numerator: readSimple(numerator, part),
    denominator: readSimple(denominator, part),
  };
}

function readLevel(written: string, part: string): Level {
  const [dimension, rest] = cut(written, ':', part);
  const at = rest.lastIndexOf('@');
  return {
    dimension: named(dimension, part),
    value: readValue(at < 0 ? rest : rest.slice(0, at), part),
    drilledFrom: at < 0 ? null : rest.slice(at + 1) || null,
  };
}

function readChip(written: string, part: string): Chip {
  let rest = written;
  let marked = false;
  let negated = false;
  while (rest.startsWith('~') || rest.startsWith('!')) {
    marked ||= rest.startsWith('~');
    negated ||= rest.startsWith('!');
    rest = rest.slice(1);
  }
  if (!rest.startsWith('@')) {
    const [dimension, values] = cut(rest, ':', part);
    return {
      kind: 'pin',
      dimension: named(dimension, part),
      values: values.split(',').map((value) => readValue(value, part)),
      negated,
      marked,
    };
  }
  const [kind, ...pieces] = rest.slice(1).split(',');
  if (kind === 'outliers') {
    if (negated || pieces.length > 0) throw new StateFormError(part);
    return { kind: 'outliers', marked };
  }
  if (pieces.length < 3) throw new StateFormError(part);
  const [operator, threshold, ...measure] = pieces;
  const condition = {
    operator: oneOf(OPERATORS, operator, part),
    number: readNumber(threshold, part),
    marked,
  };
  if (kind === 'items') {
    return { kind: 'items', ...condition, measure: readSimple(measure.join(','), part), negated };
  }
  if (kind !== 'rows' || negated) throw new StateFormError(part);
  return { kind: 'rows', ...condition, measure: readMeasure(measure.join(','), part) };
}

function readDraw(value: string, part: string): ViewState['draw'] {
  const draw = { ...DEFAULT.draw };
  for (const written of value.split(',')) {
    const [name, setting] = cut(written, ':', part);
    if (name === 'dots') draw.dots = oneOf(DOTS, setting, part);
    else draw[oneOf(SWITCHES, name, part)] = oneOf(['on', 'off'], setting, part) === 'on';
  }
  return draw;
}

function readRoll(value: string, part: string): ViewState['roll'] {
  const lengths = value.split(',');
  if (lengths.length !== 2 || !lengths.every((length) => /^[1-9]\d*$/.test(length))) {
    throw new StateFormError(part);
  }
  return { read: Number(lengths[0]), before: Number(lengths[1]) };
}

// ------------------------------------------------------------------ writing

function simpleKey(simple: Simple): string {
  const grain = simple.grain === null ? '' : `.${simple.grain}`;
  const filters = simple.filters
    .map(
      (filter) =>
        `${filter.negated ? '!' : ''}${filter.dimension}=${filter.values.map(writeValue).join('|')}`,
    )
    .join(';');
  return `${simple.figure}.${simple.aggregate}${grain}${filters ? `(${filters})` : ''}`;
}

/** A measure as the normal form writes it, and a sort names its column. */
function measureKey(measure: Measure): string {
  if (measure.kind === 'ratio') return `r:${measure.key}`;
  if (measure.kind === 'written') {
    return `r:${enc(measure.name)}:${simpleKey(measure.numerator)}/${simpleKey(measure.denominator)}`;
  }
  return simpleKey(measure);
}

function chipKey(chip: Chip): string {
  const marked = chip.marked ? '~' : '';
  if (chip.kind === 'outliers') return `${marked}@outliers`;
  if (chip.kind === 'rows') {
    return `${marked}@rows,${chip.operator},${number(chip.number)},${measureKey(chip.measure)}`;
  }
  const negated = chip.negated ? '!' : '';
  if (chip.kind === 'items') {
    return `${marked}${negated}@items,${chip.operator},${number(chip.number)},${simpleKey(chip.measure)}`;
  }
  return `${marked}${negated}${chip.dimension}:${chip.values.map(writeValue).join(',')}`;
}

/** A bound as the normal form writes it: a `T` before its time of day, its seconds only where they
 * are not zero. */
function bound(text: string | null): string {
  return text === null ? '' : enc(text.replace(' ', 'T').replace(/(T\d{2}:\d{2}):00$/, '$1'));
}

/** Each of `list` once by its `key`, the last of two with one key kept, in the order of their keys. */
function sorted<T>(list: readonly T[], key: (one: T) => string): T[] {
  return [...new Map(list.map((one) => [key(one), one])).entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([, one]) => one);
}

/** An instant's text ordered as the moment it names: by its milliseconds, then by the digits of its
 * fraction past them. */
function byMoment(a: string, b: string): number {
  const fraction = (text: string) => (/\.(\d+)/.exec(text)?.[1] ?? '').padEnd(9, '0');
  const fa = fraction(a);
  const fb = fraction(b);
  return Date.parse(a) - Date.parse(b) || (fa < fb ? -1 : fa > fb ? 1 : 0);
}

function writeTime(time: Time): string {
  if (time.kind === 'preset') return time.key;
  if (time.kind === 'weeks') {
    return ['wk', ...[...new Set(time.starts)].sort(byMoment).map(enc)].join(',');
  }
  return `c,${bound(time.start)},${bound(time.end)}`;
}

function parts(state: ViewState): [PartKey, string][] {
  const written: [PartKey, string][] = [
    ['t', writeTime(state.time)],
    ['by', state.by],
  ];
  if (state.presentation !== 'rows') {
    written.push(['p', state.axis === null ? state.presentation : `${state.presentation},${state.axis}`]);
  }
  written.push(...state.measures.map((measure): [PartKey, string] => ['m', measureKey(measure)]));
  written.push(
    ...state.levels.map((level): [PartKey, string] => [
      'dr',
      `${level.dimension}:${writeValue(level.value)}${level.drilledFrom ? `@${level.drilledFrom}` : ''}`,
    ]),
  );
  written.push(...state.chips.map((chip): [PartKey, string] => ['c', chipKey(chip)]));
  if (state.quickFilters.length > 0) {
    written.push(['b', sorted(state.quickFilters, (key) => key).map(enc).join(',')]);
  }
  written.push(['col', state.color ?? 'none']);
  if (state.sort !== null) written.push(['o', `${state.sort.direction},${enc(state.sort.column)}`]);
  if (state.drawer) written.push(['d', 'items']);
  if (state.selected !== null) written.push(['sel', writeValue(state.selected.value)]);
  if (state.itemGrain !== null) written.push(['ig', state.itemGrain]);
  if (state.item !== null) written.push(['it', `${state.item.grain},${writeValue(state.item.key)}`]);
  if (state.call !== null) written.push(['call', String(state.call)]);
  if (state.focus !== null) {
    written.push(['f', `${state.focus.dimension}:${writeValue(state.focus.key)}`]);
  }
  if (state.relative) written.push(['rel', '1']);
  if (state.markers !== null) {
    written.push(['mk', sorted(state.markers, (kind) => kind).join(',') || 'none']);
  }
  const draw = [
    ...(state.draw.dots === null ? [] : [`dots:${state.draw.dots}`]),
    ...SWITCHES.filter((switched) => !state.draw[switched]).map((switched) => `${switched}:off`),
  ];
  if (draw.length > 0) written.push(['dw', draw.join(',')]);
  if (state.roll.read !== DEFAULT.roll.read || state.roll.before !== DEFAULT.roll.before) {
    written.push(['roll', `${state.roll.read},${state.roll.before}`]);
  }
  if (state.lit !== null && state.lit.length > 0) {
    written.push(['lit', sorted(state.lit.map(writeValue), (lit) => lit).join(',')]);
  }
  if (state.events !== null && state.events.length > 0) {
    const events = sorted(state.events, (event) => event.kind);
    written.push(['ev', events.map((event) => `${event.drawn ? '' : '-'}${enc(event.kind)}`).join(',')]);
  }
  if (state.zoom !== null) written.push(['z', `${number(state.zoom[0])},${number(state.zoom[1])}`]);
  return written;
}

function joined(written: [PartKey, string][]): string {
  return written.map(([key, value]) => `${key}=${value}`).join('&');
}

/** The state in its normal form, the server's: each part in its place, a part at its default left
 * out but `t`, `by`, `m` and `col`. */
export function writeState(state: ViewState): string {
  return joined(parts(state));
}

/** The state's look-only parts as its normal form writes them. */
export function lookOf(state: ViewState): string[] {
  return parts(state)
    .filter(([key]) => LOOK.includes(key))
    .map(([key, value]) => `${key}=${value}`);
}

/** The state's normal form without its look-only parts: all the engine reads of it, so that a change
 * of look keys no new query. */
export function withoutLook(state: ViewState): string {
  return joined(parts(state).filter(([key]) => !LOOK.includes(key)));
}

