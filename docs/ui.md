# The UI

The React app is the mockup converted ([`change-discipline.md`](change-discipline.md)). This page
is its frame as built: the shell every screen sits in, the tokens and the shared pieces, the keys,
what the browser remembers, links in text and the PWA. The screens have their own pages:
[`projects.md`](projects.md) for the project list and the head, [`timeline.md`](timeline.md) for a
project's timeline and its items, and [`sign-in.md`](sign-in.md) for the handle step and the profile
page.

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

- `Avatar({who, size?})`: a person `{name, initials, slot}`, or `'pilot'`; `size` is `sm` or `xs`.
- `Menu` and `MenuItem`, and `Popover`: each closes on a press outside it and on Esc
  (`src/hooks/use-dismiss.ts`).
- `Dialog`, a modal dialog on Radix's (`@radix-ui/react-dialog`, not the template's wrapper) that a
  click beside it or Esc closes, Esc through `useEscape` (below) and never Radix's own. While it is
  open, Tab and Shift+Tab stay inside it and the page behind it is hidden from a screen reader. It
  takes the focus as it opens, to its `initialFocus` or else the first thing in it that takes the
  focus, and gives it back as it closes, to its `returnFocus` or else to what had it, if that is
  still there. `ConfirmDialog({title, lines, note?, act, pending, onConfirm, onCancel, returnFocus?,
  testId})` asks before an act: Cancel takes the focus first, so that Enter pressed again cancels,
  and while `pending`, nothing closes it. The project's menu has the focus given back to its button,
  since the item chosen is gone.
- `EmptyState({icon, title, testId})`.
- `Time({at, format?})`: a time in the browser's time zone, with the full stamp as its tooltip: by
  `format`, the day and the month ("19 Oct", the default), `clock`, the hour and the minute
  ("14:05"), or `stamp`, the date and the time ("22 Oct 2026, 14:05"). The record and the API hold
  times in UTC.
- `LinkedText`: below.
- `Markdown({text})`: GFM (react-markdown with remark-gfm) inside `.prose`, its text linked as the
  record's words are except in code and inside a link, every link opening in a new tab.
- `Fold({children, testId})`: a text cut at 13.5em, fading out, with Show more; one that fits shows
  whole.
- `TextField`: the text field every answer is typed into, a `textarea` one line at rest that grows
  with its text to eight lines and then scrolls. Enter breaks the line; Ctrl+Enter, Cmd+Enter on a
  Mac, calls its `onSend` where the field has one Send, and Esc its `onEscape` where something holds
  it. While it has the focus, its parent, the row holding what sends it, is kept in view.

`shared.css` has the mockup's buttons (`.btn` with `.btn-sm`, `.btn-icon`, `.btn-primary`,
`.btn-soft`, `.btn-ghost`), the text field (`.field` in a `.field-row` with its button beside it,
level with its bottom edge), `.chip`, `.popover`, `.menu-pop`, `.dialog`, `.empty-state`,
`.mention`, `.prose`, `.fold` and `.link`.

## The keys

`src/lib/keys.ts`. Esc closes the top-most open thing, one per press. The layers, bottom to top, are
`console`, `overlay`, `panel`, `plan`, `menu`, `dialog` and `keys`; within a layer, the thing opened
last is on top. An open thing registers with `useEscape(layer, open, close)`. `?` opens the keys
list, which names Ctrl+Enter, Esc and `?`. Neither key acts in a text field or with a modifier
held; Esc in a console's own field closes the console, and Ctrl+Enter sends a text field that has
one Send (`TextField`).

## What the browser remembers

`src/lib/browser-state.ts`, one localStorage entry, `pilot`: the theme, the current project (which
the bare address opens), and the chevrons of *Other projects* and *Finished*. Nothing of it is on
the server. A component reads it with `useBrowserState()` and changes it with
`rememberInBrowser(change)`.

The unsent text of every answer's field is a second entry, `pilot.unsent`, by field:
`<item>/<block>/answer`, `/paste`, `/other` and `/no` ([`timeline.md`](timeline.md)).
`useUnsentText(field, initial)` (`src/hooks/use-unsent-text.ts`) reads it when the field opens, so a
field opened again, after a reload or in another tab, starts from what was left in it, and writes it
on every keystroke over what the storage holds. An emptied field's entry is deleted, and so is a
sent one's once the record holds it; a refused send keeps it.

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
http(s) address, stops the app at boot; a base's trailing slash is dropped. Each deployed stage's
values are in PilotDeploy ([`deployment.md`](deployment.md)), and both keep the default pattern
(D017): a list of the tracker's keys would have to follow its projects by hand, so a word shaped
like an id, `SHA-256`, links too. **`GET /api/links`** answers them with the
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

`frontend/public/` holds the app's mark, `favicon.svg`: the operator's control tower, drawn in
three-quarter perspective, on a rounded tile in the theme's blue (D020). The favicon and the
manifest's icons (192px, 512px and a 512px maskable one, the tile full-bleed with the tower at 0.8 of
its size) are rendered from it by `scripts/render-icons.mjs`, run from `frontend/` after a change to
the SVG; the top bar's `logo.svg` is the same tower in blues on a white tile, the bar being the
theme's blue itself (D020). Beside them stand the manifest (`manifest.json`) and the service worker,
`sw.js`; the page head links the manifest and sets `theme-color` to `#568ed2`, a standing edit of
the template's `index.html` (`CLAUDE.md`).
`registerServiceWorker()` (`src/lib/service-worker.ts`) registers the worker when the shell's
module loads, on any page, before sign-in too, wherever the browser offers service workers (a
secure context). The worker caches nothing. It answers only a navigation the network does not,
with one line, "Pilot is unreachable. Try again when you are back on the network.", and never a
request under `/api/`, where sign-in, its callback and sign-out are. The UI's nginx caches the
build's hashed `/assets/` for a year and has the browser revalidate the root's files — the icons,
the logo, the manifest, the worker — on every load, so a changed icon shows under its name (a
standing edit of the template's `nginx.conf`, `CLAUDE.md`).

## Testing it

The frontend suite's fixtures (`frontend/tests/support/fixtures.ts`):

- `people`: `signIn({name?, handle?})` signs in a person with a handle, chosen through the API;
  `firstSignIn({name?})` one at their first sign-in, `null` for a token with no name;
  `other(handle, name?)` puts another person on the record; `self()` reads the signed-in person.
- `shell`: `open(path)` opens an address once the signed-in person is read.
- `links`: `set({ticket_url_template?, environment_link_base_url?})` sets the link settings for the
  spec, a setting left out unset, and unsets both after it, through `PUT /api/testing/links`, which
  answers only in testing mode and refuses what the boot refuses; `environment(id, name)` puts an
  environment on the record through `POST /api/testing/environments` ([`projects.md`](projects.md)).
- The page objects `handleStep`, `profile`, `projectList`, `projectHead` and `timeline`, and
  `projects` ([`projects.md`](projects.md), [`timeline.md`](timeline.md)).
