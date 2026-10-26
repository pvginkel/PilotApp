/**
 * The text field every answer and message is typed into (F115): one line at rest, growing with
 * what is typed to eight lines, or the chat's five, then scrolling. Enter breaks the line and
 * Ctrl+Enter (Cmd+Enter on a Mac) sends, where the field has one Send (F110). While it has the
 * focus, its parent, the row that holds what sends it, is kept in view.
 */

import { useImperativeHandle, useLayoutEffect, useRef, type KeyboardEvent, type Ref } from 'react';
import { cn } from '@/lib/utils';

const LINES = 8;

interface TextFieldProps {
  value: string;
  onChange: (value: string) => void;
  /** Ctrl+Enter's; none where several buttons send the field, as an action's options do. */
  onSend?: () => void;
  /** Esc in the field, where it closes what holds it: Other's console. */
  onEscape?: () => void;
  label: string;
  placeholder: string;
  disabled?: boolean;
  /** It takes no typing for now and keeps the focus: the chat's message on its way. */
  readOnly?: boolean;
  autoFocus?: boolean;
  /** The lines it grows to before it scrolls. */
  lines?: number;
  className?: string;
  testId: string;
  ref?: Ref<HTMLTextAreaElement>;
}

export function TextField({
  value,
  onChange,
  onSend,
  onEscape,
  label,
  placeholder,
  disabled,
  readOnly,
  autoFocus,
  lines = LINES,
  className,
  testId,
  ref,
}: TextFieldProps) {
  const field = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => field.current!, []);

  useLayoutEffect(() => {
    const element = field.current!;
    const style = getComputedStyle(element);
    const frame = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
    const most = lines * parseFloat(style.lineHeight) + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + frame;
    element.style.height = 'auto';
    const needed = element.scrollHeight + frame;
    element.style.height = `${Math.min(needed, most)}px`;
    element.style.overflowY = needed > most ? 'auto' : 'hidden';
    if (document.activeElement === element) element.parentElement!.scrollIntoView({ block: 'nearest' });
  }, [value, lines]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing && onSend) {
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
      readOnly={readOnly}
      autoFocus={autoFocus}
      data-testid={testId}
    />
  );
}
