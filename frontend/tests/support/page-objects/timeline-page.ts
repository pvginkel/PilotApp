import type { Locator, Page } from '@playwright/test';
import type { UiStateTestEvent } from '@/lib/test/test-events';
import { waitTestEvent } from '../helpers';

/**
 * A project's timeline (F8): its rows, the opening, its items open and as done lines with Undo, an
 * open item's block (F31) or a confirmation's card (F22), an inline document's blocks, segments and
 * *Send answers* with its dialog (F24.1, F33, F32.5), Pilot's dots (F35), the urgent banners and
 * the "N open above" chip (F10.2, F11), a finished timeline's end (F5.3), and where it stands
 * scrolled; opened at its project's address or at an item's or a block's under it (F97).
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
  readonly banners: Locator;
  readonly openAbove: Locator;
  readonly finishedEnd: Locator;
  readonly finishedTime: Locator;
  /** *Send answers*' dialog over unanswered recommended blocks. */
  readonly sendDialog: { root: Locator; lines: Locator; note: Locator; cancel: Locator; confirm: Locator };

  constructor(private readonly page: Page) {
    this.root = page.getByTestId('timeline');
    this.rows = this.root.locator('.feed-inner > *');
    this.items = this.root.getByTestId('timeline.item');
    this.opening = this.root.getByTestId('timeline.opening');
    this.openingWho = this.opening.getByTestId('timeline.opening.who');
    this.openingWords = this.opening.getByTestId('timeline.opening.words');
    this.openingMore = this.opening.getByTestId('timeline.opening.words.more');
    this.empty = this.root.getByTestId('timeline.empty');
    this.banners = this.root.getByTestId('timeline.banner');
    this.openAbove = this.root.getByTestId('timeline.open-above');
    this.finishedEnd = this.root.getByTestId('timeline.divider.finished');
    this.finishedTime = this.root.getByTestId('timeline.divider.finished.time');
    const dialog = page.getByTestId('timeline.send-dialog');
    this.sendDialog = {
      root: dialog,
      lines: dialog.getByTestId('timeline.send-dialog.line'),
      note: dialog.getByTestId('timeline.send-dialog.note'),
      cancel: dialog.getByTestId('timeline.send-dialog.cancel'),
      confirm: dialog.getByTestId('timeline.send-dialog.confirm'),
    };
  }

  /**
   * Opens a project at its own address, once its timeline is read and drawn: not at the ready
   * StrictMode's first unmount reports, marked aborted.
   */
  async open(id: string): Promise<void> {
    await this.goto(`/projects/${id}`);
  }

  /** Opens the project at an item's address, or a block's under it, once its timeline is read and drawn. */
  async openAt(id: string, itemId: string, blockId?: string): Promise<void> {
    await this.goto(addressOf(id, itemId, blockId));
  }

  private async goto(path: string): Promise<void> {
    const read = waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === 'project.timeline' && event.phase === 'ready' && event.metadata?.status !== 'aborted',
    );
    await this.page.goto(path);
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
      why: root.getByTestId('timeline.item.why'),
      forUser: root.getByTestId('timeline.item.for'),
      title: root.getByTestId('timeline.item.title'),
      text: root.getByTestId('timeline.item.text'),
      more: root.getByTestId('timeline.item.text.more'),
      read: root.getByTestId('timeline.item.read'),
      line: root.getByTestId('timeline.line'),
      lineKind: root.getByTestId('timeline.line.kind'),
      lineTitle: root.getByTestId('timeline.line.title'),
      lineTime: root.getByTestId('timeline.line.time'),
      said: root.getByTestId('timeline.line.said'),
      note: root.getByTestId('timeline.line.note'),
      undo: root.getByTestId('timeline.line.undo'),
      block: this.block(root.getByTestId('timeline.block')),
      confirm: this.confirm(root),
      edited: root.getByTestId('timeline.item.edited'),
      editedTime: root.getByTestId('timeline.item.edited.time'),
      unsent: root.getByTestId('timeline.item.unsent'),
      writing: root.getByTestId('timeline.writing'),
      document: root.getByTestId('timeline.item.document'),
      blocks: root.getByTestId('timeline.block'),
      /** A document's block by its id. */
      blockAt: (blockId: string) => this.block(root.locator(`[data-testid="timeline.block"][data-block-id="${blockId}"]`)),
      segments: root.getByTestId('timeline.segment'),
      segment: (blockId: string) => root.locator(`[data-testid="timeline.segment"][data-segment="${blockId}"]`),
      send: root.getByTestId('timeline.item.send'),
    };
  }

  /**
   * An open item's block, its head, its answer; a decision's options, a question's field and Send,
   * an action's paste-back, Done and its options as buttons; Other and its console; a confirmation
   * block's check and cross, and No's console.
   */
  private block(root: Locator) {
    return {
      root,
      head: root.getByTestId('timeline.block.head'),
      kind: root.getByTestId('timeline.block.kind'),
      toggle: root.getByTestId('timeline.block.toggle'),
      answered: root.getByTestId('timeline.block.answered'),
      who: root.getByTestId('timeline.block.who'),
      time: root.getByTestId('timeline.block.time'),
      deferred: root.getByTestId('timeline.block.deferred'),
      note: root.getByTestId('timeline.block.note'),
      said: root.getByTestId('timeline.block.said'),
      answerField: root.getByTestId('timeline.block.field'),
      answerSend: root.getByTestId('timeline.block.send'),
      paste: root.getByTestId('timeline.block.paste'),
      done: root.getByTestId('timeline.block.done'),
      acts: root.getByTestId('timeline.block.act'),
      act: (label: string) => root.getByTestId('timeline.block.act').filter({ hasText: label }),
      options: root.getByTestId('timeline.block.option'),
      option: (label: string) => root.getByTestId('timeline.block.option').filter({ has: this.page.locator('.label', { hasText: label }) }),
      other: root.getByTestId('timeline.block.other'),
      console: root.getByTestId('timeline.block.console'),
      field: root.getByTestId('timeline.block.console.field'),
      send: root.getByTestId('timeline.block.console.send'),
      cancel: root.getByTestId('timeline.block.console.cancel'),
      yes: root.getByTestId('timeline.confirm.yes'),
      no: root.getByTestId('timeline.confirm.no'),
      noField: root.getByTestId('timeline.confirm.console.field'),
      noSend: root.getByTestId('timeline.confirm.console.send'),
    };
  }

  /** An open confirmation's card: its proposal, the check and the cross, No's console, Details. */
  private confirm(item: Locator) {
    return {
      root: item.getByTestId('timeline.confirm'),
      proposal: item.getByTestId('timeline.confirm.proposal'),
      yes: item.getByTestId('timeline.confirm.yes'),
      no: item.getByTestId('timeline.confirm.no'),
      console: item.getByTestId('timeline.confirm.console'),
      field: item.getByTestId('timeline.confirm.console.field'),
      send: item.getByTestId('timeline.confirm.console.send'),
      cancel: item.getByTestId('timeline.confirm.console.cancel'),
      details: item.getByTestId('timeline.confirm.details'),
      prose: item.getByTestId('timeline.confirm.prose'),
    };
  }

  /** The banner pinned for the urgent item `id`. */
  banner(id: string): Locator {
    return this.root.locator(`[data-testid="timeline.banner"][data-item-id="${id}"]`);
  }

  /** The items the banners point at, in their order. */
  async bannerItems(): Promise<string[]> {
    return this.banners.evaluateAll((banners) => banners.map((banner) => banner.getAttribute('data-item-id') ?? ''));
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

/** An item's address under its project's, or a block's under the item's (F97). */
export function addressOf(projectId: string, itemId: string, blockId?: string): string {
  return `/projects/${projectId}/items/${itemId}${blockId === undefined ? '' : `/blocks/${blockId}`}`;
}
