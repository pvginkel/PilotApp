/**
 * A tool call's summary line (decision 3): what the call did, in a few words, from its input.
 * A session's tools are Claude Code's own, those of Pilot's MCP server, which every session knows
 * as `pilot` (the backend's `SERVER_KEY`), and those of the other MCP servers its environment
 * configures, each named as configured; anything else is used by its bare name. The line is one
 * colour: what it names as code is set in the mono face, and a command's or an agent's description,
 * the model's own sentence, stands without a verb. Every other line opens on its verb, so that a
 * running call's line reads as a status on its own, as a work item's line shows it (D167): "Asking
 * gitblit read file", "Using Skill".
 */

export type ToolKind = 'read' | 'command' | 'search' | 'edit' | 'agent' | 'web' | 'store' | 'progress' | 'mcp' | 'todo' | 'other';

/** A stretch of a line's words; `code`, a command, a path, a glob or an environment's name, in the mono face. */
export interface Words {
  text: string;
  code?: boolean;
}

interface ToolSummary {
  kind: ToolKind;
  /** An `mcp` call's server, by its name as configured. */
  server?: string;
  /** The finished call's line: "Read …/chat/tools.ts", "Searched for “cue”". */
  done: Words[];
  /** The running call's line: "Reading …/chat/tools.ts". */
  running: Words[];
}

/** A line's words as plain text: "Read …/chat/tools.ts". */
export const wordsText = (words: Words[]) => words.map((w) => w.text).join('');

const str = (v: unknown): string => (typeof v === 'string' ? v : '');

/** The last two segments of a path: enough to tell the file, short enough for a line. */
function shortPath(path: string): string {
  const parts = path.split('/').filter(Boolean);
  return parts.length <= 2 ? path : `…/${parts.slice(-2).join('/')}`;
}

const firstLine = (s: string) => s.split('\n')[0] ?? '';

/** Pilot's own MCP server, as a session's configuration names it. */
const PILOT_SERVER = 'pilot';

const STORE_VERBS: Record<string, [string, string]> = {
  answer: ['Recorded an answer', 'Recording an answer'],
  add_item: ['Added an item', 'Adding an item'],
  mark: ['Marked an item', 'Marking an item'],
  attach_file: ['Attached', 'Attaching'],
  stop_work: ['Stopped a session', 'Stopping a session'],
  finish: ['Finished the project', 'Finishing the project'],
};

/** A worker's calls that publish its work item's steps. */
const PROGRESS_VERBS: Record<string, [string, string]> = {
  set_progress: ['Published its steps', 'Publishing its steps'],
  set_progress_step: ['Moved a step', 'Moving a step'],
};

/**
 * A call's line from its input, or its verb alone while its input streams in (`null`): the verb,
 * past tense once it finished, then what it acted on; a description in the verb's place.
 */
export function summarizeTool(name: string, input: Record<string, unknown> | null): ToolSummary {
  const given = input ?? {};
  const line = (kind: ToolKind, verb: string, verbRunning: string, ...target: Words[]): ToolSummary => {
    const object = input === null ? [] : target.filter((w) => w.text !== '');
    const said = (v: string): Words[] => (object.length ? [{ text: `${v} ` }, ...object] : [{ text: v }]);
    return { kind, done: said(verb), running: said(verbRunning) };
  };
  const standing = (kind: ToolKind, ...words: Words[]): ToolSummary => ({ kind, done: words, running: words });
  switch (name) {
    case 'Read':
      return line('read', 'Read', 'Reading', { text: shortPath(str(given.file_path)), code: true });
    case 'Bash': {
      const description = str(given.description);
      if (description) return standing('command', { text: description });
      return line('command', 'Ran', 'Running', { text: firstLine(str(given.command)), code: true });
    }
    case 'Grep':
      return line(
        'search',
        'Searched for',
        'Searching for',
        { text: `“${str(given.pattern)}”` },
        ...(given.path ? [{ text: ' in ' }, { text: shortPath(str(given.path)), code: true }] : []),
      );
    case 'Glob':
      return line('search', 'Listed', 'Listing', { text: str(given.pattern), code: true });
    case 'Edit':
    case 'Write':
    case 'NotebookEdit':
      return line('edit', 'Edited', 'Editing', { text: shortPath(str(given.file_path)), code: true });
    case 'Agent':
    case 'Task': {
      const type = str(given.subagent_type);
      const description = str(given.description);
      if (description) return standing('agent', { text: description }, { text: ` · ${type || 'Sub'} agent` });
      return type ? line('agent', `Started the ${type} agent`, `Starting the ${type} agent`) : line('agent', 'Started an agent', 'Starting an agent');
    }
    case 'WebFetch':
      return line('web', 'Fetched', 'Fetching', { text: str(given.url) });
    case 'WebSearch':
      return line('web', 'Searched the web for', 'Searching the web for', { text: `“${str(given.query)}”` });
    case 'TodoWrite':
      return line('todo', 'Updated the plan', 'Updating the plan');
  }
  const mcp = /^mcp__(.+?)__(.+)$/.exec(name);
  if (mcp) {
    const [, server, tool] = mcp;
    if (server === PILOT_SERVER) {
      const progress = PROGRESS_VERBS[tool!];
      if (progress) return line('progress', ...progress);
      const [verb, verbRunning] = STORE_VERBS[tool!] ?? [`Used ${tool}`, `Using ${tool}`];
      return line('store', verb, verbRunning);
    }
    const asked = `${server} ${tool!.replace(/_/g, ' ')}`;
    const environment = str(given.name) || str(given.environment);
    return {
      ...line('mcp', `Asked ${asked}`, `Asking ${asked}`, ...(environment ? [{ text: '· ' }, { text: environment, code: true }] : [])),
      server,
    };
  }
  return line('other', `Used ${name}`, `Using ${name}`);
}

/**
 * A run of calls in one line, in the order they first ran, an MCP server's calls counted under its
 * own name: "Read a file, used gitblit 10 times".
 */
export function summarizeRun(calls: Pick<ToolSummary, 'kind' | 'server'>[]): string {
  const counts = new Map<string, { kind: ToolKind; server: string; count: number }>();
  for (const { kind, server = '' } of calls) {
    const counted = counts.get(`${kind} ${server}`);
    if (counted) counted.count += 1;
    else counts.set(`${kind} ${server}`, { kind, server, count: 1 });
  }
  const words = (k: ToolKind, server: string, c: number): string => {
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
      case 'mcp':
        return n(`used ${server} once`, `used ${server} # times`);
      case 'store':
        return n('changed the record', 'changed the record # times');
      case 'progress':
        return n('updated its steps', 'updated its steps # times');
      case 'todo':
        return 'updated the plan';
      case 'agent':
        return n('started an agent', 'started # agents');
      case 'other':
        return n('used a tool', 'used # tools');
    }
  };
  const text = [...counts.values()].map(({ kind, server, count }) => words(kind, server, count)).join(', ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}
