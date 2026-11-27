/**
 * A generated mutation hook's options that keep its write pending until its read again
 * (`READ_AFTER_A_WRITE`) has ended: the hook returns its read with a caller's `onSuccess`, and this
 * one does nothing more. For a
 * write whose button must not take a second press before the screen shows the first.
 */
export const UNTIL_READ = { onSuccess: () => undefined };
