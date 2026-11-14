import { expect, type CDPSession, type Locator, type Page } from '@playwright/test';

/** A pane's drawn scrollbar (scroll-bar.tsx), by its test id: the bar and its thumb. */
export class DrawnBar {
  readonly root: Locator;
  readonly thumb: Locator;

  constructor(
    page: Page,
    /** The pane it scrolls. */
    readonly pane: Locator,
    testId: string,
  ) {
    this.root = page.getByTestId(testId);
    this.thumb = page.getByTestId(`${testId}.thumb`);
  }

  /** The pane's scroll and box, and the bar's and its thumb's boxes. */
  async geometry() {
    const [pane, bar, thumb] = await Promise.all([
      this.pane.evaluate((element) => {
        const box = element.getBoundingClientRect();
        return {
          top: box.top,
          right: box.right,
          scrollTop: element.scrollTop,
          over: element.scrollHeight - element.clientHeight,
          scrollHeight: element.scrollHeight,
          clientHeight: element.clientHeight,
        };
      }),
      this.root.boundingBox(),
      this.thumb.boundingBox(),
    ]);
    return { pane, bar: bar!, thumb: thumb! };
  }

  /** How far the pane scrolls for a pixel the thumb moves. */
  async ratio(): Promise<number> {
    const { pane, bar, thumb } = await this.geometry();
    return pane.over / (bar.height - thumb.height);
  }

  /** Drags the thumb by `dy` pixels with the mouse, from its middle. */
  async drag(page: Page, dy: number): Promise<void> {
    const thumb = (await this.thumb.boundingBox())!;
    const [x, y] = [thumb.x + thumb.width / 2, thumb.y + thumb.height / 2];
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x, y + dy, { steps: 5 });
    await page.mouse.up();
  }

  /** Drags the thumb by `dy` pixels with a finger, from its middle. */
  async touchDrag(cdp: CDPSession, dy: number): Promise<void> {
    const thumb = (await this.thumb.boundingBox())!;
    const [x, y] = [thumb.x + thumb.width / 2, thumb.y + thumb.height / 2];
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
    for (let step = 1; step <= 5; step += 1) {
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: y + (dy * step) / 5 }] });
    }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  }
}

/**
 * The pane draws its bar: its own hidden, no gutter kept for it, and the drawn bar beside it in what
 * holds it.
 */
export async function expectDrawnBar(pane: Locator): Promise<void> {
  expect(
    await pane.evaluate((element) => [
      getComputedStyle(element).scrollbarWidth,
      (element as HTMLElement).offsetWidth - element.clientWidth,
      element.parentElement!.querySelectorAll(':scope > .scrollbar').length,
    ]),
  ).toEqual(['none', 0, 1]);
}
