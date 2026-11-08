import type { Locator, Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';
import type { UiStateTestEvent } from '@/lib/test/test-events';
import { waitTestEvent } from '../helpers';

type ConditionCode = components['schemas']['ConditionsSchema.6c014b4.ConditionCode'];

/**
 * The frame every screen sits in: the offer of the browser's notifications, the top bar, its gold
 * badges, the week's halt's popover and its profile menu, the gold bar, the side column, on a phone
 * the drawer with its head and its button, the keys list.
 */
export class ShellPage {
  /** The offer of the browser's notifications, across the page's top, and its two buttons. */
  readonly offer: Locator;
  readonly offerOn: Locator;
  readonly offerNotNow: Locator;
  readonly topBar: Locator;
  readonly brand: Locator;
  readonly drawerToggle: Locator;
  /** On a phone, the drawer's head, the top bar's block of colour, and Pilot's name in it. */
  readonly drawerHead: Locator;
  readonly drawerBrand: Locator;
  readonly goldBadges: Locator;
  /** The week's halt's popover off a phone, under its badge: its line, with the overrule. */
  readonly goldPopover: Locator;
  readonly app: Locator;
  readonly goldBar: Locator;
  readonly side: Locator;
  readonly scrim: Locator;
  readonly centre: Locator;
  /** The loading bar, while a wait for the next screen's reads has lasted 200 ms. */
  readonly loading: Locator;
  readonly user: Locator;
  readonly avatar: Locator;
  readonly userName: Locator;
  readonly profileMenu: Locator;
  readonly profileName: Locator;
  readonly theme: Locator;
  readonly profileItem: Locator;
  readonly signOut: Locator;
  /** The profile menu's foot: the short hash of the commit the page is built from. */
  readonly profileVersion: Locator;
  readonly keys: Locator;
  readonly keysBackdrop: Locator;

  constructor(private readonly page: Page) {
    this.offer = page.getByTestId('shell.notifications-offer');
    this.offerOn = page.getByTestId('shell.notifications-offer.on');
    this.offerNotNow = page.getByTestId('shell.notifications-offer.not-now');
    this.topBar = page.getByTestId('app-shell.topbar');
    this.brand = this.topBar.locator('.brand');
    this.drawerToggle = page.getByTestId('shell.drawer-toggle');
    this.drawerHead = page.getByTestId('shell.drawer-head');
    this.drawerBrand = this.drawerHead.locator('.brand');
    this.goldBadges = page.getByTestId('shell.gold-badges');
    this.goldPopover = page.getByTestId('shell.gold-badges.popover');
    this.app = page.getByTestId('shell.app');
    this.goldBar = page.getByTestId('shell.gold-bar');
    this.side = page.getByTestId('shell.side');
    this.scrim = page.getByTestId('shell.scrim');
    this.centre = page.getByTestId('shell.centre');
    this.loading = page.getByTestId('shell.loading');
    this.user = page.getByTestId('app-shell.topbar.user');
    this.avatar = this.user.locator('.avatar');
    this.userName = page.getByTestId('app-shell.topbar.user.name');
    this.profileMenu = page.getByTestId('app-shell.topbar.user.dropdown');
    this.profileName = page.getByTestId('shell.profile.name');
    this.theme = page.getByTestId('shell.profile.theme');
    this.profileItem = page.getByTestId('shell.profile.page');
    this.signOut = page.getByTestId('app-shell.topbar.user.logout');
    this.profileVersion = page.getByTestId('shell.profile.version');
    this.keys = page.getByTestId('shell.keys');
    this.keysBackdrop = page.getByTestId('shell.keys.backdrop');
  }

  /** The top bar's badge for a condition off a phone, by its code. */
  goldBadge(code: ConditionCode): Locator {
    return this.goldBadges.locator(`[data-testid="shell.gold-badges.badge"][data-condition="${code}"]`);
  }

  /** The gold bar's line for a condition on a phone, by its code. */
  goldLine(code: ConditionCode): Locator {
    return this.goldBar.locator(`[data-testid="shell.gold-bar.line"][data-condition="${code}"]`);
  }

  /** A gold line's words, the phone's (`goldLine()`) or the popover's (`goldPopover`), without its button. */
  goldText(line: Locator): Locator {
    return line.getByTestId('shell.gold-line.text');
  }

  /** A gold line's overrule button, the phone's (`goldLine()`) or the popover's (`goldPopover`). */
  goldOverrule(line: Locator): Locator {
    return line.getByTestId('shell.gold-line.overrule');
  }

  /**
   * Opens the app at `path`, once the signed-in person is read: not at the ready StrictMode's first
   * unmount reports, marked aborted.
   */
  async open(path = '/'): Promise<void> {
    await this.page.goto(path);
    await waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === 'people.self' && event.phase === 'ready' && event.metadata?.status !== 'aborted',
    );
  }

  /**
   * Resolves once the page hears its person's input, on which it beats (`shell.app-page`): past the
   * ready StrictMode's first unmount reports, marked aborted.
   */
  async listening(): Promise<void> {
    await waitTestEvent<UiStateTestEvent>(
      this.page,
      'ui_state',
      (event) => event.scope === 'shell.app-page' && event.phase === 'ready' && event.metadata?.status !== 'aborted',
    );
  }

  /** The colour the page asks the browser to paint its own bar in. */
  async browserBarColour(): Promise<string | null> {
    return this.page.locator('meta[name="theme-color"]').getAttribute('content');
  }

  /** The page's theme, as app-theme.css reads it. */
  async pageTheme(): Promise<string | undefined> {
    return this.page.evaluate(() => document.documentElement.dataset.theme);
  }
}
