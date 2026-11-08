/**
 * An open work item on the timeline (F26): a session Pilot started, updated in place as the
 * server's `work_moved` carries it (F80.2). Its head has the env chip once its start has one, the
 * environment's name in words that go nowhere, its full name their tooltip; on a phone its icon
 * alone, a button that shows the full name in a popover under it; a pulse while its run is under
 * way, from its start, and the running time, "17m", beside it once its run began (F26.1, F12),
 * the tile's one motion, its line standing still (W2); then Session log and Stop as icons, their
 * names their tooltips, before the head's Discuss (F26.8). Under its title is its one line
 * (F26.2): the server's own words while its session comes up, or comes back while its environment
 * restarts; the call it runs alone, "Reading …/chat/tools.ts", Thinking or Writing alone, the
 * sub-agent it waits for and that one's description, while it runs; why the gate holds its start;
 * "Stopped · <time>" with the cause of a stop made elsewhere, or a usage halt's hard stop's
 * "Stopped at the week’s limit · <time>" and its like (F135.6); the error a failed start or a turn
 * ended in error left, shown as a stopped one is (F125); what holds the nudge owed to a run whose turn ended under
 * a halt or a pause, as a held start's reason, "Halted at the week’s limit", "Paused" (F135.3,
 * F141.3). Session log, in every state, opens the session's records in the overlay (F26.3, F69).
 * Stop, while it runs, starts or is held, or idle with its nudge owed (W8), asks first in the row
 * under the line, Esc dismissing the question; Resume, in that row once it stopped or failed, carries it on (F67), disabled while the
 * project is archived, as its head's switch is (D012). Pilot's own work, the setup, the one job
 * drawn here (every other shows on the item it follows from, job.tsx), has no env chip and no Stop
 * or Resume (F26.3, F59.1), and Retry where Resume is once it stopped or failed: a fresh job for
 * the same trigger at the project's next place, disabled while the project is archived. Retried, its line says so under its stop or its failure, and
 * offers Retry no more. The row leads with the progress button once its run published its steps,
 * the plan's donut and the first step in progress, opening their list (F145.2, F145.3), until the
 * list is emptied; a job publishes none. A tile with nothing for the row has no row. Once this
 * browser's Stop or Resume swaps the two, the keyboard focus on the button that went goes to the
 * other, Resume or Stop's icon, and once its Retry lands, to Session log's icon; a swap another
 * browser's act made moves no focus, and a refused act gives it back to the button pressed, Resume,
 * Retry or Stop it (W7).
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { Link } from '@tanstack/react-router';
import { CircleAlert, Play, RotateCw, ScrollText, Server, Square } from 'lucide-react';
import { WorkingCue } from '@/components/chat/working-cue';
import { LinkedText } from '@/components/shared/linked-text';
import { Popover } from '@/components/shared/popover';
import { StepsButton } from '@/components/shared/steps-button';
import { Time } from '@/components/shared/time';
import { ItemHead } from '@/components/timeline/item-head';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import { useNow } from '@/hooks/use-now';
import { useShownProject } from '@/hooks/use-project-address';
import { useArchived } from '@/hooks/use-projects';
import { titleOf, type TimelineItem } from '@/hooks/use-timeline';
import { offersRetry, offersStop, RESUMABLE, useResume, useRetry, useStop } from '@/hooks/use-work-acts';
import type { components } from '@/lib/api/generated/types';
import { useEscape } from '@/lib/keys';
import { progressStepMark, workLine } from '@/lib/utils/status-labels';

type Work = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema'];

/** How often the running time is counted again, in milliseconds. */
const TICK = 15_000;

type Actions = 'stop' | 'resume' | 'retry' | 'log';

/** The actions a session offers: a worker's Stop or Resume by its state, a job's Retry where it offers it, else its session log alone. */
function actionsOf(work: Work): Actions {
  if (work.pilots_own) return offersRetry(work) ? 'retry' : 'log';
  return offersStop(work) ? 'stop' : RESUMABLE.includes(work.state) ? 'resume' : 'log';
}

export function WorkItem({ item }: { item: TimelineItem }) {
  // The API gives every work item its session.
  const work = item.work!;
  const actions = actionsOf(work);
  const handoff = useHandoff(actions);
  const [asked, setAsked] = useState(false);
  // The question goes with Stop, whichever browser's act took Stop away.
  if (asked && actions !== 'stop') setAsked(false);
  const asking = asked && actions === 'stop';
  const stopButton = useRef<HTMLButtonElement | null>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (asking) cancelButton.current?.focus();
  }, [asking]);
  return (
    <div className="item-body">
      <ItemHead item={item}>
        {/* A job's environment is the store's once its start takes it. */}
        {!work.pilots_own && work.environment !== null && <EnvironmentChip name={work.environment.name} />}
        {underWay(work) && <Live since={work.state === 'running' ? work.started_at : null} />}
        <SessionLog item={item} rest={actions === 'log' ? handoff.button : undefined} />
        {actions === 'stop' && (
          <button
            ref={(element) => {
              stopButton.current = element;
              handoff.button(element);
            }}
            type="button"
            className="btn btn-ghost btn-sm btn-icon work-stop"
            onClick={() => (asking ? cancelButton.current?.focus() : setAsked(true))}
            title="Stop"
            aria-label="Stop"
            data-testid="timeline.work.stop"
          >
            <Square className="icon" aria-hidden="true" />
          </button>
        )}
      </ItemHead>
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      <Line work={work} />
      {work.retried !== null && <Retried at={work.retried.at} />}
      {asking ? (
        <StopQuestion
          item={item}
          handoff={handoff}
          cancelButton={cancelButton}
          onCancel={() => {
            stopButton.current?.focus();
            setAsked(false);
          }}
        />
      ) : (
        <Row item={item} actions={actions} handoff={handoff} steps={work.progress} />
      )}
    </div>
  );
}

/**
 * The env chip: the environment's name, its full name its tooltip, going nowhere. On a phone it is
 * its icon alone, which nothing hovers: a button named after the environment, whose tap shows the
 * full name in a popover under it, closed by a tap outside it, Esc or the icon (timeline.css).
 */
function EnvironmentChip({ name }: { name: string }) {
  return (
    <span className="chip mono env" title={name} data-testid="timeline.work.environment">
      <span className="chip-label">{name}</span>
      <Popover
        label={name}
        anchorClassName="env-anchor"
        className="env-pop"
        testId="timeline.work.environment.popover"
        trigger={({ open, toggle }) => (
          <button
            type="button"
            className="env-icon"
            onClick={toggle}
            aria-label={name}
            aria-haspopup="dialog"
            aria-expanded={open}
            data-testid="timeline.work.environment.icon"
          >
            <Server className="icon" aria-hidden="true" />
          </button>
        )}
      >
        {name}
      </Popover>
    </span>
  );
}

interface Handoff {
  /** The ref of the actions' resting element: Stop's icon, Resume's or Retry's button, else Session log's icon. */
  button: (element: HTMLElement | null) => void;
  /** This browser's act starts from `from`, to swap the actions for the `to` ones. */
  start: (from: HTMLElement, to: Actions) => void;
  /** The act's answer: the item's session as it stands, or none where it was refused. */
  land: (work: Work | null) => void;
}

/**
 * The focus across a swap of the actions: onto the shown ones' resting element where this browser's
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

interface StopQuestionProps {
  item: TimelineItem;
  handoff: Handoff;
  cancelButton: RefObject<HTMLButtonElement | null>;
  /** Ends the question, the focus back on Stop's icon. */
  onCancel: () => void;
}

/**
 * Stop's question, in the row's place under the line: Stop it ends the session; Cancel, focused as
 * the question opens so that Enter pressed again cancels, and Esc dismiss it.
 */
function StopQuestion({ item, handoff, cancelButton, onCancel }: StopQuestionProps) {
  const { act, pending } = useStop(item.id);
  const cancel = () => {
    if (!pending) onCancel();
  };
  useEscape('menu', true, cancel);
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
          void act(event.currentTarget).then(handoff.land);
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

interface RowProps {
  item: TimelineItem;
  actions: Actions;
  handoff: Handoff;
  steps: Work['progress'];
}

/** The row under the line, with the progress button and Resume or a job's Retry; none where it has neither. */
function Row({ item, actions, handoff, steps }: RowProps) {
  if (steps.length === 0 && actions !== 'resume' && actions !== 'retry') return null;
  return (
    <div className="item-actions" data-testid="timeline.work.row">
      {steps.length > 0 && <Progress steps={steps} />}
      {actions === 'resume' && <Resume item={item} handoff={handoff} />}
      {actions === 'retry' && <Retry item={item} handoff={handoff} />}
    </div>
  );
}

/** The progress button: the steps the run published, behind the plan's donut and its popover. */
function Progress({ steps }: { steps: Work['progress'] }) {
  return (
    <StepsButton
      steps={steps.map((step) => ({ id: step.code, title: step.label, mark: progressStepMark(step.state) }))}
      name="Progress"
      anchorClassName="progress-anchor"
      testId="timeline.work.progress"
      popoverTestId="timeline.work.steps"
    />
  );
}

/** Resume, disabled while the project is archived, which the API refuses until Bring back. */
function Resume({ item, handoff }: { item: TimelineItem; handoff: Handoff }) {
  const { id: projectId } = useShownProject();
  const { act, pending } = useResume(item.id);
  const archived = useArchived(projectId);
  return (
    <button
      ref={(element) => handoff.button(element)}
      type="button"
      className="btn btn-sm btn-primary"
      disabled={pending || archived}
      onClick={(event) => {
        handoff.start(event.currentTarget, 'stop');
        void act(event.currentTarget).then(handoff.land);
      }}
      data-testid="timeline.work.resume"
    >
      <Play className="icon" aria-hidden="true" />
      Resume
    </button>
  );
}

/** A job's Retry, where a worker's Resume is; disabled while the project is archived, which the API refuses until Bring back. */
function Retry({ item, handoff }: { item: TimelineItem; handoff: Handoff }) {
  const { id: projectId } = useShownProject();
  const { act, pending } = useRetry(item.id);
  const archived = useArchived(projectId);
  return (
    <button
      ref={(element) => handoff.button(element)}
      type="button"
      className="btn btn-sm btn-primary"
      disabled={pending || archived}
      onClick={(event) => {
        handoff.start(event.currentTarget, 'log');
        void act(event.currentTarget).then(handoff.land);
      }}
      data-testid="timeline.work.retry"
    >
      <RotateCw className="icon" aria-hidden="true" />
      Retry
    </button>
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

/** Its run is under way: it comes up, or runs; held, once nothing holds it. */
const underWay = (work: Work) =>
  work.state === 'starting' || work.state === 'running' || (work.state === 'held' && work.held_reason === null);

/** The run under way: a pulse, and beside it the running time once `since`, when its run began. */
function Live({ since }: { since: string | null }) {
  return (
    <span className="work-live" data-testid="timeline.work.live">
      <span className="pulse" aria-hidden="true" />
      {since !== null && <Running since={since} />}
    </span>
  );
}

/** The running time from when its run began, the figure alone, "17m"; "Running for 17m" its tooltip and its accessible name. */
function Running({ since }: { since: string }) {
  const figure = span(useNow(TICK) - Date.parse(since));
  return (
    <span role="timer" title={`Running for ${figure}`} aria-label={`Running for ${figure}`} data-testid="timeline.work.running">
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
          <WorkingCue activity={line.activity} words={line.step} animate={false} />
          {line.detail !== null && (
            <>
              <span className="sep" aria-hidden="true">
                ·
              </span>
              <span className="detail" title={line.detail} data-testid="timeline.work.detail">
                {line.detail}
              </span>
            </>
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
 * Session log's icon: the session log in the overlay, at its address under the project's, by the
 * item's id, its session's; `rest` takes it where it is the actions' resting element.
 */
function SessionLog({ item, rest }: { item: TimelineItem; rest?: (element: HTMLElement | null) => void }) {
  const { address } = useShownProject();
  const replace = useTabReplace();
  return (
    <Link
      ref={rest}
      to="/projects/$address/sessions/$sessionId"
      params={{ address, sessionId: item.id }}
      replace={replace}
      className="btn btn-ghost btn-sm btn-icon work-log"
      title="Session log"
      aria-label="Session log"
      data-testid="timeline.work.session-log"
    >
      <ScrollText className="icon" aria-hidden="true" />
    </Link>
  );
}
