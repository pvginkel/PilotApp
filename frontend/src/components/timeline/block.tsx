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
 * refuses until Bring back (D012). A block of a project's own document, the handbook or
 * `project.md`, has no item, and in the overlay reads only (D1): every answer closed, with no
 * chevron and no Discuss, and an unanswered block open, its controls standing disabled. A draft's
 * block in the Draft tab is answered in place, as a document's is (F47.4), its Discuss quoting it
 * into the definition chat (F39.1).
 */

import { useState } from 'react';
import { useParams } from '@tanstack/react-router';
import { Check, ChevronDown, ChevronUp } from 'lucide-react';
import { DiscussButton } from '@/components/chat/discuss-button';
import { quoteOfBlock, quoteOfDraftBlock } from '@/components/chat/discuss-quotes';
import { InChatButton } from '@/components/chat/in-chat-button';
import { Time } from '@/components/shared/time';
import { ActionAnswer } from '@/components/timeline/action';
import { ConfirmControls, Proposal } from '@/components/timeline/confirmation';
import { DecisionOptions } from '@/components/timeline/decision';
import { blockKey, useBlockFlash } from '@/components/timeline/flash';
import { blockKindOf } from '@/components/timeline/kinds';
import { Note } from '@/components/timeline/note';
import { QuestionAnswer } from '@/components/timeline/question';
import { Deferral, DEFERRED } from '@/components/timeline/said';
import { UserAvatar } from '@/components/timeline/user-avatar';
import { useAnswer, useDraftAnswer, type Answering } from '@/hooks/use-answer';
import { useArchived } from '@/hooks/use-projects';
import { isAnswered, type Block as BlockData, type TimelineItem } from '@/hooks/use-timeline';
import type { QuoteRef } from '@/lib/chat/quotes';
import { cn } from '@/lib/utils';

interface BlockProps {
  item: TimelineItem;
  block: BlockData;
  /** A one-ask item's one block, whose kind the item's head names. */
  solo?: boolean;
}

/** An item's block, answered through its item. */
export function Block({ item, block, solo = false }: BlockProps) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const answering = useAnswer(item.id, block.id);
  const archived = useArchived(projectId);
  const flash = useBlockFlash(item.id, block.id);
  return (
    <BlockPanel
      field={blockKey(item.id, block.id)}
      block={block}
      solo={solo}
      answering={answering}
      settled={item.done !== null}
      disabled={archived}
      quote={solo ? null : quoteOfBlock(item, block)}
      flash={flash}
    />
  );
}

/**
 * A block of a project's own document, the handbook or `project.md`, which no item holds; read only
 * (D1).
 */
export function DocumentBlock({ document, block }: { document: string; block: BlockData }) {
  return (
    <BlockPanel
      field={blockKey(document, block.id)}
      block={block}
      solo={false}
      answering={null}
      settled={false}
      disabled
      quote={null}
      flash={null}
    />
  );
}

interface DraftBlockProps {
  projectId: string;
  block: BlockData;
  /** The draft's title, which its Discuss's label names. */
  title: string | null;
  flash: Flash;
}

/** A block of a draft's `project.md`, in the Draft tab: answered in place (F47.4). */
export function DraftBlock({ projectId, block, title, flash }: DraftBlockProps) {
  const answering = useDraftAnswer(projectId, block.id);
  const archived = useArchived(projectId);
  return (
    <BlockPanel
      field={blockKey(`${projectId}/project.md`, block.id)}
      block={block}
      solo={false}
      answering={answering}
      settled={false}
      disabled={archived}
      quote={quoteOfDraftBlock(block, title)}
      flash={flash}
    />
  );
}

type Flash = ReturnType<typeof useBlockFlash>;

/** What a read-only block's controls take, which stand disabled. */
const unanswerable = (): never => {
  throw new Error('A read-only block takes no answer');
};

interface BlockPanelProps {
  /** The block's key, `<item>/<block>` or `<document>/<block>`: its fields keep their unsent words under it. */
  field: string;
  block: BlockData;
  solo: boolean;
  /** How it takes an answer; none where it is read only. */
  answering: Answering | null;
  /** Its item is done. */
  settled: boolean;
  /** Its controls stand and take nothing. */
  disabled: boolean;
  /** What its head's Discuss quotes; none where its head has no Discuss. */
  quote: QuoteRef | null;
  flash: Flash | null;
}

function BlockPanel({ field, block, solo, answering, settled, disabled, quote, flash }: BlockPanelProps) {
  const [opened, setOpened] = useState(false);
  const saving = answering?.saving ?? null;
  const answer = answering?.answer ?? unanswerable;
  const answered = isAnswered(block);
  const closable = answered && (answering === null || block.by?.kind !== 'person' || settled);
  const closed = closable && !opened;
  const deferred = saving === null && block.answer === DEFERRED;
  const live = !settled && saving === null;
  const off = disabled || answering === null;
  const own = deferred ? null : block.answer;

  const controls = () => {
    if (block.confirmation) {
      return (
        <ConfirmControls
          field={field}
          block={block}
          chosen={saving === null ? own : saving.answer}
          live={live && !closed}
          disabled={off}
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
            field={field}
            block={block}
            chosen={saving === null ? own : saving.answer}
            closed={closed}
            live={live}
            disabled={off}
            onOpen={answering === null ? null : () => setOpened(true)}
            onAnswer={answer}
          />
        );
      case 'question':
        return <QuestionAnswer field={field} block={block} saving={saving} closed={closed} live={live} disabled={off} onAnswer={answer} />;
      case 'action':
        return (
          <ActionAnswer
            field={field}
            block={block}
            saving={saving}
            closed={closed}
            live={live}
            disabled={off}
            onAnswer={answer}
            onDone={answering?.done ?? unanswerable}
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
      className={cn('block', solo && 'solo', answered ? 'answered' : 'open', flash?.flashing && 'flash')}
      onAnimationEnd={flash?.onAnimationEnd}
      data-testid="timeline.block"
      data-block-id={block.id}
      data-closed={closed}
    >
      {(answered || !solo) && (
        <BlockHead
          block={block}
          answered={answered}
          closed={closed}
          onToggle={closable && answering !== null ? () => setOpened(!opened) : null}
          quote={quote}
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
  block: BlockData;
  answered: boolean;
  closed: boolean;
  /** Toggles a closed answer open and closed again; none where it stays as it is. */
  onToggle: (() => void) | null;
  quote: QuoteRef | null;
}

function BlockHead({ block, answered, closed, onToggle, quote }: BlockHeadProps) {
  const { icon: Icon, label } = blockKindOf(block);
  const toggle = closed ? 'Show every option' : 'Show only the answer';
  return (
    <div className="block-head" data-testid="timeline.block.head">
      <span className="kind" data-testid="timeline.block.kind">
        <Icon className="icon" aria-hidden="true" />
        {label}
      </span>
      {onToggle !== null && (
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
      {quote !== null && (
        <DiscussButton
          quote={quote}
          title="Discuss: quote this block into the project’s chat"
          className="block-discuss"
          testId="timeline.block.discuss"
        />
      )}
    </div>
  );
}
