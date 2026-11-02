import type { Locator, Page } from '@playwright/test';

/** A tab by its key: a draft's Chat is `timeline`, the definition chat standing in the timeline's place. */
type PhoneTabKey = 'timeline' | 'chat' | 'plan' | 'documents' | 'draft';

/**
 * A project's screen on a phone (F98.3): the tabs at the bottom, each by its key, the Chat tab's
 * unread dot and the Documents tab's count; the page between the head and the tabs; and the Plan
 * tab's page (F3.7), its heading, its steps and the line while it has none.
 */
export class PhoneTabsPage {
  readonly root: Locator;
  /** Every tab, in their order. */
  readonly tabs: Locator;
  readonly chatDot: Locator;
  readonly count: Locator;
  /** What stands between the head and the tabs. */
  readonly page: Locator;
  readonly plan: { root: Locator; heading: Locator; steps: Locator; none: Locator };

  constructor(page: Page) {
    this.root = page.getByTestId('project.tabs');
    this.tabs = this.root.getByRole('tab');
    this.chatDot = this.root.getByTestId('project.tabs.chat.unread');
    this.count = this.root.getByTestId('project.tabs.documents.count');
    this.page = page.getByTestId('project.phone-page');
    const plan = page.getByTestId('project.plan-page');
    this.plan = {
      root: plan,
      heading: plan.getByTestId('project.plan-page.heading'),
      steps: plan.getByTestId('project.plan.step'),
      none: plan.getByTestId('project.plan-page.none'),
    };
  }

  tab(key: PhoneTabKey): Locator {
    return this.root.getByTestId(`project.tabs.${key}`);
  }

  /** The Plan tab's step titled `title`, with its notes icon and the notes it lists. */
  planStep(title: string): { root: Locator; notesButton: Locator; notes: Locator } {
    const root = this.plan.steps.filter({ has: this.plan.root.page().getByTestId('project.plan.step.title').getByText(title, { exact: true }) });
    return {
      root,
      notesButton: root.getByTestId('project.plan.step.notes-button'),
      notes: root.getByTestId('project.plan.step.notes'),
    };
  }
}
