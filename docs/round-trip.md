# The worker round trip

A work item's session writes its decision documents as files in its environment, registers each with
`register_document`, attaches what backs them, and ends its turn ([`mcp.md`](mcp.md)). Pilot reads
each document once the run ends and puts it on the project's timeline, its job after the turn
pre-rules what it can ([`work.md`](work.md)), a person answers and closes the rest, Pilot writes it
back to its file, answers and all, and once none of the run's documents is open it continues the
conversation as a new work item with a message naming the files. The environment may be stopped
throughout: the controller's file routes read and write its share, never its pod
([`controller.md`](controller.md)).

| Service | Does |
|---|---|
| `TurnEndReadService` (`backend/app/services/turn_end_read_service.py`) | the read at the run's end, the job `read`, and the placing of Pilot's job after the run's turn once the read has settled |
| `WriteBackService` (`backend/app/services/write_back_service.py`) | the write-back of a closed document, the job `write-back` |
| `RecordService` (`backend/app/engine/record.py`) | the closes, the release of the continuation, Undo ([`engine.md`](engine.md)) |
| `SessionStartService.continue_run` (`backend/app/services/session_start_service.py`) | the continuation's placement and start ([`sessions.md`](sessions.md)) |

## A registered document

A registered document is a review on the timeline from its registration, in one of three states:

- **Awaiting its read**: open, with no text, its line titled by its file's name (`awaiting_read`,
  [`timeline.md`](timeline.md)). It takes no close until its read is made, succeeded or failed:
  every close of the record refuses it, "its file has not been read yet: it is read at the end of
  the turn that registered it", and the screens offer none (D045). It waits on nobody meanwhile:
  the badge and the project's waiting on you leave it out until its read is made.
- **Published**: its file as the run left it, published as written. Its text gives it its kind,
  title, summary and blocks, and its file in the tree (`inbox/<seq>-<slug>.md`,
  [`projection.md`](projection.md)); its version 1 is `registered`, of the Session that registered
  it. It is answered and closed as any document.
- **Its read failed**: `read_failed_at` set, no text. Its line keeps its file's name, its overlay
  reads "The document did not load" ([`documents.md`](documents.md)), it closes with Reviewed as any
  document with no block, its work item's session log says why, and the continuation's message
  names it (D044).

## The read at the run's end

A run ends when its turn's `result` makes the work item done, cause `turn_ended`, its turn neither
interrupted nor in error ([`sessions.md`](sessions.md)). Once that transaction commits, the loop
`read:<session id>` reads every document the Session registered that still awaits its read, in the
order registered, each through the controller outside any transaction, in the environment the
document was registered from, and takes what the read gave in a transaction of its own, under the
Project's row (`FOR UPDATE`), the Session's and the Document's. It takes nothing for a document that
no longer awaits its read, closed by Finish or read by another process meanwhile (`Document <path>
of session <id> no longer awaits its read`).

- **A clean text** is published as written (`publish_read`), and the timeline moves live.
- **A failed read**: the controller's `404` (the file or the environment gone), `403
  path-outside-work`, `409 not-a-file`, `413 file-too-large` or `409 conflict` (a link loop, or a
  manifest the controller cannot read the layout from), or a text with faults (`its text holds
  faults: line N: …`). The document keeps no text (`fail_read`, which emits `ProjectChanged` alone),
  and the registering Session's log gets the `server` record `{"type": "read-failed", "item",
  "path", "reason"}`, in no Turn.
- **Retried**: a read the controller does not answer, its `503 environment-unreadable`, or any other
  refusal of its own raises, and the loop runs again after its backoff ([`jobs.md`](jobs.md)),
  waiting the outage out. Each document is its own transaction: one failing leaves the others.

A run that stops or fails reads nothing: its documents await their reads until the run of its
Resume ends. At STARTUP the job's reconcile runs the reads every Session owes, from the rows.

**Pilot's job after the turn.** The take that leaves none of the run's documents awaiting its read,
a failed read settling as a published one does, places Pilot's job after the run's turn in its own
transaction, under the Project's row it holds (`JobService.worker_turn_ended`,
[`work.md`](work.md)); a run that registered nothing gets it in the transaction of its turn end. It
is placed once per run: the reads the startup reconcile resumes after a restart place it when they
settle, and none places a second; none is placed in a finished or an archived project. Its
pre-ruling pass, PilotProjects' `pre-rule` skill, may answer blocks as Pilot, defer them to a plan
task, and give an item of kind `document` it settled or deferred whole Pilot's own Done, cause
`settled`, which closes it as a person's Done does, its write-back and its continuation included;
Done takes no item of another kind, so a one-block document it answered stays open for a person.

## The close and the write-back

A registered document closes as any document does: Done, the answer that closes a one-ask item, an
action's Done that closes it, or Reviewed, which closes one with no block or whose read failed. The
close commits at once. A close that may continue its run holds the Project's row `FOR UPDATE` before
the Document's (below).

Once a close commits, the engine's `WriteBackOwed` asks for the loop `write-back:<session id>` of
the Session that registered the document, which writes every document of that Session whose text is
owed to its file, in the order registered: its published text, the answers in it, overwrites the
file it was registered from, or creates it and the folders it needs. Each write is made outside any
transaction and taken in one of its own under the Project's row, the Session's and the Document's,
unless the document no longer owes that text: an Undo during the write leaves it open, and an Undo
and a second close have the loop write the new text. A write taken sets `written_back_at`.

- **Refused**, for what is wrong with the file, its path or its environment: the controller's `404`
  (the environment gone, since a write makes the file), `403 path-outside-work`, `409 not-a-file`,
  `409 not-a-directory` or `413 file-too-large`. `write_back_refused_at` is set, and the
  registering Session's log gets `{"type": "write-back-refused", "item", "path", "reason"}`, in no
  Turn, live on its stream. It is not written again until the document's next close, after an Undo,
  or the Resume of the continuation that carries it.
- **Retried**: a write the controller does not answer, its `409 conflict` (its own work on the
  tree), its `503 environment-unreadable` or any other refusal of its own raises, and the loop runs
  again after its backoff.

A document whose read failed has no text to write. Finish's close, cause `finished`, owes no
write-back and continues nothing (D049): with no document of the run open and no continuation to
come, the environment is free. Undo of a closed document clears `written_back_at` and
`write_back_refused_at`, so that its next close writes it again. At STARTUP the job's reconcile runs
the writes every Session owes, from the rows.

## The continuation

The close that leaves none of the documents a run registered open places the run's continuation,
in its own transaction (D046): once the run's work item is done `turn_ended`, which a close implies
since nothing closes before its read, and never once one of them was closed by Finish, whatever
follows, since a Reopen leaves that close as it is. No continuation is placed while any of the run's
documents is open: the continuation waits on every one, and on nothing else. Another run's documents,
open or not, hold up none of it, so that two runs of one project each go on as soon as their own
documents are closed, each in its own environment; what waits on a run's open documents is the plan
skill's to leave unstarted (D076).

- **Placed** by `continue_run` ([`sessions.md`](sessions.md)): a new work item titled as the run, at
  the project's next place, after the answered items, its trigger the item whose close released it,
  on the run's plan task while the plan still has it, on none once it was removed. Its Session is in the run's environment from its placement on and continues the
  run's conversation, never reset, so it goes on in the tree as the run left it, with the answered
  files written back.
- **Its message**, the continuation's Turn 1, verbatim: "Your documents were answered and written
  back in place: <path>, <path>. Read the answers and continue." When a read failed, a second line
  follows: "Could not be read: <path>, <path>."; with none written back, that line is the message.
- **Undo goes** from every document of the run in that transaction: each is consumed by the
  continuation (`consumed_at`, `consumed_session_id`), and `ProjectChanged` moves the timeline
  (D047). It goes whether the continuation starts at once or is held: while the project is paused,
  the slot is full or the controller does not answer, Undo is gone though nothing has been sent.
- **Through the gate**, as every start ([`sessions.md`](sessions.md)): `held` while the gate is
  closed for it, else `starting`. Under a pause the person's answers go through, Done and the
  write-back included, and the continuation is held, its line saying "Paused", until the project
  resumes (D026). In an archived project every close is refused, so none places it: its project
  is archived (D012).
- **Its start writes back first.** Before its environment is brought up, which the controller
  refuses a write during, its start loop runs the write-backs the documents it carries still owe.
  One the controller refused, before or in that run, fails the start: its line reads "Failed ·
  Cannot write <path> back because <reason>", the reason read from the run's `write-back-refused`
  record, with a `start-failed` record in its own log. A `409 conflict` or a `503` waits it out on
  the loop's backoff, the line "Starting <environment>…" meanwhile; a controller that does not
  answer holds it; any other failure fails it.
- **Its Resume** owes the refused write-backs again (`RecordService.retry_write_backs`), so that its
  start writes them first, and sends the continuation's message, not `continue`, while no Turn of
  its Session has gone out ([`sessions.md`](sessions.md)).

A document the continuation registers is an item of its own, even from the run's path: the answered
one stays as it was closed.

## The environment

An environment of Pilot's own stays bound while a document a work item's run registered there is
open, so that no other start takes, resets or deletes it before the continuation is placed, and the
continuation's Session names it from then ([`controller.md`](controller.md)). The shutdown timer
may still stop it: neither the read nor the write-back needs it running. Once none of the run's
documents is open, the continuation's Session holds it as any Session holds its environment.

## Lock orders

- A read's or a write-back's take: the Project's row `FOR UPDATE`, the registering Session's, the
  Document's. A close that takes the Project's row first serialises with both.
- A close of a registered document: the Project's row `FOR UPDATE`, the Document's, then, placing
  the continuation, the slot's lock and an Environment's.
- A Resume of a continuation: the Project's row shared, its Session's, the Documents it carries, the
  slot's lock, then an Environment's.

## Testing it

The backend's tests are `backend/tests/services/test_turn_end_read_service.py` (the reads, their
refusals, the outage, startup, Finish racing a read, the lock order), `test_write_back_service.py`
(each close, a stopped environment, the order, the refusals, the retries, Undo, the outage,
startup, Undo racing a write, the lock order), `test_session_start_service.py` (`TestContinueRun`,
`TestRunContinuation`), `test_environment_service.py` (the binding) and
`test_project_event_service.py` (a second connection hears the release); and
`backend/tests/engine/test_record.py` (`TestRecordServiceRelease`, `TestRecordServiceRetryWriteBacks`,
`TestResumeMessage`, `TestRecordServiceReleaseLocks`, `TestRecordServiceWriteBackOwed`) and
`test_documents.py`.

`frontend/tests/work/registered.spec.ts` plays the round trip against the fake controller: a spec
writes the file with `controller.putFile`, registers it with `projects.register`
([`projects.md`](projects.md)), and ends the run's turn with `controller.finish(…, 'success')`, the
run playing a line naming its conversation first so that its continuation resumes it. A file removed
with `removeFile`, or a broken text, fails its read; once the read has published the document, the
file removed and `<path>/notes.md` written in its place makes the path a folder, so its write-back
is refused `409 not-a-file`. `fileText` reads what was written back, and `projects.reviewed` closes a
review over the API while the session log stands open.
