import type { Locator, Page } from '@playwright/test';
import type { UiStateTestEvent } from '@/lib/test/test-events';
import { waitTestEvent } from '../helpers';
import { projectAddress } from '../projects';

/**
 * A work item's session log in the overlay (F69), at its own address: off a phone its popover over
 * the tab showing, a dialog, on a phone a view. Its head with "Session log", the session's id its
 * tooltip, the item's title and the environment's link, a worker's run's Pilot's job after its
 * turn, on a phone Discuss, off one the cross; its
 * body with a reply per turn — text, a run of calls, a sub-agent's card, the phantom, a failure, the
 * server's word on a file the session registered, a call's effects in its place and an effect whose
 * call no record shows in its own — each ended one closing on its time, and before it what the
 * server sent the turn, as Pilot's message, clamped, with its Show more and Show less; and its
 * tail, the working cue or how it ended.
 */
export class SessionLogPage {
  readonly overlay: Locator;
  readonly head: Locator;
  readonly title: Locator;
  /** The line under the title: the item's title, the dot and the environment's link. */
  readonly sub: Locator;
  readonly item: Locator;
  readonly environment: Locator;
  /** A worker's run's: Pilot's job after its turn in its head (F59.1), `data-form` and `data-state` on its root. */
  readonly job: { root: Locator; pulse: Locator; retry: Locator };
  readonly close: Locator;
  readonly body: Locator;
  readonly log: Locator;
  readonly turns: Locator;
  readonly turnEnds: Locator;
  /** What the server sent each turn, as Pilot's message: its text, clamped, and under it Pilot and the time. */
  readonly sent: Locator;
  readonly sentTexts: Locator;
  readonly sentEnds: Locator;
  readonly sentMore: Locator;
  readonly sentLess: Locator;
  /** The replies' steps in their order, each a text, a call or a run of them, a card, a notice or an effect. */
  readonly steps: Locator;
  readonly texts: Locator;
  readonly tools: Locator;
  readonly runs: Locator;
  readonly agents: Locator;
  readonly phantom: Locator;
  readonly failures: Locator;
  readonly notices: Locator;
  /** The effects whose call no record shows; a call's own stand in its line's place, among `tools`. */
  readonly effects: Locator;
  readonly cue: Locator;
  /** The cue's dancing dots. */
  readonly dots: Locator;
  readonly tail: Locator;
  /** Under the tail of a job retried: that it was, and its words, the link to the retry's log. */
  readonly retried: Locator;
  readonly retriedLink: Locator;
  readonly failed: Locator;
  readonly discuss: Locator;

  constructor(private readonly page: Page) {
    // A dialog, never a tab, which it may lie over.
    this.overlay = page.locator('[data-testid="overlay"][role="dialog"]');
    this.head = this.overlay.getByTestId('overlay.head');
    this.title = this.overlay.getByTestId('overlay.title');
    this.sub = this.overlay.getByTestId('overlay.sub');
    this.item = this.overlay.getByTestId('session-log.item');
    this.environment = this.overlay.getByTestId('session-log.environment');
    this.job = {
      root: this.head.getByTestId('overlay.job'),
      pulse: this.head.getByTestId('overlay.job.pulse'),
      retry: this.head.getByTestId('overlay.job.retry'),
    };
    this.close = this.overlay.getByTestId('overlay.close');
    this.body = this.overlay.getByTestId('overlay.body');
    this.log = this.overlay.getByTestId('session-log');
    this.turns = this.log.getByTestId('session-log.turn');
    this.turnEnds = this.log.getByTestId('session-log.turn-end');
    this.sent = this.log.getByTestId('session-log.sent');
    this.sentTexts = this.log.getByTestId('session-log.sent.text');
    this.sentEnds = this.log.getByTestId('session-log.sent.end');
    this.sentMore = this.log.getByTestId('session-log.sent.text.more');
    this.sentLess = this.log.getByTestId('session-log.sent.text.less');
    this.steps = this.log.getByTestId('chat.reply').locator(':scope > *');
    this.texts = this.log.getByTestId('chat.text');
    this.tools = this.log.getByTestId('chat.tool');
    this.runs = this.log.getByTestId('chat.run');
    this.agents = this.log.getByTestId('chat.agent');
    this.phantom = this.log.getByTestId('chat.phantom');
    this.failures = this.log.getByTestId('chat.failure');
    this.notices = this.log.getByTestId('chat.notice');
    this.effects = this.log.getByTestId('chat.effect');
    this.cue = this.log.getByTestId('session-log.cue');
    this.dots = this.cue.getByTestId('chat.cue.dots');
    this.tail = this.log.getByTestId('session-log.tail');
    this.retried = this.log.getByTestId('session-log.retried');
    this.retriedLink = this.log.getByTestId('session-log.retried.link');
    this.failed = this.overlay.getByTestId('overlay.failed');
    this.discuss = this.overlay.getByTestId('overlay.discuss');
  }

  /** Opens the session log at its address, once its project's timeline is read and its stream reads live on the browser's connection. */
  async open(projectId: string, sessionId: string): Promise<void> {
    const reads = Promise.all([this.read('project.timeline'), this.live()]);
    await this.page.goto(sessionLogAddress(projectId, sessionId));
    await reads;
  }

  /** The next time its stream has read its records with its view on the browser's connection, so that what is written after it comes live. */
  live(): Promise<UiStateTestEvent> {
    return waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === 'session-log' && event.phase === 'ready' && event.metadata?.live === true,
    );
  }

  /** The next change of its body's pinning to the bottom. */
  sticky(stuck: boolean): Promise<UiStateTestEvent> {
    return waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === 'session-log.sticky' && event.metadata?.stuck === stuck,
    );
  }

  /** How far its body is from its bottom. */
  async scroll(): Promise<{ fromBottom: number }> {
    return this.body.evaluate((body) => ({ fromBottom: body.scrollHeight - body.scrollTop - body.clientHeight }));
  }

  private read(scope: string) {
    return waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === scope && event.phase === 'ready' && event.metadata?.status !== 'aborted',
    );
  }
}

/** A work item's session log's address under its project's, by its session's id, the item's (F69). */
export function sessionLogAddress(projectId: string, sessionId: string): string {
  return `${projectAddress(projectId)}/sessions/${sessionId}`;
}
