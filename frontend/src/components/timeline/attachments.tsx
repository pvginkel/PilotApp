/**
 * The attachments hung on an item, reader's material (F17.5, F36): on an open item, a chip per
 * attachment, its clip and its title; on a done line, an indicator (F13.6), a document icon opening
 * the one, a documents icon opening a menu of several. Each opens in the overlay's attachment view
 * (F28.5) at its address under its item's, or, in the document's overlay, under the document's,
 * which gives it its way back.
 */

import type { ReactNode } from 'react';
import { Link, useNavigate, useParams } from '@tanstack/react-router';
import { File, Files, Paperclip } from 'lucide-react';
import { Menu, MenuItem } from '@/components/shared/menu';
import type { Attachment, TimelineItem } from '@/hooks/use-timeline';

interface AttachmentsProps {
  item: TimelineItem;
  /** Shown in the item's document, in the overlay. */
  inDocument?: boolean;
}

export function Attachments({ item, inDocument = false }: AttachmentsProps) {
  if (item.attachments.length === 0) return null;
  return (
    <div className="attachments" data-testid="timeline.attachments">
      {item.attachments.map((attachment) => (
        <AttachmentLink
          key={attachment.id}
          item={item}
          attachment={attachment}
          inDocument={inDocument}
          className="btn btn-sm"
          title={attachment.title}
          testId="timeline.attachment"
        >
          <Paperclip className="icon" aria-hidden="true" />
          {attachment.title}
        </AttachmentLink>
      ))}
    </div>
  );
}

/** A done line's indicator: the one attachment, or a menu of several. */
export function LineAttachments({ item }: { item: TimelineItem }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const navigate = useNavigate();
  const { attachments } = item;
  if (attachments.length === 0) return null;
  if (attachments.length === 1) {
    const [attachment] = attachments;
    return (
      <AttachmentLink
        item={item}
        attachment={attachment}
        className="btn btn-ghost btn-sm btn-icon"
        title={`Open the attachment: ${attachment.title}`}
        label="Attachment"
        testId="timeline.line.attachment"
      >
        <File className="icon" aria-hidden="true" />
      </AttachmentLink>
    );
  }
  return (
    <Menu
      label="Attachments"
      testId="timeline.line.attachments.menu"
      trigger={({ open, toggle }) => (
        <button
          type="button"
          className="btn btn-ghost btn-sm btn-icon"
          onClick={toggle}
          aria-expanded={open}
          aria-haspopup="menu"
          title={`${attachments.length} attachments`}
          aria-label="Attachments"
          data-testid="timeline.line.attachments"
        >
          <Files className="icon" aria-hidden="true" />
        </button>
      )}
    >
      {attachments.map((attachment) => (
        <MenuItem
          key={attachment.id}
          icon={Paperclip}
          onSelect={() =>
            void navigate({
              to: '/projects/$projectId/items/$itemId/attachments/$attachmentId',
              params: { projectId, itemId: item.id, attachmentId: attachment.id },
            })
          }
          testId="timeline.line.attachments.item"
        >
          {attachment.title}
        </MenuItem>
      ))}
    </Menu>
  );
}

interface AttachmentLinkProps {
  item: TimelineItem;
  attachment: Attachment;
  inDocument?: boolean;
  className: string;
  title: string;
  label?: string;
  testId: string;
  children: ReactNode;
}

function AttachmentLink({ item, attachment, inDocument = false, className, title, label, testId, children }: AttachmentLinkProps) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const shared = { className, title, 'aria-label': label, 'data-testid': testId, 'data-attachment-id': attachment.id };
  return inDocument ? (
    <Link
      to="/projects/$projectId/documents/$documentId/attachments/$attachmentId"
      params={{ projectId, documentId: item.id, attachmentId: attachment.id }}
      {...shared}
    >
      {children}
    </Link>
  ) : (
    <Link
      to="/projects/$projectId/items/$itemId/attachments/$attachmentId"
      params={{ projectId, itemId: item.id, attachmentId: attachment.id }}
      {...shared}
    >
      {children}
    </Link>
  );
}
