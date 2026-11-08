/**
 * The frame every screen sits in. Off a phone the top bar over the side column, which stands
 * beside the centre; at the narrow width, above 900 px and below 1200 px (F98.2, F111), the side
 * column is the phone's drawer, opened from the top bar's toggle, its first part, and lying under
 * the top bar over the centre, behind its scrim, with no head of its own; switching projects closes
 * it. On a phone (F98.3, F111) no top bar: a project's head is the page's top, the
 * drawer's button its first part, and a screen with no head has the button alone where a head's
 * stands; the drawer lies over the head and opens on the top bar's block of colour, its avatar
 * opening the profile menu; it stands on the project list's tint with no rule at its edge, and the
 * page behind it darkens as it slides in, 30% black in the light theme and 80% in the dark, the
 * scrim's opacity the share of its way the drawer has come; under reduced motion it comes and goes
 * at once. The browser's own bar takes the page's colour on a phone and the top bar's off it. The
 * project list's head is at base size and its icons 16px at every width. On a phone, the keyboard
 * shrinks the app rather than panning it.
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { ShellPage } from '../support/page-objects/shell-page';
import { projectAddress } from '../support/projects';

const PHONE = { width: 390, height: 844 };
const TOP_BAR_COLOUR = '#568ed2';

/** A colour as the browser computes it, from the page's tokens: `hsl(var(--side))`. */
function colourOf(page: Page, colour: string): Promise<string> {
  return page.evaluate((css) => {
    const probe = document.createElement('div');
    probe.style.backgroundColor = css;
    document.body.append(probe);
    const computed = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return computed;
  }, colour);
}

/** The project list's head at base size and its plus's and menu's icons at 16px. */
async function expectListHead(head: Locator, base: string): Promise<void> {
  await expect(head).toHaveCSS('font-size', base);
  for (const icon of await head.locator('.btn-icon svg.icon').all()) {
    await expect(icon).toHaveCSS('width', '16px');
    await expect(icon).toHaveCSS('height', '16px');
  }
  await expect(head.locator('.btn-icon svg.icon')).toHaveCount(2);
}

interface Frame {
  /** The drawer's left edge. */
  x: number;
  scrimOpacity: number;
}

/**
 * Presses `press` and reads the drawer and its scrim as the frame changes, before the page paints:
 * where it moves, where it starts.
 */
function pressAndRead(shell: ShellPage, press: string): Promise<Frame> {
  return shell.app.evaluate(
    (app, selector) =>
      new Promise<Frame>((resolve) => {
        const drawer = app.querySelector('.tabs')!;
        const scrim = app.querySelector('.drawer-scrim')!;
        const observer = new MutationObserver(() => {
          observer.disconnect();
          resolve({ x: drawer.getBoundingClientRect().x, scrimOpacity: Number(getComputedStyle(scrim).opacity) });
        });
        observer.observe(app, { attributeFilter: ['data-drawer'] });
        document.querySelector<HTMLElement>(selector)!.click();
      }),
    press,
  );
}

const TOGGLE = '[data-testid="shell.drawer-toggle"]';
const SCRIM = '[data-testid="shell.scrim"]';

test.describe('The frame off a phone', () => {
  test('stands the top bar over the side column beside the centre, with no drawer, the browser’s bar the top bar’s colour', async ({
    people,
    shell,
    projectList,
  }) => {
    await people.signIn();
    await shell.open('/profile');

    await expect(shell.topBar).toBeVisible();
    await expect(shell.drawerToggle).toHaveCount(0);
    await expect(shell.drawerHead).toHaveCount(0);
    await expect(shell.scrim).toHaveCount(0);
    await expect(shell.side).toBeVisible();
    const top = (await shell.topBar.boundingBox())!;
    const side = (await shell.side.boundingBox())!;
    const centre = (await shell.centre.boundingBox())!;
    expect(side.width).toBe(264);
    expect(side.y).toBe(top.y + top.height);
    expect(centre.x).toBeGreaterThanOrEqual(side.x + side.width);
    expect(await shell.browserBarColour()).toBe(TOP_BAR_COLOUR);

    // The scale a pixel down off a phone: base is 15px.
    await expectListHead(projectList.head, '15px');
  });
});

test.describe('The frame at the narrow width', () => {
  test.use({ viewport: { width: 1100, height: 800 } });

  test('stands the top bar over the centre, the drawer’s toggle its first part in the bar’s white; the drawer opens from it under the top bar, with no head, behind its scrim, which closes it; at 1200 px the side column stands again', async ({
    page,
    people,
    shell,
  }) => {
    await people.signIn();
    // At a stable address: the bare address moves on to a project, which closes the drawer.
    await shell.open('/profile');

    await expect(shell.topBar).toBeVisible();
    await expect(shell.side).toBeHidden();
    await expect(shell.scrim).toBeHidden();
    await expect(shell.drawerHead).toHaveCount(0);
    await expect(shell.drawerToggle).toHaveCount(1);
    await expect(shell.topBar.getByTestId('shell.drawer-toggle')).toBeVisible();
    await expect(shell.drawerToggle).toHaveAccessibleName('Projects');
    await expect(shell.drawerToggle).toHaveAttribute('aria-expanded', 'false');
    await expect(shell.drawerToggle).toHaveCSS('color', 'rgb(255, 255, 255)');
    const first = await shell.topBar.evaluate((bar) => bar.querySelector('button, a[href], input, select, [tabindex]')?.getAttribute('data-testid'));
    expect(first).toBe('shell.drawer-toggle');
    const [top, toggle, brand, centre] = await Promise.all(
      [shell.topBar, shell.drawerToggle, shell.brand, shell.centre].map(async (locator) => (await locator.boundingBox())!),
    );
    expect(toggle.width).toBe(36);
    expect(toggle.x + 8).toBeCloseTo(20, 0);
    expect(toggle.x + toggle.width).toBeLessThanOrEqual(brand.x);
    expect(centre).toMatchObject({ x: 0, y: top.y + top.height, width: 1100 });

    await shell.drawerToggle.click();
    await expect(shell.drawerToggle).toHaveAttribute('aria-expanded', 'true');
    await expect.poll(async () => (await shell.side.boundingBox())?.x).toBe(0);
    expect(await shell.side.boundingBox()).toMatchObject({ y: top.y + top.height, width: 300 });
    await expect(shell.side).toHaveCSS('background-color', await colourOf(page, 'hsl(var(--side))'));
    await expect(shell.side).toHaveCSS('border-right-width', '0px');
    await expect(shell.scrim).toBeVisible();
    await expect(shell.scrim).toHaveCSS('opacity', '1');
    // The top bar lies over the drawer: its toggle takes the press that closes it.
    expect(await shell.drawerToggle.evaluate((button) => {
      const box = button.getBoundingClientRect();
      return button.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
    })).toBe(true);
    await shell.drawerToggle.click();
    await expect(shell.side).toBeHidden();

    await shell.drawerToggle.click();
    await expect(shell.side).toBeInViewport();
    await shell.scrim.click({ position: { x: 600, y: 300 } });
    await expect(shell.side).toBeHidden();
    await expect(shell.scrim).toBeHidden();
    await expect(shell.drawerToggle).toHaveAttribute('aria-expanded', 'false');

    await page.setViewportSize({ width: 1200, height: 800 });
    await expect(shell.drawerToggle).toHaveCount(0);
    await expect(shell.scrim).toHaveCount(0);
    await expect(shell.side).toBeVisible();
    expect((await shell.side.boundingBox())!.width).toBe(264);
    await page.setViewportSize({ width: 901, height: 800 });
    await expect(shell.drawerToggle).toBeVisible();
    await expect(shell.side).toBeHidden();
  });

  test('switching projects from the drawer closes it, and Back finds it closed', async ({ page, people, projects, projectList, shell }) => {
    const me = await people.signIn();
    const aId = await projects.make({ name: makeUnique('A'), members: [me.handle!] });
    const b = makeUnique('B');
    const bId = await projects.make({ name: b, members: [me.handle!] });
    await projectList.open(aId);

    await shell.drawerToggle.click();
    await expect(shell.side).toBeVisible();
    await projectList.tab(b).click();
    await expect(page).toHaveURL(projectAddress(bId));
    await expect(shell.side).toBeHidden();
    await expect(shell.scrim).toBeHidden();

    await page.goBack();
    await expect(page).toHaveURL(projectAddress(aId));
    await expect(shell.side).toBeHidden();
  });
});

test.describe('The frame on a phone', () => {
  test.use({ viewport: PHONE });

  test('has no top bar: a project’s head is the page’s top, the drawer’s button its first part, and the profile page has the button where the head’s stands', async ({
    people,
    projects,
    projectHead,
    profile,
    shell,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Frame'), members: [me.handle!] });
    await projectHead.open(project);

    await expect(shell.topBar).toHaveCount(0);
    expect(await projectHead.root.boundingBox()).toMatchObject({ x: 0, y: 0, width: PHONE.width });
    await expect(shell.drawerToggle).toHaveCount(1);
    await expect(projectHead.root.getByTestId('shell.drawer-toggle')).toBeVisible();
    await expect(shell.drawerToggle).toHaveAccessibleName('Projects');
    await expect(shell.drawerToggle).toHaveAttribute('aria-expanded', 'false');
    const first = await projectHead.root.evaluate((head) => head.querySelector('button, a[href], input, select, [tabindex]')?.getAttribute('data-testid'));
    expect(first).toBe('shell.drawer-toggle');
    const inHead = (await shell.drawerToggle.boundingBox())!;
    expect(inHead.x + inHead.width).toBeLessThanOrEqual((await projectHead.name.boundingBox())!.x);
    expect(inHead.width).toBe(36);

    await shell.open('/profile');
    await expect(profile.root).toBeVisible();
    await expect(shell.drawerToggle).toHaveCount(1);
    const alone = (await shell.drawerToggle.boundingBox())!;
    expect(alone.x).toBeCloseTo(inHead.x, 0);
    expect(alone.y).toBeCloseTo(inHead.y, 0);
    expect(alone.width).toBe(inHead.width);
    expect((await profile.root.boundingBox())!.y).toBeGreaterThanOrEqual(alone.y + alone.height);
  });

  test('opens the drawer over the head on the top bar’s block of colour, its avatar opening the profile menu, the list’s head at base size', async ({
    page,
    people,
    projects,
    projectHead,
    projectList,
    shell,
  }) => {
    const me = await people.signIn({ name: 'Ada Example' });
    const project = await projects.make({ name: makeUnique('Drawer'), members: [me.handle!] });
    await projectHead.open(project);
    await expect(shell.side).toBeHidden();

    await shell.drawerToggle.click();
    await expect(shell.drawerToggle).toHaveAttribute('aria-expanded', 'true');
    await expect.poll(async () => (await shell.side.boundingBox())?.x).toBe(0);
    expect(await shell.side.boundingBox()).toMatchObject({ y: 0, width: 300 });
    expect(await shell.drawerHead.boundingBox()).toMatchObject({ x: 0, y: 0, width: 300, height: 52 });
    await expect(shell.drawerHead).toHaveCSS('background-color', await colourOf(page, 'hsl(var(--primary))'));
    await expect(shell.drawerBrand).toHaveText('Pilot');
    await expect(shell.drawerBrand).toHaveCSS('color', 'rgb(255, 255, 255)');
    await expect(shell.drawerBrand.locator('img.logo')).toHaveAttribute('src', '/logo.png');
    await expect(shell.avatar).toHaveText('AE');
    await expectListHead(projectList.head, '16px');

    // The drawer lies over the head, its button under it.
    expect(await shell.drawerToggle.evaluate((button) => {
      const box = button.getBoundingClientRect();
      return button.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
    })).toBe(false);

    await shell.user.click();
    await expect(shell.profileName).toHaveText('Ada Example');
    await expect(shell.theme).toBeVisible();
    await expect(shell.profileMenu.getByRole('menuitem')).toHaveText(['Profile', 'Sign out']);
    await shell.profileItem.click();
    await expect(page).toHaveURL('/profile');
    await expect(shell.side).toBeHidden();
  });

  test('stands the drawer on the list’s tint with no rule at its edge, the page behind it darkening as far as it has come', async ({
    page,
    people,
    shell,
  }) => {
    await people.signIn();
    // At a stable address: the bare address moves on to a project, which closes the drawer.
    await shell.open('/profile');
    await expect(shell.scrim).toBeHidden();

    await shell.drawerToggle.click();
    await expect(shell.side).toBeInViewport();
    await expect(shell.scrim).toBeVisible();
    await expect(shell.scrim).toHaveCSS('opacity', '1');
    await expect(shell.side).toHaveCSS('border-right-width', '0px');
    for (const [scheme, scrim] of [
      ['light', 'rgba(0, 0, 0, 0.3)'],
      ['dark', 'rgba(0, 0, 0, 0.8)'],
    ] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await expect(page.locator('html')).toHaveAttribute('data-theme', scheme);
      await expect(shell.side).toHaveCSS('background-color', await colourOf(page, 'hsl(var(--side))'));
      await expect(shell.scrim).toHaveCSS('background-color', scrim);
    }

    // Halfway in, the page half as dark.
    await shell.app.evaluate((app) => {
      app.style.transition = 'none';
      app.style.setProperty('--drawer', '0.5');
    });
    expect(await shell.side.evaluate((drawer) => drawer.getBoundingClientRect().x)).toBeCloseTo(-0.5 * 1.05 * 300, 1);
    await expect(shell.scrim).toHaveCSS('opacity', '0.5');
    await shell.app.evaluate((app) => app.removeAttribute('style'));

    // Pressed beside the drawer, which covers its left 300px, the scrim closes it.
    await shell.scrim.click({ position: { x: 350, y: 300 } });
    await expect(shell.side).toBeHidden();
    await expect(shell.scrim).toBeHidden();
    await expect(shell.drawerToggle).toHaveAttribute('aria-expanded', 'false');
  });

  test('slides the drawer in and out as the page darkens and lightens, and under reduced motion opens and closes it at once', async ({
    page,
    people,
    shell,
  }) => {
    await people.signIn();
    await shell.open('/profile');
    // The suite's pages reduce motion (fixtures-infrastructure.ts): this one moves first.
    await page.emulateMedia({ reducedMotion: 'no-preference' });

    // It starts where it was, and moves.
    const opening = await pressAndRead(shell, TOGGLE);
    expect(opening.x).toBeCloseTo(-1.05 * 300, 0);
    expect(opening.scrimOpacity).toBe(0);
    await expect.poll(async () => (await shell.side.boundingBox())?.x).toBe(0);
    await expect(shell.scrim).toHaveCSS('opacity', '1');
    const closing = await pressAndRead(shell, SCRIM);
    expect(closing.x).toBe(0);
    expect(closing.scrimOpacity).toBe(1);
    await expect(shell.side).toBeHidden();
    await expect(shell.scrim).toBeHidden();

    await page.emulateMedia({ reducedMotion: 'reduce' });
    const opened = await pressAndRead(shell, TOGGLE);
    expect(opened.x).toBe(0);
    expect(opened.scrimOpacity).toBe(1);
    await expect(shell.side).toBeVisible();
    const closed = await pressAndRead(shell, SCRIM);
    expect(closed.x).toBeCloseTo(-1.05 * 300, 0);
    expect(closed.scrimOpacity).toBe(0);
    await expect(shell.side).toBeHidden();
    await expect(shell.side).toHaveCSS('visibility', 'hidden');
  });

  test('paints the browser’s own bar in the page’s colour, in either theme, and the top bar’s again off a phone', async ({
    page,
    people,
    shell,
  }) => {
    await people.signIn();
    await shell.open('/profile');

    for (const scheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await expect(page.locator('html')).toHaveAttribute('data-theme', scheme);
      const background = await colourOf(page, 'hsl(var(--background))');
      await expect.poll(() => shell.browserBarColour()).toBe(background);
    }

    await page.setViewportSize({ width: 1280, height: 720 });
    await expect(shell.topBar).toBeVisible();
    await expect.poll(() => shell.browserBarColour()).toBe(TOP_BAR_COLOUR);
  });
});

test.describe('The phone’s keyboard', () => {
  test('shrinks the app, the viewport resizing its content, where Chrome would pan the page', async ({ people, shell, page }) => {
    await people.signIn();
    await shell.open('/profile');

    const viewport = await page.locator('meta[name="viewport"]').getAttribute('content');
    expect(viewport!.split(',').map((part) => part.trim())).toContain('interactive-widget=resizes-content');
  });
});
