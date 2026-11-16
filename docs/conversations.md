# The conversations

A conversation is a session outside Pilot talking to a project's brain through `pilot-projects`
([`mcp.md`](mcp.md#the-projects-surface)): a headless Claude Code session in the store
environment, as a project's chat is, which the caller's first message opens, briefed, and which
takes the caller's later messages one at a time. Several stand open on one project at once, beside
its chat and its jobs and never in their queue, from one calling session or from several. A
conversation is its calling environment's: no other environment's session reaches it. It closes by
its caller's end, after a quiet spell, and when its project finishes, reopens or is archived. The
project's people read it in the Conversations tab, where they may stop Pilot's answer but never
write. This page is the conversation as built: whose it is, its routes, the opening, a message,
the reply, the interrupt and the end, the close, the brief, the Conversations tab and its two
routes. The surface's tools and the long poll that waits for a reply are [`mcp.md`](mcp.md)'s;
what a conversation shares with a chat, its start in the store, the handbook's notice, the
follow-up turn and the Stop, is [`chats.md`](chats.md)'s, which also renders it in `chat.md`; the
start, the send and the relay are [`sessions.md`](sessions.md)'s, and the table is
[`record.md`](record.md)'s. The store's frame for it is PilotProjects' chat skill, its section
`## A conversation`, and `rules/placement.md`'s `## An environment by name`, which places the work
it asks for in the caller's environment.

| Service | Does |
|---|---|
| `ConversationService` (`conversation_service.py`) | the opening, a message, the caller's interrupt and end, and a person's Stop |
| `ConversationReadService` (`conversation_read_service.py`) | whose a conversation is, the caller's list, the reply to the latest message, and a project's conversations as its people read them |
| `ChatCloseService` (`chat_close_service.py`) | the close, a chat's and a conversation's ([`chats.md`](chats.md#the-close)) |
| `BriefService` (`brief_service.py`) | the brief, `BriefService.conversation` |
| `CallerEnvironmentService` (`caller_environment_service.py`) | the caller's Environment row ([`controller.md`](controller.md)) |

All are in `backend/app/services/`.

## Whose it is

A Conversation is a Session of kind `conversation`, its row in `conversations`
([`record.md`](record.md)): its project, the Environment it was opened from and the name of the
session that opened it there, none where the call named none. Who opened it is its first Turn's
author, the service user the call came as. It answers to its opener alone
(`ConversationReadService.owned`, `opened`): a call about it from another service user or from
another environment, one that names no environment among them, is answered as for an id that never
was, `404` "Conversation <id> was not found", and a list holds none of it. The session's name is
kept and shown, never checked, so a later session of the same environment finds its predecessor's
conversations and talks on in them.

## The routes

`backend/app/api/conversations.py`, behind the API's `editor` gate, is the service user's alone,
its second write beside starting a project ([`sign-in.md`](sign-in.md#the-service-user)): a person
is a `409`, "Cannot … because you do not call as a service user". Each reads where the call came
from in its two headers, `X-Pilot-Environment`, the environment's id, and `X-Pilot-Session`, the
session's name there, an empty one none, as `pilot-projects` forwards them
([`mcp.md`](mcp.md#the-projects-surface)). A conversation is answered as `{id, project_id,
environment, session, opened_at, closed_at, close_cause, turns, in_flight}`: the caller's
environment's id and session's name, `opened_at` its Session's creation, `turns` the count of its
Turns, and `in_flight` whether one is in flight, when it takes no message.

| Route | Does |
|---|---|
| `POST /api/conversations` `{address, words}` | opens one on the project at the address, `201` the conversation, its first turn in flight |
| `GET /api/conversations[?address=]` | `{conversations}`: those the calling environment opened, open and closed, in the order they opened, of the one project an address names where it names one |
| `GET /api/conversations/<id>` | the conversation |
| `POST /api/conversations/<id>/messages` `{words}` | its next message, `201` `{conversation, seq, error}`, the Turn's number in it and the error of a send the controller failed |
| `GET /api/conversations/<id>/response` | the reply to the latest message as it stands, `{turn, state, text}` (below) |
| `POST /api/conversations/<id>/interrupt` | stops the turn in flight, the conversation kept |
| `POST /api/conversations/<id>/end` | closes it, `ended` |

An opening is a `400` with no words, no address or no environment header, a `404` for no project
at the address, and a `409` for a draft ("its project is a draft"), an archived project ("its
project is archived"), while the store's update is unlifted ("Pilot is updating",
[`store-update.md`](store-update.md)), and with no controller or no store environment configured.
A list is a `400` for an empty address and a `404` for no project at it. A message is a `400`
with no words and a `409` for a closed conversation ("its conversation is closed"), an archived
project's, while the store's update is unlifted, and while a Turn of it is in flight ("a turn of
its conversation is in flight"). None of them waits: the reply's route answers at once, and the
wait for a turn's end is the MCP process's ([`mcp.md`](mcp.md#a-conversation)).

## The opening

`ConversationService.open` refuses a draft, whose definition chat alone writes its `project.md`,
and an archived project; a finished project takes one, which reads only, as its chat does. It asks
the controller for the caller's environment before it takes any lock
(`CallerEnvironmentService.reported`), then, under the project's row locked as a change of its
standing locks it ([`projects.md`](projects.md)), writes the Environment's row where Pilot has none
(`row`): from the controller's report, else named by its id, so that no opening is refused for
where it came from (D235); the fleet stream keeps the row current as it does every row
([`controller.md`](controller.md)). Then it writes a Session of kind `conversation`, in no
environment until its start takes the store, its `cwd` the store repo's root and its model and
effort `BRAIN_MODEL` and `BRAIN_REASONING_EFFORT`, as a chat's ([`chats.md`](chats.md)); the
Conversation; and Turn 1, the brief (below) followed by the words, its author the service user,
its `words` the words alone. The Session starts through the gate as a chat's does
(`SessionStartService.start_brain`): held while the store's update is unlifted and while the
controller is unreachable, never for the pause or a usage halt, taking no slot and waiting behind
no job. Its start, its box and its surface are a chat's: in the store, boxed to the project's
folder and handed `pilot-store`, a finished project's reading only with no surface
([`chats.md`](chats.md#the-start-in-the-store)). An opening records `send`, which moves `chat.md`,
and its Session's moves raise `ProjectChanged` ([`engine.md`](engine.md)).

## A message

`ConversationService.send` takes the caller's next message under the conversation's Session's
lock, after its project's row held shared: refused for a closed conversation, an archived
project's, and while a Turn of it is in flight, its start held or under way, a turn running, or a
stopped one not yet ended, read from the record with no controller call. Nothing is queued. The
message is a Turn of the conversation, its author the service user, the words verbatim, after the
server's handbook notice where the handbook changed since its previous Turn, as a chat's
([`chats.md`](chats.md#before-the-words)); a later message carries no heading, its author never
changing. It goes through the relay's send, which creates the controller session again where it is
gone ([`sessions.md`](sessions.md)). A conversation whose start failed, or was stopped before its
brief went out, starts afresh with the next message, briefed, in the same conversation. A send the
controller failed is written and ended with its `error`, which the route answers with its `201`
and the `send` tool raises.

A turn that ends with a save of its own still held gets the server's follow-up turn, as a chat's
([`chats.md`](chats.md#the-follow-up-turn)): it has no author, and a message while it runs is
refused as one while any Turn is in flight. A turn that dies at the quota wall gets no nudge, as a
chat's does ([`usage.md`](usage.md)).

## The reply

`ConversationReadService.reply`, the `response` route's, reads Pilot's reply to the caller's
latest message as it stands, from that message's `send` record on, the server's follow-up turns
after it among them:

- `state` is `running` while a Turn is in flight or the last has not ended; else `error` where a
  Turn since the message has an `error` or its start failed, its `start-failed` record read since
  the message; `interrupted` where the last Turn ended on an interrupted result or on none,
  stopped unsent or its environment stopped under it; and `done` otherwise;
- `turn` is the caller's latest Turn's `seq`, the number the message's route answered, and none on
  `running`;
- `text` is every main-thread text Pilot wrote since the message, in order, joined by
  `"\n\n---\n\n"`, KubeCoder's separator, an error's reason its last section, and none where
  there is none; on `running` it holds the texts so far.

A conversation whose turn has ended answers the same reply until the next message, and a closed
one its last.

## The interrupt and the end

**The interrupt** (`ConversationService.interrupt`) stops the Turn in flight by the service user,
as a person's Stop stops a chat's (`SessionStartService.stop_chat`, [`chats.md`](chats.md)), and
keeps the conversation open. After a running turn's interrupt a message is refused until the relay
has ended that turn, then goes to its thread; after one of a start held or under way, the next
message starts it afresh, briefed.

**The end** (`ConversationService.end`, `ChatCloseService.end`) stops a Turn in flight the same
way and closes the conversation, `ended`. It calls no controller: the Session stays `idle` or
`stopped`, and the worker reaps the idle controller session.

Neither refuses for what it finds: an interrupt with no Turn in flight, a closed conversation's
included, and the end of a closed conversation change nothing, as KubeCoder's interrupt of an idle
session and its end of one gone. Both lock the project's row shared, then the Session's, and
answer the conversation as it then stands.

## The close

A conversation closes once, `closed_at` and `close_cause_code` written together, and takes no
message after it:

- **`ended`**: its caller's end (above);
- **`timeout`**: the timer `chat-close` closes it as it closes a project chat, `CHAT_CLOSE_TIMEOUT`
  after its last turn ended with no Turn in flight, its controller session ended first and its
  Session `ended` ([`chats.md`](chats.md#the-close));
- **`finished`**, **`reopened`**, **`archived`**: Finish, Reopen and Archive close every open
  conversation of the project in the transition's transaction, after `stop_project` stopped its
  Sessions, which locks every open conversation's Session first, so that no message's send comes
  between ([`sessions.md`](sessions.md)). They call no controller, as for a chat.

Its close writes the chat's `server` record, `{"type": "closed", "cause": <cause>}`, and the end
of its stopped turn writes it where one is in flight, so that the record is the Session's last.
The close moves `chat.md` and raises `ProjectChanged`. The store's update stops a running or
starting conversation by Pilot and leaves it open, and holds a conversation's start until its lift,
as a chat's ([`store-update.md`](store-update.md)).

## The brief

The brief is Turn 1 of a conversation (`BriefService.conversation`), Markdown, a chat's brief under
a kind line of its own (`CONVERSATION_KIND_LINE`), which names its caller as `chat.md`'s heading
does (`caller_named` in `backend/app/engine/views.py`): the environment's name, then in brackets its
id and `, session <name>`, the latter left out where the call named none.

```
/chat

Pilot's brief · a conversation with a session in RecipeBox-2 (example-recipebox-1a2b3c, session ui-sweep-triage) · project "Soup club" · /work/Projects/soup-club · 2026-10-26T09:30:15Z

Auto pilot: off — the granted column asks for this session (rules/grants.md).

The message, from the session in RecipeBox-2:
How is the fix going?
```

In an open project it has the chat's switch, its pause line while the project is paused, and its
open plan notes and deferrals without a home; in a finished one, the chat's finish line in place of
them ([`chats.md`](chats.md#the-brief)). It has no earlier-chats line: a caller reads its own
conversations alone. The caller's words close it under `The message, from the session in
<environment name>:`.

## The Conversations tab

A project that has had a conversation has a Conversations tab (D234): in the side panel after Chat,
Chat, Conversations, Documents ([`documents.md`](documents.md)), and on a phone after Chat among
the tabs at the bottom, Timeline, Chat, Conversations, Plan, Documents
([`projects.md`](projects.md)). A draft has none, nor a project that has had none.

`ProjectConversations` (`frontend/src/components/chat/project-conversations.tsx`), from the
project's list (`useProjectConversations`, `hooks/use-conversations.ts`), read again on
`project_changed` ([`timeline.md`](timeline.md)), shows the project's conversations read-only, in
the order they opened, each under a head: the environment's name, linked as an environment is
(`EnvironmentLink`, [`ui.md`](ui.md)), ` · <session>` where the call named one, "Open" or "Closed",
and Stop while Pilot answers in it. The head stays at the top of the view while its conversation
scrolls under it, so that whose it is and its Stop stay in reach. Under it the transcript streams
as a chat's (`ChatSection`, [`chats.md`](chats.md#the-chat-tab)): the caller's messages on the
right under the environment's name, Pilot's replies with their steps, the working cue and the
phantom, and "Conversation closed · <time>" where it closed.

It shows from the earliest conversation still open, or with none open the latest; "Load previous"
loads the one before above what is in view and keeps the line at the top of the view in its place
(`useKeptLine`, `hooks/use-kept-line.ts`, the Chat tab's too). How far back it shows is the tab's
own, not kept across a change of tab. A conversation that opens while it shows comes in below.
Nothing stands in it while the list's read is under way, and "The conversations did not load."
while its latest read failed. It has no composer and no unread dot: every message is the calling
session's, and a person's read is kept per chat alone. The Chat tab, its composer, its Stop and its
dot read the chats alone.

Whether the tab shows is `useHadConversations`, unknown until the list is read: a panel left on
Conversations shows it while the list is read, never the Chat tab first, which would mark the chat
seen (`usePanel`, `hooks/use-panel.ts`). The panel keeps the tab in the browser as it keeps the
others ([`ui.md`](ui.md)).

**`GET /api/projects/<id>/conversations`** answers `{conversations}`, each `{id, environment: {id,
name}, session, opened_at, closed_at, close_cause, answering}`, whoever opened it, in the order
they opened; `answering` is whether Pilot answers in it, its Session `held`, `starting` or
`running`, the states a Stop ends. **`POST /api/projects/<id>/conversations/<conversation
id>/stop`**, no body, is a chat's Stop of Pilot's answer in it, by the signed-in person
(`ConversationService.stop`, which locks the project's row before `stop_chat` locks the
Session's), and answers the conversation, `answering` false; it is a `404` for an unknown id or
another project's, and a `409` for a caller who has not chosen a handle and where Pilot is not
answering, in the chat's Stop's words. Both are in `backend/app/api/project_conversations.py`,
behind the API's `editor` gate. A conversation's records are its Session's, read and streamed by
the session routes by its id ([`sessions.md`](sessions.md)).

## Testing it

The backend's tests are `tests/services/test_conversation_service.py` (the opening, the caller's
row, several at once, the refusals, the later messages, the notice, the store's update, the
interrupt, the end, the transitions and a message meeting one, the transcript, a person's Stop),
`tests/services/test_conversation_read_service.py` (whose it is, the reply, the project's list),
`TestConversation` in `test_brief_service.py`, `TestCloseConversations` in
`test_chat_close_service.py`, `tests/api/test_conversations.py` and
`tests/api/test_project_conversations.py`, `tests/models/test_conversation.py` and the
revision's test, `tests/migrations/test_0043_conversations.py`; the tools are in
`tests/pilot_mcp/` ([`mcp.md`](mcp.md#testing-it)). `tests/support/chats.py`'s
`open_conversation(opener=)` writes a conversation with its first Turn, and `close_conversation`
closes one.

The browser's spec is `frontend/tests/chat/conversations-tab.spec.ts`. The `conversations`
fixture (`frontend/tests/support/conversations.ts`) gives a spec a calling session:
`conversations.caller(<environment name>, <session>)`, a service user of its own on a connection of
its own, calling from an environment the record names, which opens a conversation as the surface
does (`start`), sends its next message (`send`) and ends it (`end`); the conversation's session
runs in the store's fake environment as a chat's does, and the spec plays its turns through
`controller` ([`chats.md`](chats.md#testing-it)). `list` and `stop` are the signed-in person's.
The `conversationsTab` page object (`tests/support/page-objects/conversations-page.ts`) reads the
tab, a conversation's head and transcript, and waits for the list's read, a conversation's stream
and a Stop's success.
