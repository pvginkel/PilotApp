import type { Locator, Page } from '@playwright/test';
import type { UiStateTestEvent } from '@/lib/test/test-events';
import { waitTestEvent } from '../helpers';
import { blockParts, settledParts } from './timeline-page';

/**
 * The overlay (F28): an item's document over its project's timeline, opened at the document's own
 * address (F97); its head with the title, the project, the step, the segment bar, *Unsent* or
 * *Done* and *Edited <time>*; its body with the summary, the prose and the blocks, the sections
 * Pilot settled as their lines, its attachments, Pilot's dots, or "The document did not load"; its
 * foot; maximize, the cross and the backdrop. Showing an attachment (F28.5), its head is its title
 * over "Attachment of “<item>”" and, opened from the document, Back; its body the attachment by
 * its type.
 */
export class OverlayPage {
  readonly root: Locator;
  readonly backdrop: Locator;
  readonly head: Locator;
  readonly title: Locator;
  readonly sub: Locator;
  readonly back: Locator;
  readonly project: Locator;
  readonly step: Locator;
  readonly segments: Locator;
  readonly unsent: Locator;
  readonly doneChip: Locator;
  readonly edited: Locator;
  readonly editedTime: Locator;
  readonly maximize: Locator;
  readonly close: Locator;
  readonly body: Locator;
  readonly summary: Locator;
  readonly document: Locator;
  readonly blocks: Locator;
  readonly settled: Locator;
  readonly settledLines: Locator;
  readonly writing: Locator;
  readonly failed: Locator;
  readonly foot: Locator;
  readonly done: Locator;
  readonly doneTime: Locator;
  readonly send: Locator;
  readonly reviewed: Locator;
  /** The body's attachments' chips. */
  readonly attachments: Locator;
  /** An attachment shown: its view, by its type in `data-view`, and its parts. */
  readonly attachment: {
    root: Locator;
    prose: Locator;
    image: Locator;
    text: Locator;
    fileTitle: Locator;
    size: Locator;
    download: Locator;
  };

  constructor(private readonly page: Page) {
    this.root = page.getByTestId('overlay');
    this.backdrop = page.getByTestId('overlay.backdrop');
    this.head = this.root.getByTestId('overlay.head');
    this.title = this.root.getByTestId('overlay.title');
    this.sub = this.root.getByTestId('overlay.sub');
    this.back = this.root.getByTestId('overlay.back');
    this.project = this.root.getByTestId('overlay.project');
    this.step = this.root.getByTestId('overlay.step');
    this.segments = this.head.getByTestId('timeline.segment');
    this.unsent = this.head.getByTestId('timeline.item.unsent');
    this.doneChip = this.root.getByTestId('overlay.done-chip');
    this.edited = this.head.getByTestId('timeline.item.edited');
    this.editedTime = this.head.getByTestId('timeline.item.edited.time');
    this.maximize = this.root.getByTestId('overlay.maximize');
    this.close = this.root.getByTestId('overlay.close');
    this.body = this.root.getByTestId('overlay.body');
    this.summary = this.root.getByTestId('overlay.summary');
    this.document = this.root.getByTestId('overlay.document');
    this.blocks = this.root.getByTestId('timeline.block');
    this.settled = this.root.getByTestId('timeline.settled');
    this.settledLines = this.root.getByTestId('timeline.settled.line');
    this.writing = this.root.getByTestId('timeline.writing');
    this.failed = this.root.getByTestId('overlay.failed');
    this.foot = this.root.getByTestId('overlay.foot');
    this.done = this.root.getByTestId('overlay.done');
    this.doneTime = this.root.getByTestId('overlay.done.time');
    this.send = this.foot.getByTestId('timeline.item.send');
    this.reviewed = this.root.getByTestId('overlay.reviewed');
    this.attachments = this.body.getByTestId('timeline.attachment');
    const attachment = this.root.getByTestId('overlay.attachment');
    this.attachment = {
      root: attachment,
      prose: attachment.locator('.prose'),
      image: attachment.getByTestId('overlay.attachment.image'),
      text: attachment.getByTestId('overlay.attachment.text'),
      fileTitle: attachment.getByTestId('overlay.attachment.file-title'),
      size: attachment.getByTestId('overlay.attachment.size'),
      download: attachment.getByTestId('overlay.attachment.download'),
    };
  }

  /** The body's attachment chip by its attachment's id. */
  attachmentChip(attachmentId: string): Locator {
    return this.body.locator(`[data-testid="timeline.attachment"][data-attachment-id="${attachmentId}"]`);
  }

  /** Opens a document at its own address, once its project's timeline and the document are read. */
  async open(projectId: string, documentId: string): Promise<void> {
    const read = (scope: string) =>
      waitTestEvent<UiStateTestEvent>(
        this.page,
        'ui_state',
        (event) => event.scope === scope && event.phase === 'ready' && event.metadata?.status !== 'aborted',
      );
    const reads = Promise.all([read('project.timeline'), read('overlay.document')]);
    await this.page.goto(documentAddress(projectId, documentId));
    await reads;
  }

  /** A block in the body, by its id. */
  blockAt(blockId: string) {
    return blockParts(this.page, this.root.locator(`[data-testid="timeline.block"][data-block-id="${blockId}"]`));
  }

  /** A settled section's line in the body, by its block's id. */
  settledLine(blockId: string) {
    return settledParts(this.root, blockId);
  }

  /** The head's segment for a block. */
  segment(blockId: string): Locator {
    return this.head.locator(`[data-testid="timeline.segment"][data-segment="${blockId}"]`);
  }

  async scrollTop(): Promise<number> {
    return this.body.evaluate((body) => body.scrollTop);
  }
}

/** An attachment's address under its document's (F28.5). */
export function documentAttachmentAddress(projectId: string, documentId: string, attachmentId: string): string {
  return `${documentAddress(projectId, documentId)}/attachments/${attachmentId}`;
}

/** A document's address under its project's (F97). */
export function documentAddress(projectId: string, documentId: string): string {
  return `/projects/${projectId}/documents/${documentId}`;
}
