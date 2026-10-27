/**
 * A project's head (F2): its name, ticket and repo, linked (F2.1); auto pilot's switch, its
 * warning triangle while work briefed under the other setting runs (F4.3), or the Finished chip
 * once finished (F2.6, F4.1); the step button and its plan (F2.2, F3); the members
 * (F2.5); Discuss, toggling the side panel's Chat tab with nothing quoted and carrying the unread
 * dot (F2.3, F39.2, F43), the Documents button, toggling its Documents tab, and the handbook,
 * opening in the overlay (F2.3, F129.4); the plan's notes (F2.7); the project's menu (F2.4). A draft, which
 * has no handbook (F129.2), has in its head its name, the Draft chip, Create project, its members,
 * the draft-panel toggle, toggling the side panel's Draft tab (F46.2), and its menu. Create project
 * is disabled, its reason on it, while the head's `create_refusal` gives one (F48.1); pressed, the
 * head is the open project's once it is read again. An archived project's reads as it was left,
 * marked archived, its switch not to be flipped (D012).
 *
 * On a narrow window it stands in its two rows: the name and auto pilot, then the step, the
 * members and the icons, the repo hidden.
 */

import type { Ref } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { Archive, FileText, Files, Flag, MessagesSquare, NotebookText, Plus, TriangleAlert } from 'lucide-react';
import { NotesButton } from '@/components/projects/plan-notes';
import { StepButton } from '@/components/projects/plan-popover';
import { ProjectMenu } from '@/components/projects/project-menu';
import { Avatar } from '@/components/shared/avatar';
import { LinkedText } from '@/components/shared/linked-text';
import { useChatDot } from '@/hooks/use-chats';
import type { ProjectHead as Project } from '@/hooks/use-projects';
import { STOPPABLE } from '@/hooks/use-work-acts';
import { useGetProjectsTimelineByProjectId, usePostProjectsTransitionsByProjectId } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';
import { cn } from '@/lib/utils';

/** A tab of the side panel: whether it is showing, and its toggle. */
interface Toggled {
  shown: boolean;
  toggle: () => void;
}

interface ProjectHeadProps {
  project: Project;
  /** The side panel's Chat tab. */
  chat: Toggled;
  /** The side panel's Documents tab. */
  documents: Toggled;
  /** A draft's side panel's Draft tab. */
  draftTab: Toggled;
  ref?: Ref<HTMLElement>;
}

export function ProjectHead({ project, chat, documents, draftTab, ref }: ProjectHeadProps) {
  const draft = project.state === 'draft';
  return (
    <header ref={ref} className="feed-head" data-testid="project.head">
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
        {draft ? <CreateButton project={project} /> : <Autopilot project={project} />}
      </div>
      <div className="head-row">
        {!draft && <StepButton progress={project.progress} tasks={project.tasks} />}
        <Members members={project.members} />
        {!draft && <DiscussButton projectId={project.id} {...chat} />}
        {!draft && <DocumentsButton {...documents} />}
        {!draft && <HandbookButton projectId={project.id} />}
        {!draft && <NotesButton notes={project.notes} />}
        {draft && <DraftButton {...draftTab} />}
        <ProjectMenu project={project} />
      </div>
    </header>
  );
}

/** Discuss for the whole project: the side panel's Chat tab, closing the panel where it is the tab showing; its dot while a reply is unread. */
function DiscussButton({ projectId, shown, toggle }: Toggled & { projectId: string }) {
  const unread = useChatDot(projectId);
  return (
    <button
      type="button"
      className={cn('btn btn-ghost btn-sm btn-icon head-icon head-discuss', shown && 'on')}
      onClick={toggle}
      aria-pressed={shown}
      title="Discuss the project with Pilot"
      aria-label={unread ? 'Discuss the project with Pilot, a reply unread' : 'Discuss the project with Pilot'}
      data-testid="project.discuss"
    >
      <MessagesSquare className="icon" aria-hidden="true" />
      {unread && <span className="unread" data-testid="project.discuss.unread" />}
    </button>
  );
}

/** The side panel's Documents tab, closing the panel where it is the tab showing. */
function DocumentsButton({ shown, toggle }: Toggled) {
  return (
    <button
      type="button"
      className={cn('btn btn-ghost btn-sm btn-icon head-icon', shown && 'on')}
      onClick={toggle}
      aria-pressed={shown}
      title="The project’s documents"
      aria-label="The project’s documents"
      data-testid="project.documents"
    >
      <Files className="icon" aria-hidden="true" />
    </button>
  );
}

/** A draft's side panel's Draft tab, closing the panel where it is the tab showing (F46.2). */
function DraftButton({ shown, toggle }: Toggled) {
  return (
    <button
      type="button"
      className={cn('btn btn-ghost btn-sm btn-icon head-icon', shown && 'on')}
      onClick={toggle}
      aria-pressed={shown}
      title="The draft: what Pilot will set up"
      aria-label="The draft"
      data-testid="project.draft-panel"
    >
      <FileText className="icon" aria-hidden="true" />
    </button>
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

const CREATE_FORM = 'project.create';

const CREATE_HOW = 'Hand the project to Pilot: it sets it up and starts the plan';

/** Create project (F48): an `opened` transition, by the person, when they press it. */
function CreateButton({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  // Pending until every query is read again, the head included: until then a second press would
  // ask for the same change. Succeeded here, not in `mutate`'s callbacks: the head read open
  // unmounts the button, and `mutate`'s callbacks with it.
  const create = usePostProjectsTransitionsByProjectId({
    onSuccess: async () => {
      await queryClient.invalidateQueries();
      trackFormSuccess(CREATE_FORM);
    },
  });
  const refusal = project.create_refusal;
  const press = () => {
    trackFormSubmit(CREATE_FORM);
    create.mutate({ path: { project_id: project.id }, body: { kind: 'opened' } }, { onError: () => trackFormError(CREATE_FORM) });
  };
  return (
    <button
      type="button"
      className="btn btn-primary btn-sm"
      disabled={refusal !== null || create.isPending}
      title={refusal === null ? CREATE_HOW : `Cannot create ${project.name ?? 'New project'} because ${refusal}`}
      onClick={press}
      data-testid="project.create"
    >
      <Plus className="icon" aria-hidden="true" />
      Create project
    </button>
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
    <>
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
      <BriefedOtherwise project={project} />
    </>
  );
}

const BRIEFED_OTHERWISE = 'The change applies to work started from now on: a running session keeps the grants it was briefed with';

/**
 * The warning triangle beside the switch while a work item runs, starts or waits at the gate that
 * its start briefed under the switch's other setting (F4.3), as the timeline reads it.
 */
function BriefedOtherwise({ project }: { project: Project }) {
  const { data } = useGetProjectsTimelineByProjectId({ path: { project_id: project.id } });
  const otherwise = (data?.items ?? []).some(
    ({ work }) => work !== null && STOPPABLE.includes(work.state) && work.autopilot !== project.autopilot,
  );
  if (!otherwise) return null;
  return (
    <span className="switch-warning" role="img" aria-label={BRIEFED_OTHERWISE} title={BRIEFED_OTHERWISE} data-testid="project.autopilot.warning">
      <TriangleAlert className="icon" aria-hidden="true" />
    </span>
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
