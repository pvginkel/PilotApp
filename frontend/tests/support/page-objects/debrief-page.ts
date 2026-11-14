import type { Locator, Page } from '@playwright/test';
import { sessionLogAddress } from './session-log-page';

/**
 * A done work item's debrief in the overlay (F26.9), at its own address under the session log's:
 * off a phone the session log's popover over the tab showing, a dialog, on a phone a view. Its
 * head with "Debrief" over the item's title and the time its turn ended, off a phone the cross, on
 * a phone the arrow back; its body the stage session's debrief, as prose, or "The debrief did not
 * load".
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
  }
}

/** A done work item's debrief's address, under its session log's (F26.9). */
export function debriefAddress(projectId: string, sessionId: string): string {
  return `${sessionLogAddress(projectId, sessionId)}/debrief`;
}
