/**
 * The narrow width, above the phone's 900px and below 1200px (F98.2): the wide layout, but for the
 * project list, a drawer opened from the top bar. The widths are the mockup's and `use-phone.ts`'s.
 */

import { useSyncExternalStore } from 'react';

const narrow = window.matchMedia('(min-width: 901px) and (max-width: 1199px)');

function subscribe(listener: () => void): () => void {
  narrow.addEventListener('change', listener);
  return () => narrow.removeEventListener('change', listener);
}

export function useNarrow(): boolean {
  return useSyncExternalStore(subscribe, () => narrow.matches);
}
