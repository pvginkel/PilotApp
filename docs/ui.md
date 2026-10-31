# The UI

The React app is the mockup converted ([`change-discipline.md`](change-discipline.md)). This page
is its frame as built: the shell every screen sits in, the tokens and the shared pieces, the keys,
what the browser remembers, links in text and the PWA. The screens have their own pages:
[`projects.md`](projects.md) for the project list and the head, [`timeline.md`](timeline.md) for a
project's timeline and its items, [`work.md`](work.md) for a work item's line and its session log,
[`documents.md`](documents.md) for the overlay and the side panel, and [`sign-in.md`](sign-in.md)
for the handle step and the profile page.

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

`src/routes/_shell.tsx` is a layout route: the top bar, then, in `.app`'s grid, the side column
(`nav.tabs`, the project list) and the centre (`main.centre`) beside it, where the child route
shows. It reads the signed-in person through `useSelf()` (`GET /api/people/self`).
Until they have a handle, the handle step stands under the top bar in place of the side column and
the centre; a screen under the shell reads the person with `usePerson()`, whose handle, name and
avatar slot are never null.

- **The top bar** (`components/shell/top-bar.tsx`): the drawer toggle on a narrow window once the
  app is open, the logo and the name, the gold bar's badges after them, none at the handle step,
  and the person's avatar, which opens the profile menu. The
  menu holds the person's name, Theme (System, Light, Dark), Profile once the handle is chosen, and
  Sign out. The bar keeps the template's `app-shell.topbar.user*` test ids, so the template's
  sign-in specs pass against it.
- **The gold bar** (`components/shell/gold-bar.tsx`) shows each condition that holds all work, and
  nothing while none does; a condition's badge or line stands while it holds and goes when it ends,
  and nothing dismisses it. Off a phone it is `GoldBadges`, a `role="status"` region in the top bar
  after Pilot's name: a badge per condition, left-aligned, on the buttons' corner radius
  (`--radius`), its words and the time it began, "Controller unreachable since 13:16", its full line
  its `title`. The week's usage halt's badge, which carries its overrule, is a button with a chevron
  and no `title`: it opens a popover (`Popover`, `.gold-pop`) that holds its line and the overrule's
  button, so that a stray click on the top bar spends no quota, and the overrule's click closes it.
  On a phone, at 900px and below, it is `GoldBar` instead, a `role="status"` region across the
  window under the top bar, a line per condition, the overrule's button on the week's halt's line;
  `shell.css` hides the other of the two. A time is the clock alone for today, and dated, "29 Oct,
  13:16", for an earlier day, `useToday()` (`src/hooks/use-today.ts`) reading the day again each
  minute so that a page left open past midnight dates it within the minute.
  The conditions and their words (`conditionLine()`, `src/lib/utils/status-labels.ts`), in the
  server's order:
  - the controller unreachable ([`controller.md`](controller.md)), a server-off icon: "The
    controller has been unreachable since <time>. Nothing starts until it answers."
  - the week's usage halt ([`usage.md`](usage.md)), an octagon-pause icon, its badge "Halted at the
    week's limit": "Work items have been halted at the week's usage limit since <time>. 92% of the
    week's quota is used. No work item starts until a reading puts it under the limit; chats and
    Pilot's own jobs go on.", the share followed by ", as of <time>" while the reading is `stale`,
    the age a fresh reading does not have (`usage.md`). Its overrule's button says "Go on to 97%" for the
    allowance and "Run it out" at the second limit, its `title` what it does, "Work items go on
    until 97% of the week's quota is used." or "Work items go on until the week's quota runs
    out.", which the toast says once the overrule is made, from the answer's `kind` and `target`
    (`overruleWords()`). The toast follows the request, not the button, which the halt's lifting can
    take off the screen first; a refusal is the query client's toast.
  - the five-hour usage halt, an hourglass icon, its badge "Halted at the five-hour limit": the
    week's words for the five-hour window, "… of the five-hour window's quota is used …", with no
    overrule.

  **`GET /api/conditions`** answers `{conditions: [{code, since, share, taken_at, offer, target}]}`:
  `code` `outage`, `week_halt` or `five_hour_halt`, the outage first, then the week's halt, then
  the five-hour halt; `since` when it began, as this server met the controller or received the
  readings; a halt's `share` of its window's quota and its reading's `taken_at`, null for the
  outage; and the week's halt's `offer`, `allowance` or `run_out`, with the allowance's `target`, a
  fraction, null at the wall and for the other conditions, where the line shows no overrule. At
  each turn of a condition, and as a halt's figures move, the SSE event `conditions_changed`
  carries the same body to every person's connections.
  `useConditions()` (`src/hooks/use-conditions.ts`), read once in `_shell.tsx` for both the badges
  and the lines, reads it, writes each event over the read, and reads it again at every rise of the
  stream's `isConnected`. The overrule posts `POST /api/quota-overrules` `{kind: offer}`
  ([`usage.md`](usage.md)).
- **The narrow window.** Under the mockup's breakpoint, 900px wide, the gold bar's lines span the
  window under the top bar, and in the row under them the side column is a drawer over the centre,
  with a scrim. The top bar's toggle opens it; the scrim closes it, and so does any change of
  address.
- **The phone's screen.** The app is as tall as the screen the browser shows: `h-dvh` on
  `__root.tsx`'s root and on the auth gate's screens, never `h-screen`, `100vh`, which a phone's
  Chrome measures with its URL bar hidden. The app scrolls inside itself, so the bar never hides,
  and `100vh` cut off its foot by the bar's height.
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

**The gold bar's** are `--gold`, `--gold-foreground` and `--gold-edge`, its surface, its text and
the rule under each line, light and dark; a badge redeclares the light theme's three on
`.gold-badge`, so that it is the one gold in both themes on the top bar's blue.
`tests/shell/gold-bar.spec.ts` measures its text at 4.5:1 or better and its hue gold in each
theme.

## The shared pieces

In `src/components/shared/`:

- `Avatar({who, size?})`: a person `{name, initials, slot}`, or `'pilot'`; `size` is `sm` or `xs`.
- `PILOT_MARK` (`pilot-mark.ts`): the paths of Pilot's mark, which Pilot's avatar draws and the
  timeline's auto pilot mark cuts its bolt out of ([`timeline.md`](timeline.md)).
- `Menu` and `MenuItem`, and `Popover`: each closes on a press outside it and on Esc
  (`src/hooks/use-dismiss.ts`). A `Popover`, which stands in Esc's order at the plan's rank, closes
  on its button too, and its content may be a function of `close`, for an action in it that closes
  it.
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
  ("14:05"), `dated`, the day, the month and the clock ("29 Oct, 14:05"), or `stamp`, the date and
  the time ("22 Oct 2026, 14:05"). The formats are `formatTime(at, format)`'s
  (`src/lib/utils/time-format.ts`), for a string such as a `title`, and `clockFormat(at, today)`
  picks `clock` for a time on the viewer's `today` and `dated` for an earlier day's. The record and
  the API hold times in UTC.
- `LinkedText` and `EnvironmentLink`: below.
- `Markdown({text, className?, deltas?, documentLink?})`: GFM (react-markdown with remark-gfm)
  inside `.prose`, its text linked as the record's words are except in code and inside a link, every
  link opening in a new tab. Given `documentLink`, as the Draft tab gives it
  ([`documents.md`](documents.md)), it draws every link through that component and links nothing
  else. A quote tag ([`chats.md`](chats.md) has its forms) is a chip (`QuoteChip`) that goes to what
  it quotes, from any screen under a project's address (`useOpenQuote`): an item to its address, a
  block to its own, which opens the overlay where its document is a card, a draft's ask,
  `project.md/<local id>`, to the ask in the Draft tab, past Create to the project document's
  overlay, the handbook and the project document to their overlays, and an attachment to its
  address, under its item's where it hangs on one, found in the timeline's read by its batch and its
  filename, a folder's keeping its slashes; a path naming no attachment there goes nowhere. Inside a
  code span or fence, or raw HTML, as the text's own Markdown parse reads it, or behind a backslash
  escape, the tag shows as written (`quotesToLinks`, `lib/chat/quotes.ts`).
  With `deltas`, a streamed text's, its new text fades in (`.delta-fresh`); the chat's view code
  draws its text through it ([`work.md`](work.md)).
  `HeadingWords({text})` is a heading's inline Markdown alone, for inside a button: emphasis, code
  and links as the heading shows them, each link nested as `LinkedText`'s are.
- `Fold({children, testId})`: a text cut at 13.5em, fading out, with Show more; one that fits shows
  whole.
- `TextField`: the text field every answer and every message to Pilot is typed into, a `textarea`
  one line at rest that grows with its text to eight lines, or its `lines`, the chat's five, and
  then scrolls; `readOnly` holds it, keeping the focus, while what it sends is on its way. Enter
  breaks the line; Ctrl+Enter, Cmd+Enter on a Mac, calls its `onSend` where the field has one Send,
  and Esc its `onEscape` where something holds it. While it has the focus, its parent, the row
  holding what sends it, is kept in view.

`shared.css` has the mockup's buttons (`.btn` with `.btn-sm`, `.btn-icon`, `.btn-primary`,
`.btn-danger`, `.btn-soft`, `.btn-ghost`), the text field (`.field` in a `.field-row` with its
button beside it, level with its bottom edge), `.chip`, `.popover`, `.menu-pop`, `.dialog`,
`.empty-state`, `.mention`, `.prose` (its lists with their bullets and numbers, a task list's
checkboxes), `.fold` and `.link`; `.switch`, a button of role `switch` whose knob moves right while
it is `aria-checked`, the head's auto pilot switch and the profile's alarms switch; `.icon-cap`, an
icon on its text's capitals in a flex row;
`.delta-fresh`; `.unread`, the chat's unread dot ([`chats.md`](chats.md)); and `@keyframes pulse`.

## The keys

`src/lib/keys.ts`. Esc closes the top-most open thing, one per press. The layers' ranks, bottom to
top, are `console`; `overlay` and `panel`, sharing one; `plan`; `menu`; `dialog`; and `keys`. Within
a rank, the thing opened last is on top. An open thing registers with `useEscape(layer, open,
close)`, stamped when `open` turns true. The panel registers only while it lies on top of an open
overlay, so of the two the one opened last closes first ([`documents.md`](documents.md)). `?` opens
the keys list, which names Ctrl+Enter, Esc and `?`. Neither key acts in a text field or with a
modifier held; Esc in a console's own field closes the console, and Ctrl+Enter sends a text field
that has one Send (`TextField`).

## What the browser remembers

`src/lib/browser-state.ts`, one localStorage entry, `pilot`: the theme, the current project (which
the bare address opens), the chevrons of *Other projects* and *Finished*, and each project's side
panel, `{open, tab}` by the project's id, once the person set it ([`documents.md`](documents.md)).
Nothing of it is on the server. A component reads it with `useBrowserState()` and changes it with
`rememberInBrowser(change)`, a panel with `rememberPanel(projectId, panel)`, which keeps what
another tab of the browser keeps for the other projects.

The unsent text of every answer's field and of the chat's composer is a second entry,
`pilot.unsent`, by field: `<item>/<block>/answer`, `/paste`, `/other` and `/no`
([`timeline.md`](timeline.md)), a draft's ask's under `<project>/project.md/<block>` the same way
([`documents.md`](documents.md)), and `chat/<project>` ([`chats.md`](chats.md)).
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

**`<EnvironmentLink environment={{id, name}} />`** is an environment by its name, linked by its id
to `<base>/environments/<id>/ssh/open`, "Open <name> in VS Code", while the base is set, and plain
text while it is unset or not yet read: the env chip's and the session log's.

## The PWA

The app's mark is the operator's control tower in three-quarter perspective, modelled in
`frontend/assets/icon/ATC-tower.blend` and rendered beside it by `render_both.py` (its `README.txt`
says how): `tower-blue-<size>.png`, the white tower on a rounded tile in the theme's blue, and
`tower-white-<size>.png`, the same tower in blues on a white tile (D020), each at 512, 384, 192 and
96px, and `tower-blue-512-maskable.png`, the blue tile full-bleed with the tower at 0.8 of its size.
The app takes the renders as they are: `vite-icons.ts`, a plugin of `loadAppPlugins()`, serves them
from the dev server and writes them to the build's root under the names the app asks for, so a new
render is in the next build with nothing copied: the favicon (`favicon.png`, the 384px blue one)
and the manifest's icons (`icon-192.png`, `icon-512.png` and the maskable `icon-512-maskable.png`)
from the blue renders, and the top bar's `logo.png` from the 96px white one, three times the bar's
32px, the bar being the theme's blue itself (D020). Beside them stand `public/`'s manifest
(`manifest.json`) and service worker, `sw.js`; the page head links the manifest and sets
`theme-color` to `#568ed2`, a standing edit of the template's `index.html` (`CLAUDE.md`).
`registerServiceWorker()` (`src/lib/service-worker.ts`) registers the worker when the shell's
module loads, on any page, before sign-in too, wherever the browser offers service workers (a
secure context). The worker caches nothing. It answers only a navigation the network does not,
with one line, "Pilot is unreachable. Try again when you are back on the network.", and never a
request under `/api/`, where sign-in, its callback and sign-out are. The UI's nginx caches the
build's hashed `/assets/` for a year and has the browser revalidate the root's files — the icons,
the logo, the manifest, the worker — on every load, so a changed icon shows under its name. It hands
every path under `/api/` to the backend, whatever its extension, so the cache rule never answers
one from the static root, the sync's `/api/sync/files/*.json` among them. Both are standing edits
of the template's `nginx.conf` (`CLAUDE.md`), which `tests/infrastructure/nginx.spec.ts` pins.

## Testing it

The frontend suite's fixtures (`frontend/tests/support/fixtures.ts`):

- `people`: `signIn({name?, handle?, subject?})` signs in a person with a handle, chosen through
  the API, the same `subject` signing the same person in again; `firstSignIn({name?, subject?})`
  one at their first sign-in, `null` for a token with no name;
  `other(handle, name?)` puts another person on the record; `self()` reads the signed-in person.
- `shell`: `open(path)` opens an address once the signed-in person is read; `goldBadges`,
  `goldBadge(code)` and `goldPopover` read the badges and the week's halt's popover, `goldBar` and
  `goldLine(code)` the phone's lines, `goldText(line)` a line's words without its button, and
  `goldOverrule(line)` its overrule's button.
- `controller` drives the worker's fake controller, and `conditions` reads what the gold bar reads
  ([`work.md`](work.md)).
- `bridge` adds registrations to the worker's fake notification bridge and reads what they show
  ([`notifications.md`](notifications.md)).
- `links`: `set({ticket_url_template?, environment_link_base_url?})` sets the link settings for the
  spec, a setting left out unset, and unsets both after it, through `PUT /api/testing/links`, which
  answers only in testing mode and refuses what the boot refuses; `environment(id, name)` puts an
  environment on the record through `POST /api/testing/environments` ([`projects.md`](projects.md)).
- The page objects `handleStep`, `profile`, `projectList`, `projectHead`, `timeline`, `overlay`,
  `sessionLog`, `panel` and `chat`, and `projects` and `chats` ([`projects.md`](projects.md),
  [`timeline.md`](timeline.md), [`work.md`](work.md), [`documents.md`](documents.md),
  [`chats.md`](chats.md)).
