import type { Locator, Page } from '@playwright/test';
import type { FormTestEvent } from '@/lib/test/test-events';
import { waitForUiState, waitTestEvent } from '../helpers';

type Act = 'join' | 'leave' | 'finish' | 'reopen' | 'archive' | 'bring-back';
type Ask = Exclude<Act, 'join' | 'leave'>;

/**
 * A project's head (F2), auto pilot's switch, its dialog and its warning triangle (F4), the plan popover its
 * step button opens (F3), Discuss and its unread dot (F2.3, F39.2, F43), the Documents button
 * (F2.3), the handbook's button (F129.4), the plan's notes (F2.7), the members and the count they
 * fold to in a tight head (F2.5), a draft's Create project and
 * draft-panel toggle (F46.2, F48), and the project's menu and the dialogs it opens (F2.4).
 */
export class ProjectHeadPage {
  readonly root: Locator;
  readonly name: Locator;
  readonly ticket: Locator;
  readonly repo: Locator;
  readonly draft: Locator;
  readonly archived: Locator;
  readonly finished: Locator;
  readonly autopilot: Locator;
  readonly autopilotWarning: Locator;
  /** The switch's question as it turns on while confirmations it would take are open (F4.2). */
  readonly autopilotDialog: { root: Locator; backdrop: Locator; title: Locator; lines: Locator; note: Locator; no: Locator; yes: Locator };
  readonly step: Locator;
  readonly ring: Locator;
  readonly plan: Locator;
  readonly planHeading: Locator;
  readonly planSteps: Locator;
  readonly members: Locator;
  readonly memberAvatars: Locator;
  readonly membersMore: Locator;
  readonly documentsButton: Locator;
  readonly discussButton: Locator;
  readonly discussDot: Locator;
  readonly handbookButton: Locator;
  readonly notesButton: Locator;
  readonly notes: Locator;
  readonly draftPanelButton: Locator;
  readonly createButton: Locator;
  readonly menuButton: Locator;
  readonly menu: Locator;
  readonly menuItems: Locator;

  constructor(private readonly page: Page) {
    this.root = page.getByTestId('project.head');
    this.name = page.getByTestId('project.name');
    this.ticket = page.getByTestId('project.ticket');
    this.repo = page.getByTestId('project.repo');
    this.draft = page.getByTestId('project.draft');
    this.archived = page.getByTestId('project.archived');
    this.finished = page.getByTestId('project.finished');
    this.autopilot = page.getByTestId('project.autopilot');
    this.autopilotWarning = page.getByTestId('project.autopilot.warning');
    this.autopilotDialog = {
      root: page.getByTestId('project.autopilot-dialog'),
      backdrop: page.getByTestId('project.autopilot-dialog.backdrop'),
      title: page.getByTestId('project.autopilot-dialog.title'),
      lines: page.getByTestId('project.autopilot-dialog.line'),
      note: page.getByTestId('project.autopilot-dialog.note'),
      no: page.getByTestId('project.autopilot-dialog.no'),
      yes: page.getByTestId('project.autopilot-dialog.yes'),
    };
    this.step = page.getByTestId('project.step');
    this.ring = page.getByTestId('project.step.ring');
    this.plan = page.getByTestId('project.plan');
    this.planHeading = page.getByTestId('project.plan.heading');
    this.planSteps = page.getByTestId('project.plan.step');
    this.members = page.getByTestId('project.members');
    this.membersMore = page.getByTestId('project.members.more');
    this.memberAvatars = this.members.locator('.avatar:not([data-testid="project.members.more"])');
    this.documentsButton = page.getByTestId('project.documents');
    this.discussButton = page.getByTestId('project.discuss');
    this.discussDot = this.discussButton.getByTestId('project.discuss.unread');
    this.handbookButton = page.getByTestId('project.handbook');
    this.notesButton = page.getByTestId('project.notes.button');
    this.notes = page.getByTestId('project.notes');
    this.draftPanelButton = page.getByTestId('project.draft-panel');
    this.createButton = page.getByTestId('project.create');
    this.menuButton = page.getByTestId('project.menu.button');
    this.menu = page.getByTestId('project.menu');
    this.menuItems = this.menu.getByRole('menuitem');
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

  /** Presses Create project, done once the head is read again: the open project's. */
  async create(): Promise<void> {
    const done = waitTestEvent<FormTestEvent>(this.page, 'form', (event) => event.formId === 'project.create' && event.phase === 'success');
    await this.createButton.click();
    await done;
  }

  menuItem(act: Act): Locator {
    return this.page.getByTestId(`project.menu.${act}`);
  }

  /** Chooses `act` in the project's menu; Join and Leave are done once the head and the list show it. */
  async choose(act: Act): Promise<void> {
    await this.menuButton.click();
    const done = act === 'join' || act === 'leave' ? this.written(act) : undefined;
    await this.menuItem(act).click();
    await done;
  }

  /** Chooses `ask` in the project's menu with the keyboard: Enter on the menu's button, then on the item. */
  async chooseWithKeys(ask: Ask): Promise<void> {
    await this.menuButton.focus();
    await this.page.keyboard.press('Enter');
    await this.menuItem(ask).focus();
    await this.page.keyboard.press('Enter');
  }

  /** The dialog the menu opens to ask before `ask`. */
  dialog(ask: Ask): { root: Locator; backdrop: Locator; title: Locator; lines: Locator; note: Locator; cancel: Locator; confirm: Locator } {
    const id = `project.${ask}-dialog`;
    return {
      root: this.page.getByTestId(id),
      backdrop: this.page.getByTestId(`${id}.backdrop`),
      title: this.page.getByTestId(`${id}.title`),
      lines: this.page.getByTestId(`${id}.line`),
      note: this.page.getByTestId(`${id}.note`),
      cancel: this.page.getByTestId(`${id}.cancel`),
      confirm: this.page.getByTestId(`${id}.confirm`),
    };
  }

  /** Confirms the dialog open for `ask`, done once the head and the list show it. */
  async confirm(ask: Ask): Promise<void> {
    const done = this.written(ask);
    await this.dialog(ask).confirm.click();
    await done;
  }

  private written(act: Act): Promise<FormTestEvent> {
    return waitTestEvent<FormTestEvent>(this.page, 'form', (event) => event.formId === `project.${act}` && event.phase === 'success');
  }
}
