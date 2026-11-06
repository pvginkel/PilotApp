/**
 * The desktop's tab line (F28.8; the mockup's `renderDocTabs()`, `.doc-tabs`), the project head's
 * last row while a document is open, hidden once the last one closes: the timeline first, a draft's
 * definition chat in its place, never closed; then a tab per document in the order they opened,
 * each with its icon, its title cut short to the tab's widths and whole in its tooltip, and its
 * cross, the middle button closing it too; *Close all* at the line's far right. Where the tabs do
 * not fit, the line scrolls, the tab showing scrolled into it. The line's model is
 * `use-doc-tabs.ts`.
 */

import { useLayoutEffect, useRef, type MouseEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { flushSync } from 'react-dom';
import { BookOpen, CopyX, FileText, List, MessageSquare, NotebookText, Paperclip, X, type LucideIcon } from 'lucide-react';
import { attachmentTextQuery } from '@/hooks/use-attachment';
import { TIMELINE, type TabLine } from '@/hooks/use-doc-tabs';
import { hungById, titleOf } from '@/hooks/use-timeline';
import {
  useGetItemsDocumentByItemId,
  useGetProjectsDraftByProjectId,
  useGetProjectsHandbookByProjectId,
  useGetProjectsTimelineByProjectId,
} from '@/lib/api/generated/hooks';
import type { DocTab } from '@/lib/browser-state';
import { cn } from '@/lib/utils';

interface DocTabsProps {
  projectId: string;
  /** The project is a draft: its first tab is its definition chat. */
  draft: boolean;
  line: TabLine;
}

export function DocTabs({ projectId, draft, line }: DocTabsProps) {
  const row = useRef<HTMLDivElement>(null);
  const { tabs, on } = line;
  useLayoutEffect(() => {
    const element = row.current;
    const shown = element?.querySelector<HTMLElement>('.dtab.on');
    if (!element || !shown) return;
    if (shown.offsetLeft < element.scrollLeft || shown.offsetLeft + shown.offsetWidth > element.scrollLeft + element.clientWidth) {
      element.scrollLeft = shown.offsetLeft - (element.clientWidth - shown.offsetWidth) / 2;
    }
  }, [on, tabs.length]);
  // A cross takes its tab away under the focus: the tab showing then has it.
  const close = (key: string) => {
    flushSync(() => line.close(key));
    row.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus();
  };
  if (tabs.length === 0) return null;
  const First = draft ? MessageSquare : List;
  const timelineOn = on === TIMELINE;
  return (
    <nav className="doc-tabs" aria-label="Open documents" data-testid="doc-tabs">
      <div ref={row} className="doc-tabs-row" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={timelineOn}
          className={cn('dtab first', timelineOn && 'on')}
          onClick={() => line.show(null)}
          data-testid="doc-tabs.first"
        >
          <First className="icon" aria-hidden="true" />
          <span className="t">{draft ? 'Chat' : 'Timeline'}</span>
        </button>
        {tabs.map((tab) => (
          <Tab
            key={tab.key}
            projectId={projectId}
            tab={tab}
            on={tab.key === on}
            onShow={() => line.show(tab)}
            onClose={() => close(tab.key)}
          />
        ))}
      </div>
      <button
        type="button"
        className="btn btn-ghost btn-sm btn-icon close-all"
        onClick={line.closeAll}
        title="Close all"
        aria-label="Close all documents"
        data-testid="doc-tabs.close-all"
      >
        <CopyX className="icon" aria-hidden="true" />
      </button>
    </nav>
  );
}

interface TabProps {
  projectId: string;
  tab: DocTab;
  on: boolean;
  onShow: () => void;
  onClose: () => void;
}

/** A document's tab, by what it shows. */
function Tab(props: TabProps) {
  switch (props.tab.kind) {
    case 'document':
      return <DocumentTab {...props} />;
    case 'attachment':
      return <AttachmentTab {...props} />;
    case 'handbook':
      return <HandbookTab {...props} />;
    case 'project-document':
      return <ProjectDocumentTab {...props} />;
    default: {
      const unknown: never = props.tab.kind;
      return unknown;
    }
  }
}

function DocumentTab(props: TabProps) {
  const { data } = useGetItemsDocumentByItemId({ path: { item_id: props.tab.id! } });
  // An address may name an item of another project.
  const own = data !== undefined && data.project_id === props.projectId ? data : undefined;
  return <TabFace {...props} title={own === undefined ? 'Document' : titleOf(own)} icon={own?.kind === 'review' ? BookOpen : FileText} />;
}

function AttachmentTab(props: TabProps) {
  const { data } = useGetProjectsTimelineByProjectId({ path: { project_id: props.projectId } });
  // Fetching nothing, it keeps the text its body reads cached while another tab shows, and at its
  // document's address `KeptDocument` the document: the tab's scroll is set back once, as its body
  // mounts.
  useQuery({ ...attachmentTextQuery(props.tab.id!), enabled: false });
  const hung = data && hungById(data, props.tab.id!);
  return (
    <>
      {props.tab.documentId !== undefined && <KeptDocument id={props.tab.documentId} />}
      <TabFace {...props} title={hung?.attachment.title ?? 'Attachment'} icon={Paperclip} />
    </>
  );
}

function KeptDocument({ id }: { id: string }) {
  useGetItemsDocumentByItemId({ path: { item_id: id } }, { enabled: false });
  return null;
}

function HandbookTab(props: TabProps) {
  const { data } = useGetProjectsHandbookByProjectId({ path: { project_id: props.projectId } });
  return <TabFace {...props} title={data?.title ?? 'Handbook'} icon={NotebookText} />;
}

function ProjectDocumentTab(props: TabProps) {
  const { data } = useGetProjectsDraftByProjectId({ path: { project_id: props.projectId } });
  return <TabFace {...props} title={data?.title ?? 'Project document'} icon={FileText} />;
}

function TabFace({ tab, on, onShow, onClose, title, icon: Icon }: TabProps & { title: string; icon: LucideIcon }) {
  // The middle button's press scrolls nothing; its click closes the tab, as a browser's does.
  const onMouseDown = (event: MouseEvent) => {
    if (event.button === 1) event.preventDefault();
  };
  const onAuxClick = (event: MouseEvent) => {
    if (event.button !== 1) return;
    event.preventDefault();
    onClose();
  };
  return (
    <div
      className={cn('dtab', on && 'on')}
      title={title}
      onMouseDown={onMouseDown}
      onAuxClick={onAuxClick}
      data-testid="doc-tabs.tab"
      data-tab={tab.key}
    >
      <button type="button" className="dtab-main" role="tab" aria-selected={on} onClick={onShow} data-testid="doc-tabs.tab.show">
        <Icon className="icon" aria-hidden="true" />
        <span className="t" data-testid="doc-tabs.tab.title">
          {title}
        </span>
      </button>
      <button type="button" className="dtab-x" onClick={onClose} title="Close" aria-label={`Close ${title}`} data-testid="doc-tabs.tab.close">
        <X className="icon" aria-hidden="true" />
      </button>
    </div>
  );
}
