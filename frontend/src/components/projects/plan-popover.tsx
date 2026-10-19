/**
 * The step button (F2.2) and the plan it opens (F3.1): the plan's donut and the first step in
 * progress; the steps in order, done ones ticked, every step in progress highlighted, side by side
 * (F3.4), and beside a step with open notes the sticky-note icon, listing them on hover and on a
 * tap (F3.6).
 */

import { useState } from 'react';
import { Check, StickyNote } from 'lucide-react';
import { NoteList } from '@/components/projects/plan-notes';
import { LinkedText } from '@/components/shared/linked-text';
import { Popover } from '@/components/shared/popover';
import type { ProjectHead } from '@/hooks/use-projects';
import { planStep, stepReading } from '@/lib/utils/status-labels';

type Progress = ProjectHead['progress'];
type Task = ProjectHead['tasks'][number];

export function StepButton({ progress, tasks }: { progress: Progress; tasks: Task[] }) {
  const reading = stepReading(progress);
  const going = progress.in_progress;
  const tooltip = `${progress.done} of ${progress.total} steps done${going.length > 0 ? ` · in progress: ${going.join('; ')}` : ''}`;
  return (
    <Popover
      label="The plan"
      anchorClassName="step-anchor"
      className="plan-pop"
      testId="project.plan"
      trigger={({ open, toggle }) => (
        <button
          type="button"
          className="btn btn-sm"
          title={tooltip}
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={toggle}
          data-testid="project.step"
        >
          <PlanRing progress={progress} />
          <span className="step-name" data-testid="project.step.name">
            <LinkedText text={reading.text} nested />
          </span>
          {reading.more && <span className="step-more">, …</span>}
        </button>
      )}
    >
      <h3 data-testid="project.plan.heading">
        The plan{progress.total > 0 && ` · ${progress.done} of ${progress.total} done`}
      </h3>
      <ol>
        {tasks.map((task) => (
          <PlanStep key={task.id} task={task} />
        ))}
      </ol>
    </Popover>
  );
}

const RADIUS = 6;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * The plan as a donut from twelve o'clock: the steps done, then those in progress, then the rest.
 * Counts, not places: steps run side by side.
 */
function PlanRing({ progress }: { progress: Progress }) {
  const now = progress.in_progress.length;
  const counted = (
    [
      ['done', progress.done],
      ['now', now],
      ['rest', progress.total - progress.done - now],
    ] as const
  ).filter(([, count]) => count > 0);
  const parts = counted.length > 0 ? counted : ([['rest', 1]] as const);
  const steps = Math.max(1, progress.total);
  const lengths = parts.map(([, count]) => (count / steps) * CIRCUMFERENCE);
  // Each part stops one unit short of the next, so the parts read apart.
  const gap = parts.length > 1 ? 1 : 0;
  return (
    <svg className="plan-ring" viewBox="0 0 16 16" aria-hidden="true" data-testid="project.step.ring">
      {parts.map(([part], index) => (
        <circle
          key={part}
          className={part}
          cx="8"
          cy="8"
          r={RADIUS}
          strokeDasharray={`${Math.max(0.5, lengths[index] - gap).toFixed(2)} ${CIRCUMFERENCE.toFixed(2)}`}
          strokeDashoffset={(-lengths.slice(0, index).reduce((sum, length) => sum + length, 0)).toFixed(2)}
        />
      ))}
    </svg>
  );
}

function PlanStep({ task }: { task: Task }) {
  const { mark, label } = planStep(task.status);
  // The notes list while the mouse is over the icon, or after a tap or a click on it until the next.
  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const notes = task.notes.length > 0;
  const shown = notes && (hovered || pinned);
  return (
    <li className={`plan-step ${mark}`} onPointerLeave={() => setHovered(false)} data-testid="project.plan.step" data-state={mark}>
      <span className="mark" role="img" aria-label={label}>
        {mark === 'done' && <Check className="icon" aria-hidden="true" />}
      </span>
      <span className="step-title" data-testid="project.plan.step.title">
        <LinkedText text={task.title} />
      </span>
      {notes && (
        <button
          type="button"
          className="step-notes"
          title="The step's notes"
          aria-label="The step's notes"
          aria-expanded={shown}
          onPointerEnter={(event) => event.pointerType === 'mouse' && setHovered(true)}
          onClick={() => setPinned(!pinned)}
          data-testid="project.plan.step.notes-button"
        >
          <StickyNote className="icon" aria-hidden="true" />
        </button>
      )}
      {shown && <NoteList notes={task.notes} testId="project.plan.step.notes" />}
    </li>
  );
}
