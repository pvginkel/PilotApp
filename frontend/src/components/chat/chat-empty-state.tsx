/**
 * No chat yet (F113): in the side panel's Chat tab the timeline mockup's words (design/mockup/app.js,
 * `chat-empty`); in a draft's definition chat, in the timeline's place, "Tell Pilot what to manage"
 * and what to tell it (the mockup's `renderChat`, F46.1). Shown only once the chats are read, so it
 * never flashes before them.
 */

import { MessagesSquare } from 'lucide-react';

/** Where the project's chat stands: the side panel, or, for a draft, the timeline's place (the feed). */
export type ChatHome = 'panel' | 'feed';

export function ChatEmptyState({ home }: { home: ChatHome }) {
  if (home === 'feed') {
    return (
      <div className="empty-state m-auto" data-testid="chat.empty">
        <MessagesSquare className="icon" aria-hidden="true" />
        <h2>Tell Pilot what to manage</h2>
        <p>
          A card, a handover, or the idea in your own words. Pilot drafts the project beside the chat as you talk, and nothing is
          created until you press <b>Create project</b>.
        </p>
      </div>
    );
  }
  return (
    <p className="mx-2 my-auto text-center text-base/[1.6] text-muted-foreground" data-testid="chat.empty">
      Ask Pilot about this project: how a session is going, what an item means, a change to the plan. Discuss on an item quotes it here.
    </p>
  );
}
