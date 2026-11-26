/**
 * A chart's label cut to its room to the pixel (F160.11), as the mockup's `clip` cuts it
 * (`design/mockup/dashboard/util.js`): whole where it fits, else its longest start that fits with
 * the ellipsis after it, measured in the font it is drawn in. SVG text has no `text-overflow`, so
 * the cut is the page's. The measure is the caller's, so that this module holds no DOM.
 */

/** The width in pixels `text` takes at `size` pixels and `weight`. */
export type Measure = (text: string, size: number, weight: number) => number;

const cuts = new WeakMap<Measure, Map<string, string>>();

/** `text` cut to `room` pixels at `size` and `weight`, as `measure` measures it. */
export function clip(text: string, room: number, measure: Measure, size = 12, weight = 400): string {
  const px = Math.floor(room);
  let kept = cuts.get(measure);
  if (kept === undefined) {
    kept = new Map();
    cuts.set(measure, kept);
  }
  const key = `${size}|${weight}|${px}|${text}`;
  const found = kept.get(key);
  if (found !== undefined) return found;
  let cut = text;
  if (text !== '' && measure(text, size, weight) > px) {
    // A start of n characters, less a surrogate pair's first half and the spaces at its end.
    const start = (n: number) => `${text.slice(0, n).replace(/[\uD800-\uDBFF]$/, '').trimEnd()}…`;
    let low = 0;
    let high = text.length - 1;
    while (low < high) {
      const middle = (low + high + 1) >> 1;
      if (measure(start(middle), size, weight) <= px) low = middle;
      else high = middle - 1;
    }
    cut = start(low);
  }
  if (kept.size > 20000) kept.clear();
  kept.set(key, cut);
  return cut;
}
