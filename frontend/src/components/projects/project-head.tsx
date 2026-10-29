/**
 * A project's head (F2): its name, ticket and repo, linked (F2.1); auto pilot's switch, asking in
 * its dialog as it turns on while confirmations it would take are open (F4.2), its warning
 * triangle while work briefed under the other setting runs (F4.3), or the Finished chip
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
 * In a tight head its parts give way in one order: the repo, the name, the step's name down to its
 * floor, then the members, folding to the first avatars and a count; the ticket, the chips, auto
 * pilot or Create project and the icons keep their size. Where they still run past the head, it
 * stands in its two rows, as on a narrow window: the name and auto pilot, then the step, the
 * members and the icons; a narrow window hides the repo.
 */

import { useCallback, useLayoutEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { Archive, FileText, Files, Flag, MessagesSquare, NotebookText, Plus, TriangleAlert } from 'lucide-react';
import { AutopilotDialog } from '@/components/projects/autopilot-dialog';
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
  ref?: (element: HTMLElement | null) => void;
}

export function ProjectHead({ project, chat, documents, draftTab, ref }: ProjectHeadProps) {
  const draft = project.state === 'draft';
  const [head, setHead] = useState<HTMLElement | null>(null);
  useRows(head);
  const own = useCallback(
    (element: HTMLElement | null) => {
      setHead(element);
      ref?.(element);
    },
    [ref],
  );
  return (
    <header ref={own} className="feed-head" data-testid="project.head">
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
        {project.ticket && (
          <span className="ticket mono" data-testid="project.ticket">
            <LinkedText text={project.ticket} />
          </span>
        )}
        {project.repo && (
          <span className="repo mono" data-testid="project.repo">
            <LinkedText text={project.repo} />
          </span>
        )}
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
      className="btn btn-primary btn-sm head-create"
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

/**
 * Each flip is a transition on the record, by the person, when they flip it (F4.1). Turning it on
 * while confirmations it would have taken are open asks first in its dialog, whose answer turns it
 * on (F4.2).
 */
function Autopilot({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  // The flip stays pending until every query is read again, the head included: until then, a
  // second flip would ask for the same change.
  const flip = usePostProjectsTransitionsByProjectId({ onSuccess: () => queryClient.invalidateQueries() });
  const [asking, setAsking] = useState(false);
  // The dialog asks only while auto pilot is off on an open project: turned on or finished by
  // another session, the server refuses each of its answers.
  if (asking && (project.autopilot || project.state === 'finished')) setAsking(false);
  if (project.state === 'finished') {
    return (
      <span className="chip finished-chip" data-testid="project.finished">
        <Flag className="icon" aria-hidden="true" />
        Finished
      </span>
    );
  }
  const send = (kind: 'autopilot_on' | 'autopilot_off', answerConfirmations = false) => {
    const fields = { kind, answer_confirmations: answerConfirmations };
    trackFormSubmit(AUTOPILOT_FORM, fields);
    flip.mutate(
      { path: { project_id: project.id }, body: answerConfirmations ? fields : { kind } },
      {
        onSuccess: () => {
          trackFormSuccess(AUTOPILOT_FORM, fields);
          setAsking(false);
        },
        onError: () => trackFormError(AUTOPILOT_FORM, fields),
      },
    );
  };
  const toggle = () => {
    if (flip.isPending) return;
    if (project.autopilot) send('autopilot_off');
    else if (project.autopilot_may_take > 0) setAsking(true);
    else send('autopilot_on');
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
      {asking && (
        <AutopilotDialog
          count={project.autopilot_may_take}
          pending={flip.isPending}
          onAnswer={(answerConfirmations) => send('autopilot_on', answerConfirmations)}
        />
      )}
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

// `.avatar.sm` is 24px wide, and each avatar after the first overlaps the one before by 2px.
const AVATAR = 24;
const OVERLAP = 2;
const across = (avatars: number) => avatars * AVATAR - (avatars - 1) * OVERLAP;

/**
 * In the order they joined, overlapping by 2px. In a tight head they give way last, once the step's
 * name is at its floor: they fold to the first avatars and a "+N" count of the rest, its tooltip
 * naming them, one avatar at least showing.
 */
function Members({ members }: { members: Project['members'] }) {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const room = useWidth(box);
  if (members.length === 0) return null;
  // The box is as wide as every avatar until the head takes width from it: the count goes by the
  // width the head leaves it, never by what it shows, so a fold never makes room to unfold.
  const all = across(members.length);
  const shown = room === null || room > all - 0.5 ? members.length : Math.max(1, Math.floor((room + 0.5 - AVATAR) / (AVATAR - OVERLAP)));
  const folded = members.slice(shown);
  return (
    <div
      ref={setBox}
      className="members"
      style={{ flexBasis: all, minWidth: Math.min(all, across(2)) }}
      role="group"
      aria-label="Members"
      data-testid="project.members"
    >
      {members.slice(0, shown).map((member) => (
        <Avatar key={member.handle} who={{ name: member.name, initials: member.initials, slot: member.avatar_slot }} size="sm" />
      ))}
      {folded.length > 0 && (
        <span
          className="avatar sm"
          role="img"
          title={folded.map((member) => member.name).join(', ')}
          aria-label={`${folded.length} more: ${folded.map((member) => member.name).join(', ')}`}
          data-testid="project.members.more"
        >
          +{folded.length}
        </span>
      )}
    </div>
  );
}

/**
 * Stands the head in its two rows while its last part, the menu, runs past it in one: measured in one
 * row whenever the head's width or its parts change.
 */
function useRows(head: HTMLElement | null): void {
  useLayoutEffect(() => {
    if (head === null) return;
    // React writes `className` only when it changes, so the class set here stays.
    const fit = () => {
      head.classList.remove('two-rows');
      const menu = head.querySelector(':scope > .head-row:last-child > :last-child')!;
      head.classList.toggle('two-rows', menu.getBoundingClientRect().right > head.getBoundingClientRect().right);
    };
    // The parent's width is the head's, and its height stays as the head stacks: an observer of the
    // head would be told, within the frame, of the height it just changed.
    const resized = new ResizeObserver(fit);
    resized.observe(head.parentElement!);
    const changed = new MutationObserver(fit);
    changed.observe(head, { childList: true, subtree: true, characterData: true });
    return () => {
      resized.disconnect();
      changed.disconnect();
    };
  }, [head]);
}

/** The element's width, as the window and its neighbours change it; null until it is first measured. */
function useWidth(element: HTMLElement | null): number | null {
  const [width, setWidth] = useState<number | null>(null);
  useLayoutEffect(() => {
    if (element === null) return;
    // The observer reports the width when it starts, and again on every change.
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return width;
}
