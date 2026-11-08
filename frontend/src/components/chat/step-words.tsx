/** A step line's words, in the line's one colour: code in the mono face (C4). */

import { Fragment } from 'react';
import type { Words } from '@/lib/chat/tools';

export function StepWords({ words }: { words: Words[] }) {
  return (
    <>
      {words.map((w, i) => (
        <Fragment key={i}>{w.code ? <span className="mono">{w.text}</span> : w.text}</Fragment>
      ))}
    </>
  );
}
