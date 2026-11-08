/**
 * Pilot's job on the item it follows from (F59.1; the mockup's `jobOn()`), every job but the setup,
 * which keeps a line of its own: while it is queued or runs, F13.7's ghost button, the pulsing dot,
 * Pilot's mark and the job's title; failed or stopped, the same button without the dot in the
 * destructive colour, saying so, with Retry beside it while the job offers it, disabled while the
 * project is archived (D012); once it has ended, Pilot's mark without the avatar's circle, an icon
 * button. Each opens the job's session log, whose tail says what these forms have no room for: why
 * it is held, the stop's cause, the error. A done line draws the ended mark first among its actions
 * and the other forms at its end beside the time, on a phone in a row under its title (F13.7,
 * F13.8); an open card's head draws every form after its time, an opened document's head and a
 * worker's run's session log's among its buttons (F28.10); a phone's menu of a line with nothing
 * behind it offers the job as a row (F13.9).
 */

import { useRef } from 'react';
import { Link } from '@tanstack/react-router';
import { RotateCw } from 'lucide-react';
import { Avatar } from '@/components/shared/avatar';
import { PILOT_MARK } from '@/components/shared/pilot-mark';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import { useShownProject } from '@/hooks/use-project-address';
import { useArchived } from '@/hooks/use-projects';
import type { TimelineItem } from '@/hooks/use-timeline';
import { offersRetry, useRetry } from '@/hooks/use-work-acts';
import { cn } from '@/lib/utils';
import { jobForm, jobHaltLabel } from '@/lib/utils/status-labels';

type Job = NonNullable<TimelineItem['job']>;

interface JobProps {
  job: Job;
  /** The test id of its button, its dot's and its Retry's under it: the timeline's by default. */
  testId?: string;
}

/** The job in a head, in whichever form it stands. */
export function JobOn({ job, testId }: JobProps) {
  return jobForm(job.work) === 'ended' ? <JobMark job={job} testId={testId} /> : <JobButton job={job} testId={testId} />;
}

/** The job's button while it is queued or runs, or once it failed or stopped, and then its Retry. */
export function JobButton({ job, testId = 'timeline.job' }: JobProps) {
  const { address } = useShownProject();
  const replace = useTabReplace();
  const button = useRef<HTMLAnchorElement>(null);
  const form = jobForm(job.work);
  const halted = form === 'failed' || form === 'stopped' ? form : null;
  return (
    <span className="pilots-slot">
      <Link
        ref={button}
        to="/projects/$address/sessions/$sessionId"
        params={{ address, sessionId: job.id }}
        replace={replace}
        className={cn('btn btn-ghost btn-sm pilots-btn job-btn', halted !== null && 'halted')}
        title={`Pilot’s job on this ${halted ?? 'is under way'}: open its session log`}
        data-testid={testId}
        data-form={form}
        data-state={job.work.state}
      >
        {halted === null && <span className="pulse" title="Pilot’s job on this is under way" data-testid={`${testId}.pulse`} />}
        <Avatar who="pilot" size="xs" />
        <span className="job-title">{job.title}</span>
        {halted !== null && (
          <>
            {/* A space between the flex items, for the words' sake, which the layout leaves out. */}{' '}
            <span>· {jobHaltLabel(halted)}</span>
          </>
        )}
      </Link>
      {halted !== null && offersRetry(job.work) && <Retry job={job} testId={`${testId}.retry`} onLanded={() => button.current?.focus()} />}
    </span>
  );
}

/** The ended job's mark, an icon button among a line's actions or in a head. */
export function JobMark({ job, testId = 'timeline.job' }: JobProps) {
  const { address } = useShownProject();
  const replace = useTabReplace();
  return (
    <Link
      to="/projects/$address/sessions/$sessionId"
      params={{ address, sessionId: job.id }}
      replace={replace}
      className="btn btn-ghost btn-sm btn-icon job-mark"
      title={`Pilot’s job on this: ${job.title}. Open its session log`}
      aria-label={`Pilot’s job: ${job.title}`}
      data-testid={testId}
      data-form="ended"
      data-state={job.work.state}
    >
      <PilotIcon />
    </Link>
  );
}

/** The job as a row of a phone's line menu, Pilot's mark and its title, opening its session log. */
export function JobMenuRow({ job, onOpen }: { job: Job; onOpen: () => void }) {
  const { address } = useShownProject();
  return (
    <Link
      to="/projects/$address/sessions/$sessionId"
      params={{ address, sessionId: job.id }}
      role="menuitem"
      className="btn btn-ghost btn-sm"
      onClick={onOpen}
      data-testid="timeline.line.menu.job"
    >
      <PilotIcon />
      {job.title}
    </Link>
  );
}

/**
 * Retry, placing a fresh job for the same trigger, which the item then shows. Pressed from the
 * keyboard, the focus goes to the job's button once Retry, gone with the retried job, has left it
 * nowhere.
 */
function Retry({ job, testId, onLanded }: { job: Job; testId: string; onLanded: () => void }) {
  const { id: projectId } = useShownProject();
  const { act, pending } = useRetry(job.id);
  const archived = useArchived(projectId);
  const self = useRef<HTMLButtonElement>(null);
  return (
    <button
      ref={self}
      type="button"
      className="btn btn-ghost btn-sm job-retry"
      disabled={pending || archived}
      onClick={(event) => {
        const pressed = document.activeElement === event.currentTarget;
        void act().then((work) => {
          const focused = document.activeElement;
          if (work !== null && pressed && (focused === null || focused === document.body || focused === self.current)) onLanded();
        });
      }}
      data-testid={testId}
    >
      <RotateCw className="icon" aria-hidden="true" />
      Retry
    </button>
  );
}

/** Pilot's mark without the avatar's circle, at an icon's size. */
function PilotIcon() {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PILOT_MARK.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
