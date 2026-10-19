/**
 * A modal dialog over the page (the mockup's `.overlay` and `.dialog`): a click beside it or Esc
 * closes it. A confirm dialog asks before an act, as the mockup's Finish does.
 */

import { useId, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import type { LucideIcon } from 'lucide-react';
import { useEscape } from '@/lib/keys';
import { cn } from '@/lib/utils';

interface DialogProps {
  title: ReactNode;
  onClose: () => void;
  /** Where it stands in Esc's order: the keys list lies over every other dialog. */
  layer?: 'dialog' | 'keys';
  className?: string;
  testId: string;
  children: ReactNode;
}

export function Dialog({ title, onClose, layer = 'dialog', className, testId, children }: DialogProps) {
  const titleId = useId();
  useEscape(layer, true, onClose);
  return createPortal(
    <div className="overlay" onClick={onClose} data-testid={`${testId}.backdrop`}>
      <div
        className={cn('dialog', className)}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
        data-testid={testId}
      >
        <h2 id={titleId} data-testid={`${testId}.title`}>
          {title}
        </h2>
        {children}
      </div>
    </div>,
    document.body,
  );
}

interface ConfirmDialogProps {
  title: ReactNode;
  /** What the act does, a line each. */
  lines: string[];
  note?: string;
  act: { label: string; icon: LucideIcon };
  /** The act is on its way: nothing closes the dialog but its answer. */
  pending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  testId: string;
}

/** What the act does, a note, then Cancel and the act; a click beside it or Esc cancels. */
export function ConfirmDialog({ title, lines, note, act, pending, onConfirm, onCancel, testId }: ConfirmDialogProps) {
  const cancel = () => {
    if (!pending) onCancel();
  };
  const Icon = act.icon;
  return (
    <Dialog title={title} onClose={cancel} className="confirm" testId={testId}>
      <ul className="dialog-list">
        {lines.map((line) => (
          <li key={line} data-testid={`${testId}.line`}>
            {line}
          </li>
        ))}
      </ul>
      {note && (
        <p className="dialog-note" data-testid={`${testId}.note`}>
          {note}
        </p>
      )}
      <div className="dialog-actions">
        <button type="button" className="btn" disabled={pending} onClick={cancel} data-testid={`${testId}.cancel`}>
          Cancel
        </button>
        <button type="button" className="btn btn-primary" disabled={pending} onClick={onConfirm} data-testid={`${testId}.confirm`}>
          <Icon className="icon" aria-hidden="true" />
          {act.label}
        </button>
      </div>
    </Dialog>
  );
}
