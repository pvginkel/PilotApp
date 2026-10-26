/**
 * No chat yet: the timeline mockup's words (design/mockup/app.js, `chat-empty`). Shown only once
 * the chats are read, so it never flashes before them.
 */

export function ChatEmptyState() {
  return (
    <p className="mx-2 my-auto text-center text-[14px] text-muted-foreground" data-testid="chat.empty">
      Ask Pilot about this project: how a session is going, what an item means, a change to the plan. Discuss on an item quotes it here.
    </p>
  );
}
