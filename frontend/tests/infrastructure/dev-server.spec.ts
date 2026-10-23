/**
 * The workers' dev servers each pre-bundle the app's dependencies into a cache
 * of their own (tests/support/process/servers.ts, vite.config.ts's cacheDir).
 * Sharing one, two servers starting cold swap its deps/ under each other's
 * first pages.
 */

import { test, expect } from '../support/fixtures-infrastructure'

test.describe('The dev server', () => {
  test('serves the pre-bundled dependencies from its own cache', async ({ page, frontendUrl }) => {
    test.skip(
      process.env.PLAYWRIGHT_PREVIEW_MODE === 'true',
      'the preview serves a production build, which pre-bundles nothing'
    )

    const deps: string[] = []
    page.on('request', request => {
      const path = new URL(request.url()).pathname
      if (path.includes('/deps/')) deps.push(path)
    })

    await page.goto('/')

    expect(deps).not.toHaveLength(0)
    const ownCache = `/node_modules/.tmp/vite-playwright/${new URL(frontendUrl).port}/deps/`
    expect(deps.filter(path => !path.startsWith(ownCache))).toEqual([])
  })
})
