/**
 * The conditions that hold all work, which the gold bar shows (F125; UC *The gold bar*), as GET
 * /api/conditions reads them. The server's `conditions_changed` carries the same body at each
 * turn and is written over the read, and each time the stream comes up they are read again, which
 * covers a turn missed while it was down (design 2 §6.2). Nothing waits for the stream (SSE-4).
 */

import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useSseContext } from '@/contexts/sse-context';
import { useGetConditions } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

type Conditions = components['schemas']['ConditionsSchema.6c014b4'];
type Condition = Conditions['conditions'][number];

/** The server's event, `{"conditions": [{"code": …, "since": …}]}`. */
const EVENT = 'conditions_changed';
const KEY = ['getConditions', undefined];

export function useConditions(): Condition[] {
  const queryClient = useQueryClient();
  const { isConnected, addEventListener } = useSseContext();
  const query = useGetConditions();
  useUiStateInstrumentation('shell.conditions', { isLoading: query.isLoading, error: query.error });

  useEffect(
    () =>
      addEventListener(EVENT, (data) => {
        // A read under way may have been answered before the turn: it is dropped, and the turn
        // written once it is (a cancelled read puts back what it found when it began).
        void queryClient.cancelQueries({ queryKey: KEY, exact: true }).then(() => queryClient.setQueryData(KEY, data as Conditions));
      }),
    [addEventListener, queryClient],
  );

  useEffect(() => {
    if (isConnected) void queryClient.invalidateQueries({ queryKey: KEY, exact: true });
  }, [isConnected, queryClient]);

  return query.data?.conditions ?? [];
}
