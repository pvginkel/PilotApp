# Documents, the overlay and the panel

A project's documents as a signed-in person reads them apart from the timeline: a document read on
its own, a draft's asks answered in place, the attachments and their stream, the overlay that shows
them, and the side panel with its Documents tab and a draft's Draft tab. The reads are
`backend/app/api/items.py`, `projects.py` and `attachments.py`, on `TimelineService` and
`AttachmentService`; the screens are `frontend/src/components/overlay/` and
`components/panel/`. A document on the timeline, inline or as a card, its blocks, its *Unsent* and
its *Send answers*, is [`timeline.md`](timeline.md)'s, and the overlay draws its text the same way.
The panel's Chat tab, and Discuss in the overlay's head, are [`chats.md`](chats.md)'s.

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

## A draft's asks

A draft's `project.md` has no item, so a person answers its asks in place, in the Draft tab (below),
through routes of the draft's own (`DraftService`, `backend/app/services/draft_service.py`), each
the record's own write into `project.md`, by the caller, now:

- **`POST /api/projects/<id>/draft/blocks/<local id>/answer`** `{answer, note?}` answers an ask as
  an item's block route answers one ([`timeline.md`](timeline.md));
- **`POST /api/projects/<id>/draft/blocks/<local id>/done`** `{note?}` marks an action without
  options Done, the note its paste-back.

Each answers `204`. Neither takes an Undo, and answering again replaces the answer. An ask the draft
does not hold is a `404`; a caller who has not chosen a handle, a project that is no draft or is
archived, and an answer the block does not take are a `409`. Each holds the project's row for share
before it reads the project's state, so Create project cannot come between them: past Create the
project document takes no answer. In the definition chat, Pilot records an answer a person gives
there through `answer` on `project.md/<local id>` ([`mcp.md`](mcp.md)).

## Attachments

An attachment is a copy of a file kept for the reader, never edited, hung on an item, or, a draft's,
on nothing until Create project hangs it on the opening ([`record.md`](record.md)). Its bytes stay
in PostgreSQL, on its own row, behind `AttachmentStore` (`backend/app/engine/attachments.py`, the
container's `attachment_store`): `put(attachment, content)` keeps a new row with its bytes, their
size and their sha256; `get(attachment)` reads the bytes; `delete(attachment)` takes the row off the
record, which an Item Attachment holding it refuses. Every other read leaves the bytes alone:
`content` is deferred, and touching it on a loaded row raises. An attachment is at most 16 MiB
(`MAX_SIZE`), checked where a file enters the record: `AttachService.attach`, by which a work item's
session, a chat's, and a definition chat's with no `to`, copy files in with `attach_file`
([`mcp.md`](mcp.md)), and the record's testing routes alike.

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
the sheet, whose head holds the titles, Discuss once what it shows is read, quoting it
([`chats.md`](chats.md)), maximize and the cross, over its body and its foot. It
opens in place, two thirds of the window wide, at least 640px and at most the text column with its
scrollbar, and maximized it takes the window's width; on a wide window both stop at the open panel.
It lies over the side column, the gold bar and the centre, under the top bar and the drawer. The
cross, Esc and a click on the backdrop close it, which goes to the project's address. Its body keeps
its scroll while what it shows is read again, and starts at its top for each thing it shows. On a
phone, at 900px and below, it takes the window's width in the centre's row, under the gold bar
([`ui.md`](ui.md)), with no maximize. Where a read fails, its body reads "The document did not
load." A work item's session log opens in it too ([`work.md`](work.md)).

**The focus.** The sheet is a dialog named by its titles. It takes the focus as it opens, and
again when what it shows replaces what had it, and gives it back as it closes to what had it before,
where that is still on the page. While it is open the timeline under its backdrop takes no focus
(`inert`), nor the panel below 1200px where the overlay lies over it. The project's head does: its
Discuss and Documents buttons, and the overlay's own Discuss, are how the panel opens over the
overlay below 1200px.

### A document

At a document's address (`DocumentOverlay`, read by `useItemDocument`):

- **The head**: the title, and under it the project's name, the step, the segment bar, *Done* or
  *Unsent*, and *Edited <time>*.
- **The body**: the summary as its lead, the attachments, then the text as an inline document draws
  it, every block answered in place and every settled section collapsed, and Pilot's dots while a
  turn saves it. A segment scrolls the body to its block, which flashes, its section opened first.
- **The foot**: on a done item, "Done · <stamp>", then " · Pilot", or the other person's name, where
  the signed-in person did not do it; on an open review, Reviewed; on an open document, *Send
  answers*, which closes the overlay once the record holds the answers, each disabled while the
  project is archived (D012); on an open one-ask item or notice, nothing.

A registered document with no text, awaiting its read at the end of the run that registered it or
after one that failed ([`round-trip.md`](round-trip.md)), draws its head, titled by its file's
name, and "The document did not load." as its body; its foot holds Reviewed once the read was made,
and nothing while it awaits it. Its attachments open at their addresses.

Opened at a card's block address, it goes to the block once its body draws it, and flashes it. Open
on a done line shows the document as Done fixed it (above), with no *Edited <time>* and no dots: those
tell of the text as it stands. A document done another way, by an answer, a turn's end or Finish,
shows its text as it stands, with both. An address naming the opening, an item of another project or
no item reads "The document did not load."

### An attachment

At an attachment's address, the head is its clip and title over "Attachment of “<item>”", or
"Attachment of the draft" for one hung on nothing, and there is no foot. Opened from the document's
overlay, an arrow with no label leads back to the document. The body goes by the type it was stored
with (`attachment-overlay.tsx`):

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
body is its prose as Markdown and its asks, in their order, or *Empty* while it has nothing past its
title, then Pilot's dots while a turn saves it. A fenced ask in either has no item to answer it, so
it reads only (D072), drawn as the timeline draws a settled ask (`DocumentBlock`,
`components/timeline/block.tsx`). An answered ask is closed, with its answer, who gave it and *In
the chat* where it was given there, and with no chevron and no Discuss. An ask left open at Create
stands open, its controls disabled. A failed read, a draft's handbook included, reads "The document
did not load."

### Live

What the overlay shows is read again on its project's `project_changed`, on every rise of the event
stream, when the window regains focus and after the person's own writes
([`timeline.md`](timeline.md)). A save of the handbook or the project document raises one where it
changes the published text or makes its session the one writing it, and a turn's end raises one for
each document it lets go ([`engine.md`](engine.md)), so an open overlay shows Pilot's new text, and
its dots come and go, as they happen.

## The side panel

`Panel` (`components/panel/panel.tsx`) stands beside the project's head and timeline: a tab strip,
Chat first, with the unread dot ([`chats.md`](chats.md)), then Documents, with its count, and the
close cross. The head's Discuss ([`projects.md`](projects.md)) opens it on the Chat tab and its
Documents button on the Documents tab, each closing it where its tab is showing; Discuss elsewhere
and *In the chat* open it on the Chat tab, on top. A draft's panel stands beside its definition
chat, with Draft in Chat's place: the head's Draft toggle opens it on the Draft tab or closes it
where that tab shows, and an ask a quote or an effect line goes to opens it there, on top. A draft's
Discuss and *In the chat* go to its definition chat instead ([`chats.md`](chats.md)).

**Each project's own.** A project's panel, open or closed, and its tab are kept in the browser
(`usePanel`, `browser-state.ts`'s `panels`, [`ui.md`](ui.md)) as the person last left them, so
switching projects brings each back as it was. Until the person sets it, it stands open on a wide
window and closed below one, following the window live, on its first tab: an open project's Chat, a
draft's Draft. A remembered Chat reads as Draft for a draft and Draft as Chat for an open project,
so a panel open on the Draft tab at Create project stays open, on the Chat tab.

- **A wide window**, 1200px and over: the open panel stands beside the timeline, 420px wide, and the
  overlay beside it, to its left. Its head takes the project head's height, its tab on the name's
  baseline.
- **Below 1200px** it lies over the timeline, and of the panel and the overlay the one opened last
  is on top: the overlay whenever what it shows changes or a row of the panel opens, the panel when
  a button of the head, a tab, a Discuss or *In the chat* opens it. Going to an item's or a block's
  address, not an attachment's, on a load or by history, closes the panel and keeps it closed.
- **A phone**, 900px and below: it is the whole screen, as the overlay is.

**Esc.** On a wide window Esc closes the overlay and never the panel. Below 1200px, where the two
lie over each other, it closes the one on top first. With no overlay open, Esc leaves the panel
alone. The panel takes Esc only while it is open below 1200px over an open overlay, on top of it;
it shares the overlay's rank, so it is always the one opened later ([`ui.md`](ui.md)).

### The Draft tab

A draft's `project.md` as Pilot writes it (`DraftTab`, `components/panel/draft-tab.tsx`), read again
on each of the project's live events. It shows the title as the prose's heading, then the body's
prose and asks in their order, then Pilot's dots while a turn saves it, else the foot: "Change
anything in the chat. **Create project** hands it to Pilot, which sets it up and starts the plan."
With neither title nor body it reads "Empty. Pilot writes the project here as you talk, and nothing
is set up until you press **Create project**.", and a failed read "The draft did not load."

Each ask is answered in place, as an inline document's block is (`DraftBlock`, through the draft's
routes above), its Discuss quoting it as `project.md/<local id>`, its unsent words kept as an item's
are ([`ui.md`](ui.md)). An ask gone to is scrolled into view and
flashed (`hooks/use-draft-place.ts`). A link to material Pilot attached,
`[words](attachments/<batch>/<filename>)` relative to the draft's folder (a leading `./` dropped,
escapes decoded), opens that attachment in the overlay. Every other link, ticket id, repo and
environment in the draft reads as plain words.

### The Documents tab

`documents-tab.tsx`, from the project's timeline and its project document, read as one
(`usePanelDocuments`):

- **The project document** first: its title, the text's, else, and until it is read, "Project
  document", over "Project document".
- **Attachments**, newest batch first, a batch being the files hung in one call. A batch of one is
  its title over "<item> · <stamp>"; a batch of several is a folder row, the last directory their
  sources share, else "N files", over "<item> · <stamp>", with each file under it, its title over
  its file name, a folder's file named by its path relative to the folder. With none: "None yet. A
  session attaches reader’s material here: a design, a survey, a log."
- **In the timeline**: the timeline's documents and reviews, newest first, each its title over
  "<Open | Unsent | Done> · <stamp>", *Unsent* as the timeline reads it. With none: "None yet."

Every row opens in the overlay at its address. While either read is under way the two headings
stand with nothing under them, and while either's latest read failed, "The documents did not load."
stands in their place, under the project document's row. The tab's count is the attachments and
the documents, the project document left out, and stands only once both are read.

A draft's Documents tab lists the attachments alone, what Pilot attached so far in its definition
chat, hung on nothing (`unhung_attachments`, [`timeline.md`](timeline.md)), a row's line its stamp:
its project document is its Draft tab, and it has no timeline. With none: "None yet. Pilot attaches
here what you point it at in the chat: a card, a handover, a design."

## Addresses

| Address | Opens |
|---|---|
| `/projects/<project>/documents/<item>` | the item's document in the overlay |
| `/projects/<project>/documents/<item>/attachments/<attachment>` | the attachment in the document's overlay, in the document's place, with the arrow back |
| `/projects/<project>/items/<item>/attachments/<attachment>` | the attachment in the overlay, over the timeline where it stands |
| `/projects/<project>/attachments/<attachment>` | the attachment in the overlay, wherever it hangs: a draft's, on nothing, and the same one once Create hangs it on the opening |
| `/projects/<project>/handbook` | the handbook |
| `/projects/<project>/project-document` | the project document |

The routes draw nothing of their own: the project's route (`routes/_shell/projects/$projectId.tsx`)
draws the overlay over the timeline from them, as it does from a card's block address
([`timeline.md`](timeline.md)). An attachment's chip on the timeline, the done line's indicator and
a row of the Documents tab open its address under its item's, and its chip in the document's overlay
the one under the document's; a draft's Documents tab and its links open the one under the
project's. Closing the overlay goes to the project's address. Another project's
address closes it, since the project's route remounts, while the panel comes back as that project
left it.

## Testing it

The reads are pinned in `TestItemDocument` and `TestProjectDocument`
(`backend/tests/services/test_timeline_service.py`), `TestGetItemDocument`
(`tests/api/test_items.py`) and `TestGetProjectDocuments` (`tests/api/test_projects.py`); the store
and the stream in `tests/engine/test_attachments.py`, `tests/services/test_attachment_service.py`
and `tests/api/test_attachments.py`; a draft's answers in `tests/services/test_draft_service.py`.
The browser suites are `frontend/tests/timeline/overlay.spec.ts`, `attachments.spec.ts` and
`project-documents.spec.ts`, and `tests/projects/panel.spec.ts` and `draft-panel.spec.ts`.

A spec hangs files on an item with `projects.attach(itemId, files)`, or on nothing in a draft with
`projects.attachToDraft(projectId, files)`, saves the handbook or the project document with
`projects.saveProjectDocument(projectId, role, text)` and answers an open project's with
`projects.answerProjectDocument(projectId, role, block, answer, handle)`, over the record's testing
endpoints ([`projects.md`](projects.md)), on a project made with a session. The `overlay` fixture
(`tests/support/page-objects/overlay-page.ts`) opens a document's address (`open`), the handbook or
the project document (`openProjectDocument`), and reads the overlay's head, body, foot and
attachment view, its head's Discuss among them; the `panel` fixture (`panel-page.ts`) reads the
panel, its Documents tab and a draft's Draft tab (`draft`, `draftBlock(id)`), and the `chat` fixture
its Chat tab ([`chats.md`](chats.md)). On the default 1280px viewport the panel stands open, on the
Chat tab, a draft's on the Draft tab. A draft's page draws no timeline, so `timeline.open()`, which
waits for the timeline's read, never returns on one: a spec opens a draft with
`projectList.open(id)` or `projectHead.open(id)`.
