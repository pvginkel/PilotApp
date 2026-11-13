/**
 * A one-ask item's Send (F32.3): the one control that sends what its block's presses chose, at the
 * right end of the block's last row, disabled until something is chosen.
 */

import { Send } from 'lucide-react';

interface SendChoiceProps {
  /** Something is chosen, and the block takes an answer now. */
  ready: boolean;
  onSend: () => void;
  testId?: string;
}

export function SendChoice({ ready, onSend, testId = 'timeline.block.send' }: SendChoiceProps) {
  return (
    <button type="button" className="btn btn-primary send-choice" onClick={onSend} disabled={!ready} title="Send (Ctrl+Enter)" data-testid={testId}>
      <Send className="icon" aria-hidden="true" />
      Send
    </button>
  );
}
