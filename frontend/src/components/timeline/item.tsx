/**
 * A prose item on the timeline. Open, it is its head (F12), its title and its text, the prose drawn
 * as GFM (F29.1), the prose before its first block folding when long (F12.2); an urgent one is
 * tinted (F10.1), and one whose latest save is held shows its last published text with a dashed
 * border, a concept (F78). Done, it is its line (F13.1, F13.2).
 */

import type { AnimationEvent } from 'react';
import { StickyNote, TriangleAlert } from 'lucide-react';
import { Fold } from '@/components/shared/fold';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Time } from '@/components/shared/time';
import { kindOf } from '@/components/timeline/kinds';
import { UserAvatar } from '@/components/timeline/user-avatar';
import { blocksOf, titleOf, type BodyPart, type ProsePart, type TimelineItem, type TimelineUser } from '@/hooks/use-timeline';
import { usePerson } from '@/hooks/use-self';
import { cn } from '@/lib/utils';

interface ItemProps {
  item: TimelineItem;
  /** Newly arrived: it flashes once. */
  fresh: boolean;
  onFlashed: () => void;
}

export function Item({ item, fresh, onFlashed }: ItemProps) {
  const done = item.done !== null;
  const flashed = (event: AnimationEvent) => event.target === event.currentTarget && onFlashed();
  return (
    <article
      className={cn(
        'item',
        done ? 'collapsed' : 'open',
        !done && item.concept && 'concept',
        !done && item.urgent && 'urgent',
        fresh && 'fresh',
      )}
      onAnimationEnd={flashed}
      data-testid="timeline.item"
      data-item-id={item.id}
      data-kind={item.kind}
      data-state={done ? 'done' : 'open'}
      data-concept={item.concept}
    >
      {done ? <DoneLine item={item} /> : <OpenItem item={item} />}
    </article>
  );
}

function OpenItem({ item }: { item: TimelineItem }) {
  return (
    <div className="item-body">
      <ItemHead item={item} />
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      {/* The API gives every prose item but the opening its text. */}
      <ItemText body={item.body!} />
    </div>
  );
}

function ItemHead({ item }: { item: TimelineItem }) {
  const { icon: Icon, label } = kindOf(item);
  return (
    <div className="item-head" data-testid="timeline.item.head">
      <span className="kind" data-testid="timeline.item.kind">
        <Icon className="icon" aria-hidden="true" />
        {label}
      </span>
      <span className="sep">·</span>
      <Time at={item.created_at} format="clock" testId="timeline.item.time" />
      {item.urgent && (
        <span className="chip urgent" data-testid="timeline.item.urgent">
          <TriangleAlert className="icon" aria-hidden="true" />
          Urgent
        </span>
      )}
      {item.for_user && (
        <span className="chip for" data-testid="timeline.item.for">
          for {item.for_user.name}
        </span>
      )}
    </div>
  );
}

const isProse = (part: BodyPart): part is ProsePart => part.type === 'prose';

/** The prose before the first block folds; what comes after it shows whole. */
function ItemText({ body }: { body: BodyPart[] }) {
  const first = body.findIndex((part) => part.type === 'block');
  const lead = (first < 0 ? body : body.slice(0, first)).filter(isProse);
  const after = (first < 0 ? [] : body.slice(first + 1)).filter(isProse);
  return (
    <>
      {lead.length > 0 && (
        <Fold testId="timeline.item.text">
          {lead.map((part, index) => (
            <Markdown key={index} text={part.markdown} />
          ))}
        </Fold>
      )}
      {after.map((part, index) => (
        <div key={index} className="item-after">
          <Markdown text={part.markdown} />
        </div>
      ))}
    </>
  );
}

/** One ask in an item of its own: its line shows the person's answer under its title. */
const ONE_ASK = new Set<TimelineItem['kind']>(['decision', 'confirmation', 'question', 'action']);

interface Said {
  by: TimelineUser;
  words: string;
  note: string | null;
}

/**
 * A person's answer to a one-ask item, and its note; never what Pilot did. A confirmation's Yes or
 * No is no words: only its reason is.
 */
function saidIn(item: TimelineItem): Said | null {
  if (!ONE_ASK.has(item.kind)) return null;
  const [block] = blocksOf(item);
  if (block === undefined || block.by === null || block.by.kind === 'agent') return null;
  const words =
    item.kind === 'confirmation' || block.answer === null
      ? ''
      : block.answer === 'deferred'
        ? // The API gives a deferred block its deferral; a title of none is the project's end.
          `Deferred to ${block.deferral!.title ?? "the project's end"}`
        : block.answer;
  if (words === '' && block.note === null) return null;
  return { by: block.by, words, note: block.note };
}

/**
 * The same line for every kind: its icon, its title and when it was done; under the title the
 * person's answer to a one-ask item with its note, the other person's after their avatar. It does
 * not expand.
 */
function DoneLine({ item }: { item: TimelineItem }) {
  const me = usePerson();
  const { icon: Icon } = kindOf(item);
  const title = titleOf(item);
  const said = saidIn(item);
  return (
    <div className="line" data-testid="timeline.line">
      <span className="kind-icon">
        <Icon className="icon" aria-hidden="true" />
      </span>
      <span className="title" title={title} data-testid="timeline.line.title">
        <LinkedText text={title} />
      </span>
      {/* An item's done line is drawn only once it is done. */}
      <Time at={item.done!.at} format="clock" testId="timeline.line.time" />
      {said && (
        <span className="said" data-testid="timeline.line.said">
          <span className="said-text" title={[said.words, said.note].filter(Boolean).join(' · ')}>
            {said.by.handle !== me.handle && <UserAvatar user={said.by} size="xs" />}
            {said.words && <LinkedText text={said.words} />}
            {said.words && said.note && ' · '}
            {said.note && (
              <span className="note" data-testid="timeline.line.note">
                <StickyNote className="icon" aria-hidden="true" />
                <LinkedText text={said.note} />
              </span>
            )}
          </span>
        </span>
      )}
    </div>
  );
}
