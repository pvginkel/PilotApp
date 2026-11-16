/**
 * Pilot's alert on a document (F168.6): what its Send starts where another open ask has to be
 * answered before it is sent, a problem Pilot found where its notes are advice. A rounded gold box
 * as the halt's popover is, the document's width: the triangle, what to answer first and what the
 * Send starts, and the popover's button, which opens the ask it names (use-open-quote.ts).
 * Opened, it is the last line of the document's head, under the segment bar, not scrolling; inline,
 * the document's top. On a phone it is one line, cut with an ellipsis, a chevron at its end, which a
 * tap opens and closes, closed as it mounts. It blocks nothing, and the read drops it once the item
 * of the ask it names is done.
 */

import { useState } from 'react';
import { ChevronDown, ChevronUp, TriangleAlert } from 'lucide-react';
import { Markdown } from '@/components/shared/markdown';
import { useOpenQuote } from '@/hooks/use-open-quote';
import { usePhone } from '@/hooks/use-phone';
import type { TimelineItem } from '@/hooks/use-timeline';
import { cn } from '@/lib/utils';

type SendAlertData = NonNullable<TimelineItem['send_alert']>;

export function SendAlert({ alert }: { alert: SendAlertData }) {
  const phone = usePhone();
  const [open, setOpen] = useState(false);
  const openQuote = useOpenQuote();
  const { item, block, title } = alert.awaits;
  const toggle = open ? 'Show the alert’s first line only' : 'Show the whole alert';
  return (
    <div
      className={cn('gold-line doc-alert', open && 'open')}
      // On a phone a tap anywhere on it opens and closes it: the chevron's reaches it.
      onClick={phone ? () => setOpen(!open) : undefined}
      data-testid="timeline.item.send-alert"
      data-open={open}
    >
      <TriangleAlert className="icon" aria-hidden="true" />
      <div className="gold-body">
        <Markdown text={alert.text} className="da-text" />
        <div className="gold-actions">
          <button
            type="button"
            className="gold-btn"
            onClick={(event) => {
              event.stopPropagation();
              openQuote({ kind: 'block', id: `${item}/${block}`, label: title });
            }}
            title={`Go to ${block} of “${title}”, to answer it first`}
            data-testid="timeline.item.send-alert.go"
          >
            {title}
          </button>
        </div>
      </div>
      {phone && (
        <button
          type="button"
          className="btn btn-ghost btn-icon toggle"
          aria-label={toggle}
          title={toggle}
          aria-expanded={open}
          data-testid="timeline.item.send-alert.toggle"
        >
          {open ? <ChevronUp className="icon" aria-hidden="true" /> : <ChevronDown className="icon" aria-hidden="true" />}
        </button>
      )}
    </div>
  );
}
