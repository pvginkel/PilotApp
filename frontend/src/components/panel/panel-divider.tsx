/**
 * The divider between the side panel and what stands left of it, off a phone, in a project and a
 * draft alike (R12): dragged, or moved by the arrow keys while it has the focus, it sets the
 * panel's width, which the browser keeps, every project's in pixels and every draft's as a share of
 * the window, dragging one leaving the other (F133). Whatever is kept, the panel stands no narrower
 * than `PANEL_LEAST` and leaves `BESIDE_LEAST` to its left, the timeline's column, a draft's chat
 * or the tab showing, at every width off a phone, 901 px included; a width held in for want of room
 * stays kept as it was. It sets `--panel` on the project's page, which the panel's width reads
 * (panel.css).
 */

import { useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { rememberPanelWidth, useBrowserState } from '@/lib/browser-state';

const PANEL_LEAST = 320;
const BESIDE_LEAST = 440;
/** How far an arrow key moves the divider. */
const STEP = 16;

interface PanelDividerProps {
  /** The project's page, the panel's and what stands left of it, once drawn. */
  project: HTMLElement | null;
  /** The project is a draft. */
  draft: boolean;
}

export function PanelDivider({ project, draft }: PanelDividerProps) {
  const kept = useBrowserState().panelWidths;
  const [room, setRoom] = useState<{ page: number; window: number } | null>(null);
  // While dragged: where the pointer went down and the width then; and the width it asks for now.
  const drag = useRef<{ x: number; width: number } | null>(null);
  const [dragged, setDragged] = useState<number | null>(null);

  useLayoutEffect(() => {
    if (project === null) return undefined;
    const measure = () => setRoom({ page: project.getBoundingClientRect().width, window: window.innerWidth });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(project);
    return () => observer.disconnect();
  }, [project]);

  const most = room === null ? null : room.page - BESIDE_LEAST;
  const held = (width: number) => Math.round(Math.max(PANEL_LEAST, Math.min(width, most!)));
  const width = room === null ? null : held(dragged ?? (draft ? kept.draft * room.window : kept.project));

  useLayoutEffect(() => {
    if (project === null || width === null) return undefined;
    project.style.setProperty('--panel', `${width}px`);
    return () => {
      project.style.removeProperty('--panel');
    };
  }, [project, width]);

  const keep = (to: number) => rememberPanelWidth(draft ? 'draft' : 'project', draft ? to / room!.window : to);
  const asked = (event: PointerEvent) => drag.current!.width + drag.current!.x - event.clientX;
  const start = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || width === null) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, width };
    setDragged(width);
  };
  const move = (event: PointerEvent) => {
    if (drag.current !== null) setDragged(asked(event));
  };
  const end = (event: PointerEvent) => {
    if (drag.current === null) return;
    const to = held(asked(event));
    // A press that moved nothing keeps no width held in for want of room.
    if (to !== drag.current.width) keep(to);
    drag.current = null;
    setDragged(null);
  };
  const cancel = () => {
    drag.current = null;
    setDragged(null);
  };
  const step = (event: KeyboardEvent) => {
    const by = event.key === 'ArrowLeft' ? STEP : event.key === 'ArrowRight' ? -STEP : 0;
    if (by === 0 || width === null) return;
    event.preventDefault();
    const to = held(width + by);
    if (to !== width) keep(to);
  };

  return (
    <div
      className="panel-divider"
      role="separator"
      aria-orientation="vertical"
      aria-label="The side panel’s width"
      aria-valuenow={width ?? undefined}
      aria-valuemin={PANEL_LEAST}
      aria-valuemax={most ?? undefined}
      tabIndex={0}
      data-dragging={dragged !== null ? '' : undefined}
      onPointerDown={start}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={cancel}
      onKeyDown={step}
      data-testid="panel.divider"
    />
  );
}
