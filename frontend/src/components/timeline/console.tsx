/**
 * A console that takes its control's place: the growing field (F115) with Send and a cross inside
 * its border, Ctrl+Enter sending (F110), its words kept in the browser until sent (F133). It lies
 * under everything else in Esc's order, and Esc in its field closes it too. Other's (F17.2, F19.4,
 * F21.2) and a No's reason (F22.3) are consoles.
 */

import { Send, X } from 'lucide-react';
import { TextField } from '@/components/shared/text-field';
import { useUnsentText } from '@/hooks/use-unsent-text';
import { useEscape } from '@/lib/keys';
import { cn } from '@/lib/utils';

interface ConsoleProps {
  /** Where its unsent words are kept in the browser. */
  field: string;
  /** The words it opens with while none are kept. */
  initial?: string;
  label: string;
  placeholder: string;
  /** Send's name: its label, and its tooltip before the keys. */
  send: string;
  /** It sends with nothing typed: a No's reason may stay empty. */
  blankSends?: boolean;
  className?: string;
  testId: string;
  onSend: (words: string, onSaved: () => void) => void;
  onClose: () => void;
}

export function Console({ field, initial = '', label, placeholder, send, blankSends = false, className, testId, onSend, onClose }: ConsoleProps) {
  const { text, change, sent } = useUnsentText(field, initial);
  useEscape('console', true, onClose);
  const held = !blankSends && text.trim() === '';
  const sendIt = () => {
    if (!held) onSend(text, sent);
  };
  return (
    <div className={cn('console', className)} data-testid={testId}>
      <TextField
        value={text}
        onChange={change}
        onSend={sendIt}
        onEscape={onClose}
        label={label}
        placeholder={placeholder}
        autoFocus
        testId={`${testId}.field`}
      />
      <button
        type="button"
        className="console-btn send"
        onClick={sendIt}
        disabled={held}
        title={`${send} (Ctrl+Enter)`}
        aria-label={send}
        data-testid={`${testId}.send`}
      >
        <Send className="icon" aria-hidden="true" />
      </button>
      <button
        type="button"
        className="console-btn"
        onClick={onClose}
        title="Cancel (Esc)"
        aria-label="Cancel"
        data-testid={`${testId}.cancel`}
      >
        <X className="icon" aria-hidden="true" />
      </button>
    </div>
  );
}
