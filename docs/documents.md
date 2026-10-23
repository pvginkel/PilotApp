# Documents, the overlay and the panel

A project's documents as a signed-in person reads them apart from the timeline: a document read on
its own, the attachments and their stream, the overlay that shows them, and the side panel with its
Documents tab. The reads are `backend/app/api/items.py`, `projects.py` and `attachments.py`, on
`TimelineService` and `AttachmentService`; the screens are `frontend/src/components/overlay/` and
`components/panel/`. A document on the timeline, inline or as a card, its blocks, its *Unsent* and
its *Send answers*, is [`timeline.md`](timeline.md)'s, and the overlay draws its text the same way.

## Reading a document on its own

- **`GET /api/items/<item_id>/document`** answers the item's timeline entry, every field of it
  ([`timeline.md`](timeline.md)), and `project_id`. A document done by Done, a person's (cause
  `marked`) or Pilot's (`settled`), reads as Done fixed it: its `title`, `summary`, `body`,
  `word_count` and `read_minutes` come from its latest `done` Version, and the rest (`done`,
  `writing`, `edited_at`, `concept`, `attachments`) is the record's as it stands. Only Done cuts
  that Version, so an open item, and one done any other way (an answer, Read, Reviewed, or Finish's
  close, a Done undone before it included), reads as last published. An unknown id, a work item and
  a wait answer `404` "Document of item <id> was not found".
- **`GET /api/projects/<project_id>/draft`** and **`…/handbook`** answer the project document,
  `project.md`, and the handbook, `handbook.md`, as last published: `{title, body, writing}`,
  `title` the text's own, from its front matter or its first heading, else null, and `body` its
  parts as the timeline gives them, `[]` for a text with nothing past its title, as the handbook is
  born. An unknown project answers `404`, and a draft's handbook, which a draft does not have,
  "Handbook of project <id> was not found".

Each is behind the API's sign-in and the `editor` role ([`sign-in.md`](sign-in.md)), on any
project.

## Attachments

An attachment is a copy of a file kept for the reader, never edited, hung on an item
([`record.md`](record.md)). Its bytes stay in PostgreSQL, on its own row, behind `AttachmentStore`
(`backend/app/engine/attachments.py`, the container's `attachment_store`): `put(attachment,
content)` keeps a new row with its bytes, their size and their sha256; `get(attachment)` reads the
bytes; `delete(attachment)` takes the row off the record, which an Item Attachment holding it
refuses. Every other read leaves the bytes alone: `content` is deferred, and touching it on a loaded
row raises. An attachment is at most 16 MiB (`MAX_SIZE`), checked where a file enters the record.

**`GET /api/attachments/<attachment_id>`** streams the bytes (`AttachmentService.served`), behind
the sign-in and the `editor` role, `404` for an unknown id. It sends `Content-Length`, a
`Content-Disposition` carrying the attachment's `filename` (RFC 5987 beyond ASCII), and
`X-Content-Type-Options: nosniff`, and serves the bytes by the type they were stored with:

- a raster image, PNG, JPEG, GIF, WebP, AVIF or BMP, inline as its own type;
- text but HTML inline as `text/plain; charset=utf-8`;
- anything else, SVG and HTML among it, as a download of `application/octet-stream`, so that
  nothing an attachment holds runs in the app's origin.

The title and the stored type do not travel on the stream: the timeline's `attachments` carry them
([`timeline.md`](timeline.md)).

## The overlay

`Overlay` (`components/overlay/overlay.tsx`) is a page over the project's timeline: a backdrop and
the sheet, whose head holds the titles, maximize and the cross, over its body and its foot. It
opens in place, two thirds of the window wide, at least 640px and at most the text column with its
scrollbar, and maximized it takes the window's width; on a wide window both stop at the open panel.
It lies over the side column and the centre, under the top bar and the drawer. The cross, Esc and a
click on the backdrop close it, which goes to the project's address. Its body keeps its scroll
while what it shows is read again, and starts at its top for each thing it shows. On a phone, at
900px and below, it is the whole screen, with no maximize. Where a read fails, its body reads "The
document did not load."

### A document

At a document's address (`DocumentOverlay`, read by `useItemDocument`):

- **The head**: the title, and under it the project's name, the step, the segment bar, *Done* or
  *Unsent*, and *Edited <time>*.
- **The body**: the summary as its lead, the attachments, then the text as an inline document draws
  it, every block answered in place and every settled section collapsed, and Pilot's dots while a
  turn saves it. A segment scrolls the body to its block, which flashes, its section opened first.
- **The foot**: on a done item, "Done · <stamp>", then " · Pilot", or the other person's name, where
  the signed-in person did not do it; on an open review, Reviewed; on an open document, *Send
  answers*, which closes the overlay once the record holds the answers; on an open one-ask item or
  notice, nothing.

Opened at a card's block address, it goes to the block once its body draws it, and flashes it. Open
on a done line shows the document as Done fixed it (above). An address naming the opening, an item
of another project or no item reads "The document did not load."

### An attachment

At an attachment's address, the head is its clip and title over "Attachment of “<item>”", and there
is no foot. Opened from the document's overlay, an arrow with no label leads back to the document.
The body goes by the type it was stored with (`attachment-overlay.tsx`):

- Markdown (`text/markdown`), rendered read only, its front matter left out and a fenced ask shown
  as plain code: an attachment is reader's material, never an item;
- a raster image, inline from the stream;
- SVG, as an image of its text, read from the stream that serves it as a download, so that its
  script never runs;
- other text but HTML, in a monospace block;
- anything else, its title, "<filename> · <size>" and Download, which opens the stream.

An attachment its item does not carry reads "The document did not load."

### The handbook and the project document

The head's handbook button opens the handbook, and the Documents tab's first row the project
document (`HandbookOverlay`, `ProjectDocumentOverlay`, read by `useHandbook` and
`useProjectDraft`). Each is read only, with no foot. Its head is the icon and the text's title, else
"Handbook" or "Project document", over "<project> · Handbook" or "<project> · Project document"; its
body is its prose as Markdown, or *Empty* where it has none, then Pilot's dots while a turn saves
it. A fenced ask in either has no item to answer it, and is not drawn. A failed read, a draft's
handbook included, reads "The document did not load."

### Live

What the overlay shows is read again on its project's `project_changed`, on every rise of the event
stream, when the window regains focus and after the person's own writes
([`timeline.md`](timeline.md)). The record raises no `project_changed` for a save of the handbook,
and raises one for a save of the project document only where it renames the project, so an open
handbook shows Pilot's new text on its next read.

## The side panel

`Panel` (`components/panel/panel.tsx`) stands beside the project's head and timeline: a tab strip,
Documents alone, with its count, and the close cross. The head's Documents button
([`projects.md`](projects.md)) opens it on the Documents tab, and closes it where that tab is
showing. A draft has neither the panel nor the button.

**Each project's own.** A project's panel, open or closed, and its tab are kept in the browser
(`usePanel`, `browser-state.ts`'s `panels`, [`ui.md`](ui.md)) as the person last left them, so
switching projects brings each back as it was. Until the person sets it, it stands open on a wide
window and closed below one, following the window live.

- **A wide window**, 1200px and over: the open panel stands beside the timeline, 420px wide, and the
  overlay beside it, to its left. Its head takes the project head's height, its tab on the name's
  baseline.
- **Below 1200px** it lies over the timeline, and of the panel and the overlay the one opened last
  is on top: the overlay whenever what it shows changes or a row of the panel opens, the panel when
  the Documents button or its tab opens it. Going to an item's or a block's address, not an
  attachment's, on a load or by history, closes the panel and keeps it closed.
- **A phone**, 900px and below: it is the whole screen, as the overlay is.

**Esc.** On a wide window Esc closes the overlay and never the panel. Below 1200px, where the two
lie over each other, it closes the one on top first. With no overlay open, Esc leaves the panel
alone. The panel takes Esc only while it is open below 1200px over an open overlay, on top of it;
it shares the overlay's rank, so it is always the one opened later ([`ui.md`](ui.md)).

### The Documents tab

`documents-tab.tsx`, from the project's timeline and its project document:

- **The project document** first: its title, the text's, else "Project document", over "Project
  document".
- **Attachments**, newest batch first, a batch being the files hung in one call. A batch of one is
  its title over "<item> · <stamp>"; a batch of several is a folder row, the last directory their
  sources share, else "N files", over "<item> · <stamp>", with each file under it, its title over
  its file name. With none: "None yet. A session attaches reader’s material here: a design, a
  survey, a log."
- **In the timeline**: the timeline's documents and reviews, newest first, each its title over
  "<Open | Unsent | Done> · <stamp>", *Unsent* as the timeline reads it. With none: "None yet."

Every row opens in the overlay at its address. The tab's count is the attachments and the
documents, the project document left out.

## Addresses

| Address | Opens |
|---|---|
| `/projects/<project>/documents/<item>` | the item's document in the overlay |
| `/projects/<project>/documents/<item>/attachments/<attachment>` | the attachment in the document's overlay, in the document's place, with the arrow back |
| `/projects/<project>/items/<item>/attachments/<attachment>` | the attachment in the overlay, over the timeline where it stands |
| `/projects/<project>/handbook` | the handbook |
| `/projects/<project>/project-document` | the project document |

The routes draw nothing of their own: the project's route (`routes/_shell/projects/$projectId.tsx`)
draws the overlay over the timeline from them, as it does from a card's block address
([`timeline.md`](timeline.md)). An attachment's chip on the timeline, the done line's indicator and
a row of the Documents tab open its address under its item's, and its chip in the document's overlay
the one under the document's. Closing the overlay goes to the project's address. Another project's
address closes it, since the project's route remounts, while the panel comes back as that project
left it.

## Testing it

The reads are pinned in `TestItemDocument` and `TestProjectDocument`
(`backend/tests/services/test_timeline_service.py`), `TestGetItemDocument`
(`tests/api/test_items.py`) and `TestGetProjectDocuments` (`tests/api/test_projects.py`); the store
and the stream in `tests/engine/test_attachments.py`, `tests/services/test_attachment_service.py`
and `tests/api/test_attachments.py`. The browser suites are
`frontend/tests/timeline/overlay.spec.ts`, `attachments.spec.ts` and `project-documents.spec.ts`,
and `tests/projects/panel.spec.ts`.

A spec hangs files on an item with `projects.attach(itemId, files)` and saves the handbook or the
project document with `projects.saveProjectDocument(projectId, role, text)`, over the record's
testing endpoints ([`projects.md`](projects.md)), on a project made with a session. The `overlay`
fixture (`tests/support/page-objects/overlay-page.ts`) opens a document's address (`open`), the
handbook or the project document (`openProjectDocument`), and reads the overlay's head, body, foot
and attachment view; the `panel` fixture (`panel-page.ts`) reads the panel and its Documents tab. On
the default 1280px viewport the panel stands open.
