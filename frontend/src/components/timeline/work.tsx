/**
 * An open work item on the timeline (F26): a session Pilot started, updated in place as the
 * server's `work_moved` carries it (F80.2). Its head has the env chip, opening the environment in
 * KubeCoder, once its start has one, and "running N min" with a pulse while its turn runs (F26.1,
 * F12). Under its title is its one line (F26.2): the server's own words while its session comes
 * up, or comes back while its environment restarts; the working state and the latest step while
 * it runs; why the gate holds its start; "Stopped · <time>" with the cause of a stop made
 * elsewhere; the error a failed start or a turn ended in error left, shown as a stopped one is
 * (F125). Its Session log opens the session's records in the overlay (F26.3, F69). Stop, while it
 * runs, starts or is held, asks first in its actions' place, Esc dismissing the question; Resume,
 * once it stopped or failed, carries it on (F67), disabled while the project is archived, as its
 * head's switch is (D012). Pilot's own work, a background job such as the setup, has no env chip
 * and no Stop or Resume, its session log alone (F26.3, F59.1). Once this browser's Stop or Resume
 * swaps the two, the keyboard focus on the button that went goes to the other's resting button,
 * Resume or Stop; a swap another browser's act made moves no focus.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link, useParams } from '@tanstack/react-router';
import { CircleAlert, Play, ScrollText, Square } from 'lucide-react';
import { WorkingCue } from '@/components/chat/working-cue';
import { EnvironmentLink, LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import { ItemHead } from '@/components/timeline/item-head';
import { useNow } from '@/hooks/use-now';
import { useArchived } from '@/hooks/use-projects';
import { titleOf, type TimelineItem } from '@/hooks/use-timeline';
import { RESUMABLE, STOPPABLE, useResume, useStop } from '@/hooks/use-work-acts';
import type { components } from '@/lib/api/generated/types';
import { useEscape } from '@/lib/keys';
import { workLine } from '@/lib/utils/status-labels';

type Work = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema'];

/** How often "running N min" is counted again, in milliseconds. */
const TICK = 15_000;

type Actions = 'stop' | 'resume';

/** The actions a session's state offers: Stop, Resume, or neither. */
const actionsOf = (state: Work['state']): Actions | null =>
  STOPPABLE.includes(state) ? 'stop' : RESUMABLE.includes(state) ? 'resume' : null;

export function WorkItem({ item }: { item: TimelineItem }) {
  // The API gives every work item its session.
  const work = item.work!;
  const actions = work.pilots_own ? null : actionsOf(work.state);
  const handoff = useHandoff(actions);
  return (
    <div className="item-body">
      <ItemHead item={item}>
        {/* A job's environment is the store's once its start takes it. */}
        {!work.pilots_own && work.environment !== null && (
          <span className="chip mono env">
            <EnvironmentLink environment={work.environment} testId="timeline.work.environment" />
          </span>
        )}
        {work.state === 'running' && work.started_at !== null && <Running since={work.started_at} />}
      </ItemHead>
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      <Line work={work} />
      {actions === 'stop' ? (
        <StopActions item={item} handoff={handoff} />
      ) : actions === 'resume' ? (
        <ResumeActions item={item} handoff={handoff} />
      ) : (
        <div className="item-actions">
          <SessionLog item={item} />
        </div>
      )}
    </div>
  );
}

interface Handoff {
  /** The ref of the actions' resting button, Stop's or Resume's. */
  button: (element: HTMLButtonElement | null) => void;
  /** This browser's act starts from `from`, to swap the actions for the `to` ones. */
  start: (from: HTMLElement, to: Actions) => void;
  /** The act's answer: the item's session as it stands, or none where it was refused. */
  land: (work: Work | null) => void;
}

/**
 * The focus across a swap of the actions: onto the shown ones' resting button where this browser's
 * act made the swap, from the button that had the focus then, and nothing has the focus since. Every
 * swap ends the act's wait, as does an answer that leads to no swap.
 */
function useHandoff(shown: Actions | null): Handoff {
  const button = useRef<HTMLButtonElement | null>(null);
  const awaited = useRef<Actions | null>(null);
  const setButton = useCallback((element: HTMLButtonElement | null) => {
    button.current = element;
  }, []);
  useLayoutEffect(() => {
    const to = awaited.current;
    awaited.current = null;
    const focused = document.activeElement;
    if (to !== null && to === shown && (focused === null || focused === document.body)) button.current?.focus();
  }, [shown]);
  return {
    button: setButton,
    start: (from, to) => {
      awaited.current = document.activeElement === from ? to : null;
    },
    land: (work) => {
      if (work === null || actionsOf(work.state) !== awaited.current) awaited.current = null;
    },
  };
}

/**
 * Session log and Stop, which asks first in the actions' place, as the mockup asks; Cancel takes
 * the focus, so that Enter pressed again cancels, and gives it back to Stop.
 */
function StopActions({ item, handoff }: { item: TimelineItem; handoff: Handoff }) {
  const { act, pending } = useStop(item.id);
  const [asking, setAsking] = useState(false);
  const stopButton = useRef<HTMLButtonElement | null>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const asked = useRef(false);
  const cancel = () => {
    if (!pending) setAsking(false);
  };
  useEscape('menu', asking, cancel);
  useEffect(() => {
    if (asking) cancelButton.current?.focus();
    else if (asked.current) stopButton.current?.focus();
    asked.current = asking;
  }, [asking]);

  if (asking) {
    return (
      <div className="item-actions confirm" data-testid="timeline.work.stop-confirm">
        <span className="confirm-text" data-testid="timeline.work.stop-confirm.text">
          Stop the session? Its turn ends where it is; Resume sends it on.
        </span>
        <button
          type="button"
          className="btn btn-sm btn-danger"
          disabled={pending}
          onClick={(event) => {
            handoff.start(event.currentTarget, 'resume');
            void act().then(handoff.land);
          }}
          data-testid="timeline.work.stop-confirm.yes"
        >
          <Square className="icon" aria-hidden="true" />
          Stop it
        </button>
        <button
          ref={cancelButton}
          type="button"
          className="btn btn-sm"
          disabled={pending}
          onClick={cancel}
          data-testid="timeline.work.stop-confirm.cancel"
        >
          Cancel
        </button>
      </div>
    );
  }
  return (
    <div className="item-actions">
      <SessionLog item={item} />
      <button
        ref={(element) => {
          stopButton.current = element;
          handoff.button(element);
        }}
        type="button"
        className="btn btn-sm"
        onClick={() => setAsking(true)}
        data-testid="timeline.work.stop"
      >
        <Square className="icon" aria-hidden="true" />
        Stop
      </button>
    </div>
  );
}

/** Resume, before Session log; disabled while the project is archived, which the API refuses until Bring back. */
function ResumeActions({ item, handoff }: { item: TimelineItem; handoff: Handoff }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const { act, pending } = useResume(item.id);
  const archived = useArchived(projectId);
  return (
    <div className="item-actions">
      <button
        ref={(element) => handoff.button(element)}
        type="button"
        className="btn btn-sm btn-primary"
        disabled={pending || archived}
        onClick={(event) => {
          handoff.start(event.currentTarget, 'stop');
          void act().then(handoff.land);
        }}
        data-testid="timeline.work.resume"
      >
        <Play className="icon" aria-hidden="true" />
        Resume
      </button>
      <SessionLog item={item} />
    </div>
  );
}

/** "running N min" from when its run began, with a pulse. */
function Running({ since }: { since: string }) {
  // performance.timeOrigin + performance.now() is the wall clock's time, in milliseconds.
  const now = performance.timeOrigin + useNow(true, TICK);
  return (
    <span className="work-live" data-testid="timeline.work.running">
      <span className="pulse" aria-hidden="true" />
      running {span(now - new Date(since).getTime())}
    </span>
  );
}

/** A run's length as the head counts it: "under a minute", "12 min", "1 h 5 min", "3 h", "2 days". */
function span(ms: number): string {
  const minutes = Math.round(Math.max(ms, 0) / 60_000);
  if (minutes < 1) return 'under a minute';
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return minutes % 60 && hours < 6 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
  return `${Math.round(hours / 24)} days`;
}

function Line({ work }: { work: Work }) {
  const line = workLine(work);
  if (line === null) return null;
  const shared = { 'data-testid': 'timeline.work.line', 'data-state': work.state };
  switch (line.kind) {
    case 'cue':
      return (
        <div className="work-line" {...shared}>
          <WorkingCue activity={line.activity} />
          {line.step !== null && (
            <span className="step" title={line.step} data-testid="timeline.work.step">
              {line.step}
            </span>
          )}
        </div>
      );
    case 'stopped':
      return (
        <div className="work-line ended" {...shared}>
          <Square className="icon" aria-hidden="true" />
          <span>
            Stopped
            {line.at !== null && (
              <>
                {' · '}
                <Time at={line.at} format="clock" />
              </>
            )}
            {line.cause !== null && ` · ${line.cause}`}
          </span>
        </div>
      );
    case 'failed':
      return (
        <div className="work-line ended" {...shared}>
          <CircleAlert className="icon" aria-hidden="true" />
          <span>
            Failed
            {line.error !== null && ` · ${line.error}`}
          </span>
        </div>
      );
    default: {
      const unknown: never = line;
      return unknown;
    }
  }
}

/** The session log in the overlay, at its address under the project's, by the item's id, its session's. */
function SessionLog({ item }: { item: TimelineItem }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  return (
    <Link
      to="/projects/$projectId/sessions/$sessionId"
      params={{ projectId, sessionId: item.id }}
      className="btn btn-sm"
      data-testid="timeline.work.session-log"
    >
      <ScrollText className="icon" aria-hidden="true" />
      Session log
    </Link>
  );
}
