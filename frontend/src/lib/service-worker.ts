/** Registers the PWA's service worker, `public/sw.js`, by which Chrome installs the app (F95). */
export function registerServiceWorker(): void {
  // Absent outside a secure context: the dev server reached over plain http by its address.
  if ('serviceWorker' in navigator) {
    void navigator.serviceWorker.register('/sw.js');
  }
}
