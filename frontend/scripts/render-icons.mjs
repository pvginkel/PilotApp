/**
 * Renders the favicon and the PWA icons from public/favicon.svg, Pilot's mark on its rounded
 * tile. Run from frontend/: `node scripts/render-icons.mjs`.
 *
 * The favicon and the plain icons keep the tile's transparent corners; the maskable icon is the
 * tile full-bleed with the mark at 0.8 of its size, inside the 80% safe circle a launcher may clip
 * to. The files keep their names: the UI's nginx revalidates the root's files on every load.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { chromium } from '@playwright/test';

const publicDir = new URL('../public/', import.meta.url);
const svg = readFileSync(new URL('favicon.svg', publicDir), 'utf8');

const outputs = [
  { file: 'favicon.png', size: 384, maskable: false },
  { file: 'icon-192.png', size: 192, maskable: false },
  { file: 'icon-512.png', size: 512, maskable: false },
  { file: 'icon-512-maskable.png', size: 512, maskable: true },
];

const browser = await chromium.launch();
for (const { file, size, maskable } of outputs) {
  const page = await browser.newPage({ viewport: { width: size, height: size } });
  await page.setContent(`<html><body style="margin:0;background:transparent">${svg}</body></html>`);
  await page.evaluate(
    ({ size, maskable }) => {
      const root = document.querySelector('svg');
      root.setAttribute('width', size);
      root.setAttribute('height', size);
      if (maskable) {
        document.getElementById('tile').setAttribute('rx', '0');
        const box = root.viewBox.baseVal;
        const scale = 0.8;
        const offset = (box.width * (1 - scale)) / 2;
        document.getElementById('tower').setAttribute('transform', `translate(${offset} ${offset}) scale(${scale})`);
      }
    },
    { size, maskable },
  );
  const png = await page.screenshot({ omitBackground: !maskable });
  writeFileSync(new URL(file, publicDir), png);
  console.log(`wrote public/${file} (${size}px)`);
  await page.close();
}
await browser.close();
