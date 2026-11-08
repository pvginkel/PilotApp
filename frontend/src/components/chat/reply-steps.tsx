/**
 * A reply's steps in order: text as Markdown, and between the texts what Pilot did — tool calls,
 * a sub-agent under its call (decisions 3 to 5). Thinking is left out once it has ended (ruling
 * 2); the cue shows it while it runs. A run of consecutive calls is one line that opens to them,
 * its spinner and its running call's words while one runs (ruling 3). A sub-agent is a card,
 * collapsed until opened, its progress under it while it runs (ruling 4). A call that changed
 * something is its effects, in its own place, never inside a run (ruling 5); an effect whose call
 * no record shows stands in its record's place.
 */

import { useState } from 'react';
import { Bot, Check, CircleAlert, Layers, Square } from 'lucide-react';
import { summarizeRun, summarizeTool, type ToolKind, type Words } from '@/lib/chat/tools';
import { shownSteps, type AgentView, type Step, type ToolCallView } from '@/lib/chat/view';
import { Markdown } from '@/components/shared/markdown';
import { useHeld } from '@/hooks/use-held';
import { cn } from '@/lib/utils';
import { StepLine } from './step-line';
import { StepWords } from './step-words';
import { EffectLine, ToolCallLine } from './tool-call';

const fadeIn = 'animate-fade-in opacity-0';

type Block = { kind: 'step'; step: Step } | { kind: 'run'; steps: Step[] };

const isAgent = (s: Step) => s.kind === 'tool' && !!s.call.agent;
const groupable = (s: Step) => s.kind === 'tool' && !s.call.agent && !s.call.effects.length;

function blocksOf(steps: Step[], grouped: boolean): Block[] {
  const visible = shownSteps(steps);
  if (!grouped) return visible.map((step) => ({ kind: 'step', step }));
  const blocks: Block[] = [];
  let run: Step[] = [];
  const flush = () => {
    if (run.length === 1) blocks.push({ kind: 'step', step: run[0]! });
    else if (run.length) blocks.push({ kind: 'run', steps: run });
    run = [];
  };
  for (const step of visible) {
    if (groupable(step)) run.push(step);
    else {
      flush();
      blocks.push({ kind: 'step', step });
    }
  }
  flush();
  return blocks;
}

function runSummary(steps: Step[]): string {
  const kinds: ToolKind[] = [];
  for (const s of steps) if (s.kind === 'tool') kinds.push(summarizeTool(s.call.name, s.call.input).kind);
  return summarizeRun(kinds);
}

function runningCall(steps: Step[]): ToolCallView | null {
  for (let i = steps.length - 1; i >= 0; i--) {
    const s = steps[i]!;
    if (s.kind === 'tool' && !s.call.result && !s.call.stopped) return s.call;
  }
  return null;
}

/**
 * A run's line: its running call's words while one runs, else what the run did, and its count of
 * steps, each text held for a moment; the spinner, and the count of failed calls, the one red
 * in the line, change at once.
 */
function RunLine({ steps, liveFrom }: { steps: Step[]; liveFrom: number | null }) {
  const [open, setOpen] = useState(false);
  const running = runningCall(steps);
  const failed = steps.filter((s) => s.kind === 'tool' && s.call.result?.isError).length;
  const words: Words[] = running ? summarizeTool(running.name, running.input).running : [{ text: runSummary(steps) }];
  const said = useHeld({ words, count: steps.length }, `${steps.length} ${JSON.stringify(words)}`);
  return (
    <div data-testid="chat.run">
      <StepLine icon={<Layers className="size-3.5" aria-hidden />} running={!!running} open={open} onToggle={() => setOpen(!open)}>
        <StepWords words={said.words} />
        <span className="opacity-70"> · {said.count} steps</span>
        {failed > 0 && (
          <>
            <span className="opacity-70"> · </span>
            <span className="text-destructive-text" data-testid="chat.run.failed">
              {failed} failed
            </span>
          </>
        )}
      </StepLine>
      {open && (
        <div className="mb-1">
          <ReplySteps steps={steps} liveFrom={liveFrom} flat />
        </div>
      )}
    </div>
  );
}

function AgentCard({ call, agent, liveFrom }: { call: ToolCallView; agent: AgentView; liveFrom: number | null }) {
  const [open, setOpen] = useState(false);
  const running = agent.status === 'running';
  const status =
    agent.status === 'running' ? null : agent.status === 'completed' ? (
      <Check className="size-3.5 text-success-text" aria-label="Done" />
    ) : agent.status === 'failed' ? (
      <CircleAlert className="size-3.5 text-destructive-text" aria-label="Failed" />
    ) : (
      <Square className="size-3 text-muted-foreground" aria-label="Stopped" />
    );
  return (
    <div className="my-1 rounded-md border bg-muted/40" data-tool-use={call.id} data-testid="chat.agent">
      <StepLine
        icon={<Bot className="size-3.5" aria-hidden />}
        running={running}
        open={open}
        onToggle={() => setOpen(!open)}
        className="px-2.5 py-1"
      >
        <StepWords words={summarizeTool(call.name, call.input).done} />
        {status && <span className="ml-1.5 inline-flex align-[-2px]">{status}</span>}
      </StepLine>
      {!open && running && agent.progress && (
        <div className="truncate px-2.5 pb-1 pl-8 font-mono text-xs/[1.6] text-muted-foreground">{agent.progress}</div>
      )}
      {open && (
        <div className="border-t px-2.5 py-1.5">
          {agent.steps.length ? (
            <ReplySteps steps={agent.steps} liveFrom={liveFrom} nested />
          ) : (
            <div className="text-sm/[1.6] text-muted-foreground">Starting…</div>
          )}
          {agent.summary && (
            <div className="mt-1.5 border-t pt-1.5 text-sm/[1.6] text-muted-foreground">
              <span className="font-medium">Reported:</span> {agent.summary}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ReplySteps({
  steps,
  liveFrom,
  streamed,
  nested = false,
  flat = false,
}: {
  steps: Step[];
  liveFrom: number | null;
  /** Text records that replace the phantom: shown already, they do not fade in again. */
  streamed?: ReadonlySet<number>;
  /** A sub-agent's steps: smaller text. */
  nested?: boolean;
  /** Inside an opened run: no grouping again. */
  flat?: boolean;
}) {
  const blocks = blocksOf(steps, !flat);
  const fresh = (seq: number) => liveFrom != null && seq >= liveFrom;

  return (
    <>
      {blocks.map((b) => {
        if (b.kind === 'run') {
          const seq = b.steps[0]!.seq;
          return (
            // Keyed as its first step is, so a step that becomes a run keeps its place.
            <div key={`${b.steps[0]!.kind}:${seq}`} className={cn(fresh(seq) && fadeIn)}>
              <RunLine steps={b.steps} liveFrom={liveFrom} />
            </div>
          );
        }
        const s = b.step;
        if (s.kind === 'thinking') return null;
        const key = `${s.kind}:${s.seq}`;
        let body: React.ReactNode;
        switch (s.kind) {
          case 'text':
            body = <Markdown text={s.text} className={nested ? 'text-sm/[1.6]' : undefined} />;
            break;
          case 'tool':
            body = isAgent(s) ? <AgentCard call={s.call} agent={s.call.agent!} liveFrom={liveFrom} /> : <ToolCallLine call={s.call} />;
            break;
          case 'error':
            body = (
              <StepLine icon={<CircleAlert className="size-3.5" aria-hidden />} tone="error" className="whitespace-normal">
                {s.text}
              </StepLine>
            );
            break;
          case 'notice':
            body = (
              <StepLine icon={<CircleAlert className="size-3.5" aria-hidden />} tone="error" className="whitespace-normal [&>span]:whitespace-normal">
                {s.text}
              </StepLine>
            );
            break;
          case 'effect':
            body = <EffectLine effect={s.effect} />;
            break;
        }
        return (
          <div
            key={key}
            className={cn(s.kind === 'text' && 'my-0.5', fresh(s.seq) && !streamed?.has(s.seq) && fadeIn)}
            data-testid={`chat.${s.kind}`}
          >
            {body}
          </div>
        );
      })}
    </>
  );
}
