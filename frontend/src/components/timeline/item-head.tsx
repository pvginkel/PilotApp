/**
 * An open item's head (F12): its kind's icon and label, its time with the full stamp as tooltip, a
 * confirmation's reason line with its tooltip (F22.1), and the Urgent and "for <user>" chips (F10.1,
 * F107).
 */

import { TriangleAlert } from 'lucide-react';
import { Time } from '@/components/shared/time';
import { kindOf } from '@/components/timeline/kinds';
import type { Block, TimelineItem } from '@/hooks/use-timeline';

/** `because`: the ground a confirmation asks on. */
export function ItemHead({ item, because = null }: { item: TimelineItem; because?: Block['because'] }) {
  const { icon: Icon, label } = kindOf(item);
  return (
    <div className="item-head" data-testid="timeline.item.head">
      <span className="kind" data-testid="timeline.item.kind">
        <Icon className="icon" aria-hidden="true" />
        {label}
      </span>
      <span className="sep">·</span>
      <Time at={item.created_at} format="clock" testId="timeline.item.time" />
      {because !== null && (
        <>
          <span className="sep">·</span>
          <span className="why" title={because.description} data-testid="timeline.item.why">
            {because.name}
          </span>
        </>
      )}
      {item.urgent && (
        <span className="chip urgent" data-testid="timeline.item.urgent">
          <TriangleAlert className="icon" aria-hidden="true" />
          Urgent
        </span>
      )}
      {item.for_user && (
        <span className="chip for" data-testid="timeline.item.for">
          for {item.for_user.name}
        </span>
      )}
    </div>
  );
}
