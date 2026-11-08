/**
 * What the app does once a newer version of it is deployed — app-owned, never overwritten by
 * template updates. `banner` offers a reload in the banner above the app; `reload` reloads the
 * page by itself once no field is being typed in (`contexts/deployment-context-provider.tsx`).
 */

type NewVersion = 'banner' | 'reload';

export const NEW_VERSION: NewVersion = 'reload';
