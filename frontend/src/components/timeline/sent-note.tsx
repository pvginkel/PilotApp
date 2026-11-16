/**
 * A one-ask decision's or question's note, which its Send carries with the answer (F17.4, F32.3):
 * Pilot's note taken puts the note it suggests there (F168.2; take-note.ts). The field stands once
 * it holds words, the person's to change before the Send, and, emptied, until the block is drawn
 * again. An action's paste-back and a No's reason are their own notes already.
 */

import { useState } from 'react';
import { TextField } from '@/components/shared/text-field';
import type { useUnsentText } from '@/hooks/use-unsent-text';

interface SentNoteProps {
  /** The note's unsent words, kept under `<block key>/note`. */
  note: ReturnType<typeof useUnsentText>;
  disabled: boolean;
  /** The block's Send, Ctrl+Enter's in the field. */
  onSend: () => void;
}

export function SentNote({ note, disabled, onSend }: SentNoteProps) {
  const [typed, setTyped] = useState(false);
  if (note.text === '' && !typed) return null;
  const change = (next: string) => {
    setTyped(true);
    note.change(next);
  };
  return (
    // The field's parent, kept in view while it grows.
    <div className="sent-note">
      <TextField
        value={note.text}
        onChange={change}
        onSend={onSend}
        label="Your note with the answer"
        placeholder="Your note with the answer, if any"
        disabled={disabled}
        survivesReload
        testId="timeline.block.note-field"
      />
    </div>
  );
}
