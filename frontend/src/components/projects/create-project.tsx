/**
 * Create project (F48; D119), at the end of a draft's definition chat, scrolling with it, once the
 * head's `create_refusal` is null: Pilot's turn over and a draft with a valid slug written. While
 * the head gives a reason there is no button at all, and it is never shown disabled. A box with a
 * border, as wide as what it holds and centred, holds the button and a muted line saying the project
 * is ready to be created: above 900px the button left of the line, at 900px and below above it (the
 * mockup's `.create-ready`). Pressed, it makes the `opened` transition, by the person; a refusal the
 * head cannot give, no controller or no store environment, comes back as the request's error.
 */

import { Plus } from 'lucide-react';
import type { ProjectHead as Project } from '@/hooks/use-projects';
import { usePostProjectsTransitionsByProjectId } from '@/lib/api/generated/hooks';
import { UNTIL_READ } from '@/lib/api/until-read';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const CREATE_FORM = 'project.create';

export function CreateProject({ project }: { project: Project }) {
  // Pending until every query is read again, the head included: until then a second press would
  // ask for the same change.
  const create = usePostProjectsTransitionsByProjectId(UNTIL_READ);
  if (project.create_refusal !== null) return null;
  const press = () => {
    if (create.isPending) return;
    trackFormSubmit(CREATE_FORM);
    // Succeeded once that read has ended, and by the write's own promise, not in `mutate`'s
    // callbacks: the head read open unmounts the definition chat, and `mutate`'s callbacks with it.
    create.mutateAsync({ path: { project_id: project.id }, body: { kind: 'opened' } }).then(
      () => trackFormSuccess(CREATE_FORM),
      () => trackFormError(CREATE_FORM),
    );
  };
  return (
    <div
      className="flex max-w-full items-center gap-3.5 self-center rounded-lg border py-2.5 pr-[18px] pl-2.5 text-center text-sm/[1.6] text-muted-foreground [@media(max-width:900px)]:flex-col [@media(max-width:900px)]:gap-2 [@media(max-width:900px)]:px-[18px] [@media(max-width:900px)]:pt-3.5 [@media(max-width:900px)]:pb-3"
      data-testid="project.create-ready"
    >
      <button
        type="button"
        className="btn btn-primary btn-sm"
        aria-disabled={create.isPending || undefined}
        title="Hand the project to Pilot: it sets it up and starts the plan"
        onClick={press}
        data-testid="project.create"
      >
        <Plus className="icon" aria-hidden="true" />
        Create project
      </button>
      <span data-testid="project.create-ready.line">The project is ready to be created.</span>
    </div>
  );
}
