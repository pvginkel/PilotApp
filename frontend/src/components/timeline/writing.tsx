/**
 * Pilot writing (F35): its avatar and the dancing dots at the end of a text while the turn that
 * saved it runs, as the record's writing flag says; the turn's end clears them, on the next read.
 * The dots are DesignAssistant's progress dots (`portal/src/components/workspace/
 * progress-indicator.tsx`, `animateDot` and `useDotLoop`): one dot at a time brightens and squishes
 * for 400 ms, then a random other one.
 */

import { useEffect, useRef } from 'react';
import { Avatar } from '@/components/shared/avatar';

const OPACITY_RAMP = 50;
const OPACITY_HOLD = 300;
const SQUISH_HALF = 200;
const CYCLE = 400;

/** A dot other than the last one. */
function nextDot(last: number): number {
  const candidates = [0, 1, 2].filter((index) => index !== last);
  return candidates[Math.floor(Math.random() * candidates.length)];
}

function animateDot(dot: HTMLElement, onFinish: () => void) {
  const pulse = dot.animate(
    [
      { opacity: 0.5 },
      { opacity: 1, offset: OPACITY_RAMP / CYCLE },
      { opacity: 1, offset: (OPACITY_RAMP + OPACITY_HOLD) / CYCLE },
      { opacity: 0.5 },
    ],
    { duration: CYCLE, easing: 'ease-in-out', fill: 'forwards' },
  );
  const squish = dot.animate(
    [{ transform: 'scaleY(1)' }, { transform: 'scaleY(0.4)', offset: SQUISH_HALF / CYCLE }, { transform: 'scaleY(1)' }],
    { duration: CYCLE, easing: 'ease-in-out', fill: 'forwards' },
  );
  pulse.onfinish = onFinish;
  return () => {
    pulse.cancel();
    squish.cancel();
  };
}

export function PilotWriting() {
  const dots = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    let stopped = false;
    let last = -1;
    let cancel: (() => void) | null = null;
    const next = () => {
      if (stopped) return;
      last = nextDot(last);
      cancel = animateDot(dots.current!.children[last] as HTMLElement, next);
    };
    next();
    return () => {
      stopped = true;
      cancel?.();
    };
  }, []);

  return (
    <div className="typing" title="Pilot is writing this: its turn is still running" data-testid="timeline.writing">
      <Avatar who="pilot" size="xs" />
      <span ref={dots} className="dots">
        <span />
        <span />
        <span />
      </span>
    </div>
  );
}
