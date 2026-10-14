/**
 * Home page: a placeholder for the app's first route.
 * Generated once and app-owned. Replace it with the app's own page, or with a
 * redirect to it. Without any route besides the root, the router's types
 * collapse to `never` and `tsc` fails.
 */

import { createFileRoute } from '@tanstack/react-router'
import { UserDropdown } from '@/components/layout/user-dropdown'

export const Route = createFileRoute('/')({
  component: HomePage,
})

function HomePage() {
  return (
    <>
      {/* Without the app shell the app draws its own header, and the
          template's auth specs look for the signed-in user's dropdown in it. */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b px-4">
        <h1 className="text-lg font-semibold">Pilot</h1>
        <UserDropdown />
      </header>
      <main className="flex-1 overflow-auto" data-testid="home.page" />
    </>
  )
}
