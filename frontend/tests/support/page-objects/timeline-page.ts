import type { Locator, Page } from '@playwright/test';
import type { UiStateTestEvent } from '@/lib/test/test-events';
import { waitTestEvent } from '../helpers';

/**
 * A project's timeline (F8): its rows, the opening, its items open and as done lines, and where it
 * stands scrolled.
 */
export class TimelinePage {
  readonly root: Locator;
  /** The dividers, the opening and the items, in their order. */
  readonly rows: Locator;
  readonly items: Locator;
  readonly opening: Locator;
  readonly openingWho: Locator;
  readonly openingWords: Locator;
  readonly openingMore: Locator;
  readonly empty: Locator;

  constructor(private readonly page: Page) {
    this.root = page.getByTestId('timeline');
    this.rows = this.root.locator('.feed-inner > *');
    this.items = this.root.getByTestId('timeline.item');
    this.opening = this.root.getByTestId('timeline.opening');
    this.openingWho = this.opening.getByTestId('timeline.opening.who');
    this.openingWords = this.opening.getByTestId('timeline.opening.words');
    this.openingMore = this.opening.getByTestId('timeline.opening.words.more');
    this.empty = this.root.getByTestId('timeline.empty');
  }

  /**
   * Opens a project at its own address, once its timeline is read and drawn: not at the ready
   * StrictMode's first unmount reports, marked aborted.
   */
  async open(id: string): Promise<void> {
    const read = waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === 'project.timeline' && event.phase === 'ready' && event.metadata?.status !== 'aborted',
    );
    await this.page.goto(`/projects/${id}`);
    await read;
  }

  /** The item `id`, open or as its done line, and what it shows. */
  item(id: string) {
    const root = this.root.locator(`[data-testid="timeline.item"][data-item-id="${id}"]`);
    return {
      root,
      head: root.getByTestId('timeline.item.head'),
      kind: root.getByTestId('timeline.item.kind'),
      time: root.getByTestId('timeline.item.time'),
      urgent: root.getByTestId('timeline.item.urgent'),
      forUser: root.getByTestId('timeline.item.for'),
      title: root.getByTestId('timeline.item.title'),
      text: root.getByTestId('timeline.item.text'),
      more: root.getByTestId('timeline.item.text.more'),
      line: root.getByTestId('timeline.line'),
      lineTitle: root.getByTestId('timeline.line.title'),
      lineTime: root.getByTestId('timeline.line.time'),
      said: root.getByTestId('timeline.line.said'),
      note: root.getByTestId('timeline.line.note'),
    };
  }

  /** Each row as its test id and its text, in order. */
  async rowsRead(): Promise<[string, string][]> {
    return this.rows.evaluateAll((rows) =>
      rows.map((row) => [row.getAttribute('data-testid') ?? '', (row as HTMLElement).innerText.trim()] as [string, string]),
    );
  }

  /** How far the timeline stands from its end, in pixels. */
  async fromEnd(): Promise<number> {
    return this.root.evaluate((feed) => feed.scrollHeight - feed.scrollTop - feed.clientHeight);
  }

  async scrollTop(): Promise<number> {
    return this.root.evaluate((feed) => feed.scrollTop);
  }

  /** Scrolls the timeline to its top, as the reader does. */
  async scrollToTop(): Promise<void> {
    await this.root.evaluate((feed) => feed.scrollTo({ top: 0 }));
  }

  /** The window comes back into focus, which reads the timeline again. */
  async refocus(): Promise<void> {
    await this.page.evaluate(() => document.dispatchEvent(new Event('visibilitychange', { bubbles: true })));
  }
}
