/** Colours as the browser computes them, and WCAG's contrast between them. */

import type { Locator } from '@playwright/test';

interface Colours {
  /** The text's colour and the element's own background, as sRGB bytes. */
  text: [number, number, number];
  background: [number, number, number];
  /** WCAG 2's contrast ratio of the text against the background. */
  ratio: number;
}

/** An element's text against its own, opaque, background. */
export async function coloursOf(locator: Locator): Promise<Colours> {
  return locator.evaluate((element) => {
    const probe = document.createElement('canvas').getContext('2d', { willReadFrequently: true })!;
    // The browser's own parser: any colour syntax, painted and read back as sRGB bytes.
    const rgb = (colour: string): [number, number, number] => {
      probe.clearRect(0, 0, 1, 1);
      probe.fillStyle = colour;
      probe.fillRect(0, 0, 1, 1);
      const [r, g, b] = probe.getImageData(0, 0, 1, 1).data;
      return [r, g, b];
    };
    const luminance = ([r, g, b]: [number, number, number]) => {
      const linear = (c: number) => {
        const s = c / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
    };
    const style = getComputedStyle(element);
    const text = rgb(style.color);
    const background = rgb(style.backgroundColor);
    const [hi, lo] = [luminance(text), luminance(background)].sort((a, b) => b - a);
    return { text, background, ratio: (hi + 0.05) / (lo + 0.05) };
  });
}
