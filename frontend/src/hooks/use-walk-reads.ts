/**
 * The dashboard kept current (F160.6): the collector's walk ends with `collection_changed` where it
 * published something (`backend/app/services/walk_service.py`), and every query of the record's
 * figures (`FIGURES`) is then stale. Those the screen shows are read again in place, their answers
 * drawn until the new arrive, whichever screen is in view; the rest are read once a screen shows
 * them again. A page that is hidden reads nothing until it shows. A read under way when the event
 * comes may have been answered before the walk's rows: it lands, and is read again then, so that
 * walks closer together than a read takes never keep one from landing. A figure that has never
 * been answered, its read refused, waits for its Retry.
 *
 * An event reaches only the browsers whose stream the sending process holds, so each time the
 * stream comes back up the figures are read again as on the event; its first coming up is none. A
 * read whose answer comes over the stream (`OVER_STREAM`), a task's, and is under way as it comes
 * up, the first time included, is asked again at once, since an answer sent while no stream stood
 * never lands.
 */

import { useEffect, useRef } from 'react';
import { useQueryClient, type Query } from '@tanstack/react-query';
import { useSseContext } from '@/contexts/sse-context';
import { FIGURES, OVER_STREAM } from '@/lib/dashboard/queries';

/** The server's event, `{"as_of": <the walk's end>}`. */
const EVENT = 'collection_changed';

const hidden = () => document.visibilityState === 'hidden';

export function useWalkReads(): void {
  const queryClient = useQueryClient();
  const { isConnected, addEventListener } = useSseContext();
  const readAll = useRef<(lost?: boolean) => void>(() => undefined);
  const askLost = useRef<() => void>(() => undefined);

  useEffect(() => {
    const cache = queryClient.getQueryCache();
    const owed = new Set<Query>();
    const stale = (query: Query) => queryClient.invalidateQueries({ queryKey: query.queryKey, exact: true, refetchType: hidden() ? 'none' : 'active' });
    const overStream = (query: Query) => query.state.fetchStatus !== 'idle' && query.meta?.[OVER_STREAM] === true;
    const askAgain = (query: Query) => {
      owed.delete(query);
      void queryClient.cancelQueries({ queryKey: query.queryKey, exact: true }).then(() => stale(query));
    };
    const readOne = (query: Query, lost = false) => {
      if (query.state.fetchStatus !== 'idle') {
        if (lost && overStream(query)) askAgain(query);
        else owed.add(query);
        return;
      }
      if (query.state.data === undefined) return;
      void stale(query);
    };
    readAll.current = (lost = false) => cache.findAll({ queryKey: [FIGURES] }).forEach((query) => readOne(query, lost));
    askLost.current = () => cache.findAll({ queryKey: [FIGURES], predicate: overStream }).forEach(askAgain);
    const unwatch = cache.subscribe((event) => {
      if (event.type === 'removed') owed.delete(event.query);
      if (event.type !== 'updated' || event.query.state.fetchStatus !== 'idle' || !owed.delete(event.query)) return;
      const { query } = event;
      queueMicrotask(() => readOne(query));
    });
    const shown = () => {
      if (!hidden()) void queryClient.refetchQueries({ queryKey: [FIGURES], type: 'active', stale: true }, { cancelRefetch: false });
    };
    document.addEventListener('visibilitychange', shown);
    const unsubscribe = addEventListener(EVENT, () => readAll.current());
    return () => {
      unsubscribe();
      unwatch();
      document.removeEventListener('visibilitychange', shown);
      owed.clear();
    };
  }, [addEventListener, queryClient]);

  // Whether the stream stood at its last change, and whether it has stood since the dashboard mounted.
  const standing = useRef(isConnected);
  const stood = useRef(isConnected);
  useEffect(() => {
    const cameUp = isConnected && !standing.current;
    standing.current = isConnected;
    if (!cameUp) return;
    if (stood.current) readAll.current(true);
    else askLost.current();
    stood.current = true;
  }, [isConnected]);
}
