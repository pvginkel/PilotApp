/**
 * The project's menu, at the end of its head (F2.4): Join or Leave, each at once with its toast
 * (F127); Finish or Reopen, and Archive, each asking first in a dialog (F5.1, F6, F128.1), Finish's
 * and Archive's naming the running sessions they stop; on an archived project only Bring back,
 * which asks too (F128.3, D012). What follows a write, the toast or the dialog's closing, comes
 * once the list and the head show the new standing.
 */

import { useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Archive, ArchiveRestore, Ellipsis, Flag, RotateCcw, UserMinus, UserPlus, type LucideIcon } from 'lucide-react';
import { ConfirmDialog } from '@/components/shared/dialog';
import { LinkedText } from '@/components/shared/linked-text';
import { Menu, MenuItem } from '@/components/shared/menu';
import type { ProjectHead as Project } from '@/hooks/use-projects';
import { useToast } from '@/hooks/use-toast';
import {
  useDeleteProjectsMembershipByProjectId,
  usePostProjectsMembershipByProjectId,
  usePostProjectsTransitionsByProjectId,
} from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

type Kind = components['schemas']['TransitionRequestSchema.e86ccd6']['kind'];
type Ask = 'finish' | 'reopen' | 'archive' | 'bring-back';

interface Question {
  kind: Kind;
  /** The title is "<verb> <name>?". */
  verb: string;
  lines: string[];
  note?: string;
  act: { label: string; icon: LucideIcon };
}

/** "A", "A and B", "A, B and C". */
const listOf = (names: string[]) => (names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`);

/** The work items whose sessions run, start or are held, which Finish and Archive stop, named; none when there are none. */
function runningLines(project: Project): string[] {
  // A work item always has its title.
  const names = project.running_work.map((work) => work.title!);
  if (names.length === 0) return [];
  return [names.length > 1 ? `${names.length} running sessions stop: ${listOf(names)}.` : `The running session stops: ${names[0]}.`];
}

// The texts are the operator's (D010), the running sessions' line the mockup's with each named
// (F5.1); none names the notifications, which a person assumes to work (D011).
function question(ask: Ask, project: Project): Question {
  switch (ask) {
    case 'finish': {
      const open = project.open_items;
      return {
        kind: 'finished',
        verb: 'Finish',
        lines: [
          ...runningLines(project),
          ...(open > 0 ? [`${open} open item${open > 1 ? 's close' : ' closes'} unanswered.`] : []),
          'Pilot starts nothing more, and auto pilot’s permissions end with the project.',
        ],
        note: 'The timeline and the chat stay, and the project can be reopened.',
        act: { label: 'Finish project', icon: Flag },
      };
    }
    case 'reopen':
      return {
        kind: 'reopened',
        verb: 'Reopen',
        lines: ['Pilot takes the plan up where it stood.', 'Auto pilot stays off until you turn it on.'],
        act: { label: 'Reopen project', icon: RotateCcw },
      };
    case 'archive':
      return {
        kind: 'archived',
        verb: 'Archive',
        lines: [...runningLines(project), 'It leaves the project list for Archived, in the menu beside the list’s head.'],
        note: 'Nothing is deleted: Bring back returns it where it was.',
        act: { label: 'Archive project', icon: Archive },
      };
    case 'bring-back':
      return {
        kind: 'brought_back',
        verb: 'Bring back',
        lines: ['It returns to the project list, where it was.'],
        act: { label: 'Bring back', icon: ArchiveRestore },
      };
    default: {
      const unhandled: never = ask;
      throw new Error(`No question for ${String(unhandled)}`);
    }
  }
}

export function ProjectMenu({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const { showSuccess } = useToast();
  // Each write stays pending until every query is read again, the list's and the head's.
  const refetch = { onSuccess: () => queryClient.invalidateQueries() };
  const join = usePostProjectsMembershipByProjectId(refetch);
  const leave = useDeleteProjectsMembershipByProjectId(refetch);
  const transition = usePostProjectsTransitionsByProjectId(refetch);
  const [asking, setAsking] = useState<Ask | null>(null);
  // The item that opened a dialog is gone once it is chosen: the focus goes back to the menu's button.
  const menuButton = useRef<HTMLButtonElement>(null);
  const name = project.name ?? 'New project';
  const path = { project_id: project.id };

  const membership = (form: 'project.join' | 'project.leave', toast: string) => {
    trackFormSubmit(form);
    (form === 'project.join' ? join : leave).mutate(
      { path },
      {
        onSuccess: () => {
          trackFormSuccess(form);
          showSuccess(toast);
        },
        onError: () => trackFormError(form),
      },
    );
  };

  const confirm = (ask: Ask, kind: Kind) => {
    const form = `project.${ask}`;
    trackFormSubmit(form, { kind });
    transition.mutate(
      { path, body: { kind } },
      {
        onSuccess: () => {
          trackFormSuccess(form, { kind });
          setAsking(null);
        },
        onError: () => trackFormError(form, { kind }),
      },
    );
  };

  const asked = asking && question(asking, project);
  return (
    <>
      <Menu
        label="The project’s menu"
        anchorClassName="head-icon"
        testId="project.menu"
        trigger={({ open, toggle }) => (
          <button
            ref={menuButton}
            type="button"
            className="btn btn-ghost btn-sm btn-icon"
            title="More"
            aria-label="The project’s menu"
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={toggle}
            data-testid="project.menu.button"
          >
            <Ellipsis className="icon" aria-hidden="true" />
          </button>
        )}
      >
        {project.archived ? (
          <MenuItem icon={ArchiveRestore} onSelect={() => setAsking('bring-back')} testId="project.menu.bring-back">
            Bring back
          </MenuItem>
        ) : (
          <>
            {project.member ? (
              <MenuItem
                icon={UserMinus}
                onSelect={() =>
                  membership(
                    'project.leave',
                    project.state === 'finished' ? `You left ${name}.` : `You left ${name}. It moves to Other projects.`,
                  )
                }
                testId="project.menu.leave"
              >
                Leave the project
              </MenuItem>
            ) : (
              <MenuItem icon={UserPlus} onSelect={() => membership('project.join', `You joined ${name}.`)} testId="project.menu.join">
                Join the project
              </MenuItem>
            )}
            {project.state === 'open' && (
              <MenuItem icon={Flag} onSelect={() => setAsking('finish')} testId="project.menu.finish">
                Finish the project…
              </MenuItem>
            )}
            {project.state === 'finished' && (
              <MenuItem icon={RotateCcw} onSelect={() => setAsking('reopen')} testId="project.menu.reopen">
                Reopen the project
              </MenuItem>
            )}
            <MenuItem icon={Archive} onSelect={() => setAsking('archive')} testId="project.menu.archive">
              Archive the project
            </MenuItem>
          </>
        )}
      </Menu>
      {asking && asked && (
        <ConfirmDialog
          title={
            <>
              {asked.verb} <LinkedText text={name} />?
            </>
          }
          lines={asked.lines}
          note={asked.note}
          act={asked.act}
          pending={transition.isPending}
          onConfirm={() => confirm(asking, asked.kind)}
          onCancel={() => setAsking(null)}
          returnFocus={menuButton}
          testId={`project.${asking}-dialog`}
        />
      )}
    </>
  );
}
