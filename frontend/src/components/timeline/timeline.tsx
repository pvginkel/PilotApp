/**
 * A project's timeline (F8): its prose and work items in their order under their date and step
 * dividers (F9, F9.1), the opening first; one shorter than the page stands at its top. It opens at
 * its end, a project's own on each project (F1.6), and at its end it follows what arrives — an
 * item, a fold settling — unless the reader has scrolled away from it, or opened something that
 * took the end out of reach: the reader's own open or close never moves the top of what they read
 * (use-own-growth.ts). A new item flashes (F8.2).
 *
 * An open urgent item has a banner pinned to the top, whose Show scrolls to the item and flashes
 * it; a finished project's has none (F10.2). While open items are scrolled out above, a chip under
 * the banners counts them and scrolls to the nearest (F11). A finished project's timeline ends in
 * "Finished · <stamp>", every item but the opening done by Finish (F5.3), and under it the archive
 * question its latest finish put, open or as its done line (F5.6). A new project paused by its
 * Create has, once its setup is done, Pilot's line under the setup saying it is ready to resume,
 * with nothing to press, gone at the resume (D083).
 *
 * Pilot's jobs show on the items they follow from, not as lines of their own, the setup's aside
 * (F59.1, job.tsx).
 *
 * Opened at an item's address, the timeline goes to the item and flashes it; at a block's, to the
 * block, its collapsed section opened (F31.5), or to its item where its line or its card stands for
 * it; an address it draws nothing for leaves it at its end (F97). An address whose item the
 * timeline as read lacks — read before the item came, as a chat's quote chip can open it — waits:
 * the timeline is read again, and the address goes to its item once that read draws it, or leaves
 * the timeline where it stands once that read has landed without it. A segment opens its block's
 * collapsed section too (F33). Under a tab or the overlay it takes no focus, and keeps its scroll.
 */

import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { ArrowDown, ArrowUp, Flag, TriangleAlert } from 'lucide-react';
import { Avatar } from '@/components/shared/avatar';
import { LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import { blockKey, FlashContext, GoToContext } from '@/components/timeline/flash';
import { Item } from '@/components/timeline/item';
import { Opening } from '@/components/timeline/opening';
import { rowsOf, type Row } from '@/components/timeline/rows';
import { SectionsContext, useSections } from '@/components/timeline/sections';
import { useOwnGrowth } from '@/hooks/use-own-growth';
import { isLine, titleOf, useTimeline, type TimelineItem } from '@/hooks/use-timeline';

/** How far from the end, in pixels, still reads as at the end. */
const END_SLACK = 48;
/** How far under the banners an item's end may stand, in pixels, and still read as scrolled out above. */
const ABOVE_SLACK = 8;

/** Where the timeline is opened: an item, or one of its blocks. */
interface Address {
  item: string;
  block: string | null;
}

/** A read of the timeline an address asked for, by the address's key. */
interface Ask {
  key: string;
}

interface TimelineProps {
  projectId: string;
  address: Address | null;
  /** It lies under a tab or the overlay. */
  inert: boolean;
}

export function Timeline({ projectId, address, inert }: TimelineProps) {
  const { data, refetch, isFetching } = useTimeline(projectId);
  const items = useMemo(() => data?.items.filter(isLine), [data]);
  const finishedAt = data?.finished_at ?? null;
  const readyAfter = data?.ready_after ?? null;
  // Every finish puts one, so a finished project's latest archive question is its latest finish's.
  const question = finishedAt === null ? undefined : items?.filter((item) => item.kind === 'archive_question').at(-1);
  const placed = question === undefined ? items : items?.filter((item) => item !== question);
  const urgent = finishedAt === null ? (items ?? []).filter((item) => item.urgent && item.done === null) : [];
  const { fresh, flashed, flash } = useFresh(items);
  const sections = useSections(address === null || address.block === null ? null : blockKey(address.item, address.block));
  const feed = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const pins = useRef<HTMLDivElement>(null);
  const own = useOwnGrowth(feed);
  // The open items scrolled out above the banners, by id, in their order.
  const [above, setAbove] = useState<string[]>([]);
  // At the end until the reader scrolls away from it; it opens there.
  const atEnd = useRef(true);
  // The end was let go by the reader's own open, and no scroll has decided it since.
  const released = useRef(false);
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
    released.current = false;
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
    released.current = false;
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
  // The read an address asked for, its item lacking from the timeline as read, and the last that landed.
  const asked = useRef<Ask | null>(null);
  const [landed, setLanded] = useState<Ask | null>(null);

  useLayoutEffect(() => {
    if (atEnd.current) toEnd();
    countAbove();
  }, [data]);

  // After the pin to the end above, on every render.
  useLayoutEffect(() => {
    if (address === null) {
      reached.current = null;
      asked.current = null;
      return;
    }
    const key = address.block === null ? address.item : blockKey(address.item, address.block);
    if (data === undefined || reached.current === key) return;
    if (!data.items.some((item) => item.id === address.item)) {
      if (asked.current?.key !== key) {
        const ask = { key };
        asked.current = ask;
        // Over a read under way, which may predate the item.
        void refetch({ cancelRefetch: true }).then(() => setLanded(ask));
      }
      if (landed !== asked.current || isFetching) return;
    }
    reached.current = key;
    goTo(address);
  });

  // The timeline's own height changes, as when the head above it is drawn or the window is
  // resized, and nothing scrolls it: at its end, it stays there. Its content grows or shrinks: an
  // arrival keeps it at its end, and the reader's own open or close leaves it where it stands, no
  // longer following its end once that is out of reach, and following it again once their close
  // brings it back. A change of the column's width is a reflow.
  useLayoutEffect(() => {
    const element = feed.current!;
    const column = inner.current!;
    let width = column.offsetWidth;
    const observer = new ResizeObserver(() => {
      const reflowed = column.offsetWidth !== width;
      width = column.offsetWidth;
      if (own() && !reflowed) {
        const reach = element.scrollHeight - element.scrollTop - element.clientHeight < END_SLACK;
        if (atEnd.current && !reach) {
          atEnd.current = false;
          released.current = true;
        } else if (released.current && reach) {
          atEnd.current = true;
          released.current = false;
        }
      } else if (atEnd.current) toEnd();
      countAbove();
    });
    observer.observe(element);
    observer.observe(column);
    return () => observer.disconnect();
  }, [own]);

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
      <div ref={inner} className="feed-inner">
        <FlashContext.Provider value={{ fresh, flashed }}>
          <GoToContext.Provider value={goToBlock}>
            <SectionsContext.Provider value={sections}>
              {placed && rowsOf(placed, readyAfter).map((row) => <TimelineRow key={row.key} row={row} fresh={fresh} flashed={flashed} />)}
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
        <span className="name">
          <LinkedText text={row.title} />
        </span>
      </div>
    );
  }
  if (row.type === 'ready') {
    return (
      <p className="project-ready" data-testid="timeline.ready">
        <Avatar who="pilot" size="xs" />
        <span>The project is ready — resume the project to start it.</span>
      </p>
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
