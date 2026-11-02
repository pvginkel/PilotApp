/**
 * The step button (F2.2) and the plan it opens (F3.1): the plan's steps behind the steps' button,
 * each step's open notes beside it (F3.6). On the phone the Plan tab is the plan as a page, its
 * rows a thumb's height (F3.7).
 */

import { StepRow, StepsButton, type Step } from '@/components/shared/steps-button';
import type { ProjectHead } from '@/hooks/use-projects';
import { planStepMark } from '@/lib/utils/status-labels';

type Task = ProjectHead['tasks'][number];

const stepsOf = (tasks: Task[]): Step[] =>
  tasks.map((task) => ({ id: task.id, title: task.title, mark: planStepMark(task.status), notes: task.notes }));

export function StepButton({ tasks }: { tasks: Task[] }) {
  return <StepsButton steps={stepsOf(tasks)} name="The plan" anchorClassName="step-anchor" testId="project.step" popoverTestId="project.plan" />;
}

/** The Plan tab on the phone: the popover's heading and steps as a page, "No steps yet." while it has none. */
export function PlanPage({ tasks }: { tasks: Task[] }) {
  const steps = stepsOf(tasks);
  const done = steps.filter((step) => step.mark === 'done').length;
  return (
    <section className="plan-page" aria-label="The plan" data-testid="project.plan-page">
      <h2 data-testid="project.plan-page.heading">{`The plan${steps.length > 0 ? ` · ${done} of ${steps.length} done` : ''}`}</h2>
      {steps.length > 0 ? (
        <ol>
          {steps.map((step) => (
            <StepRow key={step.id} step={step} testId="project.plan.step" />
          ))}
        </ol>
      ) : (
        <p className="none" data-testid="project.plan-page.none">
          No steps yet.
        </p>
      )}
    </section>
  );
}
