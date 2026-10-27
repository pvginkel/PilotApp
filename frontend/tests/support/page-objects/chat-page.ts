import type { Locator, Page } from '@playwright/test';
import type { FormTestEvent, UiStateTestEvent } from '@/lib/test/test-events';
import { waitTestEvent } from '../helpers';

/**
 * The side panel's Chat tab (F38, F40, F130.1): its tab in the panel's head; its transcript, the
 * chats shown with each person's message — its quotes, words, the name of another person, the time
 * and the avatar — and Pilot's reply to it, its steps, the phantom, the cue, a failure and its end;
 * the date dividers, the line where a chat closed, "The chat before · <day>" at the top, the empty
 * state, and the line in its place where the tab's read failed; and under the transcript the
 * composer (F44): the quote Discuss put over its field and its remove (F39.3), its field, Send or
 * Stop in its place, and why an archived project's takes no message. The tab carries the unread dot
 * (F43). A draft's definition chat is the same, standing in the timeline's place (`feed`, F46.1),
 * its empty state "Tell Pilot what to manage" (F113) and no tab.
 */
export class ChatPage {
  readonly tab: Locator;
  readonly tabDot: Locator;
  readonly root: Locator;
  readonly body: Locator;
  readonly messages: Locator;
  readonly messageTexts: Locator;
  readonly names: Locator;
  readonly messageEnds: Locator;
  readonly quotes: Locator;
  readonly replies: Locator;
  readonly texts: Locator;
  readonly phantom: Locator;
  readonly cue: Locator;
  readonly failures: Locator;
  readonly replyEnds: Locator;
  readonly days: Locator;
  readonly closed: Locator;
  readonly before: Locator;
  readonly empty: Locator;
  readonly failed: Locator;
  /** Everything in the transcript, in its order: dividers, messages, replies, the button and the lines. */
  readonly lines: Locator;
  readonly composer: Locator;
  /** The quote over the field: its `data-quote`, its label and its remove. */
  readonly quote: Locator;
  readonly quoteLabel: Locator;
  readonly quoteRemove: Locator;
  readonly field: Locator;
  readonly send: Locator;
  readonly stop: Locator;
  readonly archived: Locator;

  constructor(
    private readonly page: Page,
    home: 'panel' | 'feed' = 'panel',
  ) {
    const panel = page.getByTestId('panel');
    this.tab = panel.getByTestId('panel.tab.chat');
    this.tabDot = this.tab.getByTestId('panel.tab.chat.unread');
    this.root = home === 'panel' ? panel.getByTestId('panel.chat') : page.getByTestId('project.chat');
    this.body = this.root.getByTestId('chat.body');
    this.messages = this.root.getByTestId('chat.person');
    this.messageTexts = this.root.getByTestId('chat.person.text');
    this.names = this.root.getByTestId('chat.person.name');
    this.messageEnds = this.root.getByTestId('chat.person.end');
    this.quotes = this.root.getByTestId('chat.quote');
    this.replies = this.root.getByTestId('chat.pilot');
    this.texts = this.root.getByTestId('chat.text');
    this.phantom = this.root.getByTestId('chat.phantom');
    this.cue = this.root.getByTestId('chat.cue');
    this.failures = this.root.getByTestId('chat.failure');
    this.replyEnds = this.root.getByTestId('chat.pilot.end');
    this.days = this.root.getByTestId('chat.day');
    this.closed = this.root.getByTestId('chat.closed');
    this.before = this.root.getByTestId('chat.before');
    this.empty = this.root.getByTestId('chat.empty');
    this.failed = this.root.getByTestId('chat.failed');
    this.lines = this.root.getByTestId('chat').locator(':scope > *');
    this.composer = this.root.getByTestId('chat.composer');
    this.quote = this.composer.getByTestId('chat.composer.quote');
    this.quoteLabel = this.quote.getByTestId('chat.composer.quote.label');
    this.quoteRemove = this.quote.getByTestId('chat.composer.quote.remove');
    this.field = this.composer.getByTestId('chat.composer.field');
    this.send = this.composer.getByTestId('chat.composer.send');
    this.stop = this.composer.getByTestId('chat.composer.stop');
    this.archived = this.composer.getByTestId('chat.composer.archived');
  }

  /** The server's next answer taking the composer's `send` or `stop`, or the chat marked seen at its end (`read`), as the browser has it. */
  acted(act: 'send' | 'stop' | 'read'): Promise<FormTestEvent> {
    return waitTestEvent<FormTestEvent>(this.page, 'form', (event) => event.formId === `chat.${act}` && event.phase === 'success');
  }

  /** The next read of the tab's list of chats, done. */
  read(): Promise<UiStateTestEvent> {
    return waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === 'panel.chat' && event.phase === 'ready' && event.metadata?.status !== 'aborted',
    );
  }

  /** The next time the chat's stream has read its records with its view on the browser's connection, so that what is written after it comes live. */
  live(chatId: string): Promise<UiStateTestEvent> {
    return waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === 'chat.section' && event.phase === 'ready' && event.metadata?.chat === chatId && event.metadata.live === true,
    );
  }

  /** The next change of the transcript's pinning to its end. */
  sticky(stuck: boolean): Promise<UiStateTestEvent> {
    return waitTestEvent<UiStateTestEvent>(this.page, 'ui_state', (event) => event.scope === 'chat.sticky' && event.metadata?.stuck === stuck);
  }

  /** Where an element stands from the top of the transcript's view. */
  async top(locator: Locator): Promise<number> {
    const [box, view] = await Promise.all([locator.boundingBox(), this.body.boundingBox()]);
    return box!.y - view!.y;
  }
}
