# Projects

A project as a signed-in person reads and changes it: the project list, a project's head, its
transitions and its members. The API is `backend/app/api/projects.py` on `ProjectService`
(`backend/app/services/project_service.py`), the screens are `frontend/src/components/projects/`,
the tables are [`record.md`](record.md)'s, and the frame the screens sit in is [`ui.md`](ui.md). The
timeline under a project's head, and its items, are [`timeline.md`](timeline.md)'s; the overlay over
it and the side panel beside it, with the project's handbook and project document, are
[`documents.md`](documents.md)'s.

Nothing in the app creates a project yet: the dev seed and the record's testing endpoints (below)
make them. In production the list is empty, and the centre reads "No projects yet"; the dev stage's
holds what the slices' deployed checks made there.

## Reading them

- **`GET /api/projects`** answers `{projects: [tab]}`, the unarchived projects in the order they
  were created (`Project.number`); with `?archived=true`, the archived ones, in the same shape. A
  tab is `{id, name, ticket, state, finished_at, status, member, progress, badge}`. `name` is null
  for a draft without a title. `finished_at` is the latest `finished` transition's time, null unless
  the project is finished. `status` is below. `member` is whether the caller has an open membership,
  false before they have a handle. `progress` is `{done, total, in_progress}` over the plan's steps,
  removed steps not counted, `in_progress` the titles of the steps in progress in the plan's order.
  `badge` is `{count, urgent}`: `count` the project's open items waiting on the caller, which are
  its prose items but the opening, a notice only while it is urgent, and a work item whose session
  stopped or failed, never a wait and never an item for another person (before the caller
  has a handle, every item for someone is another's); `urgent` whether one of them is urgent.
- **`GET /api/projects/<id>`** answers the project's head: `{id, name, ticket, repo, state,
  archived, autopilot, status, member, members, progress, tasks, notes, running_work, open_items}`.
  A member is `{handle, name, initials, avatar_slot}`, in the order they joined; a task is a step,
  `{id, title, status, notes}`, with its open notes; `notes` are the plan's own; a note is `{id,
  summary, content}`. `running_work` is `[{id, title}]`, in timeline order, the work items whose
  session runs, starts or is held, which Finish and Archive stop. `open_items` counts the
  project's open items but the opening, which is never done (D016), and those, which Finish closes
  unanswered. An archived project reads as it was left. An unknown id answers `404`.

**The status** (`project_status()` in `project_service.py`) is one for every viewer, derived on
each read and never stored: `paused`, or `pausing` while a Session of the project, a Chat's too, is
`running`; else `running` while a work item or a job is `running`; `waiting_on_you` while an open
item waits on a member, the badge's set (for nobody while the project has a member, or for a
member); `waiting_on_event` while a wait is open; `done` while every step of a plan with steps is
done; `idle` otherwise. A draft and a finished project have none; an archived open one has its
status as it stands. A work item held or starting is not running.

## Changing them

**`POST /api/projects/<id>/transitions`** `{kind}` makes a transition as the caller, now, and
answers `201` with the head as it then stands. A transition is a `project_transitions` row, and the
project's cache it changes (`state_code`, `archived`, `autopilot` or `paused`) is written with it:

| `kind` | Allowed on | Also |
|---|---|---|
| `finished` | an open project | every session of the project running, starting or held stopped, as Stop stops one ([`sessions.md`](sessions.md)); while auto pilot is on, `autopilot_off`, and while it is paused, `resumed`, each at the same instant, by the same person; then every open item but the opening closed unanswered |
| `reopened` | a finished project | auto pilot stays off and the project is not paused: a finished project's never are |
| `archived` | a draft, an open or a finished project | every session of the project running, starting or held stopped; auto pilot and the pause are kept, so Bring back returns the project as it was |
| `brought_back` | an archived project | |
| `autopilot_on` | an open project with auto pilot off | |
| `autopilot_off` | a project with auto pilot on | |
| `paused` | an open project that is not paused | every start in it but a Chat's held at the gate ([`sessions.md`](sessions.md)); a running turn runs out |
| `resumed` | a paused project | once it commits, the gate opens for its held starts |

An archived project takes `brought_back` alone. Any other `kind`, `opened` included, is a `400`.
A transition that the project's standing does not allow is a `409`, and so is any write by a caller
who has not chosen a handle ([`sign-in.md`](sign-in.md)). The refusal's reason is the error
envelope's `error`, worded to be shown: "Cannot finish Recipe box because it is a draft", "Cannot
pause Recipe box because it is paused already". An unknown project is a `404`.

Finish's close is the engine's `RecordService.close_unanswered` ([`engine.md`](engine.md)): each
open item but the opening is marked done at the transition's instant, by the person who finished,
with the done cause `finished`, which offers no undo; the project's sessions are stopped before
it. Nothing of the project but a Chat's session starts once it is finished or archived.

**`POST /api/projects/<id>/membership`** joins the project as the caller (`201`), and **`DELETE`**
on the same path leaves it (`200`), each answering the head. Joining opens a `project_members`
row, so a rejoin is a new row; leaving closes the open one (`left_at`). Each is refused with `409`
on an archived project, to a caller without a handle, to a member joining and to someone who is
not a member leaving. A project may be left with no members. Pilot is never a member: the caller
is found by the token's subject, and Pilot's row has none.

The `editor` role is the whole of the check: anyone who holds it changes any project. Every change
holds the project's row first (`FOR NO KEY UPDATE`), so two changes of one project never
interleave. A transition emits a `TreeHashMoved` of the project's `timeline.json`, which shows its
state, `archived` and `autopilot` ([`projection.md`](projection.md)); a pause and a resume, which
the store's tree does not show, emit `ProjectChanged` alone, and so do a join and a leave, which
move no file. A transition that moves the pause, Finish's resume among them, moves the reason on
the project's held work items' lines ([`work.md`](work.md)).
Archive and Bring back emit `ManifestChanged` too: the project's folder leaves the store's tree, or
comes back to it as the record renders it, once the transition commits ([`sync.md`](sync.md)).

## The project list

The side column (`project-column.tsx`). Its head reads "Projects", with the overflow menu ("More")
at its right, which holds *Archived*.

- **The groups.** The person's projects, the unfinished ones they are a member of, stand under the
  head with no group row; *Other projects* holds the unfinished rest, and *Finished* every finished
  project, member or not. A group with no project is not drawn. *Other projects* and *Finished*
  open and close on their chevrons and show their counts. The browser remembers each chevron as
  last set, closed by default. A group also stands open while the project on screen is in it,
  until the person closes it.
- **A tab** (`project-tab.tsx`) is a link to the project: its name ("New project" for a draft
  without a title), its ticket, and its status line: "Draft"; "Finished" and the day it finished;
  else the step reading, which is the first step in progress (", …" after it while more are in
  progress), or "Not started", "N of M done" or "All steps done". `stepReading()` in
  `frontend/src/lib/utils/status-labels.ts` is that reading for the tab and the head's step button
  alike. While `badge.count` is above 0, the status line ends in it, "N waiting on you" as its
  tooltip, orange while `badge.urgent`; a finished tab's too.
- **The status icon** (`status-icon.tsx`) stands before the status line, where the project has a
  `status`, its label in its tooltip: running, a filled dot, green and pulsing; waiting on you, a
  person; waiting on an event, an hourglass; done, a check in a circle; idle, a dashed circle;
  pausing and paused, the pause glyph, pausing pulsing. It is the pause: a click, a tap, Enter or
  Space pauses a project that is not paused, the pause glyph showing under the pointer and the
  focus, and resumes one paused or pausing, the play glyph showing there, at once, with no dialog,
  and without opening the project. While the write is pending the icon shows the glyph it asked
  for, and the write reads every query again, as the switch's does. The tab being a link, the icon
  is a `span role="button"`. On an archived project it is the status alone, since the record
  refuses its pause and its resume.
- **Archived** switches the column to the archived projects (D012): their tabs, flat, in the API's
  order, or "None yet", under a back arrow ("Back to the projects") that returns to the list. Which
  view shows is the column's own state, and the browser does not remember it.

A project has its own address, `/projects/<id>`, by its id. The bare address opens the project the
browser remembers while that project is in the list, else the list's first in the order shown; with
no project the centre reads "No projects yet" and the address stays `/`. Under it are an item's
address and a block's ([`timeline.md`](timeline.md)), and a document's, an attachment's, the
handbook's and the project document's ([`documents.md`](documents.md)), at which the project's tab
is current too. The project's route remounts on each project, so whatever it opened (the plan, the
notes, the menu, a dialog, the overlay) is closed on the next one, while the side panel comes back
as that project left it; the drawer closes on any change of address ([`ui.md`](ui.md)).

The list and the head are read again when the window regains focus, after each of the person's
own writes, which invalidate every query, on the server's `project_changed` event, and whenever the
event stream comes up ([`timeline.md`](timeline.md)).

## The head

`project-head.tsx` draws the head in two rows: the name, its chip and the ticket and the repo, then
the auto pilot switch; below them the step button, the members, the Documents button, the
handbook's, the plan's notes button and the project's menu. On a wide window the two rows share one
line. Under the narrow window's breakpoint they are a row each and the repo is hidden. In a tight
head the repo and the step's name give way first, then the name, cut with an ellipsis; the chips,
auto pilot, the members and the icons keep their size.

- **The chips.** A draft shows "Draft", its name and members, and no switch, step, Documents,
  handbook or notes button.
  A finished project shows the "Finished" chip in place of the switch. An archived project shows
  "Archived" after its name and the rest as it was left, the switch disabled.
- **The warning triangle** stands after the switch while a work item runs, starts or is held whose
  start was briefed under the switch's other setting (`work.autopilot`, as the timeline reads it),
  its tooltip "The change applies to work started from now on: a running session keeps the grants
  it was briefed with".
- **The step button** shows the plan as a donut of its steps, done and in progress, and the step
  reading; its tooltip is "N of M steps done", then " · in progress: a; b" while any step is. It
  opens the plan popover: "The plan · N of M done" ("The plan" alone with no steps), the steps in
  order, a done one ticked and one in progress highlighted. A step with open notes has a
  sticky-note icon; its notes list under the step while the mouse is on the icon, or after a tap
  or a click on it until the next.
- **The plan's notes button** shows while the plan has open notes of its own, and opens "The plan's
  notes", each note its summary and then its content.
- **The members** are small avatars, overlapping by 2px, in the order they joined, in a group named
  "Members".
- **The Documents button**, pressed while the side panel shows its Documents tab, opens that tab or
  closes it; **the handbook's** opens the handbook in the overlay ([`documents.md`](documents.md)).

The popovers and the menu close on a press outside them and on Esc.

## The project's menu

`project-menu.tsx`, last in the head's second row. On an unarchived project, a draft included:
"Join the project" or "Leave the project"; "Finish the project…" on an open project, "Reopen the
project" on a finished one; and "Archive the project". On an archived project, "Bring back" alone.

Join and Leave act at once, each with a toast: "You joined <name>." and "You left <name>. It moves
to Other projects.", on a finished project "You left <name>." alone, since it stays under Finished.

Finish asks first, in a modal dialog, and Archive, Reopen and Bring back ask in one shaped as
Finish's (D010): the title "<Act> <name>?", the lines of what it does, a note, and Cancel beside the
act's button. Esc cancels. While
the write is pending, Esc, Cancel and a click beside the dialog do nothing; a refusal shows as a
toast and the dialog stays open. A confirmed dialog closes once the list and the head show the new
standing, and no toast follows it.

| Act | Lines | Note | Button |
|---|---|---|---|
| Finish | the running sessions' line (below); "N open items close unanswered." (only while there are any); "Pilot starts nothing more, and auto pilot’s permissions end with the project." | "The timeline and the chat stay, and the project can be reopened." | Finish project |
| Reopen | "Pilot takes the plan up where it stood."; "Auto pilot stays off until you turn it on." | | Reopen project |
| Archive | the running sessions' line; "It leaves the project list for Archived, in the menu beside the list’s head." | "Nothing is deleted: Bring back returns it where it was." | Archive project |
| Bring back | "It returns to the project list, where it was." | | Bring back |

The running sessions' line names the head's `running_work`, only while there is any: "The running
session stops: <title>." or "<N> running sessions stop: A, B and C.". No dialog line and no toast
names the notifications (D011).

## Testing it

The testing endpoints make what the UI cannot. The record's own,
`backend/app/api/testing_record.py`, sit on the API blueprint, behind its sign-in and the `editor`
role as every route is, and answer on every `STAGE` but `prd`, whatever `FLASK_ENV` says (D027), so
that the dev stage's deployed check makes its invented record through them. On `prd`, which an unset
`STAGE` resolves to outside testing and development, each answers `400` "The record's testing
endpoints are not available on prd". Every other testing endpoint, the test sign-in among them,
answers only in testing mode ([`sign-in.md`](sign-in.md)).

- `POST /api/testing/people` `{handle, name?}` puts a person on the record as the handle step does,
  under a subject no one signs in with, and answers `201` `{handle, name, avatar_slot}`; it refuses
  what the handle step refuses.
- `POST /api/testing/environments` `{id, name}` puts an environment on the record (`409` for a taken
  id).
- `POST /api/testing/projects` makes a project in the standing given and answers `201` `{id}`:
  `name`, `state` (`draft`, `open` or `finished`, `open` by default), `archived`, `autopilot`,
  `paused`, `members` (handles, at least one, the first the creator, joining in that order),
  `ticket`, `repo`, `tasks`, `notes`, `environment_id`, `open_items` and `opening`. The transitions
  to that standing are made at one instant by the first member, and the plan is saved through the
  engine. A project past the draft is born with its opening first: the first member's words,
  `opening` (by default "An invented project, started for a test."), verbatim, titled by its name or
  "New project", and with its handbook, empty; its project document is `# <name>`. With an
  `environment_id`, an idle work session of the project there adds `open_items` open notices. A
  finished project with auto pilot on, a paused project that is not open, a member named twice, open
  items without an environment and a plan with a fault are each a `400`; a handle that is no
  person's, `agent` included, and an unknown environment a `404`.
- `POST /api/testing/projects/<id>/work` `{environment_id, title, brief, cwd, step?}` places a work
  item in an environment of the stage's own controller and starts its session through the gate, as
  every work item's starts ([`sessions.md`](sessions.md)), and answers `201` `{id}`, the item's,
  its Work's and its Session's; the start runs once the request commits. `step` is the id of a plan
  task it serves. An unknown project or a step not in the plan is a `404`; no controller
  configured, or a finished or an archived project, a `409`; an environment the controller lacks,
  or a controller that failed, a `502`. A work item is created by its own Session, so once one has
  started, the routes below that act by the project's session started last act by it.
- `POST /api/testing/projects/<id>/items` `{kind, title, text}` adds a prose item as Pilot adds one,
  born through the engine's `bear_item` by the project's session started last, and answers `201`
  `{id}`. `kind` is a prose kind but the opening; the text, front matter and blocks included, says
  the rest ([`block-dsl.md`](block-dsl.md)). A project with no session, or a text with a fault, is a
  `409`.
- `POST /api/testing/items/<id>/saves` `{text}` ingests an agent's save of the item's file by that
  session, on the tree's current hash, as the store's sync does, and answers `200` `{held, faults:
  [{line, message}]}`. A held save leaves the item a concept until a clean one.
- `POST /api/testing/projects/<id>/draft/saves` and `…/handbook/saves` `{text}` ingest a save of the
  project document or the handbook by the project's session, as an item's does, with the same
  answer. An unknown or archived project, and a draft's handbook, are a `404`; a project with no
  session a `409`.
- `POST /api/testing/projects/<id>/turn-ends`, no body, ends the turn of the project's session
  started last as the relay does ([`engine.md`](engine.md)), and answers `204`: Pilot's writing
  flag cleared on every document the session was saving, and a `turn` Version cut of each whose text
  moved. No live event follows. An unknown project is a `404`, one with no session a `409`.
- `POST /api/testing/items/<id>/done`, no body, marks a document Done as Pilot does one it settled
  or deferred whole, by the project's session, and answers `204`: cause `settled`, a `done` Version
  cut. An unknown item is a `404`; a project with no session, an item that is no document or is
  done, and a block unanswered a `409`.
- `POST /api/testing/items/<id>/attachments` `{files: [{title, filename, content_type, content}]}`,
  `content` base64, hangs the files on the item as the project's session attaches them in one call,
  and answers `201` `{batch, ids}`, the ids in the files' order: one batch, the project's next,
  after the item's own attachments, each copied from `<session's folder>/<filename>` and kept
  through the store ([`documents.md`](documents.md)). No file, a filename that is not one path
  segment (empty, `.`, `..`, or holding a slash or NUL) or is named twice, content that is not
  base64, and a file over 16 MiB are a `400`; an unknown item a `404`; a project with no session a
  `409`.

A project past the draft, born with its opening, an item placed, a work item placed, an item's save
posted, Pilot's Done and attachments hung each raise `project_changed` through the engine, so an
open screen follows them ([`timeline.md`](timeline.md)); a turn's end raises none, and a save of the
handbook none either. The frontend suite's `projects` fixture (`frontend/tests/support/projects.ts`)
wraps them (`make`, `makeWithSession`, `place`, `save`, `saveProjectDocument`, `endTurn`,
`doneByPilot`, `attach`, `list`, `head`, `transition`, the item writes of
[`timeline.md`](timeline.md), and the work item's of [`work.md`](work.md)), and the page objects
`projectList` and `projectHead` drive the screens: `projectList.statusIcon(name)` reads a tab's
icon, its status and its glyphs, and `projectList.written(id, kind)` waits for its pause or resume
to be written; `projectHead.autopilotWarning` is the triangle. The status and the pause are pinned
in `tests/projects/project-status.spec.ts`. Each Playwright worker's database is a
clone of the dev seed ([`record.md`](record.md)), so every spec's list holds the seed's projects
beside its own.
