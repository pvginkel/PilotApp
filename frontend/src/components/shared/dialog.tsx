/**
 * A modal dialog over the page (the mockup's `.overlay` and `.dialog`), on Radix's dialog: a click
 * beside it or Esc closes it, and while it is open the focus stays in it. It takes the focus as it
 * opens and gives it back as it closes. A confirm dialog asks before an act, as the mockup's Finish
 * does.
 */

import { useRef, useState, type ReactNode, type RefObject } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import type { LucideIcon } from 'lucide-react';
import { useEscape } from '@/lib/keys';
import { cn } from '@/lib/utils';

interface DialogProps {
  title: ReactNode;
  onClose: () => void;
  /** Where it stands in Esc's order: the keys list lies over every other dialog. */
  layer?: 'dialog' | 'keys';
  /** What takes the focus as it opens; else the first thing in it that takes it, or the dialog itself. */
  initialFocus?: RefObject<HTMLElement | null>;
  /** What takes the focus back as it closes; else what had it as it opened, if that is still there. */
  returnFocus?: RefObject<HTMLElement | null>;
  className?: string;
  testId: string;
  children: ReactNode;
}

export function Dialog({ title, onClose, layer = 'dialog', initialFocus, returnFocus, className, testId, children }: DialogProps) {
  useEscape(layer, true, onClose);
  const [opener] = useState(() => document.activeElement);
  return (
    <DialogPrimitive.Root
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="overlay" data-testid={`${testId}.backdrop`}>
          <DialogPrimitive.Content
            className={cn('dialog', className)}
            aria-modal="true"
            // Esc is the shell's (lib/keys.ts), which closes the top-most open thing, one per press.
            onEscapeKeyDown={(event) => event.preventDefault()}
            onOpenAutoFocus={(event) => {
              if (!initialFocus?.current) return;
              event.preventDefault();
              initialFocus.current.focus();
            }}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              const target = returnFocus?.current ?? opener;
              if (target instanceof HTMLElement && target.isConnected) target.focus();
            }}
            data-testid={testId}
          >
            <DialogPrimitive.Title data-testid={`${testId}.title`}>{title}</DialogPrimitive.Title>
            {children}
          </DialogPrimitive.Content>
        </DialogPrimitive.Overlay>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
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
  /** What takes the focus back as it closes (Dialog's `returnFocus`). */
  returnFocus?: RefObject<HTMLElement | null>;
  testId: string;
}

/**
 * What the act does, a note, then Cancel and the act; a click beside it or Esc cancels. Cancel
 * takes the focus as it opens, so that Enter pressed again cancels rather than acts.
 */
export function ConfirmDialog({ title, lines, note, act, pending, onConfirm, onCancel, returnFocus, testId }: ConfirmDialogProps) {
  const cancelButton = useRef<HTMLButtonElement>(null);
  const cancel = () => {
    if (!pending) onCancel();
  };
  const Icon = act.icon;
  return (
    <Dialog title={title} onClose={cancel} initialFocus={cancelButton} returnFocus={returnFocus} className="confirm" testId={testId}>
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
        <button ref={cancelButton} type="button" className="btn" disabled={pending} onClick={cancel} data-testid={`${testId}.cancel`}>
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
