import type { Locator, Page } from '@playwright/test';
import { waitForUiState } from '../helpers';

/** A project's head (F2), the plan popover its step button opens (F3) and the plan's notes (F2.7). */
export class ProjectHeadPage {
  readonly root: Locator;
  readonly name: Locator;
  readonly ticket: Locator;
  readonly repo: Locator;
  readonly draft: Locator;
  readonly archived: Locator;
  readonly finished: Locator;
  readonly autopilot: Locator;
  readonly step: Locator;
  readonly ring: Locator;
  readonly plan: Locator;
  readonly planHeading: Locator;
  readonly planSteps: Locator;
  readonly members: Locator;
  readonly notesButton: Locator;
  readonly notes: Locator;

  constructor(private readonly page: Page) {
    this.root = page.getByTestId('project.head');
    this.name = page.getByTestId('project.name');
    this.ticket = page.getByTestId('project.ticket');
    this.repo = page.getByTestId('project.repo');
    this.draft = page.getByTestId('project.draft');
    this.archived = page.getByTestId('project.archived');
    this.finished = page.getByTestId('project.finished');
    this.autopilot = page.getByTestId('project.autopilot');
    this.step = page.getByTestId('project.step');
    this.ring = page.getByTestId('project.step.ring');
    this.plan = page.getByTestId('project.plan');
    this.planHeading = page.getByTestId('project.plan.heading');
    this.planSteps = page.getByTestId('project.plan.step');
    this.members = page.getByTestId('project.members');
    this.notesButton = page.getByTestId('project.notes.button');
    this.notes = page.getByTestId('project.notes');
  }

  /** Opens a project at its own address, once its head is read. */
  async open(id: string): Promise<void> {
    await this.page.goto(`/projects/${id}`);
    await waitForUiState(this.page, 'project.head', 'ready');
  }

  /** The plan popover's step titled `title`, with its notes icon and the notes it lists. */
  planStep(title: string): { root: Locator; notesButton: Locator; notes: Locator } {
    const root = this.planSteps.filter({ has: this.page.getByTestId('project.plan.step.title').getByText(title, { exact: true }) });
    return {
      root,
      notesButton: root.getByTestId('project.plan.step.notes-button'),
      notes: root.getByTestId('project.plan.step.notes'),
    };
  }
}
