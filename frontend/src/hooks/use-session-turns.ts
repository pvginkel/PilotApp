/**
 * A Session's Turns, what each was sent and by whom, GET /api/sessions/<id>/turns: the server's own
 * included, which no record carries (F69). It is read again once the Session's records name a Turn
 * the last read did not hold, such as a Resume's or a continuation's; a record names its Turn only
 * once the Turn is stored, so that read holds it.
 */

import { useEffect, useMemo } from 'react';
import { useGetSessionsTurnsBySessionId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import type { ChatRecord } from '@/lib/chat/records';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

export type SessionTurn = components['schemas']['SessionTurnsSchema.01118bb.SessionTurnSchema'];

export function useSessionTurns(sessionId: string, records: readonly ChatRecord[]): SessionTurn[] | undefined {
  const named = useMemo(() => records.reduce((top, record) => Math.max(top, record.turn ?? 0), 0), [records]);
  const { data, error, isFetching, refetch } = useGetSessionsTurnsBySessionId({ path: { session_id: sessionId } });
  const held = data?.turns.at(-1)?.turn ?? 0;
  useEffect(() => {
    if (data !== undefined && !isFetching && named > held) void refetch();
  }, [data, isFetching, named, held, refetch]);
  useUiStateInstrumentation('session-log.turns', {
    isLoading: isFetching,
    error,
    getReadyMetadata: () => ({ turns: held }),
  });
  return data?.turns;
}
