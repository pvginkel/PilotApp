/**
 * A prose heading as it is drawn: its size and its weight, the space it keeps above it, whether it
 * opens its part of the text, and how far it stands under what comes before that part, or under
 * its part's top where it opens the text's first.
 */

import type { Locator } from '@playwright/test';

interface Heading {
  size: number;
  weight: string;
  /** Its top margin, in pixels. */
  above: number;
  /** Whether it is the first thing in its part. */
  opens: boolean;
  /** Whether its part is the first of its text. */
  first: boolean;
  gap: number;
}

export function headingOf(heading: Locator): Promise<Heading> {
  return heading.evaluate((element) => {
    const style = getComputedStyle(element);
    const part = element.parentElement!;
    // A part alone in a box of its own stands where its box does.
    let box = part;
    while (box.parentElement!.children.length === 1) box = box.parentElement!;
    const before = box.previousElementSibling;
    const top = element.getBoundingClientRect().top;
    return {
      size: parseFloat(style.fontSize),
      weight: style.fontWeight,
      above: parseFloat(style.marginTop),
      opens: part.firstElementChild === element,
      first: before === null,
      gap: before === null ? top - part.getBoundingClientRect().top : top - before.getBoundingClientRect().bottom,
    };
  });
}

/** A size of the type scale as the page has it, in pixels: `--text-lg`. */
export function scaleOf(page: Locator, name: string): Promise<number> {
  return page.evaluate((_, variable) => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(variable)), name);
}
