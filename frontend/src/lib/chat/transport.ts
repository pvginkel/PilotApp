/**
 * What the chat needs from the server, as one interface, and its adapter on PilotApp's API
 * (docs/sessions.md, "The stream"): a Session's records by REST, and its live frames as the SSE
 * event `session` on the browser's one connection.
 *
 * A stream subscribes its view first, then reads the records after its offset by page: what was
 * written after the subscribe comes live, what came before it reads, and a record it gets both
 * ways is the same `seq`, which the reducer drops. The live frames that come during the read wait
 * for its end, after `caught-up`; a partial among them that came before a record the read gave is
 * stale, and dropped. With no connection the stream reads its records and nothing comes live. A
 * read or a subscribe that fails, a refused subscribe included (`409`, this process holding no
 * connection under the request id), drops the stream, which the client reopens.
 */

import type { SseContextValue } from '@/contexts/sse-context-base';
import { api } from '@/lib/api/generated/client';
import { makeUniqueToken } from '@/lib/utils/random';
import type { StreamEventLine } from './claude-lines';
import type { ChatFrame, ChatRecord } from './records';

interface ChatStreamHandlers {
  onFrame: (frame: ChatFrame) => void;
  /** The stream dropped: the client reopens it after the last record it holds. */
  onDrop: () => void;
}

interface ChatSubscription {
  close: () => void;
}

export interface ChatTransport {
  /** Streams a Session's records after `afterSeq` (0: all of them), then what is written live. */
  openStream: (sessionId: string, afterSeq: number, handlers: ChatStreamHandlers) => ChatSubscription;
}

/** The SSE event a Session's frames travel as. */
const EVENT = 'session';

/** The most records a page of the read holds. */
const PAGE = 200;

type SessionEvent =
  | { session: string; frame: 'record'; data: ChatRecord }
  | { session: string; frame: 'partial'; data: StreamEventLine }
  | { session: string; frame: 'end' };

const frameOf = (event: SessionEvent): ChatFrame => {
  switch (event.frame) {
    case 'record':
      return { type: 'record', record: event.data };
    case 'partial':
      return { type: 'partial', line: event.data };
    case 'end':
      return { type: 'end' };
  }
};

/** The frames that came live during the read, less the partials that came before a record it gave. */
function fresh(frames: ChatFrame[], lastRead: number): ChatFrame[] {
  let stale = -1;
  frames.forEach((frame, index) => {
    if (frame.type === 'record' && frame.record.seq <= lastRead) stale = index;
  });
  return frames.filter((frame, index) => frame.type !== 'partial' || index > stale);
}

/** `requestId`: the browser's SSE connection, none while it is down. */
export function sessionTransport(requestId: string | null, addEventListener: SseContextValue['addEventListener']): ChatTransport {
  return {
    openStream(sessionId, afterSeq, { onFrame, onDrop }) {
      const path = { session_id: sessionId };
      const view = { request_id: requestId ?? '', view: makeUniqueToken(16) };
      let closed = false;
      let subscribed = false;
      let waiting: ChatFrame[] | null = [];
      const unlisten =
        requestId === null
          ? () => {}
          : addEventListener(EVENT, (data) => {
              const event = data as SessionEvent;
              if (closed || event.session !== sessionId) return;
              const frame = frameOf(event);
              if (waiting === null) onFrame(frame);
              else waiting.push(frame);
            });

      // A view the DELETE misses goes with its connection.
      const unsubscribe = () => void api.DELETE('/api/sessions/{session_id}/stream', { params: { path }, body: view }).catch(() => {});
      const close = () => {
        closed = true;
        unlisten();
        if (subscribed) unsubscribe();
      };

      const run = async () => {
        if (requestId !== null) {
          const { response } = await api.POST('/api/sessions/{session_id}/stream', { params: { path }, body: view });
          if (!response.ok) throw new Error(`The session stream refused the view: ${response.status}`);
          if (closed) {
            unsubscribe();
            return;
          }
          subscribed = true;
        }
        let after = afterSeq;
        let ended = false;
        for (;;) {
          const { data, error } = await api.GET('/api/sessions/{session_id}/records', {
            params: { path, query: { after, limit: PAGE } },
          });
          if (closed) return;
          if (data === undefined) throw new Error(`The session's records did not load: ${JSON.stringify(error)}`);
          const records = data.records as ChatRecord[];
          for (const record of records) onFrame({ type: 'record', record });
          after = records.at(-1)?.seq ?? after;
          if (records.length < PAGE) {
            ended = data.ended;
            break;
          }
        }
        onFrame({ type: 'caught-up' });
        if (ended) onFrame({ type: 'end' });
        const live = fresh(waiting ?? [], after);
        waiting = null;
        for (const frame of live) onFrame(frame);
      };

      run().catch(() => {
        if (closed) return;
        close();
        onDrop();
      });
      return { close };
    },
  };
}
