import type { Locator, Page } from '@playwright/test';

/** A dashboard address of a view tab and its view's state, after the app's path (F160.3). */
export const dashboardAddress = (state: string, tab = 't1') => `#dash/${tab}/${state}`;

/**
 * The dashboard (F160), the second screen beside Projects: its screen, and the reads of its module,
 * which the page loads at its first opening (F160.2); the line of view tabs, Close all and the new
 * view's copy-plus (F161.2); the new tab's panel, its find, Start from scratch and its two lists of
 * views (F161.4); the global toolbar, the one view's tab at its left, the time and its picker
 * (F162.2), Reset and Save view, its pane asking a name (F161.5), the banner under it, the main
 * area, which scrolls; the scope above the card, the drill path and its segments, each a level's
 * kind and value (F162.3), the chips, each its sign, its words and its ×, the filter picker and a
 * dimension's pane, its search, its values, Is or Is not, Filter or Mark, Add or Apply, Add as quick
 * filter and its name, and Remove (F162.4); the quick filters' line under them, each its name, its
 * count, its amount and its ×, and the dialog its × asks (F162.6); and the view's card: its head, By
 * and its list, the presentation's Rows and Table, Color and its list, Relative, and the table's Copy
 * and CSV (F163.1 to F163.3, F163.7), each list's search, its groups and its entries, each its pick,
 * its count and its star, By's "n hidden"; the legend, the headings' row, the All row and a row per
 * value of the By, each its label, its time where it has one, and a figure per measure; the medians,
 * and the cut past 40 rows; the table, its headings, its All row and its rows, each its label, its
 * time and its cells.
 */
export class DashboardPage {
  readonly screen: Locator;
  readonly toolbar: Locator;
  readonly reset: Locator;
  readonly saveView: Locator;
  readonly savePane: Locator;
  readonly saveName: Locator;
  readonly saveNote: Locator;
  readonly save: Locator;
  readonly time: Locator;
  readonly timeWords: Locator;
  readonly timePicker: Locator;
  readonly from: Locator;
  readonly to: Locator;
  readonly apply: Locator;
  readonly month: Locator;
  readonly monthBefore: Locator;
  readonly monthAfter: Locator;
  readonly days: Locator;
  readonly ranges: Locator;
  readonly weeks: Locator;
  readonly timeFoot: Locator;
  readonly tab: Locator;
  readonly tabClose: Locator;
  readonly line: Locator;
  readonly lineTabs: Locator;
  readonly lineNames: Locator;
  readonly closeAll: Locator;
  readonly newView: Locator;
  readonly panel: Locator;
  readonly find: Locator;
  readonly scratch: Locator;
  readonly systemViews: Locator;
  readonly savedViews: Locator;
  readonly removeDialog: Locator;
  readonly banner: Locator;
  readonly bannerText: Locator;
  readonly retry: Locator;
  readonly closeBanner: Locator;
  readonly main: Locator;
  readonly scope: Locator;
  readonly path: Locator;
  readonly pathSegments: Locator;
  readonly pathKinds: Locator;
  readonly pathValues: Locator;
  readonly chips: Locator;
  readonly addFilter: Locator;
  readonly filterDimensions: Locator;
  readonly pane: Locator;
  readonly paneSearch: Locator;
  readonly paneValues: Locator;
  readonly paneLabels: Locator;
  readonly paneAmounts: Locator;
  readonly paneIsNot: Locator;
  readonly paneMark: Locator;
  readonly paneApply: Locator;
  readonly paneRemove: Locator;
  readonly paneQuickFilter: Locator;
  readonly quickFilterName: Locator;
  readonly quickFilterSave: Locator;
  readonly quickFilters: Locator;
  readonly quickFilterRemoveDialog: Locator;
  readonly card: Locator;
  readonly cardHead: Locator;
  readonly by: Locator;
  readonly byWords: Locator;
  readonly byMore: Locator;
  readonly color: Locator;
  readonly colorWords: Locator;
  readonly rowsPresentation: Locator;
  readonly tablePresentation: Locator;
  readonly relative: Locator;
  readonly copy: Locator;
  readonly csv: Locator;
  readonly table: Locator;
  readonly tableHeads: Locator;
  readonly tableAll: Locator;
  readonly tableRows: Locator;
  readonly tableLabels: Locator;
  readonly tableTimes: Locator;
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
    this.reset = page.getByTestId('dashboard.reset');
    this.saveView = page.getByTestId('dashboard.save-view');
    this.savePane = page.getByTestId('dashboard.save');
    this.saveName = page.getByTestId('dashboard.save.name');
    this.saveNote = page.getByTestId('dashboard.save.note');
    this.save = page.getByTestId('dashboard.save.save');
    this.time = page.getByTestId('dashboard.time');
    this.timeWords = page.getByTestId('dashboard.time.words');
    this.timePicker = page.getByTestId('dashboard.time-picker');
    this.from = page.getByTestId('dashboard.time-picker.from');
    this.to = page.getByTestId('dashboard.time-picker.to');
    this.apply = page.getByTestId('dashboard.time-picker.apply');
    this.month = page.getByTestId('dashboard.time-picker.month');
    this.monthBefore = page.getByTestId('dashboard.time-picker.before');
    this.monthAfter = page.getByTestId('dashboard.time-picker.after');
    this.days = page.getByTestId('dashboard.time-picker.day');
    this.ranges = page.getByTestId('dashboard.time-picker.range');
    this.weeks = page.getByTestId('dashboard.time-picker.week');
    this.timeFoot = page.getByTestId('dashboard.time-picker.foot');
    this.tab = page.getByTestId('dashboard.tab');
    this.tabClose = page.getByTestId('dashboard.tab.close');
    this.line = page.getByTestId('dashboard.tabs');
    this.lineTabs = page.getByTestId('dashboard.tabs.tab');
    this.lineNames = page.getByTestId('dashboard.tabs.tab.name');
    this.closeAll = page.getByTestId('dashboard.tabs.close-all');
    this.newView = page.getByTestId('dashboard.new');
    this.panel = page.getByTestId('dashboard.panel');
    this.find = page.getByTestId('dashboard.panel.find');
    this.scratch = page.getByTestId('dashboard.panel.scratch');
    this.systemViews = page.getByTestId('dashboard.panel.system');
    this.savedViews = page.getByTestId('dashboard.panel.saved');
    this.removeDialog = page.getByTestId('dashboard.panel.remove-dialog');
    this.banner = page.getByTestId('dashboard.banner');
    this.bannerText = page.getByTestId('dashboard.banner.text');
    this.retry = page.getByTestId('dashboard.banner.retry');
    this.closeBanner = page.getByTestId('dashboard.banner.close');
    this.main = page.getByTestId('dashboard.main');
    this.scope = page.getByTestId('dashboard.scope');
    this.path = page.getByTestId('dashboard.path');
    this.pathSegments = page.getByTestId('dashboard.path.segment');
    this.pathKinds = page.getByTestId('dashboard.path.kind');
    this.pathValues = page.getByTestId('dashboard.path.value');
    this.chips = page.getByTestId('dashboard.chip');
    this.addFilter = page.getByTestId('dashboard.add-filter');
    this.filterDimensions = page.getByTestId('dashboard.filter.dimension');
    this.pane = page.getByTestId('dashboard.pane');
    this.paneSearch = page.getByTestId('dashboard.pane.search');
    this.paneValues = page.getByTestId('dashboard.pane.value');
    this.paneLabels = page.getByTestId('dashboard.pane.value.label');
    this.paneAmounts = page.getByTestId('dashboard.pane.value.amount');
    this.paneIsNot = page.getByTestId('dashboard.pane.is-not');
    this.paneMark = page.getByTestId('dashboard.pane.mark');
    this.paneApply = page.getByTestId('dashboard.pane.apply');
    this.paneRemove = page.getByTestId('dashboard.pane.remove');
    this.paneQuickFilter = page.getByTestId('dashboard.pane.quick-filter');
    this.quickFilterName = page.getByTestId('dashboard.pane.quick-filter.name');
    this.quickFilterSave = page.getByTestId('dashboard.pane.quick-filter.save');
    this.quickFilters = page.getByTestId('dashboard.quick-filters');
    this.quickFilterRemoveDialog = page.getByTestId('dashboard.quick-filter.remove-dialog');
    this.card = page.getByTestId('dashboard.card');
    this.cardHead = page.getByTestId('dashboard.card.head');
    this.by = page.getByTestId('dashboard.by');
    this.byWords = page.getByTestId('dashboard.by.words');
    this.byMore = page.getByTestId('dashboard.by.more');
    this.color = page.getByTestId('dashboard.color');
    this.colorWords = page.getByTestId('dashboard.color.words');
    this.rowsPresentation = page.getByTestId('dashboard.presentation.rows');
    this.tablePresentation = page.getByTestId('dashboard.presentation.table');
    this.relative = page.getByTestId('dashboard.relative');
    this.copy = page.getByTestId('dashboard.copy');
    this.csv = page.getByTestId('dashboard.csv');
    this.table = page.getByTestId('dashboard.table');
    this.tableHeads = page.getByTestId('dashboard.table.head');
    this.tableAll = page.getByTestId('dashboard.table.all');
    this.tableRows = page.getByTestId('dashboard.table.row');
    this.tableLabels = page.getByTestId('dashboard.table.row.label');
    this.tableTimes = page.getByTestId('dashboard.table.row.at');
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

  /** A chip's words, which open its pane where it has one. */
  chipWords(chip: Locator): Locator {
    return chip.getByTestId('dashboard.chip.words');
  }

  /** The quick filter named `label` on the line: its toggle, its count, its amount and its ×. */
  quickFilter(label: string): { item: Locator; toggle: Locator; count: Locator; amount: Locator; remove: Locator } {
    const item = this.page
      .getByTestId('dashboard.quick-filter')
      .filter({ has: this.page.getByTestId('dashboard.quick-filter.label').getByText(label, { exact: true }) });
    return {
      item,
      toggle: item.getByTestId('dashboard.quick-filter.toggle'),
      count: item.getByTestId('dashboard.quick-filter.count'),
      amount: item.getByTestId('dashboard.quick-filter.amount'),
      remove: item.getByTestId('dashboard.quick-filter.remove'),
    };
  }

  /** The search of By's list or Color's. */
  listSearch(of: 'by' | 'color'): Locator {
    return this.page.getByTestId(`dashboard.${of}.search`);
  }

  /** The groups of By's list or Color's, in its order, each its heading where it has one. */
  listGroups(of: 'by' | 'color'): Locator {
    return this.page.getByTestId(`dashboard.${of}.group`);
  }

  /** The labels of the entries of By's list or Color's, `group` one of its groups or the whole list, in its order. */
  listLabels(of: 'by' | 'color', group?: Locator): Locator {
    return (group ?? this.page.getByTestId(`dashboard.${of}.list`)).getByTestId(`dashboard.${of}.entry.label`);
  }

  /** The entry of By's list or Color's labelled `label`: its row, its pick, its count and its star. */
  entry(of: 'by' | 'color', label: string): { item: Locator; pick: Locator; count: Locator; star: Locator } {
    const item = this.page.getByTestId(`dashboard.${of}.entry`).filter({ has: this.page.getByTestId(`dashboard.${of}.entry.label`).getByText(label, { exact: true }) });
    return {
      item,
      pick: item.getByTestId(`dashboard.${of}.entry.pick`),
      count: item.getByTestId(`dashboard.${of}.entry.count`),
      star: item.getByTestId(`dashboard.${of}.entry.star`),
    };
  }

  /** A row's cells of the table, its All row's among them, after its label. */
  cells(row: Locator): Locator {
    return row.getByTestId('dashboard.table.cell');
  }

  /** The picker's group of dimensions `group`, Parts or Attributes. */
  filterGroup(group: 'Parts' | 'Attributes'): Locator {
    return this.page.getByTestId('dashboard.filter.picker').getByRole('group', { name: group }).getByTestId('dashboard.filter.dimension');
  }

  /** The pane's value whose label is `label`. */
  paneValue(label: string): Locator {
    return this.paneValues.filter({ has: this.page.getByTestId('dashboard.pane.value.label').getByText(label, { exact: true }) });
  }

  /** The calendar's day `day` of the month it shows. */
  day(day: number): Locator {
    return this.days.filter({ hasText: new RegExp(`^${day}$`) });
  }

  /** The line's tab named `name`. */
  lineTab(name: string): Locator {
    return this.lineTabs.filter({ has: this.page.getByTestId('dashboard.tabs.tab.name').getByText(name, { exact: true }) });
  }

  /** The names of a list of the panel's views, `list` the system views or the saved ones, in its order. */
  viewNames(list: Locator): Locator {
    return list.getByTestId('dashboard.panel.view.name');
  }

  /** The row of the view named `name` in `list`. */
  view(list: Locator, name: string): Locator {
    return list.getByTestId('dashboard.panel.view').filter({ has: this.page.getByTestId('dashboard.panel.view.name').getByText(name, { exact: true }) });
  }

  /** A view's act in its row on hover: its rename, its remove or its star. */
  async act(row: Locator, act: 'rename' | 'remove' | 'star'): Promise<void> {
    await row.hover();
    await row.getByTestId(`dashboard.panel.view.${act}`).click();
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

  /**
   * The states whose rows the server answered from the call on, a read the page cancelled left
   * out, as the dev server's second mount of a query cancels the first's; read by the answer.
   */
  rowsAnswered(): () => string[] {
    const states: string[] = [];
    this.page.on('requestfinished', (request) => {
      const url = new URL(request.url());
      if (url.pathname === '/api/dashboard/rows') states.push(url.searchParams.get('state') ?? '');
    });
    return () => states;
  }

  /** The states the page asks the quick filters' counts of from the call on, each a task started; read by the answer. */
  countsReads(): () => string[] {
    return this.reads('/api/dashboard/counts/quick-filters');
  }

  /**
   * The states whose By's counts the server started from the call on, each a task, a request the
   * page cancelled left out, as the dev server's second mount of the list cancels the first's; read
   * by the answer.
   */
  byCountsAnswered(): () => string[] {
    const states: string[] = [];
    this.page.on('requestfinished', (request) => {
      const url = new URL(request.url());
      if (url.pathname === '/api/dashboard/counts/attributes') states.push(url.searchParams.get('state') ?? '');
    });
    return () => states;
  }

  /** The states the page asks the normal form of from the call on; read by the answer. */
  addressReads(): () => string[] {
    return this.reads('/api/dashboard/address');
  }

  /**
   * The tab `hash` names moved to the state it names, a new entry, as the dashboard's own moves
   * write one (F160.4): its entry carries in the history's state the tab's id, and the saved view
   * and the state it opened with that the entry before held of the same tab.
   */
  async go(hash: string): Promise<void> {
    await this.page.evaluate((to) => {
      const tab = /^#dash\/([^/=]+)\//.exec(to)?.[1];
      const was = (history.state as { dash?: { tab: string; view: unknown; opened: unknown } } | null)?.dash;
      const kept = was !== undefined && was.tab === tab ? was : { view: null, opened: null };
      history.pushState({ dash: { tab, view: kept.view, opened: kept.opened } }, '', to);
    }, hash);
  }

  /** The page's address moved to `hash`, as a link from outside the dashboard moves it: typed, or followed. */
  async follow(hash: string): Promise<void> {
    await this.page.evaluate((to) => (location.hash = to), hash);
  }

  /** The tabs the browser keeps, each its id and its state now, in the order opened. */
  keptTabs(): Promise<{ id: string; now: string | null }[]> {
    return this.page.evaluate(() =>
      (JSON.parse(localStorage.getItem('pilot') ?? '{}').viewTabs?.tabs ?? []).map((each: { id: string; now: string | null }) => ({ id: each.id, now: each.now })),
    );
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
