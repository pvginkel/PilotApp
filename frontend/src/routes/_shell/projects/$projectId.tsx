/**
 * A project at its own address, by its id (F1.6): its head over its timeline. The browser
 * remembers it as the current project, which the bare address opens. Under it an item's address,
 * and under that a block's, open the timeline at the item or the block, and a document's opens
 * the document in the overlay over the timeline, at the block its address names (F97); another
 * project's address closes it.
 */

import { useEffect } from 'react';
import { createFileRoute, useParams, useSearch } from '@tanstack/react-router';
import { DocumentOverlay } from '@/components/overlay/document-overlay';
import { ProjectHead } from '@/components/projects/project-head';
import { Timeline } from '@/components/timeline/timeline';
import { useProjectHead } from '@/hooks/use-projects';
import { rememberInBrowser } from '@/lib/browser-state';

export const Route = createFileRoute('/_shell/projects/$projectId')({
  // Everything a project opens under its route starts closed on each project, and its timeline
  // at its end (F1.6), or at the address it is opened at.
  remountDeps: ({ params }) => params.projectId,
  component: Project,
});

function Project() {
  const { projectId } = Route.useParams();
  const { itemId, blockId, documentId } = useParams({ strict: false });
  const { block } = useSearch({ strict: false });
  useEffect(() => rememberInBrowser({ project: projectId }), [projectId]);
  const { data } = useProjectHead(projectId);
  return (
    <>
      {data && <ProjectHead project={data} />}
      <Timeline projectId={projectId} address={itemId === undefined ? null : { item: itemId, block: blockId ?? null }} />
      {documentId !== undefined && (
        <DocumentOverlay projectId={projectId} project={data} documentId={documentId} block={block ?? null} />
      )}
    </>
  );
}
