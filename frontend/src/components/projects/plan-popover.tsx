/**
 * The step button (F2.2) and the plan it opens (F3.1): the plan's steps behind the steps' button,
 * each step's open notes beside it (F3.6).
 */

import { StepsButton } from '@/components/shared/steps-button';
import type { ProjectHead } from '@/hooks/use-projects';
import { planStepMark } from '@/lib/utils/status-labels';

type Task = ProjectHead['tasks'][number];

export function StepButton({ tasks }: { tasks: Task[] }) {
  return (
    <StepsButton
      steps={tasks.map((task) => ({ id: task.id, title: task.title, mark: planStepMark(task.status), notes: task.notes }))}
      name="The plan"
      anchorClassName="step-anchor"
      testId="project.step"
      popoverTestId="project.plan"
    />
  );
}
