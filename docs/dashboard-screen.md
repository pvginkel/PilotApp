# The dashboard screen

The analysis dashboard is the app's second screen, beside Projects, off a phone: view tabs, each
holding one view whole, a view's scope above its chart, and the chart in a card whose head is the
view's toolbar. Every figure on it is the engine's answer ([`dashboard.md`](dashboard.md)): the
page reads a view's state, writes it, and draws what the server answers, computing no figure. Its
code is `frontend/src/components/dashboard/`, the hooks it reads through in `frontend/src/hooks/`
(`use-view-tabs.ts`, `use-dashboard-view.ts`, `use-walk-reads.ts` and their neighbours), and
`frontend/src/lib/dashboard/`, the parts with no DOM: the state's grammar, its moves, its words and
the charts' geometry.

## The screen in the shell

The top bar's tabs, Projects and Dashboard, say which screen shows, and the address's hash says it
too: the dashboard shows where the hash is `#dash` or begins `#dash/`, over the app's path at hand,
so that the project behind stays matched by the router. The two screens share one box, the one out
of sight laid out of the flow, its visibility off and inert, and the dashboard, no route, is
loaded at its first opening and never taken down, so that each keeps its place, its scroll and what
it has read; behind the dashboard the Projects screen shows nothing to what reads "this page shows
a project", and on a phone there is no dashboard ([`ui.md`](ui.md#the-shell)). The bare address
keeps its hash through its step to the remembered project, and sign-in's redirect carries the hash
too (`auth-redirect.ts`), so a dashboard link opened cold loads the page behind it as well.

Out of sight the dashboard still hears the walk's event and reads again what it shows
([below](#kept-current)).

## The address and its history

What the hash names (`placeOf`, `lib/dashboard/address.ts`), read off the address as the browser
holds it, never the router's decoded hash, in which a value's `%26` would read as `&`:

- `#dash/<tab>/<state>`: a view tab and the state it shows, in the engine's grammar
  ([`dashboard.md`](dashboard.md#a-views-state));
- `#dash/<tab>`: a tab on the new tab's panel;
- `#dash`: no tab named, the tab at hand as it was left, the panel at the first opening;
- `#dash/<state>`: a link, which names no tab. A tab's id holds no `=` and a state always does.

**An entry of the dashboard's own** carries its tab in the history's state, `dash: {tab, view,
opened}`, the tab's id, the saved view it is of and the state it opened with, and none of the
app's state, whose `fromList` would redirect the project behind. Back and Forward to such an entry
move that tab's state alone, its name and what Reset goes back to staying; an entry of a tab since
closed opens it again as it was. **Any other entry is a link**, opened cold, typed or followed from
a reply: it shows the tab already showing its state, by its text, else by the server's normal form,
which the page asks, else a tab of its own, never another state in a tab that is open, and the
entry is written back in place as that tab's own, its id kept where it is free.

Which move adds an entry:

- **a new entry**: a press on a screen's tab, showing another tab, a new tab, a view opened from
  the panel, a time set, a drill or a step back up the path, a chip's change, a quick filter turned
  on or off, a threshold added, a By, a presentation or a color picked, and Reset;
- **the entry in place**: Relative, a sort, a measure added, removed, changed or moved, a ratio
  made joining the view's columns, a save, and a removed ratio taken out of the tab at hand;
- **none**: a tab's close and Close all, which replace the entry.

After a new build's reload, which keeps the URL and the history's state, the dashboard comes back
from them and the browser's store: its tabs, each one's state, its sorts and its scroll. What the
page alone held is gone, its answers among it.

## The view tabs

The tabs (`use-view-tabs.ts`) are kept in the browser, `viewTabs` in `browser-state.ts`
([`ui.md`](ui.md#what-the-browser-remembers)): `tabs`, each `{id, view, opened, now, sorts,
scroll}` in the order opened, and `seen`, their ids in the order they showed, the latest first, the
first the tab at hand. `view` is the saved view the tab is of, by its id and name, `opened` the
state it opened with, `now` its state as the address writes it, never normalised, `sorts` the sort
it remembers for each By ([below](#the-measures)) and `scroll` where it was scrolled to. They are
read once as the dashboard first opens in the page and written whole on every change, so two
windows are never kept in step. A new tab's id is four lowercase letters and digits.

**The tab line** (`view-tabs.tsx`) is the document tabs' form ([`documents.md`](documents.md)): a
tab is its presentation's icon and its name, its saved view's, else its drill's last level's, else
its By's, "New view" on the panel; its square-x or the middle button closes it; Close all (copy-x)
and copy-plus, a new tab on the panel, stand at the right. Closing the tab showing shows the one
seen before it, a new tab on the panel where none is left. With one tab there is no line: the tab
stands at the global toolbar's left, its close going back to the panel, and copy-plus ends the
toolbar.

**A tab out of sight keeps its answers** for as long as it is open: it holds its view's queries
without reading them, so the walk's event leaves them stale and they are read again as the tab is
brought back. Its scroll, the main area's or the table's, is kept 200 ms after a scroll and as it
leaves, and set back as its view is drawn, the view growing to it.

**The new tab's panel** (`views-panel.tsx`) has no chart, its block centred in the panel's height:
a head row that stays, with a find field, which filters both lists on the name, Esc clearing it,
and Start from scratch, the barest view that draws, `t=qw&by=project&m=cost.sum&col=none`, this
quota week by project with cost alone; under it System views at the left and Saved views at the
right, each scrolling on its own under its heading, stacked, System views first, where the panel
is 760 px wide or less. In each the starred come first, in the order starred, then the rest in the
server's order; a row's tooltip is what the view draws, in words (`describe.ts`), "By Project · All
time · Cost, Tokens", and its note; a click opens the view in that tab, forgetting the sorts it
remembered. A saved view's row has, on hover and on focus, its rename, typed in place, its remove,
behind a dialog, and its star; a system view's its star alone. The lists are everyone's, read again
each time the panel shows.

**Save view and Reset** stand at the global toolbar's right (`save-view.tsx`), with no Refresh: the
screen reads again by itself. Save view's pane asks a name, at most 80 characters, the field holding
the name of the saved view the tab is of; under it a saved view's name reads `Replaces the saved
view "<name>".` and a system view's "A system view has this name: yours is saved beside it, in
Saved views." The save keeps the tab's state whole for everyone, and the tab takes the view and the
state saved as what it opened with, its entry in place; its toast carries the parts the server
dropped. Reset takes the tab back to what it opened with, its saved view, the start from scratch or
a link's state, forgetting the sorts it remembered, and is there to press only where the tab's state
differs from it in the server's normal form.

## The scope

Above the card, in one line (`scope.tsx`): the drill path, the chips and "+ Filter"; under it the
quick filters'. The global toolbar holds the view's time after the one view's tab.

- **The time picker** (`time-picker.tsx`, `lib/dashboard/time.ts`). Collapsed, the time in a few
  words: "Quota week 48" for this, the last and a picked quota week, a range's label, "Last 7 days",
  or a range's days, "7 Nov – 13 Nov"; its title the window the answer read, exactly. Its popover
  has From and To over a month's calendar with Apply, each typed day first, "12 Nov 2026",
  "12/11", or ISO, a time of day optional, an empty one an open bound but never both, a pick on the
  calendar keeping a time only where one was typed, and Apply refusing a range that does not run
  forward; at the right the catalogue's ranges, All time among them, then its quota weeks newest
  first, each written by the instant it starts, `wk,<starts_at>`; at the foot "Times in <zone>" and
  when the running quota week started there. The catalogue's time is read again as the popover
  opens, since the weeks follow the usage readings.
- **The drill path** is one segmented bar: All, then a segment per level, its kind small and muted
  before what no level before it said. A row drills (`drilled`, `lib/dashboard/scope.ts`): a part's
  row is a level pushed onto the path, By moving to the part's next level, a level of a dimension
  the path holds replacing it and those under it; an attribute's row is a chip keeping its value,
  By moving to the attribute's next where the catalogue gives one, else to the parts' level under
  the path; a Call's row drills into nothing. A parent's segment goes back to it with the By and the
  presentation it had, All clears the drill, and the last segment is no button.
- **A chip**: its sign, a funnel where it filters and a diamond where it marks, which a press flips;
  its words, which open its pane; its values cut before "n more", every value in its tooltip, of a
  negated chip only "is not" marked out; its ×; at most 300 px wide. "+ Filter" lists the parts and
  the attributes, and no time, the time being the toolbar's. A dimension's pane lists its values in
  the view's scope without its own chips, each with its cost and rows, searched by the server; the
  values picked are kept with Is or Is not, as a filter or a mark. A threshold's words open its
  pane ([below](#the-measures)); the outlier rows' open nothing.
- **A value's words** (`useValueLabels`): a closed list's name from the catalogue, else the label
  the page was told by the row it drilled from or the pane it was picked in, else one looked up
  among the values of a scope that holds it (`labelQuery`): a level's in the view's time and the
  levels down to it, a chip's in the time alone. A label found is kept; the value's key shows until
  it comes.
- **The quick filters** (`quick-filters.tsx`): everyone's, in the order made, each a toggle in a
  chip's form, a diamond first where it marks, with its name, its count and its amount in its
  figure's format, read again each time the line shows, the counts asked again once where their
  answer lacks one the line lists, which another person made meanwhile. A press puts it in the
  view's `b=` or takes it out, filtering or marking as it was made, with no chip shown; one that is
  on narrows the others' counts; one off that counts nothing is muted and takes no press; its × on
  hover removes it for everyone after a dialog. The counts are a task's answer over the stream (`taskAnswer`,
  `lib/dashboard/task.ts`), heard before the task starts, a superseded read ceasing to listen while
  the task runs on, and never retried by itself. "Add as quick filter", at a dimension's pane's
  foot or an each-item threshold's, names one, its name filled with the chip's words, and makes it
  for everyone with the cost as its amount; the scope keeps no chip of it.

## The card

**The head** (`card-head.tsx`): at the left By and the presentation, one segmented control of Rows
and Table; at the right + Measure, Color, Relative and, with a table, Copy and CSV. A view of
another presentation, In order, Over time or Lanes, is drawn as its rows, neither pressed.

- **By** opens the parts and the attributes the catalogue gives, each with its count of values in
  the view's scope, asked as the list opens and each fact's counts shown as they arrive
  (`use-by-counts.ts`), those with one value or none behind "n hidden", which unfolds them muted,
  the By at hand and a favorite never hidden; a search; a star on hover, a favorite rising to
  Favorites at the top in the list's own order; one scrollbar, the search above it. The counts are
  kept for the scope they count, the time, the drill, the chips and the quick filters, so a By, a
  measure or a color changed asks none again.
- **Color** is By's list with no counts and none hidden, None and Token kind under a rule after it.
- **Relative** draws each figure as a multiple of its column's median among its peers, a look that
  asks nothing; greyed with a table.
- **Rows** (`rows-chart.tsx` over `rows-layout.ts`): the legend of the color's values, the
  headings' row, in sight while the rows scroll, the All row, then a row per value of the By, the
  first 40 and up to 1,000 with Show all, each label cut to its column and whole in its tooltip,
  each measure's bar split by the color, its figure and the peers' median as a tick. A By of Pilot
  sessions, Pilot turns, conversations or Calls gives each row a second line, its time. A row is a
  button where the view drills into its value.
- **Table** (`rows-table.tsx`, `table.ts`): the All row and the By's rows, a column per measure and
  its n, a row's share of All where the first measure sums or counts, and with a color the first
  stacking measure split over its values; it scrolls both ways inside the card, its headings in
  sight, and draws the first 1,000 rows. Copy and CSV take every row as its figures, unformatted,
  the instant after the label where the By's values have one: tab-separated to the clipboard,
  comma-separated to a file built on the page.

### The measures

The measures are the view's columns, with no chip (`measure-heads.tsx`, `use-measure-heads.ts`,
`lib/dashboard/measures.ts`):

- **A heading** is the measure's name in the page's words (`measureWords`), "Cost", "Cost per
  conversation (median)", "Conversations", a ratio's name, and sorts by its column, largest first
  and then the other way. The menu's sign and a × show under the pointer and while the focus is
  inside it, the last measure having no ×, the name cut short of them. The menu's sign opens its
  panel: the aggregate and the grain of a figure's measure, a ratio's sides, Filter… and, on a
  person's ratio, Edit…; a change leaves it open, and its ×, Esc or a press outside closes it. A
  heading is dragged to move its column, a line marking the drop and Esc putting it back.
- **+ Measure** leads the head's right group: each fact's figures under the fact's label, then
  Ratios, the built-in ones, then the stored, a person's with a pencil and a × on hover, one loaded
  from the workflow's file with neither, and New ratio… last. A measure picked is the last column.
- **A refused measure**: where the By takes some measures and refuses others, the card names the
  refused and the one that stands in for each where the answer gives one.
- **The sorts a tab remembers** (`sorts.ts`): a drill, a step back up or a By picked lands on the
  sort the tab remembers for the By it lands on, the first being its opened state's, else the
  default; a sort the person picks is remembered for the By at hand. Hiding a measure forgets a sort
  on it, and one changed in place, its aggregate or its grain, takes its sorts along.
- **A filter on a measure** (`threshold-pane.tsx`): Filter… opens the threshold's pane in the
  panel's place, its head's arrow the way back. It is on the By's rows, keeping or marking those
  that pass, or on each item of the measure's grain, "Each conversation", with Is or Is not; an
  operator and the engine's raw figure, a share's 30% being 0.3. A ratio's threshold is on the By's
  rows alone, an item having no ratio of its own (D290). Apply adds it as a chip, whose words open
  the pane again to change or remove it; an each-item threshold's pane makes a quick filter, the By's
  rows' none.
- **A custom ratio's form** (`ratio-form.tsx`), in + Measure's place or the panel's by Edit…: a
  name; a numerator and a denominator, each a figure under one of its aggregates over one of its
  grains, with filters of its own, picked in a dimension's pane among the dimensions that reach the
  side's fact, Is or Is not, with no mark and no quick filter; and its format, by default a share
  where the two figures have one format, else the numerator's (D284). A ratio made joins the view's
  columns; a change reads again every figure of a state that names it; a name another person's
  ratio has is said under the field. A remove asks in a dialog and takes the ratio out of every
  open tab, as it is now and as it opened: its column, a threshold on it and a sort on it, a view
  left with no measure taking cost.

## Kept current

A view's figures are queries keyed by its state in its normal form without its look-only parts
(`lib/dashboard/queries.ts`), under `FIGURES`, so a change of look asks nothing; each read takes
the query's signal, so one superseded is cancelled; none goes stale by age. A state from outside
the page is read through `GET /api/dashboard/address` first, and a normal form, once read, is its
own. The previous answer stays drawn while the next is on its way.

The collector's walk ends with `collection_changed` where it published something
([`collection.md`](collection.md#a-walks-end)), and `useWalkReads` then marks every `FIGURES` query
stale: those of the tab in view are read again in place, whichever screen shows, and the rest as a
tab brings them into view; a browser page that is hidden reads nothing until it shows. A read
under way as the event comes lands, and is read again then, so walks closer together than a read
never keep one from landing; a figure never answered waits for its Retry. As the stream comes back
up the figures are read again as on the event, and a task's read under way is asked again at once,
since its answer sent while no stream stood never lands. One walk so reads, once each, the tab in
view's rows and its quick filters' counts, and an open filter's pane's values with them; nothing of
a tab out of sight, no By's counts, which the next opening of the list asks again, no label and no
normal form (D288; `frontend/tests/dashboard/walk-reads.spec.ts`, priced in the engine's timing,
[`dashboard.md`](dashboard.md#the-timing)). The screen shows no age of its data and has no Refresh.

What a write of the dashboard's changed is all it reads again (`use-view-writes.ts`): the
catalogue's `stored` or `measures` part or the favourites it wrote, the quick filters' counts after
one is made or removed, every normal form after a quick filter's or a ratio's remove, and the
figures of the states that name a ratio changed. A write elsewhere in the app reads none of the
engine's: the figures and the labels carry `WRITES_PASS_OVER`, which the generated hooks' read
after a write passes over ([`timeline.md`](timeline.md)).

## What went well, what failed

What went well is a toast: a view saved or replaced, renamed or removed, a quick filter made or
removed, a ratio made, changed or removed. What failed is the banner under the global toolbar
(`banner.tsx`), the previous answer staying drawn: the latest failure not closed, its reason, the
engine's refusal's text among them, and a read's Retry, which asks again every read that failed; a
write's has none, and each write's own failure replaces the query client's toast. A read of the
scope's, a value's label, a pane's values or By's counts, stands in the banner while it stands
refused and its reader is drawn in the tab at hand (`ReadFailures`).

## Its words

US spelling; a billed call to the model a *Call*, a badge a *quick filter*. Dates are day first with
the month's short name and a 24-hour clock, "7 Nov 09:52", the year after the month where it is not
this one, in the engine's zone each answer names, never the browser's, the months' names the page's
own (`lib/dashboard/dates.ts`). A figure is written by its format (`figures.ts`): dollars to the
cent, tokens in thousands and millions, a count whole or to two decimals where it is a median or a
ratio, seconds as a duration, a share as a percentage, `–` where there is none. A label on a chart
is cut to its room to the pixel, in the font it is drawn in (`clip.ts`): a heading's to its column
at rest, short of its controls under the pointer.

## Testing it

The screen's specs are `frontend/tests/dashboard/`, through the page object
`tests/support/page-objects/dashboard-page.ts` (the `dashboard` fixture), which also counts the
page's reads of the engine (`rowsReads()`, `dashboardReads()`). `state.spec.ts` runs with no page:
it holds `lib/dashboard/state.ts` to the file of states (`backend/dashboard-states/states.json`,
[`dashboard.md`](dashboard.md#a-views-state)), each normal form read and written back as it is,
each refused one thrown as a `StateFormError` or read for the server to refuse. A spec reads exact
figures on the tally loaded on projects of its own (`collection.loadScenario('tally', …)`,
[`collection.md`](collection.md#testing-it)), over a time that holds the 4,040 s before its load,
and keeps the dashboard current with `collection.walk()`. `dashboardBounds` sets the engine's
timeout and hold on the worker's backend ([`dashboard.md`](dashboard.md#testing-it)), `savedViews`
and `customRatios` make what a spec needs through the API under names of its own, the workflow's
ratios loaded by a service user of the spec's, since every spec of a worker shares its record.
