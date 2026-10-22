/**
 * A project's timeline (F8): its prose items in their order under their date and step dividers
 * (F9), the opening first. It is anchored to the bottom: it opens at its end, a project's own on
 * each project (F1.6), and when items arrive it scrolls to the end unless the reader has scrolled
 * away from it; a new item flashes (F8.2). Empty, it reads "Nothing yet" (F113). Work items and
 * waits draw no line here.
 *
 * An open urgent item has a banner pinned to the top, whose Show scrolls to the item and flashes
 * it; a finished project's has none (F10.2). While open items are scrolled out above, a chip under
 * the banners counts them and scrolls to the nearest (F11). A finished project's timeline ends in
 * "Finished · <stamp>", every item but the opening done by Finish (F5.3).
 */

import { useLayoutEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Flag, TriangleAlert } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import { Item } from '@/components/timeline/item';
import { Opening } from '@/components/timeline/opening';
import { rowsOf, type Row } from '@/components/timeline/rows';
import { titleOf, useTimeline, type TimelineItem } from '@/hooks/use-timeline';

/** How far from the end, in pixels, still reads as at the end. */
const END_SLACK = 48;
/** How far under the banners an item's end may stand, in pixels, and still read as scrolled out above. */
const ABOVE_SLACK = 8;

export function Timeline({ projectId }: { projectId: string }) {
  const { data } = useTimeline(projectId);
  const items = data?.items.filter((item) => item.form === 'prose');
  const finishedAt = data?.finished_at ?? null;
  const urgent = finishedAt === null ? (items ?? []).filter((item) => item.urgent && item.done === null) : [];
  const { fresh, flashed, flash } = useFresh(items);
  const feed = useRef<HTMLDivElement>(null);
  const pins = useRef<HTMLDivElement>(null);
  // The open items scrolled out above the banners, by id, in their order.
  const [above, setAbove] = useState<string[]>([]);
  // At the end until the reader scrolls away from it; it opens there.
  const atEnd = useRef(true);
  // Where the timeline last put itself, at its end.
  const pinned = useRef<number | null>(null);
  const toEnd = () => {
    const element = feed.current!;
    element.scrollTop = element.scrollHeight;
    pinned.current = element.scrollTop;
  };
  const countAbove = () => {
    const element = feed.current!;
    const top = element.getBoundingClientRect().top + pins.current!.offsetHeight;
    const ids = [...element.querySelectorAll<HTMLElement>('.feed-inner > .item.open')]
      .filter((article) => article.getBoundingClientRect().bottom < top + ABOVE_SLACK)
      .map((article) => article.dataset.itemId!);
    setAbove((current) => (same(current, ids) ? current : ids));
  };
  const onScroll = () => {
    const element = feed.current!;
    // A scroll event reports where the timeline stands once the frame is laid out, after the head
    // above it may have been drawn: one where the timeline put itself is its own, not the reader's.
    atEnd.current =
      element.scrollTop === pinned.current || element.scrollHeight - element.scrollTop - element.clientHeight < END_SLACK;
    countAbove();
  };
  // The reader goes to an item, its middle to the timeline's or its top to its scroll margin. A
  // scroll that moves the timeline no longer follows its end until its scroll events put it back
  // there; one that would not move it fires none, and leaves following as it stands.
  const scrollTo = (id: string, block: 'center' | 'start') => {
    const element = feed.current!;
    const article = element.querySelector<HTMLElement>(`.feed-inner > [data-item-id="${CSS.escape(id)}"]`)!;
    const box = article.getBoundingClientRect();
    const top = box.top - element.getBoundingClientRect().top - element.clientTop + element.scrollTop;
    const wanted =
      block === 'center'
        ? top + box.height / 2 - element.clientHeight / 2
        : top - parseFloat(getComputedStyle(article).scrollMarginTop);
    const target = Math.min(Math.max(wanted, 0), element.scrollHeight - element.clientHeight);
    if (Math.abs(target - element.scrollTop) < 1) return;
    atEnd.current = false;
    element.scrollTo({ top: target, behavior: 'smooth' });
  };
  const show = (id: string) => {
    scrollTo(id, 'center');
    flash(id);
  };

  useLayoutEffect(() => {
    if (atEnd.current) toEnd();
    countAbove();
  }, [data]);

  // The timeline's own height changes, as when the head above it is drawn or the window is
  // resized, and nothing scrolls it: at its end, it stays there.
  useLayoutEffect(() => {
    const observer = new ResizeObserver(() => {
      if (atEnd.current) toEnd();
      countAbove();
    });
    observer.observe(feed.current!);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={feed} className="feed" onScroll={onScroll} data-testid="timeline">
      <div ref={pins} className="pins">
        {urgent.length > 0 && (
          <div className="pinned" data-testid="timeline.banners">
            {urgent.map((item) => (
              <UrgentBanner key={item.id} item={item} onShow={() => show(item.id)} />
            ))}
          </div>
        )}
        {above.length > 0 && (
          <button
            type="button"
            className="btn btn-soft btn-sm open-above"
            onClick={() => scrollTo(above[above.length - 1], 'start')}
            data-testid="timeline.open-above"
          >
            <ArrowUp className="icon" aria-hidden="true" />
            {above.length} open above
          </button>
        )}
      </div>
      <div className="feed-inner">
        {items?.length === 0 && (
          <div className="divider" data-testid="timeline.empty">
            Nothing yet
          </div>
        )}
        {items && rowsOf(items).map((row) => <TimelineRow key={row.key} row={row} fresh={fresh} flashed={flashed} />)}
        {finishedAt !== null && (
          <div className="divider finished" data-testid="timeline.divider.finished">
            <span>
              <Flag className="icon" aria-hidden="true" />
              Finished · <Time at={finishedAt} format="stamp" testId="timeline.divider.finished.time" />
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function UrgentBanner({ item, onShow }: { item: TimelineItem; onShow: () => void }) {
  return (
    <button type="button" className="pin-banner" onClick={onShow} data-testid="timeline.banner" data-item-id={item.id}>
      <TriangleAlert className="icon" aria-hidden="true" />
      <span className="what">Urgent</span>
      <span className="sep">·</span>
      <span className="title">
        <LinkedText text={titleOf(item)} nested />
      </span>
      <span className="sep">·</span>
      <span className="go">
        Show <ArrowDown className="icon" aria-hidden="true" />
      </span>
    </button>
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
 * The items that arrived since the timeline was first read, and those flashed on purpose, until
 * each has flashed. The first read flashes nothing.
 */
function useFresh(items: TimelineItem[] | undefined) {
  const [seen, setSeen] = useState<Seen>({ items: undefined, fresh: new Set() });
  if (items !== undefined && seen.items === undefined) {
    setSeen({ items, fresh: seen.fresh });
  } else if (items !== undefined && seen.items !== undefined && !same(ids(items), ids(seen.items))) {
    const known = new Set(ids(seen.items));
    const arrived = ids(items).filter((id) => !known.has(id));
    setSeen({ items, fresh: new Set([...seen.fresh, ...arrived]) });
  }
  const flashed = (id: string) =>
    setSeen((current) => ({ ...current, fresh: new Set([...current.fresh].filter((other) => other !== id)) }));
  const flash = (id: string) => {
    flashed(id);
    // Back on two frames later, once a frame has been drawn without it, so its animation starts again.
    requestAnimationFrame(() =>
      requestAnimationFrame(() => setSeen((current) => ({ ...current, fresh: new Set([...current.fresh, id]) }))),
    );
  };
  return { fresh: seen.fresh, flashed, flash };
}

const ids = (items: TimelineItem[]) => items.map((item) => item.id);

function same(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((id, index) => id === right[index]);
}
