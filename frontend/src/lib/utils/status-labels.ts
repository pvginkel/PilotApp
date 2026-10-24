/**
 * How a project's standing reads (STATUS-4): the head's step reading (F2.2), a tab's status line
 * (F1.2), derived from the record, never written by the brain (database.md decision 15), and a
 * step's standing in the plan popover (F3.1). How a work item's session reads: why the gate holds
 * its start (F26.1), why it stopped when no one stopped it (F71), and its session log's tail (F69.2).
 */

import type { components } from '@/lib/api/generated/types';

type ProjectTab = components['schemas']['ProjectListResponseSchema.e86ccd6.ProjectTabSchema'];
type PlanProgress = components['schemas']['ProjectListResponseSchema.e86ccd6.PlanProgressSchema'];
type TaskStatus = components['schemas']['ProjectHeadSchema.e86ccd6.TaskStatus'];
type Work = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema'];
type HeldReason = components['schemas']['TimelineSchema.1fdd8ae.HeldReason'];
type StopCause = components['schemas']['TimelineSchema.1fdd8ae.StopCause'];

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

/** Why the gate holds a work item's start, as its line says it (F26.1, F141.5). */
export function heldReasonLabel(reason: HeldReason): string {
  switch (reason) {
    case 'paused':
      return 'Paused';
    case 'controller_unreachable':
      return 'Waiting for the controller';
    default: {
      const unknown: never = reason;
      return String(unknown);
    }
  }
}

/** Why a work item stopped when its environment was stopped under it, a stop made elsewhere (F26.1, F71). */
function stopCauseLabel(cause: StopCause, environment: string): string {
  switch (cause) {
    case 'environment_stopped':
      return `${environment} was stopped`;
    case 'environment_deleting':
      return `${environment} is being deleted`;
    case 'environment_gone':
      return `${environment} is gone`;
    default: {
      const unknown: never = cause;
      return String(unknown);
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
      const text =
        by !== null
          ? by.handle === selfHandle
            ? 'Stopped by you'
            : `Stopped by ${by.name}`
          : work.stopped_cause !== null
            ? stopCauseLabel(work.stopped_cause, work.environment.name)
            : 'Stopped';
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
