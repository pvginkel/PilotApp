/**
 * The phantom (§4, decision 1): the text block under way, built from its marker and the text
 * deltas after it, never stored; it goes when the main thread's next `assistant` record lands,
 * and that record shows the block whole. It streams as Markdown re-rendered per delta, its new
 * text fading in delta by delta (ruled 2026-10-18); a quote tag shows once it has closed. A
 * thinking block or a tool call under way shows in the working cue alone.
 */

import { cutOpenQuote } from '@/lib/chat/quotes';
import type { Phantom } from '@/lib/chat/stream-state';
import { Markdown } from '@/components/shared/markdown';
import { deltaMarks } from './delta-fade';

export function PhantomReply({ phantom }: { phantom: Phantom }) {
  if (phantom.block !== 'text') return null;
  const text = cutOpenQuote(phantom.text);
  if (!text) return null;
  return (
    <div className="my-0.5" data-phantom data-testid="chat.phantom">
      <Markdown text={text} deltas={deltaMarks(text, phantom.deltas)} />
    </div>
  );
}
