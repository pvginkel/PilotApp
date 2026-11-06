/**
 * The side panel (F38.1): each project's own, open or closed and on which tab, as the person last
 * left it, kept in the browser and nothing of it on the server (F1.6, F133); until they set it,
 * open on its first tab: an open project's Chat, a draft's Draft (F46.3), each standing for the
 * other across Create project. Off a phone, wide or narrow, it stands beside the timeline, or a
 * draft's definition chat, or the tab showing in their place; nothing lies over it, and Esc never closes it
 * (F98.1, F98.2). Its Documents tab lists the project document, the attachments, a batch of several
 * together, and the timeline's documents and reviews, newest first (F37), from the project's
 * timeline and its project document, read as one; a draft's lists what Pilot attached so far, hung
 * on nothing (F36.6).
 */

import { useGetProjectsDraftByProjectId, useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';
import { PANEL_TABS, rememberPanel, useBrowserState, type Panel, type PanelTab } from '@/lib/browser-state';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';
import type { Attachment, TimelineItem } from '@/hooks/use-timeline';

interface PanelState {
  panel: Panel;
  /** Opens the panel on the tab. */
  show: (tab: PanelTab) => void;
  close: () => void;
  /** Closes the panel when the tab is the one showing, else shows it (F2.3). */
  toggle: (tab: PanelTab) => void;
}

/** A draft's first tab is Draft where an open project's is Chat; Documents is either's. */
const tabOf = (tab: PanelTab, draft: boolean): PanelTab => (tab === 'documents' ? tab : draft ? 'draft' : 'chat');

/** The project's panel, a draft's if `draft`. */
export function usePanel(projectId: string, draft: boolean): PanelState {
  const { panels } = useBrowserState();
  const left = panels[projectId] ?? { open: true, tab: PANEL_TABS[0] };
  const panel = { ...left, tab: tabOf(left.tab, draft) };
  const show = (tab: PanelTab) => rememberPanel(projectId, { open: true, tab });
  const close = () => rememberPanel(projectId, { ...panel, open: false });
  return {
    panel,
    show,
    close,
    toggle: (tab) => (panel.open && panel.tab === tab ? close() : show(tab)),
  };
}

/** Attachments hung on an item in one call (F37.1), or on none: a draft's (F36.6). */
export interface Batch {
  batch: number;
  item: TimelineItem | null;
  attachments: Attachment[];
}

/** The tab's lists, newest first. */
export interface PanelLists {
  /** Each batch's files in their order. */
  batches: Batch[];
  /** The timeline's documents and reviews. */
  documents: TimelineItem[];
}

/** The tab's read, its timeline's and its project document's together: its lists once both landed. */
export type PanelRead = PanelLists | 'pending' | 'failed';

export interface PanelDocuments {
  /** The project document's title: its text's, once read; none until then, and where its text gives none. */
  projectDocument: string | null;
  /** `pending` while either read has nothing yet, `failed` while either's latest read failed (F113). */
  lists: PanelRead;
  /** What the tab carries on its name: the attachments and the timeline's documents, once read (F37.3). */
  count: number;
}

export function usePanelDocuments(projectId: string): PanelDocuments {
  const timeline = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } }, { refetchOnWindowFocus: 'always' });
  const draft = useGetProjectsDraftByProjectId({ path: { project_id: projectId } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation('panel.documents', {
    isLoading: timeline.isLoading || draft.isLoading,
    error: timeline.error ?? draft.error,
  });
  const projectDocument = draft.data?.title ?? null;
  if (timeline.error !== null || draft.error !== null) return { projectDocument, lists: 'failed', count: 0 };
  if (timeline.data === undefined || draft.data === undefined) return { projectDocument, lists: 'pending', count: 0 };
  const { items, unhung_attachments } = timeline.data;
  const batches = [...items.map((item) => batchesOf(item, item.attachments)), batchesOf(null, unhung_attachments)]
    .flat()
    .sort((one, other) => other.batch - one.batch);
  const documents = items.filter((item) => item.kind === 'document' || item.kind === 'review').reverse();
  return {
    projectDocument,
    lists: { batches, documents },
    count: batches.reduce((count, batch) => count + batch.attachments.length, 0) + documents.length,
  };
}

/** The attachments of one item, or of none, by their batch, each batch's in their order. */
function batchesOf(item: TimelineItem | null, attachments: Attachment[]): Batch[] {
  const byBatch = new Map<number, Batch>();
  for (const attachment of attachments) {
    const batch = byBatch.get(attachment.batch) ?? { batch: attachment.batch, item, attachments: [] };
    batch.attachments.push(attachment);
    byBatch.set(attachment.batch, batch);
  }
  return [...byBatch.values()];
}
