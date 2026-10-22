/**
 * The text field every answer is typed into (F115): one line at rest, growing with what is typed
 * to eight lines, then scrolling. Enter breaks the line and Ctrl+Enter (Cmd+Enter on a Mac) sends
 * (F110). While it has the focus, its parent, the row that holds its Send, is kept in view.
 */

import { useLayoutEffect, useRef, type KeyboardEvent } from 'react';
import { cn } from '@/lib/utils';

const LINES = 8;

interface TextFieldProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  /** Esc in the field, where it closes what holds it: Other's console. */
  onEscape?: () => void;
  label: string;
  placeholder: string;
  disabled?: boolean;
  autoFocus?: boolean;
  className?: string;
  testId: string;
}

export function TextField({ value, onChange, onSend, onEscape, label, placeholder, disabled, autoFocus, className, testId }: TextFieldProps) {
  const field = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const element = field.current!;
    const style = getComputedStyle(element);
    const frame = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
    const most = LINES * parseFloat(style.lineHeight) + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + frame;
    element.style.height = 'auto';
    const needed = element.scrollHeight + frame;
    element.style.height = `${Math.min(needed, most)}px`;
    element.style.overflowY = needed > most ? 'auto' : 'hidden';
    if (document.activeElement === element) element.parentElement!.scrollIntoView({ block: 'nearest' });
  }, [value]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
      event.preventDefault();
      onSend();
    } else if (event.key === 'Escape' && onEscape) {
      event.preventDefault();
      onEscape();
    }
  };

  return (
    <textarea
      ref={field}
      className={cn('field', className)}
      rows={1}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={onKeyDown}
      aria-label={label}
      placeholder={placeholder}
      disabled={disabled}
      autoFocus={autoFocus}
      data-testid={testId}
    />
  );
}
