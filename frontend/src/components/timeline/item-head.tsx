/**
 * An open item's head (F12): its kind's icon and label, its time with the full stamp as tooltip, a
 * confirmation's reason line with its tooltip (F22.1), and the Urgent and "for <user>" chips (F10.1,
 * F107); after them what a document's head adds. A document Pilot changed in a turn after the text
 * it was first shown with says so, *Edited <time>* beside Pilot's mark (F28.7).
 */

import type { ReactNode } from 'react';
import { TriangleAlert } from 'lucide-react';
import { Avatar } from '@/components/shared/avatar';
import { Time } from '@/components/shared/time';
import { kindOf } from '@/components/timeline/kinds';
import type { Block, TimelineItem } from '@/hooks/use-timeline';

type Reason = NonNullable<Block['because']>;

/**
 * Why Pilot asks, said plainly, never in the grants table's terms (F22.1, ui-conventions): the line
 * and its tooltip, by the Confirmation Reason's code.
 */
const WHY: Partial<Record<string, { label: string; tooltip: string }>> = {
  'auto-pilot-off': {
    label: 'Auto pilot off',
    tooltip: 'Pilot asks because auto pilot is off; under auto pilot it would go ahead',
  },
  rider: {
    label: 'Auto pilot off: other commits go too',
    tooltip: "The push carries commits that are not this project's; under auto pilot it would go ahead",
  },
  irreversible: {
    label: 'Always asks: cannot be undone',
    tooltip: 'Pilot asks for an act that cannot be undone, even under auto pilot',
  },
  'product-hold': {
    label: 'Always asks: you held this back',
    tooltip: 'You held this back; Pilot asks even under auto pilot',
  },
  'self-approval': {
    label: 'Always asks: overrules a check',
    tooltip: 'Going ahead would overrule a hold or a failed check; Pilot asks even under auto pilot',
  },
};

/** A reason a migration adds after these reads as the record names it until it has its words here. */
function whyOf(because: Reason) {
  return WHY[because.code] ?? { label: because.name, tooltip: because.description };
}

interface ItemHeadProps {
  item: TimelineItem;
  /** The ground a confirmation asks on. */
  because?: Block['because'];
  /** What a document's head adds after the chips. */
  children?: ReactNode;
}

export function ItemHead({ item, because = null, children }: ItemHeadProps) {
  const { icon: Icon, label } = kindOf(item);
  const why = because === null ? null : whyOf(because);
  return (
    <div className="item-head" data-testid="timeline.item.head">
      <span className="kind" data-testid="timeline.item.kind">
        <Icon className="icon" aria-hidden="true" />
        {label}
      </span>
      <span className="sep">·</span>
      <Time at={item.created_at} format="clock" testId="timeline.item.time" />
      {why !== null && (
        <>
          <span className="sep">·</span>
          <span className="why" title={why.tooltip} data-testid="timeline.item.why">
            {why.label}
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
      {children}
    </div>
  );
}

/** *Edited <time>*, the time of Pilot's latest such turn. */
export function Edited({ at }: { at: string }) {
  return (
    <span className="edited" data-testid="timeline.item.edited">
      <Avatar who="pilot" size="xs" />
      Edited <Time at={at} format="clock" testId="timeline.item.edited.time" />
    </span>
  );
}
