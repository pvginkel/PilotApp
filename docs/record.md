# The record

Everything Pilot owns lives in PostgreSQL, the content of every document included. The store's
tree of Markdown and JSON files is rendered from it ([`projection.md`](projection.md)), and the
engine keeps the two in step ([`engine.md`](engine.md)). This page is the schema as built: the
models in `backend/app/models/` and the Alembic revisions in `backend/alembic/versions/`.

## The tables

**People and projects**

- `users`: a person who signs in, or Pilot itself. Pilot is the one row of kind `agent`, with the
  handle `agent` and the name `Pilot`, written by the first revision; it has no `subject`, email,
  notification token or avatar slot. A person has a `subject` and an `avatar_slot`, each unique. A
  handle is lower-case letters, digits and hyphens, unique, and `agent` is no person's. A person's
  row is made when they choose their handle, at their first sign-in, with the lowest free slot
  counting from 1 ([`sign-in.md`](sign-in.md)).
- `projects`: `number` (an identity, which names a draft's folder), `slug` (none while the project
  is a draft and set once it is not; lower-case letters, digits and hyphens, never starting with
  `draft-`), `name`, the state (`draft`, `open`, `finished`), `archived`, `autopilot`, `paused`,
  and the plan's `ticket` and `repo`.
- `project_members`: a membership from `joined_at` to `left_at`; one open membership per user and
  project, and a rejoin is a new row; nothing makes Pilot a member.
- `project_transitions`: each change of a project's state, archived flag, auto pilot switch or
  pause, with when and by whom ([`projects.md`](projects.md)).

**The plan**, which `plan.json` renders and is parsed back into

- `plan_tasks`: keyed by project and the agent's `task_id`, with `position`, `title` and
  `status_code` (`pending`, `in_progress`, `done`). A task is never deleted: a removed one keeps its row with
  `removed_at`, and loses its position.
- `plan_notes`: a note on a task, or on the plan itself with no task: the agent's `note_id`,
  `summary`, `content`, `created_at`. A note is never deleted either: a struck one keeps its row
  with `deleted_at`. One open note per `note_id` and project; a note's task is of its own project.
- `plan_note_references`: the blocks a note's `refs` name.

**The timeline and its documents**

- `items`: an entry on a project's timeline, numbered by `seq` from 1 within the project, of an
  item kind. The opening is a person's (`created_by_user_id`); every other item was added by a
  Session (`created_by_session_id`). Its done is `done_at` with `done_cause_code`, and
  `done_by_user_id` when a user did it; `consumed_at` with `consumed_session_id` is a session
  taking its answers: a registered document's, the continuation of the run that registered it, from
  its placement ([`round-trip.md`](round-trip.md)).
- `documents`: a Markdown file of a project's folder, `path` relative to the folder. A prose item's
  document shares its item's `id`, and its own columns are `summary` and, for a registered
  document, the source environment and path, both or neither, `read_failed_at` (its read at its
  run's end failed, so it has no text: `ck_documents_read_failed`), `written_back_at` (its closed
  text written to its file) and `write_back_refused_at` (that write refused by the controller, a
  document with a text not written back: `ck_documents_write_back_refused`). The draft
  (`project.md`) and the handbook (`handbook.md`) are a project's documents instead, with
  `project_id` and `role_code` (`draft`, `handbook`), one of each per project. A document holds two
  texts, each with its sha256 and time: `published_*`, the truth, and `ingested_*`, the agent's
  latest save with its session; a registered document has no published text until its file is read,
  and none after a failed read.
  `writing_session_id` with `writing_since` is the session whose turn is writing it.
- `document_versions`: a published text fixed, numbered from 1 per document, with its cause
  (`born`, `registered`, `turn`, `done`) and the session it is of, if any.
- `blocks`: an ask inside a document, unique by document and `local_id`, with what its text says:
  kind, `confirmation`, `because_code`, `proposal`, `default_value`, `check_text`, and the answer
  (`answer`, `answered_by_user_id`, `answered_at`, `note`, `via_code`, `done_at`,
  `deferred_to_task_id`).
- `block_options`: a block's choices in order: `label`, `text` (none for a bare label),
  `recommended`. Deleting a block deletes its options.
- `save_errors`: a fault the engine holds against the latest save of a path, the path from the
  tree's root, under the Environment whose save raised it: `parse` (the save is held) or `reverted`
  (what the merge put back or took out), with its line and message.
- `attachments`: a copy of a file kept for the reader, never edited, at
  `attachments/<batch>/<filename>` of its project's folder: its bytes, `title`, `content_type`,
  `size`, `sha256`, and its source environment and path, which the draft's copy has none of,
  and `copied_at`; a file a session copied has that session (`created_by_session_id`), and its
  `filename` may hold slashes, a folder's file named by its path relative to the folder. Its
  bytes, `content`, are read and written through the engine's `AttachmentStore` alone: a loaded row
  never holds them ([`documents.md`](documents.md)). `item_attachments` hangs one on an item, in a
  position among the item's.

**Sessions and environments**

- `environments`: a KubeCoder environment Pilot has touched, keyed by its environment id. A work
  item's start writes the row of an environment it creates from the create's answer, and an
  environment's start makes one from the controller's report when it first touches it; the store's
  sidecar's first sync call makes the store's the same way ([`sync.md`](sync.md)), or by its id
  alone while no controller is configured. The fleet stream keeps its `name`, `last_state`,
  `last_seen_at` and `exempt` current; `server_started_at` and `started_pod_at` are Pilot's claim,
  that it started the environment and the pod's start that bring-up settled on, and `stop_due_at`
  is when Pilot stops it. An environment Pilot created is its own: `server_created_at` and `repo`,
  the repository it was made from, set together, and `delete_due_at`, when Pilot deletes it while
  it stays free, which only one of its own has ([`controller.md`](controller.md)).
- `sessions`: a run of a Claude Code conversation in one environment, none while its start has not
  provided one, for one project, of a session kind, in a state (`held`, `starting`, `running`, `idle`, `stopped`, `ended`, `failed`), the held
  ones indexed by `created_at`, the gate's order:
  `controller_session` names its headless session at the controller and `conversation_id` its
  Claude conversation; `current_line`, a JSON object, says what its turn in flight is doing, and is
  null while none is ([`sessions.md`](sessions.md)). `token_hash` is unique, so a bearer token
  resolves to one session: the sha256 of the token its latest create carried, and of one no one
  holds before its first ([`mcp.md`](mcp.md)).
- `work`: a work item, the extension table its Item and its Session share their id with
  ([`work.md`](work.md)): `project_id`, `session_kind_code` (`work` or `job`, never a Chat's),
  `trigger_code` (a job's Work Trigger; a worker's run has none) and `trigger_item_id` (an item of
  the same project, never the work item itself; a continuation's, the registered document whose
  close released it), `repo`, the repository a worker's run is placed by
  (none for a job), and `autopilot`, the switch's setting at its brief. Its keys reach its Item and
  its Session through the one project. A `work`-kind Session may stand with no `work` row, as the
  seed's idle session and a testing project's do.
- `turns`: a message sent to a session and the reply it produced, numbered by `seq` from 1 within
  the session: its `message`, its `author_user_id` (none for the server's own, such as a start's
  brief), the item or the block it quotes (one at most; a quoted block's removal clears the key),
  `started_at`, `ended_at`, and the `error` of a turn that failed.
- `session_records`: every session's list, chat and work alike, in one table, numbered by `seq`
  from 1 within its session without a gap, which its writer holds under the session's row lock:
  `kind_code` (`claude`, `result`, `send`, `server`), the `payload`, its turn (`turn_id`, a turn of
  its own session), and `at`. A `claude` or `result` record is a line or the end of the controller
  session's raw stream: it falls in a turn and carries its `controller_session` and `raw_offset`,
  which no other kind has. A `claude` payload is never a `stream_event` line. A `send` has no
  payload, its words and author being its turn's, and a turn has one at most; every other kind
  has a payload.

## The reference values

Eighteen are PostgreSQL enum types, each a `StrEnum` in `backend/app/models/reference.py`, and four
are tables with rows, because each value carries a fact. The revisions write the rows; a value is
added by a revision and nowhere else.

| Table | Rows |
|---|---|
| `item_kinds` (`name`, `form`, `icon`) | prose: `opening`, `decision`, `confirmation`, `question`, `action`, `notice`, `document`, `review`; work: `work`; wait: `card_wait`, `timed_wait` |
| `done_causes` (`name`, `undo_offered`) | undo offered: `answered`, `marked`, `settled`; not: `turn_ended`, `finished` |
| `confirmation_reasons` (`name`, `asks_under_autopilot`, `description`) | asked only while auto pilot is off: `auto-pilot-off`, `rider`; asked under auto pilot too: `irreversible`, `product-hold`, `self-approval` |
| `session_kinds` (`name`, `surface`, `on_timeline`) | `chat` (`pilot-store`, not on the timeline), `work` (`pilot-work`), `job` (`pilot-store`) |

A confirmation reason's `description` is the line `reference.json` gives the agent, which picks a
confirmation's `because` from it.

## The caches

Some columns are caches of a document's published text, rebuilt in the transaction of every change
to it ([`engine.md`](engine.md)):

- a prose item's `kind_code`, `title`, `plan_task_id`, `urgent` and `for_user_id`, and its
  document's `summary`, read from the front matter and the blocks; `title` is none while the text
  gives none;
- the document's `blocks` and `block_options`, rewritten in place by local id;
- the project's `name`, the draft's title.

The opening's text is read for nothing: it has no `blocks`, and its item keeps the kind, title and
caches it was born with.

The project's `state_code`, `archived`, `autopilot` and `paused` are caches of its transitions,
written with each one ([`projects.md`](projects.md)). A session's `turns`, `turn_started_at` and
`turn_ended_at` are caches of its turns, which the send, the turn's end and the session start
refresh ([`sessions.md`](sessions.md)).

## Physical notes

- The three document text columns (`documents.ingested_text`, `documents.published_text`,
  `document_versions.text`) are `text` compressed with `lz4`, which the revision sets and a model
  cannot carry. They keep an empty text; every other text column stores an empty or blank value as
  NULL (the template's empty-string normalisation).
- A hash is the sha256 of the text's UTF-8 bytes, in hex. Every time is `timestamptz`.
- Two references no key can reach are the engine's to check: a block's `deferred_to_task_id` names
  a task of its document's project, and a plan note's reference names a block of its project's
  items.

## Changing the schema

- **A change is a new revision.** Every green build of `main` deploys, and the `migrate` init
  container applies the revisions ([`deployment.md`](deployment.md)), so a revision on `main` is
  never edited.
- **The suite holds the models to the revisions.** Every test database is built by the revisions;
  `test_models_match_revisions` (`backend/tests/test_database_schema.py`) fails on any difference
  between the models and them. Autogenerate compares no enum type, so `TestEnumTypes`
  (`backend/tests/models/test_reference.py`) holds the module's `ENUM_TYPES` to the database's:
  a value a revision adds goes into the `StrEnum` with it.
- **Every enum type exists from the first revision.** A later revision references one with
  `postgresql.ENUM(name=…, create_type=False)` and never creates it; a model uses
  `app.models.reference`'s type.
- **Names.** `db.metadata` has no naming convention, so every check constraint and index is named
  (`ck_<table>_…`, `ix_<table>_…`, `uq_<table>_…`); primary, foreign and unique key constraints
  take PostgreSQL's names. A reference value's column is `<attr>_code`, a reference to a row's
  `<attr>_id` or `<role>_user_id`.

## The seed

`cli load-test-data --yes-i-am-sure` recreates the dev database from the revisions and loads an
invented record into it, `TestDataService.load_all()` in
`backend/app/services/test_data_service.py`; it refuses to run on `STAGE=prd`, production's stage.
Playwright's global setup builds its seed database with the same command, and each worker clones it.
The documents, the record's writes and the plan go through the engine's own operations, so the seed
is a record the engine could have produced, and its times are those of the run:

- the people `ada` and `ben`, in avatar slots 1 and 2;
- a draft, `Garden planner`, ada's, its draft holding one unanswered question;
- the open project `recipe-box`, ticket `RB-12`, ada's and ben's, in the environment
  `example-recipes-1`: an opening; items a work session added, with asks open, answered by a person
  and by Pilot, deferred to a task and to the plan, and done; an attachment; and a plan whose notes
  point at blocks, one of its tasks removed;
- the finished project `bike-log`, `Bike repair log`, ben's and ada's, both its steps done, auto
  pilot turned off as it finished;
- the archived project `photo-album`, `Photo album`, ada's, one step in progress and one not
  started.

Tests find its rows by slug, handle and item title.
