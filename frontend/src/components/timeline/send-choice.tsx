/**
 * A one-ask item's Send (F32.3): the one control that sends what its block's presses chose, at the
 * right end of the block's last row, disabled until something is chosen; while what it sent saves,
 * disabled, its icon the spinner once the write has waited (F148). Where the item's close starts
 * Pilot's work, its icon is the job's mark under the mouse (F59.3).
 */

import { Send } from 'lucide-react';
import { BusyIcon } from '@/components/shared/busy-icon';

interface SendChoiceProps {
  /** Something is chosen, and the block takes an answer now. */
  ready: boolean;
  /** What it sent is being saved. */
  busy: boolean;
  /** Its send starts Pilot's work, as the server reads the item's close. */
  starts: boolean;
  onSend: () => void;
  testId?: string;
}

export function SendChoice({ ready, busy, starts, onSend, testId = 'timeline.block.send' }: SendChoiceProps) {
  return (
    <button type="button" className="btn btn-primary send-choice" onClick={onSend} disabled={!ready || busy} title="Send (Ctrl+Enter)" data-testid={testId}>
      <BusyIcon busy={busy} starts={starts}>
        <Send className="icon" aria-hidden="true" />
      </BusyIcon>
      Send
    </button>
  );
}
