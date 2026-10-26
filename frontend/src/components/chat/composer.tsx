/**
 * The Chat tab's composer (F44; the chat mockup's decision 7): the growing field (F115), to five
 * lines, Enter breaking the line and Ctrl+Enter (Cmd+Enter) sending (F110), and Send beside it,
 * disabled while the field is empty, the field waiting while the message is on its way. A message
 * with no chat open starts one, which the tab shows where it opens. While Pilot answers, Send's
 * place is Stop, in every member's composer whoever sent the message, ending the turn where it is;
 * the field does not wait, so the next message can be written meanwhile. The focus stays in the
 * field after Send and after Stop. Its words are kept in the browser until sent, keyed by the
 * project (F133). In an archived project it takes no message, and says why (F128.5); the server
 * refuses one all the same.
 */

import { useRef, type MouseEvent } from 'react';
import { SendHorizontal, Square } from 'lucide-react';
import { TextField } from '@/components/shared/text-field';
import { useSendMessage, useStopChat } from '@/hooks/use-chats';
import { useArchived } from '@/hooks/use-projects';
import { useUnsentText } from '@/hooks/use-unsent-text';

const LINES = 5;

/** A press on a button leaves the focus in the field. */
const keepFocus = (event: MouseEvent) => event.preventDefault();

interface ComposerProps {
  projectId: string;
  /** Whether Pilot answers in the project's chat. */
  answering: boolean;
  /** The server took a message of this browser's. */
  onSent: () => void;
}

export function Composer({ projectId, answering, onSent }: ComposerProps) {
  const { text, change } = useUnsentText(`chat/${projectId}`);
  const sending = useSendMessage(projectId);
  const stopping = useStopChat(projectId);
  const archived = useArchived(projectId);
  const field = useRef<HTMLTextAreaElement>(null);
  const words = text.trim();
  const sendable = !archived && !answering && !sending.pending && words !== '';

  const send = () => {
    field.current!.focus();
    if (!sendable) return;
    void sending.act(words).then((took) => {
      if (!took) return;
      change('');
      onSent();
    });
  };
  const stopIt = () => {
    field.current!.focus();
    void stopping.act();
  };

  return (
    <div className="flex-none border-t px-3.5 pt-2.5 pb-3.5" data-testid="chat.composer">
      {archived && (
        <p className="mb-2 text-[13px] text-muted-foreground" data-testid="chat.composer.archived">
          The project is archived: bring it back to message Pilot.
        </p>
      )}
      <div className="field-row">
        <TextField
          ref={field}
          value={text}
          onChange={change}
          onSend={send}
          label="Message Pilot"
          placeholder="Message Pilot"
          disabled={archived}
          readOnly={sending.pending}
          lines={LINES}
          testId="chat.composer.field"
        />
        {answering ? (
          <button
            type="button"
            className="btn btn-soft btn-icon"
            disabled={stopping.pending}
            onMouseDown={keepFocus}
            onClick={stopIt}
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
            onClick={send}
            title="Send (Ctrl+Enter)"
            aria-label="Send"
            data-testid="chat.composer.send"
          >
            <SendHorizontal className="icon" aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  );
}
