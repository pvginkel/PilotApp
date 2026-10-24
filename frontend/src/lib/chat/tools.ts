/**
 * A tool call's summary line (decision 3): what the call did, in a few words, from its input.
 * The brain's tools are Claude Code's own, the fleet's (KubeCoder's MCP server) and
 * `pilot-store`'s; anything else shows its bare name.
 */

export type ToolKind = 'read' | 'command' | 'search' | 'edit' | 'agent' | 'web' | 'store' | 'fleet' | 'todo' | 'other';

interface ToolSummary {
  kind: ToolKind;
  /** "Read", "Ran", "Searched": the verb, past tense, for a finished call. */
  verb: string;
  /** "Reading", "Running": while it runs. */
  verbRunning: string;
  /** The object: a path, a command, a pattern. */
  target: string;
}

const str = (v: unknown): string => (typeof v === 'string' ? v : '');

/** The last two segments of a path: enough to tell the file, short enough for a line. */
function shortPath(path: string): string {
  const parts = path.split('/').filter(Boolean);
  return parts.length <= 2 ? path : `…/${parts.slice(-2).join('/')}`;
}

const firstLine = (s: string) => s.split('\n')[0] ?? '';

const STORE_VERBS: Record<string, [string, string]> = {
  answer: ['Recorded an answer', 'Recording an answer'],
  add_item: ['Added an item', 'Adding an item'],
  mark: ['Marked an item', 'Marking an item'],
  attach_file: ['Attached', 'Attaching'],
  stop_work: ['Stopped a session', 'Stopping a session'],
  finish: ['Finished the project', 'Finishing the project'],
};

export function summarizeTool(name: string, input: Record<string, unknown>): ToolSummary {
  switch (name) {
    case 'Read':
      return { kind: 'read', verb: 'Read', verbRunning: 'Reading', target: shortPath(str(input.file_path)) };
    case 'Bash':
      return {
        kind: 'command',
        verb: 'Ran',
        verbRunning: 'Running',
        target: str(input.description) || firstLine(str(input.command)),
      };
    case 'Grep':
      return {
        kind: 'search',
        verb: 'Searched for',
        verbRunning: 'Searching for',
        target: `“${str(input.pattern)}”${input.path ? ` in ${shortPath(str(input.path))}` : ''}`,
      };
    case 'Glob':
      return { kind: 'search', verb: 'Listed', verbRunning: 'Listing', target: str(input.pattern) };
    case 'Edit':
    case 'Write':
    case 'NotebookEdit':
      return { kind: 'edit', verb: 'Edited', verbRunning: 'Editing', target: shortPath(str(input.file_path)) };
    case 'Agent':
    case 'Task':
      return {
        kind: 'agent',
        verb: `${str(input.subagent_type) || 'Sub'} agent`,
        verbRunning: `${str(input.subagent_type) || 'Sub'} agent`,
        target: str(input.description),
      };
    case 'WebFetch':
      return { kind: 'web', verb: 'Fetched', verbRunning: 'Fetching', target: str(input.url) };
    case 'WebSearch':
      return { kind: 'web', verb: 'Searched the web for', verbRunning: 'Searching the web for', target: `“${str(input.query)}”` };
    case 'TodoWrite':
      return { kind: 'todo', verb: 'Updated the plan', verbRunning: 'Updating the plan', target: '' };
  }
  const mcp = /^mcp__(.+?)__(.+)$/.exec(name);
  if (mcp) {
    const [, server, tool] = mcp;
    if (server === 'pilot-store') {
      const [verb, verbRunning] = STORE_VERBS[tool!] ?? [tool!, tool!];
      return { kind: 'store', verb, verbRunning, target: '' };
    }
    const words = tool!.replace(/_/g, ' ');
    return {
      kind: 'fleet',
      verb: server === 'kubecoder' ? 'KubeCoder' : server!,
      verbRunning: server === 'kubecoder' ? 'KubeCoder' : server!,
      target: `${words}${input.name ? ` · ${str(input.name)}` : input.environment ? ` · ${str(input.environment)}` : ''}`,
    };
  }
  return { kind: 'other', verb: name, verbRunning: name, target: '' };
}

/** A run of calls in one line, in the order they first ran: "Asked KubeCoder, read a file". */
export function summarizeRun(kinds: ToolKind[]): string {
  const counts = new Map<ToolKind, number>();
  for (const k of kinds) counts.set(k, (counts.get(k) ?? 0) + 1);
  const words = (k: ToolKind, c: number): string => {
    const n = (one: string, many: string) => (c === 1 ? one : many.replace('#', String(c)));
    switch (k) {
      case 'read':
        return n('read a file', 'read # files');
      case 'command':
        return n('ran a command', 'ran # commands');
      case 'search':
        return n('searched once', 'searched # times');
      case 'edit':
        return n('edited a file', 'edited # files');
      case 'web':
        return n('went to the web', 'went to the web # times');
      case 'fleet':
        return n('asked KubeCoder', 'asked KubeCoder # times');
      case 'store':
        return n('changed the record', 'changed the record # times');
      case 'todo':
        return 'updated the plan';
      case 'agent':
        return n('started an agent', 'started # agents');
      case 'other':
        return n('used a tool', 'used # tools');
    }
  };
  const text = [...counts].map(([k, c]) => words(k, c)).join(', ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}
