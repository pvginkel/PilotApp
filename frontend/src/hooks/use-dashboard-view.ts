/**
 * One view of the dashboard as it is read (F160.6, F160.8): the state an address carries, read
 * through the server's normal form (`addressQuery`), then its rows, keyed by the state without its
 * look-only parts (`rowsQuery`). While a new state's answer is on its way the last answer stays
 * drawn, and where a read fails it stays drawn too, the failure beside it with its Retry. The
 * presentation the state names is drawn as rows: the rows route answers a By's rows whatever the
 * presentation, and the others are drawn by the presentations' own slices.
 */

import { useState } from 'react';
import { keepPreviousData, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import { addressQuery, rowsQuery, stateOf } from '@/lib/dashboard/queries';
import type { Rows } from '@/lib/dashboard/rows-layout';
import { readState, withoutLook, type ViewState } from '@/lib/dashboard/state';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

/** What failed: what it said, when, and a read's Retry; a write has none. */
export interface Failure {
  error: Error;
  at: number;
  retry?: () => void;
}

/** A read's failure, with its Retry; none where it has not failed. */
export function failureOf(query: UseQueryResult<unknown>): Failure | null {
  return query.isError ? { error: query.error, at: query.errorUpdatedAt, retry: () => void query.refetch() } : null;
}

interface DashboardView {
  /** The state in its normal form, the last the server wrote back; none before the first. */
  state: ViewState | null;
  /** The answer drawn: the state's, else the last one drawn; none before the first. */
  rows: Rows | undefined;
  /** Whether Relative reads the figures drawn (`rel=1`), a look-only part. */
  relative: boolean;
  /** An answer for another state is on its way. */
  changing: boolean;
  failure: Failure | null;
}

/** The view `written` names, a state as an address carries it; none for no state. */
export function useDashboardView(written: string | null): DashboardView {
  const queryClient = useQueryClient();
  const address = useQuery({ ...addressQuery(queryClient, written ?? ''), enabled: written !== null });
  useUiStateInstrumentation('dashboard.address', { isLoading: address.isFetching, error: address.error });
  // The last state the server wrote back: a text it refuses leaves the view at the one before.
  const [normal, setNormal] = useState<string | null>(null);
  const read = address.data === undefined ? null : stateOf(address.data.address);
  if (read !== null && read !== normal) setNormal(read);
  const state = normal === null ? null : readState(normal);
  const key = state === null ? null : withoutLook(state);

  const rows = useQuery({ ...rowsQuery(key ?? ''), enabled: key !== null, placeholderData: keepPreviousData });
  useUiStateInstrumentation('dashboard.rows', {
    isLoading: rows.isFetching,
    error: rows.error,
    getReadyMetadata: () => ({ key }),
    getErrorMetadata: () => ({ key }),
  });
  const [drawn, setDrawn] = useState<Rows | undefined>(undefined);
  if (rows.data !== undefined && rows.data !== drawn) setDrawn(rows.data);

  return {
    state,
    rows: drawn,
    relative: state?.relative ?? false,
    changing: rows.isPlaceholderData || (written !== null && address.isPending),
    failure: failureOf(address) ?? failureOf(rows),
  };
}
