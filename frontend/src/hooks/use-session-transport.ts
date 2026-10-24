/**
 * The chat's transport on the browser's SSE connection (lib/chat/transport.ts): a new one each
 * time the connection comes up or goes, so that a stream opened on it reopens on the next.
 */

import { useMemo } from 'react';
import { useSseContext } from '@/contexts/sse-context';
import { sessionTransport, type ChatTransport } from '@/lib/chat/transport';

export function useSessionTransport(): ChatTransport {
  const { isConnected, requestId, addEventListener } = useSseContext();
  const connection = isConnected ? requestId : null;
  return useMemo(() => sessionTransport(connection, addEventListener), [connection, addEventListener]);
}
