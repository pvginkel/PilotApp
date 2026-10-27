/**
 * A project at its own address, by its id (F1.6): its head over its timeline. The browser
 * remembers it as the current project, which the bare address opens. Under it an item's address,
 * and under that a block's, open the timeline at the item or the block, and a document's opens
 * the document in the overlay over the timeline (F97), as a block's does where its document is a
 * card, at the block (F33). An attachment's address under an item's opens it in the overlay over
 * the timeline where the timeline stands, and under a document's in the document's overlay
 * (F28.5), and under the project's, wherever it hangs, a draft's material hung on nothing
 * (F36.6). The handbook's address, and the project document's, open it in the overlay over the
 * timeline (F129.4, F37.4), and a work item's session log's opens it there (F69). Another
 * project's address closes it. A draft has its definition chat in the timeline's place (F46.1),
 * once the head says it is one. Beside the head and the timeline stands the side panel, the
 * project's own (F38.1); Discuss anywhere on the project's screens opens it on the Chat tab, on
 * top, with what it quotes in the composer (F39), and *In the chat* on a block answered in the chat
 * opens it there at the message that gave the answer (F42.3). A draft's panel has the Draft and
 * Documents tabs (F46.3), its chat standing in the timeline's place: there Discuss and *In the chat*
 * take the definition chat, closing an overlay over it and, below a wide window, the panel. An
 * ask of the draft gone to from its chat opens the Draft tab at it, and past Create the project
 * document. While an overlay is open, the timeline under its backdrop takes no focus, nor the panel
 * where the overlay lies over it; the head's buttons do, the Documents button being how the panel
 * opens over the overlay below a wide window (F98.2).
 */

import { useEffect, useState } from 'react';
import { createFileRoute, useMatch, useNavigate, useParams, useRouterState } from '@tanstack/react-router';
import { ProjectChat } from '@/components/chat/project-chat';
import { ItemAttachmentOverlay, ProjectAttachmentOverlay } from '@/components/overlay/attachment-overlay';
import { DocumentOverlay } from '@/components/overlay/document-overlay';
import { HandbookOverlay, ProjectDocumentOverlay } from '@/components/overlay/project-document-overlay';
import { SessionLogOverlay } from '@/components/overlay/session-log-overlay';
import { Panel } from '@/components/panel/panel';
import { ProjectHead } from '@/components/projects/project-head';
import { isCard } from '@/components/timeline/document-state';
import { Timeline } from '@/components/timeline/timeline';
import { discussIn, DiscussContext } from '@/hooks/use-discuss';
import { DraftBlockContext, goToDraftBlock } from '@/hooks/use-draft-place';
import { goToChat, InChatContext, type ChatPlace } from '@/hooks/use-in-chat';
import { usePanel, useWideWindow } from '@/hooks/use-panel';
import { useProjectHead } from '@/hooks/use-projects';
import { useTimelineItem, type TimelineItem } from '@/hooks/use-timeline';
import { rememberInBrowser } from '@/lib/browser-state';
import type { QuoteRef } from '@/lib/chat/quotes';

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
  const loose = itemId === undefined && documentId === undefined ? (attachmentId ?? null) : null;
  const goneTo = itemId === undefined || attached !== null ? null : { item: itemId, block: blockId ?? null };
  const handbook = useMatch({ from: '/_shell/projects/$projectId/handbook', shouldThrow: false }) !== undefined;
  const projectDocument = useMatch({ from: '/_shell/projects/$projectId/project-document', shouldThrow: false }) !== undefined;
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const overlay =
    overlaid !== null || attached !== null || loose !== null || handbook || projectDocument || sessionId !== undefined ? pathname : null;
  const toItem = itemId === undefined || attached !== null ? null : `${itemId}/${blockId ?? ''}`;
  const draft = data?.state === 'draft';
  const { panel, front, covered, show, close, toggle, overlayOnTop } = usePanel(projectId, draft, overlay, toItem);
  const wide = useWideWindow();
  const navigate = useNavigate();
  // A draft's chat stands in the timeline's place, under the overlay and, below a wide window, the panel.
  const toDefinitionChat = () => {
    if (overlay !== null) void navigate({ to: '/projects/$projectId', params: { projectId } });
    if (!wide) close();
  };
  const discuss = (quote: QuoteRef | null) => {
    discussIn(projectId, quote);
    if (draft) toDefinitionChat();
    else show('chat');
  };
  const inChat = (place: ChatPlace) => {
    goToChat(projectId, place);
    if (draft) toDefinitionChat();
    else show('chat');
  };
  const toDraftBlock = (block: string) => {
    if (!draft) {
      void navigate({ to: '/projects/$projectId/project-document', params: { projectId } });
      return;
    }
    goToDraftBlock(projectId, block);
    show('draft');
  };
  const [head, setHead] = useState<HTMLElement | null>(null);
  // Not before the head is read, which says whether it is a draft.
  const panelShown = panel.open && data !== undefined;
  const chatShown = panelShown && panel.tab === 'chat';
  return (
    <DiscussContext.Provider value={discuss}>
      <InChatContext.Provider value={inChat}>
        <DraftBlockContext.Provider value={toDraftBlock}>
          <div className="project" data-panel={panelShown ? 'open' : 'closed'} data-front={front}>
            <div className="project-main">
              {data && (
                <ProjectHead
                  ref={setHead}
                  project={data}
                  chat={{ shown: chatShown, toggle: () => (chatShown ? close() : discuss(null)) }}
                  documents={{ shown: panelShown && panel.tab === 'documents', toggle: () => toggle('documents') }}
                  draftTab={{ shown: panelShown && panel.tab === 'draft', toggle: () => toggle('draft') }}
                />
              )}
              {data !== undefined &&
                (draft ? (
                  <ProjectChat projectId={projectId} members={data.members} home="feed" covered={overlay !== null} />
                ) : (
                  <Timeline projectId={projectId} address={goneTo} inert={overlay !== null} />
                ))}
            </div>
            {panelShown && (
              <Panel
                projectId={projectId}
                draft={draft}
                members={data.members}
                tab={panel.tab}
                head={head}
                onTab={show}
                onClose={close}
                onOpen={overlayOnTop}
                covered={covered}
              />
            )}
            {overlaid !== null && <DocumentOverlay projectId={projectId} project={data} {...overlaid} />}
            {attached !== null && <ItemAttachmentOverlay projectId={projectId} {...attached} />}
            {loose !== null && <ProjectAttachmentOverlay projectId={projectId} attachmentId={loose} />}
            {handbook && <HandbookOverlay projectId={projectId} project={data} />}
            {projectDocument && <ProjectDocumentOverlay projectId={projectId} project={data} />}
            {sessionId !== undefined && <SessionLogOverlay projectId={projectId} sessionId={sessionId} />}
          </div>
        </DraftBlockContext.Provider>
      </InChatContext.Provider>
    </DiscussContext.Provider>
  );
}

/** The document a block's address opens in the overlay, at the block: its item, where it is a card. */
function cardAt(item: TimelineItem | undefined, blockId: string | undefined) {
  return item !== undefined && blockId !== undefined && isCard(item) ? { documentId: item.id, block: blockId, attachment: null } : null;
}
