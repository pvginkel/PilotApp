import type { Locator } from '@playwright/test';

/**
 * How far a chip's words, its text and not its icon, stand above its pill's middle, and the pill's
 * height. Its words are the text it draws, in the chip itself or in its label; text it draws none
 * of, a popover's or one hidden, is left out.
 */
export const lift = (chip: Locator) =>
  chip.evaluate((element) => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const texts: Text[] = [];
    while (walker.nextNode()) {
      const drawn = document.createRange();
      drawn.selectNodeContents(walker.currentNode);
      if (drawn.getClientRects().length > 0) texts.push(walker.currentNode as Text);
    }
    const words = document.createRange();
    words.setStart(texts[0], 0);
    words.setEnd(texts[texts.length - 1], texts[texts.length - 1].length);
    const [text, pill] = [words.getBoundingClientRect(), element.getBoundingClientRect()];
    return { lift: (pill.top + pill.bottom) / 2 - (text.top + text.bottom) / 2, height: pill.height };
  });
