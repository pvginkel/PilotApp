/**
 * How a project's standing reads (STATUS-4): the head's step reading (F2.2), a tab's status line
 * (F1.2), derived from the record, never written by the brain (database.md decision 15), a tab's
 * status icon (F1.3, F141.1), and a step's standing in the plan popover and in a work item's progress (F3.1, F145.3). How a work item's session reads: its one line on the
 * timeline (F26.1, F26.2, F125), why the gate holds its start (F26.1), why it stopped when no one
 * of the app's people stopped it (F71, F135.6), its session log's tail (F69.2), and a job's line withdrawn by an Undo (F14.1). What Pilot
 * does on an item that is Pilot's, on its line (F13.7) and on the strip over it opened (F28.9). How a condition that holds all work reads
 * on the gold bar (F125, F135.7), and the week's halt's overrule (F135.2).
 */

import { Circle, CircleCheck, CircleDashed, Hourglass, OctagonPause, Pause, RefreshCw, ServerOff, UserRound, type LucideIcon } from 'lucide-react';
import type { components } from '@/lib/api/generated/types';
import { phaseOf, type Activity } from '@/lib/chat/activity';
import { summarizeTool, type Words } from '@/lib/chat/tools';
import { clockFormat, formatTime } from '@/lib/utils/time-format';

type ProjectTab = components['schemas']['ProjectListResponseSchema.e86ccd6.ProjectTabSchema'];
type PlanProgress = components['schemas']['ProjectListResponseSchema.e86ccd6.PlanProgressSchema'];
type ProjectStatus = NonNullable<ProjectTab['status']>;
type TaskStatus = components['schemas']['ProjectHeadSchema.e86ccd6.TaskStatus'];
type ProgressState = components['schemas']['TimelineSchema.1fdd8ae.ProgressState'];
type Work = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema'];
type HeldReason = components['schemas']['TimelineSchema.1fdd8ae.HeldReason'];
type CurrentLine = components['schemas']['TimelineSchema.1fdd8ae.CurrentLineSchema'];
type LineStep = NonNullable<CurrentLine['step']>;
type Condition = components['schemas']['ConditionsSchema.6c014b4.ConditionSchema'];
type OverruleKind = components['schemas']['ConditionsSchema.6c014b4.OverruleKind'];
type HaltSetting = components['schemas']['ConditionsSchema.6c014b4.HaltSetting'];
type Doing = components['schemas']['TimelineSchema.1fdd8ae.Doing'];

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

/** A step's mark in its popover: ticked once done, highlighted while in progress. */
export type StepMark = 'done' | 'now' | 'pending';

export function planStepMark(status: TaskStatus): StepMark {
  switch (status) {
    case 'done':
      return 'done';
    case 'in_progress':
      return 'now';
    case 'pending':
      return 'pending';
    default: {
      const unknown: never = status;
      return unknown;
    }
  }
}

/** A work item's step's mark (F145.2): an `active` step is in progress. */
export function progressStepMark(state: ProgressState): StepMark {
  switch (state) {
    case 'done':
      return 'done';
    case 'active':
      return 'now';
    case 'pending':
      return 'pending';
    default: {
      const unknown: never = state;
      return unknown;
    }
  }
}

/** A step's mark as a screen reader names it. */
export function stepMarkLabel(mark: StepMark): string {
  switch (mark) {
    case 'done':
      return 'Done';
    case 'now':
      return 'In progress';
    case 'pending':
      return 'Not started';
    default: {
      const unknown: never = mark;
      return String(unknown);
    }
  }
}

/**
 * Why the gate holds a work item’s start, as its line says it (F26.1, F141.5, F143.4, F59.2, F135.1,
 * F135.4, F144.4; DB 183);
 * `running`, the work items that leave it no slot, counted while no slot is free.
 */
export function heldReasonLabel(reason: HeldReason, running: number | null): string {
  switch (reason) {
    case 'week_halt':
      return 'Halted at the week’s limit';
    case 'five_hour_halt':
      return 'Halted at the five-hour limit';
    case 'paused':
      return 'Paused';
    case 'store_update':
      return 'Waiting for Pilot’s update';
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
 * How Pilot's job shows on the item it follows from (F59.1): under way while it is held, starts or
 * runs, or its turn ended under a halt or a pause and owes the nudge that carries it on; ended once
 * its turn ended or its session did; failed or stopped.
 */
type JobForm = 'running' | 'ended' | 'failed' | 'stopped';

export function jobForm(work: Work): JobForm {
  switch (work.state) {
    case 'held':
    case 'starting':
    case 'running':
      return 'running';
    case 'idle':
      return work.nudge_owed ? 'running' : 'ended';
    case 'ended':
      return 'ended';
    case 'failed':
    case 'stopped':
      return work.state;
    default: {
      const unknown: never = work.state;
      return unknown;
    }
  }
}

/** What a failed or stopped job's button says after its title. */
export function jobHaltLabel(form: 'failed' | 'stopped'): string {
  switch (form) {
    case 'failed':
      return 'Failed';
    case 'stopped':
      return 'Stopped';
    default: {
      const unknown: never = form;
      return String(unknown);
    }
  }
}

/** What Pilot does on an item that is Pilot's, as its line's button says it (F13.7). */
export function pilotsDoingLabel(doing: Doing): string {
  switch (doing) {
    case 'awaiting_run':
      return 'Awaiting the run';
    case 'pre_ruling':
      return 'Pre-ruling';
    case 'asking_writer':
      return 'Asking the writer';
    case 'doing':
      return 'Doing it';
    case 'researching':
      return 'Researching';
    case 'waiting_on_answer':
      return 'Waiting on your answer';
    default: {
      const unknown: never = doing;
      return String(unknown);
    }
  }
}

/**
 * What Pilot does on a document that is Pilot's, as the strip over it opened says it (F28.9): the
 * words before what the strip links, the work item doing it or the document awaiting the person's
 * answer, and the words after it; `read`, whether the document has a text.
 */
export function pilotsStripWords(doing: Doing, read: boolean): { before: string; after: string } {
  switch (doing) {
    case 'awaiting_run':
      return read
        ? { before: 'Pilot goes over this document once the other documents its run registered are read.', after: '' }
        : { before: 'Nothing of this document has been read yet.', after: '' };
    case 'pre_ruling':
      return { before: 'Pilot is pre-ruling this document: it settles what it may, and what is left comes to you.', after: '' };
    case 'asking_writer':
      return { before: 'Pilot asked the writer about this document and waits for the reply, then goes over it again.', after: '' };
    case 'doing':
      return { before: 'Pilot does what is open here in ', after: '; its Done comes with the result.' };
    case 'researching':
      return { before: 'Pilot has a fact this asks about checked in ', after: ' before it rules.' };
    case 'waiting_on_answer':
      return { before: 'Pilot waits on your answer to ', after: ' before it goes on with what is open here.' };
    default: {
      const unknown: never = doing;
      return { before: String(unknown), after: '' };
    }
  }
}

interface ConditionLine {
  /** What holds, followed by the time it began. */
  title: string;
  /** What it holds. */
  detail: string;
  /** What holds in short, its badge's words, followed by the time it began. */
  badge: string;
  icon: LucideIcon;
}

const PERCENT = new Intl.NumberFormat('en-GB', { style: 'percent', maximumFractionDigits: 0 });

/**
 * A halt's share of its window's quota, "92% of the week’s quota is used.", and the reading's age
 * while it is stale, "92% of the week’s quota is used, as of 14:20." (design 4 §6, The age; D102).
 */
function halted(condition: Condition, quota: string, today: string): string {
  // The API gives a halt its share, the time of its reading and whether it is stale.
  const used = `${PERCENT.format(condition.share!)} of ${quota} is used`;
  // A fresh reading is current to within the poll, whatever its taken_at.
  if (!condition.stale) return `${used}.`;
  const takenAt = condition.taken_at!;
  return `${used}, as of ${formatTime(takenAt, clockFormat(takenAt, today))}.`;
}

const HALT_GOES_ON = 'chats and Pilot’s own jobs go on.';

/**
 * What a halt does to the work items, by its window's halt setting (F135.6): every setting holds
 * their starts; the cooperative stop asks the running ones to stop at their next step, and under
 * the hard stop Pilot has stopped them.
 */
function haltDoes(condition: Condition): string {
  // The API gives a halt its setting.
  const setting: HaltSetting = condition.setting!;
  switch (setting) {
    case 'no_new_work':
      return `No work item starts until a reading puts it under the limit; ${HALT_GOES_ON}`;
    case 'cooperative_stop':
      return `The running work items are asked to stop at their next step, and none starts until a reading puts it under the limit; ${HALT_GOES_ON}`;
    case 'hard_stop':
      return `Pilot has stopped every running work item, and none starts until a reading puts it under the limit; ${HALT_GOES_ON}`;
    default: {
      const unknown: never = setting;
      return String(unknown);
    }
  }
}

/**
 * A condition that holds all work, as its line and its badge on the gold bar say it (F125, F135.7, F144.4),
 * a time in it dated for an earlier day than the viewer's `today` (`useToday()`).
 */
export function conditionLine(condition: Condition, today: string): ConditionLine {
  const code = condition.code;
  switch (code) {
    case 'outage':
      return {
        title: 'The controller has been unreachable',
        detail: 'Nothing starts until it answers.',
        badge: 'Controller unreachable',
        icon: ServerOff,
      };
    case 'store_update':
      return {
        title: 'Pilot is updating its store',
        detail: 'No chat answers and no job of Pilot’s starts until it is done; work items go on.',
        badge: 'Pilot is updating',
        icon: RefreshCw,
      };
    case 'week_halt':
      return {
        title: 'Work items have been halted at the week’s usage limit',
        detail: `${halted(condition, 'the week’s quota', today)} ${haltDoes(condition)}`,
        badge: 'Halted at the week’s limit',
        icon: OctagonPause,
      };
    case 'five_hour_halt':
      return {
        title: 'Work items have been halted at the five-hour usage limit',
        detail: `${halted(condition, 'the five-hour window’s quota', today)} ${haltDoes(condition)}`,
        badge: 'Halted at the five-hour limit',
        icon: Hourglass,
      };
    default: {
      const unknown: never = code;
      return { title: String(unknown), detail: '', badge: String(unknown), icon: ServerOff };
    }
  }
}

interface OverruleWords {
  /** The button's words. */
  label: string;
  /** What it does: the button's title, and its toast once made. */
  does: string;
}

/**
 * The overrule the week's halt offers, as its button and its toast say it (F135.2): the allowance,
 * its target a fraction, or run-out, to the wall.
 */
export function overruleWords(kind: OverruleKind, target: number | null): OverruleWords {
  switch (kind) {
    case 'allowance': {
      // The API gives the allowance its target.
      const to = PERCENT.format(target!);
      return { label: `Go on to ${to}`, does: `Work items go on until ${to} of the week’s quota is used.` };
    }
    case 'run_out':
      return { label: 'Run it out', does: 'Work items go on until the week’s quota runs out.' };
    default: {
      const unknown: never = kind;
      return { label: String(unknown), does: String(unknown) };
    }
  }
}

/** A stop no one of the app's people made, as its line and its session log's tail say it. */
type StopWords =
  /**
   * Pilot's stop: a usage halt's hard stop (F135.6), for the halt that holds it now, or the store's
   * update's (F144.4); its line's words and its session log tail's.
   */
  | { kind: 'pilot'; line: string; tail: string }
  /** Its environment stopped under it or settled in error, a stop made elsewhere (F71). */
  | { kind: 'elsewhere'; cause: string };

const HALT_TAIL = 'Stopped by Pilot at the usage limit';

/**
 * Why a work item stopped when no one of the app's people stopped it (F26.1, F69.2): a usage halt's
 * hard stop, the store's update, or a stop made elsewhere; null for any other stop.
 */
function stopWords(work: Work): StopWords | null {
  const cause = work.stopped_cause;
  if (cause === null) return null;
  // A stop made elsewhere is its environment's: a Session stopped under its turn has one.
  const environment = () => work.environment!.name;
  switch (cause) {
    case 'week_halt':
      return { kind: 'pilot', line: 'Stopped at the week’s limit', tail: HALT_TAIL };
    case 'five_hour_halt':
      return { kind: 'pilot', line: 'Stopped at the five-hour limit', tail: HALT_TAIL };
    case 'usage_limit':
      return { kind: 'pilot', line: 'Stopped at the usage limit', tail: HALT_TAIL };
    case 'store_update':
      return { kind: 'pilot', line: 'Stopped for Pilot’s update', tail: 'Stopped by Pilot for its update' };
    case 'environment_stopped':
      return { kind: 'elsewhere', cause: `${environment()} was stopped` };
    case 'environment_deleting':
      return { kind: 'elsewhere', cause: `${environment()} is being deleted` };
    case 'environment_gone':
      return { kind: 'elsewhere', cause: `${environment()} is gone` };
    case 'environment_error':
      return { kind: 'elsewhere', cause: `${environment()} is in error` };
    default: {
      const unknown: never = cause;
      return { kind: 'elsewhere', cause: String(unknown) };
    }
  }
}

/**
 * A work item's one line on the timeline while its session is held, starts or runs, or owes its
 * nudge: the working cue's state, or the call it runs alone (D167).
 */
interface WorkCue {
  kind: 'cue';
  activity: Activity;
  /** The call it runs, in the phase's place, worded as the chat words a running call. */
  step: Words[] | null;
  /** What follows the phase after a " · ": a sub-agent's description while it runs. */
  detail: string | null;
}

/** "Stopped · <time>", or Pilot's stop's words before it, and the cause of a stop made elsewhere. */
interface WorkStopped {
  kind: 'stopped';
  /** "Stopped", or "Stopped at the week’s limit" and its like (F135.6), or "Stopped for Pilot’s update" (F144.4). */
  text: string;
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
/** A run whose turn ended under a halt or a pause, its nudge owed, while nothing holds that nudge. */
const NUDGE_DUE: Activity = { kind: 'waiting', phase: 'Waiting for its nudge' };

/**
 * What holds the nudge owed to a run whose turn ended under a halt or a pause, in a held start's
 * words, or that the nudge is due once nothing does (F135.3, F141.3).
 */
export function nudgeCue(work: Work): Activity {
  return work.held_reason === null ? NUDGE_DUE : { kind: 'waiting', phase: heldReasonLabel(work.held_reason, work.held_running) };
}

const cue = (activity: Activity, step: Words[] | null = null, detail: string | null = null): WorkCue => ({
  kind: 'cue',
  activity,
  step,
  detail,
});

/**
 * A work item's one line (F26.1, F26.2): why the gate holds its start; the current line as the
 * chat words its cue, the call it runs alone in the phase's place and Thinking or Writing with
 * nothing after it (D167), or that it starts, or waits for Pilot, before its session gives one;
 * "Stopped · <time>" with a stop made elsewhere's cause, or a usage halt's hard stop's "Stopped at
 * the week’s limit · <time>" and its like (F135.6), or the store's update's "Stopped for Pilot’s
 * update · <time>" (F144.4); the error it failed on; what holds the nudge
 * owed to a run whose turn ended under a halt or a pause, in a held start's words (F135.3, F141.3).
 * Null once its turn ended done, when its done line stands for it.
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
    case 'stopped': {
      const words = stopWords(work);
      return {
        kind: 'stopped',
        text: words?.kind === 'pilot' ? words.line : 'Stopped',
        at: work.stopped_at,
        cause: words?.kind === 'elsewhere' ? words.cause : null,
      };
    }
    case 'failed':
      return { kind: 'failed', error: work.error };
    case 'idle':
      if (!work.nudge_owed) return null;
      return cue(nudgeCue(work));
    case 'ended':
      return null;
    default: {
      const unknown: never = work.state;
      return cue({ kind: 'working', phase: String(unknown) });
    }
  }
}

/**
 * A current line's call as the chat words a running one: its verb alone while its input streams
 * in, before the call's line gives its target.
 */
function runningWords(call: LineStep | null): Words[] | null {
  if (call === null || call.tool === null) return null;
  return summarizeTool(call.tool, call.input === null ? null : (call.input as Record<string, unknown>)).running;
}

/**
 * The relay's current line in the chat cue's words (design 2 §9.5): the server's own while the
 * session comes up; the call it runs, else "Working"; Thinking and Writing alone, never the call
 * that finished before them; the sub-agent it waits for, and its description.
 */
function lineCue(line: CurrentLine): WorkCue {
  switch (line.state) {
    case 'starting':
      return cue({ kind: 'starting', phase: line.text === null ? STARTING.phase : phaseOf(line.text) });
    case 'thinking':
      return cue({ kind: 'thinking', phase: 'Thinking' });
    case 'writing':
      return cue({ kind: 'writing', phase: 'Writing' });
    case 'working':
      return cue({ kind: 'tool', phase: 'Working' }, runningWords(line.step));
    case 'waiting': {
      const type = line.agent?.type ?? null;
      return cue(
        { kind: 'agent', phase: type === null ? 'Waiting for the agent' : `Waiting for the ${type} agent` },
        null,
        line.agent?.description || null,
      );
    }
    default: {
      const unknown: never = line.state;
      return cue({ kind: 'working', phase: String(unknown) });
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
 * A session log's tail once its work runs no turn (F69.2): "Stopped by you", by whom else, by Pilot
 * at the usage limit (F135.6) or for its update (F144.4), or the environment stopped under it, at the
 * stop; "The turn ended" or "Failed", at `endedAt`. Null while it is held, starts or runs, when the
 * working cue is the tail.
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
      const words = stopWords(work);
      const by = work.stopped_by;
      const text =
        words?.kind === 'pilot'
          ? words.tail
          : by !== null
            ? by.handle === selfHandle
              ? 'Stopped by you'
              : `Stopped by ${by.name}`
            : (words?.cause ?? 'Stopped');
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
