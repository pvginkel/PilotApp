import type { Locator, Page } from '@playwright/test';
import { waitForUiState } from '../helpers';

type Group = 'others' | 'finished';

/** The project list in the side column (F1), and the archived projects it opens (D2). */
export class ProjectListPage {
  readonly head: Locator;
  readonly menuButton: Locator;
  readonly menu: Locator;
  readonly archivedItem: Locator;
  readonly mine: Locator;
  readonly tabs: Locator;
  readonly archived: Locator;
  readonly archivedBack: Locator;
  readonly empty: Locator;

  constructor(private readonly page: Page) {
    this.head = page.getByTestId('projects.head');
    this.menuButton = page.getByTestId('projects.menu.button');
    this.menu = page.getByTestId('projects.menu');
    this.archivedItem = page.getByTestId('projects.menu.archived');
    this.mine = page.getByTestId('projects.mine');
    this.tabs = page.getByTestId('projects.tab');
    this.archived = page.getByTestId('projects.archived');
    this.archivedBack = page.getByTestId('projects.archived.back');
    this.empty = page.getByTestId('projects.empty');
  }

  /** Opens a project at its own address, once the person and the list are read. */
  async open(id: string): Promise<void> {
    await this.page.goto(`/projects/${id}`);
    await waitForUiState(this.page, 'projects.list', 'ready');
  }

  /** The tab named `name`, wherever it shows. */
  tab(name: string, within: Locator = this.page.getByTestId('shell.side')): Locator {
    return within
      .getByTestId('projects.tab')
      .filter({ has: this.page.getByTestId('projects.tab.name').getByText(name, { exact: true }) });
  }

  group(group: Group): { root: Locator; toggle: Locator; count: Locator } {
    return {
      root: this.page.getByTestId(`projects.group.${group}`),
      toggle: this.page.getByTestId(`projects.group.${group}.toggle`),
      count: this.page.getByTestId(`projects.group.${group}.count`),
    };
  }
}
