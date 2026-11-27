/**
 * By's counts (F163.2, F154.6): each dimension's count of values in the view's scope, asked as By's
 * panel opens, a task whose events come over the stream: each progress update carries one fact's
 * counts, shown as they arrive, and the result all of them. They are kept for the scope they count,
 * the view's time, drill, chips and quick filters, under `FIGURES` and by no query's read
 * (`byCountsKey`): an opening in a scope counted already asks nothing, and the walk's event leaves
 * them stale, asking nothing while the panel is open, so that the next opening asks them again; the
 * counts held stay drawn until the new arrive. A count that fails stands in the banner with its
 * Retry while the panel is open.
 */

import { useCallback, useContext, useEffect, useId, useMemo, useState } from 'react';
import { skipToken, useQuery, useQueryClient } from '@tanstack/react-query';
import { ReadFailures } from '@/hooks/use-dashboard-view';
import { useSSETask } from '@/hooks/use-sse-task';
import { toApiError } from '@/lib/api/api-error';
import { api } from '@/lib/api/client';
import { byCountsKey } from '@/lib/dashboard/queries';
import { withoutLook, type ViewState } from '@/lib/dashboard/state';

/** The counts kept for a scope, and whether the task that counted them ended. */
interface Counted {
  counts: Readonly<Record<string, number>>;
  done: boolean;
}

/** A progress update's data and the task's result (`backend/app/schemas/dashboard.py`, `AttributeCountsSchema`). */
interface CountsAnswer {
  counts: { dimension: string; count: number }[];
}

/** What a view's By counts are counted in. */
const scopeOf = (state: ViewState) => JSON.stringify([state.time, state.levels, state.chips, state.quickFilters]);

/** By's counts of the view `state`, those come so far, by dimension. */
export function useByCounts(state: ViewState): ReadonlyMap<string, number> {
  const queryClient = useQueryClient();
  const stand = useContext(ReadFailures)!;
  const reader = useId();
  const scope = scopeOf(state);
  const written = withoutLook(state);
  const held = useQuery<Counted>({ queryKey: byCountsKey(scope), queryFn: skipToken, enabled: false }).data;
  // Raised by the banner's Retry, which asks again whatever is held.
  const [asked, setAsked] = useState(0);

  const take = useCallback(
    (answer: unknown, done: boolean) => {
      const key = byCountsKey(scope);
      // A walk's event while the task ran leaves what it counted stale.
      const stale = queryClient.getQueryState(key)?.isInvalidated === true;
      const counts = Object.fromEntries(((answer as CountsAnswer | null)?.counts ?? []).map((each) => [each.dimension, each.count]));
      queryClient.setQueryData<Counted>(key, (was) => ({ counts: { ...was?.counts, ...counts }, done }));
      if (stale) void queryClient.invalidateQueries({ queryKey: key, exact: true, refetchType: 'none' });
    },
    [queryClient, scope],
  );
  const fail = useCallback(
    // eslint-disable-next-line no-restricted-properties -- a real timestamp: when the count failed, set against the banner's other failures
    (error: Error) => stand(reader, { error, at: Date.now(), retry: () => setAsked((times) => times + 1) }),
    [stand, reader],
  );
  // Each kept as it is, so that the task's subscription and the effect asking it stand as they are.
  const onProgress = useCallback((_message: string, _percentage?: number, data?: Record<string, unknown> | null) => take(data, false), [take]);
  const onResult = useCallback((data: unknown) => take(data, true), [take]);
  const onError = useCallback((message: string) => fail(new Error(message)), [fail]);
  const { subscribeToTask } = useSSETask({ onProgress, onResult, onError });

  useEffect(() => {
    const key = byCountsKey(scope);
    const kept = queryClient.getQueryState<Counted>(key);
    if (asked === 0 && kept?.data?.done === true && !kept.isInvalidated) return;
    stand(reader, null);
    queryClient.setQueryData<Counted>(key, (was) => ({ counts: was?.counts ?? {}, done: false }));
    const controller = new AbortController();
    void (async () => {
      const { data, error, response } = await api.POST('/api/dashboard/counts/attributes', { params: { query: { state: written } }, signal: controller.signal });
      if (error !== undefined) throw toApiError(error, response.status);
      subscribeToTask(data.task_id);
    })().catch((error: Error) => {
      if (!controller.signal.aborted) fail(error);
    });
    return () => controller.abort();
  }, [queryClient, stand, reader, scope, written, asked, subscribeToTask, fail]);
  useEffect(() => () => stand(reader, null), [stand, reader]);

  return useMemo(() => new Map(Object.entries(held?.counts ?? {})), [held]);
}
