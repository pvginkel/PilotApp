/**
 * The glyph of a wait's request button (F27.3; ui-conventions, "A wait"): the operator's
 * `mockup/hourglass-skip.svg`, Lucide's hourglass with its lower bulb's right half given to two
 * chevrons, drawn as Lucide draws its icons.
 */

const PATHS = [
  'M5 2h14',
  'M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2',
  'M5 22h7',
  'M7 22v-4.172a2 2 0 0 1 .586-1.414L12 12',
  'm15 16 3 3-3 3',
  'm19 16 3 3-3 3',
];

export function HourglassSkip() {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
