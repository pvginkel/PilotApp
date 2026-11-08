/**
 * A smooth scroll's behaviour: instant under the reduced-motion setting (D175), which no style rule
 * reaches for a scroll a script asks to be smooth.
 */

const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');

export const smoothly = (): ScrollBehavior => (reduced.matches ? 'instant' : 'smooth');
