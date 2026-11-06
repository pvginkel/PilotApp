import type { Locator, Page } from '@playwright/test';

/**
 * The desktop's tab line (F28.8), the project head's last row while a document is open: its first
 * tab, the timeline or a draft's chat; a tab per open document, by its key in `data-tab` —
 * `document <item>`, `attachment <attachment>`, `handbook`, `project-document` — with its title,
 * the button that shows it and its cross; and *Close all*. The tab showing is `aria-selected`.
 */
export class DocTabsPage {
  readonly root: Locator;
  readonly first: Locator;
  readonly tabs: Locator;
  readonly titles: Locator;
  readonly closeAll: Locator;

  constructor(page: Page) {
    this.root = page.getByTestId('doc-tabs');
    this.first = this.root.getByTestId('doc-tabs.first');
    this.tabs = this.root.getByTestId('doc-tabs.tab');
    this.titles = this.tabs.getByTestId('doc-tabs.tab.title');
    this.closeAll = this.root.getByTestId('doc-tabs.close-all');
  }

  /** A tab by its key. */
  tab(key: string) {
    const root = this.root.locator(`[data-testid="doc-tabs.tab"][data-tab="${key}"]`);
    return {
      root,
      show: root.getByTestId('doc-tabs.tab.show'),
      title: root.getByTestId('doc-tabs.tab.title'),
      close: root.getByTestId('doc-tabs.tab.close'),
    };
  }

  /** An item's document's tab. */
  document(itemId: string) {
    return this.tab(`document ${itemId}`);
  }

  /** An attachment's tab. */
  attachment(attachmentId: string) {
    return this.tab(`attachment ${attachmentId}`);
  }

  /** The keys of the open tabs, in the line's order. */
  async keys(): Promise<string[]> {
    return this.tabs.evaluateAll((tabs) => tabs.map((tab) => tab.getAttribute('data-tab')!));
  }
}
