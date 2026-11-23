# The engine's timing (F154.9)

Every part of the dashboard's engine was timed on two generated histories, at production's
database settings. Over all time, every part passes two seconds by 1.7 million Calls, most of
them before 800,000. Over a quota week, the rows, the medians, a pane's values and the series by
weekday and by hour answer in under a second at both sizes; the events strip, the lanes and a
conversation's calls take more than two seconds over any range at both sizes. At three million
Calls, By's counts over all time are refused at the database's limit on temporary files.

The engine's timeout and its statements at once take their defaults from it: 45 s for a whole
read and 2 statements at once (below).

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
| The attributes' counts (By's panel), a task | all | 19,472 | refused |  | 0 | none |
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


## The engine's defaults

- **The timeout bounds a read whole, 45 s.** `Bounds.read` gives a read's wait for a slot and
  every statement it runs one deadline, each statement's `statement_timeout` set to what is left
  of it. A read had waited up to the timeout for its slot and then given each statement the
  whole timeout, so a read of five statements could hold its request for minutes. The proxies in
  front of `/api/` wait 60 s, nginx's default `proxy_read_timeout`, which `snippets/proxy.conf`
  leaves as it is; a read past it answered the proxy's 504, not the engine's refusal with a
  reason. 45 s leaves 15 s for what runs outside the read: the state's check before it, and the
  shaping and the answer after it. Every view timed at three million is answered within it, the
  lanes over all time, 44.7 s with their shaping, at its edge.
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
