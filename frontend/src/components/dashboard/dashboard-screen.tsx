/**
 * The dashboard's screen (F160), a module of its own, which the shell loads at the dashboard's
 * first opening (F160.2): a page that never opens it never loads it. Out of sight it lies under
 * the Projects screen, in its box, out of the flow, its visibility off and inert, and what lies
 * under it is out of view (`ScreenInView`); it keeps its scroll and its answers, and reads again
 * on the walk's event whichever screen shows (`use-walk-reads.ts`).
 *
 * Top to bottom (the mockup's `frame.js`): the global toolbar, the view's tab at its left; the
 * banner, what failed; the main area, which scrolls, holding the view's card. The view is the
 * state the address names (`address.ts`), read off the hash as the browser holds it; an address
 * that names none, `#dash`, finds the view as it was left.
 */

import { useState } from 'react';
import { useRouterState } from '@tanstack/react-router';
import { ChartBar, RefreshCw, X } from 'lucide-react';
import { useDashboardView, type DashboardView, type Failure } from '@/hooks/use-dashboard-view';
import { ScreenInView } from '@/hooks/use-screens';
import { useWalkReads } from '@/hooks/use-walk-reads';
import { placeOf } from '@/lib/dashboard/address';
import { hashOf } from '@/lib/screens';
import { RowsChart } from './rows-chart';
import './dashboard.css';

export function DashboardScreen({ shown }: { shown: boolean }) {
  useWalkReads();
  const href = useRouterState({ select: (state) => state.location.href });
  // The state the address names while the dashboard shows; out of sight it keeps the one it had.
  const named = shown ? placeOf(hashOf(href)).state : null;
  const [written, setWritten] = useState<string | null>(null);
  if (named !== null && named !== written) setWritten(named);
  const view = useDashboardView(written);
  return (
    <ScreenInView value={shown}>
      <section className={shown ? 'dash' : 'dash away'} inert={!shown} aria-label="Dashboard" data-testid="dashboard">
        {written !== null && <View view={view} />}
      </section>
    </ScreenInView>
  );
}

function View({ view }: { view: DashboardView }) {
  const { rows } = view;
  return (
    <>
      <div className="dash-bar" role="toolbar" aria-label="Dashboard" data-testid="dashboard.toolbar">
        <span className="dash-onetab" title={rows?.by.label} data-testid="dashboard.tab">
          <ChartBar className="icon" aria-hidden="true" />
          <span className="t">{rows?.by.label}</span>
        </span>
      </div>
      {view.failure !== null && <Banner failure={view.failure} />}
      <div className="dash-main" data-testid="dashboard.main">
        <section className={view.changing ? 'dash-card changing' : 'dash-card'} aria-label="View" aria-busy={view.changing} data-testid="dashboard.card">
          <div className="dash-chart">
            {rows === undefined ? <p className="empty">Loading the view…</p> : <RowsChart rows={rows} relative={view.relative} />}
          </div>
        </section>
      </div>
    </>
  );
}

/** What failed, under the toolbar until it is closed or a read of its own goes well: its reason, and Retry. */
function Banner({ failure }: { failure: Failure }) {
  const [closed, setClosed] = useState<number | null>(null);
  if (closed === failure.at) return null;
  return (
    <div className="dash-banner" role="status" data-testid="dashboard.banner">
      <div className="text" data-testid="dashboard.banner.text">
        {failure.error.message}
      </div>
      <button
        type="button"
        className="btn btn-sm"
        onClick={() => {
          setClosed(failure.at);
          failure.retry();
        }}
        data-testid="dashboard.banner.retry"
      >
        <RefreshCw className="icon" aria-hidden="true" /> Retry
      </button>
      <button type="button" className="btn btn-ghost btn-sm btn-icon" title="Close" aria-label="Close" onClick={() => setClosed(failure.at)} data-testid="dashboard.banner.close">
        <X className="icon" aria-hidden="true" />
      </button>
    </div>
  );
}
