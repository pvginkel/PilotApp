import type { Locator, Page } from '@playwright/test';
import type { UiStateTestEvent } from '@/lib/test/test-events';
import { waitTestEvent } from '../helpers';
import { blockParts, settledParts } from './timeline-page';

/**
 * A document opened (F28): off a phone in its tab in its project's timeline's place, on a phone a
 * view, opened at the document's own address (F97); its head with the title, the project, the step, the segment bar, *Unsent* or
 * *Done* and *Edited <time>*, and its buttons: Pilot's job on the item, its Undo and Discuss; its body with the summary, the prose and the blocks, the sections
 * Pilot settled as their lines, its attachments, Pilot's dots, or "The document did not load"; its
 * foot; off a phone the session log's popover's cross, and no tab, view or popover draws a maximize or a backdrop; over the text, the box of Pilot's questions to a
 * registered document's writer and the reply (F52.2), which its own address opens it at. A document that is Pilot's has the strip under its head,
 * what Pilot does on it in `data-doing`, its words, its link and *Stop and take over* (F28.9), and
 * one awaiting its read says that its text comes once it is read; one a run of Pilot's put to the
 * person while it holds a block of another document has the Cancel in its foot. Showing an attachment (F28.5), its head is its title
 * over "Attachment of “<item>”", its document a link there; its body the attachment by its type.
 * On a phone it is a view (F98.4): Back is its arrow, with no maximize, cross or backdrop. Showing the handbook or the project document (F129.4, F37.4), its head is the title over
 * the project and what it is; its body the prose, its links to the project's attached material
 * among it, and Pilot's dots, or *Empty*. Showing the item
 * alone on a phone (F99), its head is the project's name over the item's step; its body the item as
 * the timeline draws it (`TimelinePage.item(id, overlay.alone)`).
 */
export class OverlayPage {
  readonly root: Locator;
  readonly backdrop: Locator;
  readonly head: Locator;
  readonly title: Locator;
  readonly sub: Locator;
  /** On a phone the view's arrow back. */
  readonly back: Locator;
  /** An attachment's document in its head, the link to it. */
  readonly documentLink: Locator;
  /** The project document's or the handbook's links to the project's attached material (F29.3). */
  readonly materialLinks: Locator;
  readonly project: Locator;
  /** What a read-only document of the project is: Handbook, Project document. */
  readonly role: Locator;
  readonly step: Locator;
  readonly segments: Locator;
  readonly unsent: Locator;
  readonly doneChip: Locator;
  readonly edited: Locator;
  readonly editedTime: Locator;
  readonly maximize: Locator;
  readonly close: Locator;
  /** The head's Discuss (F39.1). */
  readonly discuss: Locator;
  /**
   * Pilot's job on the document's item in its head (F28.10), in whichever form it stands, as
   * `TimelinePage.item(id).job` has it, `data-form` and `data-state` on its root.
   */
  readonly job: { root: Locator; pulse: Locator; retry: Locator };
  /** The head's Undo, while the record offers it (F14.1). */
  readonly undo: Locator;
  readonly body: Locator;
  readonly summary: Locator;
  readonly document: Locator;
  readonly blocks: Locator;
  readonly settled: Locator;
  readonly settledLines: Locator;
  readonly writing: Locator;
  readonly empty: Locator;
  readonly failed: Locator;
  /** The item alone (F99), which `TimelinePage.item` reads within. */
  readonly alone: Locator;
  /** A registered document's body while it awaits its read. */
  readonly unread: Locator;
  /** The strip under the head while the document is Pilot's (F28.9). */
  readonly strip: { root: Locator; text: Locator; link: Locator; stop: Locator };
  /** The foot's Cancel of a document a run of Pilot's put to the person (F28.9): its line, the line's links, its button. */
  readonly cancel: { line: Locator; links: Locator; button: Locator };
  readonly foot: Locator;
  readonly done: Locator;
  readonly doneTime: Locator;
  readonly send: Locator;
  readonly reviewed: Locator;
  /** The body's attachments' chips. */
  readonly attachments: Locator;
  /** The box of Pilot's questions to the writer and the reply (F52.2), which flashes when gone to. */
  readonly clarificationBox: Locator;
  /** Its sections, one per pass that asked. */
  readonly clarifications: Locator;
  /** An open archive question's Archive and Keep, in its block's place (F5.6). */
  readonly archiveQuestion: { archive: Locator; keep: Locator };
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
    this.documentLink = this.root.getByTestId('overlay.document-link');
    this.materialLinks = this.root.getByTestId('overlay.material-link');
    this.project = this.root.getByTestId('overlay.project');
    this.role = this.root.getByTestId('overlay.role');
    this.step = this.root.getByTestId('overlay.step');
    this.segments = this.head.getByTestId('timeline.segment');
    this.unsent = this.head.getByTestId('timeline.item.unsent');
    this.doneChip = this.root.getByTestId('overlay.done-chip');
    this.edited = this.head.getByTestId('timeline.item.edited');
    this.editedTime = this.head.getByTestId('timeline.item.edited.time');
    this.maximize = this.root.getByTestId('overlay.maximize');
    this.close = this.root.getByTestId('overlay.close');
    this.discuss = this.head.getByTestId('overlay.discuss');
    this.job = {
      root: this.head.getByTestId('overlay.job'),
      pulse: this.head.getByTestId('overlay.job.pulse'),
      retry: this.head.getByTestId('overlay.job.retry'),
    };
    this.undo = this.head.getByTestId('overlay.undo');
    this.body = this.root.getByTestId('overlay.body');
    this.summary = this.root.getByTestId('overlay.summary');
    this.document = this.root.getByTestId('overlay.document');
    this.blocks = this.root.getByTestId('timeline.block');
    this.settled = this.root.getByTestId('timeline.settled');
    this.settledLines = this.root.getByTestId('timeline.settled.line');
    this.writing = this.root.getByTestId('timeline.writing');
    this.empty = this.root.getByTestId('overlay.empty');
    this.failed = this.root.getByTestId('overlay.failed');
    this.alone = this.root.getByTestId('item-alone');
    this.unread = this.root.getByTestId('overlay.unread');
    const strip = this.root.getByTestId('overlay.pilot-strip');
    this.strip = {
      root: strip,
      text: strip.getByTestId('overlay.pilot-strip.text'),
      link: strip.getByTestId('overlay.pilot-strip.link'),
      stop: strip.getByTestId('overlay.pilot-strip.stop'),
    };
    this.foot = this.root.getByTestId('overlay.foot');
    this.cancel = {
      line: this.foot.getByTestId('overlay.cancel.line'),
      links: this.foot.getByTestId('overlay.cancel.link'),
      button: this.foot.getByTestId('overlay.cancel'),
    };
    this.done = this.root.getByTestId('overlay.done');
    this.doneTime = this.root.getByTestId('overlay.done.time');
    this.send = this.foot.getByTestId('timeline.item.send');
    this.reviewed = this.root.getByTestId('overlay.reviewed');
    this.attachments = this.body.getByTestId('timeline.attachment');
    this.clarificationBox = this.body.getByTestId('overlay.clarification-box');
    this.clarifications = this.body.getByTestId('overlay.clarification');
    this.archiveQuestion = {
      archive: this.body.getByTestId('timeline.archive-question.archive'),
      keep: this.body.getByTestId('timeline.archive-question.keep'),
    };
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
    const reads = Promise.all([this.read('project.timeline'), this.read('overlay.document')]);
    await this.page.goto(documentAddress(projectId, documentId));
    await reads;
  }

  /** The next read of the scope, done. */
  private read(scope: string) {
    return waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === scope && event.phase === 'ready' && event.metadata?.status !== 'aborted',
    );
  }

  /** Opens the project's handbook, or its project document, at its address, once its project's timeline and it are read. */
  async openProjectDocument(projectId: string, role: 'handbook' | 'draft'): Promise<void> {
    const reads = Promise.all([this.read('project.timeline'), this.read(`overlay.${role}`)]);
    await this.page.goto(role === 'handbook' ? handbookAddress(projectId) : projectDocumentAddress(projectId));
    await reads;
  }

  /** A block in the body, by its id. */
  blockAt(blockId: string) {
    return blockParts(this.page, this.root.locator(`[data-testid="timeline.block"][data-block-id="${blockId}"]`));
  }

  /**
   * The section of the pass that asked the writer `nth` (F52.2): its head, its stamp and the reply's,
   * its questions, each by its block's id with its words, its part of the reply and that the reply
   * is awaited, and the reply whole.
   */
  clarification(nth = 0) {
    const root = this.clarifications.nth(nth);
    const questions = root.getByTestId('overlay.clarification.question');
    return {
      root,
      head: root.getByTestId('overlay.clarification.head'),
      time: root.getByTestId('overlay.clarification.time'),
      replied: root.getByTestId('overlay.clarification.replied'),
      questions,
      question: (blockId: string) => {
        const question = root.locator(`[data-testid="overlay.clarification.question"][data-block="${blockId}"]`);
        return {
          root: question,
          block: question.getByTestId('overlay.clarification.block'),
          text: question.getByTestId('overlay.clarification.text'),
          reply: question.getByTestId('overlay.clarification.reply'),
          awaited: question.getByTestId('overlay.clarification.awaited'),
        };
      },
      /** The reply whole, under the questions, where it did not keep the headings asked for. */
      reply: root.locator(':scope > [data-testid="overlay.clarification.reply"]'),
      /** Every reply in the section, a question's part or the whole. */
      replies: root.getByTestId('overlay.clarification.reply'),
    };
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

/** The address under a document's of the box of Pilot's questions to its writer and the reply (F52.2). */
export function clarificationAddress(projectId: string, documentId: string): string {
  return `${documentAddress(projectId, documentId)}/clarification`;
}

/** The project's handbook's address under its project's (F129.4). */
export function handbookAddress(projectId: string): string {
  return `/projects/${projectId}/handbook`;
}

/** The project document's address under its project's (F37.4). */
export function projectDocumentAddress(projectId: string): string {
  return `/projects/${projectId}/project-document`;
}
