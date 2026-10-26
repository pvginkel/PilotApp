# The block DSL

A document is Markdown the agent writes, and the asks in it are fenced blocks the record reads. This
page is the grammar as the engine reads and writes it. Its library is the package `pilot-dsl`,
imported as `pilot_dsl` (`backend/packages/pilot-dsl/`, [below](#the-package)): `parse()`,
`validate()`, `body()` and `words()` in `reader.py`; the splice, the merge, `with_title()` and
`with_facts()` in `writer.py`. The library is pure: it takes text and returns text, and imports
nothing but the standard library and PyYAML, so what it validates against comes in as values
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
- `summary`, shown on the item's card and as the lead of its overlay ([`timeline.md`](timeline.md),
  [`documents.md`](documents.md));
- `step`, the id of a task of the project's plan, a removed task included;
- `urgent`, `true` or `false`;
- `for`, a handle;
- `slug`, read in the draft only: the slug the project takes when it is created. Lower-case
  letters, digits and hyphens, not starting with `draft-`, and no other project's. A draft without
  one is no fault.

Any other key is ignored.

**The title** is the front matter's `title`, else the text of the first ATX heading (`#` to
`######`) outside a fence, else none. A first heading is the title's own when the front matter
gives no title or the same words, and the reader reports its line. An item's title is its text's
alone, none while the text gives none; the draft's is the project's name. Every save Pilot makes of
an item, of its own or of a registered document, must give a title one of the two ways, whatever
its shape; the draft, the handbook, the opening, and a registered document as its worker's turn
left it are outside the rule. Pilot's own item is born with the title it was added with written
first into its front matter, unless that gives a `title` already (`with_title()`), and with the
facts it was added with, `step`, `urgent: true`, `for` and `summary`, each written where the front
matter gives none of its own, in place of a key that gives none, else after its last line
(`with_facts()`).

**The body as shown.** `body(text)` splits a text without a fault the way a screen draws it: its
prose parts and its blocks in order, the front matter and the heading that is the title left out.
A prose part is the Markdown between two blocks or a section's edges, without blank lines at its
ends, and one with nothing in it is left out. A prose part inside a block's own section carries
that block's local id (`Prose.section`), and one outside every section none, so a section's parts
and its block stand together, its heading the first line of its first part.

**A block's own section** (`Block.section`: the heading's text and its span) starts at the nearest
heading before the block, the title's own heading counting as none. A heading is read as the title
is: an ATX heading outside a fence, its text without its `#` marks and closing `#`s; an empty `##`,
a setext heading, `#tag` and a line indented four spaces are none, and open or end no section. The
section runs to the line before the next heading of the same or a higher level, else to the text's
last line, and is the block's only where that span holds no other block, a block under a
sub-heading counting; no heading further out is tried. A block without one has none. The screens
draw a section whose block Pilot answered as one line ([`timeline.md`](timeline.md)).

**The count.** `words(text)` counts the text's words past its front matter, a word being a run of
characters between whitespace: its headings and every block's fence and body count, but not a
block's answer lines (`answer`, `by`, `at`, `note`, `via`, `to`, `done`), so no answer, Done or Undo
moves it.

**The opening** is not read at all: its text is the person's words verbatim, and nothing in it is
a block or a fault ([`engine.md`](engine.md)).

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
  matter, which YAML would read as a line break; a key or a value a double-quoted escape writes
  NUL or an unpaired surrogate into, which no row holds; a body or a front matter nested too deep
  to read, an alias of a list or mapping inside itself among them;
- a key the block's kind does not take; a list or a mapping where one value is wanted; `options`
  that is no list, or an entry that is no label with at most one line; two options with one label,
  compared trimmed and case kept (`block D1: duplicate option label Dome`); `options` or
  `recommend` beside `proposal`; `recommend` naming no option;
- `type` other than `confirmation`; a confirmation without `proposal` or `because`;
  `answer: deferred` without `to`, or `to` without it; a `via` outside its values; an `at` or a
  `done` that is no time; `urgent` other than `true` or `false`.

The faults against the record, which `validate()` finds with the `Facts` the engine gives it:

- `step` naming no task of the project; `for` or `by` naming no handle; `because` naming no
  confirmation reason, the message listing them;
- `to` naming neither `plan` nor a task in the plan, unless the published text carries that same
  `to` on that block: a task removed after the deferral leaves it standing;
- in the draft, a `slug` that is malformed, starts with `draft-` or is another project's;
- a save Pilot makes of an item with no title: ``the item has no title: give it `title` in the
  front matter or a first heading``.

A caller that cannot know the handles or the removed tasks passes none for them (`Facts.handles`,
`Facts.removed_task_ids`), as the store's script does ([below](#the-package)): the rules that rest
on them, `for` and `by` naming no handle and `step` naming no task, are then skipped, and every
other rule judges as it does with them.

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
The agent owns the prose, the front matter, the blocks no person has answered and its own answer
lines. Outside the draft, a person's answer, or an action's Done, freezes its block: once the
published block's `by` names a person, the block is the record's whole. A `by: agent` answer
freezes nothing, and Undo, which takes the answer lines out, unfreezes the block.

- **A frozen block** whose fence the save changed, line for line with line endings aside, gets its
  published fence back where the save has it, with one fault at its opening line: `block D1
  reverted: answered by a person`. A line reordered, added or commented inside it counts as a
  change; the fence moved whole stays where the save put it.
- **A block the save gives a person's answer**, where the record holds none, loses its answer lines,
  a fault per key.
- **A block the save dropped** is put back, its fence as published: after the nearest block before
  it that the save kept, else before the nearest after it, else at the end.
- **A registered document a person has answered in** freezes its body prose too, every line after
  the front matter outside the blocks, blank lines all alike. Where the save changed it, the result
  is the published body under the save's front matter, each block as the rules above left it and a
  block the save added placed as a dropped one is put back, with one fault, `the body prose
  reverted: a person has answered in the document`, at the first line that differs, or with no line
  where the save only added at the end. A block the save added, with its one blank line, is no
  change of the prose; a block it moved is. A title the save gave only in a first heading that this
  reverted is written first into the merged front matter, so the text keeps one.
- **The draft** keeps the merge by line: a person's answer lines alone are the record's. A save that
  keeps them as published, indentation and line endings aside, stands as written, their order
  included; where it changed, dropped or added one, the block's answer lines in the save are taken
  out and the published ones written at the end of the block's mapping, a fault per key. A block may
  go from the draft, its answers with it.
- **The opening** is the record's whole: a save that differs from it is reverted, with one fault.

Each fault of the merge is reported at its line in the merged text, and the merged text is
published. A record line the agent never had, written while its save was held or behind a stale
base, is put back and reported in the same way. A save is gated before it is merged, so a frozen
block's faulty definition in the save still holds the save.

## The corpus

`backend/packages/pilot-dsl/tests/corpus/` pins the grammar, one case per rule. `accepted/`,
`held/`, `never-a-fault/` and `normalised/` hold a `<case>.md` beside a `<case>.json`: its rule, the
facts it changes from `facts.json`, and the parse and faults expected. `splice/` holds a text, the
write and the text expected; `merge/` the published text, the save, and the text and faults
expected. `TestConformanceCorpus` in the package's `tests/test_reader.py` and `test_writer.py` runs
them. The folder's `.gitattributes` keeps every file's bytes as committed, CRLF included.

## The package

`backend/packages/pilot-dsl/` is a Python package of its own: its `pyproject.toml`, PyYAML its one
dependency, the source in `src/pilot_dsl/`, and its tests and the corpus in `tests/`. The backend
depends on it by path, editable (`[tool.uv.sources]` in `backend/pyproject.toml`), and the
backend's pytest runs the package's tests with its own, so `kc project test` and CI run them. The
image copies `packages/` in before its `uv sync` and leaves the package's tests out
(`backend/.dockerignore`). A splice the text cannot take, its block gone, raises the package's
`WriteRefused`, "Cannot <operation> because <cause>"; the engine answers it as its own
`InvalidOperationException`, with the same message.

Two consumers outside this repository follow the grammar. The brain's editing script,
`tools/pilot.py` in `pvginkel/PilotProjects`, reads a project's documents and splices their answer
lines with this package, never through the API (D050). It takes the package from GitHub at the
PilotApp commit its `pyproject.toml` names and its `uv.lock` pins. Before it writes a document, it
runs `validate()` with the facts the store's tree carries: the plan's live tasks, the confirmation
reasons from `reference.json` and the file's own `to`s; no handles, no removed tasks and no other
project's slug. The rules resting on those are left to `pilot-sync`'s check after the write,
against the server's whole record ([`sync.md`](sync.md)) (D063). And AIWorkflow's
`/dev:document-format`, the `dev` plugin's skill for an agent that writes a document Pilot reads,
gives the grammar in its own words. So a change to the grammar here is followed in both:
PilotProjects' pin is moved by hand, the commit in its `pyproject.toml` and then `uv lock`, and the
skill is brought in line.
