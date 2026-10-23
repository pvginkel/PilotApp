import type { PluginOption } from 'vite'

/**
 * App-owned plugin extensions — appended to the Vite config's plugins, in dev, build and preview.
 * Modify this file to add app-specific plugins (e.g. files served and built from outside public/).
 * This file is never overwritten by template updates.
 */
export function loadAppPlugins(): PluginOption[] {
  return []
}
