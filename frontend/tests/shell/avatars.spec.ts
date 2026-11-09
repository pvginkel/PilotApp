/**
 * The avatars' palette (F132; ui-conventions.md, "Answering: the options"): six colours, the
 * primary's tint first and the mockup's pink second, every pair at 4.5:1 or better in both
 * themes, and Pilot's mark outside the palette, a grey circle, its lines the primary blue (D118),
 * the light theme's in its strong shade (D179), so that the mark stands at 3:1 or better, as WCAG
 * asks of a graphic, in both themes. The palette is app-theme.css's; the avatars here are drawn as
 * the Avatar piece draws them, slot n in colour (n - 1) mod 6 + 1.
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { coloursOf, cssColour, hue } from '../support/contrast';

const COLOURS = [1, 2, 3, 4, 5, 6];

async function drawPalette(page: Page): Promise<void> {
  await page.evaluate((colours) => {
    const row = document.createElement('div');
    row.dataset.testid = 'palette';
    for (const colour of colours) {
      const avatar = document.createElement('span');
      avatar.className = 'avatar';
      avatar.dataset.colour = String(colour);
      avatar.textContent = 'MB';
      row.append(avatar);
    }
    const pilot = document.createElement('span');
    pilot.className = 'avatar pilot';
    pilot.dataset.testid = 'pilot';
    row.append(pilot);
    const tint = document.createElement('span');
    tint.dataset.testid = 'tint';
    tint.style.backgroundColor = 'hsl(var(--primary-muted))';
    row.append(tint);
    document.body.append(row);
  }, COLOURS);
}

for (const theme of ['light', 'dark'] as const) {
  test(`every colour of the palette reaches 4.5:1, ${theme}`, async ({ page, people, shell }) => {
    await page.emulateMedia({ colorScheme: theme });
    await people.signIn();
    await shell.open();
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    await drawPalette(page);

    const avatars = page.getByTestId('palette').locator('.avatar[data-colour]');
    const colours = await Promise.all(COLOURS.map((_, i) => coloursOf(avatars.nth(i))));
    for (const [i, { ratio }] of colours.entries()) {
      expect(ratio, `colour ${i + 1}`).toBeGreaterThanOrEqual(4.5);
    }
    expect(new Set(colours.map(({ background }) => background.join())).size).toBe(6);

    // The primary's tint first, the mockup's pink second.
    const tint = await coloursOf(page.getByTestId('tint'));
    expect(colours[0].background).toEqual(tint.background);
    expect(Math.abs(hue(colours[1].background) - 330)).toBeLessThan(5);

    // Pilot's mark: a grey circle, none of the palette's colours, its lines the primary blue, the
    // light theme's in its strong shade, at 3:1 or better on the circle.
    const pilot = await coloursOf(page.getByTestId('pilot'));
    const blue = theme === 'light' ? 'hsl(var(--primary-strong))' : 'hsl(var(--primary))';
    await expect(page.getByTestId('pilot')).toHaveCSS('color', await cssColour(page, blue));
    expect(pilot.ratio, "Pilot's mark").toBeGreaterThanOrEqual(3);
    expect(Math.max(...pilot.background) - Math.min(...pilot.background)).toBeLessThan(40);
    expect(colours.map(({ background }) => background.join())).not.toContain(pilot.background.join());
  });
}
