/**
 * How a project's standing reads (STATUS-4): the head's step reading (F2.2), a tab's status line
 * (F1.2), derived from the record, never written by the brain (database.md decision 15), a tab's
 * status icon (F1.3, F141.1), and a step's standing in the plan popover (F3.1). How a work item's session reads: its one line on the
 * timeline (F26.1, F26.2, F125), why the gate holds its start (F26.1), why it stopped when no one
 * stopped it (F71), its session log's tail (F69.2), and a job's line withdrawn by an Undo (F14.1). How a condition that holds all work reads
 * on the gold bar (F125).
 */

import { Circle, CircleCheck, CircleDashed, Hourglass, Pause, ServerOff, UserRound, type LucideIcon } from 'lucide-react';
import type { components } from '@/lib/api/generated/types';
import { phaseOf, type Activity } from '@/lib/chat/activity';
import { summarizeTool } from '@/lib/chat/tools';

type ProjectTab = components['schemas']['ProjectListResponseSchema.e86ccd6.ProjectTabSchema'];
type PlanProgress = components['schemas']['ProjectListResponseSchema.e86ccd6.PlanProgressSchema'];
type ProjectStatus = NonNullable<ProjectTab['status']>;
type TaskStatus = components['schemas']['ProjectHeadSchema.e86ccd6.TaskStatus'];
type Work = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema'];
type HeldReason = components['schemas']['TimelineSchema.1fdd8ae.HeldReason'];
type CurrentLine = components['schemas']['TimelineSchema.1fdd8ae.CurrentLineSchema'];
type LineStep = NonNullable<CurrentLine['step']>;
type ConditionCode = components['schemas']['ConditionsSchema.6c014b4.ConditionCode'];
type DoneCause = components['schemas']['TimelineSchema.1fdd8ae.DoneSchema']['cause'];

interface StepReading {
  text: string;
  /** More steps are in progress than the one named: ", …" follows the name, kept when it is cut short. */
  more: boolean;
}

/** The first step in progress by name; else "Not started", "N of M done" or "All steps done". */
export function stepReading(progress: PlanProgress): StepReading {
  const [first, ...rest] = progress.in_progress;
  if (first !== undefined) return { text: first, more: rest.length > 0 };
  if (progress.done === 0) return { text: 'Not started', more: false };
  if (progress.done === progress.total) return { text: 'All steps done', more: false };
  return { text: `${progress.done} of ${progress.total} done`, more: false };
}

interface StatusLine extends StepReading {
  /** The time shown after the text: when a finished project finished. */
  at: string | null;
}

/** "Draft" while the project is in the chat, "Finished <date>" once finished, else the step reading. */
export function projectStatusLine(tab: Pick<ProjectTab, 'state' | 'finished_at' | 'progress'>): StatusLine {
  switch (tab.state) {
    case 'draft':
      return { text: 'Draft', more: false, at: null };
    case 'finished':
      return { text: 'Finished', more: false, at: tab.finished_at };
    case 'open':
      return { ...stepReading(tab.progress), at: null };
    default: {
      const unknown: never = tab.state;
      return { text: String(unknown), more: false, at: null };
    }
  }
}

interface StatusIconReading {
  label: string;
  icon: LucideIcon;
}

/** A project's status as its tab's icon shows it (F1.3, F141.1): the words it reads and its glyph. */
export function projectStatusIcon(status: ProjectStatus): StatusIconReading {
  switch (status) {
    case 'running':
      return { label: 'Running', icon: Circle };
    case 'waiting_on_you':
      return { label: 'Waiting on you', icon: UserRound };
    case 'waiting_on_event':
      return { label: 'Waiting on an event', icon: Hourglass };
    case 'done':
      return { label: 'Every step done', icon: CircleCheck };
    case 'idle':
      return { label: 'Idle', icon: CircleDashed };
    case 'pausing':
      return { label: 'Pausing', icon: Pause };
    case 'paused':
      return { label: 'Paused', icon: Pause };
    default: {
      const unknown: never = status;
      return { label: String(unknown), icon: CircleDashed };
    }
  }
}

interface PlanStep {
  /** The step's mark in the plan popover: ticked once done, highlighted while in progress. */
  mark: 'done' | 'now' | 'pending';
  label: string;
}

export function planStep(status: TaskStatus): PlanStep {
  switch (status) {
    case 'done':
      return { mark: 'done', label: 'Done' };
    case 'in_progress':
      return { mark: 'now', label: 'In progress' };
    case 'pending':
      return { mark: 'pending', label: 'Not started' };
    default: {
      const unknown: never = status;
      return { mark: 'pending', label: String(unknown) };
    }
  }
}

/**
 * Why the gate holds a work item’s start, as its line says it (F26.1, F141.5, F143.4, F59.2; DB 183);
 * `running`, the work items that leave it no slot, counted while no slot is free.
 */
export function heldReasonLabel(reason: HeldReason, running: number | null): string {
  switch (reason) {
    case 'paused':
      return 'Paused';
    case 'controller_unreachable':
      return 'Waiting for the controller';
    case 'slot':
      // The API counts the running work items whenever it holds a start for a slot.
      return `Waiting for a slot · ${running!} running`;
    case 'queue':
      return 'Waiting for the job before it';
    case 'conversation':
      return 'Waiting for the run before it';
    default: {
      const unknown: never = reason;
      return String(unknown);
    }
  }
}

/**
 * What a work item's done line says of how it closed, under its title: a job withdrawn by the Undo
 * of the item whose close placed it, before its brief went out, which never ran (F14.1); null for
 * every other close, which its time stands for.
 */
export function workClosedLabel(cause: DoneCause): string | null {
  switch (cause) {
    case 'withdrawn':
      return 'Withdrawn by an Undo';
    case 'answered':
    case 'marked':
    case 'settled':
    case 'turn_ended':
    case 'finished':
      return null;
    default: {
      const unknown: never = cause;
      return String(unknown);
    }
  }
}

interface ConditionLine {
  /** What holds, followed by the time it began. */
  title: string;
  /** What it holds. */
  detail: string;
  icon: LucideIcon;
}

/** A condition that holds all work, as its line on the gold bar says it (F125). */
export function conditionLine(code: ConditionCode): ConditionLine {
  switch (code) {
    case 'outage':
      return { title: 'The controller has been unreachable', detail: 'Nothing starts until it answers.', icon: ServerOff };
    default: {
      const unknown: never = code;
      return { title: String(unknown), detail: '', icon: ServerOff };
    }
  }
}

/**
 * Why a work item stopped when its environment was stopped under it or settled in error, a stop
 * made elsewhere (F26.1, F71); null for any other stop.
 */
function stopCause(work: Work): string | null {
  const cause = work.stopped_cause;
  if (cause === null) return null;
  // A stop made elsewhere is its environment's: a Session stopped under its turn has one.
  const environment = work.environment!.name;
  switch (cause) {
    case 'environment_stopped':
      return `${environment} was stopped`;
    case 'environment_deleting':
      return `${environment} is being deleted`;
    case 'environment_gone':
      return `${environment} is gone`;
    case 'environment_error':
      return `${environment} is in error`;
    default: {
      const unknown: never = cause;
      return String(unknown);
    }
  }
}

/** A work item's one line on the timeline while its session is held, starts or runs: the working cue's state, and the latest step. */
interface WorkCue {
  kind: 'cue';
  activity: Activity;
  /** The latest tool call, worded as the chat words a call; a sub-agent's description while it runs. */
  step: string | null;
}

/** "Stopped · <time>", and the cause of a stop made elsewhere. */
interface WorkStopped {
  kind: 'stopped';
  at: string | null;
  cause: string | null;
}

/** A failed start, or a turn ended in error, shown as a stopped one is, with the error (F125). */
interface WorkFailed {
  kind: 'failed';
  error: string | null;
}

type WorkLine = WorkCue | WorkStopped | WorkFailed;

const STARTING: Activity = { kind: 'starting', phase: 'Starting' };
const WAITING: Activity = { kind: 'waiting', phase: 'Waiting for Pilot' };

const cue = (activity: Activity, step: string | null = null): WorkCue => ({ kind: 'cue', activity, step });

/**
 * A work item's one line (F26.1, F26.2): why the gate holds its start; the current line as the
 * chat words its cue, or that it starts, or waits for Pilot, before its session gives one;
 * "Stopped · <time>" with a stop made elsewhere's cause; the error it failed on. Null once its
 * turn ended, when its done line stands for it.
 */
export function workLine(work: Work): WorkLine | null {
  const line = work.current_line;
  switch (work.state) {
    case 'held':
      if (work.held_reason !== null) return cue({ kind: 'waiting', phase: heldReasonLabel(work.held_reason, work.held_running) });
      return line === null ? cue(STARTING) : lineCue(line);
    case 'starting':
      return line === null ? cue(STARTING) : lineCue(line);
    case 'running':
      return line === null ? cue(WAITING) : lineCue(line);
    case 'stopped':
      return { kind: 'stopped', at: work.stopped_at, cause: stopCause(work) };
    case 'failed':
      return { kind: 'failed', error: work.error };
    case 'idle':
    case 'ended':
      return null;
    default: {
      const unknown: never = work.state;
      return cue({ kind: 'working', phase: String(unknown) });
    }
  }
}

/**
 * A current line's step as the chat words its call, running or done: its verb alone while its
 * input streams in, before the call's line gives its target; an empty target is not drawn.
 */
function stepWords(call: LineStep | null, running: boolean): string | null {
  if (call === null || call.tool === null) return null;
  const summary = summarizeTool(call.tool, (call.input ?? {}) as Record<string, unknown>);
  const verb = running ? summary.verbRunning : summary.verb;
  return call.input === null ? verb : [verb, summary.target].filter(Boolean).join(' ');
}

/** The relay's current line in the chat cue's words (design 2 §9.5): the server's own while the session comes up. */
function lineCue(line: CurrentLine): WorkCue {
  const done = stepWords(line.step, false);
  switch (line.state) {
    case 'starting':
      return cue({ kind: 'starting', phase: line.text === null ? STARTING.phase : phaseOf(line.text) });
    case 'thinking':
      return cue({ kind: 'thinking', phase: 'Thinking' }, done);
    case 'writing':
      return cue({ kind: 'writing', phase: 'Writing' }, done);
    case 'working':
      return cue({ kind: 'tool', phase: 'Working' }, stepWords(line.step, true));
    case 'waiting': {
      const type = line.agent?.type ?? null;
      return cue(
        { kind: 'agent', phase: type === null ? 'Waiting for the agent' : `Waiting for the ${type} agent` },
        line.agent?.description ?? null,
      );
    }
    default: {
      const unknown: never = line.state;
      return cue({ kind: 'working', phase: String(unknown) }, done);
    }
  }
}

interface LogTail {
  /** How the session's last turn ended. */
  mark: 'ended' | 'stopped' | 'failed';
  text: string;
  /** The time after the text. */
  at: string | null;
}

/**
 * A session log's tail once its work runs no turn (F69.2): "Stopped by you", by whom else, or the
 * environment stopped under it, at the stop; "The turn ended" or "Failed", at `endedAt`. Null
 * while it is held, starts or runs, when the working cue is the tail.
 */
export function sessionLogTail(work: Work, selfHandle: string, endedAt: string | null): LogTail | null {
  switch (work.state) {
    case 'held':
    case 'starting':
    case 'running':
      return null;
    case 'idle':
    case 'ended':
      return { mark: 'ended', text: 'The turn ended', at: endedAt };
    case 'stopped': {
      const by = work.stopped_by;
      const text = by !== null ? (by.handle === selfHandle ? 'Stopped by you' : `Stopped by ${by.name}`) : (stopCause(work) ?? 'Stopped');
      return { mark: 'stopped', text, at: work.stopped_at };
    }
    case 'failed':
      return { mark: 'failed', text: 'Failed', at: endedAt };
    default: {
      const unknown: never = work.state;
      return { mark: 'ended', text: String(unknown), at: endedAt };
    }
  }
}
