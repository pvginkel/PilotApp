import type { Locator, Page } from '@playwright/test';

/**
 * The dashboard (F160), the second screen beside Projects: its screen, and the reads of its module,
 * which the page loads at its first opening (F160.2).
 */
export class DashboardPage {
  readonly screen: Locator;

  constructor(private readonly page: Page) {
    this.screen = page.getByTestId('dashboard');
  }

  /**
   * Records the page's reads of the dashboard's module from the call on, the dev server's source or
   * a build's chunk; read by the answer.
   */
  moduleReads(): () => number {
    let reads = 0;
    this.page.on('request', (request) => {
      if (/\/dashboard-screen(\.tsx|-[\w-]+\.js)$/.test(new URL(request.url()).pathname)) reads += 1;
    });
    return () => reads;
  }
}
