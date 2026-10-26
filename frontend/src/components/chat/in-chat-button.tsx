/**
 * *In the chat* (F42.3): on a block answered in the chat, in its head and its done line, a button
 * with the chat icon and its label that goes to the message that gave the answer (use-in-chat.ts).
 * A narrow block head keeps its icon alone (F98.3, timeline.css).
 */

import { MessageSquare } from 'lucide-react';
import { useInChat, type ChatPlace } from '@/hooks/use-in-chat';

export function InChatButton({ place, testId }: { place: ChatPlace; testId: string }) {
  const inChat = useInChat();
  return (
    <button
      type="button"
      className="in-chat"
      onClick={() => inChat(place)}
      title="Go to the answer in the chat"
      aria-label="Go to the answer in the chat"
      data-testid={testId}
      data-place={`${place.chat} ${place.seq}`}
    >
      <MessageSquare className="icon" aria-hidden="true" />
      <span className="in-chat-label">In the chat</span>
    </button>
  );
}
