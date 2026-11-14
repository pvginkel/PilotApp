import type { Locator, Page } from '@playwright/test';
import { sessionLogAddress } from './session-log-page';

/**
 * A done work item's debrief in the overlay (F26.9), at its own address under the session log's:
 * off a phone the session log's popover over the tab showing, a dialog, on a phone a view. Its
 * head with "Debrief" over the item's title and the time its turn ended, and Full debrief, off a
 * phone the cross, on a phone the arrow back; its body the stage session's debrief, as prose, or
 * "The debrief did not load". The full debrief, at its address under the debrief's (F26.10), in
 * the same frame: "Full debrief" over the item's title, the arrow back to the debrief, off a phone
 * the cross too; its body the table of its sections, a row each, then the sections, each its name
 * and its entries, an entry's round line before it where it opens its round with its why.
 */
export class DebriefPage {
  readonly overlay: Locator;
  readonly head: Locator;
  readonly title: Locator;
  readonly sub: Locator;
  readonly item: Locator;
  /** The time the item's turn ended. */
  readonly ended: Locator;
  readonly close: Locator;
  readonly back: Locator;
  readonly body: Locator;
  /** The debrief's words, as prose. */
  readonly text: Locator;
  readonly failed: Locator;
  /** The debrief's way to the full debrief, in its head. */
  readonly full: Locator;
  /** The full debrief's table: a row per section, its name, its rounds and its time. */
  readonly index: Locator;
  readonly rows: Locator;
  readonly rowNames: Locator;
  readonly rowRounds: Locator;
  readonly rowTimes: Locator;
  /** The full debrief's sections, each its name over its entries. */
  readonly sections: Locator;
  readonly sectionNames: Locator;

  constructor(page: Page) {
    // A dialog, never a tab, which it may lie over.
    this.overlay = page.locator('[data-testid="overlay"][role="dialog"]');
    this.head = this.overlay.getByTestId('overlay.head');
    this.title = this.overlay.getByTestId('overlay.title');
    this.sub = this.overlay.getByTestId('overlay.sub');
    this.item = this.overlay.getByTestId('debrief.item');
    this.ended = this.overlay.getByTestId('debrief.ended');
    this.close = this.overlay.getByTestId('overlay.close');
    this.back = this.overlay.getByTestId('overlay.back');
    this.body = this.overlay.getByTestId('overlay.body');
    this.text = this.overlay.getByTestId('debrief');
    this.failed = this.overlay.getByTestId('overlay.failed');
    this.full = this.overlay.getByTestId('debrief.full');
    this.index = this.overlay.getByTestId('debrief.index');
    this.rows = this.index.getByTestId('debrief.index.row');
    this.rowNames = this.index.getByTestId('debrief.index.name');
    this.rowRounds = this.index.getByTestId('debrief.index.rounds');
    this.rowTimes = this.index.getByTestId('debrief.index.time');
    this.sections = this.overlay.getByTestId('debrief.section');
    this.sectionNames = this.sections.getByTestId('debrief.section.name');
  }

  /** A section's entries, in the order given. */
  entries(section: Locator): Locator {
    return section.getByTestId('debrief.entry');
  }

  /** A section's lines in their order, by their kind: `entry`, or `round` for a round's why. */
  async lineKinds(section: Locator): Promise<string[]> {
    return section.locator('ol > li').evaluateAll((lines) => lines.map((line) => (line.classList.contains('db-round') ? 'round' : 'entry')));
  }
}

/** A done work item's debrief's address, under its session log's (F26.9). */
export function debriefAddress(projectId: string, sessionId: string): string {
  return `${sessionLogAddress(projectId, sessionId)}/debrief`;
}

/** A done work item's full debrief's address, under its debrief's (F26.10). */
export function fullDebriefAddress(projectId: string, sessionId: string): string {
  return `${debriefAddress(projectId, sessionId)}/full`;
}
