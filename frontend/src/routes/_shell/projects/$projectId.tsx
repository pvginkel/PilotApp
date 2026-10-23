/**
 * A project at its own address, by its id (F1.6): its head over its timeline. The browser
 * remembers it as the current project, which the bare address opens. Under it an item's address,
 * and under that a block's, open the timeline at the item or the block, and a document's opens
 * the document in the overlay over the timeline (F97), as a block's does where its document is a
 * card, at the block (F33). An attachment's address under an item's opens it in the overlay over
 * the timeline where the timeline stands, and under a document's in the document's overlay
 * (F28.5). Another project's address closes it.
 */

import { useEffect } from 'react';
import { createFileRoute, useParams } from '@tanstack/react-router';
import { ItemAttachmentOverlay } from '@/components/overlay/attachment-overlay';
import { DocumentOverlay } from '@/components/overlay/document-overlay';
import { ProjectHead } from '@/components/projects/project-head';
import { isCard } from '@/components/timeline/document-state';
import { Timeline } from '@/components/timeline/timeline';
import { useProjectHead } from '@/hooks/use-projects';
import { useTimelineItem, type TimelineItem } from '@/hooks/use-timeline';
import { rememberInBrowser } from '@/lib/browser-state';

export const Route = createFileRoute('/_shell/projects/$projectId')({
  // Everything a project opens under its route starts closed on each project, and its timeline
  // at its end (F1.6), or at the address it is opened at.
  remountDeps: ({ params }) => params.projectId,
  component: Project,
});

function Project() {
  const { projectId } = Route.useParams();
  const { itemId, blockId, documentId, attachmentId } = useParams({ strict: false });
  useEffect(() => rememberInBrowser({ project: projectId }), [projectId]);
  const { data } = useProjectHead(projectId);
  const addressed = useTimelineItem(projectId, blockId === undefined ? undefined : itemId);
  const overlaid =
    documentId !== undefined ? { documentId, block: null, attachment: attachmentId ?? null } : cardAt(addressed, blockId);
  const attached = itemId !== undefined && attachmentId !== undefined ? { itemId, attachmentId } : null;
  const goneTo = itemId === undefined || attached !== null ? null : { item: itemId, block: blockId ?? null };
  return (
    <>
      {data && <ProjectHead project={data} />}
      <Timeline projectId={projectId} address={goneTo} />
      {overlaid !== null && <DocumentOverlay projectId={projectId} project={data} {...overlaid} />}
      {attached !== null && <ItemAttachmentOverlay projectId={projectId} {...attached} />}
    </>
  );
}

/** The document a block's address opens in the overlay, at the block: its item, where it is a card. */
function cardAt(item: TimelineItem | undefined, blockId: string | undefined) {
  return item !== undefined && blockId !== undefined && isCard(item) ? { documentId: item.id, block: blockId, attachment: null } : null;
}
