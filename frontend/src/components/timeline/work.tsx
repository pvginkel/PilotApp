/**
 * An open work item on the timeline (F26): a session Pilot started, updated in place as the
 * server's `work_moved` carries it (F80.2). Its head has the env chip, opening the environment in
 * KubeCoder, once its start has one, an icon alone on a phone, and the running time, a pulse and "17m", while its turn runs
 * (F26.1, F12). Under its title is its one line (F26.2): the server's own words while its session comes
 * up, or comes back while its environment restarts; the working state and the latest step while
 * it runs; why the gate holds its start; "Stopped · <time>" with the cause of a stop made
 * elsewhere, or a usage halt's hard stop's "Stopped at the week’s limit · <time>" and its like
 * (F135.6); the error a failed start or a turn ended in error left, shown as a stopped one is
 * (F125); what holds the nudge owed to a run whose turn ended under a halt or a pause, as a held
 * start's reason, "Halted at the week’s limit", "Paused" (F135.3, F141.3). Its Session log opens the session's records in the overlay (F26.3, F69). Stop, while it
 * runs, starts or is held, asks first in its actions' place, Esc dismissing the question; Resume,
 * once it stopped or failed, carries it on (F67), disabled while the project is archived, as its
 * head's switch is (D012). Pilot's own work, a background job such as the setup, has no env chip
 * and no Stop or Resume, its session log alone (F26.3, F59.1), and Retry where Resume is once it
 * stopped or failed: a fresh job for the same trigger at the project's next place, disabled while
 * the project is archived. Retried, its line says so under its stop or its failure, and offers
 * Retry no more. Once this browser's Stop or Resume swaps the two, the keyboard focus on the
 * button that went goes to the other's resting button, Resume or Stop, and once its Retry lands,
 * to Session log; a swap another browser's act made moves no focus.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link, useParams } from '@tanstack/react-router';
import { CircleAlert, Play, RotateCw, ScrollText, Server, Square } from 'lucide-react';
import { WorkingCue } from '@/components/chat/working-cue';
import { EnvironmentLink, LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import { ItemHead } from '@/components/timeline/item-head';
import { useNow } from '@/hooks/use-now';
import { useArchived } from '@/hooks/use-projects';
import { titleOf, type TimelineItem } from '@/hooks/use-timeline';
import { RESUMABLE, STOPPABLE, useResume, useRetry, useStop } from '@/hooks/use-work-acts';
import type { components } from '@/lib/api/generated/types';
import { useEscape } from '@/lib/keys';
import { workLine } from '@/lib/utils/status-labels';

type Work = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema'];

/** How often the running time is counted again, in milliseconds. */
const TICK = 15_000;

type Actions = 'stop' | 'resume' | 'retry' | 'log';

/**
 * The actions a session offers: a worker's Stop or Resume by its state, a job's Retry while it is
 * stopped or failed, not retried and owed no nudge — one whose turn died at the quota wall is not at
 * its end until its nudge's run ends (D078) — else its session log alone.
 */
function actionsOf(work: Work): Actions {
  if (work.pilots_own) {
    return RESUMABLE.includes(work.state) && work.retried === null && !work.nudge_owed ? 'retry' : 'log';
  }
  return STOPPABLE.includes(work.state) ? 'stop' : RESUMABLE.includes(work.state) ? 'resume' : 'log';
}

export function WorkItem({ item }: { item: TimelineItem }) {
  // The API gives every work item its session.
  const work = item.work!;
  const actions = actionsOf(work);
  const handoff = useHandoff(actions);
  return (
    <div className="item-body">
      <ItemHead item={item}>
        {/* A job's environment is the store's once its start takes it. On a phone the chip is its
            icon, the name left to the link's tooltip and to a screen reader. */}
        {!work.pilots_own && work.environment !== null && (
          <span className="chip mono env">
            <EnvironmentLink environment={work.environment} testId="timeline.work.environment">
              <Server className="icon" aria-hidden="true" />
              <span className="chip-label">{work.environment.name}</span>
            </EnvironmentLink>
          </span>
        )}
        {work.state === 'running' && work.started_at !== null && <Running since={work.started_at} />}
      </ItemHead>
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      <Line work={work} />
      {work.retried !== null && <Retried at={work.retried.at} />}
      {actions === 'stop' ? (
        <StopActions item={item} handoff={handoff} />
      ) : actions === 'resume' ? (
        <ResumeActions item={item} handoff={handoff} />
      ) : actions === 'retry' ? (
        <RetryActions item={item} handoff={handoff} />
      ) : (
        <div className="item-actions">
          <SessionLog item={item} rest={handoff.button} />
        </div>
      )}
    </div>
  );
}

interface Handoff {
  /** The ref of the actions' resting element: Stop's, Resume's or Retry's button, else Session log. */
  button: (element: HTMLElement | null) => void;
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
function useHandoff(shown: Actions): Handoff {
  const button = useRef<HTMLElement | null>(null);
  const awaited = useRef<Actions | null>(null);
  const setButton = useCallback((element: HTMLElement | null) => {
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
      if (work === null || actionsOf(work) !== awaited.current) awaited.current = null;
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

/**
 * A job's Retry, where a worker's Resume is, before Session log; disabled while the project is
 * archived, which the API refuses until Bring back.
 */
function RetryActions({ item, handoff }: { item: TimelineItem; handoff: Handoff }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const { act, pending } = useRetry(item.id);
  const archived = useArchived(projectId);
  return (
    <div className="item-actions">
      <button
        ref={(element) => handoff.button(element)}
        type="button"
        className="btn btn-sm btn-primary"
        disabled={pending || archived}
        onClick={(event) => {
          handoff.start(event.currentTarget, 'log');
          void act().then(handoff.land);
        }}
        data-testid="timeline.work.retry"
      >
        <RotateCw className="icon" aria-hidden="true" />
        Retry
      </button>
      <SessionLog item={item} />
    </div>
  );
}

/** That a person's Retry placed a new job for this one, at the project's next place, and when. */
function Retried({ at }: { at: string }) {
  return (
    <div className="work-line ended retried" data-testid="timeline.work.retried">
      <RotateCw className="icon" aria-hidden="true" />
      <span>
        Retried as a new job below · <Time at={at} format="clock" />
      </span>
    </div>
  );
}

/**
 * The running time from when its run began, a pulse and the figure alone, "17m"; "Running for 17m"
 * its tooltip and its accessible name.
 */
function Running({ since }: { since: string }) {
  // performance.timeOrigin + performance.now() is the wall clock's time, in milliseconds.
  const now = performance.timeOrigin + useNow(true, TICK);
  const figure = span(now - new Date(since).getTime());
  return (
    <span
      className="work-live"
      role="timer"
      title={`Running for ${figure}`}
      aria-label={`Running for ${figure}`}
      data-testid="timeline.work.running"
    >
      <span className="pulse" aria-hidden="true" />
      {figure}
    </span>
  );
}

/** A run's length as the head counts it: "0m", "12m", "1h 5m", past six hours "7h", past two days "2d". */
function span(ms: number): string {
  const minutes = Math.round(Math.max(ms, 0) / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return minutes % 60 && hours < 6 ? `${hours}h ${minutes % 60}m` : `${hours}h`;
  return `${Math.round(hours / 24)}d`;
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
            {line.text}
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

/**
 * The session log in the overlay, at its address under the project's, by the item's id, its
 * session's; `rest` takes it where it is the actions' resting element.
 */
function SessionLog({ item, rest }: { item: TimelineItem; rest?: (element: HTMLElement | null) => void }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  return (
    <Link
      ref={rest}
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
