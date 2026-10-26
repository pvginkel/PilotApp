/**
 * That Pilot asked a registered document's writer about its blocks (F86.8), on the open item:
 * "Pilot asked the writer about D2 and D4", the blocks by their local ids in the document's order.
 */

import { Avatar } from '@/components/shared/avatar';
import type { TimelineItem } from '@/hooks/use-timeline';

/** The blocks by their local ids: "D2", "D2 and D4", "D1, D2 and D4". */
const listed = (ids: readonly string[]) => (ids.length < 2 ? ids.join('') : `${ids.slice(0, -1).join(', ')} and ${ids.at(-1)!}`);

export function WriterAsked({ item }: { item: TimelineItem }) {
  if (item.asked_writer_about.length === 0) return null;
  return (
    <p className="item-sub writer-asked" data-testid="timeline.item.writer-asked">
      <Avatar who="pilot" size="xs" />
      <span>Pilot asked the writer about {listed(item.asked_writer_about)}</span>
    </p>
  );
}
