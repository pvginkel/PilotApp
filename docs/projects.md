# Projects

A project as a signed-in person reads and changes it: the project list, a project's head, its
transitions and its members. The API is `backend/app/api/projects.py` on `ProjectService`
(`backend/app/services/project_service.py`), the screens are `frontend/src/components/projects/`,
the tables are [`record.md`](record.md)'s, and the frame the screens sit in is [`ui.md`](ui.md).

Nothing in the app creates a project yet: the dev seed and the suites' testing endpoints (below)
make them. In production the list is empty, and the centre reads "No projects yet".

## Reading them

- **`GET /api/projects`** answers `{projects: [tab]}`, the unarchived projects in the order they
  were created (`Project.number`); with `?archived=true`, the archived ones, in the same shape. A
  tab is `{id, name, ticket, state, finished_at, member, progress}`. `name` is null for a draft
  without a title. `finished_at` is the latest `finished` transition's time, null unless the
  project is finished. `member` is whether the caller has an open membership, false before they
  have a handle. `progress` is `{done, total, in_progress}` over the plan's steps, removed steps
  not counted, `in_progress` the titles of the steps in progress in the plan's order.
- **`GET /api/projects/<id>`** answers the project's head: `{id, name, ticket, repo, state,
  archived, autopilot, member, members, progress, tasks, notes, open_items}`. A member is `{handle,
  name, initials, avatar_slot}`, in the order they joined; a task is a step, `{id, title, status,
  notes}`, with its open notes; `notes` are the plan's own; a note is `{id, summary, content}`.
  `open_items` counts the project's open items but the opening, which is never done. An archived
  project reads as it was left. An unknown id answers `404`.

## Changing them

**`POST /api/projects/<id>/transitions`** `{kind}` makes a transition as the caller, now, and
answers `201` with the head as it then stands. A transition is a `project_transitions` row, and the
project's cache it changes (`state_code`, `archived` or `autopilot`) is written with it:

| `kind` | Allowed on | Also |
|---|---|---|
| `finished` | an open project | while auto pilot is on, `autopilot_off` at the same instant, by the same person; every open item but the opening closed unanswered |
| `reopened` | a finished project | auto pilot stays off: a finished project's always is |
| `archived` | a draft, an open or a finished project | auto pilot is kept, so Bring back returns the project as it was |
| `brought_back` | an archived project | |
| `autopilot_on` | an open project with auto pilot off | |
| `autopilot_off` | a project with auto pilot on | |

An archived project takes `brought_back` alone. Any other `kind`, `opened` included, is a `400`.
A transition that the project's standing does not allow is a `409`, and so is any write by a caller
who has not chosen a handle ([`sign-in.md`](sign-in.md)). The refusal's reason is the error
envelope's `error`, worded to be shown: "Cannot finish Recipe box because it is a draft". An
unknown project is a `404`.

Finish's close is the engine's `RecordService.close_unanswered` ([`engine.md`](engine.md)): each
open item but the opening is marked done at the transition's instant, by the person who finished,
with the done cause `finished`, which offers no undo.

**`POST /api/projects/<id>/membership`** joins the project as the caller (`201`), and **`DELETE`**
on the same path leaves it (`200`), each answering the head. Joining opens a `project_members`
row, so a rejoin is a new row; leaving closes the open one (`left_at`). Each is refused with `409`
on an archived project, to a caller without a handle, to a member joining and to someone who is
not a member leaving. A project may be left with no members. Pilot is never a member: the caller
is found by the token's subject, and Pilot's row has none.

The `editor` role is the whole of the check: anyone who holds it changes any project. Every change
holds the project's row first (`FOR NO KEY UPDATE`), so two changes of one project never
interleave. A transition emits a `TreeHashMoved` of the project's `timeline.json`, which shows its
state, `archived` and `autopilot` ([`projection.md`](projection.md)); a membership moves no file.

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
  alike.
- **Archived** switches the column to the archived projects (D012): their tabs, flat, in the API's
  order, or "None yet", under a back arrow ("Back to the projects") that returns to the list. Which
  view shows is the column's own state, and the browser does not remember it.

A project has its own address, `/projects/<id>`, by its id. The bare address opens the project
the browser remembers while that project is in the list, else the list's first in the order shown;
with no project the centre reads "No projects yet" and the address stays `/`. The project's route
remounts on each project, so whatever it opened (the plan, the notes, the menu, a dialog) is closed
on the next one; the drawer closes on any change of address ([`ui.md`](ui.md)).

The list and the head are read again when the window regains focus and after each of the person's
own writes, which invalidate every query. Nothing pushes them.

## The head

`project-head.tsx` draws the head in two rows: the name, its chip and the ticket and the repo, then
the auto pilot switch; below them the step button, the members, the plan's notes button and the
project's menu. On a wide window the two rows share one line. Under the narrow window's breakpoint
they are a row each and the repo is hidden.

- **The chips.** A draft shows "Draft", its name and members, and no switch, step or notes button.
  A finished project shows the "Finished" chip in place of the switch. An archived project shows
  "Archived" after its name and the rest as it was left, the switch disabled.
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
| Finish | "N open items close unanswered." (only while there are any); "Pilot starts nothing more, and auto pilot’s permissions end with the project." | "The timeline and the chat stay, and the project can be reopened." | Finish project |
| Reopen | "Pilot takes the plan up where it stood."; "Auto pilot stays off until you turn it on." | | Reopen project |
| Archive | "It leaves the project list for Archived, in the menu beside the list’s head." | "Nothing is deleted: Bring back returns it where it was." | Archive project |
| Bring back | "It returns to the project list, where it was." | | Bring back |

No dialog line and no toast names the notifications (D011).

## Testing it

The testing endpoints make what the UI cannot. They answer only under `FLASK_ENV=testing`, on a
stage other than `prd`, and need no sign-in:

- `POST /api/testing/people` `{handle, name?}` puts a person on the record as the handle step does,
  under a subject no one signs in with, and answers `201` `{handle, name, avatar_slot}`; it refuses
  what the handle step refuses.
- `POST /api/testing/environments` `{id, name}` puts an environment on the record (`409` for a taken
  id).
- `POST /api/testing/projects` makes a project in the standing given and answers `201` `{id}`:
  `name`, `state` (`draft`, `open` or `finished`, `open` by default), `archived`, `autopilot`,
  `members` (handles, at least one, the first the creator, joining in that order), `ticket`, `repo`,
  `tasks`, `notes`, and `open_items` (open notices a session in `environment_id` added). The
  transitions to that standing are made at one instant by the first member, and the plan is saved
  through the engine. A finished project with auto pilot on, a member named twice, open items
  without an environment and a plan with a fault are each a `400`; a handle that is no person's,
  `agent` included, and an unknown environment a `404`.

The frontend suite's `projects` fixture (`frontend/tests/support/projects.ts`) wraps them
(`make`, `list`, `head`, `transition`), and the page objects `projectList` and `projectHead` drive
the screens. Each Playwright worker's database is a clone of the dev seed
([`record.md`](record.md)), so every spec's list holds the seed's projects beside its own.
