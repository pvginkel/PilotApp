# The chats

A project's chat is how a person reaches its brain: a headless Claude Code session in the store
environment, which a message starts, briefed, and which takes the messages after it while it is
open. A chat closes after a quiet spell, or when its project finishes, reopens or is archived, and
the next message starts the project's next chat. This page is the chat as built: a message and the
way it goes, the chat's start in the store and its brief, what the server puts before a message's
words, the server's follow-up turn, the Stop of Pilot's answer, the close, the chats as a person
reads them, `chat.md`, the chats as the brain reads them, and the chat's screens: the side panel's
Chat tab, its composer, Discuss, the unread dot and *In the chat*. What the brain may do through
its tools is [`mcp.md`](mcp.md)'s, the start, the send and the relay that carry a chat's turns are
[`sessions.md`](sessions.md)'s, the panel's shell is [`documents.md`](documents.md)'s, and the
tables are [`record.md`](record.md)'s. The skill the brief opens with is PilotProjects'
`.claude/skills/chat/SKILL.md`.

| Service | Does |
|---|---|
| `ChatService` (`chat_service.py`) | a person's message: sent to the project's open chat, or the chat started with it; and the Stop of Pilot's answer |
| `BriefService` (`brief_service.py`) | the chat's brief, the follow-up turn, and the server's lines after a worker's brief ([`mcp.md`](mcp.md)) |
| `ChatCloseService` (`chat_close_service.py`) | a chat's close: at Finish, Reopen and Archive, and on the timer `chat-close` |
| `ChatReadService` (`chat_read_service.py`) | a project's chats in their order, and a person's place in them |
| `session_scope.py` | what a brain session's create is handed: its box, its surface and its `PILOT_PROJECT` ([`sessions.md`](sessions.md)) |

All are in `backend/app/services/`; `chat.md` is the engine's `ViewService.chat`
(`backend/app/engine/views.py`).

## A message

**`POST /api/projects/<id>/chat/messages`** `{words}`, behind the API's `editor` gate, sends Pilot a
message as the signed-in person, the words verbatim, and answers `201` `{chat, seq, state, error}`:
the chat's id, which is its Session's, the message's Turn's number in it, the Session's state, and
the error of a send the controller failed, the Turn ended with it ([`sessions.md`](sessions.md)).
It is a `400` with no words, a `404` for an unknown project, and a `409` with the reason for a
caller who has not chosen a handle, in a draft ("its project is a draft": a draft's chat is its
definition chat, which takes no message here), in an archived project ("its project is archived"),
while the chat's start is under way or held ("its chat is starting"), while a turn of it is in
flight ("a turn is in flight", the controller's `409 session-busy`, or "a turn of its chat is in
flight"), and with no controller or no store environment configured.

The message is a Turn of the project's chat: its author the person, its `words` the words as they
came, quote tags and all, and its `message` what goes to the session, the words with what the
server puts before them ([below](#before-the-words)). Its `send` record stands in its place among
the chat's records. A quote travels in the words as a tag, the closing tag repeating the attribute
and the quoted thing's title between the two:

- `<quoted_item id="<item id>">…</quoted_item id="<item id>">`, an item;
- `<quoted_block id="<item id>/<local id>">…</quoted_block id="…">`, a block;
- `<quoted_path path="<path>">…</quoted_path path="<path>">`, a file of the project's folder by its
  path there (D070): `handbook.md`, `project.md`, or an attachment's
  `attachments/<batch>/<filename>`, the batch from 1 and the filename keeping the slashes of a
  folder it came in, with no empty, `.` or `..` segment. To the server, as to the UI, a tag naming
  any other path is no quote.

The Turn's quote is what the first quote tag in the words names: the Item or the Block of the
project, and none for a path's tag, nor for a tag that names neither, an unknown or malformed id or
another project's. A path's quote lives in the `words` alone. The brain resolves a quote itself,
from the tree, a path's from the project's folder; the server inlines nothing.

Which way a message goes is the project's open chat's to say, read with its Session:

- **None open**: a Chat, kind `project`, is opened with a Session of kind `chat`, in no environment
  until its start takes the store, its `cwd` the store repo's root, `/work/PilotProjects`, and its
  model and effort `BRAIN_MODEL` and `BRAIN_REASONING_EFFORT` (below). Its Turn 1 is the chat's
  brief followed by the words, and the Session starts through the gate (below). A project has one
  chat open at a time.
- **Open and up**, its Session `idle`, `running`, `ended`, or `stopped` with a conversation: the
  words go to it as a Turn through the relay's send, which first creates the controller session
  again where it is gone ([`sessions.md`](sessions.md)). The chat's Session is locked from before
  the send to the commit, so no close and no stop comes between them: a message that finds the chat
  closed meanwhile starts the project's next chat, and one that finds its project archived is
  refused.
- **Starting or held**: refused, "its chat is starting".
- **Failed, or stopped before its brief went out**, as the chat's Stop during its start leaves it:
  the start is made again in the same Chat, in a headless session of its own, its controller session
  cleared, its next Turn carrying the brief and the words; while the stopped Turn is still ending,
  "a turn of its chat is in flight". No close is a failure or a stop, so the Chat stays the open
  one.

A start is written under the project's row, locked as a change of its standing locks it
([`projects.md`](projects.md)), then the chat's Session's: two starts of one project's chat, or a
start and a Finish, go one after the other, the second start "its chat is starting".

**A finished project's chat reads only.** A message starts its chat as it does an open project's,
and that chat's create is boxed with nothing under `/work` it can write, the store repo read-only
and no folder writable, its project's included, and is handed no `pilot-store`, whose every tool
changes the record; its home directory stays writable, and the fleet's tools stay, as for every
brain session. Its brief says the project is finished. **An archived project** takes no message.
Archive closed its chat (below), so the refusal guards a send racing the archive; after Bring
back, which starts nothing, the next message starts a chat, briefed with the project's state.

## The start in the store

The chat's Session passes the gate as a work item's does ([`sessions.md`](sessions.md)), held while
the controller is unreachable, never for the pause, and taking no slot
(`SessionStartService.start_brain`); it is refused with no controller or no store environment
configured (`STORE_ENVIRONMENT_ID`, [`sync.md`](sync.md)). Its start loop takes the store: the
store's Environment row made from the controller's report where Pilot has none yet, the Session's
Environment written under its lock with "Starting <store's name>…", and the store started and its
settle awaited, as a stopped store is started on demand ([`controller.md`](controller.md)). The
store is exempt, so no timer of Pilot's stops it again. Then "Creating the session…", and the
create as `scoped_create` derives it ([`sessions.md`](sessions.md)): the cwd read-only, the
project's folder, `/work/Projects/<folder>`, the one folder under `/work` it writes, `PILOT_PROJECT`
naming that folder, and `pilot-store` handed to it ([`mcp.md`](mcp.md)).

A create boxed with a folder to write that the controller refuses `422` meets that folder not on
disk yet, as `pilot-sync` writes it a moment after the record changes: it is made again every 2 s
until 60 s have passed since its first refusal, and then fails the start, as any other refusal
does, `409 capability-unavailable` (the store's pod composed without the sandbox) among them. A
finished project's create has no folder to wait for, and its `422` fails the start at once. Once
created, the Turn is sent, and its relay records the turn.

## The brief

The brief is the first Turn of a chat's session (`BriefService.project_chat`), Markdown, its blocks
a blank line apart; a line that does not hold is left out, never written as "none":

- `/chat`, the skill line alone, which loads PilotProjects' chat skill and hands it the rest;
- `Pilot's brief · the project's chat · project "<name>" · /work/Projects/<folder> · <UTC stamp>`,
  and `a finished project's chat` for a finished project's;
- in an open project, `Auto pilot: on — the granted column holds for this session
  (rules/grants.md).` or `Auto pilot: off — the granted column asks for this session
  (rules/grants.md).`, the switch the session keeps, then, while the project is paused, `The project
  is paused since <stamp>: anything you start is held until it resumes — say so.`; in a finished
  one, `This project is finished (<stamp>): you read only — no `pilot-store`, nothing under `/work`
  you can write. Answer from the tree, the records and the fleet tools; what you would change, say
  so and name who can.`, the stamp its latest `finished` transition's;
- in an open project, ``Open plan notes, by summary (the content and the blocks a read away in
  plan.json; `pilot.py plan note list`):``, then a line per open note, `- <task id> "<title>" ·
  <note id>: <summary>` or `- the plan · <note id>: <summary>`, the tasks' in the plan's order
  and then the plan's own; then `Deferrals without a home (a note names none of these blocks —
  write one, or answer the block anew in a new item):` and a line per such deferral, as the hook's
  check prints it ([`sync.md`](sync.md));
- once a chat of the project has closed, `Earlier chats of this project are in chat.md; the latest
  closed <stamp>.`;
- `The message, from <handle> (member):`, or `(not a member):`, then the words verbatim, which the
  brief ends with.

No brief carries the handbook: the chat skill reads `handbook.md` before it acts (D058).

## Before the words

A message sent to the open chat goes as the person's words, with up to two things before them.

**The author's name.** Where the chat's previous Turn with an author is another person's, the line
the brief ends with names this one, `The message, from <handle> (member):` or `(not a member):`,
then a newline and the words (`BriefService.message_from`). The previous author is that of the
chat's latest Turn with one that reached the brain: a server's Turn has no author, and a Turn whose
send failed never went out, so a message retried after a failed send is named again. A message
without the line is from the person the latest such line named, the brief's included, and the chat
skill records a ruling for that person.

**The handbook's notice.** Where the project's handbook was published later than the chat's latest
Turn that reached the brain was sent, the server's notice goes first, a blank line before what
follows it (D052): a Turn whose send failed never went out, nor its notice, so a message retried
after a failed send carries the notice again.

```
<store_notification>
The handbook (handbook.md) changed since your last turn.
</store_notification>
```

The notice is counted once the send went out, `pilot_chat_handbook_changed_total{project}`, by the
project's id. A start's Turn carries the brief instead, and the skill reads the handbook then
anyway. The store's saves name no session ([`sync.md`](sync.md)), so a handbook the chat edited
itself counts as a change too.

Either way the Turn's `words`, and so its `send` record, are the words alone.

## The follow-up turn

A brain session's turn that ends with a save of its own still held, the paths the engine's turn end
returns ([`engine.md`](engine.md)), and that leaves the Session `idle`, gets a turn of the server's
(`RelayService._follow_up`, `BriefService.follow_up`): no author, a line per held path,
``Your save of `<path>` is held: `<path>:<line>: <message>`, `…`.``, the path from the tree's root
and each parse fault as the hook's check prints it (`<path>: <message>` with no line), then `Fix
it and end your turn.`. It is written in flight in the transaction that ends the turn, the Session
staying `running` with it, and the relay sends it once that commits. A work item's turn gets none.

A turn gets one follow-up, and a follow-up gets none (D065): one that itself ends with a save
still held leaves that save held, its item showing its last published text, and the next turn of
any session of the project meets the fault through the hook ([`sync.md`](sync.md)). A save is a
session's when its ingest names that session, and the store's sync names none, so a turn of a
session in the store ends with no save of its own held, and its follow-up comes only where an
ingest named the session.

## Stopping Pilot's answer

**`POST /api/projects/<id>/chat/stop`**, no body, stops Pilot's answer in the project's open chat
where it is, as the signed-in person, whoever sent the message: one conversation, one turn
(`ChatService.stop`, `SessionStartService.stop_chat`, a work item's Stop's own path,
[`sessions.md`](sessions.md)). A turn in flight is interrupted once the request commits, the
conversation kept, so the next message continues it; a start held at the gate or under way ends its
Turn unsent, and the next message starts the chat afresh in the same Chat, briefed (above). Its
Session is `stopped`, and the chat closes on its timeout as after any turn. A controller that does
not answer lets the turn run out. Until the interrupted turn has ended, a message is refused as one
sent while a turn is in flight.

It answers `200` the chat as the list gives it (below), `answering` false. It is a `404` for an
unknown project, a `409` for a caller who has not chosen a handle, and a `409` "Cannot stop Pilot in
<project> because …" where "no chat is open", "it is not answering", "it was stopped already", "its
chat failed to start" or "its chat's session has ended".

## The close

A chat closes for one of four causes, `Chat.closed_at` and `close_cause_code` written together, and
is never sent to again: the next message starts a chat of its own.

- **`timeout`**: the timer `chat-close`, on each round of the scheduler ([`jobs.md`](jobs.md)),
  closes every open project chat whose Session's last turn ended `CHAT_CLOSE_TIMEOUT` ago or more,
  with no Turn in flight. Each in a transaction of its own under its Session's lock, skipping one
  another transaction holds, a message's send among them: its controller session, where it has one,
  ended first, a `404` or a `409` counting as ended, and its Session `ended`, then the chat closed.
  A controller that does not answer leaves the chat open for the next round. A definition chat
  never closes by timeout.
- **`finished`**: Finish closes the project's open chat in its transaction, after it stopped the
  project's Sessions, a turn the chat had running among them ([`projects.md`](projects.md)).
- **`reopened`**: Reopen does the same for a chat opened while the project was finished, and stops
  that chat's running turn first, as Finish stops one (D068), so that the close stays the chat's
  last record and the next message starts a chat that writes. An idle chat needs no stop: a closed
  chat is never sent to.
- **`archived`**: Archive closes the project's open chat in its transaction, after it stopped the
  project's Sessions, as Finish does, so that an archived project has no chat open. Bring back
  starts none: the next message after it starts a chat under the project's state then.

A chat's box is fixed at its create, so a close at a change of the project's state keeps every
chat in the state it was opened under. Finish, Reopen and Archive call no controller: the chat
keeps its controller session, idle or interrupted, and nothing sends to it again.

The close's `server` record, `{"type": "closed", "cause": <cause>}`, is the chat's last. The close
writes it when no Turn of the chat is in flight, and otherwise the end of that Turn does, as the
relay records the turn a stop interrupted, so its `at` can be later than `closed_at`. A chat's
open and its close move `chat.md` and raise `ProjectChanged` ([`engine.md`](engine.md)).

## The chats read

**`GET /api/projects/<id>/chats`** answers `{chats, read_at, unread}`: the project's chats, the
definition chat first where one exists, then the project's chats in the order they opened, each
`{id, kind, opened_at, closed_at, close_cause, answering}`, open or closed with its cause; and the
caller's place in them, `read_at` null for a caller with no handle. `answering` is whether Pilot is
answering in the chat, its Session `held`, `starting` or `running`, the states the Stop ends: false
once that ends, however it ends, and for a closed chat; each move of it raises `ProjectChanged`, as
every move of a chat's Session's state does ([`work.md`](work.md)). A chat's records are its
Session's, read and followed as any Session's are ([`sessions.md`](sessions.md)).

**`PUT /api/projects/<id>/chat/read`**, no body, says the signed-in person has seen the project's
chat to its end now, on whichever device: their Chat Read, one per person and project, written at
the transaction's start, the records' own clock. It answers `{read_at, unread}`, and is a `409` for
a caller who has not chosen a handle. `unread` is whether Pilot replied after `read_at`, or at all
while there is none: a reply is a main-thread `assistant` record with text of one of the project's
chats. The place is the project's, not a chat's, so the next chat keeps it. A Chat Read's write
emits nothing live; a reply reaches the browsers through its turn's end, whose state move raises
`ProjectChanged`. The chat's routes are behind the API's `editor` gate, and `404` for an unknown
project.

## `chat.md`

Every syncing project's folder holds `chat.md`, read-only ([`projection.md`](projection.md)): the
project's chats as the brain reads them, rendered from the records (`ViewService.chat`). Its
paragraphs stand a blank line apart:

- first `<!-- a projection of the record; an edit is reverted — the timeline is edited through the
  tools -->`, which a folder with no chat holds alone;
- per chat, in the list's order, `## Chat · opened <UTC stamp>`;
- a person's message as `**<handle>** · <stamp>`, then their words verbatim, quote tags as sent;
- Pilot's run as `**agent** · <stamp>`, then each main-thread text block of its `assistant`
  records, and each effect's line, `<verb> · <label>`, where its call ran: after the `assistant`
  record that holds its tool-use id, whichever was written first, else in its own record's place
  ([`mcp.md`](mcp.md));
- last, `Closed <stamp>`, the stamp the brief's "the latest closed" gives, or `Open`.

The server's own turns, the brief's frame and the follow-up among them, are not in it: Pilot's
reply to a follow-up continues its run. A record of a chat's Session that the file shows, a `send`,
an effect, Pilot's text or a main-thread tool call, moves it in the record's own transaction
(`SessionRecordService.append`, through `ViewService.recorded`); a record that shows nothing moves
nothing, and no work item's record moves it. A render reads three kinds of record per chat,
filtered, a page at a time.

## The Chat tab

The side panel's first tab, the one it opens on ([`documents.md`](documents.md) has the panel's
shell), is the project's chat (`ChatTab`, `frontend/src/components/chat/chat-tab.tsx`), from the
chats read (`useProjectChats`, `hooks/use-chats.ts`), read again when the window regains the focus
and on `project_changed` ([`timeline.md`](timeline.md)).

- **What it shows.** The project's latest chat: the open one, or with none open the latest closed
  one. Above it, "The chat before · <day>" loads that chat above what is in view, the line at the
  top of the view kept in its place until the reader's own wheel, touch, click or key; a chat that
  opens while the tab shows comes in below. Nothing stands in it while the list's read is under
  way, and "The chat did not load." while its latest read failed. A project with no chat reads "Ask
  Pilot about this project: how a session is going, what an item means, a change to the plan.
  Discuss on an item quotes it here."
- **A chat** (`chat-section.tsx`) streams its records from the first, as the session log does
  ([`work.md`](work.md)), drawn as `buildChatView` places them: each person's message, Pilot's
  reply to it, the working cue while Pilot answers, and the phantom of the text under way; a date
  divider over its first message and wherever the day turns; and "Chat closed · <time>" where it
  closed, its cause not shown. What comes live fades in, what loads does not. A turn its records
  leave open ends once the list says Pilot no longer answers. Every viewer streams the chats it
  shows, so another member's message and Pilot's reply to it come to them as to the sender.
- **A person's message** (`person-message.tsx`) stands on the right in the primary's tint, its
  words as written, ticket ids, repos and environments linked (`LinkedText`, [`ui.md`](ui.md)), not
  Markdown; a quote it opens with is a line over it, and one inside it a chip where it stands; under
  it the time and the avatar, another person's name before the time.
- **Pilot's reply** (`PilotReply`, `pilot-reply.tsx`) is a reply's body as the session log draws
  it, bare in the column, the cue under it while its turn runs; an ended turn closes on Pilot's
  avatar and its time, " · Stopped" after an interrupted one and " · Failed" after a failed one.
- **It sticks to its end** while it grows (`useStickyBottom`): only the reader's own scrolling up
  lets go, and their message sent from the composer, or a Discuss, takes it back to the end.

On a phone it is the same column, the panel being the whole screen.

**The composer** (`composer.tsx`) stands under the transcript: the growing text field (`TextField`,
[`ui.md`](ui.md)) to five lines, Enter breaking the line and Ctrl+Enter, Cmd+Enter on a Mac,
sending, and Send beside it, disabled while the field is empty; the field takes no typing while the
message is on its way. A message with no chat open starts one, which the tab shows where it opens.
While Pilot answers in the latest chat (`answering`), Stop stands in Send's place, in every member's
composer whoever sent the message, and the field stays open for the next message. Neither button
takes the focus from the field, and Send and Stop put it back there for a keyboard press. Its words
are kept in the browser until sent, by the project (`chat/<project id>`, [`ui.md`](ui.md)); a
refused send keeps them, the refusal the query client's toast in the API's words. Each answer writes
whether Pilot answers into the list as read. In an archived project the field and Send are disabled
under "The project is archived: bring it back to message Pilot."

**Discuss** (`DiscussButton`, `discuss-button.tsx`) quotes what it stands on into the chat. It ends
an open item's head, every kind's, and a document's block's head, where a one-ask item's is its
item's; stands before a done line's time; and stands in the overlay's head of a document (the item),
an attachment, the handbook, the project document (by path) and a session log (its work item). Its
quote's label is an item's title; a block's "<ask> · <item's title>"; a file's title as read, else
"Handbook" or "Project document"; an attachment's title, its path as the timeline gives it. A click
puts the quote in the project's composer (`hooks/use-discuss.ts`) and opens the panel on the Chat
tab, on top: the quote stands over the field as a chip, with its remove, the field takes the focus
and the transcript goes to its end. The message goes as the quote's tag, a space and the words, and
the chip goes once the server took it. The quote is kept in the page alone, by the project: a reload
keeps the words and not the quote. The head's Discuss ([`projects.md`](projects.md)) opens the Chat
tab with nothing quoted, dropping a quote the composer held, and closes the panel where the Chat tab
shows.

**The unread dot** (`useChatDot`) stands on the head's Discuss and on the Chat tab while the list's
`unread` says Pilot replied after the person last saw the chat to its end, and this page does not
show it at its end. At its end means the Chat tab shown, its panel not under the overlay, its
transcript pinned to its end, and the page visible; there, while the list says a reply is unread,
`useChatSeen` marks the chat seen (`PUT …/chat/read`) and writes the answer into the list, so a
reply watched as it arrives leaves no dot. A failed mark is made again once the chat is shown again.
No other browser hears of the mark: each drops its dot at its next read of the list.

***In the chat*** (`InChatButton`, `in-chat-button.tsx`), the chat icon and "In the chat", stands on
a block whose answer was given in the chat (`in_chat`, [`timeline.md`](timeline.md)): in its head
before the time, the icon alone at 600px and below, and in a one-ask item's done line after the
answer, kept whole. A click (`hooks/use-in-chat.ts`) opens the panel on the Chat tab, on top, with
nothing quoted. The tab loads the chats before until the one holding the answer's record, lets go of
its end, and once that chat's stream has read to the record scrolls the person's message of the turn
that holds it, the latest at or before it, into the middle of the view, flashes it and holds it
there until the reader scrolls. On its way there the chat is not at its end, and so not seen.

## Settings and metrics

| Setting | Default | |
|---|---|---|
| `BRAIN_MODEL` | `opus` | the model of every brain session, the chat's and every job's |
| `BRAIN_REASONING_EFFORT` | `xhigh` | their reasoning effort |
| `CHAT_CLOSE_TIMEOUT` | 3300 | the seconds after its last turn ended at which an open project chat with no turn in flight closes, `cache_expiration_ttl`'s 55 minutes; above 0 |

The brain runs on one model and one effort, for the chat and every job alike, each a setting of the
deployment (D066): no chat and no task has its own, and the brain has no tool to change its own; it
starts sub-agents where it wants another model. Each stage's values set the three
([`deployment.md`](deployment.md)). The chat's counter is
`pilot_chat_handbook_changed_total{project}` (above).

## Testing it

The tests are in `backend/tests/services/` (`test_chat_service.py`, `test_chat_close_service.py`,
`test_chat_read_service.py`, `test_brief_service.py`, `test_session_scope.py`, and the brain's
start and the chat's Stop in `test_session_start_service.py`, its follow-up turn in
`test_relay_service.py`), `backend/tests/api/test_chats.py` and `backend/tests/engine/test_views.py`
(`TestChatView`); `backend/tests/support/chats.py` writes a chat's records. On the fake controller
([`controller.md`](controller.md)), a boxed create needs its cwd and each folder it writes on the
environment's tree, so a chat's start in the store needs a file under `/work/PilotProjects` and one
under the project's folder (`put_file`), or its create is `422`.

The browser suites are `frontend/tests/chat/` (`chat-tab.spec.ts`, `composer.spec.ts`,
`discuss.spec.ts`, `in-chat.spec.ts`), and `tests/timeline/quotes.spec.ts` for the chips. The
Playwright backends start every chat in the store environment of their own fake,
`playwright-store` (`STORE_ENVIRONMENT_ID`, `loadAppBackendEnv()`), which the `chats` fixture
(`frontend/tests/support/chats.ts`) puts there once per backend with the store repo and the
project's folder on its tree. `chats.start(project, words, other?)` sends a message and answers
`{chat, session}` once the store's session works, and `chats.opening(project)` readies the store
for a message sent from the composer and answers a wait for its session; the spec plays a turn
with `controller.play` and `finish` on `chats.store`. `send`, `working(session)`, `idle(project)`,
`stop`, `seen`, `list` and `other(name, handle)`, another person on a connection of their own, do
what they say; `answer(project, block, value, handle, {note, toolUseId})` records a person's answer
as the chat's brain does, while a turn of the open chat is in flight, through the record's testing
route ([`projects.md`](projects.md)), the place *In the chat* goes to. The `chat` page object
(`tests/support/page-objects/chat-page.ts`) reads the tab, its dot, the transcript and the composer,
and `acted('send' | 'stop' | 'read')` waits for that write's success.
