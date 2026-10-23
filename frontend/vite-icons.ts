import fs from 'fs'
import path from 'path'
import type { Plugin } from 'vite'

// The root names the page head, the manifest and the top bar ask for, each from its render in
// assets/icon/ (render_both.py, from ATC-tower.blend beside it).
const ICONS: Record<string, string> = {
  'favicon.png': 'tower-blue-384.png',
  'icon-192.png': 'tower-blue-192.png',
  'icon-512.png': 'tower-blue-512.png',
  'icon-512-maskable.png': 'tower-blue-512-maskable.png',
  // The top bar shows it at 32px; three times that keeps it sharp on a phone.
  'logo.png': 'tower-white-96.png',
}

const ICON_DIR = path.resolve(__dirname, 'assets/icon')

/**
 * Serves the renders of Pilot's mark under their root names from the dev server, and writes them
 * to the build's root, so a new render is in the next build with nothing copied. The names stay
 * put across renders: the UI's nginx revalidates the root's files on every load.
 */
export function appIcons(): Plugin {
  return {
    name: 'app-icons',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const render = ICONS[(req.url ?? '').split('?')[0].slice(1)]
        if (!render) {
          next()
          return
        }
        fs.readFile(path.join(ICON_DIR, render), (error, png) => {
          if (error) {
            next(error)
            return
          }
          res.setHeader('Content-Type', 'image/png')
          res.setHeader('Cache-Control', 'no-cache')
          res.end(png)
        })
      })
    },
    generateBundle() {
      for (const [fileName, render] of Object.entries(ICONS)) {
        this.emitFile({ type: 'asset', fileName, source: fs.readFileSync(path.join(ICON_DIR, render)) })
      }
    },
  }
}
