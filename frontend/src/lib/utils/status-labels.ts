/**
 * How a project's standing reads (STATUS-4): the head's step reading (F2.2) and a tab's status
 * line (F1.2), derived from the record, never written by the brain (database.md decision 15).
 */

import type { components } from '@/lib/api/generated/types';

type ProjectTab = components['schemas']['ProjectListResponseSchema.e86ccd6.ProjectTabSchema'];
type PlanProgress = components['schemas']['ProjectListResponseSchema.e86ccd6.PlanProgressSchema'];

interface StepReading {
  text: string;
  /** More steps are in progress than the one named: ", …" follows the name, kept when it is cut short. */
  more: boolean;
}

/** The first step in progress by name; else "Not started", "N of M done" or "All steps done". */
function stepReading(progress: PlanProgress): StepReading {
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
