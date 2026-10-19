# The UI

The React app is the mockup converted ([`change-discipline.md`](change-discipline.md)). This page
is its frame as built: the shell every screen sits in, the tokens and the shared pieces, the keys,
what the browser remembers, links in text and the PWA. The screens have their own pages:
[`projects.md`](projects.md) for the project list and the head, and [`sign-in.md`](sign-in.md) for
the handle step and the profile page.

## Where things go

`frontend/index.html`, `nginx.conf`, `src/index.css`, `src/main.tsx` and `src/routes/__root.tsx`
are the template's (`CLAUDE.md` § Template ownership). The app's own:

- **A screen** is a route under the shell, `src/routes/_shell/<name>.tsx`; `/` is
  `_shell/index.tsx`.
- **The tokens and base styles** are `src/styles/app-theme.css`, which imports each component
  folder's stylesheet; a screen's own styles sit beside its components.
- **The shared pieces** are `src/components/shared/`, their styles in its `shared.css`.
- **The toast's look** is `src/styles/toast.ts`, over the template's toast.

## The shell

`src/routes/_shell.tsx` is a layout route: the top bar, then the side column (`nav.tabs`, the
project list) and the centre (`main.centre`), where the child route shows. It reads the signed-in
person through `useSelf()` (`GET /api/people/self`). Until they have a handle, the handle step
stands under the top bar in place of the side column and the centre; a screen under the shell
reads the person with `usePerson()`, whose handle, name and avatar slot are never null.

- **The top bar** (`components/shell/top-bar.tsx`): the drawer toggle on a narrow window once the
  app is open, the logo and the name, and the person's avatar, which opens the profile menu. The
  menu holds the person's name, Theme (System, Light, Dark), Profile once the handle is chosen, and
  Sign out. The bar keeps the template's `app-shell.topbar.user*` test ids, so the template's
  sign-in specs pass against it.
- **The narrow window.** Under the mockup's breakpoint, 900px wide, the side column is a drawer
  over the centre, with a scrim. The top bar's toggle opens it; the scrim closes it, and so does
  any change of address.
- **Empty states** are `EmptyState`: "No projects yet" when there is no project, "None yet" for an
  empty list of archived projects.

## Tokens and the theme

`app-theme.css` holds the mockup's tokens, light and dark, as `:root[data-theme="light"]` and
`:root[data-theme="dark"]`. They are unlayered, so they win over the template's layered
`index.css`, its `prefers-color-scheme: dark` block included, and each sets every token
`index.css` sets, so a choice other than the system's leaves none of the template's showing.
Tailwind's `dark:` variant follows `data-theme` (`@custom-variant dark`).

The theme (`src/lib/theme.ts`) is System, Light or Dark, remembered in the browser. `startTheme()`
sets `data-theme` when the shell's module loads, before the first render, and while the choice is
System it follows the OS live. Before it runs, `index.css`'s own tokens show, with the same
background and text.

**The avatars.** The palette is `--avatar-1` to `--avatar-6`, each with its `-text`: the primary
tint, pink, green, amber, violet and teal. A person's avatar slot counts from 1 and slot *n* takes
colour (*n* − 1) modulo 6, plus 1; `tests/shell/avatars.spec.ts` measures every pair at 4.5:1 or
better in both themes. Pilot's mark is `--avatar-pilot`, grey, outside the palette. `Avatar`
(`components/shared/avatar.tsx`) shows a person's initials with their full name as its tooltip, or
a user icon for a name without initials.

## The shared pieces

In `src/components/shared/`:

- `Avatar({who, size?})`: a person `{name, initials, slot}`, or `'pilot'`.
- `Menu` and `MenuItem`, and `Popover`: each closes on a press outside it and on Esc
  (`src/hooks/use-dismiss.ts`).
- `Dialog`, a modal dialog that a click beside it or Esc closes, and `ConfirmDialog({title, lines,
  note?, act, pending, onConfirm, onCancel, testId})`, which asks before an act; while `pending`,
  nothing closes it.
- `EmptyState({icon, title, testId})`.
- `Time({at})`: a time in the browser's time zone, the day and the month ("19 Oct"), with the full
  stamp as its tooltip. The record and the API hold times in UTC.
- `LinkedText`: below.

`shared.css` has the mockup's buttons (`.btn` with `.btn-sm`, `.btn-icon`, `.btn-primary`,
`.btn-soft`, `.btn-ghost`), the text field (`.field` in a `.field-row` with its button beside it,
one line at rest), `.chip`, `.popover`, `.menu-pop`, `.dialog`, `.empty-state` and `.mention`.

## The keys

`src/lib/keys.ts`. Esc closes the top-most open thing, one per press. The layers, bottom to top, are
`overlay`, `panel`, `plan`, `menu`, `dialog` and `keys`; within a layer, the thing opened last is
on top. An open thing registers with `useEscape(layer, open, close)`. `?` opens the keys list.
Neither key acts in a text field or with a modifier held.

## What the browser remembers

`src/lib/browser-state.ts`, one localStorage entry, `pilot`: the theme, the current project (which
the bare address opens), and the chevrons of *Other projects* and *Finished*. Nothing of it is on
the server. A component reads it with `useBrowserState()` and changes it with
`rememberInBrowser(change)`.

## Toasts

The template's toast, in the mockup's look (`src/styles/toast.ts`): a card at most 380px wide, an
error and a warning told apart by their border. A refused write's reason, the API's `error`, shows
as the query client's error toast. A toast's text is plain: the toast viewport sits above the
router, outside the links' provider.

## Links in text

Ticket ids, repos and environments link wherever the record's words show, buttons included.

**The settings.** `TICKET_ID_PATTERN` (by default `[A-Z][A-Z0-9_]*-[1-9][0-9]*`, matched whole),
`TICKET_URL_TEMPLATE` (a ticket's address, `{id}` where the id goes) and
`ENVIRONMENT_LINK_BASE_URL` (KubeCoder's address), in `backend/app/app_config.py`. An empty one is
unset, and unset leaves its text unlinked. A template without `{id}`, or a base that is not an
http(s) address, stops the app at boot; a base's trailing slash is dropped. Production's values
are in PilotDeploy ([`deployment.md`](deployment.md)). **`GET /api/links`** answers them with the
record's environments: `{ticket_id_pattern, ticket_url_template, environment_link_base_url,
environments: [{id, name}]}`, the environments by name, then id.

**What links** (`src/lib/links.ts`), the first match winning, in this order:

1. A ticket id, by `\b(?:<pattern>)\b`, while the URL template is set: to the template with `{id}`
   replaced, titled "Open <id> in the tracker".
2. `pvginkel/<name>`, always: to `https://github.com/pvginkel/<name>`, titled "Open <repo> on
   GitHub".
3. While the base is set, an environment: an id of KubeCoder's form (`pvginkel-<…>-<six hex
   digits>`), or the name of one of the record's environments, anywhere when the name ends in
   `-<digits>` and otherwise only before " environment" or " environments", the longest name
   first where two match at one place (`Lab-1-2` over `Lab-1`). It links to
   `<base>/environments/<id>/ssh/open`, which opens the environment in VS Code, titled "Open
   <environment> in VS Code".

The pattern is compiled as a JavaScript `RegExp` as well, so a pattern only Python reads breaks the
text under the shell.

**`<LinkedText text={…} />`** renders the record's words under the shell's `LinksProvider`, which
reads `GET /api/links` once; until it answers, text shows unlinked. A link is an `<a
class="mention">` that opens in a new tab, in the colour of the text around it and underlined under
the mouse. With `nested`, for text inside a link or a button, where a link cannot nest, each link
is a `span role="link"` that opens on a click or on Enter and keeps the link or button around it
from acting.

## The PWA

`frontend/public/` holds the manifest (`manifest.json`), its icons (192px, 512px and a 512px
maskable one) and the service worker, `sw.js`; the page head links the manifest and sets
`theme-color` to `#568ed2`, a standing edit of the template's `index.html` (`CLAUDE.md`).
`registerServiceWorker()` (`src/lib/service-worker.ts`) registers the worker when the shell's
module loads, on any page, before sign-in too, wherever the browser offers service workers (a
secure context). The worker caches nothing. It answers only a navigation the network does not,
with one line, "Pilot is unreachable. Try again when you are back on the network.", and never a
request under `/api/`, where sign-in, its callback and sign-out are. The UI's nginx caches `*.js`
and the icons for a year; the browser fetches a worker's script past that cache, but a changed
icon needs a new file name.

## Testing it

The frontend suite's fixtures (`frontend/tests/support/fixtures.ts`):

- `people`: `signIn({name?, handle?})` signs in a person with a handle, chosen through the API;
  `firstSignIn({name?})` one at their first sign-in, `null` for a token with no name;
  `other(handle)` puts another person on the record; `self()` reads the signed-in person.
- `shell`: `open(path)` opens an address once the signed-in person is read.
- `links`: `set({ticket_url_template?, environment_link_base_url?})` sets the link settings for the
  spec, a setting left out unset, and unsets both after it; `environment(id, name)` puts an
  environment on the record. They use `PUT /api/testing/links`, which answers only in testing mode
  and refuses what the boot refuses.
- The page objects `handleStep`, `profile`, `projectList` and `projectHead`, and `projects`
  ([`projects.md`](projects.md)).
