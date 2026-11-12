import type { QueryClient, QueryKey } from '@tanstack/react-query';

/**
 * Writes `patch` over a query's data as read, a live event's or a write's answer, and leaves the
 * query as stale as it found it. `setQueryData` takes what it writes for a fresh read: it drops the
 * mark an event such as `project_changed` left on a query no screen shows, and restamps its time,
 * so that under the query client's `staleTime` the screen that shows it again would read nothing
 * and show the cache from before the change. A query marked before the patch is marked again after
 * it, with no read: the screen that shows it next reads it.
 */
export function patchQueryData<T>(queryClient: QueryClient, queryKey: QueryKey, patch: (data: T | undefined) => T | undefined): void {
  const marked = queryClient.getQueryState(queryKey)?.isInvalidated === true;
  queryClient.setQueryData<T>(queryKey, patch);
  if (marked) void queryClient.invalidateQueries({ queryKey, exact: true, refetchType: 'none' });
}
