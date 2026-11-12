import type { Locator, Page } from '@playwright/test';

/** How far the middle of `step` stands under the middle of `scroller`, the box its list scrolls in, in pixels. */
export async function underMiddle(scroller: Locator, step: Locator): Promise<number> {
  const middle = (locator: Locator) =>
    locator.evaluate((element) => {
      const box = element.getBoundingClientRect();
      return box.top + box.height / 2;
    });
  return (await middle(step)) - (await middle(scroller));
}

/** How far `scroller` is scrolled, and the furthest it scrolls. */
export async function scrolled(scroller: Locator): Promise<{ top: number; furthest: number }> {
  return scroller.evaluate((element) => ({ top: element.scrollTop, furthest: element.scrollHeight - element.clientHeight }));
}

/** Counts the clicks that reach the page's document from here on: what it returns answers the count so far. */
export async function heardClicks(page: Page): Promise<() => Promise<number>> {
  await page.evaluate(() => {
    const counter = window as unknown as { heardClicks: number };
    counter.heardClicks = 0;
    document.addEventListener('click', () => (counter.heardClicks += 1));
  });
  return () => page.evaluate(() => (window as unknown as { heardClicks: number }).heardClicks);
}
