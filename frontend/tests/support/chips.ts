import type { Locator } from '@playwright/test';

/** How far a chip's words, its text and not its icon, stand above its pill's middle, and the pill's height. */
export const lift = (chip: Locator) =>
  chip.evaluate((element) => {
    const texts = Array.from(element.childNodes).filter((node) => node.nodeType === Node.TEXT_NODE);
    const words = document.createRange();
    words.setStart(texts[0], 0);
    words.setEnd(texts[texts.length - 1], texts[texts.length - 1].textContent!.length);
    const [text, pill] = [words.getBoundingClientRect(), element.getBoundingClientRect()];
    return { lift: (pill.top + pill.bottom) / 2 - (text.top + text.bottom) / 2, height: pill.height };
  });
