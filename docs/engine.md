# The engine

The engine keeps the record and the store's tree in step. Documents are born in the record and
published with their caches; an agent's save comes through the parse gate and is merged by
ownership; the record's own writes are spliced into the published text; and an event says what
moved. It is a module of the Flask server, `backend/app/engine/`, its services wired in
`backend/app/services/container.py`. Every operation writes in the caller's transaction, and
nothing it emits is delivered before that transaction commits.

| Service | Does |
|---|---|
| `DocumentService` (`documents.py`) | the births, `publish()`, the document's row lock, versions, the turn's end |
| `IngestService` (`ingest.py`) | an agent's save of a path of the tree |
| `RecordService` (`record.py`) | a person's answer, Done, undo, Read, Reviewed; Finish's close |
| `PlanService` (`plan.py`) | `plan.json`, rendered and saved; the deferrals without a home |
| `TreeService` (`tree.py`) | what a path names, the bytes it must hold, its tree hash; the manifest |
| `ViewService` (`views.py`) | `reference.json` and `timeline.json` |
| `EngineBus` (`bus.py`) | the events, one bus per process |

The grammar the engine reads is [`block-dsl.md`](block-dsl.md), the tree and its files
[`projection.md`](projection.md), the tables [`record.md`](record.md), and the sync between the
engine and the store's tree [`sync.md`](sync.md).

## Born in the record

Every document is born in the record, published, before any agent edits it, with version 1 cut,
cause `born`:

- `bear_draft(project, text="")`: the draft, `project.md`.
- `bear_handbook(project, text="")`: the handbook, `handbook.md`.
- `bear_item(project, kind, title, session, text="")`: a prose item of Pilot's own, of any prose
  kind but the opening, which `session` added; its version is of that session. It takes the next
  `seq` under the project's row lock, and its path from the title. The title is written first into
  the text's front matter, one opened at the top where the text has none, unless the front matter
  gives a `title` already (`dsl.with_title`), so the text carries its title from birth.
- `bear_opening(project, title, user, text)`: the opening, the words of the person who started the
  project, taken as written. The record reads nothing from its text: it has no blocks, and its kind,
  title and caches stay as it was born.

A birth but the opening's refuses a text with a fault of its own (an unclosed fence, a body that is
no mapping, and the like) and then writes nothing. The opening's is never refused, whatever it
holds.

## Publishing

`DocumentService.publish(document, text)` is the one write of a published text: an agent's merged
save and the record's writes both go through it. It refuses a text with a fault of its own, the
opening's excepted, which it never reads; it sets the published text, hash and time, and rebuilds
every cache in the same transaction:

- the document's blocks, rewritten in place by local id; a block the text lost is deleted with its
  options, and a block's options are rewritten only when they changed;
- for a prose item but the opening, its kind (a single block gives its kind, `confirmation` for a
  confirmation; several make it a `document`; with none it keeps its kind), its title, the text's
  alone and none while the text gives none, its task (`step`), `urgent`, its addressee (`for`) and
  its document's summary. The opening's text rebuilds nothing;
- for the draft, the project's name: its title, or none.

It validates nothing against the record and cuts no version. A publish that changes an item's
published text raises `ProjectChanged` (below).

## The ingest

`IngestService.ingest(path, content, base_hash, environment, session)` takes the store's save of
`path`, from the tree's root: `base_hash` is the hash the sidecar last synced for the path, none
when it has none, and `session` the session whose turn wrote the save, none while that is not
known. It answers an `Ingested`:

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
   one writing the document becomes the writer from now.
3. The path's `parse` Save Errors go, in every environment: the save's faults replace them.
4. The text is validated against the record ([`block-dsl.md`](block-dsl.md)): every user's
   handle, the plan's tasks and removed tasks, the confirmation reasons, the other projects' slugs,
   the published text's deferrals, and the title of a save Pilot makes of an item.
5. With any fault the save is **held**: a `parse` Save Error per fault, under the save's
   environment. The published text stays as it was, and the tree keeps the agent's save.
6. With none, the save is merged by ownership against the published text and the result
   published, with a `reverted` Save Error per fault the merge reports; the answer carries the
   merged text where it differs from the save. The `reverted` rows of earlier saves stand.

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
one document never interleave. A write that touches the text splices it into the published text and
publishes it, while the path's latest save is held too: the tree keeps the agent's save then, and
the next clean save's merge carries the write to the file.

- `answer(document, local_id, user, answer, *, via=AnswerChannel.APP, note=None, to=None)`: a
  person's answer to a block, `deferred` with `to` naming a task in the plan or `plan`. It
  replaces the block's answer, Pilot's included. An answer to the one block of a one-ask item, an
  item with a single block, marks the item done, cause `answered`, at the answer's time. Outside
  the draft, a person's answer freezes its block against the agent's next saves
  ([`block-dsl.md`](block-dsl.md)), and so does an action's Done.
- `done_action(document, local_id, user, *, note=None)`: Done on an action without options; on a
  one-ask item it is the item's done as well.
- `undo(item)`: clears a done prose item's mark while no session has taken its answers and its done
  cause offers undo. On cause `answered` it also takes out the answer lines of the block the person
  answered, which unfreezes the block. `offers_undo(item)` says whether `undo` would take the item
  now, by the same rule.
- `done(item, user)`: Done on a document. A person's first answers every unanswered block that
  has a recommendation with it, `via: recommended`, and is refused while a block has neither an
  answer nor a recommendation; its cause is `marked`. Pilot's is refused while any block is
  unanswered; its cause is `settled`. Then a `done` version is cut and the item marked done.
- `read(item, user)` on a notice and `reviewed(item, user)` on a review: the item's mark, cause
  `marked`, the text untouched.
- `close_unanswered(project, user, at)`: Finish's close ([`projects.md`](projects.md)). Every open
  item of the project but the opening, which is never done, is marked done at `at` by `user`, cause
  `finished`, which offers no undo; the texts are untouched. It takes the row lock of each open
  prose item's document first, in id order, so a write to one of them waits for the close or finds
  its item done.

Each refuses with `InvalidOperationException`, its message saying why: Pilot as the actor of an
answer, an action's Done, Read or Reviewed, since Pilot answers in the file with `by: agent`; any
write on a done item; a blank answer; `deferred` without `to`, `to` without `deferred`, or a `to`
naming neither `plan` nor a task in the plan; an answer to an action without options other than a
deferral; Done on an action with options or on a block that is no action; Done on an item that is
not a `document`, Read on one that is not a notice, Reviewed on one that is not a review; undo of
an item that is no prose item, is not done, has been consumed, or was done by a cause that offers
none. A block the text does not have is a `RecordNotFoundException`, and the opening has none: an
answer or a Done on it is refused so.

The writes but the close, which takes its caller's time, record their times to the second; they
trim every value and read a blank note as none.

## The turn's end

`DocumentService.turn_ended(session)` clears the writing session of every document `session` was
writing, cuts a `turn` version of each whose published text changed since its last version, and
returns the paths, from the tree's root and sorted, of those whose latest save is still held. It
emits nothing. The relay calls it in the transaction that ends a turn on the controller's `result`
frame ([`sessions.md`](sessions.md)), and drops the paths it returns.

## The bus

`EngineBus` is the container's singleton: `subscribe(callback)`, `unsubscribe(callback)` and
`emit(event)`. An event is delivered once the transaction that emitted it commits, and never if it
rolls back, to every subscriber, in the order the transaction emitted them; an event equal to one
already emitted in the transaction is delivered once.

| Event | Emitted |
|---|---|
| `TreeHashMoved(path, hash)` | when a path's tree hash moved: a birth, a publish, a save; `timeline.json` when what it shows moved, a done mark or its undo and a project's transition included; `plan.json` when a save moved its rendering |
| `DocumentModified(project_id, path)` | on every save of a document, held or published; the record's own writes raise none |
| `ErrorsRaised(project_id, path)` | on every held save |
| `ErrorsResolved(project_id, path)` | on a clean save after a held one, and when a held `plan.json` is written down |
| `ManifestChanged()` | when the set of syncing projects changed; nothing in the record raises it yet, and the sync's testing endpoint does |
| `ProjectChanged(project_id)` | when what the project's timeline, head or tab shows moved: with every `TreeHashMoved` of its `timeline.json`; on a publish that changes an item's published text, a record write on a held item included; on a save that holds an item or ends its hold; on a save of `plan.json` that moved its rendering. `ProjectEventService` sends it to the browsers ([`timeline.md`](timeline.md)) |

## Testing it

The engine's tests are in `backend/tests/engine/`, the block DSL's in `backend/tests/engine/dsl/`
with the corpus ([`block-dsl.md`](block-dsl.md)). Two fixtures of `backend/tests/conftest.py`
serve them: `engine_events`, every event the bus delivers during the test, and `fake_sidecar`, the
store's sidecar played against the sync routes ([`sync.md`](sync.md)): `save()` writes a file and
puts it, and `drain()` fetches what the change stream says moved. The bus delivers on a commit, so
a test reads events after committing through `scoped_session(container)` or a request context.
