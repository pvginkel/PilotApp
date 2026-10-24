/**
 * The lines of `claude`'s stream-json stdout the chat reads, as a headless turn prints them with
 * `--include-partial-messages` (KubeCoder's response stream, `format=raw`). Typed loosely: a
 * record keeps the line verbatim, and the view reads only what it shows (an allowlist).
 *
 * The shapes follow KubeCoder's goldens (worker/internal/claudeshim/goldens/headless_*.jsonl).
 */

interface TextBlock {
  type: 'text';
  text: string;
}

interface ThinkingBlock {
  type: 'thinking';
  /** Empty when `claude` shows thinking as updates only: most blocks. */
  thinking: string;
  signature?: string;
}

interface ToolUseBlock {
  type: 'tool_use';
  id: string;
  name: string;
  input: Record<string, unknown>;
}

interface ToolResultBlock {
  type: 'tool_result';
  tool_use_id: string;
  content: string | { type: string; text?: string }[];
  is_error?: boolean;
}

type AssistantBlock = TextBlock | ThinkingBlock | ToolUseBlock;

interface LineBase {
  session_id?: string;
  uuid?: string;
  /** Set on a sub-agent's lines: the main thread's Agent call it runs under. */
  parent_tool_use_id?: string | null;
  timestamp?: string;
}

/** One content block of an API message, whole, after its deltas. */
export interface AssistantLine extends LineBase {
  type: 'assistant';
  message: { id: string; content: AssistantBlock[] };
  /** On a thinking block's line. */
  thinking_duration_ms?: number;
  /** An API error `claude` reports as a message (the error golden). */
  error?: string;
  is_api_error_message?: boolean;
  subagent_type?: string;
}

/** A tool's result, as the next user message. */
interface UserLine extends LineBase {
  type: 'user';
  message: { role: 'user'; content: ToolResultBlock[] | string };
}

/** `claude`'s own result line: one turn may print several (a background agent's notice). */
interface ResultLine extends LineBase {
  type: 'result';
  subtype: string;
  is_error: boolean;
  result?: string;
  duration_ms?: number;
  num_turns?: number;
}

/** The system notices: init, status, thinking_tokens, the background tasks' lifecycle. */
export interface SystemLine extends LineBase {
  type: 'system';
  subtype: string;
  task_id?: string;
  tool_use_id?: string;
  description?: string;
  subagent_type?: string;
  last_tool_name?: string;
  status?: string;
  summary?: string;
  estimated_tokens?: number;
  [key: string]: unknown;
}

type StreamEvent =
  | { type: 'message_start'; message: { id: string } }
  | {
      type: 'content_block_start';
      index: number;
      content_block: { type: 'text' | 'thinking' | 'tool_use' | string; name?: string; id?: string };
    }
  | {
      type: 'content_block_delta';
      index: number;
      delta:
        | { type: 'text_delta'; text: string }
        | { type: 'thinking_delta'; thinking: string }
        | { type: 'input_json_delta'; partial_json: string }
        | { type: 'signature_delta'; signature: string };
    }
  | { type: 'content_block_stop'; index: number }
  | { type: 'message_delta'; delta: Record<string, unknown> }
  | { type: 'message_stop' };

/** A partial-message line: never a record; a marker or a text delta is forwarded live. */
export interface StreamEventLine extends LineBase {
  type: 'stream_event';
  event: StreamEvent;
}

interface OtherLine extends LineBase {
  type: 'rate_limit_event' | string;
  [key: string]: unknown;
}

export type ClaudeLine = AssistantLine | UserLine | ResultLine | SystemLine | StreamEventLine | OtherLine;

export const isAssistant = (l: ClaudeLine): l is AssistantLine => l.type === 'assistant';
export const isUser = (l: ClaudeLine): l is UserLine => l.type === 'user';
export const isSystem = (l: ClaudeLine): l is SystemLine => l.type === 'system';
export const isMainThread = (l: ClaudeLine): boolean => !l.parent_tool_use_id;

/** The text of a tool result, its parts joined. */
export function resultText(block: ToolResultBlock): string {
  if (typeof block.content === 'string') return block.content;
  return block.content.map((part) => part.text ?? '').join('\n');
}
