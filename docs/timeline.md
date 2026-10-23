# The timeline

A project's timeline as a signed-in person reads and answers it: the read, the writes on its items,
the live event, and the screen under the project's head. The read is `GET
/api/projects/<id>/timeline` in `backend/app/api/projects.py` on `TimelineService`
(`backend/app/services/timeline_service.py`); the writes are `backend/app/api/items.py` on
`ItemService`, which calls the engine's `RecordService` ([`engine.md`](engine.md)); the screen is
`frontend/src/components/timeline/`. The texts are written in the block DSL
([`block-dsl.md`](block-dsl.md)), and the project's head and list are
[`projects.md`](projects.md)'s.

## Reading it

**`GET /api/projects/<id>/timeline`** answers the timeline whole, `{finished_at, items}`, and `404`
for an unknown project. `finished_at` is the latest `finished` transition's time while the project
is finished, else null. `items` are every item, by `seq`, each with:

- `id`, `seq`, `kind` (an item kind's code) and `form` (`prose`, `work` or `wait`);
- `title`, null for a registered document whose text gives none, and `file_name`, a registered
  document's file name from its source path, which its line shows while `title` is null;
- `created_at`; `step`, `{id, title}`, the plan task it serves with the task's title live from the
  plan (a removed task's last), or null; `urgent`; `for_user`, a person or null;
- `done`, null while open, else `{at, cause, by, undo}`: `by` is null when the server did it, and
  `undo` whether the record takes Undo now (`RecordService.offers_undo`);
- `concept`: whether a `parse` Save Error stands on its document's path, its latest save held, so
  that its text is the one last published (F78);
- the opening's `author` and its `words`, verbatim; null on every other item;
- `body`: every other prose item's text as drawn (`dsl.body`), its parts in order, `{type: prose,
  markdown}` and `{type: block, block}`, the front matter and the heading that is the title left
  out; null for the opening, work and waits.

A block is `{id, kind, confirmation, because, proposal, default, check, options, answer, by, at,
note, via, done, deferral}`. `id` is its local id; `because` is a confirmation's reason, `{code,
name, description}`, the grants table's name and the line the agent reads, not the card's words;
`options` are `{label, text, recommended}` in order; `via` is `app` for a person's answer whose text
names no channel; `deferral` is `{to, title}` while `answer` is `deferred`, `title` the task's title
live from the plan and null for `to: plan`, the project's end. A person or Pilot, wherever one is
named, is `{kind, handle, name, initials, avatar_slot}`, Pilot `kind: agent` with no slot.

## Answering it

Six routes under `/api/items/<item_id>`, each the record's own write, as the caller, now, through
the app, answering `204` with no body:

| Route | Body | Does |
|---|---|---|
| `POST blocks/<block_id>/answer` | `{answer, note?}` | a block's answer: an option's label, `Agree` to a proposal, `Yes` or `No` to a confirmation, or free words; the note, an action's paste-back or a No's reason |
| `POST blocks/<block_id>/done` | `{note?}` | Done on an action without options, the note what was pasted back |
| `POST done` | | Done on a document, with its recommendations |
| `POST read` | | Read on a notice |
| `POST reviewed` | | Reviewed on a review |
| `POST undo` | | Undo of a done item's answer or mark, whoever gave it |

An answer or a Done on a one-ask item is the item's done. Neither body takes `to` or `via`, and
neither takes another key (`400`): the page never defers. An unknown item answers `404` "Item <id>
was not found", and a block the item lacks, any block of a work item or of the opening, `404`
"Block <item>/<block> was not found". A caller who has not chosen a handle, and every refusal of the
record, answer `409` with the record's reason ([`engine.md`](engine.md)); Undo takes no person, so
it needs no handle. The routes are behind the API's sign-in and `editor` role
([`sign-in.md`](sign-in.md)).

## Live

Once a change to what a project's timeline, head or tab shows commits, the engine's
`ProjectChanged` ([`engine.md`](engine.md)) goes to every person's connections as the SSE event
`project_changed`, `{"project_id": "<id>"}`, the writer's own browser included
(`ProjectEventService`, `backend/app/services/project_event_service.py`). A person is a user with a
handle, so a connection whose user has none hears nothing. Only the process that holds a connection
delivers to it.

`useProjectEvents` (`frontend/src/hooks/use-project-events.ts`), called by the shell, reads again,
on the event, the project lists and the named project's head and timeline, events that arrive
together once after them; and on every rise of the stream's `isConnected`, the first included,
every list, head and timeline, which covers an event sent from a process that does not hold the
browser's stream. A person's own write reads every query again as well.

## The timeline

`Timeline` (`timeline.tsx`) draws under the project's head, from `useTimeline`
(`hooks/use-timeline.ts`). It draws the prose items in their order, the opening first; work items
and waits draw no line. A project with none reads "Nothing yet".

- **Dividers** (`rows.ts`). A day divider falls at each new date in the browser's time zone,
  "Thursday 22 October"; a step divider where the step changes, the task's title. An item serving
  no step starts no divider and ends no step.
- **Anchored to its end.** It opens at its end and stays there as items arrive or its height
  changes, until the reader scrolls more than 48px away from it. An item that arrives after the
  first read flashes once.
- **The opening** (`opening.tsx`) is a bubble beside its author's avatar, "<who> started this
  project · <time>" over it, "You" for the signed-in person and the full name for the other; its
  words verbatim, folding with Show more. It has no head and is never done.
- **An open item** (`item.tsx`) is its head, its title (`title`, else `file_name`) and its text.
  The head (`item-head.tsx`) is the kind's icon and label (`kinds.ts`; a confirmation's is
  "Confirm", a document's "Document · N" with its most common block's icon), the time, the full
  stamp as its tooltip, the Urgent chip and "for <full name>" while it is for someone. The text's
  prose is GFM (`Markdown`, [`ui.md`](ui.md)); the prose before the first block folds past 13.5em
  with Show more, the ask stands in that block's place, and the prose after it shows whole. A
  concept has a dashed border.
- **Urgent.** An open urgent item is tinted, its kind's label in the urgent colour. Each has a
  banner pinned at the top of the timeline, in their order, "Urgent · <title> · Show", whose click
  scrolls the item to the middle and flashes it; a finished project's timeline pins none.
- **"N open above"**, a chip under the banners, counts the open items whose end is scrolled out
  above them, the other person's included, never a done line or the opening; its click scrolls the
  nearest of them to the top.

A document or a review draws its prose and none of its blocks.

## Answering inline

A one-ask item's block (`block.tsx`) is answered in its place; each click or Send posts through
`useAnswer` (`hooks/use-answer.ts`), and the item becomes its done line once the screens read it
back.

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
  words.
- **A confirmation** (`confirmation.tsx`) is a card: its head with the reason line, plain words by
  the reason's code with the ground as its tooltip ("Auto pilot off", "Always asks: cannot be
  undone", and so on; a code without words of its own shows `because.name`); the title and the
  proposal beside the check, Yes, and the cross, No, which opens a console for the reason that
  sends empty too, "Send No"; and Details, which unfolds the prose, and Less.
- **A notice** has Read.

A console (`console.tsx`) is the growing text field with Send and a cross, Cancel, inside its
border; Ctrl+Enter (Cmd+Enter on a Mac) sends it and Esc closes it, and its Send is disabled while
it is blank, a No's excepted. Its words, and every field's here, are kept in the browser until sent
([`ui.md`](ui.md)).

**An answered block on an open item**, Pilot's answer or a deferral, has a head: its kind, a
chevron, Answered, the time and the avatar of who answered, Pilot's mark for Pilot. An answer that
is not a person's reads closed, the answer alone, and opens, on a click or the chevron, to the
block's controls, live, so that the person can replace it. A deferral reads "Deferred to <task>",
or to *the project's end*, with its note; opened, the controls stand under that line with nothing
chosen. A note stands under its answer with the note icon.

## Done lines and Undo

A done item is one line that does not expand: its kind's icon, or a confirmation's green check for
Yes and red cross for No; its title; Undo while `done.undo`; and the time it was done. Under the
title stands a person's answer to a one-ask item, the other person's after their avatar, its note
after " · " with the note icon: an option, the words, or "Deferred to <task>"; a confirmation's Yes
or No shows only its note, and nothing of Pilot's shows. Undo ("Undo, until a session has taken
it") opens the item again, and a one-ask item's block unanswered.

**Finished.** Finish closes every open item but the opening, so a finished project's timeline is its
opening and done lines, and ends in "Finished · <stamp>", "22 Oct 2026, 14:05". No line offers
Undo while the project is finished, a line answered before Finish included (D028); Reopen brings it
back.

## Addresses

An item's address is `/projects/<project>/items/<item>`, a block's
`/projects/<project>/items/<item>/blocks/<block>`, by their ids; the project's route
(`routes/_shell/projects/$projectId.tsx`) draws the timeline at them, and the two child routes
draw nothing of their own. Opened there, the timeline jumps to the middle of the item, the block or
a confirmation card's row, and flashes it. A block the timeline does not draw, as in a done item's
line or an id the item lacks, goes to its item; an item it does not draw leaves it at its end. Each
address is gone to once, when the timeline is read or when Back reopens it, and the jump stops the
timeline following its end.

**On a narrow window.** At 900px and below an option's line goes under its label, Recommended
staying at the label's end. At 600px and below a block's head wraps, and Answered shows its icon
alone, its word left to a screen reader.

## Testing it

The engine's side is pinned in `backend/tests/engine/`, the read in
`tests/services/test_timeline_service.py` and `TestGetTimeline` (`tests/api/test_projects.py`), the
writes and the event in `tests/api/test_items.py`, `tests/services/test_item_service.py` and
`tests/services/test_project_event_service.py`. The browser suites are `frontend/tests/timeline/`,
with `tests/projects/badge.spec.ts`.

A spec makes its project with `projects.makeWithSession`, places items with `projects.place`, a
text written in the block DSL, and posts an agent's save with `projects.save`; `projects.answer`,
`markDone`, `undo`, `timeline` and `block` drive the routes above ([`projects.md`](projects.md) has
the testing endpoints they call). The `timeline` page object
(`tests/support/page-objects/timeline-page.ts`) opens a project's timeline (`open`), or an
address (`openAt`), and reads its items, blocks, banners and done lines; `slowNetwork`
(`tests/support/network.ts`) holds a write on its way, to see what shows while it saves. A spec
asserting a live update waits for the stream first (`deploymentSse.ensureConnected()`).
