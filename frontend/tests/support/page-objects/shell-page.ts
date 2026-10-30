import type { Locator, Page } from '@playwright/test';
import { waitForUiState } from '../helpers';

/** The frame every screen sits in: the top bar, its gold badges and its profile menu, the gold bar, the side column, the keys list. */
export class ShellPage {
  readonly topBar: Locator;
  readonly brand: Locator;
  readonly drawerToggle: Locator;
  readonly goldBadges: Locator;
  readonly app: Locator;
  readonly goldBar: Locator;
  readonly side: Locator;
  readonly scrim: Locator;
  readonly centre: Locator;
  readonly user: Locator;
  readonly avatar: Locator;
  readonly userName: Locator;
  readonly profileMenu: Locator;
  readonly profileName: Locator;
  readonly theme: Locator;
  readonly profileItem: Locator;
  readonly signOut: Locator;
  readonly keys: Locator;
  readonly keysBackdrop: Locator;

  constructor(private readonly page: Page) {
    this.topBar = page.getByTestId('app-shell.topbar');
    this.brand = this.topBar.locator('.brand');
    this.drawerToggle = page.getByTestId('shell.drawer-toggle');
    this.goldBadges = page.getByTestId('shell.gold-badges');
    this.app = page.getByTestId('shell.app');
    this.goldBar = page.getByTestId('shell.gold-bar');
    this.side = page.getByTestId('shell.side');
    this.scrim = page.getByTestId('shell.scrim');
    this.centre = page.getByTestId('shell.centre');
    this.user = page.getByTestId('app-shell.topbar.user');
    this.avatar = this.user.locator('.avatar');
    this.userName = page.getByTestId('app-shell.topbar.user.name');
    this.profileMenu = page.getByTestId('app-shell.topbar.user.dropdown');
    this.profileName = page.getByTestId('shell.profile.name');
    this.theme = page.getByTestId('shell.profile.theme');
    this.profileItem = page.getByTestId('shell.profile.page');
    this.signOut = page.getByTestId('app-shell.topbar.user.logout');
    this.keys = page.getByTestId('shell.keys');
    this.keysBackdrop = page.getByTestId('shell.keys.backdrop');
  }

  /** The top bar's badge for a condition off a phone, by its code: `outage`, the controller unreachable. */
  goldBadge(code: 'outage'): Locator {
    return this.goldBadges.locator(`[data-testid="shell.gold-badges.badge"][data-condition="${code}"]`);
  }

  /** The gold bar's line for a condition on a phone, by its code: `outage`, the controller unreachable. */
  goldLine(code: 'outage'): Locator {
    return this.goldBar.locator(`[data-testid="shell.gold-bar.line"][data-condition="${code}"]`);
  }

  /** Opens the app at `path`, once the signed-in person is read. */
  async open(path = '/'): Promise<void> {
    await this.page.goto(path);
    await waitForUiState(this.page, 'people.self', 'ready');
  }

  /** The page's theme, as app-theme.css reads it. */
  async pageTheme(): Promise<string | undefined> {
    return this.page.evaluate(() => document.documentElement.dataset.theme);
  }
}
