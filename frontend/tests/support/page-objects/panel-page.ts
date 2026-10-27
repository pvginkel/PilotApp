import type { Locator, Page } from '@playwright/test';
import type { FormTestEvent, UiStateTestEvent } from '@/lib/test/test-events';
import { waitTestEvent } from '../helpers';
import { blockParts } from './timeline-page';

/** A row of the Documents tab: its title and the line under it. */
interface PanelRow {
  root: Locator;
  title: Locator;
  sub: Locator;
}

/**
 * The side panel (F38.1): its head with the Documents tab, the tab's count and the close cross;
 * the Documents tab (F37) with the project document, the attachments, a batch of several under its
 * folder, and the timeline's documents and reviews, each a row with its title and the line under
 * it, "None yet" where a list is empty, and the line in the lists' place where the tab's read failed.
 * A draft's has the Draft tab in the Chat tab's place (F46.3): the draft's title, its text and its
 * asks, Pilot's dots, the foot, "Empty", and the line where its read failed.
 */
export class PanelPage {
  readonly root: Locator;
  readonly head: Locator;
  /** The tabs in the head, in their order. */
  readonly tabs: Locator;
  readonly draftTab: Locator;
  readonly documentsTab: Locator;
  readonly count: Locator;
  readonly close: Locator;
  readonly body: Locator;
  /** The lists' headings. */
  readonly headings: Locator;
  readonly projectDocument: PanelRow;
  /** Every attachment's row, a batch's files included, in their order. */
  readonly attachments: Locator;
  readonly noAttachments: Locator;
  readonly batches: Locator;
  /** The timeline's documents and reviews, in their order. */
  readonly documents: Locator;
  readonly noDocuments: Locator;
  /** What stands in the lists' place where the tab's read failed. */
  readonly failed: Locator;
  /** A draft's Draft tab: its text, and what stands in its place. */
  readonly draft: {
    root: Locator;
    title: Locator;
    /** Its prose, part by part. */
    prose: Locator;
    /** Its links to a document Pilot attached. */
    links: Locator;
    blocks: Locator;
    writing: Locator;
    foot: Locator;
    empty: Locator;
    failed: Locator;
  };

  constructor(private readonly page: Page) {
    this.root = page.getByTestId('panel');
    this.head = this.root.getByTestId('panel.head');
    this.tabs = this.head.getByRole('tab');
    this.draftTab = this.head.getByTestId('panel.tab.draft');
    this.documentsTab = this.head.getByTestId('panel.tab.documents');
    this.count = this.head.getByTestId('panel.tab.documents.count');
    this.close = this.head.getByTestId('panel.close');
    this.body = this.root.getByTestId('panel.body');
    this.headings = this.body.locator('h3');
    this.projectDocument = rowOf(this.body.getByTestId('panel.project-document'));
    this.attachments = this.body.getByTestId('panel.attachment');
    this.noAttachments = this.body.getByTestId('panel.attachments.none');
    this.batches = this.body.getByTestId('panel.batch');
    this.documents = this.body.getByTestId('panel.document');
    this.noDocuments = this.body.getByTestId('panel.timeline-documents.none');
    this.failed = this.body.getByTestId('panel.documents.failed');
    const draft = this.body.getByTestId('panel.draft');
    this.draft = {
      root: draft,
      title: draft.getByTestId('panel.draft.title'),
      prose: draft.locator(':scope > .prose').filter({ hasNot: page.getByTestId('panel.draft.title') }),
      links: draft.getByTestId('panel.draft.link'),
      blocks: draft.getByTestId('timeline.block'),
      writing: this.body.getByTestId('timeline.writing'),
      foot: draft.getByTestId('panel.draft.foot'),
      empty: this.body.getByTestId('panel.draft.empty'),
      failed: this.body.getByTestId('panel.draft.failed'),
    };
  }

  /** An ask of the draft in the Draft tab, by its local id. */
  draftBlock(blockId: string) {
    return blockParts(this.page, this.draft.root.locator(`[data-testid="timeline.block"][data-block-id="${blockId}"]`));
  }

  /** The next read of the Draft tab's text, done. */
  readDraft(): Promise<UiStateTestEvent> {
    return waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === 'panel.draft' && event.phase === 'ready' && event.metadata?.status !== 'aborted',
    );
  }

  /** The server's next answer taking an answer (`answer`) or an action's Done (`done`) given in the Draft tab. */
  answered(act: 'answer' | 'done'): Promise<FormTestEvent> {
    return waitTestEvent<FormTestEvent>(this.page, 'form', (event) => event.formId === `draft.${act}` && event.phase === 'success');
  }

  attachment(attachmentId: string): PanelRow {
    return rowOf(this.body.locator(`[data-testid="panel.attachment"][data-attachment-id="${attachmentId}"]`));
  }

  /** A batch of several files: its folder's row, and its files' rows. */
  batch(batch: number): { root: Locator; head: PanelRow; files: Locator } {
    const root = this.body.locator(`[data-testid="panel.batch"][data-batch="${batch}"]`);
    return { root, head: rowOf(root.getByTestId('panel.batch.head')), files: root.getByTestId('panel.attachment') };
  }

  /** A document or review of the timeline, by its item's id; its state in `data-state`. */
  document(itemId: string): PanelRow {
    return rowOf(this.body.locator(`[data-testid="panel.document"][data-item-id="${itemId}"]`));
  }

  /** The next read of the tab's lists, done. */
  read(): Promise<UiStateTestEvent> {
    return waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === 'panel.documents' && event.phase === 'ready' && event.metadata?.status !== 'aborted',
    );
  }
}

function rowOf(root: Locator): PanelRow {
  return { root, title: root.getByTestId('panel.row.title'), sub: root.getByTestId('panel.row.sub') };
}

/** Whether the element is what the window shows at its centre: nothing lies over it there. */
export function isOnTop(locator: Locator): Promise<boolean> {
  return locator.evaluate((element) => {
    const box = element.getBoundingClientRect();
    return element.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
  });
}
