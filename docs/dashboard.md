# The dashboard's query engine

One engine in the backend answers every view of the analysis dashboard from Pilot's record at the
query: the package `backend/app/dashboard/`, beside the record's engine ([`engine.md`](engine.md))
and not inside it, writing nothing. A view's whole state travels as the URL writes it, and the
server alone gives it its meaning, down one path: read, checked against the catalogue in every
part, written back in its normal form as the answer's `address`, planned, run under the engine's
bounds, shaped. No copy of the calls is kept and nothing is fed, so a change in the record shows at
the next read. The facts it reads are the transcripts' a collector publishes
([`collection.md`](collection.md)) with the caches each publication derives, Pilot's own Sessions
and Turns, the Prices and the Quota Weeks ([`record.md`](record.md#the-tables)). What
the dashboard stores, the saved views, quick filters, custom ratios and favourites, is
[below](#what-the-dashboard-stores).

Every route is under `/api/dashboard` (`backend/app/api/dashboard.py`,
`backend/app/api/dashboard_store.py`), for a signed-in editor ([`sign-in.md`](sign-in.md)):
`401` with no one signed in and `403` without the role, on every route below.

## The catalogue

What a view may name (`catalogue.py`), assembled and never written down (`assembly.py`): from
Pilot's code, its facts, joins, dimensions, figures, aggregates, built-in ratios and time ranges;
from the record's rows, a vocabulary's codes as a dimension's values and a version dimension per
Component, `<code>_version` (`claude_code_version`), with the marker of its versions; from the
stored configuration, the custom ratios and the quick filters. Every entry is a row of one shape
whatever source gave it, so a source that declares more adds rows and no shape. Pilot's code
declares nothing of a workflow: its dimensions are Pilot's own sessions, turns and work items and
the collector's facts.

- **The facts** (`facts.py`), each a table of the record or a union of a few, one row a thing that
  happened. **Call**: a Call, and each Turn of Pilot's whose conversation's main thread was never
  collected standing in with its own `cost`, marked `estimate`, with its Turn's tokens by the kinds
  a Turn counts and none of a Call's other facts. **Turn**: a Turn of Pilot's. **Event**: an Event,
  or an occurrence of one of the ten kinds another table records (a compaction, a rewind, a cache
  miss, a wait past the cache's lifetime, a model's fallback, a response cut at its token limit, a
  refusal, a saved output, a denied tool call and a failed hook), each at its own moment on the
  Call it is held on, with its `is_error` and one short detail from the fact behind it (D274): an API
  error's status, a saved output's tool and size, a denial's kind and tool, a hook's command, a
  compaction's trigger, a fallback's model. Every fact's row carries the thread, Pilot's Session
  and Turn and its moment, so a filter falls from one fact to another by the conversation.
- **The joins** reach the record from a fact's row, all of them many to one, so that a row is never
  lost or doubled. A Call's work item and project are reached through its Launch's Session.
- **The dimensions** (`dimensions.py`) are what a view is By, filtered on and colored by: the parts
  `project`, `psession` (a Session of Pilot's), `pturn`, `sitting`, `conversation` and `call`; the
  attributes `source` (`work`, `pilot` or `chat`), `work_type` (`chat:<kind>`, `conversation`,
  `job:<trigger>`, `clarification`, `research`, `claimed` or `work`), `session_kind`,
  `turn_cause`, `person`, `failed`, `environment`, `repository`, `agent_type`, `sub`, `model`,
  `effort`, `stop_reason`, `miss`, `miss_cause`, `past_ttl`, `rewind`, `compaction`,
  `compact_trigger`, `estimate`, `event_kind`, `event_error` and the version dimensions; the times
  `qweek`, `day`, `weekday` and `hod`, the last three derived in `DASHBOARD_ZONE`; and the orders
  `session_start` and `turn_seq`. A two-valued dimension's values are `1` and `0`. A sitting is the
  threads on no project that follow one another within `DASHBOARD_SITTING_GAP_SECONDS`, keyed by
  the first one's first Call.
- **The figures** (`measures.py`) are numbers of one fact's row: `cost`, `tokens`, `calls`,
  `misses`, `miss_cost`, `past_ttl`, `compactions`, `rewinds`, `ctx` (the context's tokens),
  `waited`, `took`, `turns`, `turn_time`, `failed_turns`, `reported_cost`, `events` and
  `error_events`. A measure is a figure under an **aggregate**, `sum`, `median`, `mean`, `max`,
  `p90` or `count`, at a **grain**: any part, or a fact's own rows. A figure says how an item takes
  its rows together, a sum but for `ctx`, the largest.
- **The built-in ratios**: `overhead`, the cost of Pilot's chats, jobs and runs over that of its
  work items, what ran outside Pilot in neither; `miss_share`, the misses' cost over all; and
  `per_call`, cost over Calls. A stored ratio joins them ([below](#what-the-dashboard-stores)).
- **The time ranges**: `today`, `d2`, `d7`, `qw` (the running quota week), `lqw` (the one before
  it), `l2`, `l4`, `l8` and `all`, each a unit of days or quota weeks, a count and a step back.
- **The markers**: a version marker per Component, a line where a version was first seen.

**The process keeps its catalogue** (`CatalogueService`, the container's `catalogue_service`)
until something it was assembled from changes: a publication that writes a vocabulary's row, a
write of a quick filter or a ratio, and a load of the workflow's views and ratios each drop it
after their commit, and the next read assembles it again. A stored ratio or quick filter is offered
only where what it names reads under the rest of the catalogue, its measures, its chip and its
amount's figure, and a ratio only under a key no built-in ratio has: one that does not is left out,
so a state naming it drops it with a note.

**`GET /api/dashboard/catalogue?part=`** answers one part: `dimensions`, each with its closed list
of values where it has one and the markers; `measures`, the facts, figures, aggregates, grains and
ratios; `time`, the ranges, the zone and the sitting's gap; or `stored`, the saved views with their
addresses and every quick filter and stored ratio row with whether the catalogue offers it. A part
it does not have is a `400`.

| Setting | Default | |
|---|---|---|
| `DASHBOARD_ZONE` | `Europe/Amsterdam` | the IANA zone the day, the weekday and the hour are derived in; checked at the load |
| `DASHBOARD_SITTING_GAP_SECONDS` | 14400 | the gap between one transcript's last Call and the next one's first at which a sitting ends; above 0 |

## A view's state

A view is one form, its state, as the URL carries it after `#dash/` (`state.py`), in the mockup's
grammar with what the record adds to it:

```text
t=<range>|wk,<week's key>,…|c,<from>,<to>   by=<dimension>
p=order[,<order dimension>]|time,<grain>|lanes|table     (rows: absent)
m=<measure>, in order    dr=<level>, outermost first    c=<chip>, in order
b=<quick filter>,…    col=<dimension>|token_kind|none    o=<dir>,<column>
d=items    sel=<value>    ig=<grain>    it=<grain>,<key>    call=<call>
f=<dimension>:<key>    rel=1    mk=<kind>,…|none    dw=<part>:<value>,…
roll=<items read>,<items before it draws>    lit=<value>,…    ev=[-]<kind>,…
z=<from>,<to>

measure := <figure>.<aggregate>[.<grain>][(<filter>;…)] | r:<key>
           | r:<name>:<simple>/<simple>
filter  := [!]<dimension>=<value>|<value>…
level   := <part>:<value>[@<dimension drilled from>]
chip    := [~][!]<dimension>:<value>,… | [~]@rows,<op>,<number>,<measure>
           | [~][!]@items,<op>,<number>,<simple> | [~]@outliers
```

A value is percent-encoded, a bare `~` is none, and `~` before a chip marks what it keeps rather
than filtering to it. A value is read by its dimension's type: a whole number, an id, a date, an
instant with its zone, or a text, a closed list's codes alone. A quota week's key is the instant it
starts, `2025-01-02T10%3A00%3A00Z`, never its label, which two weeks can share
([`usage.md`](usage.md#the-quota-weeks)); a bound of `c` is a date or a time of day in the
catalogue's zone, a date-only end holding its day. `roll` is the length of a series' rolling median
and its band, the items it reads and the items before it draws, `10,15` where the state names none.
`d`, `rel`, `mk`, `dw`, `lit`, `ev` and `z` are look-only parts, which change what the page draws
and no answer.

**Its normal form** (`write`) makes two spellings of one view one address: `wk`, `b`, `mk`, `lit`
and `ev` sorted with no repeat, the chips, levels and measures in their order, and `t`, `by`, `m`
and `col` always written. **An entry**, a state that names its focus alone, `f=<dimension>:<key>`,
the app's way into the dashboard on one thing, is filled in from the record (`AddressService.entry`):
its focus's path as the drill, By the focus's next part in rows, cost and the cache misses, and the
quota weeks its Calls fall in, all time where it has none.

**A refusal** (`refusal.py`) names every fault at once, each on a line with its part as written,
what is wrong, the nearest names by spelling and what is allowed there, and ends on a correct
example of each kind of part refused: `400` `STATE_REFUSED`, the text whole in `error`, built in
this one place for the screen and a tool alike. A part the view cannot have is a fault, among them a
presentation its By lacks, a call selected outside an opened conversation, values lit with no color
and a number that is not finite. What a state names by key and is gone, a quick filter or a ratio,
is dropped with a note, never a fault: every answer carries `notes`, one per part dropped.

**`GET /api/dashboard/address?state=&fix_time=`** answers `{address, look, notes}`: the view's address,
`#dash/` and the state in its normal form, the state taken with `#dash/` before it or without, its
look-only parts as that form writes them, and
the notes. `fix_time` writes the time range as it stands now (`fixed`): a range of days as its two
dates, a range of quota weeks as their keys, "this quota week" the latest week the record holds, so
that a link shows the time an answer was about.

**The file of states**, `backend/dashboard-states/states.json`, holds states as written, each with
its normal form, its look-only parts, its notes and the query it means, the planner's, or the
refusal's exact text. `tests/dashboard/test_states.py` reads it whole; its `about` says what each
entry carries.

## The answers

Each answer route takes the state as `state` and runs the path above, the planner
(`planner.py`) reading the facts the measures need, the joins the By, the color, the drill and the
chips name, and each measure's grain, and the statements (`statements.py`) one grouped scan per
fact, never a distinct count by a sort. Every answer carries `address`, `look` and `notes`, and its
times as instants with the engine's zone beside them, never text: the page writes them.

| Route | Answers |
|---|---|
| `GET /api/dashboard/rows` | each measure on every row of the By and on the All row, split by the color, in the view's sort (`rows.py`) |
| `GET /api/dashboard/series` | a view in order or over time: its points along the axis, each measure as a panel with its dots, outliers, rolling band and median, and the markers (`series.py`) |
| `GET /api/dashboard/series/events` | a series' events strip: each point's events by kind and how many are errors, apart from the series so that it never holds the chart up (`strip.py`) |
| `GET /api/dashboard/lanes` | a lane per row of the By that holds Calls, with each measure, its waits and its events (`lanes.py`) |
| `GET /api/dashboard/items` | the items of the row selected, else of every row, at the view's grain, or an opened item's calls (`items.py`) |
| `GET /api/dashboard/conversations/<transcript_id>/calls` | every Call of one thread over all time, in its file's order, each with its events and whether the view's window and scope hold it; `404` for a thread the record lacks |
| `GET /api/dashboard/values?dimension=&search=` | one attribute's values for a filter's pane, at once ([below](#the-two-counts)) |
| `POST /api/dashboard/counts/attributes`, `…/counts/quick-filters` | `202`: By's counts and the quick filters' counts, each a task ([below](#the-two-counts)) |
| `GET /api/dashboard/conversations/<transcript_id>/reading`, `…/reading/texts`, `…/reading/block` | a conversation in the reader ([below](#a-conversations-reading)) |

- **The rows.** A row is a value of the By any statement reads, `n` its items with a value. A ratio
  is its two sides divided in the process, none over none or zero. The rows are in the state's sort,
  else by the first measure, the largest first, at most 2,000 with the count of all; the color's
  values are those the stacking measures hold on the All row, past 12 folded into one. A measure's
  `median` is its rows', the rows holding the focus left out. A measure whose fact has no By is
  refused with why, and answered by its stand-in where a figure of a fact that has the By stands
  for it (`Figure.stands_for`).
- **Thresholds and the outlier rows.** A chip on the By's rows, `@rows`, keeps or marks the rows
  whose measure passes its number, and `@outliers` the rows whose first measure is an outlier among
  them, above Q3 + 1.5·IQR and at least twice the median, none among fewer than five values or on a
  median of zero or less (`outliers.py`). Both are judged on every row before any is dropped, and
  the All row is answered again from the rows kept. They narrow the items, the lanes and the series
  to the rows they keep, and never By's counts or a filter's pane, which keep the scope before them
  (D273). A row is marked where every mark on the view holds.
- **The series** takes the By's order dimension in order, the grain over time, the By then playing
  no part. A sum or a count is a column per point, stacked by the color; a measure over the items of
  a part other than the points' is the items' dots, at most 4,000; any other one dot a point. The
  band is the rolling median and its quartiles over `roll`'s items, warmed on the members or items
  before the window under the scope alone; the markers the latest 24 of a kind within the axis.
- **The lanes**, at most 200, the earliest first: a wait is a gap of 60 s or more between a lane's
  rows, past the cache's lifetime where the Call ending it waited past it; an event carries its
  thread, the Call it is held on and that Call's cost, and its detail (D274). Past 12,000 waits and
  events in all they merge at the whole span's resolution, the span over 4,000, doubled until they
  fit, a merged one saying how many it holds and an event of more than one carrying no detail.
- **The items** are those of the state's `ig`, else the first measure's grain, else the
  conversations; with an item opened (`it`) its calls; at most 2,000, the earliest first, with the
  count of all. Each carries the figures the catalogue gives its grain, and an item that is one row
  of a fact, a call or an event, the dimensions shown with it; an event's key is its kind and the id
  of the row that records it, `cache_miss:42`.
- **A conversation's calls**, at most 2,000, are what the reader's calls are. *Took* runs from a
  Call's sending to its completion, none where Claude Code recorded no sending time (D275);
  *Waited* is the Call's `waited_seconds`, from its predecessor's completion to its own sending, or
  to its completion where it has no sending time, so the two never overlap.

## The bounds

Every read of the engine runs inside `Bounds.read` (`bounds.py`, the container's
`dashboard_bounds`):

- **A read-only transaction of its own under one deadline.** A read commits the caller's
  transaction first, so a caller with writes makes them after, then waits for a slot holding no
  connection, opens a read-only transaction and rolls it back at its end. The deadline is
  `DASHBOARD_STATEMENT_TIMEOUT_SECONDS` from the moment the state's check begins, and every read of
  one answer shares it, an entry's read and the answer's own: before each statement is sent its
  `statement_timeout` is set, `SET LOCAL`, to what is left. So the wait for a slot and the
  statements together end within the timeout, by default below the 60 s the proxies in front of
  `/api/` wait for an answer. Both are per transaction, as the pooler in transaction mode requires
  ([`deployment.md`](deployment.md#the-database)).
- **`work_mem` is never raised**: every statement runs at the cluster's own.
- **Statements at once**: each read holds one of `DASHBOARD_STATEMENTS_AT_ONCE` slots, which must
  be fewer than the app's pool holds, its size and its overflow, else the engine's first read fails
  on the setting (`ConfigurationError`); so a
  burst from several tabs leaves the pool to the rest of the app, and the slots cap the disk a
  burst's temporary files can take.
- **A refusal with a reason**, `409`, told apart by PostgreSQL's error code: `QUERY_TIMEOUT`, a read
  past the deadline, "its read ran past the engine's timeout of 45 s: a shorter time range or a
  narrower scope reads less", which a read that starts with nothing left of it gets at once;
  `QUERY_TEMP_FILE_LIMIT`, a statement the cluster ended at its `temp_file_limit`; and
  `QUERY_BUSY`, no slot freed within what was left.

The engine's statements run longer than the suite's statement cap and declare their own bound
([`slice-test-plan.md`](slice-test-plan.md)).

| Setting | Default | |
|---|---|---|
| `DASHBOARD_STATEMENT_TIMEOUT_SECONDS` | 45 | one answer's reads, the wait for a slot and every statement together; above 0 |
| `DASHBOARD_STATEMENTS_AT_ONCE` | 2 | the engine's reads at once, each a connection of the pool; above 0 and below the pool's size with its overflow |

## The two counts

The counts that would slow every view are tasks (`counts.py`, `tasks.py`), on the app's task form:
the route checks the state, starts the task and answers `202` at once, `{task_id, status, address,
look, notes}`, running no statement but an entry's; the task's events go over the stream the page
holds, to the caller alone, as `task_event`. A task is held to the engine's timeout one read at a
time, never whole, so no count is refused for the task's length.

- **By's counts**, `POST /api/dashboard/counts/attributes`, asked when By's panel opens: each
  dimension's count of values in the view's scope, none counting as one, under every chip, its own
  included, so that a drilled project reads one; an order dimension counts as its part. Each fact
  is counted in a read of its own, and its counts come as a `progress_update` whose `data` holds
  every count so far, then every count as the task's result.
- **The quick filters' counts and amounts**, `POST /api/dashboard/counts/quick-filters`, asked with
  the view: each quick filter's count of what it keeps and its amount's figure summed over it, in
  the view's scope and under the quick filters that are on, so that one that is on narrows the
  others'. One on the By's rows, the outlier rows' or a threshold's, counts the By's rows it keeps.
  Its result comes whole.
- **A filter's pane**, `GET /api/dashboard/values?state=&dimension=&search=`, answers at once: one
  attribute's values in the view's scope without the attribute's own chips, so that its other
  values show, each with its rows and their cost, the largest cost first, a time's in its order, at
  most 200 with the count of all; `search` keeps those whose label or key holds its words.

A task's refusal is its `task_failed`, its `error` the refusal's text.

## A conversation's reading

The collector serves a conversation's reading, its texts, to the backend alone
([`collector.md`](collector.md#the-reading)), and the backend keeps it (`readings.py`,
`ReadingsService`, the container's `readings_service`, one a process):

- **Asked at every read.** Each read of a Transcript asks the collector at
  `COLLECTOR_URL`'s `readings/<session_id>[/<agent_id>]`, under `COLLECTOR_TOKEN` and the reading's
  version, conditionally with `If-None-Match` where a reading is kept. `304` serves the kept one,
  `200` keeps the new one in its place, and `404` `TRANSCRIPT_GONE` drops it and answers the
  transcript gone. Any other answer, or none, is a refusal with why, which leaves a kept reading
  kept and logs a warning naming the Transcript; an empty `COLLECTOR_URL` or `COLLECTOR_TOKEN`
  refuses every read. Two reads of one Transcript at once share one ask.
- **Kept on scratch storage, never in the database** (`ReadingCache`): one file a Transcript, named
  by its id, the collector's validator its first line, then the reading as the collector gzipped
  it, in `DASHBOARD_READINGS_DIR`, at most `DASHBOARD_READINGS_MAX_BYTES` of them, the least
  recently read evicted first and the reading just kept never, so one reading over the bound is kept
  alone. A process takes the files a process before it kept. Each stage mounts a scratch volume of
  the pod's there ([`deployment.md`](deployment.md#what-runs)).

The reader's routes (`reader.py`, `ReaderService`) take a conversation by its transcript's id and
the view's state, and read the calls a conversation's calls answer, so that the reader's calls are
the chart's, each joined to its reading's blocks by its `message_id`:

- **`GET …/conversations/<transcript_id>/reading?state=&batch=`** answers a batch of 200 calls with
  their blocks, each text of a block cut to its first 1,500 characters, a cut block carrying its
  full `length`, a tool call's input cut with its texts taken together; with no `batch`, the batch
  that holds the call the state selects. Its head says `status`, `served`, `gone` or `refused`, and
  `why`; `total`, `held`, and `stopped` where the reader stopped at 2,000 calls; `batches`, in the
  order to take them, the selected call's first; `characters`, the full texts' sum, and `whole`,
  whether that is 2,000,000 or less. A gone or refused reading answers `200` with no batch.
- **`…/reading/texts?state=`** answers every block a batch cut, whole, in one answer where `whole`
  holds, and none where it does not.
- **`…/reading/block?state=&call=&part=&index=`** answers one block whole as it opens, by its call,
  its part, `received`, `sent` or `after`, and its place in it; `404` for a block the reading lacks
  on a call the reader holds.

What follows the reading's last Call stands on that Call where the reader holds it; a Call the
reading lacks is `held` false, with no block. The reader's reads of the record run under the bounds
and its ask of the collector after them, holding no slot.

| Setting | Default | |
|---|---|---|
| `COLLECTOR_URL` | empty | the base URL of the collector's readings; empty refuses every read of a conversation |
| `DASHBOARD_READINGS_DIR` | empty | the folder the readings are kept in; empty keeps them in a temporary folder of the process's own |
| `DASHBOARD_READINGS_MAX_BYTES` | 268435456 (256 MiB) | the readings' bytes kept at most, as the collector compressed them |

## What the dashboard stores

The saved views, quick filters and custom ratios everyone shares, and a person's favourites
(`backend/app/services/dashboard_store_service.py`, `DashboardStoreService`; the tables in
[`record.md`](record.md#the-tables)). A stored expression is one value, kept in the
normal form a state writes and read whole; a key it names that is gone is dropped at the read, with
a note. The server holds no view tab and nothing of a By's look.

- **The saved views** are the system views and those people saved. Saving a view's whole state
  under a name, its band's length with it, replaces the view a person saved under that name, its
  id and stars kept (`200`), or saves a new one (`201`); a system view of the name stands beside
  it, a name standing once among the system views and once among the saved. A rename to another
  saved view's name is a `409`. A system view is the system's: nobody renames, removes or replaces
  one, `409`, and a person's star is all they change.
- **The quick filters** are a chip under a label, filtering or marking as written, with a figure
  whose sum shows beside its count, made by anyone under a code the server draws, four letters and
  digits, a letter first, never changed, and removed by anyone; one the dashboard shipped with stays
  removed. Revision 0054 wrote the five once: *Waits past the cache TTL* (`past_ttl:1`, the misses'
  cost), *Cache misses* (`miss:1`, the misses' cost), *Compactions* (`compaction:1`), *Outlier rows*
  (`@outliers`) and *Expensive calls* (`@items,gt,1,cost.sum`, their cost).
- **The custom ratios** are two measures under a name. One a person makes is anyone's to change and
  remove, its key made from its name, `person_` and the name's words within 24 letters, `_2` on
  where taken, a space no built-in or loaded ratio's key is in; a name two ratios of people's
  share is a `409`. A loaded ratio is nobody's to change or remove, `409`.
- **A person's favourites** are their stars, on a system view and a saved one alike, in the order
  starred, and their dimensions in By's list, any dimension, and in Color's, a part, an attribute
  or the token kind; one the catalogue no longer offers there is left out of the read. A favourite's
  route is a person's alone: `409` for a caller with no handle or a service user.

| Route | |
|---|---|
| `POST /api/dashboard/saved-views` `{name, state, note?}` | save a view, `201` made or `200` replaced, with the notes |
| `PATCH`, `DELETE /api/dashboard/saved-views/<id>` | rename, remove a saved view |
| `PUT`, `DELETE /api/dashboard/saved-views/<id>/star` | the caller's star |
| `GET /api/dashboard/favourites` | the caller's stars and favourite dimensions |
| `POST /api/dashboard/favourites/dimensions` `{menu, dimension}`, `DELETE` with the two as its query | a favourite in By's list (`by`) or Color's (`color`) |
| `POST /api/dashboard/quick-filters` `{label, chip, amount?, note?}`, `DELETE …/<id>` | make, remove a quick filter |
| `POST /api/dashboard/custom-ratios` `{name, numerator, denominator, note?}`, `PUT`, `DELETE …/<id>` | make, change, remove a person's ratio |
| `PUT /api/dashboard/workflow` `{views, ratios}` | the workflow's load, the service user's alone ([below](#the-workflows-load)) |

A state, a chip or a ratio's side with faults is the refusal's `400`, every fault of both sides of
a ratio named at once. A write of a quick filter or a ratio drops the process's catalogue once it
has committed, so that the next read offers what it wrote; a saved view is read at each call.

**Pilot's own system views** name nothing of a workflow (`backend/app/dashboard/views.py`):
*Projects*, each project's cost, tokens, cache misses and largest context over all time, colored by
work type; *Work types*, the same By work type, colored by model; and *Where the week went*, the
cost of each of the last eight quota weeks and the overhead ratio, colored by source. A deploy
makes the stored ones what the release holds, matched by key, a changed one in place with its
stars, after the migrations ([`deployment.md`](deployment.md#what-runs)), and so does the dev
seed's load.

### The workflow's load

The workflow's system views and its ratios, those that name a declared kind or value, come from a
file the workflow's plugin keeps; Pilot's image holds nothing of it. The plugin's command reads the
file and hands its entries to the tool `load_workflow_views` on the projects surface
([`mcp.md`](mcp.md#the-projects-surface)), which calls **`PUT /api/dashboard/workflow`** as the
service user (D272); a person calling it is a `409`. After a load the workflow's views and ratios
are the entries, each by its key: an entry a row holds changes that row in place, a view keeping its
stars; a new key is added; a row whose key the entries no longer hold is removed, a view's stars with
it. At most 200 of each.

Every entry is checked before any is written, and a load with a fault anywhere is refused whole,
every fault named after its entry, `view "<key>"` or `ratio "<key>"`: a state or a measure that
does not read, a key on two entries, a name an entry before it has, a view under the name of one of
Pilot's own views, a ratio under a built-in ratio's key or one that begins `person_`. A view's state
may name a ratio of the same load. A view's state and a ratio's sides are kept in their normal form,
a view's band as its state writes it; a part of a view's state a read drops is a note in the answer,
`{views, ratios, notes}`, each of the first two the rows added, changed and removed.

## The timing

`backend/tools/timing/` times every part of the engine on a generated history, at production's
database settings: `instance.py` makes a PostgreSQL of its own in the prd cluster's `development`
namespace and removes it after (`instance.yaml`, run in `cexec iac`); `history.py` writes a history
of a given number of Calls in the scenario's invented words, through the app's own publication;
`parts.py` reads each part through the app as the page reads it, over all time and over a quota
week, and runs each statement again under `EXPLAIN (ANALYZE, BUFFERS)`, writing
`results/<calls>.json`; and `report.py` renders the report, `report.md`, from two results. The
report gives each part's time at both sizes, the size at which it passes two seconds, the record's
size on disk and the burst, and the engine's two defaults above are read off it. `tests/tools/`
pins the tools.

## Testing it

The engine's suite is `backend/tests/dashboard/`, a module a file of the package, with the routes'
in `tests/api/test_dashboard.py` and `test_dashboard_store.py`, the store in
`tests/services/test_dashboard_store_service.py` and `tests/models/test_dashboard.py`, and the
load's tool in `tests/pilot_mcp/`. `tests/support/dashboard.py` assembles a test's own catalogue
and reads its answers; the suite drops the process's catalogue before every test. Every test
database holds Pilot's three system views and the five quick filters, the price file's Prices and
the fixed rule's quota weeks, which the revisions and `post_migration_hook` write into the suite's
template. The load is pinned
on an invented file of the workflow's, `tests/fixtures/workflow_views.json`. A test of a statement's
plan reads it on a clone of the run's template, as the rows earlier tests rolled back on a worker's
database weigh in the planner's estimates. The refusals' texts are pinned in
`tests/dashboard/test_refusal.py` and the file of states.

**The fake collector** (`backend/app/services/fake_collector.py`, `FakeCollector`) serves the
collector's readings route as the collector does, its bearer, its version's `426`, `404`
`TRANSCRIPT_GONE`, `304` and the gzipped reading with its `ETag`, so that no suite asks a collector.
Under pytest the fixture `fake_collector` serves it on a free port and `readings_service` reads it
into the test's `tmp_path` (`tests/conftest.py`, `tests/support/fake_collector.py`). For Playwright
it is mounted at `/api/testing/collector`, in testing mode on a stage other than prd, and each backend's
`COLLECTOR_URL` and `COLLECTOR_TOKEN` point at its own mount
(`frontend/tests/support/backend-env-extensions.ts`). It serves the readings of the scenario a load
handed it, each the collector's own reading of the scenario's files, so a reading's calls are the
facts' ([`collection.md`](collection.md#testing-it)), and those a test hands it. A test drives it
through its verbs, in process or as `POST <base>/fake/<verb>`: `gone` makes a conversation's file
gone, `too_large` grows its reading past the reader's bounds, `refuse` refuses every ask (`426` or
`500`), and `asks` lists each ask taken with the validator it named.
