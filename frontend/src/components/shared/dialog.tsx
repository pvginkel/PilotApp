/**
 * A modal dialog over the page (the mockup's `.overlay` and `.dialog`): a click beside it or Esc
 * closes it.
 */

import { useId, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useEscape } from '@/lib/keys';

interface DialogProps {
  title: string;
  onClose: () => void;
  /** Where it stands in Esc's order: the keys list lies over every other dialog. */
  layer?: 'dialog' | 'keys';
  testId: string;
  children: ReactNode;
}

export function Dialog({ title, onClose, layer = 'dialog', testId, children }: DialogProps) {
  const titleId = useId();
  useEscape(layer, true, onClose);
  return createPortal(
    <div className="overlay" onClick={onClose} data-testid={`${testId}.backdrop`}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
        data-testid={testId}
      >
        <h2 id={titleId}>{title}</h2>
        {children}
      </div>
    </div>,
    document.body,
  );
}
