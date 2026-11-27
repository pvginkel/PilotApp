/**
 * What failed (F160.8), under the global toolbar until it is closed or a read of its own goes well:
 * the latest failure of those given, its reason and a read's Retry; a write's has none, and its
 * close is the screen's (`onClose`), so that a tab drawn again does not show it again.
 */

import { useState } from 'react';
import { RefreshCw, X } from 'lucide-react';
import type { Failure } from '@/hooks/use-dashboard-view';

/** A failure apart from the view's own reads, a write's or a read's of its scope, which the banner shows beside theirs, and its close. */
export interface Wrote {
  failure: Failure | null;
  close: () => void;
}

export function Banner({ failures, onClose }: { failures: readonly (Failure | null)[]; onClose: (failure: Failure) => void }) {
  const [closed, setClosed] = useState<number | null>(null);
  const failure = failures.reduce<Failure | null>((latest, each) => (each !== null && (latest === null || each.at > latest.at) ? each : latest), null);
  if (failure === null || closed === failure.at) return null;
  const { retry } = failure;
  return (
    <div className="dash-banner" role="status" data-testid="dashboard.banner">
      <div className="text" data-testid="dashboard.banner.text">
        {failure.error.message}
      </div>
      {retry !== undefined && (
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => {
            setClosed(failure.at);
            retry();
          }}
          data-testid="dashboard.banner.retry"
        >
          <RefreshCw className="icon" aria-hidden="true" /> Retry
        </button>
      )}
      <button
        type="button"
        className="btn btn-ghost btn-sm btn-icon"
        title="Close"
        aria-label="Close"
        onClick={() => {
          setClosed(failure.at);
          onClose(failure);
        }}
        data-testid="dashboard.banner.close"
      >
        <X className="icon" aria-hidden="true" />
      </button>
    </div>
  );
}
