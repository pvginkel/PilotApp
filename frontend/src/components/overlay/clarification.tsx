/**
 * Pilot's questions to a registered document's writer and the writer's reply, in the overlay over
 * the document's text (F52.2; DB 257): a section per pre-ruling pass that asked, "Pilot asked the
 * writer · <stamp>", each question after its block's local id, and the reply once it came, each
 * question's part under it where the reply kept the headings asked for, else the reply whole under
 * the questions. Until the reply, and where none came, the questions stand alone.
 */

import { Avatar } from '@/components/shared/avatar';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Time } from '@/components/shared/time';
import type { ItemDocument } from '@/hooks/use-document';

type Clarification = ItemDocument['clarifications'][number];

export function Clarifications({ item }: { item: ItemDocument }) {
  // The API gives the passes in the order they first asked, each its own stamp.
  return item.clarifications.map((clarification) => <ClarificationSection key={clarification.asked_at} clarification={clarification} />);
}

function ClarificationSection({ clarification }: { clarification: Clarification }) {
  const { asked_at: askedAt, questions, reply, split } = clarification;
  return (
    <section className="clarification" data-testid="overlay.clarification">
      <h3 data-testid="overlay.clarification.head">
        <Avatar who="pilot" size="xs" />
        <span>
          Pilot asked the writer · <Time at={askedAt} format="stamp" testId="overlay.clarification.time" />
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
