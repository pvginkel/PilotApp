/**
 * A project's head (F2): its name, ticket and repo, linked (F2.1); auto pilot's switch, asking in
 * its dialog as it turns on while confirmations it would take are open (F4.2), its warning
 * triangle while work briefed under the other setting runs (F4.3), or the Finished chip
 * once finished (F2.6, F4.1); the step button and its plan (F2.2, F3); the members
 * (F2.5); the plan's notes (F2.7); the project's menu (F2.4). The side panel beside it is always
 * open, and nothing in the head toggles it (F2.3): the chat is its Chat tab, the documents and the
 * handbook its Documents tab. A draft, which has no handbook (F129.2), has in its head its name,
 * the Draft chip, its members and its menu (F46.2); its Create project stands at its definition
 * chat's end (`create-project.tsx`). An archived project's reads as it was left, marked archived,
 * its switch not to be flipped (D012). A phone's head is `phone-head.tsx`'s.
 *
 * In a tight head its parts give way in one order: the repo, the name down to its floor, 250px or
 * its own width where it is narrower, the step's name down to its floor, then the members, folding
 * to the first avatars and a count; the ticket, the chips, auto pilot and the icons keep their size,
 * and the step button stands no wider than 350px. Where they still run past the head, it stands in
 * its two rows: the name and auto pilot, the name taking what its row leaves, then the step, the
 * members and the icons.
 */

import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { Archive, Flag, TriangleAlert } from 'lucide-react';
import { AutopilotDialog } from '@/components/projects/autopilot-dialog';
import { NotesButton } from '@/components/projects/plan-notes';
import { StepButton } from '@/components/projects/plan-popover';
import { ProjectMenu } from '@/components/projects/project-menu';
import { Avatar } from '@/components/shared/avatar';
import { LinkedText } from '@/components/shared/linked-text';
import { useAutopilotFlip } from '@/hooks/use-autopilot-flip';
import type { ProjectHead as Project } from '@/hooks/use-projects';
import { STOPPABLE } from '@/hooks/use-work-acts';
import { useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

interface ProjectHeadProps {
  project: Project;
  ref?: (element: HTMLElement | null) => void;
}

export function ProjectHead({ project, ref }: ProjectHeadProps) {
  const draft = project.state === 'draft';
  const [head, setHead] = useState<HTMLElement | null>(null);
  useRows(head);
  const name = project.name ?? 'New project';
  const heading = useNameFloor(name);
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
        <h1 ref={heading} data-testid="project.name">
          <LinkedText text={name} />
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
        {!draft && <Autopilot project={project} />}
      </div>
      <div className="head-row">
        {!draft && <StepButton tasks={project.tasks} />}
        <Members members={project.members} />
        {!draft && <NotesButton notes={project.notes} />}
        <ProjectMenu project={project} />
      </div>
    </header>
  );
}

const AUTOPILOT_FORM = 'project.autopilot';

/**
 * Each flip is a transition on the record, by the person, when they flip it (F4.1). Turning it on
 * while confirmations it would have taken are open asks first in its dialog, whose answer turns it
 * on (F4.2). On a phone the switch has no label, its name its accessible one, and the Finished chip
 * shows its icon alone.
 */
export function Autopilot({ project, phone = false }: { project: Project; phone?: boolean }) {
  const flip = useAutopilotFlip(project.id);
  const [asking, setAsking] = useState(false);
  // The dialog asks only while auto pilot is off on an open, unarchived project: turned on,
  // finished or archived by another session, the server refuses each of its answers.
  if (asking && (project.autopilot || project.state === 'finished' || project.archived)) setAsking(false);
  if (project.state === 'finished') {
    return (
      <span className="chip finished-chip" title={phone ? 'Finished' : undefined} data-testid="project.finished">
        <Flag className="icon" aria-hidden="true" />
        <span className="chip-label">Finished</span>
      </span>
    );
  }
  const send = (kind: 'autopilot_on' | 'autopilot_off', answerConfirmations = false) => {
    const fields = { kind, answer_confirmations: answerConfirmations };
    trackFormSubmit(AUTOPILOT_FORM, fields);
    flip.mutate(answerConfirmations ? fields : { kind }, {
      onSuccess: () => {
        trackFormSuccess(AUTOPILOT_FORM, fields);
        setAsking(false);
      },
      onError: () => trackFormError(AUTOPILOT_FORM, fields),
    });
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
        aria-disabled={flip.isPending || undefined}
        disabled={project.archived}
        title="Auto pilot hands the project to Pilot; it still asks on the held column"
        aria-label={phone ? 'Auto pilot' : undefined}
        onClick={toggle}
        data-testid="project.autopilot"
      >
        <span className="track">
          <span className="knob" />
        </span>
        {!phone && 'Auto pilot'}
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

// `.avatar.sm` is 29px wide, and each avatar after the first overlaps the one before by 2px.
const AVATAR = 29;
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

// The least width the name gives way to in a tight head's one row, where it is wider.
const NAME_FLOOR = 250;

/**
 * Sets the name's floor, `--name-floor` (project-head.css), from the name measured whole: no CSS
 * width is the lesser of a length and the content's.
 */
function useNameFloor(name: string) {
  const heading = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    const element = heading.current!;
    element.style.removeProperty('--name-floor');
    element.style.setProperty('--name-floor', `${Math.min(NAME_FLOOR, element.scrollWidth)}px`);
  }, [name]);
  return heading;
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
