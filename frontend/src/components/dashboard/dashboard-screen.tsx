/**
 * The dashboard's screen (F160), a module of its own, which the shell loads at the dashboard's
 * first opening (F160.2): a page that never opens it never loads it. Out of sight it lies under
 * the Projects screen, in its box, out of the flow, its visibility off and inert, and what lies
 * under it is out of view (`ScreenInView`); it keeps its scroll and its answers, and reads again
 * on the walk's event whichever screen shows (`use-walk-reads.ts`).
 *
 * Top to bottom (the mockup's `frame.js`): the line of view tabs, while more than one is open
 * (`view-tabs.tsx`); then the tab at hand: on the new tab's panel (`views-panel.tsx`), or its
 * view, the global toolbar, with one view its tab at the toolbar's left and copy-plus at its end;
 * the banner, what failed; the main area, which scrolls, holding the view's card. The tabs follow
 * the address (`use-view-tabs.ts`), read off the hash as the browser holds it; `#dash` names none
 * and shows the tab at hand as it was left, the panel at the first opening. The toolbar's right
 * holds Reset and Save view, and no Refresh (F160.7): the screen reads again by itself.
 *
 * Each tab's answers are kept for as long as the tab (F160.6): a tab out of sight holds its view's
 * queries without reading them, so that the walk's event leaves them stale and they are read
 * again as the tab is brought into view. Its scroll is kept with it in the browser (F160.10).
 */

import { useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useDashboardView, type Failure } from '@/hooks/use-dashboard-view';
import { ScreenInView } from '@/hooks/use-screens';
import { keepScroll, scrollOf, useViewTabMoves, useViewTabs, useViewTabsAt, type ViewTab } from '@/hooks/use-view-tabs';
import { WriteFailures } from '@/hooks/use-view-writes';
import { useWalkReads } from '@/hooks/use-walk-reads';
import { addressQuery, rowsQuery, stateOf } from '@/lib/dashboard/queries';
import { readState, withoutLook } from '@/lib/dashboard/state';
import { Banner, type Wrote } from './banner';
import { RowsChart } from './rows-chart';
import { ResetButton, SaveViewButton } from './save-view';
import { NewViewButton, OneTab, ViewTabLine } from './view-tabs';
import { ViewsPanel } from './views-panel';
import './dashboard.css';

export function DashboardScreen({ shown }: { shown: boolean }) {
  useWalkReads();
  useViewTabsAt(shown);
  const { tabs, at } = useViewTabs();
  const moves = useViewTabMoves();
  // A write's failure, until its banner is closed.
  const [failed, setFailed] = useState<Failure | null>(null);
  const wrote = { failure: failed, close: () => setFailed(null) };
  return (
    <ScreenInView value={shown}>
      <section className={shown ? 'dash' : 'dash away'} inert={!shown} aria-label="Dashboard" data-testid="dashboard">
        {/* eslint-disable-next-line no-restricted-properties -- a real timestamp: when the write failed, set against a read's errorUpdatedAt */}
        <WriteFailures.Provider value={(error) => setFailed({ error, at: Date.now() })}>
          {at !== null && (
            <>
              {tabs.length > 1 && <ViewTabLine tabs={tabs} at={at} moves={moves} />}
              {at.now === null ? (
                <ViewsPanel key={at.id} tab={at} moves={moves} wrote={wrote} />
              ) : (
                <View key={at.id} tab={at} now={at.now} one={tabs.length === 1} moves={moves} wrote={wrote} />
              )}
              {tabs.map((tab) => tab !== at && tab.now !== null && <KeptView key={tab.id} now={tab.now} />)}
            </>
          )}
        </WriteFailures.Provider>
      </section>
    </ScreenInView>
  );
}

interface ViewProps {
  tab: ViewTab;
  now: string;
  /** It is the one view: its tab stands at the toolbar's left, copy-plus at its end. */
  one: boolean;
  moves: ReturnType<typeof useViewTabMoves>;
  wrote: Wrote;
}

function View({ tab, now, one, moves, wrote }: ViewProps) {
  const view = useDashboardView(now);
  const { rows } = view;
  const main = useKeptScroll(tab.id);
  return (
    <>
      <div className="dash-bar" role="toolbar" aria-label="Dashboard" data-testid="dashboard.toolbar">
        {one && <OneTab tab={tab} moves={moves} />}
        <span className="grow" />
        <ResetButton tab={tab} now={now} moves={moves} />
        <SaveViewButton tab={tab} now={now} />
        {one && <NewViewButton moves={moves} />}
      </div>
      <Banner failures={[view.failure, wrote.failure]} onClose={(failure) => failure === wrote.failure && wrote.close()} />
      <div ref={main} className="dash-main" data-testid="dashboard.main">
        <section className={view.changing ? 'dash-card changing' : 'dash-card'} aria-label="View" aria-busy={view.changing} data-testid="dashboard.card">
          <div className="dash-chart">
            {rows === undefined ? <p className="empty">Loading the view…</p> : <RowsChart rows={rows} relative={view.relative} />}
          </div>
        </section>
      </div>
    </>
  );
}

/**
 * The main area of the tab `id` set back to where it was left as its view is drawn, the view
 * growing to it, until the person scrolls; where it is scrolled to kept with the tab, a moment
 * after a scroll and as the tab leaves the screen.
 */
function useKeptScroll(id: string): RefObject<HTMLDivElement | null> {
  const main = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = main.current!;
    let owed = scrollOf(id);
    let set = -1;
    let last = owed;
    const restore = () => {
      if (owed === 0) return;
      element.scrollTop = owed;
      set = element.scrollTop;
      if (set === owed) owed = 0;
    };
    restore();
    const growing = new ResizeObserver(restore);
    for (const child of element.children) growing.observe(child);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onScroll = () => {
      if (element.scrollTop !== set) owed = 0;
      last = element.scrollTop;
      clearTimeout(timer);
      timer = setTimeout(() => keepScroll(id, last), 200);
    };
    element.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      growing.disconnect();
      element.removeEventListener('scroll', onScroll);
      clearTimeout(timer);
      keepScroll(id, last);
    };
  }, [id]);
  return main;
}

/** A tab out of sight: its view's answers held, never read, so that they stay for as long as the tab. */
function KeptView({ now }: { now: string }) {
  const queryClient = useQueryClient();
  const address = useQuery({ ...addressQuery(queryClient, now), enabled: false });
  const key = address.data === undefined ? null : withoutLook(readState(stateOf(address.data.address)));
  useQuery({ ...rowsQuery(key ?? ''), enabled: false });
  return null;
}
