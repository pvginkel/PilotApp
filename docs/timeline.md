# The timeline

A project's timeline as a signed-in person reads and answers it: the read, the writes on its items,
the live event, and the screen under the project's head. The read is `GET
/api/projects/<id>/timeline` in `backend/app/api/projects.py` on `TimelineService`
(`backend/app/services/timeline_service.py`); the writes are `backend/app/api/items.py` on
`ItemService`, which calls the engine's `RecordService` ([`engine.md`](engine.md)); the screen is
`frontend/src/components/timeline/`. The texts are written in the block DSL
([`block-dsl.md`](block-dsl.md)), and the project's head and list are
[`projects.md`](projects.md)'s. A document read on its own, the overlay it opens in, the
attachments and the side panel are [`documents.md`](documents.md)'s.

## Reading it

**`GET /api/projects/<id>/timeline`** answers the timeline whole, `{finished_at, items, ready_after,
unhung_attachments}`, and `404` for an unknown project. `finished_at` is the latest `finished`
transition's time while the project is finished, else null. `ready_after` is the setup's work item,
its latest Retry's where it was retried, once it is done at its turn's end, while the project stands
paused by the pause Create wrote (D083, [`projects.md`](projects.md)); else null.
`unhung_attachments` are a draft's attachments hung on no item, by batch and then file name, in an
item's attachments' shape: what its definition chat attached, which Create project hangs on the
opening, so none past Create ([`documents.md`](documents.md)). `items` are every item, by `seq`,
each with:

- `id`, `seq`, `kind` (an item kind's code) and `form` (`prose`, `work` or `wait`);
- `title`, null for a registered document whose text gives none or that has no text, and
  `file_name`, a registered document's file name from its source path, which its line shows while
  `title` is null;
- `awaiting_read`: whether it is a registered document whose file has not been read yet, at the end
  of the run that registered it ([`round-trip.md`](round-trip.md)); until then it has no text and
  takes no close;
- `created_at`; `step`, `{id, title}`, the plan task it serves with the task's title live from the
  plan (a removed task's last), or null; `urgent`; `for_user`, a person or null;
- `done`, null while open, else `{at, cause, by, undo}`: `by` is null when the server did it, and
  `undo` whether the record takes Undo now (`RecordService.offers_undo`);
- `concept`: whether a `parse` Save Error stands on its document's path, its latest save held, so
  that its text is the one last published (F78);
- the opening's `author` and its `words`, verbatim; null on every other item;
- `body`: every other prose item's text as drawn (`dsl.body`), its parts in order, `{type: prose,
  markdown, section}` and `{type: block, block}`, the front matter and the heading that is the
  title left out; null for the opening, work and waits, and for a registered document with no text,
  awaiting its read or after one that failed. A prose part's `section` is the local id of
  the block whose own section holds it, null outside every section ([`block-dsl.md`](block-dsl.md));
- `summary`: the front matter's `summary`, null where the text gives none and for the opening, work
  and waits;
- `word_count`, the text's own count (`dsl.words`), which no answer, Done or Undo moves, and
  `read_minutes`, that count at 230 words a minute, rounded half up, at least 1; both null where
  `body` is;
- `writing`: whether a session's running turn is saving the text (`Document.writing_session_id`).
  A save in its session's turn sets it, one landing after that turn ended never, and the turn's
  end clears it, each raising `project_changed` ([`engine.md`](engine.md));
- `edited_at`: the time of the latest `turn` Version that follows the first Version whose text has
  anything in `dsl.body`, the first text the item was shown with; null where no such Version
  follows it, and where `body` is null (D032);
- `attachments`, on every item, work included, in the order they hang on it: `{id, title, filename,
  content_type, size, batch, copied_at, source}`, `batch` the project's attach call it came in,
  from 1, and `source` where it was copied from, `<environment>:<path>`, null for the draft's copy
  that Create project hangs on the opening. Its bytes are streamed apart
  ([`documents.md`](documents.md));
- `clarifications`: Pilot's questions to a registered document's writer and the writer's reply, one
  per pre-ruling pass that asked about its blocks, in the order first asked, which is one in
  practice ([`round-trip.md`](round-trip.md)); empty on every other item. Each is `{asked_at,
  questions, reply, replied_at, split}`: `asked_at` when the pass first asked about the document;
  `questions` in their blocks' order, each `{block, question, asked_at, heading, reply}`, the local
  id, the words verbatim, the heading the writer was asked to answer it under, and its part of the
  reply, null until the reply comes and where the reply does not keep that heading or holds nothing
  under it; `reply`, the run's turn's final text whole, which may answer another document's
  questions too, and `replied_at`, both null until it comes; `split`, whether every question has
  its part, so the reply is shown per block, else whole;
- `work`, a work item's status, its Session as its line shows it, null for every other kind
  ([`work.md`](work.md));
- `wait`, a wait's own, null for every other kind ([`waits.md`](waits.md)): `cards` and `states`, a
  card wait's, as the brain gave them, and `due_at`, a timed wait's, each null on the other kind;
  `firings`, in order, each `{seq, cause, fired_at, transition, requested_by, outcome}`,
  `transition` `{card, from_state, to_state, at, by}` for a card's change of state and
  `requested_by` a person for a request, each null otherwise, and `outcome` what the brain did with
  it, `pilots_turn`, `left_open` or `closed`, null where it did nothing; `request`, `{label, open,
  refusal}`, the head's button, `label` *Check now* or *Skip wait*, `open` whether the wait takes a
  request now, and `refusal` why not, null while it does; and `note`, the brain's words at its close
  through `mark`, null while open and after Finish's close. A wait waits since its `created_at`;
- `pilots_work`, what Pilot does on the item while it is Pilot's ([`round-trip.md`](round-trip.md)),
  null while it is the person's or done, and on every other item: `{doing, work, pulse, asked_in}`.
  `doing` is `awaiting_run`, it or another document its run registered awaiting its read;
  `pre_ruling`, its pass in flight, or the pass after the writer's reply; `asking_writer`, the
  clarification run its pass asked for in flight; and, with every open block held, `doing` or
  `researching` while something of the run holding them is in flight and `waiting_on_answer` while
  that run waits on the person. `work`, `{id, title}`, is what its line goes to: the work item that
  registered it while `awaiting_run`, the pass's job while `pre_ruling`, the work item the standing
  claim or research of its first held block names otherwise, and null while `asking_writer`.
  `pulse` is whether the session doing that work is queued or held, starting or running, never
  while `awaiting_run` or `waiting_on_answer`. `asked_in`, `{id, title}`, the title the line's, the
  file's name where the text gives none, is the run's first open document on the timeline while
  `waiting_on_answer`, else null. `awaiting_read` tells a document with no text from one already
  read while another of its run awaits its read, both `awaiting_run`;
- `cancel`, the Cancel the item offers ([`round-trip.md`](round-trip.md)), null while it offers none:
  `{takes_back}`, the blocks the run holds, in timeline order, each `{document, block, heading,
  kind, research}`, its document `{id, title}`, its local id, its own section's heading or null,
  its kind, and whether the run holds it as a research rather than a claimed action.

A block is `{id, kind, confirmation, because, proposal, default, check, options, answer, by, at,
note, via, done, claim, held, deferral, writer_asked, section}`. `id` is its local id; `because` is a
confirmation's reason, `{code, name, description, asks_under_autopilot}`, the grants table's name
and the line the agent reads, not the card's words, and whether it asks under auto pilot too;
`options` are `{label, text, recommended}` in order; `via` is `app` for a person's answer whose text
names no channel; `in_chat` is where in a chat the answer was recorded, `{chat, seq}`, the chat's id
and the number in its records of the `server` record placing the latest `answered` effect on the
block, read through the session's records route ([`sessions.md`](sessions.md)), and null unless
`via` is `chat` and that effect's call ran in a chat; `claim` is an action Pilot claimed and has not
done, `{work, undone}`, `work` the work item that does it, `{id, title}`, the one named for it last,
or null while none is ([`engine.md`](engine.md)), and `undone` whether Pilot's work left it undone,
the run of that work item having handed it back, done with it, failed, stopped or cancelled, false
while it is held and while no work item is named for it; null on every other block; `held` is what
holds a block while Pilot's work holds it, a claimed action or a block a research checks a fact for
([`round-trip.md`](round-trip.md)), `{doing, work, pulse, asked_in}` as `pilots_work` has them,
`doing` one of `doing`, `researching` or `waiting_on_answer` and `work` the work item its standing
claim or research names, and null while it is not held; `writer_asked` is whether Pilot asked the
registered document's writer about the block; `deferral` is `{to, title}` while `answer`
is `deferred`, `title` the task's title live from the plan and null for `to: plan`, the project's
end; `section` is the block's own section, `{heading}`, the heading's text, or null. A person or
Pilot, wherever one is named, is `{kind, handle, name, initials, avatar_slot}`, Pilot `kind: agent`
with no slot.

## Answering it

Seven routes under `/api/items/<item_id>`, each the record's own write, as the caller, now, through
the app, answering `204` with no body:

| Route | Body | Does |
|---|---|---|
| `POST blocks/<block_id>/answer` | `{answer, note?}` | a block's answer: an option's label, `Agree` to a proposal, `Yes` or `No` to a confirmation, or free words; the note, an action's paste-back or a No's reason |
| `POST blocks/<block_id>/done` | `{note?}` | Done on an action without options, the note what was pasted back |
| `POST done` | | Done on a document, with its recommendations |
| `POST read` | | Read on a notice |
| `POST reviewed` | | Reviewed on a review |
| `POST undo` | | Undo of a done item's answer or mark, whoever gave it |
| `POST request` | | a wait's firing requested by the caller, *Check now* on a card wait, *Skip wait* on a timed wait, which the wait's next run is briefed with ([`waits.md`](waits.md)) |

Stop and take over, `POST take-over`, and the Cancel, `POST cancel`, are
[`round-trip.md`](round-trip.md)'s. An answer, an action's Done and a document's Done are refused
while the item is Pilot's or the block is held, with "Pilot is working on …" (there).

An answer or a Done on a one-ask item is the item's done. Neither body takes `to` or `via`, and
neither takes another key (`400`): the page never defers. The archive question takes `Archive` or
`Keep` alone, and its Archive archives the project in the same act ([`projects.md`](projects.md));
its Undo is refused. An unknown item answers `404` "Item <id>
was not found", and a block the item lacks, any block of a work item or of the opening, `404`
"Block <item>/<block> was not found". A caller who has not chosen a handle, and every refusal of the
record, an archived project's close or Undo among them, "its project is archived" (D012), answer
`409` with the record's reason ([`engine.md`](engine.md)); Undo takes no person, so
it needs no handle. A request on an item that is no wait, or on a wait that takes none now, is a
`409` with the reason, "Pilot is checking" among them ([`waits.md`](waits.md)). The routes are behind the API's sign-in and `editor` role
([`sign-in.md`](sign-in.md)).

## Live

Once a change to what a project's timeline, head or tab shows commits, the engine's
`ProjectChanged` ([`engine.md`](engine.md)) goes to every person's connections as the SSE event
`project_changed`, `{"project_id": "<id>"}`, the writer's own browser included
(`ProjectEventService`, `backend/app/services/project_event_service.py`). A person is a user with a
handle, so a connection whose user has none hears nothing. Only the process that holds a connection
delivers to it. A work item's status moves on an event of its own, `work_moved`, which carries it
and moves nothing else ([`work.md`](work.md)).

`useProjectEvents` (`frontend/src/hooks/use-project-events.ts`), called by the shell, reads again,
on the event, the project lists and the named project's head, timeline, handbook, project document
and chats ([`chats.md`](chats.md)), and every document read of an item of it
([`documents.md`](documents.md)), events that arrive together once after them, a first read still
under way cancelled and made again, since it may predate the event; and on every rise of
the stream's `isConnected`, the first included, every one of those reads, which covers an event sent
from a process that does not hold the browser's stream. A person's own write reads every query again
as well. Each `work_moved`'s status it writes into the timeline as read, with no read.

## The timeline

`Timeline` (`timeline.tsx`) draws under the project's head, from `useTimeline`
(`hooks/use-timeline.ts`). It draws every item in its order, the opening first. Every project it draws has its opening: a draft draws its definition chat in the
timeline's place ([`chats.md`](chats.md)).

- **Dividers** (`rows.ts`). A day divider falls at each new date in the browser's time zone,
  "Thursday 22 October"; a step divider where the step changes, the task's title. An item serving
  no step starts no divider and ends no step. No divider falls between consecutive work items: a
  run of them stands under its last member's day and step dividers, placed before the run.
- **Anchored to its end.** It opens at its end and stays there as items arrive or its height
  changes, until the reader scrolls more than 48px away from it. An item that arrives after the
  first read flashes once.
- **The ready line.** While `ready_after` names the setup's work item, one line stands right under
  its line, before the items the setup placed after it: Pilot's avatar and "The project is ready —
  resume the project to start it." (`rows.ts`'s `ready` row). It has nothing to press, and it goes
  at the first resume ([`projects.md`](projects.md)).
- **The opening** (`opening.tsx`) is a bubble beside its author's avatar, "<who> started this
  project · <time>" over it, "You" for the signed-in person and the full name for the other; its
  words verbatim, folding with Show more, and its attachments under them. It has no head and is
  never done.
- **An open item** (`item.tsx`) is its head, its title (`title`, else `file_name`), its text and
  its attachments; a document and a review draw as [below](#documents-and-reviews). The head
  (`item-head.tsx`) is the kind's icon and label (`kinds.ts`; a confirmation's is "Confirm", a
  document's "Document · N" with its most common block's icon), the time, the full stamp as its
  tooltip, a confirmation's auto pilot mark (below) and reason line, the Urgent chip and "for
  <full name>" while it is for someone, and at its end Discuss,
  quoting the item into the chat ([`chats.md`](chats.md)). The kind never wraps, and where the
  head's parts are wider than the card the head wraps, so that none leaves it or widens the page. The text's prose is GFM
  (`Markdown`, [`ui.md`](ui.md)); the prose before the first block folds past 13.5em with Show
  more, the ask stands in that block's place, and the prose after it shows whole. A concept has a
  dashed border. An open work item is its session's: its env chip once its start has an
  environment, its one line and its Stop or Resume, a job of Pilot's own its Retry once it failed or
  stopped ([`work.md`](work.md)).
- **An item Pilot is working on** (`PilotsLine`, `item.tsx`), its `pilots_work` set, is one line,
  as a done line is: a dashed circle in the time's grey in its kind's place, "Pilot is working on
  it" its tooltip; the title (`title`, else `file_name`); Open once its text is read; Discuss; what
  Pilot does; and the time it was placed. What Pilot does (`PilotsButton`, `pilots.tsx`) is a ghost
  button: a pulsing dot while `pulse`, Pilot's mark, and the words `pilotsDoingLabel()` gives
  `doing` (`status-labels.ts`), "Awaiting the run", "Pre-ruling", "Asking the writer", "Doing it",
  "Researching" or "Waiting on your answer". It goes to `work`'s address, "Go to the work item:
  <title>" its tooltip, or while `pre_ruling` to the pass's session log, "Open the session log of
  Pilot’s job: <title>"; while `work` is null its words stand still, "Pilot is working on this: it
  comes to you once Pilot is done". At 900px and below it takes a row of its own under the title.
  The line takes no answer and is not open: it is neither tinted urgent nor a concept and "N open
  above" leaves it out, while its urgent banner stands. The pass's job keeps its own line beside it
  ([`work.md`](work.md)).
- **An open wait** (`wait.tsx`) is its head, its title and what it waits on
  ([`waits.md`](waits.md)). Its head's kind is "Wait", with the ticket for a card wait and the
  hourglass for a timed wait, and just before Discuss, touching it, stands the request's one button:
  an icon alone, the operator's hourglass, two chevrons in place of its lower bulb's right half
  (`hourglass-skip.tsx`), its label its tooltip, *Check now* on a card wait and *Skip wait* on a
  timed wait. A press records
  the request. While the wait takes none the button is disabled, its tooltip the reason, "Pilot is
  checking", "The wait is done", "Its project is finished" or "Its project is archived", and it
  stays disabled from a press until the read holds the firing the press made. A card wait shows its
  cards, each a ticket link, and its states, "SR-1, SR-4 → Done or Won't fix", then "Waiting since
  <time>" and its firings, a line each: "SR-4 → Done", the card a ticket link, or "Check requested
  by <handle>", then its time and, where the brain did anything with it, what: "Pilot’s turn", "left
  open" or "closed", " · " between them. A timed wait shows its due time from now in one coarse
  unit, minutes to weeks, rounded, a count that reaches the next unit's size moving up to it: "Due
  in 7 minutes", "Due now" within a minute either side, "Due 5 minutes ago", counted again every
  15 s, and once its due time fired it what the brain did, "Due 5 minutes ago · Pilot’s turn". Its
  requests, "Skip requested by <handle>", are its firings' lines. Every time has its full stamp as
  its tooltip, and one off today shows its date.
- **Attachments** (`attachments.tsx`) are chips, the clip and the title, a long one cut short:
  after a one-ask item's or a notice's text, at a confirmation card's end, in the opening's bubble,
  after an inline document's text and on a card. A chip opens the attachment in the overlay
  ([`documents.md`](documents.md)).
- **Pilot asked the writer.** A block whose writer Pilot asked about it (`writer_asked`) carries
  Pilot's mark and "Pilot asked the writer" in its head (`WriterAsked`, `writer-asked.tsx`), a link
  to the document's clarification address, `/projects/<project>/documents/<item>/clarification`,
  which opens the overlay at the box of Pilot's questions and the writer's reply
  ([`documents.md`](documents.md)); in the overlay it is a button that goes to the box there. A
  one-ask item's block and a confirmation's, whose head is the item's, carry it in the item's head.
  A held block's line carries none, opened or not, and a settled section's line none, though its
  block's head does once opened; a card and a done line show nothing of it.
- **The auto pilot mark** (`autopilot-mark.tsx`) stands on an open confirmation the switch would
  answer while the project's auto pilot is off: its reason does not ask under auto pilot
  (`because.asks_under_autopilot` false), it is unanswered and its item open (`may-take.ts`). It is
  Pilot's mark with a filled bolt cut out at its foot, bare, in the time's grey, at a kind icon's
  size, its hover "Auto pilot will handle this for you": after the time in a confirmation card's
  head, and beside the kind in a confirmation block's head, inline and in the overlay. A document's
  card carries it as a chip last among its counts, "N auto pilot may take", hovering "Auto pilot
  will handle these for you" (or "this" for one). It goes once the block is answered or auto pilot
  turns on, and comes back when it turns off; the handbook's, the project document's and a draft's
  blocks never carry it. Turning auto pilot on while any stands asks first
  ([`projects.md`](projects.md)).
- **Pilot writing.** While a session's turn saves an item's text (`writing`), Pilot's avatar and
  three dots, one at a time brightening, end the open item, every kind but the opening. The save
  that makes the turn the text's writer and the turn's end each raise `project_changed`, so the
  dots come and go as they happen.
- **Urgent.** An open urgent item is tinted, its kind's label in the urgent colour. Each has a
  banner pinned at the top of the timeline, in their order, "Urgent · <title> · Show", whose click
  scrolls the item to the middle and flashes it; a finished project's timeline pins none.
- **"N open above"**, a chip under the banners, counts the open items whose end is scrolled out
  above them, the other person's included, never a done line or the opening; its click scrolls the
  nearest of them to the top.

## Documents and reviews

`document.tsx`, by what `document-state.ts` reads of the item. A document of up to 150 words of its
own (`word_count`) stands inline; a longer one, and every review, leaves a card (`isCard`). No
answer moves the count, so a document stays as it stands while it is answered.

- **Its head** is an item's head, then *Edited <time>* and *Unsent* (below).
- **Inline**, it is its head; its title; its prose and its blocks in order, each block answered in
  place as a one-ask item's is ([below](#answering-inline)), its own head naming its kind; its
  attachments; Pilot's dots; and the segment bar beside *Send answers*, the bar empty where it has no
  block.
- **A card** is its head over a box: the title, the summary, the count chips, the segment bar, or "N
  min read" (`read_minutes`) for a text with no block, as every review is, the attachments, and
  Open, which reads Continue while the document is *Unsent*, beside Reviewed on a review; Pilot's
  dots follow the box. The chips count the blocks by kind, a confirmation as a decision, an action
  Pilot claimed among the actions while it is open, but for Pilot's answers: "N settled by Pilot",
  and "N deferred" for its deferrals; a count of none has no chip. The auto pilot chip comes last.
  Open goes to the document's address, which opens it in the overlay
  ([`documents.md`](documents.md)); none of the text shows on the card. Reviewed (`POST reviewed`)
  makes the review a done line.
- **A registered document with no text** after a failed read is a review's card titled by its
  file's name, with no "N min read", a warning chip beside the name, *Did not load*, and its
  Reviewed, which closes it ([`round-trip.md`](round-trip.md)). Awaiting its read, it is Pilot's
  line (above). Its text, once read, gives it its title and its blocks live, on a review's card as
  any other.
- **The segment bar**: a segment per block, filled once the block is answered, a claim only once
  its action is done, and a held block's in the plan donut's in-progress colour (`.seg.held`), its
  tooltip what the block asks, its section's heading, else its kind, and whether it is answered,
  open or one Pilot is working on. Inline, a segment
  scrolls to its block, which flashes; on a card it opens the overlay at the block's address.

**Unsent and Send answers** (D026, D033). A document reads *Unsent* while it has an answer and no
Done: a person's answer or Pilot's, an action's Done among them. A deferral alone is no answer here,
since it asks nothing of the person, and neither is a recommendation or a claim not yet done; a held
save, `concept`, has nothing to do with it (`isUnsent`). The document's Done is *Send answers*,
which fixes the answers and sends them back while the work goes on (`POST done`). It enables once
every unanswered block has a recommendation and no block is held, its tooltip while one is "Pilot
is working on a block of it: send once Pilot is done"; with any block unanswered it asks first, in
a dialog,
"Send with the recommendations?", a line per unanswered block, "<ask> · <answer>", a proposal's
answer "Agree: <proposal>" and a confirmation's "Yes: <proposal>", whose Confirm sends, the record
answering each block with its recommendation. An action's Done keeps its name, and a one-ask item,
its answer being its done, has neither.

***Edited <time>*** (D032), Pilot's mark and the clock in a document's head, says that Pilot changed
the document in a turn after the first text it was shown with (`edited_at`). No read is recorded:
the label means changed since first shown, not since you read it.

**A settled section** (`sections.ts`, `settled.tsx`). A block's own section
([`block-dsl.md`](block-dsl.md)) whose answer is Pilot's, a deferral included, stands collapsed to
one line in its block's place, inline and in the overlay alike: Pilot's mark, the heading's words,
"·", the answer as the closed block shows it ("Deferred to <task>", a proposal agreed to as the
proposal, an action's Done), a chevron, and the note as a second muted line, each clipped;
consecutive lines are one list. A click on it, a segment of its document's bar or the block's
address opens it, and it stays open on that page, the timeline or the overlay, each its own, while
the page is shown. A person's answer is not Pilot's, so it opens the section for good, and Undo,
which never gives Pilot its answer back, leaves it open. A block with no section never collapses.
The count, the bar and *Send answers* are the same whether it collapses or not.

**A held block** (`held.tsx`). In a document that is the person's, a held block's own section
stands as one line in its block's place, inline and in the overlay alike, as a settled section's
does: Pilot's mark, the heading's words (the kind's label where the block has no section), "·",
what Pilot does as the line's button, without Pilot's mark, and a chevron; the claim's note as a
second muted line. A click on the line or its chevron, a segment of its document's bar or the
block's address opens the section under it, its prose and the block's controls, disabled; a click
closes it again. In a document that is Pilot's every block is drawn whole, under the overlay's strip
([`documents.md`](documents.md)).

## Answering inline

A one-ask item's block, and each of a document's (`block.tsx`), is answered in its place; each
click or Send posts through `useAnswer` (`hooks/use-answer.ts`). The block's form, `BlockPanel`, is
the one every ask is drawn with: an item's (`Block`), the handbook's and the project document's in
the overlay, read only (`DocumentBlock`), and a draft's in its Draft tab, answered through the
draft's routes (`DraftBlock`, `useDraftAnswer`, [`documents.md`](documents.md)). A one-ask item
becomes its done line once the screens read it back; a document's block stays, answered, until *Send
answers*.

- **A decision** (`decision.tsx`): its options as full-width rows, each its label, its line and
  Recommended on the recommendation; a proposal is one row, tinted as recommended, that answers
  `Agree`; Other comes last, "Something else", and opens a console. While an answer saves, its row
  fills and the others fade, disabled.
- **A question** (`question.tsx`): the field, "Your answer", or "Default: …" where the block has a
  default, and Send. Send with the field empty answers the default; with no default it is disabled
  while the field is blank. The answer shows boxed while it saves.
- **An action** (`action.tsx`): without options, a paste-back field, "What to paste back, if
  anything", over Done; with options, a button each, the first primary, and Other…, whose console
  sends its words as the answer. The paste-back goes as the note of the Done, the option or the
  words. An action Pilot claimed is open until its `done`. Unless its held line says so, it reads,
  while nothing saves, Pilot's avatar, "Pilot does it" and " · " the work item that does it, linked
  to its address, with the claim's note under it, over the controls: disabled in a document that is
  Pilot's, and a person's where no work item is named for it. One Pilot's work handed back
  (`claim.undone`) reads nothing of the claim: its head, drawn in a one-ask item too, says "Pilot’s
  work left it undone", "<work item> ended without doing it: it is yours again" its tooltip, and its
  controls are a person's, whose Done is answered as any person's is.
- **A confirmation** (`confirmation.tsx`) is a card: its head with the reason line, plain words by
  the reason's code with the ground as its tooltip (`item-head.tsx`'s `WHY`: "Auto pilot off",
  "Always asks: cannot be undone", and so on; a code without words of its own shows `because.name`);
  the title and the proposal beside the check, Yes, and the cross, No, which opens a console for the
  reason that sends empty too, "Send No"; and Details, which unfolds the prose, and Less. Inside a
  document a confirmation is a block, its proposal beside the same Yes and No. A standing grant, a
  permission meant to outlast the project or reach past it, is a reason of its own,
  `standing-grant`, which asks under auto pilot too, so the switch never answers it (D086): "Always
  asks: a lasting permission", its tooltip "The permission would outlast the project or reach past
  it; Pilot asks even under auto pilot".
- **A notice** has Read.

A console (`console.tsx`) is the growing text field with Send and a cross, Cancel, inside its
border; Ctrl+Enter (Cmd+Enter on a Mac) sends it and Esc closes it, and its Send is disabled while
it is blank, a No's excepted. While its field has the focus, a resize of the window, as a phone's
keyboard makes as it opens, scrolls the console back into view. Its words, and every field's here,
are kept in the browser until sent ([`ui.md`](ui.md)).

**An answered block on an open item**, Pilot's answer or a deferral, has a head: its kind, a
chevron, Answered, the time and the avatar of who answered, Pilot's mark for Pilot, and before the
time *In the chat* where the answer was given in the chat (`in_chat`), which goes to the message
that gave it ([`chats.md`](chats.md)). An answer that is not a person's reads closed, the answer
alone, and opens, on a click or the chevron, to the block's controls, live, so that the person can
replace it. A deferral reads "Deferred to <task>", or to *the project's end*, with its note; opened,
the controls stand under that line with nothing chosen. A note stands under its answer with the note
icon. In a document every block has that head, its kind named, once answered Answered, and at its
end Discuss, quoting the block into the chat; a one-ask item's block has no Discuss of its own, its
item's head quoting the item. In a done item, as Open shows it, every answered block reads closed, a
person's answer too, and opens to its controls, all disabled.

## Done lines and Undo

A done item is one line that does not expand: its kind's icon, or a confirmation's green check for
Yes and red cross for No; its title; Open; its attachments' indicator; Undo while `done.undo`;
Discuss, quoting the item into the chat; and the time it was done. Under the title stands a
person's answer to a one-ask item, the other person's after their avatar, its note after " · " with
the note icon: an option, the words, or "Deferred to <task>"; a confirmation's Yes or No shows only
its note, and nothing of Pilot's shows. After an answer given in the chat stands *In the chat*,
kept whole however the answer is cut ([`chats.md`](chats.md)).
Undo ("Undo, until a session has taken it") opens the item again, and a one-ask item's block
unanswered. A worker's registered documents lose it together, as the close of the last of their run
places the continuation that takes their answers ([`round-trip.md`](round-trip.md)). An item of
Pilot's own loses it once the brief of the job its close placed goes out, at once in an idle
project, and an Undo before then withdraws that job ([`work.md`](work.md)).

- **Open**, on every done line but a wait's, opens the item's document in the overlay at its
  address, as Done fixed it ([`documents.md`](documents.md)).
- **The attachments' indicator**, where attachments hang on the item, whatever its kind: the clip
  opening the one attachment, as the chips carry it, set apart from Open's document icon beside it
  (D039), or a documents icon opening a menu of them, which drops under its button at the line's
  end, no wider than the line.
- **A document Pilot marked Done** (cause `settled`, which no unanswered block allows) is a done
  line as any other, and its overlay's foot names Pilot.
- **A work item's line** is quieter than the others: set in behind a rule that runs down a run of
  consecutive work lines, in muted text, its icon, its time and its buttons smaller. Its Open opens
  its session log ([`work.md`](work.md)), and it never offers Undo. A job an Undo withdrew reads
  "Withdrawn by an Undo" under its title.
- **A wait's line** has nothing behind it: no Open, and never Undo, Pilot's close being consumed on
  the spot ([`waits.md`](waits.md)). Under its title stands the note Pilot closed it with, as linked
  text; a wait Finish closed has none.
- **On a phone** a done line has Undo alone among its actions: no Open and no Discuss, its
  attachments' indicator staying. A tap on the line, anywhere but on a link, a button or a menu of
  its own, goes where Open goes, the document's address or the session log's, which opens it as a
  view whose head carries Discuss ([`projects.md`](projects.md)). A wait's line, with nothing behind
  it, opens instead the menu of its actions in a row under it, Discuss alone, which a tap elsewhere,
  Esc or a tap on the line again closes.

**Finished.** Finish closes every open item but the opening, so a finished project's timeline is its
opening and done lines, and ends in "Finished · <stamp>", "22 Oct 2026, 14:05". Under that divider
stands the archive question its latest finish put (`archive-question.tsx`;
[`projects.md`](projects.md)): open, its head "Question" with the archive box, "Archive the
project?", and two buttons, Archive, primary, and Keep, both disabled from a click until the answer
is read back; answered, its done line, the answer under its title. No line offers Undo while the
project is finished, a line answered before Finish included (D028); Reopen brings it back.

**Archived.** An archived project takes Bring back alone (D012), so its timeline reads as it was
left: every close of an open item stands disabled, not hidden, as a work item's Resume does
([`work.md`](work.md)): a decision's options, a question's field and Send, an action's
paste-back, Done, options and Other…, a confirmation's check and cross, a notice's Read, a
review's Reviewed, a document's *Send answers*, and in the overlay its foot's
([`documents.md`](documents.md)), each reading the head's `archived` (`useArchived`). No line
offers Undo while the project is archived; Bring back gives every close and Undo back.

## Addresses

An item's address is `/projects/<project>/items/<item>`, a block's
`/projects/<project>/items/<item>/blocks/<block>`, by their ids; off a phone the project's route
(`routes/_shell/projects/$projectId.tsx`) draws the timeline at them, and the two child routes
draw nothing of their own. Opened there, the timeline jumps to the middle of the item, the block or
a confirmation card's row, and flashes it. A block the timeline does not draw, as in a done item's
line or an id the item lacks, goes to its item; an item it does not draw leaves it at its end. Each
address is gone to once, when the timeline is read or when Back reopens it, and the jump stops the
timeline following its end. A block in a collapsed section opens its section first. A block's
address whose document is a card, done or open, also opens the document in the overlay at the
block; a document's own address, an attachment's, the handbook's and the project document's are
[`documents.md`](documents.md)'s.

**The item alone.** On a phone an item's address opens the item alone (`ItemOverlay`,
`components/overlay/item-overlay.tsx`), the whole screen, a view pushed over the tabs
([`projects.md`](projects.md)); a notification's link is such an address
([`notifications.md`](notifications.md)). Its head is the view's arrow back and the project's name
over the item's step; its body the item as the timeline draws it, open or as its done line, answered
in place as there, its option rows at least 48px high, a thumb's height. A block's address waits for
the timeline's read: where the block's document is a card it opens the document at the block, as at
every width, and otherwise the item alone, going to the block. An address naming no item, or a
read that fails, reads "The item did not load". The Timeline
tab under it is not gone to the item.

**On a narrow window.** At 900px and below an option's line goes under its label, Recommended
staying at the label's end. At 600px and below a block's head wraps, and Answered shows its icon
alone, as *In the chat* does, their words left to a screen reader. An item's head, at 600px and
below, sets its parts 6px apart, Urgent shows its triangle alone and *Edited* a pencil in place of
its word, Pilot's mark and the time staying, in the overlay's head too, the words again left to a
screen reader; a work item's env chip is its icon ([`work.md`](work.md)). At 390px a document's head
with Urgent, *Edited* and its count, and a work item's with its env chip, its running time and
Session log's and Stop's icons, each hold one line.

## Testing it

The engine's side is pinned in `backend/tests/engine/`, the read in
`tests/services/test_timeline_service.py` and `TestGetTimeline` (`tests/api/test_projects.py`), the
writes and the event in `tests/api/test_items.py`, `tests/services/test_item_service.py` and
`tests/services/test_project_event_service.py`. The browser suites are `frontend/tests/timeline/`,
with `tests/projects/badge.spec.ts`; `document.spec.ts`, `card.spec.ts` and `settled.spec.ts` pin
the documents, `phone-items.spec.ts` the item alone and a done line on a phone, and
`frontend/tests/work/timeline.spec.ts` the work items ([`work.md`](work.md)), and `waits.spec.ts` the
waits, open and done, and a wait's menu on a phone, through the `waits` fixture
([`waits.md`](waits.md)).

A spec makes its project with `projects.makeWithSession`, places items with `projects.place`, a
text written in the block DSL, and posts an agent's save with `projects.save`; `projects.answer`,
`markDone`, `send`, `reviewed`, `undo`, `timeline` and `block` drive the routes above, and `endTurn` and
`doneByPilot` end the session's turn and mark a document Done as Pilot ([`projects.md`](projects.md)
has the testing endpoints they call). A text with one block makes its item that block's kind, so a
spec's document carries two blocks or more. The `timeline` page object
(`tests/support/page-objects/timeline-page.ts`) opens a project's timeline (`open`), or an
address (`openAt`), and reads its items, blocks, segments, cards, settled lines, attachments,
the item alone's as the timeline's (`item(id, overlay.alone)`), banners and done lines, their
Discuss and *In the chat*, an item's head that says Pilot asked its writer
(`item(id).writerAsked`, pinned in `frontend/tests/work/registered.spec.ts`), a block's head that
says so, a claimed action's line and its work item's link, and the mark of Pilot's work that left
it undone (`writerAsked`, `claim`, `claimWork`, `undone`, pinned in
`tests/work/clarification.spec.ts` and `claimed.spec.ts`), Pilot's line and its button
(`item(id).pilots`, `data-doing` the API's `doing`), a held block's line (`held`), the auto pilot
marks and chip
(`autopilotMark`, `autopilotChip`, `tests/timeline/autopilot-mark.spec.ts`), the archive question's
buttons (`archiveQuestion`, `archive-question.spec.ts`), the ready line (`ready`) and a wait's
button, what it waits on, its firings, its note and its phone menu (`item(id).wait`); `slowNetwork`
(`tests/support/network.ts`) holds a write on its way, to see what shows while it saves. A spec
asserting a live update waits for the stream first (`deploymentSse.ensureConnected()`).
