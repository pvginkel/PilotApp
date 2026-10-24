/**
 * The working state (ruling 6), in place of F40.2's box: DesignAssistant's cue
 * (progress-indicator.tsx), dots animated one at a time beside the phase. It is the reply's
 * current line, so its icon and words line up with the step lines above it.
 */

import { useEffect, useRef } from 'react';
import { Bot, Brain, Hourglass, PenLine, Power, Wrench } from 'lucide-react';
import type { Activity, ActivityKind } from '@/lib/chat/activity';

const ICON: Record<ActivityKind, typeof Brain> = {
  waiting: Hourglass,
  starting: Power,
  thinking: Brain,
  writing: PenLine,
  tool: Wrench,
  agent: Bot,
  working: Hourglass,
};

/** DesignAssistant's timings: a 400 ms pulse per dot, the next dot a different one. */
const CYCLE = 400;

function useDotLoop() {
  const refs = [useRef<HTMLSpanElement>(null), useRef<HTMLSpanElement>(null), useRef<HTMLSpanElement>(null)];
  useEffect(() => {
    let stopped = false;
    let last = -1;
    let anims: Animation[] = [];
    const next = () => {
      if (stopped) return;
      const candidates = [0, 1, 2].filter((i) => i !== last);
      const idx = candidates[Math.floor(Math.random() * candidates.length)]!;
      last = idx;
      const el = refs[idx]?.current;
      if (!el) return;
      const fade = el.animate(
        [{ opacity: 0.5 }, { opacity: 1, offset: 50 / CYCLE }, { opacity: 1, offset: 350 / CYCLE }, { opacity: 0.5 }],
        { duration: CYCLE, easing: 'ease-in-out', fill: 'forwards' },
      );
      const squish = el.animate([{ transform: 'scaleY(1)' }, { transform: 'scaleY(0.4)', offset: 0.5 }, { transform: 'scaleY(1)' }], {
        duration: CYCLE,
        easing: 'ease-in-out',
        fill: 'forwards',
      });
      anims = [fade, squish];
      fade.onfinish = next;
    };
    next();
    return () => {
      stopped = true;
      for (const a of anims) a.cancel();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the refs are stable
  }, []);
  return refs;
}

export function WorkingCue({ activity }: { activity: Activity }) {
  const dots = useDotLoop();
  const Icon = ICON[activity.kind];
  return (
    <div className="flex min-w-0 items-center gap-2 py-0.5 text-[13px] leading-5 text-muted-foreground" data-working data-testid="chat.cue">
      <span className="flex size-4 flex-none translate-y-px items-center justify-center">
        <Icon className="size-3.5" aria-hidden />
      </span>
      <span className="min-w-0 truncate">{activity.phase}</span>
      <span className="inline-flex flex-none translate-y-px items-center gap-0.5" aria-hidden>
        {dots.map((ref, i) => (
          <span key={i} ref={ref} className="inline-block size-1.5 origin-bottom rounded-full bg-muted-foreground/70 opacity-50" />
        ))}
      </span>
    </div>
  );
}
