/**
 * The new tab's panel (F161.4; the mockup's `views.js`, `renderPanel`): what a tab shows before it
 * has a view, with no chart, its block centred in the panel's height. A head row that stays, with
 * a find field, which filters both lists on the name as typed, case aside, Esc clearing it, and
 * Start from scratch; under it two lists side by side, System views at the left and Saved views at
 * the right, each scrolling on its own under its heading, a narrow panel stacking them; in each the
 * starred first, in the order they were starred (F155.2), then the rest in the server's order.
 *
 * A row is a view's name with its presentation's icon, what it draws and the view's note in its
 * tooltip, and opens the view in this tab. At its right, on hover and on focus, a saved view's
 * rename, typed in place, its remove, behind a dialog, and its star; a system view's star alone,
 * since nobody renames, removes or replaces one (F161.7). The lists are everyone's: read again
 * each time the panel shows.
 */

import { useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Pencil, Plus, Star, Trash2 } from 'lucide-react';
import { ConfirmDialog } from '@/components/shared/dialog';
import { failureOf } from '@/hooks/use-dashboard-view';
import { SCRATCH, type useViewTabMoves, type ViewTab } from '@/hooks/use-view-tabs';
import { useViewWords } from '@/hooks/use-view-words';
import { isNameTaken, useViewWrites } from '@/hooks/use-view-writes';
import { describe, type Words } from '@/lib/dashboard/describe';
import { catalogueQuery, favouritesQuery, stateOf, type SavedView } from '@/lib/dashboard/queries';
import { readState } from '@/lib/dashboard/state';
import { cn } from '@/lib/utils';
import { Banner, type Wrote } from './banner';
import { ViewIcon } from './view-tabs';

type Moves = ReturnType<typeof useViewTabMoves>;
type Writes = ReturnType<typeof useViewWrites>;

interface ViewsPanelProps {
  tab: ViewTab;
  moves: Moves;
  /** A write's failure, which the banner shows beside the lists' own. */
  wrote: Wrote;
}

export function ViewsPanel({ tab, moves, wrote }: ViewsPanelProps) {
  const stored = useQuery({ ...catalogueQuery('stored'), staleTime: 0 });
  const favourites = useQuery({ ...favouritesQuery(), staleTime: 0 });
  const words = useViewWords();
  const writes = useViewWrites();
  const [find, setFind] = useState('');
  const [removing, setRemoving] = useState<SavedView | null>(null);
  const cols = useRef<HTMLDivElement>(null);
  const lists = useRef<(HTMLDivElement | null)[]>([]);

  const typed = (value: string) => {
    // The block is centred in the panel's height: the lists keep the height they had as the find
    // began, so that the field does not move under the words typed into it.
    const element = cols.current!;
    element.style.height = value === '' ? '' : element.style.height || `${element.getBoundingClientRect().height}px`;
    for (const each of [...lists.current, element]) if (each) each.scrollTop = 0;
    setFind(value);
  };
  const onFindKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Escape' || find === '') return;
    event.preventDefault();
    typed('');
  };

  const views = stored.data?.saved_views;
  const starred = favourites.data?.views;
  const needle = find.trim().toLowerCase();
  const hit = (view: SavedView) => view.name.toLowerCase().includes(needle);
  /** The views of one list as the panel orders them, the starred first; none until both are read. */
  const listed = (system: boolean) => {
    if (views == null || starred === undefined) return undefined;
    const own = views.filter((view) => view.system === system);
    const first = starred.flatMap((id) => own.filter((view) => view.id === id));
    return { all: own.length, shown: [...first, ...own.filter((view) => !starred.includes(view.id))].filter(hit) };
  };
  const open = (view: SavedView | null) => moves.openView(tab.id, view === null ? null : { id: view.id, name: view.name }, view === null ? SCRATCH : stateOf(view.address));
  const list = (system: boolean, index: number) => (
    <ViewList
      label={system ? 'System views' : 'Saved views'}
      testId={system ? 'dashboard.panel.system' : 'dashboard.panel.saved'}
      views={listed(system)}
      none={
        system
          ? 'No view matches.'
          : listed(false)?.all === 0
            ? 'No view is saved yet. Save view, in a view’s toolbar, keeps one here.'
            : 'No view matches.'
      }
      starred={starred ?? []}
      words={words}
      writes={writes}
      onOpen={open}
      onRemove={setRemoving}
      listRef={(element) => void (lists.current[index] = element)}
    />
  );
  return (
    <>
      <Banner failures={[failureOf(stored), failureOf(favourites), wrote.failure]} onClose={(failure) => failure === wrote.failure && wrote.close()} />
      <div className="dash-panel" aria-label="New view" data-testid="dashboard.panel">
        <div className="dash-views">
          <div className="dash-views-top" data-testid="dashboard.panel.head">
            <input
              type="search"
              className="field dash-views-find"
              placeholder="Find a view"
              aria-label="Find a view"
              value={find}
              onChange={(event) => typed(event.target.value)}
              onKeyDown={onFindKey}
              data-testid="dashboard.panel.find"
            />
            <button type="button" className="btn" title="This quota week, by project, cost alone" onClick={() => open(null)} data-testid="dashboard.panel.scratch">
              <Plus className="icon" aria-hidden="true" />
              Start from scratch
            </button>
          </div>
          <div ref={cols} className="dash-views-cols" data-testid="dashboard.panel.lists">
            {list(true, 0)}
            {list(false, 1)}
          </div>
        </div>
      </div>
      {removing !== null && (
        <ConfirmDialog
          title={`Remove the view "${removing.name}"?`}
          lines={['It is removed for everyone.']}
          note="Tabs that have it open keep what they show."
          act={{ label: 'Remove view', icon: Trash2 }}
          pending={writes.remove.isPending}
          onConfirm={() => writes.remove.mutate(removing, { onSettled: () => setRemoving(null) })}
          onCancel={() => setRemoving(null)}
          testId="dashboard.panel.remove-dialog"
        />
      )}
    </>
  );
}

interface ViewListProps {
  label: string;
  testId: string;
  /** Its views in the panel's order, those the find leaves, and how many it holds; none until read. */
  views: { all: number; shown: SavedView[] } | undefined;
  /** What it says where it shows none. */
  none: string;
  starred: readonly string[];
  words: Words;
  writes: Writes;
  onOpen: (view: SavedView) => void;
  onRemove: (view: SavedView) => void;
  listRef: (element: HTMLDivElement | null) => void;
}

/** One list under its heading, which has a line under it while the list is scrolled from its top. */
function ViewList({ label, testId, views, none, starred, words, writes, onOpen, onRemove, listRef }: ViewListProps) {
  const [scrolled, setScrolled] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  return (
    <section className={cn('dash-views-part', scrolled && 'scrolled')} aria-label={label} data-testid={testId}>
      <h2 className="dash-views-head">{label}</h2>
      <div ref={listRef} className="dash-views-list" onScroll={(event) => setScrolled(event.currentTarget.scrollTop > 0)}>
        {views?.shown.map((view) =>
          renaming === view.id ? (
            <Renaming key={view.id} view={view} writes={writes} onDone={() => setRenaming(null)} />
          ) : (
            <ViewRow
              key={view.id}
              view={view}
              starred={starred.includes(view.id)}
              words={words}
              onOpen={() => onOpen(view)}
              onStar={(on) => writes.star.mutate({ view, on })}
              onRename={() => setRenaming(view.id)}
              onRemove={() => onRemove(view)}
            />
          ),
        )}
        {views !== undefined && views.shown.length === 0 && (
          <p className="dash-views-none" data-testid={`${testId}.none`}>
            {none}
          </p>
        )}
      </div>
    </section>
  );
}

interface ViewRowProps {
  view: SavedView;
  starred: boolean;
  words: Words;
  onOpen: () => void;
  onStar: (on: boolean) => void;
  onRename: () => void;
  onRemove: () => void;
}

function ViewRow({ view, starred, words, onOpen, onStar, onRename, onRemove }: ViewRowProps) {
  const state = readState(stateOf(view.address));
  const what = describe(state, words);
  const act = (title: string, className: string, onClick: () => void, icon: ReactNode, testId: string, pressed?: boolean) => (
    <button
      type="button"
      className={cn('btn btn-ghost btn-sm btn-icon', className)}
      title={title}
      aria-label={`${title}: ${view.name}`}
      aria-pressed={pressed}
      onClick={onClick}
      data-testid={`dashboard.panel.view.${testId}`}
    >
      {icon}
    </button>
  );
  return (
    <div className={cn('dash-viewrow', view.system && 'system', starred && 'fav')} data-testid="dashboard.panel.view" data-view={view.id}>
      <button type="button" className="dash-view" title={view.note === null ? what : `${what}\n${view.note}`} onClick={onOpen} data-testid="dashboard.panel.view.open">
        <ViewIcon of={state.presentation} />
        <span className="txt">
          <span className="name" data-testid="dashboard.panel.view.name">
            {view.name}
          </span>
        </span>
      </button>
      <span className="dash-view-acts">
        {!view.system && act('Rename this view', 'dash-view-edit', onRename, <Pencil className="icon" aria-hidden="true" />, 'rename')}
        {!view.system && act('Remove this view', 'dash-view-x', onRemove, <Trash2 className="icon" aria-hidden="true" />, 'remove')}
        {act(
          starred ? 'Remove from the favorites' : 'Add to the favorites',
          cn('dash-view-star', starred && 'on'),
          () => onStar(!starred),
          <Star className="icon" aria-hidden="true" />,
          'star',
          starred,
        )}
      </span>
    </div>
  );
}

/** A rename, typed in place: Enter saves, Esc or a click away cancels; a name another saved view has is said under the field, which stays open. */
function Renaming({ view, writes, onDone }: { view: SavedView; writes: Writes; onDone: () => void }) {
  const [name, setName] = useState(view.name);
  const [taken, setTaken] = useState<string | null>(null);
  const { presentation } = readState(stateOf(view.address));
  const busy = writes.rename.isPending;
  const save = () => {
    const to = name.trim();
    if (busy) return;
    if (to === '' || to === view.name) {
      onDone();
      return;
    }
    writes.rename.mutate(
      { view, name: to },
      {
        onSuccess: onDone,
        onError: (error) => {
          if (isNameTaken(error)) setTaken(to);
          else onDone();
        },
      },
    );
  };
  return (
    <div className="dash-viewrow renaming" data-testid="dashboard.panel.view" data-view={view.id}>
      <div className="dash-view">
        <ViewIcon of={presentation} />
        <span className="txt">
          <input
            type="text"
            className="field dash-view-name"
            value={name}
            maxLength={80}
            aria-label={`The new name of the view ${view.name}`}
            autoFocus
            onFocus={(event) => event.currentTarget.select()}
            onChange={(event) => {
              setName(event.target.value);
              setTaken(null);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') save();
              else if (event.key === 'Escape') onDone();
            }}
            onBlur={() => {
              if (!busy) onDone();
            }}
            data-testid="dashboard.panel.view.name-field"
          />
          {taken !== null && (
            <span className="what" data-testid="dashboard.panel.view.taken">
              {`A view named "${taken}" exists already`}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}
