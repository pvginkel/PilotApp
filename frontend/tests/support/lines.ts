/** Measures of a step line or a working cue: its icon against its words. */

import type { Locator } from '@playwright/test';

/**
 * Where a line's icon stands: `off`, its middle from the middle of the capitals of the words after
 * it, in pixels, negative above it (the capitals' middle is half a capital's height over the
 * words' baseline); `left`, its left edge on the page; `inLine`, its middle from the line's top.
 */
export async function iconOf(line: Locator): Promise<{ off: number; left: number; inLine: number }> {
  return line.evaluate((element) => {
    const svg = element.querySelector('svg')!;
    const icon = svg.getBoundingClientRect();
    const words = svg.parentElement!.nextElementSibling!;
    const probe = document.createElement('span');
    probe.style.cssText = 'display: inline-block; width: 0; height: 1cap;';
    words.prepend(probe);
    const capital = probe.getBoundingClientRect();
    probe.remove();
    const middle = (icon.top + icon.bottom) / 2;
    return { off: middle - (capital.top + capital.bottom) / 2, left: icon.left, inLine: middle - element.getBoundingClientRect().top };
  });
}

/** A line's height, in pixels. */
export async function heightOf(line: Locator): Promise<number> {
  return (await line.boundingBox())!.height;
}
