/**
 * A project's status as one icon on its tab, in the mockup's live dot's place (F1.3, F141.1), the
 * running glyph pulsing as the dot did; and the pause (F141.2). A click, or a tap on the phone,
 * pauses a project that is not paused, the pause glyph showing under the pointer, and resumes one
 * paused or pausing, the play glyph showing there. There is no dialog: the icon takes the glyph
 * it asked for at once and holds it until the list is read again. An archived project's icon
 * shows its status alone, since the record refuses its pause and its resume (D012).
 */

import type { KeyboardEvent, SyntheticEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Pause, Play, type LucideIcon } from 'lucide-react';
import type { ProjectTab as Project } from '@/hooks/use-projects';
import { usePostProjectsTransitionsByProjectId } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';
import { projectStatusIcon } from '@/lib/utils/status-labels';

const PAUSE_FORM = 'projects.tab.pause';

interface StatusIconProps {
  project: Project;
  archived: boolean;
}

export function StatusIcon({ project, archived }: StatusIconProps) {
  const queryClient = useQueryClient();
  // The write stays pending until every query is read again, the list included.
  const transition = usePostProjectsTransitionsByProjectId({ onSuccess: () => queryClient.invalidateQueries() });
  const status = project.status;
  if (status === null) return null;
  const { label, icon } = projectStatusIcon(status);

  if (archived) {
    return (
      <span className="status-icon" role="img" aria-label={label} title={label} data-testid="projects.tab.status-icon" data-status={status}>
        <Glyph icon={icon} at="rest" name={status} />
      </span>
    );
  }

  const asked = transition.isPending ? transition.variables.body.kind : null;
  const paused = asked === null ? status === 'paused' || status === 'pausing' : asked === 'paused';
  const kind = paused ? 'resumed' : 'paused';
  const what = `${label} · ${paused ? 'Resume' : 'Pause'} the project`;
  const act = (event: SyntheticEvent) => {
    // The tab's link must not open the project too: the click bubbles to it, and so does Enter,
    // which a link turns into a click of its own.
    event.preventDefault();
    event.stopPropagation();
    if (transition.isPending) return;
    const fields = { project: project.id, kind };
    trackFormSubmit(PAUSE_FORM, fields);
    transition.mutate(
      { path: { project_id: project.id }, body: { kind } },
      {
        onSuccess: () => trackFormSuccess(PAUSE_FORM, fields),
        onError: () => trackFormError(PAUSE_FORM, fields),
      },
    );
  };
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') act(event);
  };
  return (
    // The tab is a link, where a button cannot nest: a span acts as one, as NestedLink does.
    <span
      className="status-icon"
      role="button"
      tabIndex={0}
      aria-label={what}
      aria-busy={asked !== null}
      title={what}
      onClick={act}
      onKeyDown={onKeyDown}
      data-testid="projects.tab.status-icon"
      data-status={status}
    >
      {asked === null ? <Glyph icon={icon} at="rest" name={status} /> : <Glyph icon={asked === 'paused' ? Pause : Play} at="rest" name={asked} />}
      <Glyph icon={paused ? Play : Pause} at="hover" name={paused ? 'play' : 'pause'} />
    </span>
  );
}

/** One glyph of the icon: the one at rest, or the one under the pointer and the focus. */
function Glyph({ icon: Icon, at, name }: { icon: LucideIcon; at: 'rest' | 'hover'; name: string }) {
  return (
    <span className={`glyph-${at}`} data-testid={`projects.tab.status-icon.${at}`} data-glyph={name}>
      <Icon className="icon" aria-hidden="true" />
    </span>
  );
}
