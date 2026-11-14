/**
 * A dropped connection (F149): while the browser's connection to Pilot's server is down or slow,
 * the whole page lies under the scrim, the top bar, the gold bar and a dialog included, taking
 * every click, with a badge in its middle: Lucide's loader turning before "Connecting…", or
 * "Retrying…" once an attempt to open the stream has failed. Down is the live stream gone for
 * more than DOWN_AFTER after it stood or not up DOWN_AFTER after the launch, or the browser
 * offline; slow, a request under way for more than 8 s (`fetch-extensions.ts`). It lifts at once
 * when the connection is back, and the stream's return reads everything again
 * (`use-project-events.ts`). The stream retries for as long as it takes
 * (`sse-context-provider.tsx`).
 */

import { useEffect, useState, useSyncExternalStore } from 'react';
import { LoaderCircle } from 'lucide-react';
import { useSseContext } from '@/contexts/sse-context';
import { lateRequest } from '@/lib/api/fetch-extensions';

/** How long the stream is down before the page says so, in milliseconds. */
const DOWN_AFTER = 3000;

function subscribeOnline(listener: () => void): () => void {
  window.addEventListener('online', listener);
  window.addEventListener('offline', listener);
  return () => {
    window.removeEventListener('online', listener);
    window.removeEventListener('offline', listener);
  };
}

export function ConnectionTint() {
  const { isConnected, retrying } = useSseContext();
  const online = useSyncExternalStore(subscribeOnline, () => navigator.onLine);
  const late = useSyncExternalStore(lateRequest.subscribe, lateRequest.get);
  const [down, setDown] = useState(false);
  useEffect(() => {
    if (isConnected) return;
    const timer = setTimeout(() => setDown(true), DOWN_AFTER);
    return () => {
      clearTimeout(timer);
      setDown(false);
    };
  }, [isConnected]);
  if (online && !late && (isConnected || !down)) return null;
  return (
    <div
      className="link-down"
      // An open dialog or menu closes on a press that reaches the document (Radix's dismissable
      // layer, `use-dismiss.ts`).
      onPointerDown={(event) => event.stopPropagation()}
      data-testid="shell.connection"
    >
      <span className="link-badge" role="status" data-testid="shell.connection.badge">
        <LoaderCircle className="icon animate-spin" aria-hidden="true" />
        {retrying ? 'Retrying…' : 'Connecting…'}
      </span>
    </div>
  );
}
