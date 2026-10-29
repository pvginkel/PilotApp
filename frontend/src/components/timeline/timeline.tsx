/**
 * A project's timeline (F8): its prose and work items in their order under their date and step
 * dividers (F9, F9.1), the opening first. It is anchored to the bottom: it opens at its end, a
 * project's own on each project (F1.6), and when items arrive it scrolls to the end unless the
 * reader has scrolled away from it; a new item flashes (F8.2). Waits draw no line here.
 *
 * An open urgent item has a banner pinned to the top, whose Show scrolls to the item and flashes
 * it; a finished project's has none (F10.2). While open items are scrolled out above, a chip under
 * the banners counts them and scrolls to the nearest (F11). A finished project's timeline ends in
 * "Finished · <stamp>", every item but the opening done by Finish (F5.3), and under it the archive
 * question its latest finish put, open or as its done line (F5.6).
 *
 * Opened at an item's address, the timeline goes to the item and flashes it; at a block's, to the
 * block, its collapsed section opened (F31.5), or to its item where its line or its card stands for
 * it; an address it draws nothing for leaves it at its end (F97). A segment opens its block's
 * collapsed section too (F33). Under an overlay's backdrop it takes no focus.
 */

import { useLayoutEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { ArrowDown, ArrowUp, Flag, TriangleAlert } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import { blockKey, FlashContext, GoToContext } from '@/components/timeline/flash';
import { Item } from '@/components/timeline/item';
import { Opening } from '@/components/timeline/opening';
import { rowsOf, type Row } from '@/components/timeline/rows';
import { SectionsContext, useSections } from '@/components/timeline/sections';
import { titleOf, useTimeline, type TimelineItem } from '@/hooks/use-timeline';

/** How far from the end, in pixels, still reads as at the end. */
const END_SLACK = 48;
/** How far under the banners an item's end may stand, in pixels, and still read as scrolled out above. */
const ABOVE_SLACK = 8;

/** Where the timeline is opened: an item, or one of its blocks. */
interface Address {
  item: string;
  block: string | null;
}

interface TimelineProps {
  projectId: string;
  address: Address | null;
  /** It lies under an overlay's backdrop. */
  inert: boolean;
}

export function Timeline({ projectId, address, inert }: TimelineProps) {
  const { data } = useTimeline(projectId);
  const items = data?.items.filter((item) => item.form !== 'wait');
  const finishedAt = data?.finished_at ?? null;
  // Every finish puts one, so a finished project's latest archive question is its latest finish's.
  const question = finishedAt === null ? undefined : items?.filter((item) => item.kind === 'archive_question').at(-1);
  const placed = question === undefined ? items : items?.filter((item) => item !== question);
  const urgent = finishedAt === null ? (items ?? []).filter((item) => item.urgent && item.done === null) : [];
  const { fresh, flashed, flash } = useFresh(items);
  const sections = useSections(address === null || address.block === null ? null : blockKey(address.item, address.block));
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
  const articleOf = (id: string) =>
    feed.current!.querySelector<HTMLElement>(`.feed-inner > [data-item-id="${CSS.escape(id)}"]`);
  // The reader goes to an item or a block, its middle to the timeline's or its top to its scroll
  // margin. A scroll that moves the timeline no longer follows its end until its scroll events put
  // it back there; one that would not move it fires none, and leaves following as it stands.
  const scrollTo = (goal: HTMLElement, block: 'center' | 'start', behavior: ScrollBehavior = 'smooth') => {
    const element = feed.current!;
    const box = goal.getBoundingClientRect();
    const top = box.top - element.getBoundingClientRect().top - element.clientTop + element.scrollTop;
    const wanted =
      block === 'center'
        ? top + box.height / 2 - element.clientHeight / 2
        : top - parseFloat(getComputedStyle(goal).scrollMarginTop);
    const target = Math.min(Math.max(wanted, 0), element.scrollHeight - element.clientHeight);
    if (Math.abs(target - element.scrollTop) < 1) return;
    atEnd.current = false;
    element.scrollTo({ top: target, behavior });
  };
  // Only an item the timeline draws has a banner.
  const show = (id: string) => {
    scrollTo(articleOf(id)!, 'center');
    flash(id);
  };
  // An address jumps: a smooth scroll's first frames, still near the end, read as following it,
  // and the head drawn above the timeline in them would pin it back there. A segment glides.
  const goTo = ({ item, block }: Address, behavior: ScrollBehavior = 'instant') => {
    const article = articleOf(item);
    if (article === null) return;
    const found = block === null ? null : article.querySelector<HTMLElement>(`[data-block-id="${CSS.escape(block)}"]`);
    scrollTo(found ?? article, 'center', behavior);
    flash(found === null ? item : blockKey(item, block!));
  };
  const goToBlock = (item: string, block: string) => {
    // Its collapsed section opens first, so that the block is drawn to go to.
    flushSync(() => sections.open(blockKey(item, block)));
    goTo({ item, block }, 'smooth');
  };
  // The address last gone to: each is gone to once, when the timeline is read, or when it is opened
  // with the timeline on screen.
  const reached = useRef<string | null>(null);

  useLayoutEffect(() => {
    if (atEnd.current) toEnd();
    countAbove();
  }, [data]);

  // After the pin to the end above, on every render.
  useLayoutEffect(() => {
    if (address === null) {
      reached.current = null;
      return;
    }
    const key = address.block === null ? address.item : blockKey(address.item, address.block);
    if (data === undefined || reached.current === key) return;
    reached.current = key;
    goTo(address);
  });

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
    <div ref={feed} className="feed" onScroll={onScroll} inert={inert} data-testid="timeline">
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
            onClick={() => scrollTo(articleOf(above[above.length - 1])!, 'start')}
            data-testid="timeline.open-above"
          >
            <ArrowUp className="icon" aria-hidden="true" />
            {above.length} open above
          </button>
        )}
      </div>
      <div className="feed-inner">
        <FlashContext.Provider value={{ fresh, flashed }}>
          <GoToContext.Provider value={goToBlock}>
            <SectionsContext.Provider value={sections}>
              {placed && rowsOf(placed).map((row) => <TimelineRow key={row.key} row={row} fresh={fresh} flashed={flashed} />)}
              {finishedAt !== null && (
                <div className="divider finished" data-testid="timeline.divider.finished">
                  <span>
                    <Flag className="icon" aria-hidden="true" />
                    Finished · <Time at={finishedAt} format="stamp" testId="timeline.divider.finished.time" />
                  </span>
                </div>
              )}
              {question && <Item item={question} fresh={fresh.has(question.id)} onFlashed={() => flashed(question.id)} />}
            </SectionsContext.Provider>
          </GoToContext.Provider>
        </FlashContext.Provider>
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
    <Opening item={row.item} fresh={fresh.has(row.item.id)} onFlashed={() => flashed(row.item.id)} />
  ) : (
    <Item item={row.item} fresh={fresh.has(row.item.id)} onFlashed={() => flashed(row.item.id)} />
  );
}

interface Seen {
  items: TimelineItem[] | undefined;
  fresh: ReadonlySet<string>;
}

/**
 * The items that arrived since the timeline was first read, and the items and blocks flashed on
 * purpose, until each has flashed. The first read flashes nothing.
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
  const flashed = (key: string) =>
    setSeen((current) => ({ ...current, fresh: new Set([...current.fresh].filter((other) => other !== key)) }));
  const flash = (key: string) => {
    flashed(key);
    // Back on two frames later, once a frame has been drawn without it, so its animation starts again.
    requestAnimationFrame(() =>
      requestAnimationFrame(() => setSeen((current) => ({ ...current, fresh: new Set([...current.fresh, key]) }))),
    );
  };
  return { fresh: seen.fresh, flashed, flash };
}

const ids = (items: TimelineItem[]) => items.map((item) => item.id);

function same(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((id, index) => id === right[index]);
}
