import type { Locator, Page } from '@playwright/test';
import type { FormTestEvent } from '@/lib/test/test-events';
import { waitForUiState, waitTestEvent } from '../helpers';

type Group = 'others' | 'finished';

/**
 * The project list in the side column (F1), a tab's status icon, the pause (F1.3, F141), the plus
 * that starts a new project (F46.1), and the archived projects it opens (D012).
 */
export class ProjectListPage {
  readonly head: Locator;
  readonly newProject: Locator;
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
    this.newProject = page.getByTestId('projects.new');
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

  /** Resolves once the server took the plus's new project, with the draft's id as `fields.project`. */
  created(): Promise<FormTestEvent> {
    return waitTestEvent<FormTestEvent>(this.page, 'form', (event) => event.formId === 'projects.new' && event.phase === 'success');
  }

  /** The tab named `name`, wherever it shows. */
  tab(name: string, within: Locator = this.page.getByTestId('shell.side')): Locator {
    return within
      .getByTestId('projects.tab')
      .filter({ has: this.page.getByTestId('projects.tab.name').getByText(name, { exact: true }) });
  }

  /** The badge on the tab named `name` (F1.4). */
  badge(name: string): Locator {
    return this.tab(name).getByTestId('projects.tab.badge');
  }

  /** The status icon on the tab named `name` (F1.3): its glyph at rest, and the one under the pointer and the focus. */
  statusIcon(name: string, within?: Locator): { root: Locator; rest: Locator; hover: Locator } {
    const root = this.tab(name, within).getByTestId('projects.tab.status-icon');
    return {
      root,
      rest: root.getByTestId('projects.tab.status-icon.rest'),
      hover: root.getByTestId('projects.tab.status-icon.hover'),
    };
  }

  /** Resolves once the pause or the resume a tab's icon asked for project `id` is written and the list read again (F141.2). */
  written(id: string, kind: 'paused' | 'resumed'): Promise<FormTestEvent> {
    return waitTestEvent<FormTestEvent>(
      this.page,
      'form',
      (event) => event.formId === 'projects.tab.pause' && event.phase === 'success' && event.fields?.project === id && event.fields.kind === kind,
    );
  }

  group(group: Group): { root: Locator; toggle: Locator; count: Locator } {
    return {
      root: this.page.getByTestId(`projects.group.${group}`),
      toggle: this.page.getByTestId(`projects.group.${group}.toggle`),
      count: this.page.getByTestId(`projects.group.${group}.count`),
    };
  }
}
