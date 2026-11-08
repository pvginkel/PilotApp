/**
 * An open wait on the timeline (F27), as `design/ui-conventions.md` has it. Its head carries the
 * request's one button, an icon alone touching Discuss, its label its tooltip: *Check now* on a
 * card wait, *Skip wait* on a timed wait (F27.3). A press records the person's request, which fires
 * the wait; while the wait takes none the button is disabled, the server's reason its tooltip,
 * "Pilot is checking". A card wait shows its cards as ticket links (F93) and the states it waits
 * for, "Waiting since <time>", and its firings, one line each, with what the brain did with it
 * after its time where it did anything: "SR-4 → Done · 01:12 · left open" (F27.1). A timed wait
 * shows "Due in 7 minutes", one coarse unit from minutes to weeks, "Due now" under a minute, then
 * "Due 5 minutes ago", and what the brain did once its due time fired it: "· Pilot’s turn"
 * (F27.2); its requests are its other firings' lines. Every time has its full stamp as its
 * tooltip. It updates as the project's live event brings its firings and its runs' ends.
 */

import { Fragment, useState } from 'react';
import { LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import { HourglassSkip } from '@/components/timeline/hourglass-skip';
import { ItemHead } from '@/components/timeline/item-head';
import { useNow } from '@/hooks/use-now';
import { useToday } from '@/hooks/use-today';
import { titleOf, type TimelineItem } from '@/hooks/use-timeline';
import { usePostItemsRequestByItemId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';
import { clockFormat, formatTime } from '@/lib/utils/time-format';

type Wait = components['schemas']['TimelineSchema.1fdd8ae.WaitSchema'];
type Firing = Wait['firings'][number];
type WaitKind = Extract<TimelineItem['kind'], 'card_wait' | 'timed_wait'>;

/** What the brain did with a firing, after its time. */
const OUTCOMES: Record<NonNullable<Firing['outcome']>, string> = {
  pilots_turn: 'Pilot’s turn',
  left_open: 'left open',
  closed: 'closed',
};

/** A request's firing by the button it was pressed with: "Check requested by pieter". */
const REQUESTED: Record<WaitKind, string> = { card_wait: 'Check', timed_wait: 'Skip' };

/** How often a timed wait's due time is counted again, in milliseconds. */
const TICK = 15_000;

const MINUTE = 60_000;
/** The coarse units, the largest count each is used for before the next takes over. */
const UNITS: [string, number, number][] = [
  ['minute', MINUTE, 60],
  ['hour', 60 * MINUTE, 24],
  ['day', 24 * 60 * MINUTE, 7],
  ['week', 7 * 24 * 60 * MINUTE, Infinity],
];

function coarse(span: number): string {
  // The last unit has no bound.
  const [unit, size] = UNITS.find(([, each, below]) => Math.round(span / each) < below)!;
  const count = Math.round(span / size);
  return `${count} ${unit}${count === 1 ? '' : 's'}`;
}

/** "Due in 7 minutes", "Due now" under a minute either side, "Due 5 minutes ago". */
function dueWords(left: number): string {
  if (Math.abs(left) < MINUTE) return 'Due now';
  return left > 0 ? `Due in ${coarse(left)}` : `Due ${coarse(-left)} ago`;
}

/** "Done", "Done or Won't fix", "Done, Won't fix or Duplicate". */
function either(states: string[]): string {
  return states.length === 1 ? states[0] : `${states.slice(0, -1).join(', ')} or ${states.at(-1)}`;
}

export function WaitItem({ item }: { item: TimelineItem }) {
  // The API gives every wait its own, and a wait's kind is one of the two.
  const wait = item.wait!;
  const kind = item.kind as WaitKind;
  return (
    <div className="item-body">
      <ItemHead item={item}>
        <RequestButton item={item} wait={wait} />
      </ItemHead>
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      {kind === 'card_wait' ? (
        <>
          <CardsAndStates cards={wait.cards!} states={wait.states!} />
          <Since at={item.created_at} />
          <Firings kind={kind} firings={wait.firings} />
        </>
      ) : (
        <>
          <Due at={wait.due_at!} firing={wait.firings.find((firing) => firing.cause === 'due')} />
          <Firings kind={kind} firings={wait.firings.filter((firing) => firing.cause !== 'due')} />
        </>
      )}
    </div>
  );
}

/** The cards, each a ticket link, and the states that fire the wait: "SR-1, SR-4 → Done or Won't fix". */
function CardsAndStates({ cards, states }: { cards: string[]; states: string[] }) {
  return (
    <p className="item-sub wait-on" data-testid="timeline.wait.on">
      {cards.map((card, index) => (
        <Fragment key={card}>
          {index > 0 && ', '}
          <span data-testid="timeline.wait.card">
            <LinkedText text={card} />
          </span>
        </Fragment>
      ))}
      {' → '}
      <span data-testid="timeline.wait.states">{either(states)}</span>
    </p>
  );
}

function Since({ at }: { at: string }) {
  const today = useToday();
  return (
    <p className="item-sub" data-testid="timeline.wait.since">
      Waiting since <Time at={at} format={clockFormat(at, today)} />
    </p>
  );
}

/** A timed wait's due time from now, counted again each tick, and what the brain did once it fired. */
function Due({ at, firing }: { at: string; firing: Firing | undefined }) {
  const now = useNow(TICK);
  return (
    <p className="item-sub" data-testid="timeline.wait.due">
      <time dateTime={at} title={formatTime(at, 'full')}>
        {dueWords(Date.parse(at) - now)}
      </time>
      {firing?.outcome && <Outcome firing={firing} />}
    </p>
  );
}

function Firings({ kind, firings }: { kind: WaitKind; firings: Firing[] }) {
  const today = useToday();
  if (firings.length === 0) return null;
  return (
    <ul className="wait-firings" data-testid="timeline.wait.firings">
      {firings.map((firing) => (
        <li key={firing.seq} data-testid="timeline.wait.firing" data-cause={firing.cause}>
          {firing.transition !== null ? (
            <LinkedText text={`${firing.transition.card} → ${firing.transition.to_state}`} />
          ) : (
            // The API names the requester of every request.
            `${REQUESTED[kind]} requested by ${firing.requested_by!.handle}`
          )}
          {' · '}
          <Time at={firing.fired_at} format={clockFormat(firing.fired_at, today)} />
          {firing.outcome && <Outcome firing={firing} />}
        </li>
      ))}
    </ul>
  );
}

function Outcome({ firing }: { firing: Firing }) {
  return (
    <>
      {' · '}
      <span data-testid="timeline.wait.outcome" data-outcome={firing.outcome}>
        {OUTCOMES[firing.outcome!]}
      </span>
    </>
  );
}

const capitalised = (words: string) => words.charAt(0).toUpperCase() + words.slice(1);

/**
 * The request's button. From the press until the timeline reads the firing it recorded, it is
 * disabled, so that a second press cannot follow the first before the read says Pilot is checking.
 */
function RequestButton({ item, wait }: { item: TimelineItem; wait: Wait }) {
  const mutation = usePostItemsRequestByItemId();
  // The wait's firings when the request was sent.
  const [sentAt, setSentAt] = useState(0);
  const { label, open, refusal } = wait.request;
  const pending = mutation.isPending || (mutation.isSuccess && wait.firings.length <= sentAt);
  const fields = { item: item.id };
  const request = () => {
    setSentAt(wait.firings.length);
    trackFormSubmit('timeline.request', fields);
    mutation.mutate(
      { path: { item_id: item.id } },
      {
        onSuccess: () => trackFormSuccess('timeline.request', fields),
        onError: () => trackFormError('timeline.request', fields),
      },
    );
  };
  return (
    <button
      type="button"
      className="btn btn-ghost btn-sm btn-icon wait-request"
      onClick={request}
      disabled={!open || pending}
      // The API gives a reason wherever the wait takes no request.
      title={open ? label : capitalised(refusal!)}
      aria-label={label}
      data-testid="timeline.wait.request"
    >
      <HourglassSkip />
    </button>
  );
}
