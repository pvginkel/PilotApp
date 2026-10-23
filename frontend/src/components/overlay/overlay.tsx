/**
 * The overlay (F28.1): a page of its own over the project's timeline, part of the page at the
 * mockup's width, opening in place, and the whole page once maximized; its cross, Esc and its
 * backdrop close it. Its body keeps its scroll while what it shows is read again, and starts at
 * its top for each thing it shows. A segment in it goes to its block in its body, which flashes
 * (F33), and opened at a block it goes there once its body draws it; either opens the block's
 * collapsed section (F31.5). On a phone it is the whole screen, with no maximize (F98.3).
 */

import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { flushSync } from 'react-dom';
import { Maximize2, Minimize2, X } from 'lucide-react';
import { blockKey, FlashContext, GoToContext, useFlashes } from '@/components/timeline/flash';
import { SectionsContext, useSections } from '@/components/timeline/sections';
import { useEscape } from '@/lib/keys';
import { cn } from '@/lib/utils';

interface OverlayProps {
  /** What it shows, by a key of its own. */
  showing: string;
  /** A block of what it shows, to go to once its body draws it. */
  at?: { item: string; block: string } | null;
  /** Before its titles: an attachment's way back to its document. */
  back?: ReactNode;
  /** Its head's titles: the title and the line under it. */
  titles: ReactNode;
  foot: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

export function Overlay({ showing, at = null, back = null, titles, foot, onClose, children }: OverlayProps) {
  const [max, setMax] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const { fresh, flashed, flash } = useFlashes();
  const sections = useSections(at === null ? null : blockKey(at.item, at.block));
  useEscape('overlay', true, onClose);
  const blockIn = (blockId: string) => body.current!.querySelector<HTMLElement>(`[data-block-id="${CSS.escape(blockId)}"]`);
  // The block is drawn in the body.
  const goTo = (itemId: string, blockId: string, behavior: ScrollBehavior = 'smooth') => {
    const element = body.current!;
    const block = blockIn(blockId)!;
    const top =
      block.getBoundingClientRect().top -
      element.getBoundingClientRect().top -
      element.clientTop +
      element.scrollTop -
      parseFloat(getComputedStyle(block).scrollMarginTop);
    element.scrollTo({ top, behavior });
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
  const resize = max ? 'Restore' : 'Maximize';

  return (
    <FlashContext.Provider value={{ fresh, flashed }}>
      <GoToContext.Provider value={goToSegment}>
        <SectionsContext.Provider value={sections}>
          <div className="sheet-backdrop" onClick={onClose} data-testid="overlay.backdrop" />
          <section className={cn('sheet', max && 'max')} data-testid="overlay">
            <div className="sheet-head" data-testid="overlay.head">
              {back}
              <div className="titles">{titles}</div>
              <button
                type="button"
                className="btn btn-ghost btn-sm btn-icon maximize"
                onClick={() => setMax(!max)}
                title={resize}
                aria-label={resize}
                data-testid="overlay.maximize"
              >
                {max ? <Minimize2 className="icon" aria-hidden="true" /> : <Maximize2 className="icon" aria-hidden="true" />}
              </button>
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
            </div>
            <div key={showing} ref={body} className="sheet-body" data-testid="overlay.body">
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

/** What it shows where a read of it fails (F113). */
export function DidNotLoad() {
  return (
    <p className="item-sub" data-testid="overlay.failed">
      The document did not load.
    </p>
  );
}
