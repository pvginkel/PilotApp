/**
 * A pane's drawn scrollbar (P-269, D5): on every pane that scrolls a page's content, the browser's
 * own bar hidden and a drawn one over the pane's right edge, taking none of its width; drawn while
 * the content overflows, shown under the mouse, with the keyboard's focus in the pane, while dragged
 * and for a moment after any scroll; its thumb dragged, its track pressed to page, the wheel over it
 * scrolling the pane; in either theme, and on a phone under a finger. A code block and a text field
 * keep the browser's bar.
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { cssColour } from '../support/contrast';
import { makeUnique } from '../support/helpers';
import type { Projects } from '../support/projects';
import { DrawnBar, expectDrawnBar } from '../support/scroll-bar';
import type { TimelinePage } from '../support/page-objects/timeline-page';

const NOTICE = 'A notice that takes\n\na few lines\n\nof the timeline.\n';

/** A project whose timeline is some three times as tall as the page. */
async function longProject(projects: Projects, member: string): Promise<string> {
  const id = await projects.makeWithSession({ name: makeUnique('Scroll'), members: [member] });
  for (let index = 0; index < 12; index += 1) {
    await projects.place(id, { kind: 'notice', title: `Notice ${index + 1}`, text: NOTICE });
  }
  return id;
}

const barOf = (page: Page, timeline: TimelinePage) => new DrawnBar(page, timeline.root, 'timeline.scrollbar');

test.describe('The timeline’s drawn scrollbar', () => {
  test('floats over its right edge, taking none of its width, hidden until the mouse is over the timeline; its thumb as long as the view is of what scrolls, standing where the view does', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    await timeline.open(await longProject(projects, me.handle!));
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    const bar = barOf(page, timeline);

    await expectDrawnBar(timeline.root);
    await expect(bar.root).toBeVisible();
    await expect(bar.root).toHaveCSS('opacity', '0');
    const column = await timeline.root.locator('.feed-inner').boundingBox();
    await timeline.root.hover();
    await expect(bar.root).toHaveCSS('opacity', '1');
    // Shown, it moves nothing.
    expect(await timeline.root.locator('.feed-inner').boundingBox()).toEqual(column);

    const end = await bar.geometry();
    expect(end.bar.x + end.bar.width).toBeCloseTo(end.pane.right, 0);
    expect(end.bar.y).toBeCloseTo(end.pane.top, 0);
    expect(end.bar.height).toBeCloseTo(end.pane.clientHeight, 0);
    expect(end.thumb.height).toBeCloseTo(Math.max(32, (end.bar.height * end.pane.clientHeight) / end.pane.scrollHeight), 0);
    expect(end.thumb.y + end.thumb.height).toBeCloseTo(end.bar.y + end.bar.height, 0);

    await timeline.scrollToTop();
    await expect.poll(async () => (await bar.geometry()).thumb.y).toBeCloseTo(end.bar.y, 0);
    await timeline.root.evaluate((feed) => (feed.scrollTop = (feed.scrollHeight - feed.clientHeight) / 2));
    await expect
      .poll(async () => {
        const { bar: track, thumb } = await bar.geometry();
        return thumb.y - track.y - (track.height - thumb.height) / 2;
      })
      .toBeCloseTo(0, 0);
  });

  test('is not drawn while the timeline does not overflow', async ({ people, projects, timeline, page }) => {
    const me = await people.signIn();
    await timeline.open(await projects.makeWithSession({ name: makeUnique('Short'), members: [me.handle!] }));
    await expect(timeline.opening).toBeVisible();
    await timeline.root.hover();

    await expect(barOf(page, timeline).root).toBeHidden();
    expect(await timeline.root.evaluate((feed) => (feed as HTMLElement).offsetWidth - feed.clientWidth)).toBe(0);
  });

  test('shows for a moment after any scroll, the mouse elsewhere, and while the keyboard’s focus is in the timeline, whose keys scroll it', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    await timeline.open(await longProject(projects, me.handle!));
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    const bar = barOf(page, timeline);
    await expect(bar.root).toHaveCSS('opacity', '0');

    await timeline.root.evaluate((feed) => feed.scrollBy({ top: -200 }));
    await expect(bar.root).toHaveAttribute('data-scrolled', '');
    await expect(bar.root).toHaveCSS('opacity', '1');
    await expect(bar.root).not.toHaveAttribute('data-scrolled');
    await expect(bar.root).toHaveCSS('opacity', '0');

    // Tab from a line of the timeline's: the focus in it from the keyboard.
    await timeline.items.last().getByText('a few lines').click();
    await page.mouse.move(0, 0);
    await expect(bar.root).toHaveCSS('opacity', '0');
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => document.activeElement?.closest('[data-testid="timeline"]') !== null)).toBe(true);
    await expect(bar.root).not.toHaveAttribute('data-scrolled');
    await expect(bar.root).toHaveCSS('opacity', '1');
    const top = await timeline.scrollTop();
    await page.keyboard.press('PageUp');
    await expect.poll(() => timeline.scrollTop()).toBeLessThan(top);
  });

  test('drags with its thumb, pages towards a press on its track, and scrolls the timeline under the wheel; its thumb widens under the mouse', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    await timeline.open(await longProject(projects, me.handle!));
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    const bar = barOf(page, timeline);
    await timeline.root.hover();
    await expect(bar.thumb).toHaveCSS('width', '6px');
    await bar.thumb.hover();
    await expect(bar.thumb).toHaveCSS('width', '10px');

    const { pane } = await bar.geometry();
    const ratio = await bar.ratio();
    await bar.drag(page, -100);
    await expect.poll(() => timeline.scrollTop()).toBeCloseTo(pane.over - 100 * ratio, -0.5);
    // Nothing of the timeline's got selected on the way.
    expect(await page.evaluate(() => window.getSelection()!.toString())).toBe('');

    const dragged = await timeline.scrollTop();
    const step = 0.875 * pane.clientHeight;
    const { bar: track, thumb } = await bar.geometry();
    await page.mouse.click(track.x + track.width / 2, thumb.y - 10);
    await expect.poll(() => timeline.scrollTop()).toBeCloseTo(dragged - step, -0.5);
    const paged = await timeline.scrollTop();
    await page.mouse.click(track.x + track.width / 2, track.y + track.height - 4);
    await expect.poll(() => timeline.scrollTop()).toBeCloseTo(Math.min(pane.over, paged + step), -0.5);

    const before = await timeline.scrollTop();
    await page.mouse.move(track.x + track.width / 2, track.y + track.height / 2);
    await page.mouse.wheel(0, -120);
    await expect.poll(() => timeline.scrollTop()).toBe(before - 120);
  });

  test('draws its thumb in the muted words’ colour in the light and the dark theme, and widens it with no transition under the reduced-motion setting', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await longProject(projects, me.handle!);
    const bar = barOf(page, timeline);

    const colours: string[] = [];
    for (const theme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: theme });
      await timeline.open(id);
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await timeline.root.hover();
      await expect(bar.root).toHaveCSS('opacity', '1');
      const colour = await cssColour(page, 'hsl(var(--muted-foreground) / 0.45)');
      await expect(bar.thumb).toHaveCSS('background-color', colour);
      colours.push(colour);
    }
    expect(colours[0]).not.toBe(colours[1]);

    await expect(bar.thumb).toHaveCSS('transition-duration', '0s');
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await expect(bar.thumb).toHaveCSS('transition-duration', '0.12s');
  });
});

test.describe('Every pane that scrolls a page’s content', () => {
  test('off a phone draws its bar, with no gutter: the timeline, the side column, the panel’s tabs and its chat, a document’s tab, the session log, the plan popover and the profile page; a code block and a text field keep the browser’s', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    sessionLog,
    panel,
    chat,
    shell,
    projectHead,
    profile,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({
      name: makeUnique('Panes'),
      members: [me.handle!],
      tasks: [{ id: 'a', title: 'Step a', status: 'in_progress', notes: [] }],
    });
    const notice = await projects.place(id, { kind: 'notice', title: 'Code', text: '```\nmake check\n```\n' });
    const document = await projects.place(id, { kind: 'document', title: 'Packing', text: 'Pack the tent.\n' });
    await timeline.open(id);

    await expectDrawnBar(timeline.root);
    await expectDrawnBar(shell.side.locator('.tabs-view'));
    await expectDrawnBar(chat.body);
    await expect(chat.field).toHaveCSS('scrollbar-width', 'thin');
    await expect(timeline.item(notice).root.locator('pre')).toHaveCSS('scrollbar-width', 'thin');
    await panel.documentsTab.click();
    await expectDrawnBar(panel.body);
    await projectHead.step.click();
    await expect(projectHead.plan).toBeVisible();
    await expectDrawnBar(projectHead.planBody);
    await page.keyboard.press('Escape');

    await overlay.open(id, document);
    await expectDrawnBar(overlay.body);

    const work = await projects.startWork(id, { title: 'Survey', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
    await sessionLog.open(id, work);
    await expectDrawnBar(sessionLog.body);

    await page.goto('/profile');
    await expect(profile.heading).toBeVisible();
    await expectDrawnBar(profile.root);
  });
});

test.describe('On a phone’s Chrome', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test('every pane that scrolls a page’s content draws its bar: the home’s list, the timeline, the plan page and a view', async ({
    page,
    people,
    projects,
    shell,
    timeline,
    phoneTabs,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Phone'), members: [me.handle!] });
    const document = await projects.place(id, { kind: 'document', title: 'Packing', text: 'Pack the tent.\n' });
    await page.goto('/');
    await expectDrawnBar(shell.homeList);

    await timeline.open(id);
    await expectDrawnBar(timeline.root);
    await phoneTabs.tab('plan').click();
    await expectDrawnBar(page.getByTestId('project.plan-page'));
    await overlay.open(id, document);
    await expectDrawnBar(overlay.body);
  });

  test('shows on a touch scroll alone, never under a tap, and its thumb drags under a finger', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    await timeline.open(await longProject(projects, me.handle!));
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    const bar = barOf(page, timeline);
    await expect(bar.root).toHaveCSS('opacity', '0');

    const text = (await timeline.items.last().getByText('a few lines').boundingBox())!;
    await page.touchscreen.tap(text.x + 4, text.y + text.height / 2);
    await expect(bar.root).not.toHaveAttribute('data-scrolled');
    await expect(bar.root).toHaveCSS('opacity', '0');

    const cdp = await page.context().newCDPSession(page);
    const top = await timeline.scrollTop();
    // A finger pans the timeline down.
    const [x, y] = [text.x + 4, text.y - 200];
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
    for (let step = 1; step <= 10; step += 1) {
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: y + step * 30 }] });
    }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await expect.poll(() => timeline.scrollTop()).toBeLessThan(top);
    await expect(bar.root).toHaveAttribute('data-scrolled', '');
    // While it shows from the scroll, a finger takes its thumb, which ends the pan's fling: the drag
    // moves the timeline from where the press found it.
    const ratio = await bar.ratio();
    await timeline.root.evaluate((feed) => {
      feed.addEventListener('scrollbar-press', () => (feed.dataset.pressedAt = String(feed.scrollTop)), { once: true });
    });
    await bar.touchDrag(cdp, -60);
    const pressedAt = Number(await timeline.root.getAttribute('data-pressed-at'));
    await expect.poll(() => timeline.scrollTop()).toBeCloseTo(pressedAt - 60 * ratio, -0.5);
    await expect(bar.root).toHaveCSS('opacity', '1');
    await expect(bar.root).toHaveCSS('opacity', '0');
  });
});
