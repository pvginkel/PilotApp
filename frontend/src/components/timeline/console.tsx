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

import { useEffect, useRef, type Ref } from 'react';
import { Send, X } from 'lucide-react';
import { BusyIcon } from '@/components/shared/busy-icon';
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
  /** What it sent is being saved: Send is disabled, its icon the spinner once it has waited (F148). */
  busy?: boolean;
  className?: string;
  testId: string;
  onSend: (words: string, onSaved: () => void) => void;
  onClose: () => void;
}

export function Console({ field, initial = '', label, placeholder, send, blankSends = false, busy = false, className, testId, onSend, onClose }: ConsoleProps) {
  const { text, change, sent } = useUnsentText(field, initial);
  const held = busy || (!blankSends && text.trim() === '');
  return (
    <ConsoleBox
      text={text}
      onChange={change}
      label={label}
      placeholder={placeholder}
      send={{ name: send, held, busy }}
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
  /** Its own Send, by its name, disabled while held, busy while what it sent saves; none in a one-ask item. */
  send: { name: string; held: boolean; busy: boolean } | null;
  autoFocus: boolean;
  /** Its field's, through which Pilot's note taken gives it the focus (taken-focus.ts). */
  fieldRef?: Ref<HTMLTextAreaElement>;
  className?: string;
  testId: string;
  /** Ctrl+Enter's, and its own Send's. */
  onSend: () => void;
  onClose: () => void;
}

/** The console's box over words held outside it: a one-ask item's, which its block's Send sends. */
export function ConsoleBox({ text, onChange, label, placeholder, send, autoFocus, fieldRef, className, testId, onSend, onClose }: ConsoleBoxProps) {
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
        ref={fieldRef}
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
          <BusyIcon busy={send.busy}>
            <Send className="icon" aria-hidden="true" />
          </BusyIcon>
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
