/**
 * Settled sections, each one line (F31.5), consecutive ones a tight list: Pilot's mark, the
 * heading's words, the answer as the closed block shows it, and the note as a second muted line,
 * each clipped to its line. A click opens the whole section, under its head: Pilot's mark and the
 * heading's words, whose click folds it back to its line. Each gives its button to `button`, so
 * that the one pressed hands the keyboard focus to the one that replaces it (document.tsx).
 */

import type { RefCallback } from 'react';
import { ChevronDown, ChevronUp, StickyNote } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { HeadingWords } from '@/components/shared/markdown';
import { DEFERRED } from '@/components/timeline/said';
import { UserAvatar } from '@/components/timeline/user-avatar';
import type { Block } from '@/hooks/use-timeline';

/** A proposal's answer, which its closed block shows as the proposal. */
const AGREE = 'Agree';

type Button = RefCallback<HTMLButtonElement>;

interface SettledLinesProps {
  blocks: Block[];
  onOpen: (block: Block) => void;
  /** Takes a block's line, for the focus its head hands back. */
  button: (block: Block) => Button;
}

export function SettledLines({ blocks, onOpen, button }: SettledLinesProps) {
  return (
    <ul className="settled-lines" data-testid="timeline.settled">
      {blocks.map((block) => (
        <li key={block.id}>
          <SettledLine block={block} onOpen={() => onOpen(block)} button={button(block)} />
        </li>
      ))}
    </ul>
  );
}

function SettledLine({ block, onOpen, button }: { block: Block; onOpen: () => void; button: Button }) {
  return (
    <button
      ref={button}
      type="button"
      className="settled"
      onClick={onOpen}
      title="Show the whole section"
      aria-expanded={false}
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

/** An opened settled section's head, over its prose and its block; a click folds it back to its line. */
export function SettledHead({ block, onClose, button }: { block: Block; onClose: () => void; button: Button }) {
  return (
    <div className="settled-head">
      <button
        ref={button}
        type="button"
        className="settled open"
        onClick={onClose}
        title="Show only the line"
        aria-expanded
        data-testid="timeline.settled.head"
        data-section={block.id}
      >
        <span className="settled-main">
          <UserAvatar user={block.by!} size="xs" />
          <span className="heading" data-testid="timeline.settled.heading">
            <HeadingWords text={block.section!.heading} />
          </span>
          <ChevronUp className="icon chevron" aria-hidden="true" />
        </span>
      </button>
    </div>
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
