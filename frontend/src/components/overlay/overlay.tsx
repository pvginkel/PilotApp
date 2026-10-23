/**
 * The overlay (F28.1): a page of its own over the project's timeline, part of the page at the
 * mockup's width, opening in place, and the whole page once maximized; its cross, Esc and its
 * backdrop close it. Its body keeps its scroll while what it shows is read again, and starts at
 * its top for each thing it shows. A segment in it goes to its block in its body, which flashes
 * (F33). On a phone it is the whole screen, with no maximize (F98.3).
 */

import { useRef, useState, type ReactNode } from 'react';
import { Maximize2, Minimize2, X } from 'lucide-react';
import { blockKey, FlashContext, GoToContext, useFlashes } from '@/components/timeline/flash';
import { useEscape } from '@/lib/keys';
import { cn } from '@/lib/utils';

interface OverlayProps {
  /** What it shows, by a key of its own. */
  showing: string;
  /** Its head's titles: the title and the line under it. */
  titles: ReactNode;
  foot: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

export function Overlay({ showing, titles, foot, onClose, children }: OverlayProps) {
  const [max, setMax] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const { fresh, flashed, flash } = useFlashes();
  useEscape('overlay', true, onClose);
  // A segment's block is in the body.
  const goTo = (itemId: string, blockId: string) => {
    const element = body.current!;
    const block = element.querySelector<HTMLElement>(`[data-block-id="${CSS.escape(blockId)}"]`)!;
    const top =
      block.getBoundingClientRect().top -
      element.getBoundingClientRect().top -
      element.clientTop +
      element.scrollTop -
      parseFloat(getComputedStyle(block).scrollMarginTop);
    element.scrollTo({ top, behavior: 'smooth' });
    flash(blockKey(itemId, blockId));
  };
  const resize = max ? 'Restore' : 'Maximize';

  return (
    <FlashContext.Provider value={{ fresh, flashed }}>
      <GoToContext.Provider value={goTo}>
        <div className="sheet-backdrop" onClick={onClose} data-testid="overlay.backdrop" />
        <section className={cn('sheet', max && 'max')} data-testid="overlay">
          <div className="sheet-head" data-testid="overlay.head">
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
      </GoToContext.Provider>
    </FlashContext.Provider>
  );
}
