import type { Locator, Page } from '@playwright/test';
import type { FormTestEvent, UiStateTestEvent } from '@/lib/test/test-events';
import { waitTestEvent } from '../helpers';

/** One conversation in the tab: its head, and its transcript under it. */
interface ConversationParts {
  root: Locator;
  head: Locator;
  /** The environment whose session opened it. */
  environment: Locator;
  /** The session's name, where it gave one. */
  session: Locator;
  /** "Open" or "Closed". */
  state: Locator;
  stop: Locator;
  messageTexts: Locator;
  names: Locator;
  texts: Locator;
  phantom: Locator;
  cue: Locator;
  replyEnds: Locator;
  closed: Locator;
}

/**
 * The Conversations tab (F150.12): its tab in the panel's head and among the phone's tabs at the
 * bottom; its transcript, the conversations shown, each under its head — the environment, the
 * session, "Open" or "Closed", and Stop while Pilot answers — with its caller's messages and
 * Pilot's replies as a chat's; "Load previous" at the top, and the line in its place where the
 * tab's read failed.
 */
export class ConversationsPage {
  readonly tab: Locator;
  readonly root: Locator;
  readonly body: Locator;
  /** The conversations shown, in their order. */
  readonly conversations: Locator;
  readonly heads: Locator;
  readonly before: Locator;
  readonly failed: Locator;

  constructor(private readonly page: Page) {
    const panel = page.getByTestId('panel');
    this.tab = panel.getByTestId('panel.tab.conversations');
    this.root = panel.getByTestId('panel.conversations');
    this.body = this.root.getByTestId('conversations.body');
    this.conversations = this.root.getByTestId('conversation');
    this.heads = this.root.getByTestId('conversation.head');
    this.before = this.root.getByTestId('conversations.before');
    this.failed = this.root.getByTestId('conversations.failed');
  }

  /** The conversation by its id. */
  conversation(id: string): ConversationParts {
    const root = this.root.locator(`[data-testid="conversation"][data-conversation="${id}"]`);
    const head = root.getByTestId('conversation.head');
    return {
      root,
      head,
      environment: head.getByTestId('conversation.environment'),
      session: head.getByTestId('conversation.session'),
      state: head.getByTestId('conversation.state'),
      stop: head.getByTestId('conversation.stop'),
      messageTexts: root.getByTestId('chat.person.text'),
      names: root.getByTestId('chat.person.name'),
      texts: root.getByTestId('chat.text'),
      phantom: root.getByTestId('chat.phantom'),
      cue: root.getByTestId('chat.cue'),
      replyEnds: root.getByTestId('chat.pilot.end'),
      closed: root.getByTestId('chat.closed'),
    };
  }

  /** The next read of the project's list of conversations, done. */
  read(): Promise<UiStateTestEvent> {
    return waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === 'panel.conversations' && event.phase === 'ready' && event.metadata?.status !== 'aborted',
    );
  }

  /** The next time the conversation's stream has read its records with its view on the browser's connection, so that what is written after it comes live. */
  live(conversationId: string): Promise<UiStateTestEvent> {
    return waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === 'chat.section' && event.phase === 'ready' && event.metadata?.chat === conversationId && event.metadata.live === true,
    );
  }

  /** The server's next answer taking a conversation's Stop, as the browser has it. */
  stopped(): Promise<FormTestEvent> {
    return waitTestEvent<FormTestEvent>(this.page, 'form', (event) => event.formId === 'conversation.stop' && event.phase === 'success');
  }
}
