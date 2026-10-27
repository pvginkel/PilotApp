/**
 * The side panel (F38.1), its shell: the tab strip, Chat first with the unread dot (F43), then
 * Documents with its count (F37.3), and the close cross; a draft's, Draft in Chat's place (F46.3).
 * On a wide window it stands beside the timeline, its head as tall as the project's head and its
 * tab's text on the project name's baseline, in whatever font (F98.1); below one it lies over the
 * timeline, with a head of its own height (F98.2); on a phone it is the whole screen (F98.3).
 */

import { useLayoutEffect, useRef, type RefObject } from 'react';
import { X } from 'lucide-react';
import { ProjectChat } from '@/components/chat/project-chat';
import { DocumentsTab } from '@/components/panel/documents-tab';
import { DraftTab } from '@/components/panel/draft-tab';
import { useChatDot } from '@/hooks/use-chats';
import { usePanelDocuments, useWideWindow } from '@/hooks/use-panel';
import type { components } from '@/lib/api/generated/types';
import type { PanelTab } from '@/lib/browser-state';
import { cn } from '@/lib/utils';

type Member = components['schemas']['ProjectHeadSchema.e86ccd6.MemberSchema'];

interface PanelProps {
  projectId: string;
  /** The project is a draft. */
  draft: boolean;
  /** The project's members, as its head reads them. */
  members: readonly Member[];
  tab: PanelTab;
  /** The project's head, once drawn, which a wide window's panel head lines up with. */
  head: HTMLElement | null;
  onTab: (tab: PanelTab) => void;
  onClose: () => void;
  /** A row was opened in the overlay. */
  onOpen: () => void;
  /** It lies under the overlay and its backdrop: it takes no focus. */
  covered: boolean;
}

export function Panel({ projectId, draft, members, tab, head, onTab, onClose, onOpen, covered }: PanelProps) {
  const documents = usePanelDocuments(projectId);
  const panelHead = useAlignedHead(head, useWideWindow());
  return (
    <aside
      className="panel"
      aria-label={draft ? 'The draft and its documents' : 'The project’s chat and documents'}
      inert={covered}
      data-testid="panel"
    >
      <div ref={panelHead} className="panel-head" role="tablist" data-testid="panel.head">
        {draft ? (
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'draft'}
            className={cn('ptab', tab === 'draft' && 'on')}
            onClick={() => onTab('draft')}
            data-testid="panel.tab.draft"
          >
            Draft
          </button>
        ) : (
          <ChatTab projectId={projectId} on={tab === 'chat'} onTab={onTab} />
        )}
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'documents'}
          className={cn('ptab', tab === 'documents' && 'on')}
          onClick={() => onTab('documents')}
          data-testid="panel.tab.documents"
        >
          Documents
          {documents.count > 0 && (
            <span className="ptab-count" data-testid="panel.tab.documents.count">
              {documents.count}
            </span>
          )}
        </button>
        <span className="grow" />
        <button
          type="button"
          className="btn btn-ghost btn-sm btn-icon"
          onClick={onClose}
          title="Close"
          aria-label="Close the panel"
          data-testid="panel.close"
        >
          <X className="icon" aria-hidden="true" />
        </button>
      </div>
      <div className={cn('panel-body', tab === 'chat' && 'chat')} role="tabpanel" data-testid="panel.body">
        {tab === 'chat' ? (
          <ProjectChat projectId={projectId} members={members} home="panel" covered={covered} />
        ) : tab === 'draft' ? (
          <DraftTab projectId={projectId} />
        ) : (
          <DocumentsTab projectId={projectId} draft={draft} documents={documents} onOpen={onOpen} />
        )}
      </div>
    </aside>
  );
}

/** The Chat tab, with its unread dot (F43). */
function ChatTab({ projectId, on, onTab }: { projectId: string; on: boolean; onTab: (tab: PanelTab) => void }) {
  const unread = useChatDot(projectId);
  return (
    <button
      type="button"
      role="tab"
      aria-selected={on}
      className={cn('ptab', on && 'on')}
      onClick={() => onTab('chat')}
      data-testid="panel.tab.chat"
    >
      Chat
      {unread && <span className="unread" role="img" aria-label="Unread reply" data-testid="panel.tab.chat.unread" />}
    </button>
  );
}

/** The panel's head, lined up with the project's on a wide window: its height, and its tab's baseline on the name's. */
function useAlignedHead(head: HTMLElement | null, wide: boolean): RefObject<HTMLDivElement | null> {
  const panelHead = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const own = panelHead.current!;
    const reset = () => {
      own.style.height = '';
      own.style.removeProperty('--tab-top');
    };
    if (!wide || head === null) {
      reset();
      return undefined;
    }
    const align = () => {
      own.style.height = `${head.offsetHeight}px`;
      const tab = own.querySelector<HTMLElement>('.ptab')!;
      const want = baselineOf(head.querySelector('h1')!) - head.getBoundingClientRect().top;
      const now = baselineOf(tab) - own.getBoundingClientRect().top;
      const pad = parseFloat(getComputedStyle(tab).paddingTop);
      own.style.setProperty('--tab-top', `${Math.max(0, pad + want - now)}px`);
    };
    align();
    const observer = new ResizeObserver(align);
    observer.observe(head);
    return () => {
      observer.disconnect();
      reset();
    };
  }, [head, wide]);
  return panelHead;
}

/** The page's y of the element's first line's baseline, measured by an empty mark put before its content and taken out again. */
function baselineOf(element: Element): number {
  const mark = document.createElement('span');
  mark.style.cssText = 'display:inline-block;width:0;height:0';
  element.prepend(mark);
  const y = mark.getBoundingClientRect().bottom;
  mark.remove();
  return y;
}
