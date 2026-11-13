# The store's tree

The store environment holds a tree of files, one folder per project, which the brain and its
sessions read and write. The record renders it, the engine takes the agent's saves of it back
into the record ([`engine.md`](engine.md)), and `pilot-sync`, the store's sidecar, keeps the files
on disk in step with the record ([`sync.md`](sync.md)). This page is the tree as built
(`backend/app/engine/paths.py`, `tree.py`, `views.py` and `plan.py`): what each path holds, and the
shapes of its three JSON files, which the brain's skills and its script, `pilot.py`, are written
against. Tests pin each shape (`TestViewService` in `backend/tests/engine/test_views.py`,
`TestPlanServiceRender` in `test_plan.py`), so a change to one is a visible diff.

## The paths

At the tree's root are `reference.json` and a folder per project that is not archived:
`draft-<number>` while the project is a draft, its slug once Create project gives it one, which
moves the folder ([`projects.md`](projects.md)). In a project's folder:

| Path | Holds | A save of it |
|---|---|---|
| `project.md` | the draft, and past Create the project document | is ingested, past Create under the handbook's rules |
| `handbook.md` | the handbook, born at Create | is ingested |
| `items/<seq>-<slug>.md` | a prose item's document | is ingested; the opening's is reverted whole |
| `inbox/<seq>-<slug>.md` | a worker's registered document, once its file was read | is ingested |
| `plan.json` | the plan, rendered from its rows | is parsed back into the rows |
| `timeline.json` | the timeline, rendered from the rows | stores nothing |
| `chat.md` | the project's chats, rendered from their records ([`chats.md`](chats.md)) | stores nothing |
| `attachments/<batch>/<filename>` | an attachment's copy, its `filename` holding slashes where it came in a folder | stores nothing |

`reference.json` is read-only too. A save that stores nothing is answered with the file as the
record renders it. Any other path, a stray file, a folder no project has or an archived project's,
is not the record's: the engine refuses a save of it.

An item's file name is fixed when it is born: its `seq`, then the title it was added with as a
slug, its letters and digits made ASCII and lower-case and joined by hyphens, cut at a hyphen to at
most 60 characters. With nothing left of the title it is `items/<seq>.md`. A registered document's
is `inbox/<seq>-<slug>.md` the same way, from its file's name without its extension, and stands in
the tree only once it has a text: one awaiting its read, or whose read failed, has no file there.

## Hashes

A hash is the sha256 of a file's bytes, in hex. A path's tree hash, the hash of what the tree must
hold, is:

- for a document, its published hash, or its ingested hash while the path's latest save is held,
  so that the agent's file is left as the agent wrote it while the faults stand;
- for a rendered file, the hash of its rendering;
- for an attachment, its `sha256`.

`TreeService.read(path)` gives the bytes a path must hold with their tree hash,
`TreeService.hashes(project)` every path of a folder with its tree hash, and
`TreeService.manifest()` every path the store syncs: `reference.json` and every path of every
project that is not archived, each with its tree hash and whether it is read-only.
`TreeService.paths()` lists the same paths in path order without their hashes, so that no view is
rendered to list them.

## Read by path

The routes behind `pilot-projects`' file tools ([`mcp.md`](mcp.md#the-projects-surface)) read the
tree as the record renders it, never the store's disk, so they answer whether the store runs or not
(`backend/app/api/tree.py` on `TreeReadService`, `backend/app/services/tree_read_service.py`). They
sit on the API blueprint behind its sign-in, answer a list whole, and no screen reads them. A path
runs from the tree's root, the empty path the root itself, its `.` segments dropped and each `..`
taken; the tree is `reference.json` and the paths of every project that is not archived, so an
archived project's files are not listed, found or read, and a folder is one a file's path runs
through. A refusal's reason ends with the name KubeCoder's fleet adapter gives it, in brackets.

- **`GET /api/tree/entries?path=`** answers `{entries: [{path, is_directory}]}`, what the folder at
  the path holds, folders first and then files, each group in case-insensitive name order, every
  path from the root and a folder's ending with `/`. A file's path is a `409` `[not-a-directory]`,
  and a path nothing is at a `404`, "Folder '<path>' was not found".
- **`GET /api/tree/matches?pattern=`** answers `{paths}`, the files whose path matches the glob, in
  path order (`PathGlob`, `backend/app/utils/path_glob.py`, KubeCoder's ported): `*` any characters
  but `/`, `**` any path segments, `?` one character, `{a,b}` either alternative, with no nesting.
  Any other glob syntax is a `400` `[validation-error]` naming it.
- **`GET /api/tree/text?path=&start_line=&end_line=&tail_lines=`** answers `{content, sha256,
  total_count, limit_hit, line_cut}`: the file's lines, each `<number>: <line>`, `sha256` the hash
  of the whole file's bytes and `total_count` its lines. Read whole, a file over 128 KB is a `409`
  `[file-too-large]` giving its size and line count; a line range, 1-based and inclusive, or a tail,
  the last lines, reads a file of any size, and is cut at 2,000 lines and 128 KB of content, a range
  keeping its start and a tail the file's end, `limit_hit` then true. A line over 128 KB on its own
  comes back cut, the answer's only line, with `line_cut` true. A folder is a `409` `[not-a-file]`,
  a file that is not UTF-8 text, as an attachment may be, a `409` `[not-text]`, a tail with a range
  a `400`, and a path nothing is at a `404`, "File '<path>' was not found".

A path or a pattern that starts with `/`, or a path that climbs above the root, is a `400`
`[path-outside-projects]`. The index of a project's items, `timeline.json`'s `items` as rendered,
is read by address ([`projects.md`](projects.md)).

## The JSON files

Each is written with a two-space indent, non-ASCII characters as they are, and a final newline;
every time in them is UTC to the second (`2026-10-12T09:40:00Z`). `reference.json` and
`timeline.json` open with the key `readonly`, whose value is "a projection of the record; an edit
is reverted — the timeline is edited through the tools".

### `reference.json`

The values the agent writes from a closed list:

- `confirmation_reasons`, by code: `code`, `name`, `description`, `asks_under_autopilot`;
- `item_kinds`, by code: `code`, `name`, `form` (`prose`, `work` or `wait`);
- `task_statuses`: `pending`, `in_progress`, `done`.

### `timeline.json`

- `project`: `id`, `folder`, `name` (the draft's title, null without one), `state` (`draft`,
  `open` or `finished`), `archived`, `autopilot`.
- `items`, in `seq` order, each with:
  - `id`, `seq`, `kind` (an item kind's code) and `title` (null for a registered document whose
    text gives none or that has no text);
  - `path`, its document's within the folder (`items/4-card-layout.md`), null for an item with no
    document and for a registered document with no text;
  - `step` (a task id, or null), `urgent`, `for` (a handle, or null) and `summary` (or null);
  - `created_at`;
  - `done`: null while open, else `at`, `cause` (a done cause's code) and `by` (a handle, or null),
    and on a wait `note`, the brain's words at its close through `mark`, null after Finish's;
  - `attachments`: the `id` and `path` of each attachment hung on the item, in their order;
  - on a wait alone, its fields in `add_item`'s shape, a card wait's `cards` and `states` or a timed
    wait's `due_at`, and `firings`, in order, each `seq`, `cause` (`transition`, `due` or
    `requested`), `fired_at`, `transition` (`card`, `from`, `to`, `at`, `by`, null but for a
    transition's), `requested_by` (a handle, or null) and `job`, the run that took it, null while it
    is pending ([`waits.md`](waits.md)).
- `attachments`, every attachment of the project by batch and file name, a draft's hung on no item
  among them: `id`, `path` (`attachments/<batch>/<filename>`), `title`, and `source` (`<environment
  id>:<path>`, null for the draft's copy).

### `plan.json`

Rendered from the plan's rows:

- `ticket` and `repo`, each null when the project has none;
- `tasks`, the tasks in the plan in their order: `id`, `title`, `status` (`pending`,
  `in_progress` or `done`), and `notes`, the task's open notes;
- `notes`, the plan's own open notes.

A note is `id`, `summary`, `content`, `refs` (the ids of the blocks it is about,
`<item id>/<local id>`) and `created`; notes come in the order they were first saved. A removed
task and a struck note are not in the file.

A save of `plan.json` is the agent's way to change the plan, and the rows are the truth: its text
is stored nowhere.

- **Reading.** Strings are trimmed; a blank or null value is absent, and an absent list empty.
  `created` is the record's, and a save's is ignored. `ticket` must match the setting
  `TICKET_ID_PATTERN` whole (by default `[A-Z][A-Z0-9_]*-[1-9][0-9]*`). A task needs `id`, `title`
  and `status`, a note `id`, `summary` and `content`; no two tasks share an id, nor two notes. A
  task's title names the task alone, in at most 25 words as whitespace separates them; what it
  waits on, what follows it and the actions related to it go into a note on the task. Every title
  of the save is counted, not only one it changes, so a title the rows took before the rule holds
  the plan's next save until it is shortened (D180). A
  ref names a block of one of the project's items, never one of the draft's, which are no item's
  (D001): a draft save may drop any of its blocks, since no note can name one.
- **Writing.** The tasks take the save's order. A task the save leaves out is removed: it keeps
  its row, title and status, and comes back when a later save holds it again. A note is matched to
  the open note of its id wherever the save puts it, so a note moved to another task stays the same
  note; a note the save leaves out is struck, and an id the plan has no open note of is a new note.
- **The removal guard.** A save may not remove a task that has open notes: they are struck or
  moved first, in a save of their own.
- **Faults.** Any fault holds the save, and nothing changes. Besides the rules above: bytes that
  are not UTF-8, text that is not JSON (`NaN` and `Infinity` included), a key twice in one object,
  a string holding `\u0000` or an unpaired surrogate, a number too long to read, nesting too deep
  to read, a value that is not an object, a key the file does not have, and a value of the wrong
  type.

A clean save that differs from the rendering of the rows it wrote is answered with that rendering,
so the agent's file comes back canonical.
