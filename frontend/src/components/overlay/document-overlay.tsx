/**
 * An item's document in the overlay, at its own address over its project's timeline (F28, F97),
 * read on its own: as Done fixed it where Done did, else as it stands (F13.3), and read again as
 * the timeline is. Its head holds its title, the project, the step, the segment bar, *Unsent* or
 * *Done* (D026), and *Edited <time>* with Pilot's mark (F28.2, F28.7); its body the summary as its
 * lead, then its prose with every block answered in place, an open archive question's Archive and
 * Keep in its block's place (F5.6), then Pilot's dots while it writes
 * (F28.3), and over the text, where Pilot asked a registered document's writer about its blocks,
 * the questions and the writer's reply (F52.2). *Edited* and the dots tell of the text as it
 * stands, so a document read as Done fixed it has neither; its foot "Done · <stamp> · <who>", naming who did it unless it was the person, or
 * Reviewed on an open review, or *Send answers* on an open document, which closes the overlay
 * (F28.4). Opened at a block, it goes to the block once it draws it (F33). Its attachments stand
 * between the lead and the text, each opening, at its address under the document's, in place of
 * the document, with an arrow back to it (F28.3, F28.5). A read that fails, or finds no document
 * of the project, reads "The document did not load" (F113), and so does a registered document
 * with no text — before its file is read at its run's end, or after that read failed — under its
 * head, its foot Reviewed once that read was made (F85.1, ruling D1).
 */

import type { ReactNode } from 'react';
import { Link, useNavigate, useParams } from '@tanstack/react-router';
import { ArrowLeft, Check } from 'lucide-react';
import { DiscussButton } from '@/components/chat/discuss-button';
import { quoteOfAttachment, quoteOfItem } from '@/components/chat/discuss-quotes';
import { AttachmentBody, AttachmentTitles } from '@/components/overlay/attachment-overlay';
import { Clarifications } from '@/components/overlay/clarification';
import { DidNotLoad, Overlay } from '@/components/overlay/overlay';
import { LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import { ArchiveAnswers } from '@/components/timeline/archive-question';
import { Attachments } from '@/components/timeline/attachments';
import { DocumentParts, SegmentBar, SendAnswers, UnsentChip } from '@/components/timeline/document';
import { isUnsent } from '@/components/timeline/document-state';
import { Edited } from '@/components/timeline/item-head';
import { PilotWriting } from '@/components/timeline/writing';
import { useItemDocument, type ItemDocument } from '@/hooks/use-document';
import { useReviewed } from '@/hooks/use-marks';
import { useArchived, type ProjectHead } from '@/hooks/use-projects';
import { usePerson } from '@/hooks/use-self';
import { attachmentIn, blocksOf, titleOf } from '@/hooks/use-timeline';

interface DocumentOverlayProps {
  projectId: string;
  /** The project's head, once read. */
  project: ProjectHead | undefined;
  documentId: string;
  /** The block it opens at. */
  block: string | null;
  /** Its attachment, shown in its place. */
  attachment: string | null;
}

export function DocumentOverlay({ projectId, project, documentId, block, attachment }: DocumentOverlayProps) {
  const navigate = useNavigate();
  const { handle } = usePerson();
  const close = () => void navigate({ to: '/projects/$projectId', params: { projectId } });
  const { data, error } = useItemDocument(documentId);
  // An address may name an item of another project, or the opening, which has no text.
  const own = data !== undefined && data.project_id === projectId ? data : undefined;
  const item = own !== undefined && own.body !== null ? own : undefined;
  const textless = own !== undefined && own.body === null && own.file_name !== null ? own : undefined;
  const headed = item ?? textless;
  const failed = error !== null || (data !== undefined && headed === undefined);
  if (attachment !== null) {
    const shown = headed && attachmentIn(headed, attachment);
    return (
      <Overlay
        showing={`attachment ${attachment}`}
        back={<Back projectId={projectId} documentId={documentId} />}
        titles={headed && shown && <AttachmentTitles item={headed} attachment={shown} />}
        discuss={shown && <DiscussButton quote={quoteOfAttachment(shown)} testId="overlay.discuss" />}
        foot={null}
        onClose={close}
      >
        {failed || (headed !== undefined && shown === undefined) ? <DidNotLoad /> : shown && <AttachmentBody attachment={shown} />}
      </Overlay>
    );
  }
  return (
    <Overlay
      showing={documentId}
      at={block === null ? null : { item: documentId, block }}
      titles={headed && <Titles item={headed} project={project} />}
      discuss={headed && <DiscussButton quote={quoteOfItem(headed)} testId="overlay.discuss" />}
      foot={headed && footOf(headed, handle, close)}
      onClose={close}
    >
      {failed || textless !== undefined ? <DidNotLoad /> : item && <Body item={item} />}
    </Overlay>
  );
}

/** An attachment's way back to its document: an arrow, no label. */
function Back({ projectId, documentId }: { projectId: string; documentId: string }) {
  return (
    <Link
      to="/projects/$projectId/documents/$documentId"
      params={{ projectId, documentId }}
      className="btn btn-ghost btn-sm btn-icon back"
      title="Back to the document"
      aria-label="Back"
      data-testid="overlay.back"
    >
      <ArrowLeft className="icon" aria-hidden="true" />
    </Link>
  );
}

function Titles({ item, project }: { item: ItemDocument; project: ProjectHead | undefined }) {
  return (
    <>
      <h2 title={titleOf(item)} data-testid="overlay.title">
        <LinkedText text={titleOf(item)} />
      </h2>
      <div className="sub" data-testid="overlay.sub">
        {project && (
          <span data-testid="overlay.project">
            <LinkedText text={project.name ?? 'New project'} />
          </span>
        )}
        {item.step !== null && (
          <>
            <span>·</span>
            <span className="mono" data-testid="overlay.step">
              <LinkedText text={item.step.title} />
            </span>
          </>
        )}
        {blocksOf(item).length > 0 && <SegmentBar item={item} />}
        {item.done !== null ? (
          <span className="chip" data-testid="overlay.done-chip">
            <Check className="icon" aria-hidden="true" />
            Done
          </span>
        ) : (
          isUnsent(item) && <UnsentChip />
        )}
        {item.edited_at !== null && !asDone(item) && <Edited at={item.edited_at} />}
      </div>
    </>
  );
}

function Body({ item }: { item: ItemDocument }) {
  return (
    <>
      {item.summary !== null && (
        <div className="lead" data-testid="overlay.summary">
          <LinkedText text={item.summary} />
        </div>
      )}
      <Attachments item={item} inDocument />
      <Clarifications item={item} />
      <div className="sheet-doc" data-testid="overlay.document">
        {/* An open archive question is answered Archive or Keep alone, as the timeline draws it (F5.6). */}
        {item.kind === 'archive_question' && item.done === null ? <ArchiveAnswers item={item} /> : <DocumentParts item={item} />}
      </div>
      {item.writing && !asDone(item) && <PilotWriting />}
    </>
  );
}

/** Whether the read gives the text as Done fixed it, a person's or Pilot's (F13.3), not as it stands. */
function asDone(item: ItemDocument): boolean {
  return item.done?.cause === 'marked' || item.done?.cause === 'settled';
}

/**
 * What stands in the foot: how it was done, or what marks it done; for a one-ask item, a notice
 * or a registered document awaiting its read, nothing.
 */
function footOf(item: ItemDocument, myHandle: string, onSent: () => void): ReactNode {
  if (item.done !== null) {
    const { at, by } = item.done;
    const who = by === null || (by.kind === 'person' && by.handle === myHandle) ? null : by.kind === 'agent' ? 'Pilot' : by.name;
    return (
      <span className="state" data-testid="overlay.done">
        <Check className="icon" aria-hidden="true" /> Done · <Time at={at} format="stamp" testId="overlay.done.time" />
        {who !== null && ` · ${who}`}
      </span>
    );
  }
  if (item.kind === 'review') {
    if (item.awaiting_read) return null;
    return (
      <>
        <span className="grow" />
        <Reviewed item={item} />
      </>
    );
  }
  if (item.kind === 'document') {
    return (
      <>
        <span className="grow" />
        <SendAnswers item={item} onSent={onSent} />
      </>
    );
  }
  return null;
}

/** A review's one mark: read, nothing to answer (F25.2); disabled while the project is archived (D012). */
function Reviewed({ item }: { item: ItemDocument }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const { mark, pending } = useReviewed(item.id);
  const archived = useArchived(projectId);
  return (
    <button type="button" className="btn btn-primary" onClick={mark} disabled={pending || archived} data-testid="overlay.reviewed">
      <Check className="icon" aria-hidden="true" />
      Reviewed
    </button>
  );
}
