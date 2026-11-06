/**
 * The phone, 900px and below (F98.3): where a screen whose phone use differs shows its own phone
 * component, under the same address (design/ui-conventions.md, "Phone layout"). The width is the
 * mockup's and every `@media (max-width: 900px)` rule's.
 */

import { useSyncExternalStore } from 'react';

const phone = window.matchMedia('(max-width: 900px)');

function subscribe(listener: () => void): () => void {
  phone.addEventListener('change', listener);
  return () => phone.removeEventListener('change', listener);
}

export const isPhone = (): boolean => phone.matches;

export function usePhone(): boolean {
  return useSyncExternalStore(subscribe, isPhone);
}
