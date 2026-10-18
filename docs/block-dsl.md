# The block DSL

A document is Markdown the agent writes, and the asks in it are fenced blocks the record reads. This
page is the grammar as the engine reads and writes it. Its library is `app.engine.dsl`
(`backend/app/engine/dsl/`): `parse()` and `validate()` in `reader.py`, the splice and the merge in
`writer.py`. The library is pure: it takes text and returns text, and imports nothing but the
standard library, PyYAML and the app's exceptions, so what it validates against comes in as values
(`Facts`).

````markdown
---
title: Card layout
summary: How a recipe card is laid out on a phone
step: build
for: ada
---

The card is read at arm's length in the kitchen, so the layout matters more than the colours.

```decision id=D1
options:
  - Photo first: the photo fills the top half
  - Text first
recommend: Photo first
answer: Text first
by: ada
at: 2026-10-12T09:40:00Z
```
````

## The document

**The front matter** is optional: a first line `---`, then a YAML mapping, then a `---` line. A
`---` first line with no closing `---` opens no front matter. The keys the record reads:

- `title`;
- `summary`, the item's line on the timeline;
- `step`, the id of a task of the project's plan, a removed task included;
- `urgent`, `true` or `false`;
- `for`, a handle;
- `slug`, read in the draft only: the slug the project takes when it is created. Lower-case
  letters, digits and hyphens, not starting with `draft-`, and no other project's. A draft without
  one is no fault.

Any other key is ignored.

**The title** is the front matter's `title`, else the text of the first ATX heading (`#` to
`######`) outside a fence, else none. The reader reports that heading's line, so that a display
can strip it from the body. An item whose text gives no title keeps the title it holds: the one
it was added with, or the last its text gave. The draft's title is the project's name. Pilot's own
item with a single block must give a title one of the two ways.

**The prose** is never parsed: everything outside the front matter and the blocks is the agent's,
and no fault comes from it. A fence is a line of three or more backticks or tildes, indented up to
three spaces; it is closed by a line of the same character, at least as long, indented up to three
spaces, with nothing but whitespace after it. A backtick fence whose info string holds a backtick
is not a fence. A fence whose info string is no block kind is a code block, and the reader passes
over it.

## Blocks

A block is a fence whose info string is a block kind and the block's local id: `decision id=D1`.
The local id is unique within its document; the block's id is `<item id>/<local id>`. The body is
a YAML mapping in block style, one key to a line.

| Kind | Takes |
|---|---|
| `decision` | `options` with an optional `recommend`, or `proposal`; `type: confirmation` with `because`; `check` |
| `question` | `default` |
| `action` | `options`, `check` |

- `options`: a list, each entry a bare label (`- Yes`) or a label with one line of text
  (`- Photo first: the photo fills the top half`).
- `recommend`: the label of the option recommended.
- `proposal`: what Pilot proposes, in place of options.
- `type: confirmation`: a decision asking the operator's go on a `proposal`, on the grounds
  `because` names: a confirmation reason's code, the list `reference.json` carries
  ([`projection.md`](projection.md)).
- `default`: a question's suggested answer.
- `check`: read and kept, never acted on.

Every kind also takes the answer lines:

- `answer`: an option's label, `Agree`, `Yes` or `No`, free words, or `deferred`;
- `by`: a handle; `agent` is Pilot;
- `at`: when it was answered; `done`: when an action was done. Each is an ISO 8601 date and time,
  one without a zone being UTC; the engine writes them in UTC to the second
  (`2026-10-12T09:40:00Z`);
- `note`: words that go with the answer, or what was pasted back on an action's Done;
- `via`: `chat`, `recommended` or `autopilot`. No `via` line, or `via: app`, is the app's own
  controls;
- `to`: with `answer: deferred` only, and required with it: a task in the plan, or `plan` for the
  plan itself.

A block whose `by` names a person holds the record's answer; one with `by: agent`, or with no
`by`, holds the agent's.

**Values are read as written.** A body is YAML read with no implicit typing, so every scalar is
the string written: `answer: Yes` matches the option `- Yes`, and `answer: 2` is `"2"`. Values are
trimmed, and an empty one is absent.

## Faults

Any fault holds the save: the published text stays as it was, and the faults stand on the path
until a save of it is clean ([`engine.md`](engine.md)). A fault carries its line in the file, from
1, or none for the document as a whole, and a message written for the agent to act on, such as
``block D1: `recommend: Rack` names no option``.

The faults of the text itself:

- a fence that is not closed, where the reading stops; a kind written with capitals; a fence
  carrying `id=` whose first word is no kind; a block without `id=<id>`, or with more after it; two
  blocks with one id;
- a body or a front matter that is no YAML mapping; a body in flow style (`{…}`); a key written
  twice; a raw U+0085, U+2028, U+2029 or carriage return within a line of a body or the front
  matter, which YAML would read as a line break;
- a key the block's kind does not take; a list or a mapping where one value is wanted; `options`
  that is no list, or an entry that is no label with at most one line; `options` or `recommend`
  beside `proposal`; `recommend` naming no option;
- `type` other than `confirmation`; a confirmation without `proposal` or `because`;
  `answer: deferred` without `to`, or `to` without it; a `via` outside its values; an `at` or a
  `done` that is no time; `urgent` other than `true` or `false`.

The faults against the record, which `validate()` finds with the `Facts` the engine gives it:

- `step` naming no task of the project; `for` or `by` naming no handle; `because` naming no
  confirmation reason, the message listing them;
- `to` naming neither `plan` nor a task in the plan, unless the published text carries that same
  `to` on that block: a task removed after the deferral leaves it standing;
- in the draft, a `slug` that is malformed, starts with `draft-` or is another project's;
- Pilot's own item with a single block and no title.

Never a fault: anything in the prose, an answer matching no option, an answer without `by`, `step`
naming a removed task, and a code block in a fence of any other kind.

## What the record writes

The record's own writes are spliced into the published text: the block's answer lines are taken
out and the new ones written, and every other line stays as it was, its line ending included.

- **An answer**: `answer`, `by`, `at`, then `note`, `via` and `to` where given, in that order. It
  replaces the block's answer, Pilot's included.
- **Done on an action**: `done` and `by`, then `note` where given.
- **Undo**: the answer lines removed, and none restored, an answer of Pilot's that the person's
  replaced included.
- **Done with the recommendations**: every unanswered block that has a recommendation answered
  with it, `via: recommended`. The recommendation is a question's `default`, `Yes` to a
  confirmation, `Agree` to another proposal, or a decision's recommended option; an action has
  none.

The new lines go after the last line of the block's last key (before the closing fence in a block
with no key), at the indentation of its first key, else of its fence, and take the line ending of
the text's first line. A value is written plain where YAML allows, quoted otherwise, as a literal
block (`|`) over several lines, indented four spaces from its key so that no line of it can close
the fence, and double-quoted with escapes where it holds a character YAML breaks a line at.

## The merge by ownership

An agent's save that has no fault is merged against the published text before it is published.
The agent owns the prose, the front matter, every block's definition and its own answer lines; the
record owns the answer lines of every block whose published `by` names a person.

- A save that keeps a person's answer lines as published, indentation and line endings aside,
  stands as written, their order included. Where it changed, dropped or added one, the block's
  answer lines in the save are taken out and the published ones written at the end of the block's
  mapping, a fault per key.
- A block the save gives a person's answer, where the record holds none, loses its answer lines, a
  fault per key.
- A block the save dropped is put back, its fence as published: after the nearest block before it
  that the save kept, else before the nearest after it, else at the end. The draft is the
  exception: a block may go from it, its answers with it.
- The opening is the record's whole: a save that differs from it is reverted, with one fault.

Each fault of the merge is reported at its line in the merged text, and the merged text is
published. A record line the agent never had, written while its save was held or behind a stale
base, is put back and reported in the same way.

## The corpus

`backend/tests/fixtures/dsl/` pins the grammar, one case per rule. `accepted/`, `held/`,
`never-a-fault/` and `normalised/` hold a `<case>.md` beside a `<case>.json`: its rule, the facts
it changes from `facts.json`, and the parse and faults expected. `splice/` holds a text, the write
and the text expected; `merge/` the published text, the save, and the text and faults expected.
`TestConformanceCorpus` in `backend/tests/engine/dsl/test_reader.py` and `test_writer.py` runs them.
The folder's `.gitattributes` keeps every file's bytes as committed, CRLF included.
