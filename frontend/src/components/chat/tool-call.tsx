/**
 * A tool call's line (decision 3): its icon, what it did, a spinner while it runs; it opens to
 * its input and its result. A call that changed the record — a `pilot-store` call, or a worker's
 * `register_document` or `attach_file` — shows as its effect where it ran, in its step's place
 * (decision 5, ruled 2026-10-18).
 */

import { useState } from 'react';
import { Bot, Check, CircleAlert, Database, FileText, Globe, ListTodo, Pencil, Search, Server, SquareTerminal, Wrench } from 'lucide-react';
import { summarizeTool, type ToolKind } from '@/lib/chat/tools';
import type { Effect } from '@/lib/chat/records';
import type { ToolCallView } from '@/lib/chat/view';
import { StepLine } from './step-line';
import { useChatActions } from './actions';

const ICONS: Record<ToolKind, typeof FileText> = {
  read: FileText,
  command: SquareTerminal,
  search: Search,
  edit: Pencil,
  agent: Bot,
  web: Globe,
  store: Database,
  fleet: Server,
  todo: ListTodo,
  other: Wrench,
};

const ToolIcon = ({ kind }: { kind: ToolKind }) => {
  const Icon = ICONS[kind];
  return <Icon className="size-3.5" aria-hidden />;
};

/** The longest stretch of a result shown before "Show all". */
const RESULT_PREVIEW = 2400;

function ToolDetail({ call }: { call: ToolCallView }) {
  const [all, setAll] = useState(false);
  const input =
    call.name === 'Bash' && typeof call.input.command === 'string' ? `$ ${call.input.command}` : JSON.stringify(call.input, null, 2);
  const result = call.result?.text ?? '';
  const cut = !all && result.length > RESULT_PREVIEW;
  return (
    <div className="mt-0.5 mb-1.5 ml-6 flex flex-col gap-1 text-[12px]">
      <pre className="max-h-40 overflow-auto rounded-md bg-muted px-2.5 py-1.5 leading-[1.45] whitespace-pre-wrap break-all">{input}</pre>
      {call.result && (
        <pre
          className={`max-h-72 overflow-auto rounded-md border px-2.5 py-1.5 leading-[1.45] whitespace-pre-wrap break-all ${call.result.isError ? 'text-destructive-text' : 'text-muted-foreground'}`}
        >
          {cut ? `${result.slice(0, RESULT_PREVIEW)}…` : result || '(no output)'}
        </pre>
      )}
      {cut && (
        <button type="button" onClick={() => setAll(true)} className="self-start text-link hover:underline">
          Show all ({Math.round(result.length / 1024)} KB)
        </button>
      )}
    </div>
  );
}

/** An effect's line, "<verb> · <label>", going to its block, else its item, where it names one. */
export function EffectLine({ effect }: { effect: Effect }) {
  const { openQuote } = useChatActions();
  const target = effect.blockId
    ? { kind: 'block' as const, id: effect.blockId, label: effect.label }
    : effect.itemId
      ? { kind: 'item' as const, id: effect.itemId, label: effect.label }
      : null;
  return (
    <StepLine icon={<Check className="size-3.5" aria-hidden />} tone="success" onToggle={target ? () => openQuote(target) : undefined} link>
      {effect.verb} · {effect.label}
    </StepLine>
  );
}

export function ToolCallLine({ call }: { call: ToolCallView }) {
  const [open, setOpen] = useState(false);
  if (call.effects.length) {
    return (
      <>
        {call.effects.map((e, i) => (
          <EffectLine key={i} effect={e} />
        ))}
      </>
    );
  }
  const sum = summarizeTool(call.name, call.input);
  const running = !call.result && !call.stopped;
  const failed = call.result?.isError;
  return (
    <>
      <StepLine
        icon={failed ? <CircleAlert className="size-3.5" aria-hidden /> : <ToolIcon kind={sum.kind} />}
        tone={failed ? 'error' : 'muted'}
        running={running}
        open={open}
        onToggle={() => setOpen(!open)}
      >
        {running ? sum.verbRunning : sum.verb}
        {sum.target && <span className="text-foreground/80"> {sum.target}</span>}
        {failed && ' — failed'}
      </StepLine>
      {open && <ToolDetail call={call} />}
    </>
  );
}
