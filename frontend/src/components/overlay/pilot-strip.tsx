/**
 * The strip under an opened document's head while the document is Pilot's (F28.9), gold as the gold
 * bar is: Pilot's mark, what Pilot does on it in a sentence, linking the work item doing it or the
 * run's document awaiting the person's answer, and *Stop and take over* while something of Pilot's
 * on it runs. The take-over stops, by the person, what holds the document, and the document is
 * theirs on the read that follows it; a refusal is the query client's toast, the API's words. Its
 * form events are `overlay.take-over`'s. While the document awaits its read, a read one waits on
 * another document of its run, or the run holding its blocks waits on the person, there is no Stop.
 */

import { Link, useParams } from '@tanstack/react-router';
import { Square } from 'lucide-react';
import { Avatar } from '@/components/shared/avatar';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import type { PilotsWork } from '@/hooks/use-timeline';
import { usePostItemsTakeOverByItemId } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';
import { pilotsStripWords } from '@/lib/utils/status-labels';

const FORM = 'overlay.take-over';

interface PilotStripProps {
  itemId: string;
  pilots: PilotsWork;
  /** Whether the document has a text. */
  read: boolean;
}

export function PilotStrip({ itemId, pilots, read }: PilotStripProps) {
  const { before, after } = pilotsStripWords(pilots.doing, read);
  return (
    <div className="pilot-strip" data-testid="overlay.pilot-strip" data-doing={pilots.doing}>
      <Avatar who="pilot" size="xs" />
      <span className="grow" data-testid="overlay.pilot-strip.text">
        {before}
        <Linked pilots={pilots} />
        {after}
      </span>
      {stops(pilots.doing) && <TakeOver itemId={itemId} />}
    </div>
  );
}

/** What the sentence links: the work item doing it, or the run's document awaiting the person's answer. */
function Linked({ pilots }: { pilots: PilotsWork }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const replace = useTabReplace();
  const { doing, work, asked_in: askedIn } = pilots;
  if (doing === 'waiting_on_answer' && askedIn !== null) {
    return (
      <Link
        to="/projects/$projectId/documents/$documentId"
        params={{ projectId, documentId: askedIn.id }}
        replace={replace}
        className="link"
        data-testid="overlay.pilot-strip.link"
      >
        {askedIn.title}
      </Link>
    );
  }
  if ((doing === 'doing' || doing === 'researching') && work !== null) {
    return (
      <Link
        to="/projects/$projectId/items/$itemId"
        params={{ projectId, itemId: work.id }}
        replace={replace}
        className="link"
        data-testid="overlay.pilot-strip.link"
      >
        {work.title}
      </Link>
    );
  }
  return null;
}

/** Whether the strip offers *Stop and take over*: while something of Pilot's on the document runs. */
function stops(doing: PilotsWork['doing']): boolean {
  switch (doing) {
    case 'pre_ruling':
    case 'asking_writer':
    case 'doing':
    case 'researching':
      return true;
    case 'awaiting_run':
    case 'waiting_on_answer':
      return false;
    default: {
      const unknown: never = doing;
      throw new Error(`Pilot doing ${String(unknown)} has no strip`);
    }
  }
}

function TakeOver({ itemId }: { itemId: string }) {
  const takeOver = usePostItemsTakeOverByItemId();
  const fields = { item: itemId };
  const take = () => {
    trackFormSubmit(FORM, fields);
    takeOver.mutate(
      { path: { item_id: itemId } },
      {
        onSuccess: () => trackFormSuccess(FORM, fields),
        onError: () => trackFormError(FORM, fields),
      },
    );
  };
  return (
    <button
      type="button"
      className="gold-btn"
      onClick={take}
      // From the click until the document is read back as the person's, which takes the strip away.
      disabled={takeOver.isPending || takeOver.isSuccess}
      title="Stop Pilot’s work on it: the document is yours then"
      data-testid="overlay.pilot-strip.stop"
    >
      <Square className="icon" aria-hidden="true" />
      Stop and take over
    </button>
  );
}
