/**
 * A project's head on a phone (F2.8, F98.3), one line: the drawer's button; the name, its chip and
 * the ticket, the repo hidden; the auto pilot switch without its label, its warning triangle after
 * it (F4.3), or the Finished chip in its place, the Archived and Finished chips their icon alone,
 * their word the tooltip's and a screen reader's; the plan's donut alone, a tap on it showing the Plan
 * tab (F3.7); the members, two circles at most (F2.5); the plan's notes button while it shows (F2.7);
 * the project's menu (F2.4). A draft's has its name, the Draft chip, its members and its menu. The
 * tabs at the bottom stand for Discuss, the Documents button and the draft-panel toggle, and the
 * Documents tab lists the handbook. A tight head gives way in the name alone, cut to nothing (D073).
 */

import { Archive } from 'lucide-react';
import { PlanDonut } from '@/components/projects/plan-popover';
import { NotesButton } from '@/components/projects/plan-notes';
import { Autopilot } from '@/components/projects/project-head';
import { ProjectMenu } from '@/components/projects/project-menu';
import { Avatar } from '@/components/shared/avatar';
import { LinkedText } from '@/components/shared/linked-text';
import { DrawerButton } from '@/components/shell/drawer';
import type { ProjectHead as Project } from '@/hooks/use-projects';

interface PhoneHeadProps {
  project: Project;
  /** Shows the Plan tab. */
  onPlan: () => void;
}

export function PhoneHead({ project, onPlan }: PhoneHeadProps) {
  const draft = project.state === 'draft';
  return (
    <header className="feed-head phone-head" data-testid="project.head">
      <DrawerButton />
      <h1 data-testid="project.name">
        <LinkedText text={project.name ?? 'New project'} />
      </h1>
      {draft && (
        <span className="chip draft-chip" data-testid="project.draft">
          Draft
        </span>
      )}
      {project.archived && (
        <span className="chip archived-chip" title="Archived" data-testid="project.archived">
          <Archive className="icon" aria-hidden="true" />
          <span className="chip-label">Archived</span>
        </span>
      )}
      {project.ticket && (
        <span className="ticket mono" data-testid="project.ticket">
          <LinkedText text={project.ticket} />
        </span>
      )}
      <div className="grow" />
      {!draft && <Autopilot project={project} phone />}
      {!draft && <PlanDonut tasks={project.tasks} onShow={onPlan} />}
      <Members members={project.members} />
      {!draft && <NotesButton notes={project.notes} />}
      <ProjectMenu project={project} />
    </header>
  );
}

/**
 * Two circles at most, overlapping by 2px: the first member's avatar, then the second's where there
 * are two, or a "+N" for the rest where there are more, its tooltip naming them.
 */
function Members({ members }: { members: Project['members'] }) {
  if (members.length === 0) return null;
  const shown = members.length > 2 ? members.slice(0, 1) : members;
  const rest = members.slice(shown.length);
  const names = rest.map((member) => member.name).join(', ');
  return (
    <div className="members" role="group" aria-label="Members" data-testid="project.members">
      {shown.map((member) => (
        <Avatar key={member.handle} who={{ name: member.name, initials: member.initials, slot: member.avatar_slot }} size="sm" />
      ))}
      {rest.length > 0 && (
        <span className="avatar sm more" role="img" title={names} aria-label={`${rest.length} more: ${names}`} data-testid="project.members.more">
          +{rest.length}
        </span>
      )}
    </div>
  );
}
