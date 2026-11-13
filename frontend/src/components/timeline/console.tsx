/**
 * A console that takes its control's place: the growing field (F115) with Send and a cross inside
 * its border, Ctrl+Enter sending (F110), its words kept in the browser until sent (F133). It lies
 * under everything else in Esc's order, and Esc in its field closes it too. While its field has the
 * focus, the window shrinking under it — a phone's keyboard opening, which the page's viewport
 * meets by resizing its content — brings it back into view, above the keyboard (F99). Other's
 * (F17.2, F19.4, F21.2) and a No's reason (F22.3) are consoles. In a one-ask item it has no Send of
 * its own: its words go with the block's Send, which Ctrl+Enter in its field is, and its cross
 * gives the choice back (F32.3).
 */

import { useEffect, useRef } from 'react';
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
  const held = !blankSends && text.trim() === '';
  return (
    <ConsoleBox
      text={text}
      onChange={change}
      label={label}
      placeholder={placeholder}
      send={{ name: send, held }}
      autoFocus
      className={className}
      testId={testId}
      onSend={() => {
        if (!held) onSend(text, sent);
      }}
      onClose={onClose}
    />
  );
}

interface ConsoleBoxProps {
  text: string;
  onChange: (text: string) => void;
  label: string;
  placeholder: string;
  /** Its own Send, by its name, disabled while held; none in a one-ask item. */
  send: { name: string; held: boolean } | null;
  autoFocus: boolean;
  className?: string;
  testId: string;
  /** Ctrl+Enter's, and its own Send's. */
  onSend: () => void;
  onClose: () => void;
}

/** The console's box over words held outside it: a one-ask item's, which its block's Send sends. */
export function ConsoleBox({ text, onChange, label, placeholder, send, autoFocus, className, testId, onSend, onClose }: ConsoleBoxProps) {
  useEscape('console', true, onClose);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const keep = () => {
      const element = root.current!;
      if (element.contains(document.activeElement)) element.scrollIntoView({ block: 'nearest' });
    };
    window.addEventListener('resize', keep);
    return () => window.removeEventListener('resize', keep);
  }, []);
  return (
    <div ref={root} className={cn('console', className)} data-testid={testId}>
      <TextField
        value={text}
        onChange={onChange}
        onSend={onSend}
        onEscape={onClose}
        label={label}
        placeholder={placeholder}
        autoFocus={autoFocus}
        testId={`${testId}.field`}
      />
      {send !== null && (
        <button
          type="button"
          className="console-btn send"
          onClick={onSend}
          disabled={send.held}
          title={`${send.name} (Ctrl+Enter)`}
          aria-label={send.name}
          data-testid={`${testId}.send`}
        >
          <Send className="icon" aria-hidden="true" />
        </button>
      )}
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
