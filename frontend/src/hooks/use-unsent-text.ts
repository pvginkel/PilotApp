/**
 * A field's text, kept in the browser as it is typed until it is sent (F133): a field opened again,
 * after a reload or in another tab, starts from what was left in it. Words that leave a field on
 * their send stay kept until the server takes them, before what is typed in the field since, so
 * that a reload meanwhile finds them in it (D171); refused, they stand in the field again, what
 * was typed since under them.
 */

import { useEffect, useState } from 'react';
import { keepUnsent, unsentText } from '@/lib/browser-state';

/** The words on their way out of a field, by its key, and what was typed in it since. */
const leaving = new Map<string, { words: string; since: string }>();
/** The fields showing, by their key: each takes a text put in it from outside. */
const showing = new Map<string, Set<(text: string) => void>>();

const together = (words: string, since: string) => (since === '' ? words : `${words}\n${since}`);

/** `field` keys the text in the browser; `initial` stands while none is kept. */
export function useUnsentText(field: string, initial = '') {
  const [text, setText] = useState(() => leaving.get(field)?.since ?? unsentText(field) ?? initial);

  useEffect(() => {
    const fields = showing.get(field) ?? new Set();
    showing.set(field, fields.add(setText));
    return () => {
      fields.delete(setText);
    };
  }, [field]);

  const change = (next: string) => {
    setText(next);
    const left = leaving.get(field);
    if (left === undefined) {
      keepUnsent(field, next);
    } else {
      left.since = next;
      keepUnsent(field, together(left.words, next));
    }
  };

  /**
   * The field's words leave it on their send, one send at a time: `taken()` once the server has
   * them, `refused()` where it refuses them.
   */
  const leave = () => {
    const left = { words: text, since: '' };
    leaving.set(field, left);
    setText('');
    return {
      taken: () => {
        leaving.delete(field);
        keepUnsent(field, left.since);
      },
      refused: () => {
        leaving.delete(field);
        showing.get(field)?.forEach((show) => show(together(left.words, left.since)));
      },
    };
  };

  return { text, change, leave, sent: () => keepUnsent(field, '') };
}
