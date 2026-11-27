/**
 * The view card's head on the page (F163.2, F163.3, F163.7; the mockup's `by.js`, `starList`,
 * `byPanel` and `colorPanel`, and `view.js`, `renderPresentation`): By's list and Color's, and what
 * a pick of a By, a presentation or a color makes of the state. Pure, with no DOM; a dimension's
 * words are the catalogue's.
 *
 * By's list holds the parts and the attributes the catalogue gives, in its order, each with its
 * count of values in the view's scope once that has come; those with one value or none hide behind
 * one link, "n hidden", which unfolds them in place, muted, as a search finds them too; the By at
 * hand and a favorite never hide. Color's list is By's with no counts and none hidden, None and
 * Token kind under a rule after it: a color is a part, an attribute, the token's kind or none
 * (`backend/app/dashboard/reading.py`). In both a favorite rises to Favorites at the top, in the
 * list's own order; None takes no star.
 */

import type { Catalogue } from './queries';
import type { ViewState } from './state';

type Dimensions = Catalogue | undefined;

/** The groups of By's list, which Color's holds too. */
const GROUPS = [
  ['part', 'Parts'],
  ['attribute', 'Attributes'],
] as const;

/** The color that splits Tokens alone, by the kind of token. */
const TOKEN_KIND = 'token_kind';

export interface Entry {
  /** The dimension's key, `token_kind`; none for Color's None. */
  key: string | null;
  label: string;
  /** What it is, its tooltip. */
  line: string | null;
  /** Its values in the view's scope; none until By's counts have come, and in Color's list. */
  count: number | null;
  /** It is the one the view has. */
  on: boolean;
  /** One that hides, shown muted where the list is unfolded or searched. */
  muted: boolean;
  /** It takes a star: all but None. */
  stars: boolean;
  starred: boolean;
}

export interface Group {
  /** Its heading; none for Color's None and Token kind, under a rule. */
  heading: string | null;
  entries: Entry[];
}

/** The list as drawn: its groups, those with no entry left out. */
interface Listed {
  groups: Group[];
  /** The entries behind "n hidden"; none where the list is unfolded or searched. */
  hidden: number;
}

/** Favorites first, the starred in the list's own order, then each group's entries that are not, those the search finds. */
function listed(groups: Group[], search: string): Group[] {
  const needle = search.trim().toLowerCase();
  const hit = (entry: Entry) => needle === '' || entry.label.toLowerCase().includes(needle);
  const favorites = groups.flatMap((group) => group.entries.filter((entry) => entry.starred && hit(entry)));
  return [{ heading: 'Favorites', entries: favorites }, ...groups.map((group) => ({ ...group, entries: group.entries.filter((entry) => !entry.starred && hit(entry)) }))].filter(
    (group) => group.entries.length > 0,
  );
}

const offered = (dimensions: Dimensions, group: string) => dimensions?.dimensions?.filter((dimension) => dimension.group === group) ?? [];

interface ByOptions {
  /** The By at hand. */
  by: string;
  /** The person's favorites in By's list, by key. */
  favourites: readonly string[];
  /** The counts come so far, by dimension. */
  counts: ReadonlyMap<string, number>;
  search: string;
  /** "n hidden" was pressed while the panel is open. */
  unfolded: boolean;
}

/** By's list. */
export function byList(dimensions: Dimensions, { by, favourites, counts, search, unfolded }: ByOptions): Listed {
  const starred = new Set(favourites);
  const groups = GROUPS.map(([group, heading]) => ({
    heading,
    entries: offered(dimensions, group).map((dimension): Entry => {
      const count = counts.get(dimension.key) ?? null;
      const on = dimension.key === by;
      const favourite = starred.has(dimension.key);
      return { key: dimension.key, label: dimension.label, line: dimension.line, count, on, muted: count !== null && count <= 1 && !on && !favourite, stars: true, starred: favourite };
    }),
  }));
  const open = unfolded || search.trim() !== '';
  const hidden = groups.reduce((sum, group) => sum + group.entries.filter((entry) => entry.muted).length, 0);
  const shown = open ? groups : groups.map((group) => ({ ...group, entries: group.entries.filter((entry) => !entry.muted) }));
  return { groups: listed(shown, search), hidden: open ? 0 : hidden };
}

interface ColorOptions {
  /** The color at hand, none for None. */
  color: string | null;
  /** The person's favorites in Color's list, by key. */
  favourites: readonly string[];
  search: string;
}

/** Color's list. */
export function colorList(dimensions: Dimensions, { color, favourites, search }: ColorOptions): Group[] {
  const starred = new Set(favourites);
  const entry = (key: string | null, label: string, line: string | null): Entry => ({
    key,
    label,
    line,
    count: null,
    on: key === color,
    muted: false,
    stars: key !== null,
    starred: key !== null && starred.has(key),
  });
  return listed(
    [
      ...GROUPS.map(([group, heading]) => ({ heading, entries: offered(dimensions, group).map((dimension) => entry(dimension.key, dimension.label, dimension.line)) })),
      { heading: null, entries: [entry(null, 'None', 'No color: a bar is not split'), entry(TOKEN_KIND, 'Token kind', 'Splits Tokens alone, by the kind of token')] },
    ],
    search,
  );
}

/** The words a view's color reads in: None, Token kind, else its dimension's label. */
export function colorWords(dimensions: Dimensions, color: string | null): string {
  if (color === null) return 'None';
  if (color === TOKEN_KIND) return 'Token kind';
  return dimensions?.dimensions?.find((dimension) => dimension.key === color)?.label ?? color;
}

/**
 * The view By `by`: the sort and the drawer's row let go; a series in order where `by` has no order
 * dimension, and lanes where it is no part, falling back to rows, a series in order reading its
 * first order dimension.
 */
export function byPicked(state: ViewState, by: string, dimensions: Dimensions): ViewState {
  const all = dimensions?.dimensions ?? [];
  const ordered = all.some((dimension) => dimension.group === 'order' && dimension.base === by);
  const part = all.find((dimension) => dimension.key === by)?.group === 'part';
  const shown =
    (state.presentation === 'order' && !ordered) || (state.presentation === 'lanes' && !part)
      ? ({ presentation: 'rows', axis: null } as const)
      : state.presentation === 'order'
        ? { axis: null }
        : {};
  return { ...state, ...shown, by, sort: null, selected: null, item: null, itemGrain: null };
}

/** The view presented as rows or as a table: the sort kept but a series' sort on its axis, the drawer's row let go. */
export function presented(state: ViewState, presentation: 'rows' | 'table'): ViewState {
  return { ...state, presentation, axis: null, sort: state.sort?.column === 'axis' ? null : state.sort, selected: null, item: null };
}

/** The view colored by `color`, none for None: the color's values lit let go with it. */
export const colored = (state: ViewState, color: string | null): ViewState => ({ ...state, color, lit: null });
