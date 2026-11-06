/**
 * A project at its own address, by its id (F1.6): its head over its timeline. The browser
 * remembers it as the current project, which the bare address opens. Under it an item's address,
 * and under that a block's, open the timeline at the item or the block, and a document's opens
 * the document (F97), as a block's does where its document is a card, at the block (F33), and the
 * address under a document's of the box of Pilot's questions to its writer at the box (F52.2). An
 * attachment's address under an item's or a document's opens it (F28.5), and under the project's,
 * wherever it hangs, a draft's material hung on nothing (F36.6). The handbook's address, and the
 * project document's, open it (F129.4, F37.4), and a work item's session log's opens it (F69):
 * off a phone a popover over the tab showing, the one the line showed last, as its own address
 * draws it (F69.1). Another project's address closes them. A draft has its
 * definition chat in the timeline's place (F46.1), once the head says it is one, Create project at
 * its end once the project can be created (D119). Off a phone, what opens as a document is a tab
 * in the timeline's place (F28.1, F28.8), the tab line the head's last row while one is open
 * (`use-doc-tabs.ts`), the address following the tab showing and a move to another of the
 * project's addresses replacing the browser's entry (F97); beside the head and the timeline stands
 * the side panel, the project's own and always open (F38.1), its width dragged at its divider. Discuss anywhere on the project's
 * screens shows its Chat tab, with what it quotes in the composer (F39), and *In the chat* on a
 * block answered in the chat shows it there at the message that gave the answer (F42.3). A draft's
 * panel has the Draft and Documents tabs (F46.3), its chat standing in the timeline's place: there
 * Discuss and *In the chat* take the definition chat, showing its tab. An ask of the draft gone to
 * from its chat opens the Draft tab at it, and past Create the project document. While a tab
 * shows, the timeline under it takes no focus; the head's buttons, the tab line and the panel
 * beside it do, at the narrow width as on a wide window (F98.2), and so does what lies under the
 * session log's popover. On a phone the screen
 * is its own (`PhoneProject`), its tabs at the bottom standing for the panel, whose state it leaves
 * alone, and what the address opens a view pushed over them (F98.4): there an item's address, and
 * a block's whose item is read and no card, opens the item alone (F99) rather than the timeline at
 * it.
 */

import { useEffect, useState, type ReactNode } from 'react';
import { createFileRoute, redirect, useMatches, useNavigate, useRouter } from '@tanstack/react-router';
import { ProjectChat } from '@/components/chat/project-chat';
import { ItemAttachmentOverlay, ProjectAttachmentOverlay } from '@/components/overlay/attachment-overlay';
import { DocumentOverlay } from '@/components/overlay/document-overlay';
import { ItemOverlay } from '@/components/overlay/item-overlay';
import { HandbookOverlay, ProjectDocumentOverlay } from '@/components/overlay/project-document-overlay';
import { SessionLogOverlay } from '@/components/overlay/session-log-overlay';
import { Panel } from '@/components/panel/panel';
import { PanelDivider } from '@/components/panel/panel-divider';
import { CreateProject } from '@/components/projects/create-project';
import { DocTabs } from '@/components/projects/doc-tabs';
import { PhoneProject } from '@/components/projects/phone-project';
import { ProjectHead } from '@/components/projects/project-head';
import { isCard } from '@/components/timeline/document-state';
import { Timeline } from '@/components/timeline/timeline';
import { DocTabContext, tabLeftOn, TabMovesContext, useDocTabs } from '@/hooks/use-doc-tabs';
import { discussIn, DiscussContext } from '@/hooks/use-discuss';
import { DraftBlockContext, goToDraftBlock } from '@/hooks/use-draft-place';
import { goToChat, InChatContext, type ChatPlace } from '@/hooks/use-in-chat';
import { usePanel } from '@/hooks/use-panel';
import { isPhone, usePhone } from '@/hooks/use-phone';
import { useProjectHead, type ProjectHead as ProjectHeadOf } from '@/hooks/use-projects';
import { useTimelineItem, type TimelineItem } from '@/hooks/use-timeline';
import { rememberInBrowser, type DocTab } from '@/lib/browser-state';
import type { QuoteRef } from '@/lib/chat/quotes';

export const Route = createFileRoute('/_shell/projects/$projectId')({
  // Everything a project opens under its route starts closed on each project, and its timeline
  // at its end (F1.6), or at the address it is opened at.
  remountDeps: ({ params }) => params.projectId,
  // Off a phone, a project gone to from its row in the list shows the tab it was left on, at the
  // tab's address in the entry's place (F1.6); at its own address however else, its timeline.
  beforeLoad: ({ params, location, preload }) => {
    const tab = !preload && location.state.fromList === true && !isPhone() ? tabLeftOn(params.projectId) : null;
    if (tab !== null) throw redirect({ href: tab.href, replace: true });
  },
  component: Project,
});

function Project() {
  const { projectId } = Route.useParams();
  useEffect(() => rememberInBrowser({ project: projectId }), [projectId]);
  const { data } = useProjectHead(projectId);
  const phone = usePhone();
  const router = useRouter();
  // The matches' address: the router takes a new location a render before the matches it draws.
  const address = useMatches({ select: (matches) => matches.at(-1)!.pathname });
  const { sessionId } = shownAt(router, address);
  // Off a phone the session log's address names no tab: the one under it is the line's last.
  const under = phone || sessionId === undefined ? null : tabLeftOn(projectId);
  const pathname = under?.href ?? address;
  const { route, itemId, blockId, documentId, attachmentId } = shownAt(router, pathname);
  const addressed = useTimelineItem(projectId, blockId === undefined ? undefined : itemId);
  const box = route === '/_shell/projects/$projectId/documents/$documentId/clarification';
  const opened =
    documentId !== undefined ? { documentId, block: null, attachment: attachmentId ?? null, box } : cardAt(addressed, blockId);
  const attached = itemId !== undefined && attachmentId !== undefined ? { itemId, attachmentId } : null;
  const loose = itemId === undefined && documentId === undefined ? (attachmentId ?? null) : null;
  // A card's block opens its document, not the timeline at it.
  const goneTo = itemId === undefined || attached !== null || opened !== null ? null : { item: itemId, block: blockId ?? null };
  // A block's address waits for the read, which says whether its item is a card.
  const alone =
    phone && itemId !== undefined && attached === null && opened === null && (blockId === undefined || addressed !== undefined)
      ? { itemId, block: blockId ?? null }
      : null;
  const handbook = route === '/_shell/projects/$projectId/handbook';
  const projectDocument = route === '/_shell/projects/$projectId/project-document';
  const documents = (
    <>
      {opened !== null && <DocumentOverlay projectId={projectId} project={data} {...opened} />}
      {attached !== null && <ItemAttachmentOverlay projectId={projectId} {...attached} />}
      {loose !== null && <ProjectAttachmentOverlay projectId={projectId} attachmentId={loose} />}
      {handbook && <HandbookOverlay projectId={projectId} project={data} />}
      {projectDocument && <ProjectDocumentOverlay projectId={projectId} project={data} />}
    </>
  );
  const log = sessionId === undefined ? null : <SessionLogOverlay projectId={projectId} sessionId={sessionId} />;
  if (phone) {
    const overlaid = opened !== null || attached !== null || loose !== null || alone !== null || handbook || projectDocument || sessionId !== undefined;
    return (
      <PhoneProject projectId={projectId} project={data} overlaid={overlaid}>
        {documents}
        {alone !== null && <ItemOverlay projectId={projectId} project={data} {...alone} />}
        {log}
      </PhoneProject>
    );
  }
  // A document's tab shows it again at its own address, not at a block's or its box's.
  const documentTab = (id: string): DocTab => ({
    key: `document ${id}`,
    kind: 'document',
    id,
    href: router.buildLocation({ to: '/projects/$projectId/documents/$documentId', params: { projectId, documentId: id } }).pathname,
  });
  const tab: DocTab | null =
    opened !== null && opened.attachment === null
      ? documentTab(opened.documentId)
      : attachmentId !== undefined
        ? { key: `attachment ${attachmentId}`, kind: 'attachment', id: attachmentId, documentId, href: pathname }
        : handbook
          ? { key: 'handbook', kind: 'handbook', id: null, href: pathname }
          : projectDocument
            ? { key: 'project-document', kind: 'project-document', id: null, href: pathname }
            : null;
  return (
    <DeskProject projectId={projectId} project={data} tab={tab} goneTo={goneTo} log={log}>
      {documents}
    </DeskProject>
  );
}

interface DeskProjectProps {
  projectId: string;
  project: ProjectHeadOf | undefined;
  /** The tab the address shows, or the session log's popover lies over, none for the timeline. */
  tab: DocTab | null;
  goneTo: { item: string; block: string | null } | null;
  /** The session log the address opens in its popover, or none. */
  log: ReactNode | null;
  /** What the tab showing shows. */
  children: ReactNode;
}

/**
 * Off a phone: the head over the tab line, and the timeline, or a draft's definition chat, or the
 * tab showing in its place, the session log's popover over it; the side panel beside them.
 */
function DeskProject({ projectId, project: data, tab, goneTo, log, children }: DeskProjectProps) {
  const draft = data?.state === 'draft';
  const panel = usePanel(projectId, draft);
  const line = useDocTabs(projectId, tab);
  const navigate = useNavigate();
  const covered = tab !== null;
  // A draft's chat is its first tab.
  const toDefinitionChat = () => {
    if (covered) line.show(null);
  };
  const discuss = (quote: QuoteRef | null) => {
    discussIn(projectId, quote);
    if (draft) toDefinitionChat();
    else panel.show('chat');
  };
  const inChat = (place: ChatPlace) => {
    goToChat(projectId, place);
    if (draft) toDefinitionChat();
    else panel.show('chat');
  };
  const toDraftBlock = (block: string) => {
    if (!draft) {
      void navigate({ to: '/projects/$projectId/project-document', params: { projectId }, replace: true });
      return;
    }
    goToDraftBlock(projectId, block);
    panel.show('draft');
  };
  const [head, setHead] = useState<HTMLElement | null>(null);
  const [page, setPage] = useState<HTMLElement | null>(null);
  return (
    <TabMovesContext.Provider value>
      <DiscussContext.Provider value={discuss}>
        <InChatContext.Provider value={inChat}>
          <DraftBlockContext.Provider value={toDraftBlock}>
            <div ref={setPage} className="project">
              <div className="project-main">
                {data && <ProjectHead ref={setHead} project={data} />}
                {data && <DocTabs projectId={projectId} draft={draft} line={line} />}
                <div className="stage">
                  {data !== undefined &&
                    (draft ? (
                      <ProjectChat
                        projectId={projectId}
                        members={data.members}
                        home="feed"
                        covered={covered}
                        end={<CreateProject project={data} />}
                      />
                    ) : (
                      <Timeline projectId={projectId} address={goneTo} inert={covered} />
                    ))}
                  {tab !== null && (
                    <DocTabContext.Provider key={tab.key} value={line.shown(tab.key)}>
                      {children}
                    </DocTabContext.Provider>
                  )}
                  {log}
                </div>
              </div>
              {/* Not before the head is read, which says whether it is a draft. */}
              {data !== undefined && (
                <>
                  <PanelDivider project={page} draft={draft} />
                  <Panel projectId={projectId} draft={draft} members={data.members} tab={panel.tab} head={head} onTab={panel.show} />
                </>
              )}
            </div>
          </DraftBlockContext.Provider>
        </InChatContext.Provider>
      </DiscussContext.Provider>
    </TabMovesContext.Provider>
  );
}

/** What an address of the project shows: its route, by its id, and its params. */
function shownAt(router: ReturnType<typeof useRouter>, pathname: string) {
  const [routes, params] = router.getMatchedRoutes(pathname);
  const { itemId, blockId, documentId, attachmentId, sessionId } = params as Partial<Record<string, string>>;
  return { route: routes.at(-1)!.id, itemId, blockId, documentId, attachmentId, sessionId };
}

/** The document a block's address opens, at the block: its item, where it is a card. */
function cardAt(item: TimelineItem | null | undefined, blockId: string | undefined) {
  return item !== undefined && item !== null && blockId !== undefined && isCard(item)
    ? { documentId: item.id, block: blockId, attachment: null, box: false }
    : null;
}
