/**
 * A held block's line (F31.7): a block Pilot's work holds, a claimed action or a block a research
 * checks a fact for, inside a document that is the person's, its section one line as a settled
 * section's is (F31.5): Pilot's mark, the heading, what Pilot does as the line's button without the
 * mark, going to the work item (F13.7), and a chevron; the claim's note under it. A click on the
 * line opens the section under it, its prose and the block's controls, and closes it again.
 */

import type { ReactNode } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { Avatar } from '@/components/shared/avatar';
import { HeadingWords, Markdown } from '@/components/shared/markdown';
import { blockKindOf } from '@/components/timeline/kinds';
import { Note } from '@/components/timeline/note';
import { PilotsButton } from '@/components/timeline/pilots';
import { underHeading } from '@/components/timeline/sections';
import type { Block, BodyPart } from '@/hooks/use-timeline';

export type Hold = NonNullable<Block['held']>;

interface HeldLineProps {
  block: Block;
  hold: Hold;
  /** Whether its section stands open under it. */
  shown: boolean;
  onToggle: () => void;
}

export function HeldLine({ block, hold, shown, onToggle }: HeldLineProps) {
  const toggle = shown ? 'Show only the line' : 'Show the whole section';
  return (
    <>
      <div className="held-line" onClick={onToggle} title={toggle} data-testid="timeline.block.held">
        <Avatar who="pilot" size="xs" />
        <span className="heading" data-testid="timeline.block.held.heading">
          {block.section === null ? blockKindOf(block).label : <HeadingWords text={block.section.heading} />}
        </span>
        <span className="sep">·</span>
        {/* Its button goes to the work item without opening the section. */}
        <span className="doing" onClick={(event) => event.stopPropagation()}>
          <PilotsButton pilots={hold} mark={false} testId="timeline.block.held.pilots" />
        </span>
        <span className="grow" />
        {/* The line's own click toggles: the chevron's reaches it. */}
        <button
          type="button"
          className="btn btn-ghost btn-icon toggle"
          aria-label={toggle}
          aria-expanded={shown}
          data-testid="timeline.block.held.toggle"
        >
          {shown ? <ChevronUp className="icon" aria-hidden="true" /> : <ChevronDown className="icon" aria-hidden="true" />}
        </button>
      </div>
      {block.note !== null && (
        <div className="held-note">
          <Note text={block.note} />
        </div>
      )}
    </>
  );
}

interface HeldBodyProps {
  /** The block's own section's parts in their order, the block among them; the block alone where it has none. */
  section: BodyPart[];
  /** The block's controls, in the block's place. */
  controls: ReactNode;
}

/** The section under its line, opened: its prose, its heading the line's, and the block's controls. */
export function HeldBody({ section, controls }: HeldBodyProps) {
  return (
    <div className="held-body" data-testid="timeline.block.held.body">
      {section.map((part, index) => {
        if (part.type === 'block') return <div key="controls" className="block-controls">{controls}</div>;
        const text = index === 0 ? underHeading(part.markdown) : part.markdown;
        return text.trim() === '' ? null : <Markdown key={`prose ${index}`} text={text} />;
      })}
    </div>
  );
}
