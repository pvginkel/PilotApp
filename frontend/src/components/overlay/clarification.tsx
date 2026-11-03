/**
 * Pilot's questions to a registered document's writer and the writer's reply, in the overlay over
 * the document's text (F52.2; DB 257): the box, a section per pre-ruling pass that asked, Pilot's
 * mark, "Pilot asked the writer", its stamp and the reply's, each question after its block's local
 * id, and the reply once it came, each question's part under it where the reply kept the headings
 * asked for, else the reply whole under the questions. While the clarification run is in flight,
 * each question of the last section says the reply is awaited; where none came, the questions stand
 * alone. The asked block's mark opens the document at the box (writer-asked.tsx), which the overlay
 * goes to, and which flashes (clarification-box.ts).
 */

import type { RefObject } from 'react';
import { Avatar } from '@/components/shared/avatar';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Time } from '@/components/shared/time';
import type { ItemDocument } from '@/hooks/use-document';
import { cn } from '@/lib/utils';

type Clarification = ItemDocument['clarifications'][number];

interface ClarificationsProps {
  item: ItemDocument;
  /** The box's element, which the overlay goes to (clarification-box.ts). */
  boxRef: RefObject<HTMLDivElement | null>;
  /** Gone to: it flashes once. */
  flashing: boolean;
  onFlashed: () => void;
}

export function Clarifications({ item, boxRef, flashing, onFlashed }: ClarificationsProps) {
  if (item.clarifications.length === 0) return null;
  // Only the latest pass's clarification run can be in flight.
  const asking = item.pilots_work?.doing === 'asking_writer';
  const last = item.clarifications.length - 1;
  return (
    <div
      ref={boxRef}
      className={cn('clarifications', flashing && 'flash')}
      onAnimationEnd={onFlashed}
      data-testid="overlay.clarification-box"
    >
      {/* The API gives the passes in the order they first asked, each its own stamp. */}
      {item.clarifications.map((clarification, index) => (
        <ClarificationSection
          key={clarification.asked_at}
          clarification={clarification}
          awaited={asking && index === last && clarification.reply === null}
        />
      ))}
    </div>
  );
}

function ClarificationSection({ clarification, awaited }: { clarification: Clarification; awaited: boolean }) {
  const { asked_at: askedAt, replied_at: repliedAt, questions, reply, split } = clarification;
  return (
    <section className="clarification" data-testid="overlay.clarification">
      <h3 data-testid="overlay.clarification.head">
        <Avatar who="pilot" size="xs" />
        <b>Pilot asked the writer</b>{' '}
        <span className="when">
          · <Time at={askedAt} format="stamp" testId="overlay.clarification.time" />
          {repliedAt !== null && (
            <>
              {' '}
              · replied <Time at={repliedAt} format="stamp" testId="overlay.clarification.replied" />
            </>
          )}
        </span>
      </h3>
      <ul className="clarification-questions">
        {questions.map((question) => (
          <li key={question.block} data-testid="overlay.clarification.question" data-block={question.block}>
            <p className="asked">
              <span className="mono block-id" data-testid="overlay.clarification.block">
                {question.block}
              </span>
              <span data-testid="overlay.clarification.text">
                <LinkedText text={question.question} />
              </span>
            </p>
            {split && question.reply !== null && <Reply text={question.reply} />}
            {awaited && (
              <p className="reply awaited" data-testid="overlay.clarification.awaited">
                Awaiting the writer’s reply
              </p>
            )}
          </li>
        ))}
      </ul>
      {!split && reply !== null && <Reply text={reply} />}
    </section>
  );
}

/** The writer's words, as they wrote them. */
function Reply({ text }: { text: string }) {
  return (
    <div className="reply" data-testid="overlay.clarification.reply">
      <Markdown text={text} />
    </div>
  );
}
