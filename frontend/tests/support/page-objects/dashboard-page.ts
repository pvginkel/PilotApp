import type { Locator, Page } from '@playwright/test';

/** A dashboard address of a view tab and its view's state, after the app's path (F160.3). */
export const dashboardAddress = (state: string, tab = 't1') => `#dash/${tab}/${state}`;

/**
 * The dashboard (F160), the second screen beside Projects: its screen, and the reads of its module,
 * which the page loads at its first opening (F160.2); the global toolbar and the view's tab at its
 * left, the banner under it, the main area, which scrolls, and the view's card: the legend, the
 * headings' row, the All row and a row per value of the By, each its label, its time where it has
 * one, and a figure per measure; the medians, and the cut past 40 rows.
 */
export class DashboardPage {
  readonly screen: Locator;
  readonly toolbar: Locator;
  readonly tab: Locator;
  readonly banner: Locator;
  readonly bannerText: Locator;
  readonly retry: Locator;
  readonly closeBanner: Locator;
  readonly main: Locator;
  readonly card: Locator;
  readonly legend: Locator;
  readonly legendValues: Locator;
  readonly byHeading: Locator;
  readonly measureHeadings: Locator;
  readonly all: Locator;
  readonly allValues: Locator;
  readonly rows: Locator;
  readonly labels: Locator;
  readonly times: Locator;
  readonly medians: Locator;
  readonly empty: Locator;
  readonly cut: Locator;

  constructor(private readonly page: Page) {
    this.screen = page.getByTestId('dashboard');
    this.toolbar = page.getByTestId('dashboard.toolbar');
    this.tab = page.getByTestId('dashboard.tab');
    this.banner = page.getByTestId('dashboard.banner');
    this.bannerText = page.getByTestId('dashboard.banner.text');
    this.retry = page.getByTestId('dashboard.banner.retry');
    this.closeBanner = page.getByTestId('dashboard.banner.close');
    this.main = page.getByTestId('dashboard.main');
    this.card = page.getByTestId('dashboard.card');
    this.legend = page.getByTestId('dashboard.legend');
    this.legendValues = page.getByTestId('dashboard.legend.value');
    this.byHeading = page.getByTestId('dashboard.heads.by');
    this.measureHeadings = page.getByTestId('dashboard.heads.measure');
    this.all = page.getByTestId('dashboard.all');
    this.allValues = page.getByTestId('dashboard.all.value');
    this.rows = page.getByTestId('dashboard.row');
    this.labels = page.getByTestId('dashboard.row.label');
    this.times = page.getByTestId('dashboard.row.at');
    this.medians = page.getByTestId('dashboard.median');
    this.empty = page.getByTestId('dashboard.empty');
    this.cut = page.getByTestId('dashboard.cut');
  }

  /** The row whose label is `label`. */
  row(label: string): Locator {
    return this.rows.filter({ has: this.page.getByTestId('dashboard.row.label').getByText(label, { exact: true }) });
  }

  /** A row's figures, one per measure, in the view's order. */
  values(row: Locator): Locator {
    return row.getByTestId('dashboard.row.value');
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

  /** The states the page asks the rows of from the call on, as it sends them; read by the answer. */
  rowsReads(): () => string[] {
    return this.reads('/api/dashboard/rows');
  }

  /** The states the page asks the normal form of from the call on; read by the answer. */
  addressReads(): () => string[] {
    return this.reads('/api/dashboard/address');
  }

  /** The page's address moved to `hash` in place, as a link in the page moves it. */
  async go(hash: string): Promise<void> {
    await this.page.evaluate((to) => (location.hash = to), hash);
  }

  /** The main area's scroll. */
  scrollTop(): Promise<number> {
    return this.main.evaluate((main) => main.scrollTop);
  }

  private reads(path: string): () => string[] {
    const states: string[] = [];
    this.page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname === path) states.push(url.searchParams.get('state') ?? '');
    });
    return () => states;
  }
}
