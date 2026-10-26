/**
 * The panel's Documents tab (F37): the project document first, read only (F37.4); then the
 * attachments, newest first, each with its title and its item and stamp, the files attached in one
 * call together under their folder (F37.1); then the timeline's documents and reviews, newest
 * first, each with its state, Open, *Unsent* (D026) or Done, and its stamp (F37.2). Each opens in
 * the overlay at its address. The project document's row is named "Project document" until its
 * title is read; under the headings stands nothing while the tab's read is under way, and "None
 * yet." under a list read empty; a failed read says so in the lists' place (F113).
 */

import type { ReactNode } from 'react';
import { Link } from '@tanstack/react-router';
import { BookOpen, FileText, Folder, Paperclip } from 'lucide-react';
import { Time } from '@/components/shared/time';
import { isUnsent } from '@/components/timeline/document-state';
import type { Batch, PanelRead } from '@/hooks/use-panel';
import { titleOf, type Attachment, type TimelineItem } from '@/hooks/use-timeline';

interface DocumentsTabProps {
  projectId: string;
  documents: { projectDocument: string | null; lists: PanelRead };
  /** A row was opened in the overlay. */
  onOpen: () => void;
}

export function DocumentsTab({ projectId, documents: { projectDocument, lists }, onOpen }: DocumentsTabProps) {
  return (
    <div className="docs" data-testid="panel.documents">
      <ul>
        <li>
          <Link
            to="/projects/$projectId/project-document"
            params={{ projectId }}
            className="doc-row"
            onClick={onOpen}
            data-testid="panel.project-document"
          >
            <Row icon={<FileText className="icon" aria-hidden="true" />} title={projectDocument ?? 'Project document'}>
              Project document
            </Row>
          </Link>
        </li>
      </ul>
      {lists === 'failed' ? (
        <p className="none failed" data-testid="panel.documents.failed">
          The documents did not load.
        </p>
      ) : (
        <>
          <h3>Attachments</h3>
          {lists !== 'pending' && <Attachments projectId={projectId} batches={lists.batches} onOpen={onOpen} />}
          <h3>In the timeline</h3>
          {lists !== 'pending' && <TimelineDocuments projectId={projectId} documents={lists.documents} onOpen={onOpen} />}
        </>
      )}
    </div>
  );
}

function Attachments({ projectId, batches, onOpen }: { projectId: string; batches: Batch[]; onOpen: () => void }) {
  if (batches.length === 0) {
    return (
      <p className="none" data-testid="panel.attachments.none">
        None yet. A session attaches reader’s material here: a design, a survey, a log.
      </p>
    );
  }
  return (
    <ul data-testid="panel.attachments">
      {batches.map((batch) =>
        batch.attachments.length === 1 ? (
          <li key={batch.batch}>
            <AttachmentRow projectId={projectId} item={batch.item} attachment={batch.attachments[0]} onOpen={onOpen}>
              {titleOf(batch.item)} · <Time at={batch.attachments[0].copied_at} format="stamp" />
            </AttachmentRow>
          </li>
        ) : (
          <BatchRows key={batch.batch} projectId={projectId} batch={batch} onOpen={onOpen} />
        ),
      )}
    </ul>
  );
}

function TimelineDocuments({ projectId, documents, onOpen }: { projectId: string; documents: TimelineItem[]; onOpen: () => void }) {
  if (documents.length === 0) {
    return (
      <p className="none" data-testid="panel.timeline-documents.none">
        None yet.
      </p>
    );
  }
  return (
    <ul data-testid="panel.timeline-documents">
      {documents.map((item) => (
        <li key={item.id}>
          <DocumentRow projectId={projectId} item={item} onOpen={onOpen} />
        </li>
      ))}
    </ul>
  );
}

/** A row's icon, its title, and the line under it. */
function Row({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <>
      {icon}
      <span className="t">
        <span className="title" title={title} data-testid="panel.row.title">
          {title}
        </span>
        <span className="sub" data-testid="panel.row.sub">
          {children}
        </span>
      </span>
    </>
  );
}

interface AttachmentRowProps {
  projectId: string;
  item: TimelineItem;
  attachment: Attachment;
  onOpen: () => void;
  /** The line under its title. */
  children: ReactNode;
}

/** An attachment, opening at its address under its item's (F28.5). */
function AttachmentRow({ projectId, item, attachment, onOpen, children }: AttachmentRowProps) {
  return (
    <Link
      to="/projects/$projectId/items/$itemId/attachments/$attachmentId"
      params={{ projectId, itemId: item.id, attachmentId: attachment.id }}
      className="doc-row"
      onClick={onOpen}
      data-testid="panel.attachment"
      data-attachment-id={attachment.id}
    >
      <Row icon={<Paperclip className="icon" aria-hidden="true" />} title={attachment.title}>
        {children}
      </Row>
    </Link>
  );
}

/** Files attached in one call: their folder, with their item and stamp, and each file under it by its title and file name. */
function BatchRows({ projectId, batch, onOpen }: { projectId: string; batch: Batch; onOpen: () => void }) {
  const { item, attachments } = batch;
  return (
    <li className="doc-batch" data-testid="panel.batch" data-batch={batch.batch}>
      <div className="doc-row" data-testid="panel.batch.head">
        <Row icon={<Folder className="icon" aria-hidden="true" />} title={folderOf(attachments) ?? `${attachments.length} files`}>
          {titleOf(item)} · <Time at={attachments[0].copied_at} format="stamp" />
        </Row>
      </div>
      <ul>
        {attachments.map((attachment) => (
          <li key={attachment.id}>
            <AttachmentRow projectId={projectId} item={item} attachment={attachment} onOpen={onOpen}>
              {attachment.filename}
            </AttachmentRow>
          </li>
        ))}
      </ul>
    </li>
  );
}

/**
 * The folder files attached in one call came from: the last name of the directory their sources
 * (`<environment>:<path>`) share; none where a source is not known or they share none.
 */
function folderOf(attachments: Attachment[]): string | null {
  let shared: string[] | null = null;
  for (const { source } of attachments) {
    if (source === null) return null;
    const directory = source.slice(source.indexOf(':') + 1).split('/').slice(0, -1);
    if (shared === null) shared = directory;
    else {
      let same = 0;
      while (same < shared.length && shared[same] === directory[same]) same += 1;
      shared = shared.slice(0, same);
    }
  }
  return shared?.filter((name) => name !== '').at(-1) ?? null;
}

const STATES = { open: 'Open', unsent: 'Unsent', done: 'Done' } as const;

/** A document or review of the timeline, opening at the document's address (F97). */
function DocumentRow({ projectId, item, onOpen }: { projectId: string; item: TimelineItem; onOpen: () => void }) {
  const state = item.done !== null ? 'done' : isUnsent(item) ? 'unsent' : 'open';
  const Icon = item.kind === 'review' ? BookOpen : FileText;
  return (
    <Link
      to="/projects/$projectId/documents/$documentId"
      params={{ projectId, documentId: item.id }}
      className="doc-row"
      onClick={onOpen}
      data-testid="panel.document"
      data-item-id={item.id}
      data-state={state}
    >
      <Row icon={<Icon className="icon" aria-hidden="true" />} title={titleOf(item)}>
        {STATES[state]} · <Time at={item.created_at} format="stamp" />
      </Row>
    </Link>
  );
}
