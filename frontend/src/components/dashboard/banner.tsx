/**
 * What failed (F160.8), under the global toolbar until it is closed or a read of its own goes well:
 * the latest failure of those given that is not closed, its reason and a read's Retry, which asks
 * again every read of those given that failed; a write's has none, and its close is the screen's
 * (`onClose`), so that a tab drawn again does not show it again.
 */

import { useState } from 'react';
import { RefreshCw, X } from 'lucide-react';
import type { Failure } from '@/hooks/use-dashboard-view';

/** A write's failure, which the banner shows beside a read's, and its close. */
export interface Wrote {
  failure: Failure | null;
  close: () => void;
}

export function Banner({ failures, onClose }: { failures: readonly (Failure | null)[]; onClose: (failure: Failure) => void }) {
  // A read that fails again is a failure of its own, its error another.
  const [closed, setClosed] = useState<readonly Error[]>([]);
  const given = failures.filter((each) => each !== null);
  const failure = given.reduce<Failure | null>((latest, each) => (!closed.includes(each.error) && (latest === null || each.at > latest.at) ? each : latest), null);
  if (failure === null) return null;
  return (
    <div className="dash-banner" role="status" data-testid="dashboard.banner">
      <div className="text" data-testid="dashboard.banner.text">
        {failure.error.message}
      </div>
      {failure.retry !== undefined && (
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => {
            setClosed([...closed, ...given.filter((each) => each.retry !== undefined).map((each) => each.error)]);
            for (const each of given) each.retry?.();
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
          setClosed([...closed, failure.error]);
          onClose(failure);
        }}
        data-testid="dashboard.banner.close"
      >
        <X className="icon" aria-hidden="true" />
      </button>
    </div>
  );
}
