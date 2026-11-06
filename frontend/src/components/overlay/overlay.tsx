/**
 * The overlay (F28.1): what opens as a document. Off a phone a document, an attachment, the
 * handbook and the project document are each a tab (`use-doc-tabs.ts`): in the timeline's place,
 * the side panel beside it, at the timeline's width, on the page's own colour, its head's and its
 * foot's text in the timeline's column; no maximize, backdrop or cross, closed by its tab's cross
 * or Done and never by Esc; its body's scroll kept while another tab shows, set back once its read
 * is drawn. It takes the focus as it shows where the focus would be lost under it, and gives it
 * back as it closes to what had it before where the focus is lost then. Off a phone the session
 * log is a popover over the tab showing (F69.1): in one place and of one size, 90 % of the
 * column's text width, centred on it and between the stage's top and bottom, at most 560 px high,
 * not scrolling with what lies under it; its cross, Esc and a press outside it close it, and so
 * does a click on a link to its own address, its opener's. It takes the focus as it opens, and
 * gives it back as it closes to what had it before where the focus is lost then.
 * Its body keeps its scroll while what it shows is read again, and starts at its top for each thing
 * it shows afresh. A segment in it goes to
 * its block in its body, which flashes (F33), and opened at a block it goes there once its body
 * draws it; either opens the block's collapsed section (F31.5). Its head carries Discuss, quoting
 * what it shows (F39.1), its buttons level with its title's first line; a strip under its head,
 * where what it shows has one, says what Pilot does on it (F28.9). On a phone it is a view pushed
 * over the tabs (F98.4): the whole screen over the head and the tabs, with no animation, no
 * backdrop, no maximize and no cross, an arrow back at the left of its head where the head's drawer
 * button stands; the arrow, Esc and Back take it off (`use-phone-tab.ts`), and its body keeps its
 * scroll while another view lies over it, set back as it shows again once its read is drawn. There
 * it takes the focus as it opens, and again when what it shows replaces what had it, and gives it
 * back as it closes to what had it before, as a dialog does; the timeline under it takes none
 * meanwhile (the project's route).
 */

import { useContext, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { flushSync } from 'react-dom';
import { ArrowLeft, X } from 'lucide-react';
import { scrollToIn } from '@/components/overlay/scroll-to';
import { blockKey, FlashContext, GoToContext, useFlashes } from '@/components/timeline/flash';
import { SectionsContext, useSections } from '@/components/timeline/sections';
import { DocTabContext } from '@/hooks/use-doc-tabs';
import { PhoneViewContext } from '@/hooks/use-phone-tab';
import { useEscape } from '@/lib/keys';
import { cn } from '@/lib/utils';

interface OverlayProps {
  /** What it shows, by a key of its own. */
  showing: string;
  /** A block of what it shows, to go to once its body draws it. */
  at?: { item: string; block: string } | null;
  /** Its head's titles: the title and the line under it. */
  titles: ReactNode;
  /** Its head's Discuss, once what it shows is read. */
  discuss?: ReactNode;
  /** Under its head: what Pilot does on a document that is Pilot's. */
  strip?: ReactNode;
  foot: ReactNode;
  /** Closes it: `useOverlayClose`'s; off a phone, a tab's close is its tab's. */
  onClose: () => void;
  /** Its body, the scroll container, for what it shows. */
  bodyRef?: RefObject<HTMLDivElement | null>;
  /** Its body's scroll is its own, kept by no tab or view: the session log's, which sticks to its end (F69.2). */
  ownScroll?: boolean;
  children: ReactNode;
}

export function Overlay({
  showing,
  at = null,
  titles,
  discuss = null,
  strip = null,
  foot,
  onClose,
  bodyRef,
  ownScroll = false,
  children,
}: OverlayProps) {
  const phoneView = useContext(PhoneViewContext);
  const view = phoneView !== null;
  const tab = useContext(DocTabContext);
  const inTab = tab !== null;
  // Off a phone outside a tab: the session log's popover.
  const pop = !view && !inTab;
  // Where its body's scroll is kept while another tab shows, or another view lies over it.
  const kept = ownScroll ? null : (tab ?? phoneView);
  const sheet = useRef<HTMLElement>(null);
  const titlesId = useId();
  const [opener] = useState(() => document.activeElement);
  useEffect(() => {
    if (sheet.current!.contains(document.activeElement) || (inTab && !focusLost())) return;
    sheet.current!.focus({ preventScroll: true });
  }, [showing, inTab]);
  useEffect(
    () => () => {
      if (!(opener instanceof HTMLElement) || !opener.isConnected) return;
      // A press outside a popover gives the focus to what it pressed.
      if (!view && (!focusLost() || opener.closest('[inert]') !== null)) return;
      opener.focus();
    },
    [opener, view],
  );
  const closing = useRef(onClose);
  useEffect(() => {
    closing.current = onClose;
  });
  useEffect(() => {
    if (!pop) return undefined;
    const outside = (event: Event) => !sheet.current!.contains(event.target as Node);
    // A link to the address showing, the popover's: its opener, whose click closes it.
    const own = (event: Event) => {
      const link = (event.target as Element).closest('a[href]');
      return link instanceof HTMLAnchorElement && link.origin === window.location.origin && link.pathname === window.location.pathname;
    };
    const press = (event: PointerEvent) => {
      if (outside(event) && !own(event)) closing.current();
    };
    // Before the link's own handler, which would go to the address showing.
    const click = (event: MouseEvent) => {
      if (!outside(event) || !own(event) || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      event.stopPropagation();
      closing.current();
    };
    document.addEventListener('pointerdown', press);
    document.addEventListener('click', click, true);
    return () => {
      document.removeEventListener('pointerdown', press);
      document.removeEventListener('click', click, true);
    };
  }, [pop]);
  const ownBody = useRef<HTMLDivElement>(null);
  const body = bodyRef ?? ownBody;
  const { fresh, flashed, flash } = useFlashes();
  const sections = useSections(at === null ? null : blockKey(at.item, at.block));
  useEscape('overlay', !inTab, onClose);
  // Its body for what it shows is where it was left, as its body mounts.
  const [left, setLeft] = useState(() => ({ showing, top: kept?.scroll ?? 0 }));
  if (left.showing !== showing) setLeft({ showing, top: kept?.scroll ?? 0 });
  // A tab's head's and foot's text stand in its column, which the body's scrollbar narrows; the
  // popover centres on the column of what lies under it, narrowed by a scrollbar as wide.
  useLayoutEffect(() => {
    if (view) return;
    const element = sheet.current!.querySelector<HTMLElement>(':scope > .sheet-body')!;
    sheet.current!.style.setProperty('--gutter', `${element.offsetWidth - element.clientWidth}px`);
  }, [left, view]);
  // What its body draws may come after the body mounts, its read gone from the cache: the scroll is
  // set back once, as its column first draws, unless it scrolls first. The browser holds it to
  // what the body reaches.
  useLayoutEffect(() => {
    if (left.top === 0) return;
    const element = sheet.current!.querySelector<HTMLElement>(':scope > .sheet-body')!;
    const column = element.firstElementChild!;
    const setBack = () => {
      if (!draws(column)) return false;
      element.scrollTop = left.top;
      return true;
    };
    if (setBack()) return;
    const observer = new ResizeObserver(() => {
      if (setBack()) stop();
    });
    const stop = () => {
      observer.disconnect();
      element.removeEventListener('scroll', stop);
    };
    observer.observe(column);
    element.addEventListener('scroll', stop);
    return stop;
  }, [left]);
  const blockIn = (blockId: string) => body.current!.querySelector<HTMLElement>(`[data-block-id="${CSS.escape(blockId)}"]`);
  // The block is drawn in the body.
  const goTo = (itemId: string, blockId: string, behavior: ScrollBehavior = 'smooth') => {
    scrollToIn(body.current!, blockIn(blockId)!, behavior);
    flash(blockKey(itemId, blockId));
  };
  const goToSegment = (itemId: string, blockId: string) => {
    // Its collapsed section opens first, so that the block is drawn to go to.
    flushSync(() => sections.open(blockKey(itemId, blockId)));
    goTo(itemId, blockId);
  };
  // The block it was opened at, once gone to.
  const reached = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (at === null) return;
    const key = blockKey(at.item, at.block);
    if (reached.current === key || blockIn(at.block) === null) return;
    reached.current = key;
    goTo(at.item, at.block, 'instant');
  });

  return (
    <FlashContext.Provider value={{ fresh, flashed }}>
      <GoToContext.Provider value={goToSegment}>
        <SectionsContext.Provider value={sections}>
          <section
            ref={sheet}
            className={cn('sheet', inTab && 'tabbed', pop && 'pop')}
            role={inTab ? 'tabpanel' : 'dialog'}
            aria-labelledby={titlesId}
            tabIndex={-1}
            data-testid="overlay"
          >
            <div className="sheet-head" data-testid="overlay.head">
              {view ? (
                <button
                  type="button"
                  className="btn btn-ghost btn-icon view-back"
                  onClick={onClose}
                  title="Back"
                  aria-label="Back"
                  data-testid="overlay.back"
                >
                  <ArrowLeft className="icon" aria-hidden="true" />
                </button>
              ) : null}
              <div id={titlesId} className="titles">
                {titles}
              </div>
              {discuss}
              {pop && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm btn-icon"
                  onClick={onClose}
                  title="Close (Esc)"
                  aria-label="Close"
                  data-testid="overlay.close"
                >
                  <X className="icon" aria-hidden="true" />
                </button>
              )}
            </div>
            {strip}
            <div
              key={showing}
              ref={body}
              className="sheet-body"
              onScroll={kept === null ? undefined : (event) => kept.keep(event.currentTarget.scrollTop)}
              data-testid="overlay.body"
            >
              <div className="column">{children}</div>
            </div>
            {foot && (
              <div className="sheet-foot" data-testid="overlay.foot">
                {foot}
              </div>
            )}
          </section>
        </SectionsContext.Provider>
      </GoToContext.Provider>
    </FlashContext.Provider>
  );
}

/** No element has the focus, or the one that has it lies under what an `inert` takes out. */
function focusLost(): boolean {
  const active = document.activeElement;
  return active === null || active === document.body || active.closest('[inert]') !== null;
}

/** The column holds something drawn: its height is more than its padding's. */
function draws(column: Element): boolean {
  const style = getComputedStyle(column);
  return column.clientHeight > parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
}

/** What it shows where a read of it fails (F113). */
export function DidNotLoad({ what = 'The document' }: { what?: string }) {
  return (
    <p className="item-sub" data-testid="overlay.failed">
      {what} did not load.
    </p>
  );
}
