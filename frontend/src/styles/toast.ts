/**
 * Toast tone class maps — app-owned, customizable per project.
 *
 * The template's toast in the mockup's look (PilotAppSpecs design/mockup/style.css, "Toasts"): a
 * card on the page's background, its text at 14px, sliding in from above. At 380px at most it
 * stands 24px from the right edge of the template's 420px viewport, the mockup's place; on a wide
 * window it is lifted to 24px from the bottom too. An error or a warning is told apart by its
 * border.
 */

const look = [
  'max-w-[380px] rounded-[var(--radius)] border-border bg-background text-foreground shadow-[var(--shadow-lg)]',
  'animate-toast-in min-[901px]:bottom-2',
  '[&>div]:px-3.5 [&>div]:py-2.5',
].join(' ');

const action = 'border border-primary-edge bg-primary-strong text-primary-foreground hover:bg-primary-edge focus:ring-ring';

export const toastToneStyles = {
  success: { container: look, action },
  error: { container: `${look} border-destructive/60`, action },
  warning: { container: `${look} border-warning/60`, action },
  info: { container: look, action },
} as const;

export const toastIconMap = {
  success: '✓',
  error: '✕',
  warning: '⚠',
  info: 'ℹ',
} as const;
