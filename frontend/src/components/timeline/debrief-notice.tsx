/**
 * The debrief's notice open (F26.12, F26.13), a box of its own: its head, the Debrief's notebook in
 * its kind's place (kinds.ts), and its title, "Debrief · <subject>"; then each work item it
 * carries, in timeline order, a line with its title and the time its stage took (F26.17); then
 * Pilot's notable events as Markdown, where the pass wrote any (F52.4); then Details, closed
 * whenever the box is first drawn and Less once open, as a confirmation's (F22.4), holding per work
 * item a head with the item's title and the time its turn ended, the stage session's debrief whole
 * as prose, and under it Full debrief and Session log, opening that item's full debrief and its
 * session log where its done line's Debrief and title open them, on a phone views pushed over the
 * tabs (F98.4); under the whole, its Read.
 */

import { useState, type ReactNode } from 'react';
import { Link } from '@tanstack/react-router';
import { ChevronDown, ChevronUp, NotebookPen, ScrollText } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Time } from '@/components/shared/time';
import { ItemHead } from '@/components/timeline/item-head';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import { useShownProject } from '@/hooks/use-project-address';
import { useToday } from '@/hooks/use-today';
import { titleOf, type TimelineItem } from '@/hooks/use-timeline';
import { clockFormat, took } from '@/lib/utils/time-format';

type Carried = NonNullable<TimelineItem['debriefs']>[number];

interface DebriefNoticeProps {
  item: TimelineItem;
  /** Its Read, under the whole. */
  children: ReactNode;
}

export function DebriefNotice({ item, children }: DebriefNoticeProps) {
  const [details, setDetails] = useState(false);
  // The API gives a debrief's notice the work items it carries.
  const carried = item.debriefs!;
  const notable = carried.filter((each) => each.notable !== null);
  return (
    <div className="item-body">
      <ItemHead item={item} />
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      <ul className="stage-times" data-testid="timeline.debrief.stages">
        {carried.map((each) => (
          <li key={each.id} data-testid="timeline.debrief.stage" data-item-id={each.id}>
            <span className="stage-title" data-testid="timeline.debrief.stage.title">
              <LinkedText text={each.title} />
            </span>
            <span className="stage-time" data-testid="timeline.debrief.stage.time">
              {took(each.stage_time)}
            </span>
          </li>
        ))}
      </ul>
      {notable.length > 0 && (
        <div className="notable" data-testid="timeline.debrief.notable">
          {notable.map((each) => (
            <Markdown key={each.id} text={each.notable!} />
          ))}
        </div>
      )}
      <div className="debrief-foot">
        <button type="button" className="link details" onClick={() => setDetails(!details)} aria-expanded={details} data-testid="timeline.debrief.details">
          {details ? <ChevronUp className="icon" aria-hidden="true" /> : <ChevronDown className="icon" aria-hidden="true" />}
          {details ? 'Less' : 'Details'}
        </button>
      </div>
      {details && carried.map((each) => <CarriedDebrief key={each.id} carried={each} />)}
      {children}
    </div>
  );
}

function CarriedDebrief({ carried }: { carried: Carried }) {
  const { address } = useShownProject();
  const replace = useTabReplace();
  const today = useToday();
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
          <Time at={carried.ended_at} format={clockFormat(carried.ended_at, today)} testId="timeline.debrief.ended" />
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
