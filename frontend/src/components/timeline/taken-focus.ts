/**
 * The focus Pilot's note taken gives the field it fills (F168.2; take-note.ts), as the mockup's take
 * does: the block whose button took it asks for it by the field's key, `<block key>/<part>`, and the
 * field drawn under that key in that block takes it once, at once or as it shows, as the note field
 * its Send carries shows once it holds words; drawn again later, it takes none. A block drawn twice,
 * on the timeline and in its tab over it, gives it to the drawing whose button was pressed alone.
 */

import { createContext, useContext, useEffect, useRef } from 'react';

/** A take's ask for the focus, by the key of the field it filled: each take's its own. */
export interface FocusAsk {
  field: string;
}

/** The latest ask of the block drawn under it; none before its first take. */
export const TakenFocusContext = createContext<FocusAsk | null>(null);

/** The asks a field has taken the focus on. */
const answered = new WeakSet<FocusAsk>();

/** The ref of the text field kept under `field`, which takes the focus where its block's take asks for it. */
export function useTakenFocus(field: string) {
  const asked = useContext(TakenFocusContext);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (asked === null || asked.field !== field || ref.current === null || answered.has(asked)) return;
    ref.current.focus();
    answered.add(asked);
  }, [asked, field]);
  return ref;
}
