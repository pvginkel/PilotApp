/**
 * The side panel (F38.1): each project's own, open or closed and on which tab, as the person last
 * left it, kept in the browser and nothing of it on the server (F1.6, F133); until they set it,
 * open on a wide window and closed below one. On a wide window it stands beside the timeline and
 * the overlay beside it (F98.1). Below one the two lie over each other, the one opened last on top,
 * and Esc closes that one first; with no overlay open Esc leaves the panel alone; going to an item
 * closes the panel (F98.2). Its Documents tab lists the project document, the attachments, a batch
 * of several together, and the timeline's documents and reviews, newest first (F37).
 */

import { useEffect, useState, useSyncExternalStore } from 'react';
import { useGetProjectsDraftByProjectId, useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';
import { browserState, rememberPanel, useBrowserState, type Panel, type PanelTab } from '@/lib/browser-state';
import { useEscape } from '@/lib/keys';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';
import type { Attachment, TimelineItem } from '@/hooks/use-timeline';

/** The mockup's width at which the panel stands beside the timeline (design/mockup/app.js, style.css). */
const wideWindow = window.matchMedia('(min-width: 1200px)');

function subscribeWide(listener: () => void): () => void {
  wideWindow.addEventListener('change', listener);
  return () => wideWindow.removeEventListener('change', listener);
}

export function useWideWindow(): boolean {
  return useSyncExternalStore(subscribeWide, () => wideWindow.matches);
}

/** Which of the panel and the overlay is on top where they lie over each other. */
type Front = 'overlay' | 'panel';

interface PanelState {
  panel: Panel;
  front: Front;
  /** Opens the panel on the tab, on top. */
  show: (tab: PanelTab) => void;
  close: () => void;
  /** Closes the panel when the tab is the one showing, else shows it (F2.3). */
  toggle: (tab: PanelTab) => void;
  /** Puts the overlay on top: what it shows was opened. */
  overlayOnTop: () => void;
}

/**
 * The project's panel, beside an overlay showing what `overlay` keys, or none, at an address that
 * goes to the item `goneTo` keys, or none.
 */
export function usePanel(projectId: string, overlay: string | null, goneTo: string | null): PanelState {
  const { panels } = useBrowserState();
  const wide = useWideWindow();
  const panel = panels[projectId] ?? { open: wide, tab: 'documents' };
  // What the overlay shows, opened, is on top until the panel is opened or its tab chosen.
  const [front, setFront] = useState<Front>('overlay');
  const [shown, setShown] = useState(overlay);
  if (overlay !== shown) {
    setShown(overlay);
    if (overlay !== null) setFront('overlay');
  }
  const show = (tab: PanelTab) => {
    rememberPanel(projectId, { open: true, tab });
    setFront('panel');
  };
  const close = () => rememberPanel(projectId, { ...panel, open: false });
  useEscape('panel', panel.open && !wide && overlay !== null && front === 'panel', close);
  useEffect(() => {
    if (goneTo === null || wideWindow.matches) return;
    const left = browserState().panels[projectId];
    if (left?.open) rememberPanel(projectId, { ...left, open: false });
  }, [projectId, goneTo]);
  return {
    panel,
    front,
    show,
    close,
    toggle: (tab) => (panel.open && panel.tab === tab ? close() : show(tab)),
    overlayOnTop: () => setFront('overlay'),
  };
}

/** Attachments hung on an item in one call (F37.1). */
export interface Batch {
  batch: number;
  item: TimelineItem;
  attachments: Attachment[];
}

interface PanelDocuments {
  /** The project document's title: its text's, once read; none where its text gives none. */
  projectDocument: string | null;
  /** Newest first, each batch's files in their order. */
  batches: Batch[];
  /** The timeline's documents and reviews, newest first. */
  documents: TimelineItem[];
  /** What the tab carries on its name: the attachments and the timeline's documents (F37.3). */
  count: number;
}

export function usePanelDocuments(projectId: string): PanelDocuments {
  const timeline = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } }, { refetchOnWindowFocus: 'always' });
  const draft = useGetProjectsDraftByProjectId({ path: { project_id: projectId } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation('panel.documents', {
    isLoading: timeline.isLoading || draft.isLoading,
    error: timeline.error ?? draft.error,
  });
  const items = timeline.data?.items ?? [];
  const batches = items
    .flatMap((item) => {
      const byBatch = new Map<number, Batch>();
      for (const attachment of item.attachments) {
        const batch = byBatch.get(attachment.batch) ?? { batch: attachment.batch, item, attachments: [] };
        batch.attachments.push(attachment);
        byBatch.set(attachment.batch, batch);
      }
      return [...byBatch.values()];
    })
    .sort((one, other) => other.batch - one.batch);
  const documents = items.filter((item) => item.kind === 'document' || item.kind === 'review').reverse();
  return {
    projectDocument: draft.data?.title ?? null,
    batches,
    documents,
    count: batches.reduce((count, batch) => count + batch.attachments.length, 0) + documents.length,
  };
}
