/**
 * Create project (F48; D119), at the end of a draft's definition chat, scrolling with it, once the
 * head's `create_refusal` is null: Pilot's turn over and a draft with a valid slug written. While
 * the head gives a reason there is no button at all, and it is never shown disabled. The ready box
 * (ready-box.tsx) holds the button and a muted line saying the project is ready to be created.
 * Pressed, it makes the `opened` transition, by the person, a press that writes (F148); a refusal
 * the head cannot give, no controller or no store environment, comes back as the request's error.
 * It places the setup, Pilot's work: its icon is the job's mark under the mouse (F59.3).
 */

import { Plus } from 'lucide-react';
import { BusyIcon } from '@/components/shared/busy-icon';
import { ReadyBox } from '@/components/shared/ready-box';
import { usePress } from '@/hooks/use-press';
import type { ProjectHead as Project } from '@/hooks/use-projects';
import { usePostProjectsTransitionsByProjectId } from '@/lib/api/generated/hooks';
import { UNTIL_READ } from '@/lib/api/until-read';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const CREATE_FORM = 'project.create';

export function CreateProject({ project }: { project: Project }) {
  // Pending until every query is read again, the head included: until then a second press would
  // ask for the same change.
  const create = usePostProjectsTransitionsByProjectId(UNTIL_READ);
  const press = usePress();
  if (project.create_refusal !== null) return null;
  const pending = press.held !== null || create.isPending;
  const act = () => {
    press.run(() => {
      trackFormSubmit(CREATE_FORM);
      // Succeeded once that read has ended, and by the write's own promise, not in `mutate`'s
      // callbacks: the head read open unmounts the definition chat, and `mutate`'s callbacks with it.
      return create.mutateAsync({ path: { project_id: project.id }, body: { kind: 'opened' } }).then(
        () => trackFormSuccess(CREATE_FORM),
        () => trackFormError(CREATE_FORM),
      );
    });
  };
  return (
    <ReadyBox testId="project.create-ready">
      <button
        type="button"
        className="btn btn-primary btn-sm"
        aria-disabled={pending || undefined}
        title="Hand the project to Pilot: it sets it up and starts the plan"
        onClick={act}
        data-testid="project.create"
      >
        <BusyIcon busy={pending} starts>
          <Plus className="icon" aria-hidden="true" />
        </BusyIcon>
        Create project
      </button>
      <span data-testid="project.create-ready.line">The project is ready to be created.</span>
    </ReadyBox>
  );
}
