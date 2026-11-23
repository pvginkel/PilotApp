/**
 * The badge of the time a running work item still takes (F156.8), one form after a project's name
 * and after a running work item's time: a clock and the time left, "25 min", "1 h", "3 h", as the
 * server rounds it; longer than usual (F156.7), red with the clock's alert: an em dash where the
 * time stood, the time left on a step the workflow marked, or the icon alone (status-labels.ts).
 * Every form is a button that opens its figures under it (F156.13), on hover off a phone and on a
 * press, closed by a press elsewhere, Esc or the badge: a red badge's sentence first (F156.14), else
 * in a project's head the work item's title, then the table of the running steps and the run, as
 * the server gives them, and under it each step's longest. A badge at rest with no row to show is
 * words alone, with no hover and no press.
 */

import { useCallback, useState, type ReactNode } from 'react';
import { Clock, ClockAlert } from 'lucide-react';
import { useDismiss } from '@/hooks/use-dismiss';
import type { components } from '@/lib/api/generated/types';
import { cn } from '@/lib/utils';
import { estimateAlertSentence, estimateBadge, estimateLeftLabel, estimateRedLine, minutesWords } from '@/lib/utils/status-labels';

type Estimate = components['schemas']['TimelineSchema.1fdd8ae.EstimateSchema'];

interface EtaBadgeProps {
  estimate: Estimate;
  /** The work item the figures name, in a project's head; none on the work item itself. */
  title?: string | null;
  testId: string;
}

export function EtaBadge({ estimate, title = null, testId }: EtaBadgeProps) {
  const { alert, text } = estimateBadge(estimate);
  if (!alert && estimate.step_figures.length === 0 && estimate.run_figures === null) {
    return (
      <div className="eta-wrap">
        {/* At rest the server gives the time left. */}
        <span className="eta-badge" role="img" aria-label={estimateLeftLabel(text!)} data-testid={testId}>
          <Clock className="icon" aria-hidden="true" />
          <span>{text}</span>
        </span>
      </div>
    );
  }
  const says = alert ? estimateAlertSentence(estimate, title) : null;
  // The button's name replaces its text: a time left shown opens it, then the sentence.
  const left = text !== null && estimate.longer_than_usual !== 'outrun' ? estimateLeftLabel(text) : null;
  const name = [left, says].filter((part) => part !== null).join('. ');
  return (
    <Figures estimate={estimate} alert={alert} text={text} name={name} testId={testId}>
      {says !== null ? (
        <p className="eta-says" data-testid={`${testId}.says`}>
          {says}
        </p>
      ) : (
        title !== null && (
          <p className="eta-title" data-testid={`${testId}.title`}>
            {title}
          </p>
        )
      )}
    </Figures>
  );
}

interface FiguresProps {
  estimate: Estimate;
  alert: boolean;
  text: string | null;
  name: string;
  testId: string;
  /** What stands over the table: the sentence, or the title. */
  children: ReactNode;
}

function Figures({ estimate, alert, text, name, testId, children }: FiguresProps) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const anchor = useDismiss('plan', open, close);
  const { step_figures: steps, run_figures: run } = estimate;
  const table = steps.length > 0 || run !== null;
  const Icon = alert ? ClockAlert : Clock;
  return (
    <div className="eta-wrap" ref={anchor} onPointerEnter={() => place(anchor.current!)}>
      <button
        type="button"
        className={cn('eta-badge', alert && 'long')}
        onClick={() => {
          place(anchor.current!);
          setOpen(!open);
        }}
        aria-expanded={open}
        aria-label={name}
        data-testid={testId}
      >
        <Icon className="icon" aria-hidden="true" />
        {text !== null && <span>{text}</span>}
      </button>
      <div className={cn('eta-pop', table && 'figures')} role="tooltip" data-testid={`${testId}.pop`}>
        {children}
        {table && (
          <table className="eta-figures" data-testid={`${testId}.figures`}>
            <thead>
              <tr>
                <td />
                <th scope="col">So far</th>
                <th scope="col">Normal</th>
                <th scope="col">Slow</th>
              </tr>
            </thead>
            <tbody>
              {steps.map((step, index) => (
                <Row key={index} name={step.kind} figures={step} of="step" testId={testId} />
              ))}
              {run !== null && <Row name="The run" figures={run} of="run" testId={testId} />}
            </tbody>
          </table>
        )}
        {steps.map((step, index) => (
          <p key={index} className="eta-red" data-testid={`${testId}.figures.red`}>
            {estimateRedLine(step)}
          </p>
        ))}
      </div>
    </div>
  );
}

/**
 * Keeps the figures inside what clips them, the timeline or the page, 8px in from its edges
 * (shared.css): `--eta-shift`, how far left of the badge the pop starts off a phone, so that its
 * right edge stays inside; `--eta-left` and `--eta-right`, those edges from the pop's containing
 * block, which a work item's figures span on a phone. A closed pop is shown unseen to be measured.
 */
function place(wrap: HTMLDivElement): void {
  const pop = wrap.lastElementChild as HTMLElement;
  wrap.style.setProperty('--eta-shift', '0px');
  pop.style.display = 'block';
  pop.style.visibility = 'hidden';
  const at = pop.getBoundingClientRect();
  const own = paddingBox(pop.offsetParent ?? document.documentElement);
  pop.style.removeProperty('display');
  pop.style.removeProperty('visibility');
  let clip: Element = document.documentElement;
  for (let up = wrap.parentElement; up !== null; up = up.parentElement) {
    if (getComputedStyle(up).overflowX !== 'visible') {
      clip = up;
      break;
    }
  }
  const edges = paddingBox(clip);
  const [left, right] = [edges.left + 8, edges.right - 8];
  wrap.style.setProperty('--eta-shift', `${Math.max(left - at.left, Math.min(0, right - at.right))}px`);
  wrap.style.setProperty('--eta-left', `${left - own.left}px`);
  wrap.style.setProperty('--eta-right', `${own.right - right}px`);
}

/** An element's padding box in the viewport, its scrollbar left out: what clips its content, and what places what it contains. */
function paddingBox(element: Element): { left: number; right: number } {
  const left = element.getBoundingClientRect().left + element.clientLeft;
  return { left, right: left + element.clientWidth };
}

interface RowFigures {
  so_far_minutes: number;
  normal_minutes: number;
  slow_minutes: number;
}

function Row({ name, figures, of, testId }: { name: string; figures: RowFigures; of: 'step' | 'run'; testId: string }) {
  return (
    <tr data-testid={`${testId}.figures.${of}`}>
      <th scope="row">{name}</th>
      <td>{minutesWords(figures.so_far_minutes)}</td>
      <td>{minutesWords(figures.normal_minutes)}</td>
      <td>{minutesWords(figures.slow_minutes)}</td>
    </tr>
  );
}
