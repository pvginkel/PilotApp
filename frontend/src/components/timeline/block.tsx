/**
 * A block (F31), in a panel of its own under the prose that asks, in a one-ask item and in a
 * document alike: a decision's options, a question's field, an action's paste-back and buttons, a
 * confirmation's check and cross. Its head names its kind in a document, where the item's head does
 * not, the auto pilot mark beside it on a confirmation the switch would answer (F4.4), then, where
 * Pilot asked the registered document's writer about it, "Pilot asked the writer", a button that
 * opens the document at the questions and the reply (F52.2; writer-asked.tsx); answered,
 * the head has a chevron where it opens, Answered, and when and by whom, Pilot's mark on a block
 * Pilot settled (F31.1, F31.3), *In the chat* before them on an answer given in the
 * chat, going to its message (F42.3). An answer that is not a person's, and every
 * answer in a done item, reads closed: the answer only, which opens, as the chevron does, to the
 * block's controls, live while the item is not done (F31.2). In a document its head ends in
 * Discuss, quoting the block (F39.1); a one-ask item's is its head's, quoting the item. A deferred block reads "Deferred to
 * <task>", or to the project's end, its note under it; opened, its controls, nothing chosen, stand
 * under that line (F31.4). A note sits under its answer with its icon (F17.4). Gone to at its
 * address, it flashes (F97). In an archived project its controls stand disabled, which the API
 * refuses until Bring back (D012), and so do they in a document that is Pilot's, opened (F28.9).
 * A block Pilot's work holds, inside a document that is the person's, is its section's line (F31.7;
 * held.tsx), its controls under it, once opened, taking nothing, as the API refuses them (DB 295).
 * A block of a project's own document, the handbook or
 * `project.md`, has no item, and in the overlay reads only (D1): every answer closed, with no
 * chevron and no Discuss, and an unanswered block open, its controls standing disabled. An action
 * Pilot claimed is open until its Done, its controls a person's while no work holds it; one Pilot's
 * work handed back reads no claim, its head, drawn in a one-ask item too, saying Pilot's work left it
 * undone (F21.6). A draft's
 * block in the Draft tab is answered in place, as a document's is (F47.4), its Discuss quoting it
 * into the definition chat (F39.1).
 */

import { useContext, useState } from 'react';
import { Check, ChevronDown, ChevronUp } from 'lucide-react';
import { DiscussButton } from '@/components/chat/discuss-button';
import { quoteOfBlock, quoteOfDraftBlock } from '@/components/chat/discuss-quotes';
import { InChatButton } from '@/components/chat/in-chat-button';
import { Avatar } from '@/components/shared/avatar';
import { Time } from '@/components/shared/time';
import { ActionAnswer } from '@/components/timeline/action';
import { AutopilotMark } from '@/components/timeline/autopilot-mark';
import { ConfirmControls, Proposal } from '@/components/timeline/confirmation';
import { DecisionOptions, EXPAND } from '@/components/timeline/decision';
import { blockKey, useBlockFlash } from '@/components/timeline/flash';
import { HeldBody, HeldLine, type Hold } from '@/components/timeline/held';
import { blockKindOf } from '@/components/timeline/kinds';
import { LockedContext } from '@/components/timeline/locked';
import { autopilotMayTake } from '@/components/timeline/may-take';
import { Note } from '@/components/timeline/note';
import { QuestionAnswer } from '@/components/timeline/question';
import { Deferral, DEFERRED } from '@/components/timeline/said';
import { SectionsContext } from '@/components/timeline/sections';
import { UserAvatar } from '@/components/timeline/user-avatar';
import { WriterAsked } from '@/components/timeline/writer-asked';
import { useAnswer, useDraftAnswer, type Answering } from '@/hooks/use-answer';
import { useShownProject } from '@/hooks/use-project-address';
import { useArchived, useAutopilotOff } from '@/hooks/use-projects';
import { isAnswered, type Block as BlockData, type BodyPart, type TimelineItem } from '@/hooks/use-timeline';
import type { QuoteRef } from '@/lib/chat/quotes';
import { cn } from '@/lib/utils';

interface BlockProps {
  item: TimelineItem;
  block: BlockData;
  /** A one-ask item's one block, whose kind the item's head names. */
  solo?: boolean;
  /** Its own section's parts in their order, itself among them, which its line folds while it is held. */
  section?: BodyPart[];
}

/** An item's block, answered through its item. */
export function Block({ item, block, solo = false, section = [{ type: 'block', block }] }: BlockProps) {
  const { id: projectId } = useShownProject();
  const answering = useAnswer(item.id, block.id);
  const archived = useArchived(projectId);
  const locked = useContext(LockedContext);
  const autopilotOff = useAutopilotOff(projectId);
  const flash = useBlockFlash(item.id, block.id);
  const sections = useContext(SectionsContext);
  // Closed by its chevron after it was opened, by a click, a segment or its address.
  const [shut, setShut] = useState(false);
  const key = blockKey(item.id, block.id);
  const shown = sections.opened.has(key) && !shut;
  const toggle = () => {
    if (shown) {
      setShut(true);
      return;
    }
    sections.open(key);
    setShut(false);
  };
  // A document that is Pilot's draws every block whole (F28.9).
  const held = block.held === null || locked ? null : { hold: block.held, section, shown, onToggle: toggle };
  return (
    <BlockPanel
      field={key}
      block={block}
      solo={solo}
      mayTake={autopilotMayTake(item, block, autopilotOff)}
      answering={answering}
      settled={item.done !== null}
      disabled={archived || locked || block.held !== null}
      quote={solo ? null : quoteOfBlock(item, block)}
      asked={block.writer_asked && !solo ? item.id : null}
      flash={flash}
      held={held}
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
      mayTake={false}
      answering={null}
      settled={false}
      disabled
      quote={null}
      asked={null}
      flash={null}
      held={null}
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
      mayTake={false}
      answering={answering}
      settled={false}
      disabled={archived}
      quote={quoteOfDraftBlock(block, title)}
      asked={null}
      flash={flash}
      held={null}
    />
  );
}

type Flash = ReturnType<typeof useBlockFlash>;

/** A held block's line: what holds it, its section, and whether the section stands open under it. */
interface Held {
  hold: Hold;
  section: BodyPart[];
  shown: boolean;
  onToggle: () => void;
}

/** What a read-only block's controls take, which stand disabled. */
const unanswerable = (): never => {
  throw new Error('A read-only block takes no answer');
};

interface BlockPanelProps {
  /** The block's key, `<item>/<block>` or `<document>/<block>`: its fields keep their unsent words under it. */
  field: string;
  block: BlockData;
  solo: boolean;
  /** Its head carries the auto pilot mark. */
  mayTake: boolean;
  /** How it takes an answer; none where it is read only. */
  answering: Answering | null;
  /** Its item is done. */
  settled: boolean;
  /** Its controls stand and take nothing. */
  disabled: boolean;
  /** What its head's Discuss quotes; none where its head has no Discuss. */
  quote: QuoteRef | null;
  /** The document its head's mark opens at the questions to its writer; none where it carries no mark. */
  asked: string | null;
  flash: Flash | null;
  /** Its line, where Pilot's work holds it inside a document that is the person's; none otherwise. */
  held: Held | null;
}

function BlockPanel({ field, block, solo, mayTake, answering, settled, disabled, quote, asked, flash, held }: BlockPanelProps) {
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
  const undone = block.claim?.undone ?? false;

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
            claimed={!undone && held === null}
            saving={saving}
            closed={closed}
            live={live}
            settled={settled}
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

  if (held !== null) {
    return (
      <section
        className={cn('block held', flash?.flashing && 'flash')}
        onAnimationEnd={flash?.onAnimationEnd}
        data-testid="timeline.block"
        data-block-id={block.id}
      >
        <HeldLine block={block} hold={held.hold} shown={held.shown} onToggle={held.onToggle} />
        {held.shown && <HeldBody section={held.section} controls={controls()} />}
      </section>
    );
  }

  return (
    <section
      className={cn('block', solo && 'solo', answered ? 'answered' : 'open', flash?.flashing && 'flash')}
      onAnimationEnd={flash?.onAnimationEnd}
      data-testid="timeline.block"
      data-block-id={block.id}
      data-closed={closed}
    >
      {(answered || !solo || undone) && (
        <BlockHead
          block={block}
          mayTake={mayTake}
          asked={asked}
          undone={undone}
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
  mayTake: boolean;
  /** The document its mark opens at the questions to its writer, where Pilot asked the writer about it. */
  asked: string | null;
  /** Pilot's work on its claim left it undone (F21.6). */
  undone: boolean;
  answered: boolean;
  closed: boolean;
  /** Toggles a closed answer open and closed again; none where it stays as it is. */
  onToggle: (() => void) | null;
  quote: QuoteRef | null;
}

function BlockHead({ block, mayTake, asked, undone, answered, closed, onToggle, quote }: BlockHeadProps) {
  const { icon: Icon, label } = blockKindOf(block);
  const toggle = closed ? EXPAND : 'Show only the answer';
  return (
    <div className="block-head" data-testid="timeline.block.head">
      <span className="kind" data-testid="timeline.block.kind">
        <Icon className="icon" aria-hidden="true" />
        {label}
      </span>
      {mayTake && <AutopilotMark testId="timeline.block.autopilot-mark" />}
      {asked !== null && <WriterAsked documentId={asked} testId="timeline.block.writer-asked" />}
      {/* The API names the work item of every claim it hands back. */}
      {undone && (
        <span
          className="pilot-mark undone"
          title={`${block.claim!.work!.title} ended without doing it: it is yours again`}
          data-testid="timeline.block.undone"
        >
          <Avatar who="pilot" size="xs" />
          Pilot’s work left it undone
        </span>
      )}
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
