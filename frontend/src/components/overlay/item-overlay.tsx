/**
 * The item alone, full screen (F99): on a phone a view pushed over the tabs (F98.4), at the item's
 * address — a notification's link among them (F94.2) — or at a block's where the item is no card,
 * going to the block. Its head is the project's name over the item's step; its body the item as
 * the timeline draws it, open or as its done line, answered in place as there, its option rows a
 * thumb's height. An address naming no item the timeline draws, or a read that fails, reads "The
 * item did not load" (F113).
 */

import { DidNotLoad, Overlay } from '@/components/overlay/overlay';
import { LinkedText } from '@/components/shared/linked-text';
import { Item } from '@/components/timeline/item';
import { Opening } from '@/components/timeline/opening';
import { useOverlayClose } from '@/hooks/use-overlay-close';
import type { ProjectHead } from '@/hooks/use-projects';
import type { TimelineItem } from '@/hooks/use-timeline';
import { useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';

interface ItemOverlayProps {
  projectId: string;
  /** The project's head, once read. */
  project: ProjectHead | undefined;
  itemId: string;
  /** The block it opens at. */
  block: string | null;
}

export function ItemOverlay({ projectId, project, itemId, block }: ItemOverlayProps) {
  const close = useOverlayClose();
  const { data, error } = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } });
  const item = data?.items.find((each) => each.id === itemId);
  const failed = error !== null || (data !== undefined && item === undefined);
  return (
    <Overlay
      showing={`item ${itemId}`}
      at={block === null ? null : { item: itemId, block }}
      titles={project && <Titles project={project} item={item} />}
      foot={null}
      onClose={close}
    >
      {failed ? (
        <DidNotLoad what="The item" />
      ) : (
        item && (
          <div className="item-alone" data-testid="item-alone">
            {item.kind === 'opening' ? <Opening item={item} fresh={false} onFlashed={noop} /> : <Item item={item} fresh={false} onFlashed={noop} />}
          </div>
        )
      )}
    </Overlay>
  );
}

function Titles({ project, item }: { project: ProjectHead; item: TimelineItem | undefined }) {
  return (
    <>
      <h2 title={project.name ?? 'New project'} data-testid="overlay.title">
        <LinkedText text={project.name ?? 'New project'} />
      </h2>
      {item?.step && (
        <div className="sub" data-testid="overlay.sub">
          <span className="mono step" title={item.step.title} data-testid="overlay.step">
            <LinkedText text={item.step.title} />
          </span>
        </div>
      )}
    </>
  );
}

const noop = () => undefined;
