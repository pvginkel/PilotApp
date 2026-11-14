/**
 * The project is ready (F48.3): Create project's box at the timeline's foot while the timeline
 * names the setup the project is ready after, stuck there over what scrolls under it and standing
 * at the timeline's end once scrolled there, on the phone and the desktop. Its Resume makes the
 * `resumed` transition, by the person, as the status icon's does (F141.2), a press that writes
 * (F148) that starts Pilot's work, its play the job's mark under the mouse (F59.3); the timeline
 * read after it names no setup, and the box is gone.
 */

import { Play } from 'lucide-react';
import { BusyIcon } from '@/components/shared/busy-icon';
import { ReadyBox } from '@/components/shared/ready-box';
import { usePress } from '@/hooks/use-press';
import { usePostProjectsTransitionsByProjectId } from '@/lib/api/generated/hooks';
import { UNTIL_READ } from '@/lib/api/until-read';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

const RESUME_FORM = 'timeline.ready.resume';

export function ProjectReady({ projectId }: { projectId: string }) {
  // Pending until every query is read again, the timeline included: until then a second press
  // would ask for a resume the record refuses.
  const resume = usePostProjectsTransitionsByProjectId(UNTIL_READ);
  const press = usePress();
  const pending = press.held !== null || resume.isPending;
  const act = () => {
    press.run(() => {
      const fields = { project: projectId };
      trackFormSubmit(RESUME_FORM, fields);
      // By the write's own promise, not in `mutate`'s callbacks: the timeline read after the resume
      // unmounts the box, and `mutate`'s callbacks with it.
      return resume.mutateAsync({ path: { project_id: projectId }, body: { kind: 'resumed' } }).then(
        () => trackFormSuccess(RESUME_FORM, fields),
        () => trackFormError(RESUME_FORM, fields),
      );
    });
  };
  return (
    <ReadyBox stuck testId="timeline.ready">
      <button
        type="button"
        className="btn btn-primary btn-sm"
        aria-disabled={pending || undefined}
        title="Resume the project: Pilot starts on its plan"
        onClick={act}
        data-testid="timeline.ready.resume"
      >
        <BusyIcon busy={pending} starts>
          <Play className="icon" aria-hidden="true" />
        </BusyIcon>
        Resume
      </button>
      <span data-testid="timeline.ready.line">The project is set up and ready to start.</span>
    </ReadyBox>
  );
}
