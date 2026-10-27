/**
 * An attachment in the overlay (F28.5), reader's material and never an item (F36). Its head is its
 * clip and title over "Attachment of “<item>”", with, opened from the item's document, an arrow
 * back to it, with no label, and Discuss, quoting it by its path in the project's folder (F39.1). Its body goes by its type: Markdown as a read-only document, its
 * front matter left out and its fenced asks plain code, never blocks; a raster image inline from
 * its stream; an SVG inline only as an image, which runs no script, its text read from the stream
 * that serves it as a download; other text in a monospace block; anything else its title, its
 * file's name and size, and Download. Opened at its address under its item's, it lies over the
 * timeline where the timeline stands. At its address under its project's, it is found wherever it
 * hangs: on nothing, as a draft's material does until Create project (F36.6), its head's line then
 * "Attachment of the draft", or on an item.
 */

import { useNavigate } from '@tanstack/react-router';
import { Download, Paperclip } from 'lucide-react';
import { DiscussButton } from '@/components/chat/discuss-button';
import { quoteOfAttachment } from '@/components/chat/discuss-quotes';
import { DidNotLoad, Overlay } from '@/components/overlay/overlay';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { attachmentUrl, useAttachmentText } from '@/hooks/use-attachment';
import { attachmentIn, hungById, titleOf, type Attachment, type TimelineItem } from '@/hooks/use-timeline';
import { useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';

/** An attachment of an item of the project's timeline, at the attachment's address under the item's. */
export function ItemAttachmentOverlay({ projectId, itemId, attachmentId }: { projectId: string; itemId: string; attachmentId: string }) {
  const navigate = useNavigate();
  const close = () => void navigate({ to: '/projects/$projectId', params: { projectId } });
  // The timeline's read, which the timeline under it reports.
  const { data, error } = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } });
  const item = data?.items.find((each) => each.id === itemId);
  const attachment = item && attachmentIn(item, attachmentId);
  const failed = error !== null || (data !== undefined && attachment === undefined);
  return (
    <Overlay
      showing={`attachment ${attachmentId}`}
      titles={item && attachment && <AttachmentTitles item={item} attachment={attachment} />}
      discuss={attachment && <DiscussButton quote={quoteOfAttachment(attachment)} testId="overlay.discuss" />}
      foot={null}
      onClose={close}
    >
      {failed ? <DidNotLoad /> : attachment && <AttachmentBody attachment={attachment} />}
    </Overlay>
  );
}

/** An attachment of the project, at its address under the project's, wherever it hangs. */
export function ProjectAttachmentOverlay({ projectId, attachmentId }: { projectId: string; attachmentId: string }) {
  const navigate = useNavigate();
  const close = () => void navigate({ to: '/projects/$projectId', params: { projectId } });
  const { data, error } = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } });
  const hung = data && hungById(data, attachmentId);
  const failed = error !== null || (data !== undefined && hung === undefined);
  return (
    <Overlay
      showing={`attachment ${attachmentId}`}
      titles={hung && <AttachmentTitles item={hung.item} attachment={hung.attachment} />}
      discuss={hung && <DiscussButton quote={quoteOfAttachment(hung.attachment)} testId="overlay.discuss" />}
      foot={null}
      onClose={close}
    >
      {failed ? <DidNotLoad /> : hung && <AttachmentBody attachment={hung.attachment} />}
    </Overlay>
  );
}

/** Its title over what it hangs on: its item, or none, a draft's material. */
export function AttachmentTitles({ item, attachment }: { item: TimelineItem | null; attachment: Attachment }) {
  return (
    <>
      <h2 title={attachment.title} data-testid="overlay.title">
        <Paperclip className="icon" aria-hidden="true" /> {attachment.title}
      </h2>
      <div className="sub" data-testid="overlay.sub">
        {item === null ? (
          <span>Attachment of the draft</span>
        ) : (
          <span>
            Attachment of “<LinkedText text={titleOf(item)} />”
          </span>
        )}
      </div>
    </>
  );
}

/** The raster images the stream serves inline as themselves (attachment_service.py's `RASTER_IMAGES`). */
const RASTER_IMAGES = new Set(['image/avif', 'image/bmp', 'image/gif', 'image/jpeg', 'image/png', 'image/webp']);

type View = 'markdown' | 'image' | 'svg' | 'text' | 'file';

function viewOf(contentType: string): View {
  const essence = contentType.split(';')[0].trim().toLowerCase();
  if (essence === 'text/markdown') return 'markdown';
  if (RASTER_IMAGES.has(essence)) return 'image';
  if (essence === 'image/svg+xml') return 'svg';
  // The stream serves every text but HTML as plain text.
  if (essence.startsWith('text/') && essence !== 'text/html') return 'text';
  return 'file';
}

export function AttachmentBody({ attachment }: { attachment: Attachment }) {
  const view = viewOf(attachment.content_type);
  return (
    <div className="attachment-view" data-testid="overlay.attachment" data-view={view}>
      {view === 'image' ? (
        <img className="attachment-image" src={attachmentUrl(attachment.id)} alt={attachment.title} data-testid="overlay.attachment.image" />
      ) : view === 'file' ? (
        <FileCard attachment={attachment} />
      ) : (
        <TextView attachment={attachment} view={view} />
      )}
    </div>
  );
}

/** What is read as text: Markdown, an SVG, plain text. */
function TextView({ attachment, view }: { attachment: Attachment; view: 'markdown' | 'svg' | 'text' }) {
  const { data, error } = useAttachmentText(attachment.id);
  if (error !== null) return <DidNotLoad />;
  if (data === undefined) return null;
  if (view === 'markdown') return <Markdown text={withoutFrontMatter(data)} />;
  if (view === 'svg') {
    return (
      <img
        className="attachment-image"
        src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(data)}`}
        alt={attachment.title}
        data-testid="overlay.attachment.image"
      />
    );
  }
  return (
    <pre className="attachment-text" data-testid="overlay.attachment.text">
      {data}
    </pre>
  );
}

const FRONT_MATTER = /^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/;

/** A Markdown file's text less its front matter, which is no reading matter. */
const withoutFrontMatter = (text: string) => text.replace(FRONT_MATTER, '');

function FileCard({ attachment }: { attachment: Attachment }) {
  return (
    <div className="attachment-file">
      <Paperclip className="icon" aria-hidden="true" />
      <span className="t">
        <span className="title" data-testid="overlay.attachment.file-title">
          {attachment.title}
        </span>
        <span className="sub" data-testid="overlay.attachment.size">
          {attachment.filename} · {sizeOf(attachment.size)}
        </span>
      </span>
      <button
        type="button"
        className="btn"
        onClick={() => window.open(attachmentUrl(attachment.id))}
        title={`Download ${attachment.filename}`}
        data-testid="overlay.attachment.download"
      >
        <Download className="icon" aria-hidden="true" />
        Download
      </button>
    </div>
  );
}

const SIZE = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 });

function sizeOf(bytes: number): string {
  if (bytes < 1024) return bytes === 1 ? '1 byte' : `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${SIZE.format(bytes / 1024)} KB`;
  return `${SIZE.format(bytes / (1024 * 1024))} MB`;
}
