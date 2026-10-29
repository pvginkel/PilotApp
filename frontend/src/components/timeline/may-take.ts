/**
 * Whether the auto pilot mark stands on a block (F4.4, autopilot-mark.tsx): a confirmation whose
 * reason does not ask under auto pilot, unanswered, its item open, its project's auto pilot off (DB
 * decision 58).
 */

import type { Block, TimelineItem } from '@/hooks/use-timeline';

export function autopilotMayTake(item: TimelineItem, block: Block, autopilotOff: boolean): boolean {
  return autopilotOff && item.done === null && block.answer === null && block.because?.asks_under_autopilot === false;
}
