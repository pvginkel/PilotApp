/** What links in text, read once under the shell (linked-text.tsx's `LinksProvider`). */

import { createContext, useContext } from 'react';
import type { Linker } from '@/lib/links';

export const LinksContext = createContext<Linker | null>(null);

/** What links in text, for every renderer of the record's words, Markdown's included. */
export function useLinker(): Linker {
  const link = useContext(LinksContext);
  if (link === null) throw new Error('Text is linked only under the shell');
  return link;
}
