/**
 * The Chat tab's composer (F44; the chat mockup's decision 7): the growing field (F115), to five
 * lines, Enter breaking the line and Ctrl+Enter (Cmd+Enter) sending (F110), and Send beside it,
 * disabled while the field is empty, the field waiting while the message is on its way. A message
 * with no chat open starts one, which the tab shows where it opens. While Pilot answers, Send's
 * place is Stop, in every member's composer whoever sent the message, ending the turn where it is;
 * the field does not wait, so the next message can be written meanwhile. The focus stays in the
 * field after Send and after Stop. Its words are kept in the browser until sent, keyed by the
 * project (F133). What Discuss quoted stands over the field as a chip, with its remove, kept in the
 * browser beside the words, and goes out as its tag before the words (F38.3, F39.3); Discuss puts
 * the focus in the field, once nothing lies over it. In an archived project it takes no message,
 * and says why (F128.5); the server refuses one all the same. It lies over the chat's foot with no
 * divider, the chat scrolling under its frosted glass (mockup M3;
 * `ChatColumn`, panel.css). In a draft it lies over the definition chat, in the timeline's column
 * (F46.1), and so does a new project's, whose box its first send wires (`new-project.tsx`).
 */

import { useEffect, useRef, type MouseEvent, type ReactNode, type RefObject } from 'react';
import { SendHorizontal, Square } from 'lucide-react';
import { TextField } from '@/components/shared/text-field';
import { useSendMessage, useStopChat } from '@/hooks/use-chats';
import { composerField, focusTaken, useDiscussed } from '@/hooks/use-discuss';
import { useArchived } from '@/hooks/use-projects';
import { useUnsentText } from '@/hooks/use-unsent-text';
import { quoteTag } from '@/lib/chat/quotes';
import { cn } from '@/lib/utils';
import type { ChatHome } from './chat-empty-state';
import { ComposerQuote } from './quote-chip';

const LINES = 5;

/** A press on a button leaves the focus in the field. */
const keepFocus = (event: MouseEvent) => event.preventDefault();

interface ComposerProps {
  projectId: string;
  /** Where the chat it sends to stands. */
  home: ChatHome;
  /** Whether Pilot answers in the project's chat. */
  answering: boolean;
  /** The server took a message of this browser's. */
  onSent: () => void;
  /** Discuss put the focus in the field. */
  onDiscussed: () => void;
  /** It lies under a tab or the overlay: it takes no focus. */
  covered: boolean;
}

export function Composer({ projectId, home, answering, onSent, onDiscussed, covered }: ComposerProps) {
  const { text, change } = useUnsentText(composerField(projectId));
  const { quote, focus, drop } = useDiscussed(projectId);
  const sending = useSendMessage(projectId);
  const stopping = useStopChat(projectId);
  const archived = useArchived(projectId);
  const field = useRef<HTMLTextAreaElement>(null);
  const words = text.trim();
  const sendable = !archived && !answering && !sending.pending && words !== '';

  useEffect(() => {
    if (!focus || covered) return;
    focusTaken(projectId);
    field.current!.focus();
    onDiscussed();
  }, [focus, covered, projectId, onDiscussed]);

  const send = () => {
    field.current!.focus();
    if (!sendable) return;
    const sent = quote;
    void sending.act(sent === null ? words : `${quoteTag(sent)} ${words}`).then((took) => {
      if (!took) return;
      change('');
      if (sent !== null) drop(sent);
      onSent();
    });
  };
  const leaveOut = () => {
    drop(quote!);
    field.current!.focus();
  };
  const stopIt = () => {
    field.current!.focus();
    void stopping.act();
  };

  return (
    <ComposerBox
      home={home}
      field={field}
      text={text}
      onChange={change}
      onSend={send}
      sendable={sendable}
      waiting={sending.pending}
      disabled={archived}
      stop={answering ? { pending: stopping.pending, onStop: stopIt } : null}
    >
      {archived && (
        <p className="mb-2 text-sm/[1.6] text-muted-foreground" data-testid="chat.composer.archived">
          The project is archived: bring it back to message Pilot.
        </p>
      )}
      {quote !== null && <ComposerQuote quote={quote} onRemove={leaveOut} />}
    </ComposerBox>
  );
}

interface ComposerBoxProps {
  home: ChatHome;
  field: RefObject<HTMLTextAreaElement | null>;
  text: string;
  onChange: (text: string) => void;
  onSend: () => void;
  /** Send takes the words now. */
  sendable: boolean;
  /** The message is on its way: the field waits. */
  waiting: boolean;
  /** The field takes no message. */
  disabled?: boolean;
  /** Stop in Send's place, while Pilot answers. */
  stop?: { pending: boolean; onStop: () => void } | null;
  /** What stands over the field. */
  children?: ReactNode;
}

/** The composer as it stands: the field and Send, or Stop in Send's place, what stands over the field above them. */
export function ComposerBox({ home, field, text, onChange, onSend, sendable, waiting, disabled = false, stop = null, children }: ComposerBoxProps) {
  return (
    <div className="composer" data-testid="chat.composer">
      {/* In the timeline's column as the transcript is, its glass the column's width. */}
      <div className={cn('composer-box', home === 'feed' ? 'mx-auto max-w-(--column) px-6 max-[900px]:px-3' : 'px-3.5')}>
        <div className="glass" aria-hidden="true" data-testid="chat.composer.glass">
          <i />
          <i />
          <i />
          <b />
        </div>
        {children}
        <div className="field-row">
          <TextField
            ref={field}
            value={text}
            onChange={onChange}
            onSend={onSend}
            label="Message Pilot"
            placeholder="Message Pilot"
            disabled={disabled}
            readOnly={waiting}
            lines={LINES}
            survivesReload
            testId="chat.composer.field"
          />
          {stop !== null ? (
            <button
              type="button"
              className="btn btn-soft btn-icon"
              disabled={stop.pending}
              onMouseDown={keepFocus}
              onClick={stop.onStop}
              title="Stop Pilot’s answer"
              aria-label="Stop"
              data-testid="chat.composer.stop"
            >
              <Square className="size-3.5 fill-current" aria-hidden="true" />
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-primary btn-icon"
              disabled={!sendable}
              onMouseDown={keepFocus}
              onClick={onSend}
              title="Send (Ctrl+Enter)"
              aria-label="Send"
              data-testid="chat.composer.send"
            >
              <SendHorizontal className="icon" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
