# The chats

A project's chat is how a person reaches its brain: a headless Claude Code session in the store
environment, which a message starts, briefed, and which takes the messages after it while it is
open. A chat closes after a quiet spell, or when its project finishes or reopens, and the next
message starts the project's next chat. This page is the chat as built: a message and the way it
goes, the chat's start in the store and its brief, the handbook's notice, the server's follow-up
turn, the close, the chats as a person reads them, and `chat.md`, the chats as the brain reads
them. The chat's screens are still to come; here a chat is reached through the API. What the
brain may do through its tools is [`mcp.md`](mcp.md)'s, the start, the send and the relay that
carry a chat's turns are [`sessions.md`](sessions.md)'s, and the tables are
[`record.md`](record.md)'s. The skill the brief opens with is PilotProjects'
`.claude/skills/chat/SKILL.md`.

| Service | Does |
|---|---|
| `ChatService` (`chat_service.py`) | a person's message: sent to the project's open chat, or the chat started with it |
| `BriefService` (`brief_service.py`) | the chat's brief, the follow-up turn, and the server's lines after a worker's brief ([`mcp.md`](mcp.md)) |
| `ChatCloseService` (`chat_close_service.py`) | a chat's close: at Finish and Reopen, and on the timer `chat-close` |
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
came, quote tags and all, and its `message` what goes to the session, the words or what the server
puts before them (below). Its `send` record stands in its place among the chat's records. Its quote
is the first quote tag in the words, `<quoted_item id="<item id>">…</quoted_item id="<item id>">` or
`<quoted_block id="<item id>/<local id>">…</quoted_block id="…">`, the closing tag repeating the
id: the Item or the Block of the project it names, and none for a tag that names neither, an
unknown or malformed id or another project's. The brain resolves a quote itself, from the tree; the
server inlines nothing.

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
- **Failed, or stopped before its brief went out**, as an Archive during its start leaves it: the
  start is made again in the same Chat, in a headless session of its own, its controller session
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
brain session. Its brief says the project is finished. **An archived project's** takes no message,
neither the start of a chat nor a send to the one it left open.

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

## The handbook's notice

A message sent to the open chat after the project's handbook was published, later than the chat's
latest Turn was sent, has the server's notice before the words, a blank line between (D052):

```
<store_notification>
The handbook (handbook.md) changed since your last turn.
</store_notification>
```

The Turn's `words`, and so its `send` record, are the words alone. The notice is counted once the
send went out, `pilot_chat_handbook_changed_total{project}`, by the project's id. A start's Turn
carries the brief instead, and the skill reads the handbook then anyway. The store's saves name no
session ([`sync.md`](sync.md)), so a handbook the chat edited itself counts as a change too.

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

## The close

A chat closes for one of three causes, `Chat.closed_at` and `close_cause_code` written together, and
is never sent to again: the next message starts a chat of its own.

- **`timeout`**: the timer `chat-close`, on each round of the scheduler ([`jobs.md`](jobs.md)),
  closes every open project chat whose Session's last turn ended `CHAT_CLOSE_TIMEOUT` ago or more,
  with no Turn in flight. Each in a transaction of its own under its Session's lock, skipping one
  another transaction holds, a message's send among them: its controller session, where it has one,
  ended first, a `404` or a `409` counting as ended, and its Session `ended`, then the chat closed.
  A controller that does not answer leaves the chat open for the next round. An archived project's
  open chat closes so too. A definition chat never closes by timeout.
- **`finished`**: Finish closes the project's open chat in its transaction, after it stopped the
  project's Sessions, a turn the chat had running among them ([`projects.md`](projects.md)).
- **`reopened`**: Reopen does the same for a chat opened while the project was finished, and stops
  that chat's running turn first, as Finish stops one (D068), so that the close stays the chat's
  last record and the next message starts a chat that writes. An idle chat needs no stop: a closed
  chat is never sent to.

A chat's box is fixed at its create, so a close at Finish and at Reopen keeps every chat in the
state it was opened under. Neither calls the controller: the chat keeps its controller session,
idle or interrupted, and nothing sends to it again.

The close's `server` record, `{"type": "closed", "cause": <cause>}`, is the chat's last. The close
writes it when no Turn of the chat is in flight, and otherwise the end of that Turn does, as the
relay records the turn a stop interrupted, so its `at` can be later than `closed_at`. A chat's
open and its close move `chat.md` and raise `ProjectChanged` ([`engine.md`](engine.md)).

## The chats read

**`GET /api/projects/<id>/chats`** answers `{chats, read_at, unread}`: the project's chats, the
definition chat first where one exists, then the project's chats in the order they opened, each
`{id, kind, opened_at, closed_at, close_cause}`, open or closed with its cause; and the caller's
place in them, `read_at` null for a caller with no handle. A chat's records are its Session's, read
and followed as any Session's are ([`sessions.md`](sessions.md)).

**`PUT /api/projects/<id>/chat/read`**, no body, says the signed-in person has seen the project's
chat to its end now, on whichever device: their Chat Read, one per person and project, written at
the transaction's start, the records' own clock. It answers `{read_at, unread}`, and is a `409` for
a caller who has not chosen a handle. `unread` is whether Pilot replied after `read_at`, or at all
while there is none: a reply is a main-thread `assistant` record with text of one of the project's
chats. The place is the project's, not a chat's, so the next chat keeps it. A Chat Read's write
emits nothing live; a reply reaches the browsers through its turn's end, whose state move raises
`ProjectChanged`. Both routes are behind the API's `editor` gate, and `404` for an unknown project.

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
start in `test_session_start_service.py`, its follow-up turn in `test_relay_service.py`),
`backend/tests/api/test_chats.py` and `backend/tests/engine/test_views.py` (`TestChatView`);
`backend/tests/support/chats.py` writes a chat's records. On the fake controller
([`controller.md`](controller.md)), a boxed create needs its cwd and each folder it writes on the
environment's tree, so a chat's start in the store needs a file under `/work/PilotProjects` and one
under the project's folder (`put_file`), or its create is `422`.
