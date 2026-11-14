import { useState, useEffect, useCallback, useRef } from 'react';
import type { ReactNode } from 'react';
import { api } from '@/lib/api/generated/client';
import { isTestMode } from '@/lib/config/test-mode';
import { emitTestEvent } from '@/lib/test/event-emitter';
import type { SseTestEvent } from '@/lib/test/test-events';
import { makeUniqueToken } from '@/lib/utils/random';
import { SseContext } from './sse-context-base';
import type { SseContextValue } from './sse-context-base';
// Import to ensure test bridge registration (even though module is not used in production)
import '@/lib/config/sse-request-id';

interface SseContextProviderProps {
  children: ReactNode;
}

// The longest wait before a stream that failed is opened again.
const MAX_RETRY_MS = 5000;

// The stream counts as gone after this many of its heartbeat's cadences with
// no frame.
const SILENT_BEATS = 2;

// Worker message types; they mirror the union in `src/workers/sse-worker.ts`.
type WorkerMessage =
  | { type: 'connected'; requestId: string; __testEvent?: SseTestEventMetadata }
  | { type: 'event'; event: string; data: unknown; __testEvent?: SseTestEventMetadata }
  | { type: 'disconnected'; reason?: string; __testEvent?: SseTestEventMetadata }
  | { type: 'error'; error: string; __testEvent?: SseTestEventMetadata }
  | { type: 'rejected'; status: number; message: string; __testEvent?: SseTestEventMetadata };

interface SseTestEventMetadata {
  kind: 'sse';
  streamId: string;
  phase: 'open' | 'message' | 'error' | 'close';
  event: string;
  data?: unknown;
}

type SessionProbeOutcome = 'valid' | 'signed-out' | 'failed';

/**
 * Check the session after the backend refused the stream. GET /api/auth/self
 * refreshes the session cookies while the refresh token is good, so `valid`
 * means a new stream will be accepted. On `signed-out` (401) the API client's
 * middleware is already sending the user to login.
 */
async function probeSession(): Promise<SessionProbeOutcome> {
  try {
    const { response } = await api.GET('/api/auth/self', {
      credentials: 'include',
    });
    if (response.ok) {
      return 'valid';
    }
    return response.status === 401 ? 'signed-out' : 'failed';
  } catch (error) {
    console.error('SSE recovery: /api/auth/self failed:', error);
    return 'failed';
  }
}

/**
 * Read the backend's `rejected` payload, `{"status": <code>, "message": "<text>"}`.
 * A payload that doesn't parse gives status 0.
 */
function parseRejection(data: unknown): { status: number; message: string } {
  try {
    const payload = JSON.parse(String(data)) as { status?: unknown; message?: unknown };
    return {
      status: typeof payload?.status === 'number' ? payload.status : 0,
      message: typeof payload?.message === 'string' ? payload.message : 'Unknown',
    };
  } catch {
    return { status: 0, message: 'Unknown' };
  }
}

/**
 * The cadence a `ready` event's data names, `{"heartbeat": <seconds>}`, in
 * milliseconds, or null where it names none.
 */
function heartbeatOf(data: unknown): number | null {
  try {
    const { heartbeat } = JSON.parse(String(data)) as { heartbeat?: unknown };
    return typeof heartbeat === 'number' && heartbeat > 0 ? heartbeat * 1000 : null;
  } catch {
    return null;
  }
}

/**
 * Determine if SharedWorker should be used based on environment
 */
function shouldUseSharedWorker(): boolean {
  // Always use direct connection in development mode
  if (import.meta.env.DEV) {
    return false;
  }

  // In test mode, only use SharedWorker if explicitly enabled via URL parameter
  if (isTestMode()) {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      return params.has('__sharedWorker');
    }
    return false;
  }

  // Check if SharedWorker is supported (graceful fallback for iOS Safari)
  if (typeof SharedWorker === 'undefined') {
    return false;
  }

  // Production mode with SharedWorker support
  return true;
}

// Decided once, when the module loads: in test mode the opt-in is the
// `__sharedWorker` query parameter of the URL the page loaded with, and a route
// that redirects on load (an index route, say) drops it before the provider
// mounts.
const USE_SHARED_WORKER = shouldUseSharedWorker();

/**
 * SSE context provider that manages a unified SSE connection.
 *
 * Exposes a generic addEventListener interface. Consumer hooks subscribe to
 * named SSE events and handle their own DTO parsing.
 *
 * The backend sends all domain events as unnamed data-only messages with a
 * {type, payload} envelope. Both the SharedWorker and the direct EventSource
 * path unwrap the envelope and dispatch to local listeners by event name.
 *
 * Three control signals are named events. `ready` means the backend accepted
 * the stream, its data the heartbeat's cadence; only then is the connection
 * `isConnected`, since a refused stream opens too. `heartbeat` comes after each
 * cadence the stream was idle: a stream silent for SILENT_BEATS cadences has
 * died without saying so, and is closed and opened again at once. `rejected`
 * means the backend refused it (401/403): both paths close the stream instead
 * of retrying it, check the session, and open a new stream once the session is
 * valid again, or, where the check failed, after a backoff.
 *
 * A stream that fails is opened again after a backoff that grows to at most
 * MAX_RETRY_MS, and at once when the browser comes back online; it is retried
 * for as long as it takes. `retrying` says that an attempt has failed since it
 * last stood. The page says the connection is down; nothing asks for a reload.
 *
 * Uses SharedWorker in production for cross-tab connection sharing, falls back to
 * direct EventSource in dev/test/iOS environments.
 */
export function SseContextProvider({ children }: SseContextProviderProps) {
  const [isConnected, setIsConnected] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [requestId, setRequestId] = useState<string | null>(null);
  // Whether the stream stands, for the callbacks: an error while it stands is
  // its drop, one while it does not a failed attempt.
  const connectedRef = useRef(false);
  const retryRef = useRef<{ count: number; timer: ReturnType<typeof setTimeout> | null }>({
    count: 0,
    timer: null,
  });
  // The direct path's silence: the cadence its stream's `ready` named, when it
  // last heard a frame, and the timer that looks again.
  const silenceRef = useRef<{ heartbeatMs: number | null; lastFrameAt: number; timer: ReturnType<typeof setTimeout> | null }>({
    heartbeatMs: null,
    lastFrameAt: 0,
    timer: null,
  });

  const eventSourceRef = useRef<EventSource | null>(null);
  const sharedWorkerRef = useRef<SharedWorker | null>(null);
  const useSharedWorker = useRef<boolean>(USE_SHARED_WORKER);
  // The direct path's recovery reopens through this ref, since
  // createDirectConnection can't refer to itself.
  const createDirectConnectionRef = useRef<(() => void) | null>(null);

  // Internal listener registry: Map<eventName, Set<handler>>
  const listenersRef = useRef(new Map<string, Set<(data: unknown) => void>>());

  const markConnected = useCallback((id: string) => {
    connectedRef.current = true;
    retryRef.current.count = 0;
    setIsConnected(true);
    setRetrying(false);
    setRequestId(id);
  }, []);

  /**
   * The stream is down: dropped where it stood, else an attempt to open it
   * failed.
   */
  const markDown = useCallback(() => {
    if (connectedRef.current) {
      connectedRef.current = false;
      setIsConnected(false);
    } else {
      setRetrying(true);
    }
  }, []);

  const clearRetry = useCallback(() => {
    if (retryRef.current.timer) {
      clearTimeout(retryRef.current.timer);
      retryRef.current.timer = null;
    }
  }, []);

  /** Run `open` after the backoff, which doubles from 1 s to MAX_RETRY_MS. */
  const scheduleRetry = useCallback((open: () => void) => {
    clearRetry();
    const retry = retryRef.current;
    retry.count++;
    const delay = Math.min(1000 * 2 ** (retry.count - 1), MAX_RETRY_MS);
    console.debug(`SSE: retrying in ${delay}ms (attempt ${retry.count})`);
    retry.timer = setTimeout(() => {
      retry.timer = null;
      open();
    }, delay);
  }, [clearRetry]);

  /**
   * Recover from a refused stream: check the session, then `reopen` when it is
   * valid, leave the redirect to login to the API client when it is gone, and
   * otherwise `reopen` after the backoff, which a refusal brings back here.
   */
  const recoverFromRejection = useCallback((status: number, reopen: () => void) => {
    // Only the status: the message comes from the backend's response.
    console.debug(`SSE stream rejected: status=${status}`);
    connectedRef.current = false;
    setIsConnected(false);

    void probeSession().then(outcome => {
      if (outcome === 'valid') {
        reopen();
      } else if (outcome === 'failed') {
        setRetrying(true);
        scheduleRetry(reopen);
      }
    });
  }, [scheduleRetry]);

  /**
   * Dispatch an event to all registered handlers for a given event name
   */
  const dispatchEvent = useCallback((eventName: string, data: unknown) => {
    const handlers = listenersRef.current.get(eventName);
    if (handlers) {
      for (const handler of handlers) {
        try {
          handler(data);
        } catch (error) {
          console.error(`Error in SSE event handler for '${eventName}':`, error);
        }
      }
    }
  }, []);

  /**
   * Register a handler for a named SSE event.
   * Purely local — no subscription commands are sent to the worker or EventSource.
   * Returns an unsubscribe function.
   */
  const addEventListener = useCallback(
    (event: string, handler: (data: unknown) => void): (() => void) => {
      const map = listenersRef.current;
      if (!map.has(event)) {
        map.set(event, new Set());
      }
      map.get(event)!.add(handler);

      return () => {
        const handlers = map.get(event);
        if (handlers) {
          handlers.delete(handler);
          if (handlers.size === 0) {
            map.delete(event);
          }
        }
      };
    },
    []
  );

  /**
   * Handle worker messages and dispatch to listeners
   */
  const handleWorkerMessage = useCallback((message: WorkerMessage) => {
    // Forward test events if present
    if (message.__testEvent && isTestMode()) {
      emitTestEvent(message.__testEvent);
    }

    switch (message.type) {
      case 'connected':
        markConnected(message.requestId);
        break;

      case 'event':
        dispatchEvent(message.event, message.data);
        break;

      case 'error':
        console.error('SSE connection error:', message.error);
        markDown();
        break;

      case 'disconnected':
        console.debug('SSE disconnected:', message.reason);
        connectedRef.current = false;
        setIsConnected(false);
        break;

      case 'rejected':
        // The worker has closed the stream and won't retry it until told to.
        // Post to the worker directly, not through reconnect(), so the
        // recovery doesn't depend on the isConnected guard or render timing.
        recoverFromRejection(message.status, () => {
          sharedWorkerRef.current?.port.postMessage({ type: 'reconnect' });
        });
        break;

      default:
        console.warn('Unknown worker message:', message);
    }
  }, [dispatchEvent, markConnected, markDown, recoverFromRejection]);

  /**
   * Create SharedWorker connection
   */
  const createSharedWorkerConnection = useCallback(() => {
    try {
      console.debug('SSE context: Using SharedWorker for unified SSE connection');

      const worker = new SharedWorker(
        new URL('../workers/sse-worker.ts', import.meta.url),
        { type: 'module' }
      );

      sharedWorkerRef.current = worker;

      worker.port.onmessage = (event: MessageEvent<WorkerMessage>) => {
        handleWorkerMessage(event.data);
      };

      worker.port.start();
      worker.port.postMessage({
        type: 'connect',
        isTestMode: isTestMode(),
      });
    } catch (error) {
      console.error('Failed to create SharedWorker, falling back to direct connection:', error);
      useSharedWorker.current = false;
      connectedRef.current = false;
      setIsConnected(false);
    }
  }, [handleWorkerMessage]);

  const stopSilenceWatch = useCallback(() => {
    const silence = silenceRef.current;
    if (silence.timer) {
      clearTimeout(silence.timer);
      silence.timer = null;
    }
    silence.heartbeatMs = null;
  }, []);

  /**
   * Create direct EventSource connection.
   * Uses onmessage to unwrap the {type, payload} envelope — same logic as the SharedWorker.
   */
  const createDirectConnection = useCallback(() => {
    clearRetry();
    stopSilenceWatch();
    const tabRequestId = makeUniqueToken(32);

    const params = new URLSearchParams({ request_id: tabRequestId });
    const url = `/api/sse/stream?${params}`;

    const eventSource = new EventSource(url);
    eventSourceRef.current = eventSource;
    const silence = silenceRef.current;

    const heard = () => {
      silence.lastFrameAt = performance.now();
    };

    // Once SILENT_BEATS cadences have passed with no frame, the stream died
    // without saying so: close it and open another at once.
    const watchSilence = () => {
      if (silence.heartbeatMs === null) {
        return;
      }
      const left = silence.lastFrameAt + silence.heartbeatMs * SILENT_BEATS - performance.now();
      if (left > 0) {
        silence.timer = setTimeout(watchSilence, left);
        return;
      }
      console.debug('SSE: stream silent, reconnecting');
      eventSource.close();
      markDown();
      if (isTestMode()) {
        emitTestEvent({ kind: 'sse', streamId: 'connection', phase: 'close', event: 'silent' });
      }
      createDirectConnectionRef.current?.();
    };

    // Open is not connected: the backend may still refuse the stream. The
    // connection counts from the `ready` event, whose data names the
    // heartbeat's cadence, from which on the stream is timed.
    eventSource.addEventListener('ready', (event) => {
      heard();
      silence.heartbeatMs = heartbeatOf((event as MessageEvent).data);
      watchSilence();
      markConnected(tabRequestId);

      if (isTestMode()) {
        const payload: Omit<SseTestEvent, 'timestamp'> = {
          kind: 'sse',
          streamId: 'connection',
          phase: 'open',
          event: 'connected',
          data: { requestId: tabRequestId },
        };
        emitTestEvent(payload);
      }
    });

    eventSource.addEventListener('heartbeat', () => {
      heard();
      if (isTestMode()) {
        emitTestEvent({ kind: 'sse', streamId: 'connection', phase: 'message', event: 'heartbeat' });
      }
    });

    // The backend refused the stream and is ending it. Close it before the
    // browser retries it, and open a new one only once the session is valid,
    // unless this stream was replaced or disconnected meanwhile.
    eventSource.addEventListener('rejected', (event) => {
      const { status, message } = parseRejection((event as MessageEvent).data);
      eventSource.close();
      stopSilenceWatch();

      if (isTestMode()) {
        emitTestEvent({
          kind: 'sse',
          streamId: 'connection',
          phase: 'message',
          event: 'rejected',
          data: { status, message },
        });
      }

      recoverFromRejection(status, () => {
        if (eventSourceRef.current === eventSource) {
          createDirectConnectionRef.current?.();
        }
      });
    });

    // Single onmessage handler unwraps the {type, payload} envelope
    // and dispatches to local listeners — mirrors the SharedWorker logic.
    eventSource.onmessage = (e: MessageEvent) => {
      heard();

      let envelope: { type: string; payload: unknown };
      try {
        envelope = JSON.parse(e.data);
      } catch {
        // Non-JSON data on the unnamed channel; ignore
        return;
      }

      if (!envelope.type) {
        return;
      }

      const eventName = envelope.type;
      const eventData = envelope.payload;

      if (isTestMode()) {
        emitTestEvent({
          kind: 'sse',
          streamId: eventName,
          phase: 'message',
          event: eventName,
          data: eventData,
        });
      }

      dispatchEvent(eventName, eventData);
    };

    // Closed, so that the browser does not reconnect it on its own: the
    // backoff is the one retry.
    eventSource.onerror = (event) => {
      if (isTestMode()) {
        console.debug('EventSource error (test mode):', event);
      } else {
        console.error('EventSource error:', event);
      }
      eventSource.close();
      stopSilenceWatch();
      markDown();
      scheduleRetry(() => createDirectConnectionRef.current?.());
    };
  }, [clearRetry, dispatchEvent, markConnected, markDown, recoverFromRejection, scheduleRetry, stopSilenceWatch]);

  useEffect(() => {
    createDirectConnectionRef.current = createDirectConnection;
  }, [createDirectConnection]);

  /**
   * Disconnect from SSE
   */
  const disconnect = useCallback(() => {
    if (sharedWorkerRef.current) {
      try {
        sharedWorkerRef.current.port.postMessage({ type: 'disconnect' });
        sharedWorkerRef.current.port.close();
      } catch (error) {
        console.error('Failed to disconnect SharedWorker:', error);
      }
      sharedWorkerRef.current = null;
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    clearRetry();
    stopSilenceWatch();

    connectedRef.current = false;
    setIsConnected(false);
  }, [clearRetry, stopSilenceWatch]);

  /**
   * Reconnect SSE (for focus-based reconnection).
   *
   * A healthy connection is left alone, on both paths, so that a focus event
   * doesn't tear it down. The recovery from a refused stream reopens it without
   * going through here.
   */
  const reconnect = useCallback(() => {
    if (isConnected) {
      return;
    }

    if (useSharedWorker.current) {
      if (sharedWorkerRef.current) {
        // The worker is alive but its stream is down: ask it to reconnect.
        sharedWorkerRef.current.port.postMessage({ type: 'reconnect' });
        return;
      }
      createSharedWorkerConnection();
      return;
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    createDirectConnection();
  }, [isConnected, createSharedWorkerConnection, createDirectConnection]);

  // Back online, a stream that is down is tried at once, its backoff begun
  // again.
  useEffect(() => {
    const onOnline = () => {
      if (connectedRef.current) {
        return;
      }
      retryRef.current.count = 0;
      if (useSharedWorker.current) {
        sharedWorkerRef.current?.port.postMessage({ type: 'reconnect' });
        return;
      }
      eventSourceRef.current?.close();
      createDirectConnection();
    };
    window.addEventListener('online', onOnline);
    return () => window.removeEventListener('online', onOnline);
  }, [createDirectConnection]);

  // Establish connection on mount
  useEffect(() => {
    if (useSharedWorker.current) {
      createSharedWorkerConnection();
    } else {
      createDirectConnection();
    }

    return () => {
      disconnect();
    };
  }, [createSharedWorkerConnection, createDirectConnection, disconnect]);

  // Test-only bridge: `window.__sseForceReconnect()` opens a new stream even
  // while the connection is healthy, which reconnect() refuses to do, so a spec
  // can make the next connect meet a refusal it has armed. It posts `reconnect`
  // to the SharedWorker, or replaces the direct EventSource. It isn't part of
  // SseContextValue, and it doesn't exist outside test mode.
  useEffect(() => {
    if (!isTestMode()) {
      return;
    }

    if (typeof window === 'undefined') {
      return;
    }

    const bridge = () => {
      if (useSharedWorker.current) {
        sharedWorkerRef.current?.port.postMessage({ type: 'reconnect' });
        return;
      }
      eventSourceRef.current?.close();
      createDirectConnection();
    };

    window.__sseForceReconnect = bridge;

    return () => {
      if (window.__sseForceReconnect === bridge) {
        delete window.__sseForceReconnect;
      }
    };
  }, [createDirectConnection]);

  const contextValue: SseContextValue = {
    isConnected,
    retrying,
    requestId,
    addEventListener,
    reconnect,
  };

  return (
    <SseContext.Provider value={contextValue}>
      {children}
    </SseContext.Provider>
  );
}
