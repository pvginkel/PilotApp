/**
 * How an asked block's mark goes to the box of Pilot's questions to the writer and the reply in the
 * overlay showing its document (F52.2; writer-asked.tsx); null elsewhere, where the mark opens the
 * document at the box's address.
 */

import { createContext } from 'react';

export const ToClarificationContext = createContext<(() => void) | null>(null);
