import type { Locator, Page } from '@playwright/test';
import { waitForUiState } from '../helpers';

/** The frame every screen sits in: the top bar and its profile menu, the side column, the keys list. */
export class ShellPage {
  readonly topBar: Locator;
  readonly brand: Locator;
  readonly drawerToggle: Locator;
  readonly app: Locator;
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
    this.app = page.getByTestId('shell.app');
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
