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
  handle is lower-case letters, digits and hyphens, unique, and `agent` is no person's.
- `projects`: `number` (an identity, which names a draft's folder), `slug` (none while the project
  is a draft and set once it is not; lower-case letters, digits and hyphens, never starting with
  `draft-`), `name`, the state (`draft`, `open`, `finished`), `archived`, `autopilot`, and the
  plan's `ticket` and `repo`.
- `project_members`: a membership from `joined_at` to `left_at`; one open membership per user and
  project.
- `project_transitions`: each change of a project's state, archived flag or auto pilot switch, with
  when and by whom.

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
  taking its answers.
- `documents`: a Markdown file of a project's folder, `path` relative to the folder. A prose item's
  document shares its item's `id`, and its own columns are `summary` and, for a registered
  document, the source environment and path. The draft (`project.md`) and the handbook
  (`handbook.md`) are a project's documents instead, with `project_id` and `role_code` (`draft`,
  `handbook`), one of each per project. Every document holds two texts, each with its sha256 and
  time: `published_*`, the truth, and `ingested_*`, the agent's latest save with its session.
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
  (a line the merge put back or took out), with its line and message.
- `attachments`: a copy of a file kept for the reader, never edited, at
  `attachments/<batch>/<filename>` of its project's folder: its bytes, `title`, `content_type`,
  `size`, `sha256`, and its source environment and path, which the draft's copy has none of.
  `item_attachments` hangs one on an item, in a position among the item's.

**Sessions and environments**

- `environments`: a KubeCoder environment Pilot has touched, keyed by its environment id. The
  store's row is made by its sidecar's first sync call ([`sync.md`](sync.md)).
- `sessions`: a run of a Claude Code conversation in one environment, for one project, of a session
  kind; `token_hash` is unique, so a bearer token resolves to one session.

## The reference values

Nineteen are PostgreSQL enum types, each a `StrEnum` in `backend/app/models/reference.py`, and four
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
  document's `summary`, read from the front matter and the blocks;
- the document's `blocks` and `block_options`, rewritten in place by local id;
- the project's `name`, the draft's title.

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
`backend/app/services/test_data_service.py`; it refuses to run on production. Playwright's global setup builds its seed database with the same
command, and each worker clones it. The documents, the record's writes and the plan go through the
engine's own operations, so the seed is a record the engine could have produced, and its times are
those of the run:

- the people `ada` and `ben`;
- a draft, `Garden planner`, its draft holding one unanswered question;
- the open project `recipe-box`, ticket `RB-12`, in the environment `example-recipes-1`: an opening;
  items a work session added, with asks open, answered by a person and by Pilot, deferred to a task
  and to the plan, and done; an attachment; and a plan whose notes point at blocks, one of its tasks
  removed.

Tests find its rows by slug, handle and item title.
