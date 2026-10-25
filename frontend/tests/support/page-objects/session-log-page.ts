import type { Locator, Page } from '@playwright/test';
import type { UiStateTestEvent } from '@/lib/test/test-events';
import { waitTestEvent } from '../helpers';

/**
 * A work item's session log in the overlay (F69), at its own address over its project's timeline:
 * its head with "Session log", the item's title, the environment's link and the session's id; its
 * body with a reply per turn — text, a run of calls, a sub-agent's card, the phantom, a failure, the
 * server's word on a file the session registered — each ended one closing on its time; and its
 * tail, the working cue or how it ended.
 */
export class SessionLogPage {
  readonly overlay: Locator;
  readonly title: Locator;
  readonly item: Locator;
  readonly environment: Locator;
  readonly session: Locator;
  readonly body: Locator;
  readonly log: Locator;
  readonly turns: Locator;
  readonly turnEnds: Locator;
  readonly texts: Locator;
  readonly tools: Locator;
  readonly runs: Locator;
  readonly agents: Locator;
  readonly phantom: Locator;
  readonly failures: Locator;
  readonly notices: Locator;
  readonly cue: Locator;
  readonly tail: Locator;
  readonly failed: Locator;

  constructor(private readonly page: Page) {
    this.overlay = page.getByTestId('overlay');
    this.title = this.overlay.getByTestId('overlay.title');
    this.item = this.overlay.getByTestId('session-log.item');
    this.environment = this.overlay.getByTestId('session-log.environment');
    this.session = this.overlay.getByTestId('session-log.session');
    this.body = this.overlay.getByTestId('overlay.body');
    this.log = this.overlay.getByTestId('session-log');
    this.turns = this.log.getByTestId('session-log.turn');
    this.turnEnds = this.log.getByTestId('session-log.turn-end');
    this.texts = this.log.getByTestId('chat.text');
    this.tools = this.log.getByTestId('chat.tool');
    this.runs = this.log.getByTestId('chat.run');
    this.agents = this.log.getByTestId('chat.agent');
    this.phantom = this.log.getByTestId('chat.phantom');
    this.failures = this.log.getByTestId('chat.failure');
    this.notices = this.log.getByTestId('chat.notice');
    this.cue = this.log.getByTestId('session-log.cue');
    this.tail = this.log.getByTestId('session-log.tail');
    this.failed = this.overlay.getByTestId('overlay.failed');
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
  return `/projects/${projectId}/sessions/${sessionId}`;
}
