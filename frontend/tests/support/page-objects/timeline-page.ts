import type { Locator, Page } from '@playwright/test';
import type { UiStateTestEvent } from '@/lib/test/test-events';
import { waitTestEvent } from '../helpers';

/**
 * A project's timeline (F8): its rows, the opening, its items open and as done lines with Open and
 * Undo, an open item's block (F31) or a confirmation's card (F22), *In the chat* in a block's head
 * and a done line (F42.3), an inline document's blocks,
 * segments and *Send answers* with its dialog (F24.1, F33, F32.5), a larger document's or a
 * review's card (F24.2, F25), a registered document's read awaited or failed and that Pilot asked
 * its writer (F85.1, F86.8), a section
 * Pilot settled as its line (F31.5), an item's attachments
 * and a done line's indicator of them (F17.5, F13.6), Pilot's dots (F35), the
 * urgent banners and the "N open above" chip
 * (F10.2, F11), a finished timeline's end (F5.3), and where it stands scrolled; opened at its
 * project's address or at an item's or a block's under it (F97). A work item open shows its env
 * chip, "running N min", its one line — the working cue and the latest step — its Session log
 * (F26), and Stop with its question or Resume (F67).
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
  /** The opening's attachments' chips. */
  readonly openingAttachments: Locator;
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
    this.openingAttachments = this.opening.getByTestId('timeline.attachment');
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
      /** The head's Discuss, quoting the item (F39.1). */
      discuss: root.getByTestId('timeline.item.discuss'),
      kind: root.getByTestId('timeline.item.kind'),
      time: root.getByTestId('timeline.item.time'),
      urgent: root.getByTestId('timeline.item.urgent'),
      why: root.getByTestId('timeline.item.why'),
      /** A confirmation card's auto pilot mark (F4.4). */
      autopilotMark: root.getByTestId('timeline.item.autopilot-mark'),
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
      /** A work item's line: how it closed, where its time does not say it. */
      closed: root.getByTestId('timeline.line.closed'),
      note: root.getByTestId('timeline.line.note'),
      undo: root.getByTestId('timeline.line.undo'),
      open: root.getByTestId('timeline.line.open'),
      lineDiscuss: root.getByTestId('timeline.line.discuss'),
      /** *In the chat* after a one-ask item's answer given in the chat. */
      lineInChat: root.getByTestId('timeline.line.in-chat'),
      /** The attachments' chips, and each by its attachment's id. */
      attachments: root.getByTestId('timeline.attachment'),
      attachment: (attachmentId: string) => root.locator(`[data-testid="timeline.attachment"][data-attachment-id="${attachmentId}"]`),
      /** A done line's indicator: the one attachment, or the menu of several and its items. */
      lineAttachment: root.getByTestId('timeline.line.attachment'),
      lineAttachments: root.getByTestId('timeline.line.attachments'),
      lineAttachmentsMenu: root.getByTestId('timeline.line.attachments.menu'),
      lineAttachmentItems: root.getByTestId('timeline.line.attachments.item'),
      block: blockParts(this.page, root.getByTestId('timeline.block')),
      confirm: this.confirm(root),
      edited: root.getByTestId('timeline.item.edited'),
      editedTime: root.getByTestId('timeline.item.edited.time'),
      unsent: root.getByTestId('timeline.item.unsent'),
      /** "Pilot asked the writer about D2 and D4", under an inline document's title or a card's summary. */
      writerAsked: root.getByTestId('timeline.item.writer-asked'),
      writing: root.getByTestId('timeline.writing'),
      document: root.getByTestId('timeline.item.document'),
      blocks: root.getByTestId('timeline.block'),
      /** A document's block by its id. */
      blockAt: (blockId: string) => blockParts(this.page, root.locator(`[data-testid="timeline.block"][data-block-id="${blockId}"]`)),
      segments: root.getByTestId('timeline.segment'),
      segment: (blockId: string) => root.locator(`[data-testid="timeline.segment"][data-segment="${blockId}"]`),
      /** The lists of settled sections' lines, and each line by its block's id. */
      settled: root.getByTestId('timeline.settled'),
      settledLines: root.getByTestId('timeline.settled.line'),
      settledLine: (blockId: string) => settledParts(root, blockId),
      send: root.getByTestId('timeline.item.send'),
      work: {
        environment: root.getByTestId('timeline.work.environment'),
        running: root.getByTestId('timeline.work.running'),
        line: root.getByTestId('timeline.work.line'),
        cue: root.getByTestId('timeline.work.line').getByTestId('chat.cue'),
        step: root.getByTestId('timeline.work.step'),
        sessionLog: root.getByTestId('timeline.work.session-log'),
        stop: root.getByTestId('timeline.work.stop'),
        resume: root.getByTestId('timeline.work.resume'),
        /** A job's Retry, once it stopped or failed, and the line saying a Retry placed a new one. */
        retry: root.getByTestId('timeline.work.retry'),
        retried: root.getByTestId('timeline.work.retried'),
        /** Stop's question, in the actions' place: its words, Stop it and Cancel. */
        stopConfirm: {
          root: root.getByTestId('timeline.work.stop-confirm'),
          text: root.getByTestId('timeline.work.stop-confirm.text'),
          yes: root.getByTestId('timeline.work.stop-confirm.yes'),
          cancel: root.getByTestId('timeline.work.stop-confirm.cancel'),
        },
      },
      card: {
        root: root.getByTestId('timeline.item.card'),
        summary: root.getByTestId('timeline.item.summary'),
        counts: root.getByTestId('timeline.item.count'),
        /** The auto pilot chip beside the counts (F4.4). */
        autopilotChip: root.getByTestId('timeline.item.autopilot-chip'),
        readTime: root.getByTestId('timeline.item.read-time'),
        /** A registered document's "Loads when the turn ends" awaiting its read, and *Did not load* after it failed. */
        loads: root.getByTestId('timeline.item.loads'),
        didNotLoad: root.getByTestId('timeline.item.did-not-load'),
        open: root.getByTestId('timeline.item.open'),
        reviewed: root.getByTestId('timeline.item.reviewed'),
      },
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

/** An attachment's address under its item's (F28.5). */
export function attachmentAddress(projectId: string, itemId: string, attachmentId: string): string {
  return `/projects/${projectId}/items/${itemId}/attachments/${attachmentId}`;
}

/** An item's address under its project's, or a block's under the item's (F97). */
export function addressOf(projectId: string, itemId: string, blockId?: string): string {
  return `/projects/${projectId}/items/${itemId}${blockId === undefined ? '' : `/blocks/${blockId}`}`;
}

/** A settled section's line (F31.5), by its block's id: Pilot's mark, the heading's words, the answer, the note. */
export function settledParts(within: Locator, blockId: string) {
  const root = within.locator(`[data-testid="timeline.settled.line"][data-section="${blockId}"]`);
  return {
    root,
    avatar: root.locator('.avatar'),
    heading: root.getByTestId('timeline.settled.heading'),
    answer: root.getByTestId('timeline.settled.answer'),
    note: root.getByTestId('timeline.settled.note'),
  };
}

/**
 * An open item's block, its head, its answer; a decision's options, a question's field and Send,
 * an action's paste-back, Done and its options as buttons; Other and its console; a confirmation
 * block's check and cross, and No's console.
 */
export function blockParts(page: Page, root: Locator) {
  return {
    root,
    head: root.getByTestId('timeline.block.head'),
    discuss: root.getByTestId('timeline.block.discuss'),
    kind: root.getByTestId('timeline.block.kind'),
    /** A confirmation block's auto pilot mark (F4.4). */
    autopilotMark: root.getByTestId('timeline.block.autopilot-mark'),
    toggle: root.getByTestId('timeline.block.toggle'),
    answered: root.getByTestId('timeline.block.answered'),
    /** *In the chat*, on an answer given in the chat. */
    inChat: root.getByTestId('timeline.block.in-chat'),
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
    option: (label: string) => root.getByTestId('timeline.block.option').filter({ has: page.locator('.label', { hasText: label }) }),
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
