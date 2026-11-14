/**
 * The event a pane's drawn scrollbar (`components/shared/scroll-bar.tsx`) sends its pane when it is
 * pressed: the bar stands beside the pane, so that a press on it is no press in the pane, and a pane
 * that follows its end takes this one as such a press (use-sticky-bottom.ts).
 */
export const BAR_PRESS = 'scrollbar-press';
