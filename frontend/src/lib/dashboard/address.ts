/**
 * The dashboard's place in the page's address (F160.3), read off the hash as the browser holds it
 * (`hashOf` in `screens.ts`), never the router's decoded hash, in which a value's `%26` reads as
 * `&`:
 *
 * - `#dash/<tab>/<state>`: a view tab and the state it shows, in the state's grammar (`state.ts`);
 * - `#dash/<tab>`: a tab with no state;
 * - `#dash`: no tab named, the dashboard as it was left;
 * - `#dash/<state>`: a link that names no tab.
 *
 * A tab's id holds no `=`, and a state always does, which tells the last two apart; a value in a
 * state is written with its `/` encoded, so the first `/` after a tab's id ends it.
 */

import { DASH } from '@/lib/screens';

/** What a dashboard address names, each part null where it names none. */
interface Place {
  tab: string | null;
  state: string | null;
}

/** What `hash`, a dashboard address's hash, `#` first, names. */
export function placeOf(hash: string): Place {
  const rest = hash.slice(DASH.length + 1);
  const end = rest.indexOf('/');
  const head = end < 0 ? rest : rest.slice(0, end);
  if (head.includes('=')) return { tab: null, state: rest };
  const state = end < 0 ? '' : rest.slice(end + 1);
  return { tab: head === '' ? null : head, state: state === '' ? null : state };
}
