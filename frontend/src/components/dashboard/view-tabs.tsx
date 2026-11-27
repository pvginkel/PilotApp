/**
 * The dashboard's view tabs (F161.2; the mockup's `tabs.js`), in the document tabs' form
 * (`doc-tabs.tsx`, `.doc-tabs` and `.dtab`): a tab per view, its presentation's icon and its name,
 * its saved view's, else its drill's last level's, else its By's, and its square-x, the middle
 * button closing it too; Close all (copy-x) and, at the far right, a new view (copy-plus). With
 * one view there is no line: its tab stands at the global toolbar's left, its close going back to
 * the new tab's panel, and copy-plus ends the toolbar. A tab on the panel is "New view". The tabs'
 * model is `use-view-tabs.ts`.
 */

import { useLayoutEffect, useRef, type MouseEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { flushSync } from 'react-dom';
import { ChartBar, ChartLine, ChartNoAxesGantt, CopyPlus, CopyX, LayoutList, SquareX, Table } from 'lucide-react';
import { useValueLabels } from '@/hooks/use-value-labels';
import type { ViewTab, useViewTabMoves } from '@/hooks/use-view-tabs';
import { dimensionLabel } from '@/lib/dashboard/describe';
import { addressQuery, catalogueQuery, stateOf } from '@/lib/dashboard/queries';
import { levelNamed } from '@/lib/dashboard/scope';
import { readState, StateFormError, type ViewState } from '@/lib/dashboard/state';
import { cn } from '@/lib/utils';

type Moves = ReturnType<typeof useViewTabMoves>;

/** A view's icon, by what it presents: rows, a series in order or over time, lanes, a table; the new tab's panel. */
export function ViewIcon({ of }: { of: ViewState['presentation'] | 'panel' }) {
  switch (of) {
    case 'rows':
      return <ChartBar className="icon" aria-hidden="true" />;
    case 'order':
    case 'time':
      return <ChartLine className="icon" aria-hidden="true" />;
    case 'lanes':
      return <ChartNoAxesGantt className="icon" aria-hidden="true" />;
    case 'table':
      return <Table className="icon" aria-hidden="true" />;
    case 'panel':
      return <LayoutList className="icon" aria-hidden="true" />;
    default: {
      const unknown: never = of;
      return unknown;
    }
  }
}

function readable(written: string): ViewState | null {
  try {
    return readState(written);
  } catch (error) {
    if (error instanceof StateFormError) return null;
    throw error;
  }
}

/**
 * A tab's name and icon: on the panel "New view"; its saved view's name, as the views are read now;
 * else its drill's last level, its value's label (`use-value-labels.ts`); else its By's label.
 */
function useTabFace(tab: ViewTab): { name: string; icon: ViewState['presentation'] | 'panel' } {
  const queryClient = useQueryClient();
  const dimensions = useQuery(catalogueQuery('dimensions')).data;
  const stored = useQuery(catalogueQuery('stored')).data;
  const address = useQuery({ ...addressQuery(queryClient, tab.now ?? ''), enabled: tab.now !== null });
  const state = tab.now === null ? null : address.data === undefined ? readable(tab.now) : readState(stateOf(address.data.address));
  const last = state === null || state.levels.length === 0 ? null : levelNamed(state, state.levels.length - 1);
  const label = useValueLabels(tab.view === null && last !== null ? [last] : []);
  if (tab.now === null) return { name: 'New view', icon: 'panel' };
  const view = tab.view === null ? null : (stored?.saved_views?.find((each) => each.id === tab.view!.id)?.name ?? tab.view.name);
  const shows = state === null ? 'View' : last !== null ? label(last.dimension, last.value) : dimensionLabel(dimensions, state.by);
  return { name: view ?? shows, icon: state?.presentation ?? 'rows' };
}

/** The middle button's press scrolls nothing; its click closes the tab, as a browser's does. */
function middleCloses(onClose: () => void) {
  return {
    onMouseDown: (event: MouseEvent) => {
      if (event.button === 1) event.preventDefault();
    },
    onAuxClick: (event: MouseEvent) => {
      if (event.button !== 1) return;
      event.preventDefault();
      onClose();
    },
  };
}

function CloseButton({ name, onClose, testId }: { name: string; onClose: () => void; testId: string }) {
  return (
    <button type="button" className="dtab-x" onClick={onClose} title="Close" aria-label={`Close ${name}`} data-testid={testId}>
      <SquareX className="icon" aria-hidden="true" />
    </button>
  );
}

/** A new view, on the panel: the far right icon, on the line or at the toolbar's end. */
export function NewViewButton({ moves }: { moves: Moves }) {
  return (
    <button type="button" className="btn btn-ghost btn-sm btn-icon dash-new" onClick={moves.open} title="New view" aria-label="New view" data-testid="dashboard.new">
      <CopyPlus className="icon" aria-hidden="true" />
    </button>
  );
}

/** The one view's tab, at the global toolbar's left, without the line's primary. */
export function OneTab({ tab, moves }: { tab: ViewTab; moves: Moves }) {
  const { name, icon } = useTabFace(tab);
  const close = () => moves.close(tab.id);
  return (
    <span className="dash-onetab" title={name} {...middleCloses(close)} data-testid="dashboard.tab" data-tab={tab.id}>
      <ViewIcon of={icon} />
      <span className="t">{name}</span>
      <CloseButton name={name} onClose={close} testId="dashboard.tab.close" />
    </span>
  );
}

/** The line, while more than one view is open; the tab showing scrolled into it where the tabs do not fit. */
export function ViewTabLine({ tabs, at, moves }: { tabs: readonly ViewTab[]; at: ViewTab; moves: Moves }) {
  const row = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = row.current;
    const shown = element?.querySelector<HTMLElement>('.dtab.on');
    if (!element || !shown) return;
    if (shown.offsetLeft < element.scrollLeft || shown.offsetLeft + shown.offsetWidth > element.scrollLeft + element.clientWidth) {
      element.scrollLeft = shown.offsetLeft - (element.clientWidth - shown.offsetWidth) / 2;
    }
  }, [at.id, tabs.length]);
  // A cross takes its tab away under the focus: the tab showing then has it.
  const close = (id: string) => {
    flushSync(() => moves.close(id));
    row.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus();
  };
  return (
    <nav className="doc-tabs dash-tabs" aria-label="Views" data-testid="dashboard.tabs">
      <div ref={row} className="doc-tabs-row" role="tablist">
        {tabs.map((tab) => (
          <LineTab
            key={tab.id}
            tab={tab}
            on={tab.id === at.id}
            onShow={() => {
              if (tab.id !== at.id) moves.show(tab.id);
            }}
            onClose={() => close(tab.id)}
          />
        ))}
      </div>
      <button type="button" className="btn btn-ghost btn-sm btn-icon" onClick={moves.closeAll} title="Close all views" aria-label="Close all views" data-testid="dashboard.tabs.close-all">
        <CopyX className="icon" aria-hidden="true" />
      </button>
      <NewViewButton moves={moves} />
    </nav>
  );
}

function LineTab({ tab, on, onShow, onClose }: { tab: ViewTab; on: boolean; onShow: () => void; onClose: () => void }) {
  const { name, icon } = useTabFace(tab);
  return (
    <div className={cn('dtab', on && 'on')} title={name} {...middleCloses(onClose)} data-testid="dashboard.tabs.tab" data-tab={tab.id}>
      <button type="button" className="dtab-main" role="tab" aria-selected={on} onClick={onShow} data-testid="dashboard.tabs.tab.show">
        <ViewIcon of={icon} />
        <span className="t" data-testid="dashboard.tabs.tab.name">
          {name}
        </span>
      </button>
      <CloseButton name={name} onClose={onClose} testId="dashboard.tabs.tab.close" />
    </div>
  );
}
