/**
 * A list of steps behind a button, the plan's step button (F2.2, F3.1) and a work item's progress
 * button (F145.2, F145.3) alike: the donut of the steps done, in progress and the rest, and the
 * first step in progress by name, ", …" when more are; with none in progress "Not started",
 * "N of M done" or "All steps done". Its popover lists the steps in order, done ones ticked, every
 * step in progress highlighted, side by side (F3.4), how many are done in its heading, and beside a
 * step with open notes the sticky-note icon, listing them on hover and on a tap (F3.6).
 */

import { useLayoutEffect, useRef, useState } from 'react';
import { Check, StickyNote } from 'lucide-react';
import { NoteList } from '@/components/projects/plan-notes';
import { LinkedText } from '@/components/shared/linked-text';
import { Popover } from '@/components/shared/popover';
import type { ProjectHead } from '@/hooks/use-projects';
import { cn } from '@/lib/utils';
import { stepMarkLabel, stepReading, type StepMark } from '@/lib/utils/status-labels';

type Note = ProjectHead['notes'][number];

export interface Step {
  id: string;
  title: string;
  mark: StepMark;
  notes?: Note[];
}

interface StepsButtonProps {
  /** The steps in order. */
  steps: Step[];
  /** The popover's accessible name, and its heading before the count: "The plan". */
  name: string;
  anchorClassName: string;
  /** The button's test id, its ring's and its name's under it. */
  testId: string;
  /** The popover's test id, its heading's and its steps' under it. */
  popoverTestId: string;
}

// The least width the step's name gives way to in a tight space: about three letters and the ellipsis.
const NAME_FLOOR = 28;

export function StepsButton({ steps, name, anchorClassName, testId, popoverTestId }: StepsButtonProps) {
  const done = steps.filter((step) => step.mark === 'done').length;
  const going = steps.filter((step) => step.mark === 'now').map((step) => step.title);
  const reading = stepReading({ done, total: steps.length, in_progress: going });
  const button = useRef<HTMLButtonElement>(null);
  // No CSS width is the lesser of a length and the content's, so the anchor's least width is set
  // here, from the button and its name measured whole: the button with its name at the floor, or
  // whole where the name is shorter.
  useLayoutEffect(() => {
    const own = button.current!;
    const anchor = own.parentElement!;
    anchor.style.minWidth = '';
    const width = own.querySelector('.step-name')!.getBoundingClientRect().width;
    anchor.style.minWidth = `${own.getBoundingClientRect().width - width + Math.min(NAME_FLOOR, width)}px`;
  }, [reading.text, reading.more]);
  const tooltip = stepsTooltip(done, steps.length, going);
  return (
    <Popover
      label={name}
      anchorClassName={cn('steps-anchor', anchorClassName)}
      className="plan-pop"
      testId={popoverTestId}
      trigger={({ open, toggle }) => (
        <button
          ref={button}
          type="button"
          className="btn btn-sm"
          title={tooltip}
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={toggle}
          data-testid={testId}
        >
          <StepRing done={done} now={going.length} total={steps.length} testId={`${testId}.ring`} />
          <span className="step-name" data-testid={`${testId}.name`}>
            <LinkedText text={reading.text} nested />
          </span>
          {reading.more && <span className="step-more">, …</span>}
        </button>
      )}
    >
      <h3 data-testid={`${popoverTestId}.heading`}>
        {name}
        {steps.length > 0 && ` · ${done} of ${steps.length} done`}
      </h3>
      <ol>
        {steps.map((step) => (
          <StepRow key={step.id} step={step} testId={`${popoverTestId}.step`} />
        ))}
      </ol>
    </Popover>
  );
}

/** The button's title: how many steps are done and which are in progress. */
export const stepsTooltip = (done: number, total: number, going: string[]) =>
  `${done} of ${total} steps done${going.length > 0 ? ` · in progress: ${going.join('; ')}` : ''}`;

const RADIUS = 6;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * The steps as a donut from twelve o'clock: those done, then those in progress, then the rest.
 * Counts, not places: steps run side by side.
 */
export function StepRing({ done, now, total, testId }: { done: number; now: number; total: number; testId: string }) {
  const counted = (
    [
      ['done', done],
      ['now', now],
      ['rest', total - done - now],
    ] as const
  ).filter(([, count]) => count > 0);
  const parts = counted.length > 0 ? counted : ([['rest', 1]] as const);
  const steps = Math.max(1, total);
  const lengths = parts.map(([, count]) => (count / steps) * CIRCUMFERENCE);
  // Each part stops one unit short of the next, so the parts read apart.
  const gap = parts.length > 1 ? 1 : 0;
  return (
    <svg className="plan-ring" viewBox="0 0 16 16" aria-hidden="true" data-testid={testId}>
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

export function StepRow({ step, testId }: { step: Step; testId: string }) {
  const { mark } = step;
  // The notes list while the mouse is over the icon, or after a tap or a click on it until the next.
  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const notes = step.notes ?? [];
  const shown = notes.length > 0 && (hovered || pinned);
  return (
    <li className={`plan-step ${mark}`} onPointerLeave={() => setHovered(false)} data-testid={testId} data-state={mark}>
      <span className="mark" role="img" aria-label={stepMarkLabel(mark)}>
        {mark === 'done' && <Check className="icon" aria-hidden="true" />}
      </span>
      <span className="step-title" data-testid={`${testId}.title`}>
        <LinkedText text={step.title} />
      </span>
      {notes.length > 0 && (
        <button
          type="button"
          className="step-notes"
          title="The step's notes"
          aria-label="The step's notes"
          aria-expanded={shown}
          onPointerEnter={(event) => event.pointerType === 'mouse' && setHovered(true)}
          onClick={() => setPinned(!pinned)}
          data-testid={`${testId}.notes-button`}
        >
          <StickyNote className="icon" aria-hidden="true" />
        </button>
      )}
      {shown && <NoteList notes={notes} testId={`${testId}.notes`} />}
    </li>
  );
}
