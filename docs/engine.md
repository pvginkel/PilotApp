# The engine

The engine keeps the record and the store's tree in step. Documents are born in the record, or
registered from a worker's file and published once it is read, with their caches; an agent's save
comes through the parse gate and is merged by ownership; the record's own writes are spliced into
the published text; and an event says what moved. It is a module of the Flask server,
`backend/app/engine/`, its services wired in `backend/app/services/container.py`. Every operation
writes in the caller's transaction, and nothing it emits is delivered before that transaction
commits.

| Service | Does |
|---|---|
| `DocumentService` (`documents.py`) | the births, a worker's registration and its read, `publish()`, the document's row lock, versions, the turn's end |
| `IngestService` (`ingest.py`) | an agent's save of a path of the tree; the faults of a text Pilot's own item is to be born with |
| `RecordService` (`record.py`) | a person's answer, Done, undo, Read, Reviewed; Finish's close and the archive question's; the switch's Yes; a work item placed and done, and named for the claimed actions it does; a run's continuation released; the job after a close of an item of Pilot's own placed, and withdrawn by its Undo |
| `PlanService` (`plan.py`) | `plan.json`, rendered and saved; the deferrals without a home |
| `TreeService` (`tree.py`) | what a path names, the bytes it must hold, its tree hash; the manifest |
| `ViewService` (`views.py`) | `reference.json`, `timeline.json` and `chat.md` ([`chats.md`](chats.md)) |
| `AttachmentStore` (`attachments.py`) | an attachment's bytes, kept, read and deleted ([`documents.md`](documents.md)) |
| `AttachService` (`attachments.py`) | files a session copied from its environment, hung on an item as one batch, or a draft's on nothing ([`mcp.md`](mcp.md)); at Create project, the draft's copy and the draft's material hung on the opening |
| `EngineBus` (`bus.py`) | the events, one bus per process |

The grammar the engine reads is [`block-dsl.md`](block-dsl.md), the tree and its files
[`projection.md`](projection.md), the tables [`record.md`](record.md), and the sync between the
engine and the store's tree [`sync.md`](sync.md).

## Born in the record

Every document of Pilot's own is born in the record, published, before any agent edits it, with
version 1 cut, cause `born`; a worker's is registered (below):

- `bear_draft(project, text="")`: the draft, `project.md`, at the plus
  ([`projects.md`](projects.md)).
- `bear_handbook(project, text="")`: the handbook, `handbook.md`, at Create project.
- `bear_item(project, kind, title, session, text="")`: a prose item of Pilot's own, of any prose
  kind but the opening, which `session` added; its version is of that session. It takes the next
  `seq` under the project's row lock, and its path from the title. The title is written first into
  the text's front matter, one opened at the top where the text has none, unless the front matter
  gives a `title` already (`dsl.with_title`), so the text carries its title from birth. The
  brain's `add_item` bears one ([`mcp.md`](mcp.md)) once `IngestService.born_faults(project, text)`
  finds no fault in its text, which it reads as a save of it is read, the title rule and the
  record's facts included, with one fault more: a block whose `by` names a person, since a born text
  has no published one to hold that person's answer.
- `bear_opening(project, title, user, text)`: the opening, the words of the person who started the
  project, taken as written: at Create project, the first message to its definition chat. The record
  reads nothing from its text: it has no blocks, and its kind, title and caches stay as it was born.
- `bear_archive_question(project)`: the archive question, after a finish
  ([`projects.md`](projects.md)), of the kind `archive_question`, created by Pilot and by no
  session: "Archive the project?", one decision, `D1`, offering Archive and Keep. Its caller holds
  the project's row `FOR NO KEY UPDATE`, as a change of its standing does, and its `seq` is taken
  under that hold, the one every other birth's `next_seq` waits on. `bear_item` refuses its kind as
  it refuses the opening.

The births, and a work item's placing, take the Item's `seq` from
`DocumentService.next_seq(project)`, under the project's row lock until the transaction ends
(`lock_project(project)`, which `pilot-work`'s registration takes first to read its Session again,
[`mcp.md`](mcp.md)), so that items in one project take theirs one at a time. A work item has no
document:
`RecordService.place_work(project, session, title, plan_task_id=None, *, repo=None, trigger=None,
trigger_item_id=None)` writes its Item, kind `work`, created by its own `session` and sharing its
id, on the plan's task when given (a task not in the plan is a `RecordNotFoundException`), and its
Work, `autopilot` the project's switch as it stands and `repo` the repository it is placed by, none
for a job, which has instead the `trigger` that started it and the Item that set it off,
`trigger_item_id`, where it has one ([`work.md`](work.md));
`work_done(work_id, at)`, at its turn's end, a job's at its last, marks the Item done at `at`, by no
one, cause `turn_ended`, under the Item's row lock, and leaves one done already, as Finish's close
leaves it ([`sessions.md`](sessions.md)). Each moves `timeline.json`.

A birth but the opening's refuses a text with a fault of its own (an unclosed fence, a body that is
no mapping, and the like) and then writes nothing. The opening's is never refused, whatever it
holds.

## A worker's registered document

A document a work item's session wrote in its environment and registered ([`mcp.md`](mcp.md)) has
no text until the end of the run that registered it ([`round-trip.md`](round-trip.md)):

- `register(project, session, source_path) -> Registration(item, minted)`: the document `session`
  registered from `source_path` already, else one minted at the project's next `seq`, under the
  project's row lock, so a path registered twice at once is minted once: a `review` (a text with no
  block keeps it), created by `session`, with no title, no text and no version, its source the
  session's environment and the path as given, its own path `inbox/<seq>-<slug>.md` from the
  file's stem (`inbox/<seq>.md` with no ASCII letter or digit in it).
- `awaits_read(item, document)`, and `awaiting_read()`, its twin as a query's condition: a
  registered document still open with no text and no failed read. Such a document takes no close.
- `publish_read(document, text, session_id)`: the file as the run left it, published as written,
  which gives the document its kind, title, summary and blocks from its text, and its file in the
  tree; then its version 1, cause `registered`, of that Session. `fail_read(document)` stamps
  `read_failed_at` and emits `ProjectChanged`: the document keeps no text, and closes with
  Reviewed as any document with no block.
- `wrote_back(document)` stamps `written_back_at`, and `refuse_write_back(document)`
  `write_back_refused_at`.

`IngestService.worker_version(project, content)` reads a registered file's bytes as a text of the
project's: its decoding's faults, its own and those against the record, in line order, outside the
title rule ([`block-dsl.md`](block-dsl.md)). A text with any fault is neither registered nor
published; `listed(faults)` says them as a worker reads them, `line N: …; …`.

## Publishing

`DocumentService.publish(document, text)` is the one write of a published text: an agent's merged
save and the record's writes both go through it. It refuses a text with a fault of its own, the
opening's excepted, which it never reads; it sets the published text, hash and time, and rebuilds
every cache in the same transaction:

- the document's blocks, rewritten in place by local id; a block the text lost is deleted with its
  options, and a block's options are rewritten only when they changed;
- for a prose item but the opening, its kind (a single block gives its kind, `confirmation` for a
  confirmation; several make it a `document`; with none it keeps its kind; an archive question keeps
  its kind whatever its blocks), its title, the text's
  alone and none while the text gives none, its task (`step`), `urgent`, its addressee (`for`) and
  its document's summary. The opening's text rebuilds nothing;
- for the draft, the project's name: its title, or none.

It validates nothing against the record and cuts no version. A publish that changes the published
text, an item's, the handbook's or the project document's, raises `ProjectChanged` (below), and a
registered document's first text gives it its file in the tree, with a `TreeHashMoved` for its path.

## The ingest

`IngestService.ingest(path, content, base_hash, environment, session)` takes the store's save of
`path`, from the tree's root: `base_hash` is the hash the sidecar last synced for the path, none
when it has none, and `session` the Session whose save it is, none when none is: in the store, the
brain session that held the project folder's write lock as the sidecar read the file
([`sync.md`](sync.md)). It answers an `Ingested`:

- `kind`: what the path names, `document`, `plan` or `view` (any read-only path, an attachment
  included);
- `content`: the bytes the file must now hold, none when the save already holds them;
- `hash`: the path's tree hash after the save, except for a held save of `plan.json`, which is
  answered with the save's own hash while the tree hash stays the rendering's;
- `stale`: whether the base hash was other than the path's tree hash when the save came; a save
  with no base hash is stale;
- `held`, and `faults`: what held the save, or what the merge put back or took out.

A save of a document runs in one transaction, under the document's row lock:

1. The bytes are decoded. Bytes that are not UTF-8, and NUL, which PostgreSQL's `text` cannot
   hold, are replaced by U+FFFD with a fault at the line of the first; the answer carries the
   replaced text.
2. The save is stored as the document's ingest, with its session. A session given that is not the
   one writing the document becomes the writer from now, which raises `ProjectChanged`: Pilot's
   dots show on the document.
3. The path's `parse` Save Errors go, in every environment: the save's faults replace them.
4. The text is validated against the record ([`block-dsl.md`](block-dsl.md)): every user's
   handle, the plan's tasks and removed tasks, the confirmation reasons, the other projects' slugs,
   the published text's deferrals, and the title of a save Pilot makes of an item.
5. With any fault the save is **held**: a `parse` Save Error per fault, under the save's
   environment. The published text stays as it was, and the tree keeps the agent's save.
6. With none, the save is merged by ownership against the published text and the result
   published, with a `reverted` Save Error per fault the merge reports; the answer carries the
   merged text where it differs from the save. The `reverted` rows of earlier saves stand.

`project.md` is read as a draft while its project is one, and past Create project under the
handbook's rules ([`block-dsl.md`](block-dsl.md)): a person's answered block frozen, a dropped one
restored, and its `slug` read by nothing.

A save of the opening is never read: steps 4 and 5 pass it by, and the decoding's fault with them,
so it is never held. A save that differs from the published text, an undecodable one included, is
reverted whole, with one `reverted` fault: `the opening is the record's: the save is reverted`.

A path is held while a `parse` Save Error stands on it, in any environment, so held means that the
path's latest save was. A held document's tree hash is its ingest's, so a fix-up sent with the held
save's hash as its base is not stale. A held item shows as a concept, its text as last published,
and a save that holds an item or ends its hold raises `ProjectChanged`.

A save of `plan.json` takes the project's row lock, removes the path's `parse` Save Errors and is
parsed back into the plan's rows ([`projection.md`](projection.md)); a held one writes a `parse`
Save Error per fault and changes no row. A save of a read-only path stores nothing. Any other path
is refused with `RecordNotFoundException`.

`IngestService.write_down(paths)` is the manifest reconcile's ([`sync.md`](sync.md)): a held
`plan.json` among the paths the store is to write down is written down canonical, so under the
project's row lock its `parse` Save Errors go, in every environment, with `ErrorsResolved`.

## The record's own writes

`RecordService`'s writes each take the document's row lock first, so that a write and an ingest of
one document never interleave. Every close takes the project's row before it, so that it
serialises with Archive and reads the archive as it stands: an archived project's item takes no
close and no Undo (D012). An item's close takes the row `FOR UPDATE`, the lock order of the start
that places a continuation or a job, so that it serialises with Finish, with an Undo and with every
other close; a close in the draft holds it shared, as an Undo does, and the archive question's
close holds its document's row alone (below).
A write that touches the text splices it into the published text and publishes it, while the
path's latest save is held too: the tree keeps the agent's save then, and the next clean save's
merge carries the write to the file.

- `answer(document, local_id, user, answer, *, via=AnswerChannel.APP, note=None, to=None)`: a
  person's answer to a block, `deferred` with `to` naming a task in the plan or `plan`. It replaces
  the block's answer, Pilot's included. An answer to the one block of a one-ask item, an item with a
  single block, marks the item done, cause `answered`, at the answer's time. Outside the draft, a
  person's answer freezes its block against the agent's next saves ([`block-dsl.md`](block-dsl.md)),
  and so does an action's Done. An archive question takes `Archive` or `Keep` alone; its Archive is
  `ProjectService.archive_by_its_question`'s, which answers it and archives the project in one act.
- `done_action(document, local_id, user, *, note=None)`: Done on an action without options; on a
  one-ask item it is the item's done as well.
- `undo(item)`: clears a done prose item's mark while no session has taken its answers, its done
  cause offers undo and its project is neither finished (D028) nor archived (D012); a registered
  document's `written_back_at` and `write_back_refused_at` go with it, so that its next close writes
  it again; and the job its close placed, while it is still held before its brief, is withdrawn
  (below). An archive question offers none. On cause `answered` it also takes out the answer lines
  of the block the person answered, which unfreezes the block. It holds the project's row shared
  before the document's, so Finish and Reopen, which change the project's state under its row lock,
  never interleave with it, and locks that job's Session before it reads the item again, so that the
  job's brief, which consumes the item under that lock, and the Undo never both take effect.
  `offers_undo(item)` says whether `undo` would take the item now, by the same rule.
- `done(item, user)`: Done on a document. A person's first answers every unanswered block that
  has a recommendation with it, `via: recommended`, and is refused while a block has neither an
  answer nor a recommendation, a claimed action not yet done among them; its cause is `marked`.
  Pilot's is refused while any block is unanswered, a claim counting only once its action is done
  ([`block-dsl.md`](block-dsl.md)); its cause is `settled`. Pilot's also takes a registered
  document of one block, whose item has its block's kind, once that block is answered, deferred, or
  claimed and done; a person's Done on one, and Pilot's on a one-block item of its own, stay refused
  by its kind. Then a `done` version is cut and the item marked done.
- `read(item, user)` on a notice and `reviewed(item, user)` on a review: the item's mark, cause
  `marked`, the text untouched.
- `close_unanswered(project, user, at)`: Finish's close ([`projects.md`](projects.md)). Every open
  item of the project but the opening, which is never done, is marked done at `at` by `user`, cause
  `finished`, which offers no undo; the texts are untouched, and a registered document so closed
  owes no write-back and continues nothing. It takes the row lock of each open
  prose item's document first, in id order, so a write to one of them waits for the close or finds
  its item done.
- `close_archive_question(project, user, answer)`: the project's open archive question, if it has
  one, answered `Archive` or `Keep` by `user`, its done `answered`: the menu's Archive closes it as
  its Archive and Reopen as its Keep. It holds the question's document row alone, under the hold of
  the project's row its caller took `FOR NO KEY UPDATE`, so that a change that stops the project's
  sessions never takes the row `FOR UPDATE`, which a chat's send under way, holding its Session,
  would deadlock with.
- `autopilot_yes(project, user)`: the switch's Yes ([`projects.md`](projects.md)), under the
  project's row held `FOR UPDATE`: the documents of the confirmations it answers locked in id order,
  the confirmations read again within them, and each answered `Yes` by `user`, `via: autopilot`,
  through `answer`, so each does what a person's answer does. `autopilot_may_take(project)` is the
  query of those confirmations, in timeline order: unanswered confirmation blocks of the project's
  open items whose reason does not ask under auto pilot. The head's count and the dialog read it.

**A claimed action** (D085) is an action of a registered document the pre-ruling pass answered
`Pilot does it`, `by: agent`, and whose `done` is not yet written: open, Pilot's, until then
([`block-dsl.md`](block-dsl.md)). The work item that does it is the record's, not only its note's:
the pass names the block in the `claims` of that work item's `add_item` ([`mcp.md`](mcp.md)), the
work item first and the claim after it, and each naming is a Claim Assignment
([`record.md`](record.md)). `claimable(project, block_ids, operation)` checks the named blocks
before the work item starts, each document's row locked in id order after the project's: a block
of another project's item, or one its document lacks, is a `RecordNotFoundException`; an item that
is no registered document, is done or has not been read yet, a block that is no action or is
answered, a claim not yet done excepted, and a block named twice are refused. `give(project, work,
blocks)` writes one row each once the work item is placed. A block named again later keeps its
earlier rows, and the one whose work item has the highest `seq` stands (`claims.standing()`); a
claimed action whose rows are none has no work item named. `claims.claimed()` is the claim as a
query's condition on a block. A claimed action stays out of the badge while its document has no
other open block ([`projects.md`](projects.md)), and keeps a person's controls: a person who closes
it meanwhile is answered as any person's answer is. A run that fails leaves the claim
standing and the block open.

Each refuses with `InvalidOperationException`, its message saying why: Pilot as the actor of an
answer, an action's Done, Read or Reviewed, since Pilot answers in the file with `by: agent`; any
write on a done item; a blank answer; `deferred` without `to`, `to` without `deferred`, or a `to`
naming neither `plan` nor a task in the plan; an answer to an action without options other than a
deferral; Done on an action with options or on a block that is no action; Done on an item that is
not a `document`, Pilot's on a registered document of one block excepted, Read on one that is not
a notice, Reviewed on one that is not a review; any close of a registered document awaiting its
read ("its file has not been read yet"); any close of an archived project's item ("its project is
archived", D012); an answer but Archive or Keep to an archive question; undo of an item that is no
prose item, is an archive question, is not done, has been consumed, was done by a cause that offers
none, or is of a finished or an archived project. A block the text does not have is a
`RecordNotFoundException`, and the opening has none, nor a registered document whose read failed:
an answer or a Done on either is refused so.

The close of a registered document by anything but Finish, a one-ask answer, an action's Done that
closes it, Done or Reviewed, emits `WriteBackOwed` for the Session that registered it while its text
is owed to its file (`owes_write_back`, and `write_back_owed()` as a query's condition). Once that
Session's work item is done `turn_ended` and none of the documents it registered is open or closed
by Finish, the close also releases its continuation (`_release`): the work item that continues
the run's conversation, placed through the port `Continuations` (the session start's
`continue_run`, [`sessions.md`](sessions.md)) with the message naming the files, and every
document of the run consumed by it, `consumed_at` and `consumed_session_id`, with
`ProjectChanged` ([`round-trip.md`](round-trip.md)). `retry_write_backs(continuation_id)`, in a
Resume of a continuation, clears `write_back_refused_at` on the documents it carries, each owed
again with its `WriteBackOwed`.

**The job after an item of Pilot's own.** A person's close of an item a session of Pilot's own
added, one whose Session Kind's surface is `pilot-store` (a chat's or a job's), places the job after
it in the close's transaction, through the port `Jobs` (`JobService.item_done`,
[`work.md`](work.md)): an answer that marks a one-ask item done, an action's Done that does, Done
and Reviewed. A notice's Read, Pilot's own Done, Finish's close, a registered document's close, an
item a worker's session added and the archive question, which no session added, place none. Every
close of an item holds its project's row `FOR UPDATE`, a close in the draft alone holding it shared.
The job's brief consumes the item, which takes its Undo ([`sessions.md`](sessions.md)). An Undo
before that, while the job is held behind the project's other jobs or by the pause, withdraws it
(`JobService.withdraw`): its Session `stopped` by no one, with no Turn, and its Item done at the
Undo, cause `withdrawn`, by no one, which offers no undo. An Undo that finds the job briefed
meanwhile is refused, the item consumed.

The writes but the close, which takes its caller's time, record their times to the second; they
trim every value and read a blank note as none.

## The turn's end

`DocumentService.turn_ended(session)` clears the writing session of every document `session` was
writing, cuts a `turn` version of each whose published text changed since its last version, its
`created_at` the clock's at the cut, and
returns the paths, from the tree's root and sorted, of those whose latest save is still held. It
raises `ProjectChanged` for each document it lets go, whatever the Session's state. The relay calls
it in the transaction that ends a turn on the controller's `result` frame, and in the one that ends
a turn its environment was stopped under ([`sessions.md`](sessions.md)). The paths it returns at the
`result` of a brain session's turn that leaves the Session `idle` are the server's follow-up turn
([`chats.md`](chats.md)); every other turn's end drops them. It reads no file: the documents a work
item's run registered are read once the transaction that makes the work item done commits
([`round-trip.md`](round-trip.md)).

## The bus

`EngineBus` is the container's singleton: `subscribe(callback)`, `unsubscribe(callback)` and
`emit(event)`. An event is delivered once the transaction that emitted it commits, and never if it
rolls back, to every subscriber, in the order the transaction emitted them; an event equal to one
already emitted in the transaction is delivered once.

| Event | Emitted |
|---|---|
| `TreeHashMoved(path, hash)` | when a path's tree hash moved: a birth, a publish, a save, an attachment hung; `timeline.json` when what it shows moved, a done mark or its undo and a project's transition included; `plan.json` when a save moved its rendering; `chat.md` when a record it shows is written, and at a chat's open and close |
| `DocumentModified(project_id, path)` | on every save of a document, held or published; the record's own writes raise none |
| `ErrorsRaised(project_id, path)` | on every held save |
| `ErrorsResolved(project_id, path)` | on a clean save after a held one, and when a held `plan.json` is written down |
| `ManifestChanged()` | when the set of syncing projects or their folders changed: a draft started from the plus, a project created, archived or brought back ([`projects.md`](projects.md)), and the sync's testing endpoint |
| `ProjectChanged(project_id)` | when what the project's timeline, head or tab shows moved: with every `TreeHashMoved` of its `timeline.json`; on a publish that changes the published text of an item, a record write on a held item included, of the handbook or of the project document; on a save that holds an item or ends its hold; on a save that makes its session a document's writer, and for each document a turn's end lets go; on a save of `plan.json` that moved its rendering; on a pause, a resume, a join and a leave ([`projects.md`](projects.md)); on every move of one of its Sessions' state; on a chat's open and close ([`chats.md`](chats.md)); on a registered document's failed read, and on a continuation released, which takes Undo from its run's documents ([`round-trip.md`](round-trip.md)). `ProjectEventService` sends it to the browsers ([`timeline.md`](timeline.md)), and it starts the project's notification reconcile ([`notifications.md`](notifications.md)) |
| `WriteBackOwed(session_id)` | on a close that owes a registered document's text to its file, and on a Resume that owes a refused one again; the write-back service hears it ([`round-trip.md`](round-trip.md)) |
| `WorkMoved(project_id, work_id)` | when what a work item's line shows of its Session moved: its state, its current line, its start or its error ([`work.md`](work.md)). `ProjectEventService` sends it with the work item's status |

## Testing it

The engine's tests are in `backend/tests/engine/`, the block DSL's in its package's `tests/`
with the corpus ([`block-dsl.md`](block-dsl.md)). Two fixtures of `backend/tests/conftest.py`
serve them: `engine_events`, every event the bus delivers during the test, and `fake_sidecar`, the
store's sidecar played against the sync routes ([`sync.md`](sync.md)): `save()` writes a file and
puts it, and `drain()` fetches what the change stream says moved. The bus delivers on a commit, so
a test reads events after committing through `scoped_session(container)` or a request context.
