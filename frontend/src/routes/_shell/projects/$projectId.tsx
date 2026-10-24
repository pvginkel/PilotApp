/**
 * A project at its own address, by its id (F1.6): its head over its timeline. The browser
 * remembers it as the current project, which the bare address opens. Under it an item's address,
 * and under that a block's, open the timeline at the item or the block, and a document's opens
 * the document in the overlay over the timeline (F97), as a block's does where its document is a
 * card, at the block (F33). An attachment's address under an item's opens it in the overlay over
 * the timeline where the timeline stands, and under a document's in the document's overlay
 * (F28.5). The handbook's address, and the project document's, open it in the overlay over the
 * timeline (F129.4, F37.4), and a work item's session log's opens it there (F69). Another
 * project's address closes it. Beside the head and the timeline stands the side panel, the
 * project's own (F38.1), which a draft does not have. While an overlay is open, the timeline under
 * its backdrop takes no focus, nor the panel where the overlay lies over it; the head's buttons do,
 * the Documents button being how the panel opens over the overlay below a wide window (F98.2).
 */

import { useEffect, useState } from 'react';
import { createFileRoute, useMatch, useParams, useRouterState } from '@tanstack/react-router';
import { ItemAttachmentOverlay } from '@/components/overlay/attachment-overlay';
import { DocumentOverlay } from '@/components/overlay/document-overlay';
import { HandbookOverlay, ProjectDocumentOverlay } from '@/components/overlay/project-document-overlay';
import { SessionLogOverlay } from '@/components/overlay/session-log-overlay';
import { Panel } from '@/components/panel/panel';
import { ProjectHead } from '@/components/projects/project-head';
import { isCard } from '@/components/timeline/document-state';
import { Timeline } from '@/components/timeline/timeline';
import { usePanel } from '@/hooks/use-panel';
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
  const { itemId, blockId, documentId, attachmentId, sessionId } = useParams({ strict: false });
  useEffect(() => rememberInBrowser({ project: projectId }), [projectId]);
  const { data } = useProjectHead(projectId);
  const addressed = useTimelineItem(projectId, blockId === undefined ? undefined : itemId);
  const overlaid =
    documentId !== undefined ? { documentId, block: null, attachment: attachmentId ?? null } : cardAt(addressed, blockId);
  const attached = itemId !== undefined && attachmentId !== undefined ? { itemId, attachmentId } : null;
  const goneTo = itemId === undefined || attached !== null ? null : { item: itemId, block: blockId ?? null };
  const handbook = useMatch({ from: '/_shell/projects/$projectId/handbook', shouldThrow: false }) !== undefined;
  const projectDocument = useMatch({ from: '/_shell/projects/$projectId/project-document', shouldThrow: false }) !== undefined;
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const overlay = overlaid !== null || attached !== null || handbook || projectDocument || sessionId !== undefined ? pathname : null;
  const toItem = itemId === undefined || attached !== null ? null : `${itemId}/${blockId ?? ''}`;
  const { panel, front, covered, show, close, toggle, overlayOnTop } = usePanel(projectId, overlay, toItem);
  const [head, setHead] = useState<HTMLElement | null>(null);
  // Not before the head is read, which says whether it is a draft, nor where it never is.
  const panelShown = panel.open && data !== undefined && data.state !== 'draft';
  return (
    <div className="project" data-panel={panelShown ? 'open' : 'closed'} data-front={front}>
      <div className="project-main">
        {data && (
          <ProjectHead
            ref={setHead}
            project={data}
            documents={{ shown: panelShown && panel.tab === 'documents', toggle: () => toggle('documents') }}
          />
        )}
        <Timeline projectId={projectId} address={goneTo} inert={overlay !== null} />
      </div>
      {panelShown && (
        <Panel projectId={projectId} tab={panel.tab} head={head} onTab={show} onClose={close} onOpen={overlayOnTop} covered={covered} />
      )}
      {overlaid !== null && <DocumentOverlay projectId={projectId} project={data} {...overlaid} />}
      {attached !== null && <ItemAttachmentOverlay projectId={projectId} {...attached} />}
      {handbook && <HandbookOverlay projectId={projectId} project={data} />}
      {projectDocument && <ProjectDocumentOverlay projectId={projectId} project={data} />}
      {sessionId !== undefined && <SessionLogOverlay projectId={projectId} sessionId={sessionId} />}
    </div>
  );
}

/** The document a block's address opens in the overlay, at the block: its item, where it is a card. */
function cardAt(item: TimelineItem | undefined, blockId: string | undefined) {
  return item !== undefined && blockId !== undefined && isCard(item) ? { documentId: item.id, block: blockId, attachment: null } : null;
}
