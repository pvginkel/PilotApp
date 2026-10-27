/**
 * Going to a draft's ask (F41, F39.3): the effect line of an answer Pilot recorded in the definition
 * chat, and a quote of the ask, go to it in the Draft tab, the side panel open on the tab, on top,
 * the ask scrolled into view and flashed. The place is kept in the page, by the project, until the
 * tab reaches it; each go puts it afresh, so the same ask is gone to again.
 */

import { createContext, useCallback, useContext, useSyncExternalStore } from 'react';

/** The ask of the draft's `project.md` gone to, by its local id. */
interface DraftPlace {
  block: string;
}

let places: Record<string, DraftPlace | undefined> = {};
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function update(projectId: string, place: DraftPlace | undefined): void {
  places = { ...places, [projectId]: place };
  listeners.forEach((listener) => listener());
}

/** Puts the ask the project's Draft tab goes to. */
export function goToDraftBlock(projectId: string, block: string): void {
  update(projectId, { block });
}

/** The ask the project's Draft tab goes to, none once reached, and its reach. */
export function useDraftPlace(projectId: string) {
  const place = useSyncExternalStore(subscribe, () => places[projectId] ?? null);
  /** `which` was gone to: dropped where it is still the place. */
  const reached = useCallback(
    (which: DraftPlace) => {
      if (places[projectId] === which) update(projectId, undefined);
    },
    [projectId],
  );
  return { place, reached };
}

/** Going to an ask of the project's `project.md`, by its local id, which the project's route gives. */
export const DraftBlockContext = createContext<((block: string) => void) | null>(null);

export function useToDraftBlock(): (block: string) => void {
  return useContext(DraftBlockContext)!;
}
