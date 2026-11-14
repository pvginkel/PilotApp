/**
 * A done work item's debrief in the overlay (F26.9), at its own address under the session log's,
 * opening where the session log opens and as it does: off a phone its popover over the tab
 * showing, on a phone a view. Its head is "Debrief" over the item's title and the time its turn
 * ended; its body the stage session's own debrief, as prose the frame's full width. An address
 * that names no work item of the project, or one with no debrief, reads "The debrief did not load".
 */

import { NotebookPen } from 'lucide-react';
import { DidNotLoad, Overlay } from '@/components/overlay/overlay';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Time } from '@/components/shared/time';
import { useOverlayClose } from '@/hooks/use-overlay-close';
import { titleOf, type TimelineItem } from '@/hooks/use-timeline';
import { useGetItemsDebriefByItemId, useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

interface DebriefOverlayProps {
  projectId: string;
  /** The work item's id, its session's. */
  sessionId: string;
}

export function DebriefOverlay({ projectId, sessionId }: DebriefOverlayProps) {
  const close = useOverlayClose();
  const timeline = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } });
  const debrief = useGetItemsDebriefByItemId({ path: { item_id: sessionId } });
  useUiStateInstrumentation('overlay.debrief', { isLoading: debrief.isLoading, error: debrief.error });
  const item = timeline.data?.items.find((each) => each.id === sessionId && each.kind === 'work');
  const failed = timeline.error !== null || debrief.error !== null || (timeline.data !== undefined && item === undefined);
  return (
    <Overlay showing={`debrief ${sessionId}`} titles={!failed && item && <Titles item={item} />} foot={null} onClose={close}>
      {failed ? (
        <DidNotLoad what="The debrief" />
      ) : (
        item &&
        debrief.data && (
          <div data-testid="debrief">
            <Markdown text={debrief.data.debrief} />
          </div>
        )
      )}
    </Overlay>
  );
}

function Titles({ item }: { item: TimelineItem }) {
  return (
    <>
      <h2 data-testid="overlay.title">
        <NotebookPen className="icon" aria-hidden="true" /> Debrief
      </h2>
      <div className="sub" data-testid="overlay.sub">
        <span data-testid="debrief.item">
          <LinkedText text={titleOf(item)} />
        </span>
        {item.done !== null && (
          <>
            <span>·</span>
            <Time at={item.done.at} format="clock" testId="debrief.ended" />
          </>
        )}
      </div>
    </>
  );
}
