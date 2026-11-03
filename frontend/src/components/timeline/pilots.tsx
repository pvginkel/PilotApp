/**
 * What Pilot does on an item that is Pilot's (F13.7), as a ghost button like Open and Discuss beside
 * it: a running work item's pulsing dot while the session doing Pilot's work on it is queued, held,
 * starting or running, Pilot's mark, then the words. Where a work item does the work, it goes to it
 * in the timeline, its title the tooltip; while the pass pre-rules, it opens the pass's session log;
 * while the pass asks the writer, the words stand still and go nowhere.
 */

import { Link, useParams } from '@tanstack/react-router';
import { Avatar } from '@/components/shared/avatar';
import type { PilotsWork } from '@/hooks/use-timeline';
import { pilotsDoingLabel } from '@/lib/utils/status-labels';

interface PilotsButtonProps {
  pilots: Pick<PilotsWork, 'doing' | 'work' | 'pulse'>;
  testId: string;
}

export function PilotsButton({ pilots, testId }: PilotsButtonProps) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const { doing, work, pulse } = pilots;
  const words = (
    <>
      {pulse && <span className="pulse" title="Pilot’s session on this is running" data-testid={`${testId}.pulse`} />}
      <Avatar who="pilot" size="xs" />
      <span>{pilotsDoingLabel(doing)}</span>
    </>
  );
  // The API names no work while the pass asks the writer.
  if (work === null) {
    return (
      <span
        className="btn btn-ghost btn-sm pilots-btn still"
        title="Pilot is working on this: it comes to you once Pilot is done"
        data-testid={testId}
        data-doing={doing}
      >
        {words}
      </span>
    );
  }
  if (doing === 'pre_ruling') {
    return (
      <Link
        to="/projects/$projectId/sessions/$sessionId"
        params={{ projectId, sessionId: work.id }}
        className="btn btn-ghost btn-sm pilots-btn"
        title={`Open the session log of Pilot’s job: ${work.title}`}
        data-testid={testId}
        data-doing={doing}
      >
        {words}
      </Link>
    );
  }
  return (
    <Link
      to="/projects/$projectId/items/$itemId"
      params={{ projectId, itemId: work.id }}
      className="btn btn-ghost btn-sm pilots-btn"
      title={`Go to the work item: ${work.title}`}
      data-testid={testId}
      data-doing={doing}
    >
      {words}
    </Link>
  );
}
