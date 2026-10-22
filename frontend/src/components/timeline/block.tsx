/**
 * A one-ask item's block (F31), in a panel of its own under the prose that asks. Answered, it has
 * a head: its kind, a chevron where it opens, Answered, and when and by whom, Pilot's mark on a
 * block Pilot settled (F31.1, F31.3). An answer that is not a person's, and every answer in a done
 * item, reads closed: the chosen option only, which opens, as the chevron does, to every option,
 * changeable while the item is not done (F31.2). A deferred block reads "Deferred to <task>", or
 * to the project's end, its note under it; opened, every option, none chosen, stands under that
 * line (F31.4). A note sits under its answer with its icon (F17.4).
 */

import { useState } from 'react';
import { Check, ChevronDown, ChevronUp } from 'lucide-react';
import { Time } from '@/components/shared/time';
import { DecisionOptions } from '@/components/timeline/decision';
import { blockKindOf } from '@/components/timeline/kinds';
import { Note } from '@/components/timeline/note';
import { UserAvatar } from '@/components/timeline/user-avatar';
import { useAnswer } from '@/hooks/use-answer';
import type { Block as BlockData, TimelineItem } from '@/hooks/use-timeline';
import { cn } from '@/lib/utils';

/** The answer that stands for a block sent to a task of the plan, or to the project's end. */
const DEFERRED = 'deferred';

export function Block({ item, block }: { item: TimelineItem; block: BlockData }) {
  const { answer, saving } = useAnswer(item.id, block.id);
  const [opened, setOpened] = useState(false);
  const answered = block.answer !== null || block.done !== null;
  const closable = answered && (block.by?.kind !== 'person' || item.done !== null);
  const closed = closable && !opened;
  const deferred = saving === null && block.answer === DEFERRED;
  return (
    <section
      className={cn('block solo', answered ? 'answered' : 'open')}
      data-testid="timeline.block"
      data-block-id={block.id}
      data-closed={closed}
    >
      {answered && <BlockHead block={block} closable={closable} closed={closed} onToggle={() => setOpened(!opened)} />}
      <div className="block-controls">
        {deferred && (
          <div className="answer" data-testid="timeline.block.deferred">
            <div className="said">
              Deferred to <em>{block.deferral!.title ?? "the project's end"}</em>
            </div>
            {block.note !== null && <Note text={block.note} />}
          </div>
        )}
        {!(closed && deferred) && (
          <DecisionOptions
            item={item}
            block={block}
            chosen={saving ?? (deferred ? null : block.answer)}
            closed={closed}
            live={item.done === null && saving === null}
            onOpen={() => setOpened(true)}
            onAnswer={answer}
          />
        )}
      </div>
    </section>
  );
}

interface BlockHeadProps {
  block: BlockData;
  /** The answer reads closed until opened, and the chevron toggles it. */
  closable: boolean;
  closed: boolean;
  onToggle: () => void;
}

function BlockHead({ block, closable, closed, onToggle }: BlockHeadProps) {
  const { icon: Icon, label } = blockKindOf(block);
  const toggle = closed ? 'Show every option' : 'Show only the answer';
  return (
    <div className="block-head" data-testid="timeline.block.head">
      <span className="kind" data-testid="timeline.block.kind">
        <Icon className="icon" aria-hidden="true" />
        {label}
      </span>
      {closable && (
        <button
          type="button"
          className="btn btn-ghost btn-icon toggle"
          onClick={onToggle}
          title={toggle}
          aria-label={toggle}
          aria-expanded={!closed}
          data-testid="timeline.block.toggle"
        >
          {closed ? <ChevronDown className="icon" aria-hidden="true" /> : <ChevronUp className="icon" aria-hidden="true" />}
        </button>
      )}
      <span className="chip" title="Answered" data-testid="timeline.block.answered">
        <Check className="icon" aria-hidden="true" />
        <span className="chip-label">Answered</span>
      </span>
      <span className="grow" />
      <span className="who" data-testid="timeline.block.who">
        {block.at !== null && <Time at={block.at} format="clock" testId="timeline.block.time" />}
        {block.by !== null && <UserAvatar user={block.by} size="xs" />}
      </span>
    </div>
  );
}
