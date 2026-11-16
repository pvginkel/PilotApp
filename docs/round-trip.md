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
| `ClarificationService` (`backend/app/services/clarification_service.py`) | the clarification run placed at a pass's end, and the writer's reply recorded; `SessionStartService.clarify` places and starts it |

## A registered document

A registered document is a review on the timeline from its registration, in one of three states:

- **Awaiting its read**: open, with no text, its line titled by its file's name (`awaiting_read`,
  [`timeline.md`](timeline.md)). It takes no close until its read is made, succeeded or failed:
  every close of the record refuses it, "its file has not been read yet: it is read at the end of
  the turn that registered it", and the screens offer none (D045). It is Pilot's meanwhile
  (below).
- **Published**: its file as the run left it, published as written. Its text gives it its kind,
  title, summary and blocks, and its file in the tree (`inbox/<seq>-<slug>.md`,
  [`projection.md`](projection.md)); its version 1 is `registered`, of the Session that registered
  it. It is answered and closed as any document.
- **Its read failed**: `read_failed_at` set, no text. Its line keeps its file's name, opened it
  reads "The document did not load" ([`documents.md`](documents.md)), it closes with Reviewed as any
  document with no block, its work item's session log says why, and the continuation's message
  names it (D044).

**Pilot's or the person's** (`backend/app/services/working_on.py`). An open registered document
is Pilot's while Pilot's work on it is in flight, and the person's otherwise, read from the rows at
every read and never stored. It is Pilot's while:

- it, or another document the same Session registered, awaits its read, since the pass over them
  is placed only with the run's last read (below);
- the pass over it is in flight: the job after the turn of the work item that registered it, a
  Retry of it included, one pass covering every document that turn registered;
- the clarification run that asks its writer about one of its blocks is in flight, or the job
  after that run's turn (below);
- it has a block unanswered, and every one of them is held ([below](#held-through-the-run)).

A Work is in flight (`in_flight()`) while its item is open and its Session is `held`, queued at
the gate among them, `starting`, `running` or `idle`; while it is owed its nudge, the quota wall's
`failed` among them ([`usage.md`](usage.md)); and while it is a job the store's update not yet
lifted stopped, which the lift retries ([`store-update.md`](store-update.md)). Failed or stopped
otherwise, it is not, so a pass that fails or is stopped hands its documents to the person, and a
Retry of it, once placed, makes them Pilot's again.

A read takes all of it from a `Reading` of its own (`working_on.Reading`), made after the read's
last write and kept by no other read: every hold at once, by one query over the standing namings
and the Works of their runs, kept whole over 2,000 characters by a bound of its own
([`slice-test-plan.md`](slice-test-plan.md)), then the items that are Pilot's, a query per state. A
statement that reads a block held or an item Pilot's takes the ids the reading found. The reading
joins `work.trigger_item_id` to `items.created_by_session_id`, and neither is indexed: an index goes
on each once production's plans show the joins (D163).

A document that is Pilot's waits on nobody: `waiting()` (`backend/app/services/timeline_service.py`)
leaves it out, and with it the badge, the project's *waiting on you* and the project's notification
([`projects.md`](projects.md), [`notifications.md`](notifications.md)). Its timeline item carries
what Pilot does on it, `pilots_work`, and is one line ([`timeline.md`](timeline.md)); opened, it is
read-only under a gold strip, the pass's job in its head ([`documents.md`](documents.md)), and the
pass shows on it once it is the person's again ([`work.md`](work.md)). The app's controls take nothing on
it: an answer, an action's Done, whose note is the paste-back, and a document's Done are refused
`409`, "… because Pilot is working on the item", and so is each of them on a held block in a
document that is the person's, "… because Pilot is working on block A1", or `blocks A1, A2` for a
document's Done, read under the project's row (`ItemService`). Read and Reviewed answer no block
and are not refused. Pilot's own tools are not the app's controls, and the record takes their
writes as it does any other ([`mcp.md`](mcp.md)).

### When an ask became the person's

A block's `handed_at` is when it last came from Pilot's side to the person's to answer
(`backend/app/services/handing.py`). Whose a block is stays read from the rows: a block to answer,
unanswered and of an open item, is Pilot's while its item is Pilot's or a run holds it
([below](#held-through-the-run)). So a transaction that may move one reads the project's blocks
that are Pilot's before its writes (`sides`) and compares them once it has written (`hand_over`):
a block that was Pilot's and is the person's to answer now is handed at the move's instant, the
latest move kept; one that is Pilot's after the move has no `handed_at`, so one Pilot answers has
none; and any other keeps what it has, one the person's from its put none, one answered or of a
closed item the instant it was handed at. Nothing reads it to decide anything: the timeline's read
derives from it alone whether Pilot's note on the block, or on its document, came after the ask came
to the person, `late` ([`timeline.md`](timeline.md#reading-it)).

The moves compared are those to the person: a work item's or a job's turn end, done, failed or
interrupted, a pass's among them; a start that failed; a Stop, a
Close, a Stop and take over and the Cancel (below); the quota wall's settle
([`usage.md`](usage.md)); an environment stopped under a turn ([`sessions.md`](sessions.md)); a
project's transition that stops its Sessions, compared once after its closes, so that an Archive
hands the blocks its stops leave and a Finish, which closes their items, hands none; the
store's update's lift that leaves a job to a person's Retry ([`store-update.md`](store-update.md));
and the turn-end read (below), which makes its own document's blocks and can move those of a
document of its run read before it, Pilot's while another document of the run awaits its read and
the person's after the last read where no job follows it, after a Close for good or an Archive
since. And those back to Pilot: a Resume, a Retry, a work item added with its `claims` or `researches`,
and a clarification run placed. The instant is the move's own where it has one, a Stop's
`stopped_at`, a turn's end, a transition's, the lift's `lifted_at`, and the comparison's otherwise.
A chat's turn end is not compared.

A block that became the person's before the column has no `handed_at`.

## The read at the run's end

A run ends when its turn's `result` makes the work item done, cause `turn_ended`, its turn neither
interrupted nor in error ([`sessions.md`](sessions.md)); a turn that ends so under a cooperative
usage halt or its project's pause leaves the run open for its nudge, and the run ends at its first
such turn end with neither holding ([`usage.md`](usage.md)). Once that transaction commits, the loop
`read:<session id>` reads every document the Session registered that still awaits its read, in the
order registered, each through the controller outside any transaction, in the environment the
document was registered from, and takes what the read gave in a transaction of its own, under the
Project's row (`FOR UPDATE`), the Session's and the Document's. It takes nothing for a document that
no longer awaits its read, closed by Finish or read by another process meanwhile (`Document <path>
of session <id> no longer awaits its read`).

- **A clean text** is published as written (`publish_read`), and the timeline moves live.
- **A failed read**: the controller's `404` (the file or the environment gone), `403
  path-outside-work`, `409 not-a-file` or `413 file-too-large`, a refusal of the controller's own
  once its wait has passed (below), or a text with faults (`its text holds faults: line N: …`). The document keeps no
  text (`fail_read`, which emits `ProjectChanged` alone), and the registering Session's log gets the
  `server` record `{"type": "read-failed", "item", "path", "reason"}`, in no Turn.
- **Made again**, a refusal for a reason of the controller's own: its `409 conflict` (a link loop,
  a manifest it cannot read the layout from, or the path changed during the call, which settles),
  its `503 environment-unreadable`, or any other answer, a `401`, a `422` or a `500` among them. The
  read is made again every 5 s until 5 minutes have passed since its first refusal, and is then a
  failed read with the controller's last answer (D112, D222): the document shows *Did not load*,
  Pilot's job after the turn goes ahead, and the continuation's message names it among those that
  could not be read (below). The loop reads a round at a time, every document still owed in each,
  so that the run's waits run side by side (`RefusalWaits`,
  `backend/app/services/refusal_waits.py`). Unlike a write-back's, a read's wait does not first
  sit out an environment coming up: a read takes no `409` from a bring-up.
- **Retried**: a read the controller does not answer raises, and the loop runs again after its
  backoff ([`jobs.md`](jobs.md)), waiting the outage out, with no wait started. Each document is
  its own transaction: one failing leaves the others.

A run that stops or fails reads nothing: its documents await their reads until the run of its
Resume ends. A stopped run closed for good ([`work.md`](work.md)) is read once the close commits, or
once its stopped turn has ended, the relay telling the reads at each end of a stopped turn
(`TurnEndReadService.run_closed`): it takes no Resume, so its documents would otherwise stay Pilot's
for good. They are read and then the person's, and no job follows them. At STARTUP the job's reconcile runs the reads every Session owes, from the rows.

## Pilot's job after the turn

The take that leaves none of the run's documents awaiting its read,
a failed read settling as a published one does, places Pilot's job after the run's turn in its own
transaction, under the Project's row it holds (`JobService.worker_turn_ended`,
[`work.md`](work.md)); a run that registered nothing gets it in the transaction of its turn end. It
is placed once per run: the reads the startup reconcile resumes after a restart place it when they
settle, and none places a second; none is placed in a finished or an archived project. Its
pre-ruling pass, PilotProjects' `pre-rule` skill, may answer blocks as Pilot, defer them to a plan
task, claim an action a work item of Pilot's does (below), leave a block open for a work item of
Pilot's that checks a fact its answer rests on (below), ask the writer about a block it cannot read
(below), put what only Pilot knows of a block it leaves to a person in its note on the block, and
an alert on a document whose Send must wait on another ask (`note` and `alert`,
[`mcp.md`](mcp.md)), by exception alone, and give a document it settled or deferred whole Pilot's own Done, cause `settled`,
which closes it as a person's Done does, its write-back and its continuation included: an item of
kind `document`, or a registered document of one block, which has its block's kind, once that block
is answered, deferred, or claimed and done ([`engine.md`](engine.md)). Where the run's session gave
its debrief, the brief carries it whole after the documents (D219, [`work.md`](work.md#its-debrief)),
and the pass leaves it, puts what the operator must know of it in a note on the run's document
still open, or a notice where none is, or makes a card or a fieldnote of it; the debrief is no document,
with no block to answer and nothing to mark.

**A claimed action** (D085). An action Pilot may run under the grants, the pass claims: it adds the
work item that does it, the block named in its `claims` ([`mcp.md`](mcp.md)), then answers the
block `Pilot does it`, `by: agent`, the note naming the work item. The block stays open, held
through that work item's run (below), and its line names and links the work item
([`timeline.md`](timeline.md)). The job after that work item's turn names the claimed actions in
its brief, as does the job after the turn of a continuation of its run (D100;
[`work.md`](work.md)), and the plan skill writes each action's `done`, `by: agent`, the paste-back
its note; its document then closes by Pilot's own Done where that was its last open block, and the
write-back and the continuation follow as for any close.

**A researched block.** A block whose answer rests on a fact the pass has not read it leaves
unanswered and names in the `researches` of the work item that checks the fact
([`mcp.md`](mcp.md)), which registers a document of what it found. The block is held as a claimed
action is, and the job after that work item's turn, and the job after the turn of a continuation of
its run, names the researched blocks in its brief, so that the pass routes them on what the run
found ([`work.md`](work.md)).

## Pilot's questions to the writer

The pass asks a registered document's writer about a block it cannot read through `ask_writer`
([`mcp.md`](mcp.md)): a question a block, recorded as a Writer Question of the pass's Turn and
marked in the asked block's head ([`timeline.md`](timeline.md)). When the pass's job ends, idle
after its last turn or
failed, having asked, one **clarification run** is placed in that transaction
(`ClarificationService.pass_ended`), which puts every question the pass asked to the writer of the
run whose turn it took, whichever run's document a question names; a Stop places none. A pass whose
turn died at the quota wall is not at its end while its nudge is owed (D099): its run is placed when
the run its nudge continues ends, when that continuation's start fails, or when a reading decides
the wall missed, while its project is neither finished nor archived ([`usage.md`](usage.md)). It is a work
item (`SessionStartService.clarify`) titled `Clarify <names>`, the asked documents' file names,
at the project's next place, on the run's plan task, with no trigger item, its role a
`clarification_runs` row naming the pass ([`record.md`](record.md)); it resumes the run's
conversation in the run's environment, never reset, as the continuation does, through the gate. Its
first Turn groups the questions by document, `Pilot asks about <path>:` and `- <local id>:
<question>` a block, then ``Answer each under a heading per block id (`## D2`, `## D4`); register
nothing, start nothing; then end your turn.``, a heading `## <path> <local id>` where two asked
documents share a local id. Its turn's final text, at its idle end, is the writer's `reply`, with
`replied_at`, which moves the timeline; a turn that ends with no text records none. A turn that
ends so under a cooperative usage halt or its project's pause, the run left open for its nudge,
records its reply too, and no later turn of the run replaces it. The reply is
split per block under the headings asked for, a heading matched outside a fence at its level and by
its text, its part running to the next heading of the same or a higher level, and shown whole where
any heading is missing (`reply_parts`): the document's `clarifications`, the opened document's section
([`documents.md`](documents.md)). The job after the run's turn is briefed with it, *the writer
answered* ([`work.md`](work.md)), and asks nothing: `ask_writer` is refused there, and in a pass
whose run another pass asked about, so a Retry of a pass that asked asks nothing: one round per
worker turn. A clarification run that fails gets no job; its questions stand beside
the asks, the document open for the operator.

While another Session runs or starts on the conversation in its environment, the run's
continuation among them, the clarification run is held, its line "Waiting for the run before it",
and so is a continuation behind a clarification run: each waits for the other's turn to end
(`start_gate.carried`, [`sessions.md`](sessions.md)).

## Held through the run

A claimed action not yet done, and a researched block with neither an answer nor a `done`, is held
while the run of the work item its standing naming names holds it, the latest naming standing
([`engine.md`](engine.md)). The run is that work item and every work item on its conversation, its
continuations and its clarification runs, each with the job after its turn, the latest Retry of it
(D131). It holds the block until:

- **it is done with it** (D132): a work item of the run that is no clarification run is done at its
  turn's end, the latest job after that turn is done, and that turn registered no document with a
  block in it, so it asked the person nothing. A document of what a research found has no block, so
  it holds nothing up; a question the run puts to the person keeps the block held until they answer
  it and the job after the continuation's turn has ended;
- one of the run's work items, or the latest job after one of their turns, stands `failed` or
  `stopped` and is not in flight: a person's Stop, a take-over (below), an interrupted turn or a
  failure. A Resume or a Retry holds the block again;
- a document the run registered is closed `cancelled` (below).

While something of the run is in flight, a document it registered awaiting its read among them,
Pilot is doing the action or researching the block; otherwise the run waits on the person's answer
to the first of its open documents on the timeline that is the person's with no block held, else to
the first of its open documents (`working_on.py`'s `_asked_in`): so where another run's work holds
a block of an earlier one, or Pilot works on it, the strip and the take-over's refusal below name
one the person can answer. Its Cancel is still refused while any open document of the run is
Pilot's or has a block held (below). A held block takes no answer, Done, paste-back or offer's
taking from the app's controls (above), and in a document that is the person's it is its section's line
([`timeline.md`](timeline.md)). A claimed action the run no longer holds, its `done` unwritten, is
the person's again, its claim standing and its head saying that Pilot's work left it undone: where
the run was done with it, the job after that turn retries it in a new work item or leaves it to the
person with Pilot's note on the action saying why, written while the run still holds the block, since
`note` refuses a held block but from the job after a turn of the run that holds it (D239,
[`mcp.md`](mcp.md)), so the person reads the note inside the action once that job ends
(PilotProjects' `plan` skill). A researched block the run no longer holds is
open as any block. The job's brief ends the line of a block handed back so `handed back to the
operator: leave it to them`, and the continuation's message names them
([below](#the-continuation)).

## Stop and take over

**`POST /api/items/<id>/take-over`**, no body, answers `204` (`ItemService.take_over`): the
signed-in person's Stop and take over of a document that is Pilot's, which stops what of Pilot's
work holds it, by the person, so that it is theirs at once: the pass's job, its clarification run,
the job after the writer's reply, or what of the run holding its blocks is in flight
(`holding_work()`). `SessionStartService.take_over` takes each under its Session's lock, in id
order, after the project's row, and stops it while it is still in flight: one `running`,
`starting` or `held` as a work item's Stop stops it ([`sessions.md`](sessions.md)); one the server
would carry on from rest, `idle` or `stopped` with its nudge owed or a job the unlifted store update
stopped, `stopped` by the person at the take-over's time, its turn as it ended; one failed at the
quota wall stays `failed`. None is owed its nudge afterwards, and the store update's lift retries
none of them, since it retries Pilot's stops alone. One pass covers every document its worker's
turn registered, so its take-over hands each of them over, and a pass it ends puts no question to
the writer. A job stopped so shows as any stopped job does, with Retry, and its project's badge
counts it until it is retried ([`work.md`](work.md)).

It is a `409` "Cannot stop and take over item <id> because …" for a caller with no handle, and:
"Pilot is not working on it"; "it, or another document its run registered, has not been read
yet"; "Pilot waits on an answer to <path>, whose Cancel hands the blocks back", while the run
holding its blocks waits on the person; and "a document of the run holding its blocks has not been
read yet", between the turn's end of a work item holding its blocks and the reads of what it
registered. An item that is no document is a `404`.

## The Cancel

While the run holding a block waits on the person, the held document's strip offers no Stop: it
says Pilot waits on their answer to the run's document and links it ([`documents.md`](documents.md)).
That document offers the Cancel instead, which ends the run and gives its blocks back (D133). An
open registered document of a work item's run offers it, as the timeline's `cancel`, while it is
the person's, nothing of the run is in flight, a document of it awaiting its read among them, the
run holds a block of another document, and no other open document of the run is Pilot's or has a
held block. The timeline's `cancel` names the blocks it takes back and the run's other open
documents, `also_closes`, which the page's question names before the Cancel is made
([`documents.md`](documents.md)). It is the one way to call off a run's document: the chat's
`cancel_ask` refuses one ([`mcp.md`](mcp.md)).

**`POST /api/items/<id>/cancel`**, no body, answers `204` (`ItemService.cancel`): under the
project's row, every open registered document of the run is done at once by the person, Done Cause
`cancelled` (`RecordService.cancel`), which offers no undo, cuts no Version, owes no write-back and
continues nothing, as Finish's close does (D049). Once one of its documents is closed so, the run
holds nothing, and its blocks are the person's as above. The run is every work item on the
conversation of the work item that registered the document, so a Cancel on a continuation's
document closes the open documents of the whole conversation. It is a `409` "Cannot cancel item
<id> because …" for a caller with no handle, and: "the item is done"; "Pilot is working on the
item"; "it is no document a work item's run registered"; "its run holds no block of another
document"; "something of its run is in flight"; "Pilot is working on another document of its run,
or a block of one"; and "its project is archived". An item that is no document is a `404`.

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
- **Refused once its wait has passed**, for a reason of the controller's own: its `409 conflict`
  (its own work on the tree), its `503 environment-unreadable`, or any other answer, a `401`, a
  `422` or a `500` among them. The write is made again every 5 s while Pilot's record has its
  environment coming up or being deleted (`last_state` `provisioning`, `starting` or `deleting`, as
  the fleet stream reports it), then until 5 minutes have passed since its first refusal after that,
  and is then refused as above, with the controller's last answer (D112). The loop writes a round at
  a time, every document still owed in each, so that the documents a continuation carries wait those
  minutes side by side (`RefusalWaits`, `backend/app/services/refusal_waits.py`), and each close
  owes its write afresh, with a wait of its own.
- **Retried**: a write the controller does not answer raises, and the loop runs again after its
  backoff, with no wait started.

The waits are a run's own, in memory: a restart, or a run that raises, starts them afresh. A
wait's first refusal logs `Write-back of document <path> of session <id> refused, made again for
300 s: <reason>`, and a read's `Read of document …` the same.

A document whose read failed has no text to write. Finish's close, cause `finished`, and a
Cancel's, `cancelled`, owe no write-back and continue nothing (D049, D133): with no document of the
run open and no continuation to come, the environment is free. A close of a document whose run's
conversation ended at a work item closed for good continues nothing either (below). Undo of a closed document clears
`written_back_at` and
`write_back_refused_at`, so that its next close writes it again. At STARTUP the job's reconcile runs
the writes every Session owes, from the rows.

## The continuation

The close that leaves none of the documents a run registered open places the run's continuation,
in its own transaction (D046): once the run's work item is done `turn_ended`, which a close implies
since nothing closes before its read, and never once one of them was closed by Finish or a
Cancel, whatever follows, since a Reopen leaves a Finish's close as it is; nor where the latest
worker's run of the conversation, by its Item's `seq`, was closed for good, so that a clarification
run closed while its pass's documents are open is not continued by their close. No continuation is
placed while any of the run's
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
  Where the run held claimed or researched blocks that it handed back to the person, a last line
  names them, so that the run leaves them alone: "Handed back to the operator, so leave these to
  them: A1 of <path> (<item id>), …".
- **Undo goes** from every document of the run in that transaction: each is consumed by the
  continuation (`consumed_at`, `consumed_session_id`), and `ProjectChanged` moves the timeline
  (D047). It goes whether the continuation starts at once or is held: while the project is paused,
  the slot is full, the controller does not answer or a clarification run holds the conversation,
  Undo is gone though nothing has been sent.
- **Through the gate**, as every start ([`sessions.md`](sessions.md)): `held` while the gate is
  closed for it, else `starting`. Under a pause the person's answers go through, Done and the
  write-back included, and the continuation is held, its line saying "Paused", until the project
  resumes (D026). In an archived project every close is refused, so none places it: its project
  is archived (D012).
- **Its start writes back first.** Before its environment is brought up, which the controller
  refuses a write during, its start loop runs the write-backs the documents it carries still owe.
  One the controller refused, before or in that run, one refused for a reason of its own once its
  wait has passed, fails the start: its line reads "Failed · Cannot write <path> back because
  <reason>", the reason read from the run's `write-back-refused` record, with a `start-failed`
  record in its own log. The documents it carries are written in one run, their waits side by
  side, the line "Starting <environment>…" meanwhile; a Stop ends the wait between two rounds,
  and nothing is brought up. A controller that does not answer holds it.
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
- A pass's turn end that places its clarification run: the Project's row `FOR UPDATE`, then the
  pass's Session's, as a worker's turn end takes them; the conversation is read under the slot's
  lock. Every other turn end takes the Project's row shared before its Session's
  ([`sessions.md`](sessions.md)).
- A save of a document, one Pilot's work holds included: the Project's row shared, or `FOR UPDATE`
  where it may close an item of Pilot's own or writes a draft's title, then the Session it is
  credited to, then the Document's ([`engine.md`](engine.md)).
- A tool call's gate that reads its Session with no turn running: the Session's send lock shared,
  then the Project's row `FOR UPDATE`, both let go once read ([`mcp.md`](mcp.md)).
- A take-over: the Project's row `FOR UPDATE`, then each Session it stops in id order, as the relay
  takes them. A Cancel: the Project's row `FOR UPDATE`, then the run's Documents in id order. The
  app's answers, Dones and their refusals read what is Pilot's under the Project's row, which every
  placement of work and every Resume takes too, so no hold begins while they read.

## Testing it

The backend's tests are `backend/tests/services/test_turn_end_read_service.py` (the reads, their
refusals, the waits, the outage, startup, Finish racing a read, the lock order),
`test_write_back_service.py` (each close, a stopped environment, the order, the refusals, the waits,
the retries, Undo, the outage, startup, Undo racing a write, the lock order),
`test_refusal_waits.py`, `test_session_start_service.py` (`TestContinueRun`, `TestRunContinuation`,
`TestClarify`), `test_clarification_service.py` and `test_relay_service.py`
(`TestClarificationRun`), `test_environment_service.py` (the binding) and
`test_project_event_service.py` (a second connection hears the release); and
`backend/tests/engine/test_record.py` (`TestRecordServiceRelease`,
`TestRecordServiceRetryWriteBacks`, `TestResumeMessage`, `TestRecordServiceReleaseLocks`,
`TestRecordServiceWriteBackOwed`, `TestRecordServiceCancel`) and `test_documents.py`. What is
Pilot's is pinned in `backend/tests/services/test_working_on.py` (the hold, its hand-back and its
end, `TestWhatWaits`, `TestFlying`, `TestHoldingWork`, `TestACancel`), on records built by `Camp`
(`backend/tests/support/working_on.py`); when an ask became the person's in `test_handing.py`, at
each move's own test (`TestHandedAt` in `test_session_start_service.py`, and in
`test_relay_service.py`, `test_item_service.py`, `test_job_service.py`,
`test_pilot_store_service.py`, `test_project_service.py` and `test_store_updater.py`) and in
`backend/tests/migrations/test_0037_a_blocks_handed_at_and_a_sessions_end.py`; the timeline's fields in `TestPilotsWork`
(`test_timeline_service.py`); the take-over in `TestTakeOver` (`test_session_start_service.py`),
`TestItemServiceTakeOver` (`test_item_service.py`) and `TestTakeOver` (`tests/api/test_items.py`);
the refusals while Pilot works in `TestItemServiceWhilePilotWorks` and `TestWhilePilotWorks`; and
the Cancel in `TestItemServiceCancel`, `TestCancel` and `test_environment_service.py`. Both
services take their waits as
`refusal_wait_seconds` and `refusal_retry_seconds`, which the tests set small, a continuation's
through the container's `write_back_service` (`_write_backs_waiting`), and `RoundsHandle`
(`backend/tests/support/supervisor.py`) runs the test's own step between two rounds.

`frontend/tests/work/registered.spec.ts` plays the round trip against the fake controller: a spec
writes the file with `controller.putFile`, registers it with `projects.register`
([`projects.md`](projects.md)), and ends the run's turn with `controller.finish(…, 'success')`, the
run playing a line naming its conversation first so that its continuation resumes it. A file removed
with `removeFile`, or a broken text, fails its read; once the read has published the document, the
file removed and `<path>/notes.md` written in its place makes the path a folder, so its write-back
is refused `409 not-a-file`. `fileText` reads what was written back, and `projects.reviewed` closes a
review over the API while the session log stands open. `clarification.spec.ts` plays the
clarification run, its held continuation and its reply, and `claimed.spec.ts` a claimed action and
a researched block, held, handed back, taken over and cancelled. A spec that ends a run which
registered a document ends the pass after it too, since the pass's job runs in the fake's store
environment: `const passed = await chats.passing(project)`, then the run's end, then `await
passed()`; `chats.pass(project)` answers `{running(), end()}`, the pass running between the two
([`chats.md`](chats.md)).
