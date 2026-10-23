/**
 * A project's head (F2): its name, ticket and repo, linked (F2.1); auto pilot's switch, or the
 * Finished chip once finished (F2.6, F4.1); the step button and its plan (F2.2, F3); the members
 * (F2.5); the handbook, opening in the overlay (F2.3, F129.4); the plan's notes (F2.7); the
 * project's menu (F2.4). A draft, which has no handbook (F129.2), has in its head its name, the
 * Draft chip, its members and its menu. An archived project's reads as it was left, marked
 * archived, its switch not to be flipped (D012).
 *
 * On a narrow window it stands in its two rows: the name and auto pilot, then the step, the
 * members and the icons, the repo hidden.
 */

import { useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { Archive, Flag, NotebookText } from 'lucide-react';
import { NotesButton } from '@/components/projects/plan-notes';
import { StepButton } from '@/components/projects/plan-popover';
import { ProjectMenu } from '@/components/projects/project-menu';
import { Avatar } from '@/components/shared/avatar';
import { LinkedText } from '@/components/shared/linked-text';
import type { ProjectHead as Project } from '@/hooks/use-projects';
import { usePostProjectsTransitionsByProjectId } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

export function ProjectHead({ project }: { project: Project }) {
  const draft = project.state === 'draft';
  return (
    <header className="feed-head" data-testid="project.head">
      <div className="head-row">
        <h1 data-testid="project.name">
          <LinkedText text={project.name ?? 'New project'} />
        </h1>
        {draft && (
          <span className="chip draft-chip" data-testid="project.draft">
            Draft
          </span>
        )}
        {project.archived && (
          <span className="chip archived-chip" data-testid="project.archived">
            <Archive className="icon" aria-hidden="true" />
            Archived
          </span>
        )}
        <div className="meta">
          {project.ticket && (
            <span className="mono" data-testid="project.ticket">
              <LinkedText text={project.ticket} />
            </span>
          )}
          {project.repo && (
            <span className="repo mono" data-testid="project.repo">
              <LinkedText text={project.repo} />
            </span>
          )}
        </div>
        <div className="grow" />
        {!draft && <Autopilot project={project} />}
      </div>
      <div className="head-row">
        {!draft && <StepButton progress={project.progress} tasks={project.tasks} />}
        <Members members={project.members} />
        {!draft && <HandbookButton projectId={project.id} />}
        {!draft && <NotesButton notes={project.notes} />}
        <ProjectMenu project={project} />
      </div>
    </header>
  );
}

/** The handbook at its address, in the overlay. */
function HandbookButton({ projectId }: { projectId: string }) {
  return (
    <Link
      to="/projects/$projectId/handbook"
      params={{ projectId }}
      className="btn btn-ghost btn-sm btn-icon head-icon"
      title="The handbook"
      aria-label="The handbook"
      data-testid="project.handbook"
    >
      <NotebookText className="icon" aria-hidden="true" />
    </Link>
  );
}

const AUTOPILOT_FORM = 'project.autopilot';

/** Each flip is a transition on the record, by the person, when they flip it (F4.1). */
function Autopilot({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  // The flip stays pending until every query is read again, the head included: until then, a
  // second flip would ask for the same change.
  const flip = usePostProjectsTransitionsByProjectId({ onSuccess: () => queryClient.invalidateQueries() });
  if (project.state === 'finished') {
    return (
      <span className="chip finished-chip" data-testid="project.finished">
        <Flag className="icon" aria-hidden="true" />
        Finished
      </span>
    );
  }
  const toggle = () => {
    if (flip.isPending) return;
    const kind = project.autopilot ? 'autopilot_off' : 'autopilot_on';
    trackFormSubmit(AUTOPILOT_FORM, { kind });
    flip.mutate(
      { path: { project_id: project.id }, body: { kind } },
      {
        onSuccess: () => trackFormSuccess(AUTOPILOT_FORM, { kind }),
        onError: () => trackFormError(AUTOPILOT_FORM, { kind }),
      },
    );
  };
  return (
    <button
      type="button"
      className="switch"
      role="switch"
      aria-checked={project.autopilot}
      disabled={project.archived}
      title="Auto pilot hands the project to Pilot; it still asks on the held column"
      onClick={toggle}
      data-testid="project.autopilot"
    >
      <span className="track">
        <span className="knob" />
      </span>
      Auto pilot
    </button>
  );
}

/** In the order they joined, overlapping by 2px. */
function Members({ members }: { members: Project['members'] }) {
  if (members.length === 0) return null;
  return (
    <div className="members" role="group" aria-label="Members" data-testid="project.members">
      {members.map((member) => (
        <Avatar key={member.handle} who={{ name: member.name, initials: member.initials, slot: member.avatar_slot }} size="sm" />
      ))}
    </div>
  );
}
