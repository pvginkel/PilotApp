/**
 * One Session's stream: opens it at the start, applies its frames, and after a drop reopens it
 * after the last record held (§3), so nothing is missed and nothing doubled. A new transport
 * reopens it the same way.
 */

import { useEffect, useReducer, useRef } from 'react';
import type { ChatTransport } from '@/lib/chat/transport';
import { initialStreamState, streamReducer, type ChatStreamState } from '@/lib/chat/stream-state';

const RECONNECT_MS = 1500;

export function useChatStream(transport: ChatTransport, chatId: string): ChatStreamState {
  const [state, dispatch] = useReducer(streamReducer, initialStreamState);
  const lastSeq = useRef(0);

  useEffect(() => {
    let disposed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let sub: { close: () => void } | null = null;

    const connect = () => {
      dispatch({ type: 'connecting' });
      sub = transport.openStream(chatId, lastSeq.current, {
        onFrame: (frame) => {
          if (frame.type === 'record') lastSeq.current = Math.max(lastSeq.current, frame.record.seq);
          dispatch({ type: 'frame', frame, now: performance.now() });
        },
        onDrop: () => {
          dispatch({ type: 'dropped' });
          if (!disposed) retry = setTimeout(connect, RECONNECT_MS);
        },
      });
    };
    connect();

    return () => {
      disposed = true;
      clearTimeout(retry);
      sub?.close();
    };
  }, [transport, chatId]);

  return state;
}
