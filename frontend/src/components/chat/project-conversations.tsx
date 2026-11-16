/**
 * The project's conversations where they stand (F150.12): the Conversations tab, the side panel's
 * and the phone's. A conversation is a session outside Pilot talking to Pilot about the project,
 * and the tab shows them read-only, in the order they opened: each under its head — the
 * environment whose session opened it, linked as an environment is (F93), the session's name where
 * it gave one, and "Open" or "Closed" — its transcript as a chat's, streamed, its caller's
 * messages on the right under the environment's name and Pilot's replies with their steps
 * (`ChatSection`). While Pilot answers in one, its head carries Stop, any person's (F44). A head
 * stays at the top of the view while its conversation scrolls under it, so that whose it is and
 * its Stop stay in reach. There is no composer: every message is the calling session's.
 *
 * It shows from the earliest conversation still open, or with none open the latest; "Load
 * previous" at the top loads the one before above what is in view and leaves the view where it is,
 * as the Chat tab's does. A conversation that opens while it shows comes in below. Sticky scroll
 * keeps a streaming reply in view while the reader is at the bottom (use-sticky-bottom.ts). Nothing
 * stands in it while the list's read is under way, and "The conversations did not load." while its
 * latest read failed.
 */

import { useMemo, useRef, useState } from 'react';
import { ChevronUp, Square } from 'lucide-react';
import { EnvironmentLink } from '@/components/shared/linked-text';
import { ScrollBar } from '@/components/shared/scroll-bar';
import { useProjectConversations, useStopConversation, type Conversation } from '@/hooks/use-conversations';
import { useKeptLine } from '@/hooks/use-kept-line';
import { useStickyBottom } from '@/hooks/use-sticky-bottom';
import { ChatSection } from './chat-section';
import type { ChatPeople } from './people';

interface ProjectConversationsProps {
  projectId: string;
  /** A view lies over it: it takes no focus. */
  covered: boolean;
}

export function ProjectConversations({ projectId, covered }: ProjectConversationsProps) {
  const read = useProjectConversations(projectId);
  const conversations = typeof read === 'string' ? null : read.conversations;
  const container = useRef<HTMLDivElement>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const { unstick, stuck } = useStickyBottom(container, wrapper, 'conversations');
  const { keepTop } = useKeptLine(container, wrapper, stuck);
  // The first conversation shown, once the list is read: the earliest still open, else the latest.
  const [first, setFirst] = useState<string | null>(null);
  if (first === null && conversations !== null && conversations.length > 0) {
    setFirst((conversations.find((each) => each.closed_at === null) ?? conversations.at(-1)!).id);
  }
  const from = conversations === null || first === null ? -1 : conversations.findIndex((each) => each.id === first);
  const shown = from < 0 ? [] : conversations!.slice(from);

  const loadMore = () => {
    keepTop();
    unstick();
    setFirst(conversations![from - 1]!.id);
  };

  return (
    <div className="project-conversations relative flex min-h-0 flex-1 flex-col" inert={covered} data-testid="panel.conversations">
      <div className="scroll-frame">
        {/* The browser's own scroll anchoring off: it would move the view a second time. */}
        <div ref={container} className="scroll-view relative overflow-y-auto [overflow-anchor:none]" data-testid="conversations.body">
          <div ref={wrapper} className="flex min-h-full flex-col gap-4 px-3.5 pb-4 text-base/[1.6]" data-testid="conversations">
            {read === 'failed' ? (
              <p className="mx-2 my-auto text-center text-base/[1.6] text-muted-foreground" data-testid="conversations.failed">
                The conversations did not load.
              </p>
            ) : (
              <>
                {from > 0 && (
                  <button
                    type="button"
                    onClick={loadMore}
                    className="mx-auto mt-3 inline-flex items-center gap-1.5 rounded-md border border-r-2 border-b-2 px-2.5 py-0.5 text-sm/[1.6] text-muted-foreground hover:bg-accent hover:text-foreground"
                    data-testid="conversations.before"
                  >
                    <ChevronUp className="size-3.5" aria-hidden />
                    Load previous
                  </button>
                )}
                {shown.map((conversation) => (
                  <ConversationSection key={conversation.id} projectId={projectId} conversation={conversation} />
                ))}
              </>
            )}
          </div>
        </div>
        <ScrollBar view={container} testId="conversations.scrollbar" />
      </div>
    </div>
  );
}

/** One conversation: its head, and its transcript under it. */
function ConversationSection({ projectId, conversation }: { projectId: string; conversation: Conversation }) {
  const { environment } = conversation;
  // Every message of a conversation is its caller's, whichever service user its call came as.
  const people = useMemo<ChatPeople>(() => ({ me: '', who: () => ({ name: environment.name, initials: null, slot: null }) }), [environment.name]);
  return (
    <section className="flex flex-col gap-4" aria-label={`Conversation with a session in ${environment.name}`} data-testid="conversation" data-conversation={conversation.id}>
      <ConversationHead projectId={projectId} conversation={conversation} />
      <ChatSection chat={conversation} what="Conversation" people={people} />
    </section>
  );
}

/** A conversation's head: who opened it, whether it is open, and Stop while Pilot answers in it. */
function ConversationHead({ projectId, conversation }: { projectId: string; conversation: Conversation }) {
  const stopping = useStopConversation(projectId, conversation.id);
  return (
    <header className="conversation-head" data-testid="conversation.head">
      <div className="flex min-w-0 flex-1 items-baseline gap-1.5">
        <span className="flex-none font-semibold">
          <EnvironmentLink environment={conversation.environment} testId="conversation.environment" />
        </span>
        {conversation.session !== null && (
          <span className="min-w-0 truncate text-muted-foreground" title={conversation.session} data-testid="conversation.session">
            · {conversation.session}
          </span>
        )}
      </div>
      <span className="flex-none text-xs text-muted-foreground" data-testid="conversation.state">
        {conversation.closed_at === null ? 'Open' : 'Closed'}
      </span>
      {conversation.answering && (
        <button
          type="button"
          className="btn btn-soft btn-icon flex-none"
          disabled={stopping.pending}
          onClick={() => void stopping.act()}
          title="Stop Pilot’s answer"
          aria-label="Stop"
          data-testid="conversation.stop"
        >
          <Square className="size-3.5 fill-current" aria-hidden="true" />
        </button>
      )}
    </header>
  );
}
