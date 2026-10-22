/**
 * A project's timeline (F8): its prose items in their order under their date and step dividers
 * (F9), the opening first. It is anchored to the bottom: it opens at its end, a project's own on
 * each project (F1.6), and when items arrive it scrolls to the end unless the reader has scrolled
 * away from it; a new item flashes (F8.2). Empty, it reads "Nothing yet" (F113). Work items and
 * waits draw no line here.
 */

import { useLayoutEffect, useRef, useState } from 'react';
import { LinkedText } from '@/components/shared/linked-text';
import { Item } from '@/components/timeline/item';
import { Opening } from '@/components/timeline/opening';
import { rowsOf, type Row } from '@/components/timeline/rows';
import { useTimeline, type TimelineItem } from '@/hooks/use-timeline';

/** How far from the end, in pixels, still reads as at the end. */
const END_SLACK = 48;

export function Timeline({ projectId }: { projectId: string }) {
  const { data } = useTimeline(projectId);
  const items = data?.items.filter((item) => item.form === 'prose');
  const { fresh, flashed } = useFresh(items);
  const feed = useRef<HTMLDivElement>(null);
  // At the end until the reader scrolls away from it; it opens there.
  const atEnd = useRef(true);
  // Where the timeline last put itself, at its end.
  const pinned = useRef<number | null>(null);
  const toEnd = () => {
    const element = feed.current!;
    element.scrollTop = element.scrollHeight;
    pinned.current = element.scrollTop;
  };
  const onScroll = () => {
    const element = feed.current!;
    // A scroll event reports where the timeline stands once the frame is laid out, after the head
    // above it may have been drawn: one where the timeline put itself is its own, not the reader's.
    atEnd.current =
      element.scrollTop === pinned.current || element.scrollHeight - element.scrollTop - element.clientHeight < END_SLACK;
  };

  useLayoutEffect(() => {
    if (atEnd.current) toEnd();
  }, [data]);

  // The timeline's own height changes, as when the head above it is drawn or the window is
  // resized, and nothing scrolls it: at its end, it stays there.
  useLayoutEffect(() => {
    const observer = new ResizeObserver(() => atEnd.current && toEnd());
    observer.observe(feed.current!);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={feed} className="feed" onScroll={onScroll} data-testid="timeline">
      <div className="feed-inner">
        {items?.length === 0 && (
          <div className="divider" data-testid="timeline.empty">
            Nothing yet
          </div>
        )}
        {items && rowsOf(items).map((row) => <TimelineRow key={row.key} row={row} fresh={fresh} flashed={flashed} />)}
      </div>
    </div>
  );
}

interface TimelineRowProps {
  row: Row;
  fresh: ReadonlySet<string>;
  flashed: (id: string) => void;
}

function TimelineRow({ row, fresh, flashed }: TimelineRowProps) {
  if (row.type === 'day') {
    return (
      <div className="divider date" data-testid="timeline.divider.day">
        {row.label}
      </div>
    );
  }
  if (row.type === 'step') {
    return (
      <div className="divider step" data-testid="timeline.divider.step">
        <LinkedText text={row.title} />
      </div>
    );
  }
  return row.item.kind === 'opening' ? (
    <Opening item={row.item} />
  ) : (
    <Item item={row.item} fresh={fresh.has(row.item.id)} onFlashed={() => flashed(row.item.id)} />
  );
}

interface Seen {
  items: TimelineItem[] | undefined;
  fresh: ReadonlySet<string>;
}

/**
 * The items that arrived since the timeline was first read, until each has flashed. The first read
 * flashes nothing.
 */
function useFresh(items: TimelineItem[] | undefined) {
  const [seen, setSeen] = useState<Seen>({ items: undefined, fresh: new Set() });
  if (items !== undefined && seen.items === undefined) {
    setSeen({ items, fresh: seen.fresh });
  } else if (items !== undefined && seen.items !== undefined && !sameIds(items, seen.items)) {
    const known = new Set(seen.items.map((item) => item.id));
    const arrived = items.filter((item) => !known.has(item.id)).map((item) => item.id);
    setSeen({ items, fresh: new Set([...seen.fresh, ...arrived]) });
  }
  const flashed = (id: string) =>
    setSeen((current) => ({ ...current, fresh: new Set([...current.fresh].filter((other) => other !== id)) }));
  return { fresh: seen.fresh, flashed };
}

function sameIds(left: TimelineItem[], right: TimelineItem[]): boolean {
  return left.length === right.length && left.every((item, index) => item.id === right[index].id);
}
