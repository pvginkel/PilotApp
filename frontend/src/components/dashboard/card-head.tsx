/**
 * The view's card's head, its toolbar (F163.1; the mockup's `view.js`, `renderView`, and `by.js`):
 * By and the presentation at the left; at the right Color, Relative and, with a table, its Copy and
 * CSV, each an icon named by its tooltip.
 *
 * By names the By at hand and opens its list (`head.ts`): the parts and the attributes, each with
 * its count of values in the view's scope, asked as the list opens and each shown as it arrives
 * (`use-by-counts.ts`); those with one value or none behind "n hidden", which unfolds them muted; a
 * search; a star on hover, the person's favorite rising to Favorites at the top. Color names the
 * color at hand and opens By's list with no counts and none hidden, None and Token kind under a rule
 * after it. Each list scrolls in its popover's one scrollbar, its search standing above. The
 * presentation is one segmented control of Rows and Table; a view of another presentation, drawn as
 * rows until its slice draws it, has neither pressed. Relative is greyed while the table is drawn,
 * which shows the figures as they are. A By, a presentation or a color picked is a new entry,
 * Relative, a look, the entry in place (F160.4).
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, Download, Star } from 'lucide-react';
import { CopyButton } from '@/components/shared/copy-button';
import { Popover } from '@/components/shared/popover';
import { useByCounts } from '@/hooks/use-by-counts';
import { useFailureShown } from '@/hooks/use-dashboard-view';
import { useFavouriteWrites } from '@/hooks/use-view-writes';
import { dimensionLabel } from '@/lib/dashboard/describe';
import { whole } from '@/lib/dashboard/figures';
import { byList, byPicked, colored, colorList, colorWords, presented, type Group } from '@/lib/dashboard/head';
import { catalogueQuery, favouritesQuery } from '@/lib/dashboard/queries';
import type { Rows } from '@/lib/dashboard/rows-layout';
import type { ViewState } from '@/lib/dashboard/state';
import { tableText } from '@/lib/dashboard/table';
import { cn } from '@/lib/utils';
import { Segmented } from './segmented';

interface CardHeadProps {
  state: ViewState;
  /** The answer drawn, which Copy and CSV take; none before the first. */
  rows: Rows | undefined;
  /** The view moved to `state`: a new entry, or the entry in place where `replace`. */
  onState: (state: ViewState, replace?: boolean) => void;
}

export function CardHead({ state, rows, onState }: CardHeadProps) {
  const dimensions = useQuery(catalogueQuery('dimensions')).data;
  const by = dimensionLabel(dimensions, state.by);
  const table = state.presentation === 'table';
  return (
    <div className="dash-cardbar" role="toolbar" aria-label="View" data-testid="dashboard.card.head">
      <div className="dash-cardbar-part">
        <Picker
          kind="By"
          words={by}
          title={dimensions?.dimensions?.find((dimension) => dimension.key === state.by)?.line}
          testId="dashboard.by"
          panel={(close) => (
            <ByPanel
              state={state}
              onPick={(key) => {
                close();
                if (key !== null && key !== state.by) onState(byPicked(state, key, dimensions));
              }}
              onClose={close}
            />
          )}
        />
        <Segmented<ViewState['presentation']>
          label="Presentation"
          value={state.presentation}
          onChange={(presentation) => {
            if ((presentation === 'rows' || presentation === 'table') && presentation !== state.presentation) onState(presented(state, presentation));
          }}
          options={[
            { value: 'rows', label: 'Rows', title: `A row per ${by}`, testId: 'dashboard.presentation.rows' },
            { value: 'table', label: 'Table', title: `The rows as a table, with every measure’s n`, testId: 'dashboard.presentation.table' },
          ]}
        />
      </div>
      <div className="dash-cardbar-part end">
        <Picker
          kind="Color"
          words={colorWords(dimensions, state.color)}
          title="Split the bars by a part, an attribute or the token’s kind"
          end
          testId="dashboard.color"
          panel={(close) => (
            <ColorPanel
              state={state}
              onPick={(key) => {
                close();
                if (key !== state.color) onState(colored(state, key));
              }}
              onClose={close}
            />
          )}
        />
        <button
          type="button"
          className={cn('btn btn-sm dash-toggle', state.relative && 'on', table && 'off')}
          aria-pressed={state.relative}
          aria-disabled={table || undefined}
          title={table ? 'Relative reads rows; the table shows the figures as they are' : 'Every figure as a multiple of the peers’ median of the same measure'}
          onClick={() => {
            if (!table) onState({ ...state, relative: !state.relative }, true);
          }}
          data-testid="dashboard.relative"
        >
          Relative
        </button>
        {table && rows !== undefined && <TableTools rows={rows} />}
      </div>
    </div>
  );
}

interface PickerProps {
  /** What it picks, muted before the choice at hand. */
  kind: string;
  words: string;
  title: string | undefined;
  /** It stands in the head's right group, its list dropping to the left. */
  end?: boolean;
  testId: string;
  panel: (close: () => void) => ReactNode;
}

/** A button that names what it picks and the choice at hand, its list in a popover. */
function Picker({ kind, words, title, end = false, testId, panel }: PickerProps) {
  return (
    <Popover
      label={kind}
      className={cn('dash-list-pop', end && 'end')}
      testId={`${testId}.pop`}
      trigger={({ open, toggle }) => (
        <button type="button" className="btn btn-sm dash-pick" aria-haspopup="dialog" aria-expanded={open} title={title} onClick={toggle} data-testid={testId}>
          <span className="k">{kind}</span>
          <span data-testid={`${testId}.words`}>{words}</span>
          <ChevronDown className="chev" aria-hidden="true" />
        </button>
      )}
    >
      {panel}
    </Popover>
  );
}

interface PanelProps {
  state: ViewState;
  onPick: (key: string | null) => void;
  onClose: () => void;
}

function ByPanel({ state, onPick, onClose }: PanelProps) {
  const dimensions = useQuery(catalogueQuery('dimensions')).data;
  const favourites = useQuery(favouritesQuery());
  useFailureShown(favourites);
  const counts = useByCounts(state);
  const [search, setSearch] = useState('');
  const [unfolded, setUnfolded] = useState(false);
  if (dimensions?.dimensions == null) return <p className="empty dash-pane-wait">Loading the dimensions…</p>;
  const { groups, hidden } = byList(dimensions, { by: state.by, favourites: favourites.data?.by ?? [], counts, search, unfolded });
  return (
    <DimensionList
      menu="by"
      testId="dashboard.by"
      searchLabel="Search the dimensions"
      search={search}
      onSearch={setSearch}
      groups={groups}
      onPick={onPick}
      onClose={onClose}
      more={
        hidden > 0 && (
          <button type="button" className="dash-dimmore" title="With one value or none in this scope" onClick={() => setUnfolded(true)} data-testid="dashboard.by.more">
            {whole(hidden)} hidden
          </button>
        )
      }
    />
  );
}

function ColorPanel({ state, onPick, onClose }: PanelProps) {
  const dimensions = useQuery(catalogueQuery('dimensions')).data;
  const favourites = useQuery(favouritesQuery());
  useFailureShown(favourites);
  const [search, setSearch] = useState('');
  if (dimensions?.dimensions == null) return <p className="empty dash-pane-wait">Loading the dimensions…</p>;
  return (
    <DimensionList
      menu="color"
      testId="dashboard.color"
      searchLabel="Search the colors"
      search={search}
      onSearch={setSearch}
      groups={colorList(dimensions, { color: state.color, favourites: favourites.data?.color ?? [], search })}
      onPick={onPick}
      onClose={onClose}
    />
  );
}

interface DimensionListProps {
  menu: 'by' | 'color';
  testId: string;
  searchLabel: string;
  search: string;
  onSearch: (search: string) => void;
  groups: Group[];
  onPick: (key: string | null) => void;
  /** Esc in the search with nothing typed: the list closed, as the search holds Esc from the page's keys. */
  onClose: () => void;
  /** What follows the groups. */
  more?: ReactNode;
}

/** A list of dimensions with its search and its stars, its groups as `head.ts` lists them; Esc in the search clears it, then closes the list. */
function DimensionList({ menu, testId, searchLabel, search, onSearch, groups, onPick, onClose, more }: DimensionListProps) {
  const { favour } = useFavouriteWrites();
  // Focused once the list stands where it is shown, so that nothing scrolls to it before.
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => field.current!.focus({ preventScroll: true }), []);
  return (
    <div className="dash-dimlist" data-testid={`${testId}.list`}>
      <input
        ref={field}
        type="search"
        className="field"
        value={search}
        placeholder="Search"
        aria-label={searchLabel}
        autoComplete="off"
        spellCheck={false}
        onChange={(event) => onSearch(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== 'Escape') return;
          event.preventDefault();
          if (search === '') onClose();
          else onSearch('');
        }}
        data-testid={`${testId}.search`}
      />
      {groups.length === 0 && <p className="empty">No dimension of that name</p>}
      {groups.map((group) => (
        <div key={group.heading ?? ''} role="group" aria-label={group.heading ?? undefined} className={cn('dash-dimgroup', group.heading === null && 'bare')} data-testid={`${testId}.group`}>
          {group.heading !== null && <div className="menu-head">{group.heading}</div>}
          {group.entries.map((entry) => {
            const act = entry.starred ? 'Remove from the favorites' : 'Add to the favorites';
            return (
              <div key={entry.key ?? ''} className={cn('dash-dimrow', entry.on && 'on', entry.muted && 'dim')} data-key={entry.key ?? '~'} data-testid={`${testId}.entry`}>
                <button type="button" className="menu-item" title={entry.line ?? undefined} aria-current={entry.on || undefined} onClick={() => onPick(entry.key)} data-testid={`${testId}.entry.pick`}>
                  <span className="t" data-testid={`${testId}.entry.label`}>
                    {entry.label}
                  </span>
                  {entry.count !== null && (
                    <span className="n" title={`${whole(entry.count)} ${entry.count === 1 ? 'value' : 'values'} in scope`} data-testid={`${testId}.entry.count`}>
                      {whole(entry.count)}
                    </span>
                  )}
                </button>
                {entry.stars && (
                  <button
                    type="button"
                    className={cn('star', entry.starred && 'on')}
                    aria-pressed={entry.starred}
                    title={act}
                    aria-label={`${act}: ${entry.label}`}
                    onClick={() => favour.mutate({ menu, dimension: entry.key!, on: !entry.starred })}
                    data-testid={`${testId}.entry.star`}
                  >
                    <Star className="icon" aria-hidden="true" />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      ))}
      {more}
    </div>
  );
}

/** The table's Copy and CSV: every row of the answer, tab-separated to the clipboard, comma-separated to a file. */
function TableTools({ rows }: { rows: Rows }) {
  const copied = useMemo(() => tableText(rows, '\t'), [rows]);
  const download = () => {
    const url = URL.createObjectURL(new Blob([tableText(rows, ',')], { type: 'text/csv' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `dashboard-${rows.by.key}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url));
  };
  const csv = 'Download the rows as a CSV file';
  return (
    <>
      <CopyButton text={copied} title="Copy the rows, tab-separated" testId="dashboard.copy" />
      <button type="button" className="btn btn-ghost btn-sm btn-icon" title={csv} aria-label={csv} onClick={download} data-testid="dashboard.csv">
        <Download className="icon" aria-hidden="true" />
      </button>
    </>
  );
}
