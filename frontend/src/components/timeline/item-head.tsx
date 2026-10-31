/**
 * An open item's head (F12): its kind's icon and label, its time with the full stamp as tooltip, a
 * confirmation's auto pilot mark (F4.4) and its reason line with its tooltip (F22.1), and the
 * Urgent and "for <user>" chips (F10.1, F107); after them what a document's head adds; at its end
 * Discuss, quoting the item (F39.1). A document Pilot changed in a turn after the text it was first
 * shown with says so, *Edited <time>* beside Pilot's mark (F28.7). On a phone Urgent is its
 * triangle and *Edited* a pencil, their words left to a screen reader; the kind never wraps, and
 * the head wraps where its parts still do not fit, so that none leaves the card.
 */

import type { ReactNode } from 'react';
import { Pencil, TriangleAlert } from 'lucide-react';
import { DiscussButton } from '@/components/chat/discuss-button';
import { quoteOfItem } from '@/components/chat/discuss-quotes';
import { Avatar } from '@/components/shared/avatar';
import { Time } from '@/components/shared/time';
import { AutopilotMark } from '@/components/timeline/autopilot-mark';
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
  'standing-grant': {
    label: 'Always asks: a lasting permission',
    tooltip: 'The permission would outlast the project or reach past it; Pilot asks even under auto pilot',
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
  /** A confirmation's auto pilot mark stands after the time (autopilot-mark.tsx). */
  mayTake?: boolean;
  /** What a document's head adds after the chips. */
  children?: ReactNode;
}

export function ItemHead({ item, because = null, mayTake = false, children }: ItemHeadProps) {
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
      {mayTake && (
        <>
          <span className="sep">·</span>
          <AutopilotMark testId="timeline.item.autopilot-mark" />
        </>
      )}
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
          <span className="chip-label">Urgent</span>
        </span>
      )}
      {item.for_user && (
        <span className="chip for" data-testid="timeline.item.for">
          for {item.for_user.name}
        </span>
      )}
      {children}
      <DiscussButton quote={quoteOfItem(item)} className="item-discuss" testId="timeline.item.discuss" />
    </div>
  );
}

/**
 * *Edited <time>*, the time of Pilot's latest such turn; on a phone a pencil in the word's place,
 * the word left to a screen reader.
 */
export function Edited({ at }: { at: string }) {
  return (
    <span className="edited" data-testid="timeline.item.edited">
      <Avatar who="pilot" size="xs" />
      <Pencil className="icon edited-icon" aria-hidden="true" />
      <span className="edited-label">Edited</span> <Time at={at} format="clock" testId="timeline.item.edited.time" />
    </span>
  );
}
