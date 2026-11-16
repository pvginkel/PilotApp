/**
 * The debrief's notice open (F26.12, F26.13), a box of its own: its head, the Debrief's notebook in
 * its kind's place (kinds.ts), and its title, "Debrief · <subject>"; then, per work item it
 * carries, in timeline order, a head with the item's title and the time its turn ended, the stage
 * session's debrief whole as prose, and under it Full debrief and Session log, opening that item's
 * full debrief and its session log where its done line's Debrief and title open them, on a phone
 * views pushed over the tabs (F98.4); under the whole, its Read.
 */

import type { ReactNode } from 'react';
import { Link } from '@tanstack/react-router';
import { NotebookPen, ScrollText } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Time } from '@/components/shared/time';
import { ItemHead } from '@/components/timeline/item-head';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import { useShownProject } from '@/hooks/use-project-address';
import { titleOf, type TimelineItem } from '@/hooks/use-timeline';

type Carried = NonNullable<TimelineItem['debriefs']>[number];

interface DebriefNoticeProps {
  item: TimelineItem;
  /** Its Read, under the whole. */
  children: ReactNode;
}

export function DebriefNotice({ item, children }: DebriefNoticeProps) {
  return (
    <div className="item-body">
      <ItemHead item={item} />
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      {/* The API gives a debrief's notice the work items it carries. */}
      {item.debriefs!.map((carried) => (
        <CarriedDebrief key={carried.id} carried={carried} />
      ))}
      {children}
    </div>
  );
}

function CarriedDebrief({ carried }: { carried: Carried }) {
  const { address } = useShownProject();
  const replace = useTabReplace();
  const params = { address, sessionId: carried.id };
  return (
    <section className="carried" data-testid="timeline.debrief" data-item-id={carried.id}>
      <div className="carried-head">
        <span className="carried-title" data-testid="timeline.debrief.title">
          <LinkedText text={carried.title} />
        </span>
        {/* The dot goes with the time, so that no row of a wrapping head ends on it. */}
        <span className="dotted">
          <span className="sep">·</span>
          <Time at={carried.ended_at} format="clock" testId="timeline.debrief.ended" />
        </span>
      </div>
      <div data-testid="timeline.debrief.text">
        <Markdown text={carried.debrief} />
      </div>
      <div className="carried-links">
        <Link
          to="/projects/$address/sessions/$sessionId/debrief/full"
          params={params}
          replace={replace}
          className="btn btn-ghost btn-sm"
          title="Every agent’s debrief, per section and round"
          data-testid="timeline.debrief.full"
        >
          <NotebookPen className="icon" aria-hidden="true" />
          Full debrief
        </Link>
        <Link
          to="/projects/$address/sessions/$sessionId"
          params={params}
          replace={replace}
          className="btn btn-ghost btn-sm"
          title="Open the session log"
          data-testid="timeline.debrief.session-log"
        >
          <ScrollText className="icon" aria-hidden="true" />
          Session log
        </Link>
      </div>
    </section>
  );
}
