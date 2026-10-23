/**
 * Renders the favicon, the PWA icons and the top bar's logo from the operator's renders of Pilot's
 * mark, assets/icon/tower-blue.png and tower-white.png (from ATC-tower.blend beside them). Run from
 * frontend/: `node scripts/render-icons.mjs`.
 *
 * The favicon, the plain icons and the logo keep the tile's transparent corners; the maskable icon is
 * the blue tile full-bleed with the mark at 0.8 of its size, inside the 80% safe circle a launcher
 * may clip to. The blue render's tile is the solid theme blue, so the fill around the scaled tile
 * meets it without a seam. The files keep their names: the UI's nginx revalidates the root's files
 * on every load.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { chromium } from '@playwright/test';

const sourceDir = new URL('../../assets/icon/', import.meta.url);
const publicDir = new URL('../public/', import.meta.url);
const tileBlue = '#568ed2';

const dataUrl = (file) => `data:image/png;base64,${readFileSync(new URL(file, sourceDir)).toString('base64')}`;
const blue = dataUrl('tower-blue.png');
const white = dataUrl('tower-white.png');

const outputs = [
  { file: 'favicon.png', size: 384, source: blue, maskable: false },
  { file: 'icon-192.png', size: 192, source: blue, maskable: false },
  { file: 'icon-512.png', size: 512, source: blue, maskable: false },
  { file: 'icon-512-maskable.png', size: 512, source: blue, maskable: true },
  // The top bar shows it at 32px; three times that keeps it sharp on a phone.
  { file: 'logo.png', size: 96, source: white, maskable: false },
];

const browser = await chromium.launch();
for (const { file, size, source, maskable } of outputs) {
  const page = await browser.newPage({ viewport: { width: size, height: size } });
  const background = maskable ? tileBlue : 'transparent';
  const mark = maskable ? size * 0.8 : size;
  await page.setContent(
    `<html><body style="margin:0;width:${size}px;height:${size}px;display:grid;place-items:center;background:${background}">` +
      `<img src="${source}" width="${mark}" height="${mark}"></body></html>`,
  );
  await page.locator('img').evaluate((img) => img.decode());
  const png = await page.screenshot({ omitBackground: !maskable });
  writeFileSync(new URL(file, publicDir), png);
  console.log(`wrote public/${file} (${size}px)`);
  await page.close();
}
await browser.close();
