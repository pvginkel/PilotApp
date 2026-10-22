/**
 * A field's text, kept in the browser as it is typed until it is sent (F133): a field opened again,
 * after a reload or in another tab, starts from what was left in it.
 */

import { useState } from 'react';
import { keepUnsent, unsentText } from '@/lib/browser-state';

/** `field` keys the text in the browser; `initial` stands while none is kept. */
export function useUnsentText(field: string, initial = '') {
  const [text, setText] = useState(() => unsentText(field) ?? initial);
  const change = (next: string) => {
    setText(next);
    keepUnsent(field, next);
  };
  return { text, change, sent: () => keepUnsent(field, '') };
}
