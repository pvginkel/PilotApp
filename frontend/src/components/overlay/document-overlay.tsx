/**
 * An item's document, at its own address: off a phone in its tab, on a phone a view (F28, F97),
 * read on its own: as Done fixed it where Done did, else as it stands (F13.3), and read again as
 * the timeline is. Its head holds its title, the project, the step, the segment bar, *Unsent* or
 * *Done* (D026), and *Edited <time>* with Pilot's mark (F28.2, F28.7); its body the summary as its
 * lead, then its prose with every block answered in place, an open archive question's Archive and
 * Keep in its block's place (F5.6), then Pilot's dots while it writes
 * (F28.3), and over the text, where Pilot asked a registered document's writer about its blocks,
 * the box of the questions and the writer's reply (F52.2), which an asked block's mark goes to, as
 * the box's address opens the document at it. *Edited* and the dots tell of the text as it
 * stands, so a document read as Done fixed it has neither; its foot "Done · <stamp> · <who>", naming who did it unless it was the person, or
 * Reviewed on an open review, or *Send answers* on an open document, which closes its tab or its
 * view (F28.4), after the Cancel of a document a run of Pilot's put to the person while the run holds a
 * block of another document (F28.9). Opened at a block, it goes to the block once it draws it (F33). Its attachments stand
 * between the lead and the text, each opening at its address under the document's: off a phone a
 * tab of its own, on a phone a view over the document's, the document a link in its head (F28.3,
 * F28.5). A read that fails, or finds no document
 * of the project, reads "The document did not load" (F113), and so does a registered document
 * whose read at its run's end failed, under its head, its foot Reviewed (F85.1, ruling D1). A
 * document that is Pilot's opens read-only under the strip that says what Pilot does on it (F28.9):
 * every control drawn and taking nothing, and no foot; one awaiting its read has its head and the
 * strip over a body that says its text comes once it is read.
 */

import type { ReactNode } from 'react';
import { useParams } from '@tanstack/react-router';
import { Check } from 'lucide-react';
import { DiscussButton } from '@/components/chat/discuss-button';
import { quoteOfAttachment, quoteOfItem } from '@/components/chat/discuss-quotes';
import { AttachmentBody, AttachmentTitles } from '@/components/overlay/attachment-overlay';
import { Clarifications } from '@/components/overlay/clarification';
import { useClarificationBox } from '@/components/overlay/clarification-box';
import { DidNotLoad, Overlay } from '@/components/overlay/overlay';
import { PilotStrip } from '@/components/overlay/pilot-strip';
import { RunCancel } from '@/components/overlay/run-cancel';
import { LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import { ArchiveAnswers } from '@/components/timeline/archive-question';
import { Attachments } from '@/components/timeline/attachments';
import { DocumentParts, SegmentBar, SendAnswers, UnsentChip } from '@/components/timeline/document';
import { isUnsent } from '@/components/timeline/document-state';
import { Edited } from '@/components/timeline/item-head';
import { LockedContext } from '@/components/timeline/locked';
import { ToClarificationContext } from '@/components/timeline/to-clarification';
import { PilotWriting } from '@/components/timeline/writing';
import { useItemDocument, type ItemDocument } from '@/hooks/use-document';
import { useReviewed } from '@/hooks/use-marks';
import { useOverlayClose } from '@/hooks/use-overlay-close';
import { useArchived, type ProjectHead } from '@/hooks/use-projects';
import { usePerson } from '@/hooks/use-self';
import { attachmentIn, blocksOf, titleOf } from '@/hooks/use-timeline';
import { cn } from '@/lib/utils';

interface DocumentOverlayProps {
  projectId: string;
  /** The project's head, once read. */
  project: ProjectHead | undefined;
  documentId: string;
  /** The block it opens at. */
  block: string | null;
  /** Its attachment, shown in its place. */
  attachment: string | null;
  /** It opens at the box of Pilot's questions to its writer and the reply. */
  box: boolean;
}

export function DocumentOverlay({ projectId, project, documentId, block, attachment, box }: DocumentOverlayProps) {
  const clarification = useClarificationBox(box && attachment === null ? documentId : null);
  const { handle } = usePerson();
  const close = useOverlayClose(projectId);
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
        titles={headed && shown && <AttachmentTitles item={headed} attachment={shown} document={{ projectId, documentId }} />}
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
      strip={headed?.pilots_work && <PilotStrip itemId={headed.id} pilots={headed.pilots_work} read={item !== undefined} />}
      foot={headed && footOf(headed, handle, close)}
      onClose={close}
      bodyRef={clarification.body}
    >
      {failed ? (
        <DidNotLoad />
      ) : textless !== undefined ? (
        <Unread item={textless} />
      ) : (
        item && <Body item={item} box={clarification} />
      )}
    </Overlay>
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

/** A registered document with no text: awaiting its read, or its read failed. */
function Unread({ item }: { item: ItemDocument }) {
  if (!item.awaiting_read) return <DidNotLoad />;
  return (
    <p className="item-sub" data-testid="overlay.unread">
      Its text shows here once Pilot has read it.
    </p>
  );
}

/** `box` goes to the box of Pilot's questions to the writer, which an asked block's mark does in the overlay. */
function Body({ item, box }: { item: ItemDocument; box: ReturnType<typeof useClarificationBox> }) {
  const locked = item.pilots_work !== null;
  return (
    <LockedContext.Provider value={locked}>
      <ToClarificationContext.Provider value={box.goTo}>
        {item.summary !== null && (
          <div className="lead" data-testid="overlay.summary">
            <LinkedText text={item.summary} />
          </div>
        )}
        <Attachments item={item} inDocument />
        <Clarifications item={item} boxRef={box.box} flashing={box.flashing} onFlashed={box.onFlashed} />
        <div className={cn('sheet-doc', locked && 'locked')} data-testid="overlay.document">
          {/* An open archive question is answered Archive or Keep alone, as the timeline draws it (F5.6). */}
          {item.kind === 'archive_question' && item.done === null ? <ArchiveAnswers item={item} /> : <DocumentParts item={item} />}
        </div>
        {item.writing && !asDone(item) && <PilotWriting />}
      </ToClarificationContext.Provider>
    </LockedContext.Provider>
  );
}

/** Whether the read gives the text as Done fixed it, a person's or Pilot's (F13.3), not as it stands. */
function asDone(item: ItemDocument): boolean {
  return item.done?.cause === 'marked' || item.done?.cause === 'settled';
}

/**
 * What stands in the foot: how it was done, or what marks it done, after the Cancel where it is
 * offered; for a document that is Pilot's, nothing.
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
  if (item.pilots_work !== null) return null;
  const own = ownFoot(item, onSent);
  if (item.cancel === null) return own;
  return (
    <>
      <RunCancel itemId={item.id} cancel={item.cancel} />
      {own}
    </>
  );
}

/** What marks an open document of the person's done by its kind: Reviewed, *Send answers*, or nothing. */
function ownFoot(item: ItemDocument, onSent: () => void): ReactNode {
  if (item.kind === 'review') {
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
