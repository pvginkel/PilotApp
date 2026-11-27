# The engine's timing (F154.9)

Every part of the dashboard's engine was timed on two generated histories, at production's
database settings. Over all time, every part passes two seconds by 1.7 million Calls, most of
them before 800,000. Over a quota week, the rows, the medians, a pane's values and the series by
weekday and by hour answer in under a second at both sizes, but for the rows under a condition on
each conversation, 3.9 s at three million; the events strip, the lanes and a conversation's calls
take more than two seconds over any range at both sizes. At three million Calls, By's counts over
all time are refused at the database's limit on temporary files.

The engine's timeout and its statements at once take their defaults from it: 45 s for a whole
read and 2 statements at once (below).

The walk's event, every 30 s, has a page with the dashboard open read its view's rows and the
quick filters' counts again: 2.2 to 2.7 s over a quota week and 4.9 to 6.1 s over all time at
631,341 Calls; 15.9 to 19.3 s and 35.1 to 41.6 s at three million, over all time longer than the
walk itself (below).

The labeller's part of the engine, a kind of work's parts, the four rules over work units and
the lanes' runs, was timed later with Pilot's inventory, on two histories of its own whose every
conversation carries labels ([The labeller's part](#the-labellers-part)).

## How it was timed

- **The database**: PostgreSQL 18.3 on production's image, `shared_buffers` 256MB, `work_mem`
  4MB, `temp_file_limit` 2GB, a 2Gi memory limit and three CPUs, a StatefulSet of its own in the
  prd cluster's `development` namespace (`instance.yaml`), made for the timing and removed after
  it.
- **The storage was not production's.** The instance's volume was Ceph RBD, network storage.
  Production's PostgreSQL stands on a node-local ZFS volume, read through ZFS's cache on the
  host, outside the pod's 2Gi. A read that goes past `shared_buffers` to disk, or a sort or a
  hash that spills, was timed on other storage than production's, which may read it faster or
  slower. At 630,000 Calls the record, 0.45 GiB, sat in the page cache; at three million, 2.04
  GiB, it did not, and the burst shows the reads bound by the disk.
- **The histories**: the scenario's invented words, written by `history.py` through the app's
  own publication, 631,341 Calls over 71 days and 2,976,231 over 328 days. The first is the count
  of 2026-11-14 with every session collected. Pilot's stand-in conversations are never
  published, so the record holds a little under the size asked.
- **The parts**: `parts.py` read each through the app as the page reads it, over all time and
  over the last whole quota week (Where the week went over its last eight weeks): once to warm,
  then three times, the median taken, or once where the first read took over 20 s. Each
  statement was then run again under `EXPLAIN (ANALYZE, BUFFERS)`, whose own timing reads
  slower than the part's.
- **Timed before the names.** A Pilot session, a Pilot turn, a conversation and a Call were
  named after the timing, so that a statement that reads one's name now joins what it is read
  from: In order by Pilot session its Session's work item, chat and kind, and the lanes by
  conversation, a conversation's calls, the items of conversations and the conversations'
  values for a filter's pane each Call's thread. Every other part's statements read as they
  were timed.

Regenerate the tables with
`uv run python -m tools.timing.report tools/timing/results/630000.json tools/timing/results/3000000.json`.

## The record on disk

Production's volume is 10 Gi, and every database of the cluster shares it.

| | 631,341 calls | 2,976,231 calls |
|---|---:|---:|
| calls | 631,341 | 2,976,231 |
| transcripts | 22,604 | 106,787 |
| launches | 16,686 | 78,294 |
| tool_calls | 641,298 | 3,021,699 |
| events | 1,906 | 8,872 |
| compactions | 5,998 | 27,995 |
| sessions | 5,943 | 28,348 |
| turns | 7,932 | 37,546 |
| On disk | 0.45 GiB, 4% of 10 Gi | 2.04 GiB, 20% of 10 Gi |
| Calls from | 2026-09-13 | 2025-12-29 |

## Each part

"Passes 2 s at" is the Calls at which the line through the two times reaches two seconds: "below
631,341" where it took longer already, "beyond" where it would not within ten times the larger
size, "—" where it did not grow.

| Part | Range | 631,341, ms | 2,976,231, ms | Passes 2 s at | Slowest statement at 2,976,231, ms | Gone to disk at 2,976,231 |
|---|---|---:|---:|---|---:|---|
| Rows by project, five measures | all | 1,891 | 9,106 | 670,000 | 11,923 | none |
| Rows by project, five measures | lqw | 282 | 494 | 19,700,000 | 696 | none |
| The Projects view: four measures, colored by work type | all | 2,602 | 12,676 | below 631,341 | 18,762 | Sort to disk |
| The Projects view: four measures, colored by work type | lqw | 354 | 540 | 21,300,000 | 609 | Sort to disk |
| The Work types view: four measures, colored by model | all | 2,269 | 12,417 | below 631,341 | 13,762 | Sort to disk |
| The Work types view: four measures, colored by model | lqw | 319 | 451 | beyond | 502 | Sort to disk |
| Median, mean and P90 per conversation, by project | all | 2,099 | 14,064 | below 631,341 | 12,061 | Aggregate (Hashed) to disk; Sort to disk |
| Median, mean and P90 per conversation, by project | lqw | 349 | 710 | 11,400,000 | 504 | none |
| Rows by project under a threshold on the By's rows | all | 1,633 | 8,034 | 770,000 | 6,324 | none |
| Rows by project under a threshold on the By's rows | lqw | 331 | 678 | 11,900,000 | 490 | none |
| Rows by project under a condition on each conversation | all | 1,322 | 7,575 | 890,000 | 10,996 | Aggregate (Hashed) to disk |
| Rows by project under a condition on each conversation | lqw | 702 | 3,856 | 1,600,000 | 5,041 | Aggregate (Hashed) to disk |
| The attributes' counts (By's panel), a task | all | 19,472 | refused |  | refused | refused |
| The attributes' counts (By's panel), a task | lqw | 4,280 | 17,098 | below 631,341 | 15,870 | Hash in 2 batches; Hash in 32 batches; Sort to disk |
| The quick filters' counts and amounts, an each-item one among them, a task | all | 3,531 | 27,556 | below 631,341 | 23,109 | Aggregate (Hashed) to disk; Aggregate (Mixed) to disk |
| The quick filters' counts and amounts, an each-item one among them, a task | lqw | 1,949 | 15,408 | 640,000 | 19,447 | Aggregate (Hashed) to disk |
| An attribute's values for a filter's pane: the calls | all | 1,512 | 9,700 | 770,000 | 10,581 | Aggregate (Hashed) to disk; WindowAgg stored on disk |
| An attribute's values for a filter's pane: the calls | lqw | 196 | 399 | 21,500,000 | 344 | Aggregate (Hashed) to disk |
| An attribute's values for a filter's pane: the conversations | all | 600 | 3,799 | 1,660,000 | 4,652 | Aggregate (Hashed) to disk; WindowAgg stored on disk |
| An attribute's values for a filter's pane: the conversations | lqw | 118 | 274 | 29,000,000 | 277 | none |
| Over time by local day, colored by model | all | 1,875 | 9,884 | 670,000 | 10,111 | Sort to disk |
| Over time by local day, colored by model | lqw | 1,134 | 5,233 | 1,130,000 | 4,137 | none |
| Over time by local weekday, colored by model | all | 1,090 | 5,583 | 1,110,000 | 6,599 | Sort to disk |
| Over time by local weekday, colored by model | lqw | 185 | 327 | beyond | 334 | none |
| Over time by local hour, colored by model | all | 1,035 | 5,484 | 1,140,000 | 6,612 | Sort to disk |
| Over time by local hour, colored by model | lqw | 175 | 317 | beyond | 311 | none |
| Where the week went: by quota week, with the overhead, colored by source | all | 6,306 | 34,022 | below 631,341 | 48,912 | Sort to disk |
| Where the week went: by quota week, with the overhead, colored by source | l8 | 4,916 | 9,272 | below 631,341 | 7,515 | Sort to disk |
| In order: each Pilot session's cost by its start, with its band | all | 1,652 | 8,542 | 750,000 | 4,327 | Aggregate (Mixed) to disk |
| In order: each Pilot session's cost by its start, with its band | lqw | 1,482 | 7,309 | 840,000 | 3,977 | none |
| The events strip of the series by day | all | 3,860 | 17,745 | below 631,341 | 20,258 | Hash in 32 batches |
| The events strip of the series by day | lqw | 3,244 | 14,477 | below 631,341 | 14,965 | Hash in 32 batches |
| The lanes by project | all | 8,616 | 44,709 | below 631,341 | 19,907 | Hash in 32 batches; Sort to disk |
| The lanes by project | lqw | 3,841 | 15,971 | below 631,341 | 15,415 | Hash in 32 batches; Sort to disk |
| The lanes by conversation | all | 5,376 | 28,195 | below 631,341 | 18,351 | Aggregate (Hashed) to disk; Aggregate (Mixed) to disk; Hash in 16 batches |
| The lanes by conversation | lqw | 3,266 | 14,260 | below 631,341 | 14,560 | Hash in 16 batches |
| The items: the conversations of the rows a threshold keeps | all | 3,180 | 14,969 | below 631,341 | 8,678 | Aggregate (Hashed) to disk; WindowAgg stored on disk |
| The items: the conversations of the rows a threshold keeps | lqw | 599 | 1,147 | 6,600,000 | 459 | none |
| A conversation's calls: the longest thread's | all | 3,768 | 16,281 | below 631,341 | 18,012 | none |
| A conversation's calls: the longest thread's | lqw | 3,712 | 16,802 | below 631,341 | 17,927 | none |

## The burst

The Projects view over all time, read by one to four clients at once. At 630,000 Calls the
reads share the three CPUs: two at once take what one takes, three a little more, four nearly
twice as long. At three million every read added at once adds its whole time: the disk, not the
CPUs, bounds them.

| At once | 631,341 calls, ms | 2,976,231 calls, ms |
|---:|---|---|
| 1 | each 2,648 to 2,648, all 2,648 | each 12,323 to 12,323, all 12,323 |
| 2 | each 2,581 to 2,677, all 2,679 | each 22,093 to 25,498, all 25,500 |
| 3 | each 3,191 to 3,277, all 3,280 | each 37,331 to 37,641, all 37,642 |
| 4 | each 4,434 to 4,960, all 4,960 | each 44,054 to 46,912, all 46,913 |


## One walk

The collector's walk ends every 30 s on both stages, and one that published something sends the
walk's event to every person's connections, as every walk did in pilot-prd's busy hours of 21 to
26 November. On it a page with the dashboard open reads again, once, what its view in view shows
(`frontend/tests/dashboard/walk-reads.spec.ts`): the view's rows, the quick filters' counts and
amounts, a task, and while a filter's pane is open its values. It reads nothing of a view tab
out of sight until that tab shows, nothing while the browser page is hidden until it shows, no
By's counts, which By's list asks as it opens, no label and no normal form; a write the person
makes elsewhere in the app, a chat's message or a pause, reads none of them. The server keeps no
answer, so each person with the dashboard open reads as much again. The record sets no bar for a
walk: F154.9's two seconds is an answer's.

One walk for one page, each view's rows and the quick filters' counts as each was timed alone:

| The view | Range | 631,341 calls: rows + counts, ms | 2,976,231 calls: rows + counts, ms | Of 30 s at 631,341 | Of 30 s at 2,976,231 |
|---|---|---|---|---:|---:|
| Rows by project, five measures | all | 1,891 + 3,531 = 5,422 | 9,106 + 27,556 = 36,662 | 18% | 122% |
| Rows by project, five measures | lqw | 282 + 1,949 = 2,231 | 494 + 15,408 = 15,902 | 7% | 53% |
| The Projects view: four measures, colored by work type | all | 2,602 + 3,531 = 6,133 | 12,676 + 27,556 = 40,232 | 20% | 134% |
| The Projects view: four measures, colored by work type | lqw | 354 + 1,949 = 2,303 | 540 + 15,408 = 15,948 | 8% | 53% |
| The Work types view: four measures, colored by model | all | 2,269 + 3,531 = 5,800 | 12,417 + 27,556 = 39,973 | 19% | 133% |
| The Work types view: four measures, colored by model | lqw | 319 + 1,949 = 2,268 | 451 + 15,408 = 15,859 | 8% | 53% |
| Median, mean and P90 per conversation, by project | all | 2,099 + 3,531 = 5,630 | 14,064 + 27,556 = 41,620 | 19% | 139% |
| Median, mean and P90 per conversation, by project | lqw | 349 + 1,949 = 2,298 | 710 + 15,408 = 16,118 | 8% | 54% |
| Rows by project under a threshold on the By's rows | all | 1,633 + 3,531 = 5,164 | 8,034 + 27,556 = 35,590 | 17% | 119% |
| Rows by project under a threshold on the By's rows | lqw | 331 + 1,949 = 2,280 | 678 + 15,408 = 16,086 | 8% | 54% |
| Rows by project under a condition on each conversation | all | 1,322 + 3,531 = 4,853 | 7,575 + 27,556 = 35,131 | 16% | 117% |
| Rows by project under a condition on each conversation | lqw | 702 + 1,949 = 2,651 | 3,856 + 15,408 = 19,264 | 9% | 64% |

The rows and the counts' task are read side by side, the engine taking two statements at once.
At 631,341 Calls, where two reads at once take what one takes (the burst), the page has its
figures after the longer of the two; at three million, where each read added adds its whole
time, after about their sum. The database's time is the sum either way, and the quick filters'
counts are most of every sum. Over all time at three million a walk's reads take longer than
the walk: the next walk's event comes while they are under way, they land, and the page reads
again, so that it reads without a pause. A read the page cancels, as a change of state
supersedes it, frees the page alone: the server reads a request to its end, and a task runs on.
Where the week went, an Over time view, is drawn as its rows until its series is; its rows were
not timed.

An open filter's pane adds its values. The conversations' were timed before conversations were
named: their statement now joins each Call's thread for its name too.

| An open filter's pane | Range | 631,341 calls, ms | 2,976,231 calls, ms |
|---|---|---:|---:|
| An attribute's values for a filter's pane: the calls | all | 1,512 | 9,700 |
| An attribute's values for a filter's pane: the calls | lqw | 196 | 399 |
| An attribute's values for a filter's pane: the conversations | all | 600 | 3,799 |
| An attribute's values for a filter's pane: the conversations | lqw | 118 | 274 |

## The engine's defaults

- **The timeout bounds a read whole, 45 s.** `Bounds.read` gives a read's wait for a slot and
  every statement it runs one deadline, each statement's `statement_timeout` set to what is left
  of it. A read had waited up to the timeout for its slot and then given each statement the
  whole timeout, so a read of five statements could hold its request for minutes. The proxies in
  front of `/api/` wait 60 s, nginx's default `proxy_read_timeout`, which `snippets/proxy.conf`
  leaves as it is; a read past it answered the proxy's 504, not the engine's refusal with a
  reason. An answer's reads share one deadline from the state's check on, an entry's read among
  them, so 45 s leaves 15 s for the shaping and the answer after them. Every view timed at three
  million is answered within it, the lanes over all time, 44.7 s with their shaping, at its edge.
- **A count's task is held to it a read at a time.** By's counts read each fact in a read of
  its own, and the quick filters' counts judge the By's rows in one read and tally in another.
  No page waits on a task, so a task is answered when it is done; only each read is bounded.
- **Two statements at once.** At 630,000 Calls two reads at once take what one takes, and past
  two each read added slows them all; at three million each read added adds its whole time. Two
  also halves what a burst can hold on the shared volume, each statement allowed 2 GB of
  temporary files.

## Past two seconds

The two counts are answered as tasks, the numbers showing as they come. Every other part that
passes two seconds below three million Calls is the operator's to rule a lever for. What the
plans of the slowest statements show at three million:

- **The Event fact reads every Call and tool call.** Its source is a union of each kind's rows,
  joined to the Call after it, so a conversation's or a window's condition reaches no branch:
  the statement for one conversation's 193 events read all 2,976,231 Calls and 3,021,699 tool
  calls, nearly all of its read's 18 s. The strip, the lanes and a conversation's calls take as
  long over a quota week as over all time for this.
- **A Call's quota week is found by a range test against every week.** Where the week went over
  eight weeks compared 462,650 Calls with every week, 45 million comparisons, about 5 s of its
  statement's 7.9 s.
- **A marker's first sighting reads every Call.** Each Component's versions are first seen over
  all time, one statement a Component, about 3 to 4 s each.
- **Over all time every view reads every Call**, 2 to 4 s a million at three million, so only
  figures kept somewhere other than the Calls would hold a view over all time under two seconds
  as the record grows.
- **By's counts over all time need more than the 2 GB of temporary files the database allows a
  statement at three million.** Over a quota week the same statements already sort to disk and
  hash in 32 batches at `work_mem` 4MB.

## The labeller's part

The parts the labeller's labels give the engine, and Pilot's inventory with what it hands the
labeller, were timed on two histories whose every conversation the stub labeller labelled, at
the same settings on an instance of the same kind. Over a quota week, the rows by a kind of
work, colored by one and by a unit's role answer in under half a second at both sizes; a kind's
order, its conversations as dots and every lanes part take 2.6 to 4.7 s at 630,000 Calls and 13
to 18 s at three million. Over all time every part passes two seconds below three million Calls
but the inventory, which passes it near 3.3 million.

The lanes by project over all time take 27 s at 630,000 Calls and 156 s at three million,
against 8.6 s and 45 s above, before the lanes carried runs. At three million they are past the
engine's 45 s timeout, so they would be refused. Most of what the runs add is their merge in the
process (below). By's counts over all time already pass that timeout at 630,000 Calls.

### How it was timed

- **The database and its storage** as above: a new instance at the same settings, on Ceph RBD,
  removed after the timing.
- **The histories**: written by `history.py` as above, each conversation labelled by the stub
  labeller in process, its vocabularies declared each day: 629,283 Calls over 70 days and
  2,982,086 over 329 days. Each work session of Pilot's carries out a leg of its project's errand
  of the day in one of three roles, under six kinds of work nested as the workflow's labeller
  nests its own, an errand three steps above a leg. A role's configuration changes between its
  units, and a later round is now and then work done again.
- **Not the histories above.** They hold about three times the events, the labelled ones among
  them, so the lanes and By's counts timed again here compare with their figures above with that
  in mind.
- **The parts**: read as above, with no burst.

Regenerate the tables with
`uv run python -m tools.timing.report tools/timing/results/labeller/630000.json tools/timing/results/labeller/3000000.json`.

### Its record on disk

| | 629,283 calls | 2,982,086 calls |
|---|---:|---:|
| calls | 629,283 | 2,982,086 |
| transcripts | 22,660 | 107,174 |
| launches | 16,490 | 78,290 |
| tool_calls | 642,622 | 3,043,541 |
| events | 6,868 | 32,667 |
| compactions | 5,774 | 27,245 |
| sessions | 6,026 | 28,447 |
| turns | 7,930 | 37,454 |
| work_units | 5,710 | 26,675 |
| segments | 378,119 | 1,790,826 |
| On disk | 0.65 GiB, 7% of 10 Gi | 2.91 GiB, 29% of 10 Gi |
| Calls from | 2026-09-17 | 2026-01-01 |

### Its parts

"Passes 2 s at" is read as above.

| Part | Range | 629,283, ms | 2,982,086, ms | Passes 2 s at | Slowest statement at 2,982,086, ms | Gone to disk at 2,982,086 |
|---|---|---:|---:|---|---:|---|
| The attributes' counts (By's panel), a task | all | 61,348 | refused |  | refused | refused |
| The attributes' counts (By's panel), a task | lqw | 4,981 | 17,852 | below 629,283 | 15,408 | Hash in 16 batches; Hash in 2 batches; Hash in 32 batches; Sort to disk |
| The lanes by project | all | 26,599 | 155,660 | below 629,283 | 29,260 | Hash in 16 batches; Hash in 32 batches; Sort to disk |
| The lanes by project | lqw | 4,688 | 18,397 | below 629,283 | 15,516 | Hash in 32 batches; Sort to disk |
| The lanes by conversation | all | 5,451 | 30,011 | below 629,283 | 17,916 | Aggregate (Hashed) to disk; Aggregate (Mixed) to disk; Hash in 16 batches |
| The lanes by conversation | lqw | 3,433 | 15,595 | below 629,283 | 14,201 | Hash in 16 batches |
| Rows by the widest kind of work: its units, their measure and the cost | all | 988 | 5,252 | 1,190,000 | 7,299 | Sort to disk |
| Rows by the widest kind of work: its units, their measure and the cost | lqw | 177 | 376 | 22,200,000 | 517 | Sort to disk |
| Rows by project, colored by the widest kind of work | all | 1,471 | 7,650 | 830,000 | 11,028 | Sort to disk |
| Rows by project, colored by the widest kind of work | lqw | 230 | 454 | 19,200,000 | 577 | Sort to disk |
| Rows by a unit's role, with the share of work done again | all | 603 | 3,079 | 1,960,000 | 4,382 | none |
| Rows by a unit's role, with the share of work done again | lqw | 134 | 366 | 19,600,000 | 312 | none |
| In order: each leg by its start, its outliers judged among its role, with the marker of a role's configuration | all | 2,614 | 14,162 | below 629,283 | 5,345 | Hash in 2 batches; Sort to disk |
| In order: each leg by its start, its outliers judged among its role, with the marker of a role's configuration | lqw | 2,644 | 13,224 | below 629,283 | 4,475 | Hash in 2 batches; Sort to disk |
| In order: each errand by its start, its conversations as dots, each with its role | all | 4,845 | 26,242 | below 629,283 | 7,057 | Hash in 2 batches; Sort to disk |
| In order: each errand by its start, its conversations as dots, each with its role | lqw | 2,768 | 13,438 | below 629,283 | 5,013 | Aggregate (Hashed) to disk; Hash in 2 batches; Sort to disk |
| The lanes by conversation, their runs colored by model | all | 5,857 | 29,920 | below 629,283 | 18,003 | Aggregate (Hashed) to disk; Hash in 16 batches; Sort to disk |
| The lanes by conversation, their runs colored by model | lqw | 3,277 | 14,861 | below 629,283 | 14,280 | Hash in 16 batches |
| Pilot's inventory with what it hands the labeller, a collector's call | all | 402 | 1,794 | 3,300,000 | 175 | Sort to disk |

### Its parts past two seconds

Every part here but the inventory passes two seconds below three million Calls, and every lever
but the two counts' is the operator's to rule. What the plans of the slowest statements, and a
profile of the slowest read, show at three million:

- **The lanes' runs are merged in the process, and a wait keeps them apart.** By project over
  all time, the runs' statement handed the process 2,196,273 runs for 11 lanes. Two runs merge
  only where one ends as the next begins, and a run before a wait ends at its own last Call. So
  the merge doubled its resolution 13 times, each time over every run again, up to the whole
  span, and still answered 126,108 runs, ten times its bound, in 20 MB. Merged from each
  resolution's output instead, two runs merging where less than the resolution lies between
  them, it stopped at the fifth resolution with 894 runs in 1.7 MB, and the read took 79 s, not
  139 s. That was measured on the instance with the merge patched outside the code, which is
  unchanged.
- **The runs' statement reads every Call of the lanes through two windows**: 29 s by project
  over all time, its sort 179 MB on disk; 1.3 s over a quota week.
- **The lanes' events are the Event fact's union** above: 14 to 24 s over either range.
- **A kind's order reads over all time whatever its range.** Over a quota week a leg's own rows
  take 0.4 s and its order 13 s in all: two Components' first sightings, 4.5 s and 3.2 s; the
  configuration's marker, a statement over every Call, 3.5 s; and the band's members before the
  range, 3.2 s to find them and 3.5 s for their figures. An errand's dots add the conversations
  before the range, 5.0 s, their grouping 156 MB on disk.
- **A kind's rows, as a color and by role read every Call over all time**, as every view does.
  The widest kind By takes 5.3 s, against 9.1 s for the rows by project above: the joins up a
  unit's chain add no cause of their own.
- **By's counts over all time pass the engine's timeout at 630,000 Calls.** They took 61 s, three
  times the 19.5 s above, about 57 s of it the Calls' read; each fact's count is a read of its
  own under the 45 s timeout, so that read would be refused. The labeller's attributes and kinds
  add grouping sets to each fact's statement. The read wrote 2.1 GB of temporary files, against
  0.46 GB above; the database's 2 GB limit is on what a statement holds at once, which the timing
  does not measure. At three million they are refused for temporary disk, as above.
- **The inventory** reads in 0.4 s at 630,000 Calls and 1.8 s at three million, its transcripts'
  statement 175 ms; the rest is the route's work on 107,174 transcripts. The histories hold
  no Holds and no Documents, so its two reads of them ran over empty tables.
