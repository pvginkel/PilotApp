/**
 * A Session's Turns, what each was sent and by whom, GET /api/sessions/<id>/turns: the server's own
 * included, which no record carries (F69). It is read again once the Session's records name a Turn
 * the last read did not hold, such as a Resume's or a continuation's; a record names its Turn only
 * once the Turn is stored, so that read holds it. A Turn the gate holds, a Resume's, a
 * continuation's or a nudge's, is stored with the move to `held` and has no record until it is
 * sent: the Turns are read again at each move of the Session's state, whose event follows that
 * commit, and whenever the log is opened, whatever a read before it left in the cache.
 */

import { useEffect, useMemo, useRef } from 'react';
import { useGetSessionsTurnsBySessionId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import type { ChatRecord } from '@/lib/chat/records';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

export type SessionTurn = components['schemas']['SessionTurnsSchema.01118bb.SessionTurnSchema'];
type SessionState = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema']['state'];

export function useSessionTurns(sessionId: string, records: readonly ChatRecord[], state: SessionState): SessionTurn[] | undefined {
  const named = useMemo(() => records.reduce((top, record) => Math.max(top, record.turn ?? 0), 0), [records]);
  const { data, error, isFetching, refetch } = useGetSessionsTurnsBySessionId({ path: { session_id: sessionId } }, { refetchOnMount: 'always' });
  const readUnder = useRef(state);
  useEffect(() => {
    if (readUnder.current === state) return;
    readUnder.current = state;
    // A read under way was asked for before the move: this one takes its place.
    void refetch();
  }, [state, refetch]);
  const held = data?.turns.at(-1)?.turn ?? 0;
  // The newest Turn a re-read was asked for: a re-read that failed is not asked again until a
  // newer Turn is named, so that a failing read does not loop.
  const asked = useRef(0);
  useEffect(() => {
    if (data === undefined || isFetching || named <= held) return;
    if (error !== null && named <= asked.current) return;
    asked.current = named;
    void refetch();
  }, [data, error, isFetching, named, held, refetch]);
  useUiStateInstrumentation('session-log.turns', {
    isLoading: isFetching,
    error,
    getReadyMetadata: () => ({ turns: held }),
  });
  return data?.turns;
}
