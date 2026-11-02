/**
 * A project's screen on a phone (F98.3): its head, the tab showing, and the tabs at the bottom —
 * Timeline, Chat, Plan and Documents; a draft's Chat, the definition chat in the timeline's place,
 * Create project at its end (D119), Draft and Documents. Each tab is its icon over its name, the one
 * showing in the primary's tint, its icon on a pill; Chat carries the unread dot (F43) and Documents
 * its count (F37.3) on the icon's corner. Chat, Documents and Draft are the side panel's tabs without
 * its head (F38.1), Plan the plan popover's content as a page (F3.7). The Timeline, or a draft's
 * Chat, keeps its place under the other tabs. Discuss and *In the chat* anywhere on it show the Chat
 * tab, a draft's its Chat, and an ask of the draft gone to the Draft tab at it; where they stand in
 * the overlay, it is taken off. The tab is the entry's in the browser's history (`use-phone-tab.ts`).
 */

import type { ReactNode } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { Files, FileText, List, ListChecks, MessagesSquare, type LucideIcon } from 'lucide-react';
import { ProjectChat } from '@/components/chat/project-chat';
import { PhonePanel } from '@/components/panel/panel';
import { CreateProject } from '@/components/projects/create-project';
import { PlanPage } from '@/components/projects/plan-popover';
import { ProjectHead } from '@/components/projects/project-head';
import { Timeline } from '@/components/timeline/timeline';
import { useChatDot } from '@/hooks/use-chats';
import { discussIn, DiscussContext } from '@/hooks/use-discuss';
import { DraftBlockContext, goToDraftBlock } from '@/hooks/use-draft-place';
import { goToChat, InChatContext, type ChatPlace } from '@/hooks/use-in-chat';
import { usePanelDocuments } from '@/hooks/use-panel';
import { DRAFT_TABS, PROJECT_TABS, usePhoneTab, type PhoneTab } from '@/hooks/use-phone-tab';
import type { ProjectHead as Project } from '@/hooks/use-projects';
import type { QuoteRef } from '@/lib/chat/quotes';
import { cn } from '@/lib/utils';

interface PhoneProjectProps {
  projectId: string;
  /** The project's head, once read. */
  project: Project | undefined;
  /** Whether an overlay the address opens lies over the screen. */
  overlaid: boolean;
  /** The item, or its block, the address opens the timeline at. */
  goneTo: { item: string; block: string | null } | null;
  /** The overlays the address opens. */
  children: ReactNode;
}

export function PhoneProject({ projectId, project, overlaid, goneTo, children }: PhoneProjectProps) {
  const draft = project?.state === 'draft';
  const { tab, show } = usePhoneTab(projectId, draft, overlaid);
  const documents = usePanelDocuments(projectId);
  const navigate = useNavigate();
  const chatTab = draft ? 'timeline' : 'chat';
  const discuss = (quote: QuoteRef) => {
    discussIn(projectId, quote);
    show(chatTab);
  };
  const inChat = (place: ChatPlace) => {
    goToChat(projectId, place);
    show(chatTab);
  };
  const toDraftBlock = (block: string) => {
    if (!draft) {
      void navigate({ to: '/projects/$projectId/project-document', params: { projectId } });
      return;
    }
    goToDraftBlock(projectId, block);
    show('draft');
  };
  const away = tab !== 'timeline';
  return (
    <DiscussContext.Provider value={discuss}>
      <InChatContext.Provider value={inChat}>
        <DraftBlockContext.Provider value={toDraftBlock}>
          <div className="project">
            {project && (
              <div className="project-main">
                <ProjectHead project={project} />
                <div className="phone-page" data-tab={tab} data-testid="project.phone-page">
                  {draft ? (
                    <ProjectChat
                      projectId={projectId}
                      members={project.members}
                      home="feed"
                      covered={overlaid || away}
                      end={<CreateProject project={project} />}
                    />
                  ) : (
                    <Timeline projectId={projectId} address={goneTo} inert={overlaid || away} />
                  )}
                  {(tab === 'chat' || tab === 'documents' || tab === 'draft') && (
                    <PhonePanel projectId={projectId} draft={draft} members={project.members} tab={tab} documents={documents} covered={overlaid} />
                  )}
                  {tab === 'plan' && <PlanPage tasks={project.tasks} />}
                </div>
                <PhoneTabs projectId={projectId} draft={draft} tab={tab} count={documents.count} onTab={show} />
              </div>
            )}
            {children}
          </div>
        </DraftBlockContext.Provider>
      </InChatContext.Provider>
    </DiscussContext.Provider>
  );
}

const TABS: Record<PhoneTab, { name: string; icon: LucideIcon }> = {
  timeline: { name: 'Timeline', icon: List },
  chat: { name: 'Chat', icon: MessagesSquare },
  plan: { name: 'Plan', icon: ListChecks },
  documents: { name: 'Documents', icon: Files },
  draft: { name: 'Draft', icon: FileText },
};

interface PhoneTabsProps {
  projectId: string;
  draft: boolean;
  tab: PhoneTab;
  /** The Documents tab's count. */
  count: number;
  onTab: (tab: PhoneTab) => void;
}

function PhoneTabs({ projectId, draft, tab, count, onTab }: PhoneTabsProps) {
  const unread = useChatDot(projectId);
  return (
    <nav className="phone-tabs" role="tablist" aria-label="The project" data-testid="project.tabs">
      {(draft ? DRAFT_TABS : PROJECT_TABS).map((key) => {
        const { name, icon: Icon } = key === 'timeline' && draft ? TABS.chat : TABS[key];
        const dot = key === 'chat' && unread;
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={key === tab}
            aria-label={dot ? `${name}, a reply unread` : undefined}
            className={cn('ttab', key === tab && 'on')}
            onClick={() => onTab(key)}
            data-testid={`project.tabs.${key}`}
          >
            <span className="pill">
              <Icon className="icon" aria-hidden="true" />
              {dot && <span className="unread" data-testid="project.tabs.chat.unread" />}
              {key === 'documents' && count > 0 && (
                <span className="ptab-count" data-testid="project.tabs.documents.count">
                  {count}
                </span>
              )}
            </span>
            {name}
          </button>
        );
      })}
    </nav>
  );
}
