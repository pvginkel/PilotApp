/**
 * The fetch the generated API client sends every request through (`scripts/generate-api.js`): the
 * browser's, each request counted from its send until it is answered or fails, so that the page
 * can tell a connection that has gone slow (F149): `lateRequest` holds while a request has been
 * under way for more than SLOW_MS.
 */

/** How long a request is under way before the connection counts as slow, in milliseconds. */
const SLOW_MS = 8000;

/** Each request under way, by a token of its own, and when it was sent (`performance.now()`). */
const sentAt = new Map<object, number>();
const listeners = new Set<() => void>();
let late = false;
let timer: ReturnType<typeof setTimeout> | undefined;

/** Whether a request is late, and, while one is under way and none is, a look when the oldest would be. */
function look(): void {
  clearTimeout(timer);
  const oldest = sentAt.size === 0 ? null : Math.min(...sentAt.values());
  const left = oldest === null ? 0 : oldest + SLOW_MS - performance.now();
  if (oldest !== null && left > 0) timer = setTimeout(look, left);
  const now = oldest !== null && left <= 0;
  if (now === late) return;
  late = now;
  for (const listener of listeners) listener();
}

export function appFetch(request: Request): Promise<Response> {
  const token = {};
  sentAt.set(token, performance.now());
  look();
  return fetch(request).finally(() => {
    sentAt.delete(token);
    look();
  });
}

/** Whether a request has been under way for more than SLOW_MS, for `useSyncExternalStore`. */
export const lateRequest = {
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  get: (): boolean => late,
};
