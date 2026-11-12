/**
 * The theme (F109): system, light or dark, following the OS live under System, and remembered in
 * the browser (F133). The dark theme's dividers stand at 26 % lightness and its fields' edge, a
 * token of its own, at 36 %; the light theme's both at 91 % (mockup M3). A theme chosen over the
 * OS's paints a phone's browser bar in its own tint.
 */

import { cssColour } from '../support/contrast';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { ProjectListPage } from '../support/page-objects/project-list-page';
import { projectAddress } from '../support/projects';

test.describe('The theme', () => {
  test('follows the OS, live, under System', async ({ page, people, shell }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await people.signIn();
    await shell.open();
    const html = page.locator('html');

    await expect(html).toHaveAttribute('data-theme', 'light');
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(html).toHaveAttribute('data-theme', 'dark');
    await page.emulateMedia({ colorScheme: 'light' });
    await expect(html).toHaveAttribute('data-theme', 'light');
  });

  test('Light holds where the OS is dark, over the template’s tokens too, and is remembered', async ({ page, people, shell }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await people.signIn();
    await shell.open();
    const html = page.locator('html');
    await expect(html).toHaveAttribute('data-theme', 'dark');

    await shell.user.click();
    await shell.theme.selectOption('light');

    await expect(html).toHaveAttribute('data-theme', 'light');
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(255, 255, 255)');
    // A token index.css sets in its prefers-color-scheme block, and the mockup never had.
    const secondary = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--secondary').trim());
    expect(secondary).toBe('220 15% 96%');
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('pilot')!).theme)).toBe('light');

    await shell.open();
    await expect(html).toHaveAttribute('data-theme', 'light');
    await shell.user.click();
    await expect(shell.theme).toHaveValue('light');
  });

  test('Dark holds where the OS is light, and System follows the OS again', async ({ page, people, shell }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await people.signIn();
    await shell.open();
    const html = page.locator('html');

    await shell.user.click();
    await shell.theme.selectOption('dark');
    await expect(html).toHaveAttribute('data-theme', 'dark');
    const secondary = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--secondary').trim());
    expect(secondary).toBe('215 28% 17%');

    await shell.theme.selectOption('system');
    await expect(html).toHaveAttribute('data-theme', 'light');
  });

  test('a theme chosen over the OS’s paints a phone’s browser bar in its own tabs’ tint, from the app’s start, and System in the OS’s again', async ({
    page,
    people,
    shell,
  }) => {
    const phone = { width: 390, height: 844 };
    const desk = { width: 1280, height: 720 };
    const html = page.locator('html');
    const tint = () => cssColour(page, 'hsl(var(--side))');
    /** Chosen off a phone, where the profile menu is the top bar's; read on one. */
    const choose = async (theme: 'light' | 'dark' | 'system', reads: 'light' | 'dark') => {
      await page.setViewportSize(desk);
      await shell.user.click();
      await shell.theme.selectOption(theme);
      await expect(html).toHaveAttribute('data-theme', reads);
      await page.setViewportSize(phone);
      await expect(shell.topBar).toHaveCount(0);
    };
    await page.emulateMedia({ colorScheme: 'light' });
    await people.signIn();
    await shell.open();

    await choose('dark', 'dark');
    const dark = await tint();
    expect(await shell.browserBarColour()).toBe(dark);
    await shell.open();
    await expect(html).toHaveAttribute('data-theme', 'dark');
    expect(await shell.browserBarColour()).toBe(dark);

    await page.emulateMedia({ colorScheme: 'dark' });
    await choose('light', 'light');
    const light = await tint();
    expect(light).not.toBe(dark);
    expect(await shell.browserBarColour()).toBe(light);

    await choose('system', 'dark');
    expect(await shell.browserBarColour()).toBe(dark);
    await page.emulateMedia({ colorScheme: 'light' });
    await expect(html).toHaveAttribute('data-theme', 'light');
    expect(await shell.browserBarColour()).toBe(light);
  });

  test('Dark draws the dividers at 26 % and a field’s edge, a token of its own, at 36 %; Light both at 91 %', async ({
    page,
    people,
    projects,
    timeline,
    chat,
    panel,
  }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Contrast'), members: [me.handle!] });
    const read = chat.read();
    await timeline.open(project);
    await read;
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    const token = (name: string) => page.evaluate((each) => getComputedStyle(document.documentElement).getPropertyValue(each).trim(), name);

    expect(await token('--border')).toBe('216 28% 26%');
    expect(await token('--input')).toBe('216 24% 36%');
    await expect(panel.head).toHaveCSS('border-bottom-color', await cssColour(page, 'hsl(216 28% 26%)'));
    await expect(chat.field).toHaveCSS('outline-color', await cssColour(page, 'hsl(216 24% 36%)'));

    await page.emulateMedia({ colorScheme: 'light' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    expect(await token('--border')).toBe('220 13% 91%');
    expect(await token('--input')).toBe('220 13% 91%');
    await expect(chat.field).toHaveCSS('outline-color', await cssColour(page, 'hsl(220 13% 91%)'));
  });

  test('chosen in one tab, stays when another tab switches projects', async ({ page, people, projects, projectList, shell }) => {
    const me = await people.signIn();
    const a = await projects.make({ name: makeUnique('A'), members: [me.handle!] });
    const b = makeUnique('B');
    const bId = await projects.make({ name: b, members: [me.handle!] });
    await projectList.open(a);
    const other = await page.context().newPage();
    await other.goto(projectAddress(a));
    const otherList = new ProjectListPage(other);
    await expect(otherList.tab(b)).toBeVisible();

    await shell.user.click();
    await shell.theme.selectOption('dark');
    await otherList.tab(b).click();

    await expect(other).toHaveURL(projectAddress(bId));
    const stored = () => page.evaluate(() => JSON.parse(localStorage.getItem('pilot')!) as { theme: string; project: string });
    await expect.poll(async () => (await stored()).project).toBe(bId);
    expect((await stored()).theme).toBe('dark');
    await other.close();
  });
});
