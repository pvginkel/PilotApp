/**
 * A block (F31), in a panel of its own under the prose that asks, in a one-ask item and in a
 * document alike: a decision's options, a question's field, an action's paste-back and buttons, a
 * confirmation's check and cross. Its head names its kind in a document, where the item's head does
 * not; answered, the head has a chevron where it opens, Answered, and when and by whom, Pilot's
 * mark on a block Pilot settled (F31.1, F31.3), *In the chat* before them on an answer given in the
 * chat, going to its message (F42.3). An answer that is not a person's, and every
 * answer in a done item, reads closed: the answer only, which opens, as the chevron does, to the
 * block's controls, live while the item is not done (F31.2). In a document its head ends in
 * Discuss, quoting the block (F39.1); a one-ask item's is its head's, quoting the item. A deferred block reads "Deferred to
 * <task>", or to the project's end, its note under it; opened, its controls, nothing chosen, stand
 * under that line (F31.4). A note sits under its answer with its icon (F17.4). Gone to at its
 * address, it flashes (F97). In an archived project its controls stand disabled, which the API
 * refuses until Bring back (D012).
 */

import { useState } from 'react';
import { useParams } from '@tanstack/react-router';
import { Check, ChevronDown, ChevronUp } from 'lucide-react';
import { DiscussButton } from '@/components/chat/discuss-button';
import { quoteOfBlock } from '@/components/chat/discuss-quotes';
import { InChatButton } from '@/components/chat/in-chat-button';
import { Time } from '@/components/shared/time';
import { ActionAnswer } from '@/components/timeline/action';
import { ConfirmControls, Proposal } from '@/components/timeline/confirmation';
import { DecisionOptions } from '@/components/timeline/decision';
import { useBlockFlash } from '@/components/timeline/flash';
import { blockKindOf } from '@/components/timeline/kinds';
import { Note } from '@/components/timeline/note';
import { QuestionAnswer } from '@/components/timeline/question';
import { Deferral, DEFERRED } from '@/components/timeline/said';
import { UserAvatar } from '@/components/timeline/user-avatar';
import { useAnswer } from '@/hooks/use-answer';
import { useArchived } from '@/hooks/use-projects';
import { isAnswered, type Block as BlockData, type TimelineItem } from '@/hooks/use-timeline';
import { cn } from '@/lib/utils';

interface BlockProps {
  item: TimelineItem;
  block: BlockData;
  /** A one-ask item's one block, whose kind the item's head names. */
  solo?: boolean;
}

export function Block({ item, block, solo = false }: BlockProps) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const { answer, done, saving } = useAnswer(item.id, block.id);
  const archived = useArchived(projectId);
  const { flashing, onAnimationEnd } = useBlockFlash(item.id, block.id);
  const [opened, setOpened] = useState(false);
  const answered = isAnswered(block);
  const closable = answered && (block.by?.kind !== 'person' || item.done !== null);
  const closed = closable && !opened;
  const deferred = saving === null && block.answer === DEFERRED;
  const live = item.done === null && saving === null;
  const own = deferred ? null : block.answer;

  const controls = () => {
    if (block.confirmation) {
      return (
        <ConfirmControls
          item={item}
          block={block}
          chosen={saving === null ? own : saving.answer}
          live={live && !closed}
          disabled={archived}
          onAnswer={answer}
        >
          <Proposal block={block} />
          {saving === null && !deferred && block.note !== null && <Note text={block.note} />}
        </ConfirmControls>
      );
    }
    switch (block.kind) {
      case 'decision':
        return (
          <DecisionOptions
            item={item}
            block={block}
            chosen={saving === null ? own : saving.answer}
            closed={closed}
            live={live}
            disabled={archived}
            onOpen={() => setOpened(true)}
            onAnswer={answer}
          />
        );
      case 'question':
        return (
          <QuestionAnswer item={item} block={block} saving={saving} closed={closed} live={live} disabled={archived} onAnswer={answer} />
        );
      case 'action':
        return (
          <ActionAnswer
            item={item}
            block={block}
            saving={saving}
            closed={closed}
            live={live}
            disabled={archived}
            onAnswer={answer}
            onDone={done}
          />
        );
      default: {
        const unknown: never = block.kind;
        throw new Error(`A block of kind ${String(unknown)} has no controls`);
      }
    }
  };

  return (
    <section
      className={cn('block', solo && 'solo', answered ? 'answered' : 'open', flashing && 'flash')}
      onAnimationEnd={onAnimationEnd}
      data-testid="timeline.block"
      data-block-id={block.id}
      data-closed={closed}
    >
      {(answered || !solo) && (
        <BlockHead
          item={item}
          block={block}
          solo={solo}
          answered={answered}
          closable={closable}
          closed={closed}
          onToggle={() => setOpened(!opened)}
        />
      )}
      <div className="block-controls">
        {deferred && <Deferral block={block} />}
        {!(closed && deferred) && controls()}
      </div>
    </section>
  );
}

interface BlockHeadProps {
  item: TimelineItem;
  block: BlockData;
  solo: boolean;
  answered: boolean;
  /** The answer reads closed until opened, and the chevron toggles it. */
  closable: boolean;
  closed: boolean;
  onToggle: () => void;
}

function BlockHead({ item, block, solo, answered, closable, closed, onToggle }: BlockHeadProps) {
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
      {answered && (
        <span className="chip" title="Answered" data-testid="timeline.block.answered">
          <Check className="icon" aria-hidden="true" />
          <span className="chip-label">Answered</span>
        </span>
      )}
      <span className="grow" />
      {answered && (
        <span className="who" data-testid="timeline.block.who">
          {block.in_chat !== null && <InChatButton place={block.in_chat} testId="timeline.block.in-chat" />}
          {block.at !== null && <Time at={block.at} format="clock" testId="timeline.block.time" />}
          {block.by !== null && <UserAvatar user={block.by} size="xs" />}
        </span>
      )}
      {!solo && (
        <DiscussButton
          quote={quoteOfBlock(item, block)}
          title="Discuss: quote this block into the project’s chat"
          className="block-discuss"
          testId="timeline.block.discuss"
        />
      )}
    </div>
  );
}
