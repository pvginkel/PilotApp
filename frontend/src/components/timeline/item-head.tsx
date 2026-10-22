/**
 * An open item's head (F12): its kind's icon and label, its time with the full stamp as tooltip, a
 * confirmation's reason line with its tooltip (F22.1), and the Urgent and "for <user>" chips (F10.1,
 * F107).
 */

import { TriangleAlert } from 'lucide-react';
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

/** `because`: the ground a confirmation asks on. */
export function ItemHead({ item, because = null }: { item: TimelineItem; because?: Block['because'] }) {
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
    </div>
  );
}
