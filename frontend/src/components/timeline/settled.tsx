/**
 * Settled sections, each one line (F31.5), consecutive ones a tight list: Pilot's mark, the
 * heading's words, the answer as the closed block shows it, and the note as a second muted line,
 * each clipped to its line. A click opens the whole section.
 */

import { ChevronDown, StickyNote } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { HeadingWords } from '@/components/shared/markdown';
import { DEFERRED } from '@/components/timeline/said';
import { UserAvatar } from '@/components/timeline/user-avatar';
import type { Block } from '@/hooks/use-timeline';

/** A proposal's answer, which its closed block shows as the proposal. */
const AGREE = 'Agree';

export function SettledLines({ blocks, onOpen }: { blocks: Block[]; onOpen: (block: Block) => void }) {
  return (
    <ul className="settled-lines" data-testid="timeline.settled">
      {blocks.map((block) => (
        <li key={block.id}>
          <SettledLine block={block} onOpen={() => onOpen(block)} />
        </li>
      ))}
    </ul>
  );
}

function SettledLine({ block, onOpen }: { block: Block; onOpen: () => void }) {
  return (
    <button
      type="button"
      className="settled"
      onClick={onOpen}
      title="Show the whole section"
      data-testid="timeline.settled.line"
      data-section={block.id}
    >
      <span className="settled-main">
        {/* A settled section's answer is Pilot's, and its section has a heading. */}
        <UserAvatar user={block.by!} size="xs" />
        <span className="heading" data-testid="timeline.settled.heading">
          <HeadingWords text={block.section!.heading} />
        </span>
        <span className="sep">·</span>
        <span className="answer" data-testid="timeline.settled.answer">
          <Answer block={block} />
        </span>
        <ChevronDown className="icon chevron" aria-hidden="true" />
      </span>
      {block.note !== null && (
        <span className="settled-note" title={block.note} data-testid="timeline.settled.note">
          <StickyNote className="icon" aria-hidden="true" />
          <LinkedText text={block.note} nested />
        </span>
      )}
    </button>
  );
}

/** The answer as the closed block shows it: the deferral's line, a proposal agreed to, else the answer, or an action's Done. */
function Answer({ block }: { block: Block }) {
  if (block.answer === DEFERRED) {
    return (
      <>
        {/* The API gives a deferred block its deferral; a title of none is the project's end. */}
        Deferred to <em>{block.deferral!.title ?? "the project's end"}</em>
      </>
    );
  }
  if (block.answer === null) return 'Done';
  const agreed = block.kind === 'decision' && !block.confirmation && block.options.length === 0 && block.answer === AGREE;
  return <LinkedText text={agreed ? (block.proposal ?? AGREE) : block.answer} nested />;
}
