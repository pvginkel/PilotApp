# Documents, their tabs and the panel

A project's documents as a signed-in person reads them apart from the timeline: a document read on
its own, a draft's asks answered in place, the attachments and their stream, what opens them, off a
phone a tab on the project's tab line and on a phone a view, and the side panel with its Documents
tab and a draft's Draft tab. The reads are `backend/app/api/items.py`, `projects.py` and
`attachments.py`, on `TimelineService` and `AttachmentService`; the screens are
`frontend/src/components/overlay/`, `components/projects/doc-tabs.tsx` and `components/panel/`. A
document on the timeline, inline or as a card, its blocks, its *Unsent* and its *Send answers*, is
[`timeline.md`](timeline.md)'s, and an opened document draws its text the same way. The panel's
Chat tab, and Discuss in an opened document's head, are [`chats.md`](chats.md)'s.

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

## What opens

`Overlay` (`components/overlay/overlay.tsx`) draws what a project opens: a document, an attachment,
the handbook and the project document, a work item's session log ([`work.md`](work.md)) and, on a
phone, the item alone ([`timeline.md`](timeline.md)). Its head holds the titles and, once what it
shows is read, its buttons: Pilot's job on it and its Undo where it has them, then Discuss, quoting
it ([`chats.md`](chats.md)). The head stands at its top however tall it is, its buttons level with
the title's first line, the title at weight 600. Under it stand the strip where what it shows has
one (below), the body and the foot. Its body keeps its scroll while what it shows is read again.
Where a read fails, its body reads "The document did not load." A document's address, a card's
block's, the handbook's and the project document's read what they open before the router swaps
it in (`readFirst`, `lib/screen-reads.ts`), the screen kept as it stood until then, the loading
bar telling of a wait past 200 ms ([`ui.md`](ui.md)), so that a tab or a view opens with its
document drawn; an open made while another's read is under way replaces it.

**Off a phone, a tab.** A document, an attachment, the handbook and the project document each open
as a tab in the timeline's place (`.stage`), the side panel beside it, at the timeline's width and on
the page's own colour, its head's and its foot's text in the timeline's column. A tab has no
backdrop, maximize or cross: the cross of its tab on the tab line closes it, and so does *Send
answers* (below); Esc closes no tab. Its body's scroll is kept while another tab shows, for as long
as the page, and set back once as its body's column first draws, a tab read to its end showing its
end; a tab closed and opened again starts at its top. While a tab shows, the timeline or a draft's
definition chat under it takes no focus (`inert`); the head, the tab line and the panel beside it
do. A tab takes the focus as it shows only where the focus would be lost, and gives it back as it
closes where it is lost then; a tab's cross gives it to the tab showing next.

**The tab line** (`DocTabs`, `components/projects/doc-tabs.tsx`, its model `useDocTabs` in
`hooks/use-doc-tabs.ts`) is the project head's last row while a document is open, a `<nav>` after the
head, and goes once the last one closes. The timeline's tab stands first, a draft's definition chat,
"Chat", in its place, and never closes; then a tab per document in the order they opened, each its
icon, its title cut short and whole in its tooltip, and its cross, the middle button closing it too;
*Close all* at the line's far right closes every tab and shows the timeline. Where the tabs do not
fit, the line scrolls, the tab showing scrolled into it. Closing the tab showing shows the one that
showed before it.

**The address follows the tab showing.** A document's, an attachment's, the handbook's or the project
document's address shows its tab, opening it at the line's end where it is not open, and a document
already open shows the tab it has; a document's tab shows again at the document's own address, not
at a block's or its box's; any other address of the project shows the timeline. Off a phone a move
between the project's addresses replaces the browser's entry rather than adding one
(`useTabReplace()`), so that Back does not move between tabs.

**Each project's line is kept in the browser** (`browser-state.ts`'s `lines`, [`ui.md`](ui.md)): its
tabs in the order they opened and the order they showed in, nothing once no tab is open; the scrolls
stay in the page. A reload finds the line as it was left. The project's row in the list, the
drawer's included, brings back the tab the project was left on, at the tab's address in the entry's
place, but for the row of the project on screen, which shows its timeline; every other arrival at a
project's own address, a fresh page included, shows its timeline, the line beside it (D151).

**The session log's popover.** Off a phone a work item's session log is the Overlay's popover, over
the tab showing, the timeline or a document's, which its cross, Esc and a press outside it close
([`work.md`](work.md)).

**On a phone, a view** pushed over the tabs ([`projects.md`](projects.md) has the views and Back):
the whole screen under the gold bar, over the project's head and the tabs, with no backdrop,
maximize or cross. Its head starts with the arrow back ("Back"), where the head's drawer button
stands, 8px from the left and the top. The arrow, Esc and the browser's Back take the view off,
showing what lay under it, another view or the tab; closing is Back, never a new entry. A view keeps
its body's scroll while another lies over it, in the page, by its history entry
(`use-phone-tab.ts`), and sets it back as it shows again once its read is drawn, so that Back from an
attachment shows its document where it was read; a view opened afresh or reloaded starts at its top,
and the session log's view keeps its own scroll, at its end. A view takes the focus as it opens, and
again when what it shows replaces what had it, and gives it back as it closes to what had it before;
the head, the tab and the tabs under it take none.

### A document

At a document's address (`DocumentOverlay`, read by `useItemDocument`):

- **The head**: the title, and under it the project's name, the step, the segment bar, *Done* or
  *Unsent*, and *Edited <time>*, a pencil in place of its word at 600px and below
  ([`timeline.md`](timeline.md)); then Pilot's job on the item, the read's `job`, in the form the
  timeline draws it ([`work.md`](work.md)), and the item's Undo while `done.undo` holds, before
  Discuss. On a phone a job queued, running, failed or stopped takes a row under the head's top line.
- **The body**: the summary as its lead, the attachments, then Pilot's questions to the writer
  (below), then the text as an inline document draws it, every block answered in place, every
  settled section collapsed and every held block its line, a claimed action reading "Pilot does it"
  and its work item ([`timeline.md`](timeline.md)), an open archive question its Archive and Keep
  alone, as the timeline draws them, and Pilot's dots while a turn saves it. A segment scrolls the body
  to its block, which flashes, its section opened first.
- **The foot**: on a done item, "Done · <stamp>", then " · Pilot", or the other person's name, where
  the signed-in person did not do it; on an open review, Reviewed; on an open document, *Send
  answers*, which closes its tab, on a phone its view, once the record holds the answers, each disabled while the
  project is archived (D012); on an open one-ask item or notice, nothing; and on a document that is
  Pilot's, no foot. Before them stands the Cancel where the document offers it (below).

**A document Pilot is working on** (`pilots_work` set, [`round-trip.md`](round-trip.md)) opens,
in its tab as in its view, read-only under the strip (`PilotStrip`, `overlay/pilot-strip.tsx`), which `Overlay` draws between
its head and its body: every block drawn whole and its controls disabled (`LockedContext`,
`timeline/locked.ts`), the options not chosen and the fields faded, and no foot. The strip, gold as
the gold bar
is ([`ui.md`](ui.md)), holds Pilot's mark and a sentence (`pilotsStripWords()`, `status-labels.ts`):

- `awaiting_run`: "Nothing of this document has been read yet.", or, read while another of its
  run awaits its read, "Pilot goes over this document once the other documents its run registered
  are read.";
- `pre_ruling`: "Pilot is pre-ruling this document: it settles what it may, and what is left comes
  to you.";
- `asking_writer`: "Pilot asked the writer about this document and waits for the reply, then goes
  over it again.";
- `doing`: "Pilot does what is open here in <work>; its Done comes with the result.";
- `researching`: "Pilot has a fact this asks about checked in <work> before it rules.";
- `waiting_on_answer`: "Pilot waits on your answer to <document> before it goes on with what is
  open here.";

<work> linking the work item and <document> the run's document; while `pre_ruling` it links
nothing, and the pass's job in the head opens the pass's session log. While `pre_ruling`,
`asking_writer`, `doing` or `researching` it ends in *Stop and take over*, the gold bar's button
with a square, which asks nothing first: it calls the take-over (`POST take-over`,
[`round-trip.md`](round-trip.md)), stays disabled from the click until the document reads back as
the person's, and a refusal is a toast in the API's words. On a phone it wraps under the words, at
the right. A document awaiting its read draws its head, titled by its file's name, the strip with
no Stop, and "Its text shows here once Pilot has read it." as its body.

**The Cancel** (`RunCancel`, `overlay/run-cancel.tsx`), on a document whose `cancel` is set
([`timeline.md`](timeline.md)), opens the foot, before *Send answers* or Reviewed: a first row, "Pilot
asks this as part of its work on <document>.", each document of `takes_back` a link to its
address, joined with "and", then the button "Cancel and take back “<name>”", each block named by
its section's `heading`, else by its document's title, the names joined with "and" and none twice;
"End that work: this document and every other it put to you close, and what it holds is yours
again" its tooltip. It asks nothing first, and offers no Undo after: it calls `POST cancel`
([`round-trip.md`](round-trip.md)), disabled while the project is archived and from the click until
the document reads back as done. Its words wrap at their spaces.

**Pilot asked the writer** (`clarification.tsx`). Over a registered document's text stands the box
of Pilot's questions to its writer, a section per pre-ruling pass that asked about its blocks, the
item's `clarifications` ([`timeline.md`](timeline.md)): Pilot's avatar and "Pilot asked the writer
· <stamp>", the stamp when the pass first asked, and " · replied <stamp>" once the reply came, then
each question, muted, after its block's local id. Once the reply comes, each question's part stands
under it where the reply kept every heading asked for (`split`), else the reply whole under the
questions, as Markdown. While the clarification run is in flight (`asking_writer`), each question of
the last section reads "Awaiting the writer’s reply" under it; where the run's turn ended with no
text, the questions stand alone. The document's clarification address opens the document at the box,
and an asked block's mark in the opened document goes to it there, the address unchanged; either way it
flashes (`useClarificationBox`, `overlay/clarification-box.ts`).

A registered document whose read failed ([`round-trip.md`](round-trip.md)) draws its head, titled
by its file's name, "The document did not load." as its body, and Reviewed in its foot. Its
attachments open at their addresses.

Opened at a card's block address, it goes to the block once its body draws it, and flashes it. Open
on a done line shows the document as Done fixed it (above), with no *Edited <time>* and no dots: those
tell of the text as it stands. A document done another way, by an answer, a turn's end or Finish,
shows its text as it stands, with both. An address naming the opening, an item of another project or
no item reads "The document did not load."

### An attachment

At an attachment's address, the head is its clip and title over "Attachment of “<item>”", or
"Attachment of the draft" for one hung on nothing, and there is no foot. Off a phone it is a tab of
its own, and where its item is a document or a review, the document's title in its head is the link
to it, opening the document's tab. On a phone, at its address under its document's, where the
view's own arrow is Back, the document's title in its head is the link to it, Back to it where the
document's view lies under the attachment's, opened at its address or at one of its blocks'. The
body goes by the type it was stored with (`attachment-overlay.tsx`):

- Markdown (`text/markdown`), rendered read only, its front matter left out and a fenced ask shown
  as plain code: an attachment is reader's material, never an item;
- a raster image, inline from the stream;
- SVG, as an image of its text, read from the stream that serves it as a download, so that its
  script never runs;
- other text but HTML, in a monospace block;
- anything else, its title, "<filename> · <size>" and Download, which opens the stream.

An attachment its item does not carry reads "The document did not load."

### The handbook and the project document

The Documents tab's first row opens the project document and its second the handbook (below), each
as a tab of its own, on a phone a view (`HandbookOverlay`, `ProjectDocumentOverlay`, read by
`useHandbook` and `useProjectDraft`). Each is read only, with no foot. Its head is the icon
and the text's title, else "Handbook" or "Project document", over "<project> · Handbook" or
"<project> · Project document"; its body is its prose as Markdown and its asks, in their order, or
*Empty* while it has nothing past its title, then Pilot's dots while a turn saves it. A fenced ask
in either has no item to answer it, so it reads only (D072), drawn as the timeline draws a settled
ask (`DocumentBlock`, `components/timeline/block.tsx`). An answered ask is closed, with its answer,
who gave it and *In the chat* where it was given there, and with no chevron and no Discuss. An ask
left open at Create stands open, its controls disabled. A failed read, a draft's handbook included,
reads "The document did not load."

**A link to the project's attached material.** In either, a link to a path in the project's
`attachments/`, as written, a leading `./` and escapes allowed (`linksMaterial` and `pathOfLink` in
`hooks/use-timeline.ts`), is `MaterialLink` (`project-document-overlay.tsx`, through `Markdown`'s
`materialLink`). It opens the attachment where it hangs, at its address under its item's, the
opening's for a draft's material after Create, or under the project's where it hangs on nothing: off
a phone a tab of its own, adding no entry, on a phone a view pushed over this one. A path naming no
attachment is its words alone, and every other link opens in a new browser tab.

### Live

What a tab or a view shows is read again on its project's `project_changed`, but for the one the
page's own write committed, on every rise of the event stream, when the window regains focus and
after the page's own writes ([`timeline.md`](timeline.md)). A save of the handbook or the project document raises one where it
changes the published text or makes its session the one writing it, and a turn's end raises one for
each document it lets go ([`engine.md`](engine.md)), so an open document shows Pilot's new text, and
its dots come and go, as they happen.

## The side panel

`Panel` (`components/panel/panel.tsx`) stands beside the project's head and timeline, or the tab
showing: a tab strip, Chat first, with the unread dot ([`chats.md`](chats.md)), then Documents, with
its count. Off a phone it is always open, at every width, the narrow one included, and has no cross:
nothing closes it, and nothing lies over it. Its head stands as tall as the project's head with no
tab line under it, its tab on the name's baseline. Discuss and *In the chat* show its Chat tab. A
draft's panel stands beside its definition chat, with Draft in Chat's place, and an ask a quote or an
effect line goes to shows the Draft tab at it. A draft's Discuss and *In the chat* go to its
definition chat instead ([`chats.md`](chats.md)).

**Its tab, each project's own.** A project's panel shows the tab the person last left it on, kept
in the browser (`usePanel`, `browser-state.ts`'s `panels`, [`ui.md`](ui.md)), so switching projects
brings each back as it was; a project not opened before shows its first: an open project's Chat, a
draft's Draft. A remembered Chat reads as Draft for a draft and Draft as Chat for an open project,
so a panel on the Draft tab at Create project shows the Chat tab after it.

**Its width** is dragged at the divider at its left (`PanelDivider`,
`components/panel/panel-divider.tsx`, a `separator`), in a project and a draft alike, or moved 16px
by an arrow key while the divider has the focus. The browser keeps one width for every project's
panel, in pixels, 420 until dragged, and one for every draft's, as a share of the window, half until
dragged, so that it stays half on another screen; dragging one leaves the other (`panelWidths`,
D148). Whatever is kept, the panel stands at least 320px wide and leaves at least 440px to its left,
for the timeline's column, a draft's chat or the tab showing; a width held in for want of room stays
kept as it was. The divider sets `--panel` on the project's page (`.project`), which the panel's
width reads.

**A phone**, 900px and below, has no panel beside the timeline: its Chat, Documents and Draft tabs
are among the tabs at the bottom, each between the head and the tabs, drawn without the panel's head
(`PhonePanel`), and neither the tab kept per project nor the width is read or written there
([`projects.md`](projects.md)).

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
escapes decoded), opens that attachment, off a phone in a tab of its own, on a phone a view. Every other link, ticket id, repo and
environment in the draft reads as plain words.

### The Documents tab

`documents-tab.tsx`, from the project's timeline and its project document, read as one
(`usePanelDocuments`):

- **The project document** first: its title, the text's, else, and until it is read, "Project
  document", over "Project document".
- **The handbook** under it, on a phone (D125) and off one alike, the project's head having no
  button for it (D149): its title, the text's, else, and until it is read, "Handbook", over
  "Handbook".
- **Attachments**, newest batch first, a batch being the files hung in one call. A batch of one is
  its title over "<item> · <stamp>"; a batch of several is a folder row, the last directory their
  sources share, else "N files", over "<item> · <stamp>", with each file under it, its title over
  its file name, a folder's file named by its path relative to the folder. With none: "None yet. A
  session attaches reader’s material here: a design, a survey, a log."
- **In the timeline**: the timeline's documents and reviews, newest first, each its title over
  "<Open | Unsent | Done> · <stamp>", *Unsent* as the timeline reads it. With none: "None yet."

Every row opens at its address, off a phone in its tab, on a phone a view. While either read is under way the
two headings stand with nothing under them, and while either's latest read failed, "The documents
did not load." stands in their place, under the project document's row. The tab's count is the
attachments and the documents, the project document left out, and stands only once both are read.

A draft's Documents tab lists the attachments alone, what Pilot attached so far in its definition
chat, hung on nothing (`unhung_attachments`, [`timeline.md`](timeline.md)), a row's line its stamp:
its project document is its Draft tab, and it has no timeline. With none: "None yet. Pilot attaches
here what you point it at in the chat: a card, a handover, a design."

## Addresses

`<project>` is the project's address, its slug or a draft's `draft-<number>`, its id opening it
too ([`projects.md`](projects.md)).

| Address | Opens |
|---|---|
| `/projects/<project>/documents/<item>` | the item's document |
| `/projects/<project>/documents/<item>/clarification` | the item's document, at the box of Pilot's questions to its writer |
| `/projects/<project>/documents/<item>/attachments/<attachment>` | the attachment, its document a link in its head; on a phone a view over the document's |
| `/projects/<project>/items/<item>/attachments/<attachment>` | the attachment; on a phone a view over the timeline where it stands |
| `/projects/<project>/attachments/<attachment>` | the attachment, wherever it hangs: a draft's, on nothing, and the same one once Create hangs it on the opening |
| `/projects/<project>/handbook` | the handbook |
| `/projects/<project>/project-document` | the project document |

The routes draw nothing of their own: the project's route (`routes/_shell/projects/$address.tsx`)
draws from them, off a phone, the tab showing, and on a phone the view, as it does from a card's
block address ([`timeline.md`](timeline.md)). An attachment's chip on the timeline, the done line's
indicator and a row of the Documents tab open its address under its item's, and its chip in an
opened document the one under the document's; a draft's Documents tab and its links open the one
under the project's. Closing a tab shows, at its address, the tab that showed before it; on a phone
closing a view is Back. Another project's address draws the project's screen afresh, closing whatever
the last one opened, its session log's popover among them, while its tab line and its panel's tab
come back as that project left them.

## Testing it

The reads are pinned in `TestItemDocument`, `TestProjectDocument` and `TestPilotsWork`
(`backend/tests/services/test_timeline_service.py`), `TestGetItemDocument`
(`tests/api/test_items.py`) and `TestGetProjectDocuments` (`tests/api/test_projects.py`); the store
and the stream in `tests/engine/test_attachments.py`, `tests/services/test_attachment_service.py`
and `tests/api/test_attachments.py`; a draft's answers in `tests/services/test_draft_service.py`.
The browser suites are `frontend/tests/timeline/overlay.spec.ts`, `attachments.spec.ts` and
`project-documents.spec.ts`, and `tests/projects/doc-tabs.spec.ts` (the tab line, its addresses and
what the browser keeps of it), `panel.spec.ts` (its width among the rest), `draft-panel.spec.ts`
and, for the views on a phone, `phone-views.spec.ts`; a document's tab that waits for its document
in `tests/shell/screen-switch.spec.ts`.

A spec hangs files on an item with `projects.attach(itemId, files)`, or on nothing in a draft with
`projects.attachToDraft(projectId, files)`, saves the handbook or the project document with
`projects.saveProjectDocument(projectId, role, text)` and answers an open project's with
`projects.answerProjectDocument(projectId, role, block, answer, handle)`, over the record's testing
endpoints ([`projects.md`](projects.md)), on a project made with a session. The `overlay` fixture
(`tests/support/page-objects/overlay-page.ts`) opens a document's address (`open`), the handbook or
the project document (`openProjectDocument`), and reads what opens, its head, body and foot, the
head's Discuss, Pilot's job (`job`: `root`, `pulse`, `retry`) and Undo (`undo`) among them, an
attachment's link to its document (`documentLink`), a link to attached material (`materialLinks`)
and on a phone the view's arrow back (`back`), its clarification box and sections
(`clarificationBox`, `clarification(n)`, pinned in `tests/work/clarification.spec.ts`), the strip
(`strip`: `root`, `text`, `link`, `stop`), the unread body (`unread`) and the Cancel (`cancel`:
`line`, `links`, `button`), pinned in `tests/work/registered.spec.ts` and `claimed.spec.ts`; the
`docTabs` fixture
(`doc-tabs-page.ts`) the tab line (`first`, `document(id)`, `attachment(id)`, `tab(key)`, `closeAll`,
`keys()`), a spec closing a document's tab by `docTabs.document(id).close`; the `panel` fixture
(`panel-page.ts`) reads the panel, its Documents tab with the handbook's row (`handbook`), a draft's
Draft tab (`draft`, `draftBlock(id)`) and the divider (`divider`, `drag(by, along?)`, `width()`),
and the `chat` fixture its Chat tab ([`chats.md`](chats.md)). On the default 1280px viewport the
panel stands on the Chat tab, a draft's on the Draft tab. Storage is per Playwright context, so a reload or a `page.goto` of a
project finds the tabs its test opened, and the next test none. A draft's page draws no timeline, so `timeline.open()`, which
waits for the timeline's read, never returns on one: a spec opens a draft with
`projectList.open(id)` or `projectHead.open(id)`.
