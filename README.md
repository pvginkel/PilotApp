# Pilot

Pilot is the project manager: it owns multi-step work front to end across the KubeCoder fleet, and
the operator decides and does only what their hands must. This repository is the app. Its specs
and slices are in `pvginkel/PilotAppSpecs`, its deploy chart in `pvginkel/PilotDeploy`, and the
store environment's repository in `pvginkel/PilotProjects`.

**Status**: version 1 is being built. Its first screens are in, in the mockup's look, with a PWA's
manifest and service worker ([`docs/ui.md`](docs/ui.md)): the handle a person chooses at their first
sign-in ([`docs/sign-in.md`](docs/sign-in.md)), the project list, and a project's head with its
plan, its members, the auto pilot switch, which offers to answer the confirmations it would take as
it turns on, and Finish, Reopen, Archive and Bring back, a finish followed by the question whether
to archive ([`docs/projects.md`](docs/projects.md)); under the head, its timeline, where every item
that asks one thing is answered in place and a document inline or from its card, its answers sent at
once, with Undo, urgent banners, the auto pilot mark, a badge per tab and a URL per item, and which
every open browser follows live ([`docs/timeline.md`](docs/timeline.md)); its work items, each a
session Pilot runs, live on the timeline with its one current line, Stop and Resume, and its session
log, and Pilot's own background jobs among them, one at a time per project, each a fresh session of
the brain's: the setup, the pre-ruling pass after every worker's turn, which may ask the worker's
writer or claim an action for a work item of Pilot's, and the plan's next step after every item of
Pilot's a person closes, with Retry on one that failed ([`docs/work.md`](docs/work.md)); each
project's status as one icon on its tab, which pauses it, and the gold bar over the list while the
controller does not answer; and the overlay that opens a document, an attachment or the handbook,
beside the side panel with the project's chat and its documents
([`docs/documents.md`](docs/documents.md)). A project starts from the plus beside the list, as a
draft: its definition chat stands in the timeline's place while Pilot writes the draft,
`project.md`, in the panel's Draft tab, its asks answered in place, and Create project opens it,
hands it to Pilot's setup, the brain's first background job, and pauses it, so that its work waits
for a person's resume ([`docs/projects.md`](docs/projects.md), [`docs/work.md`](docs/work.md)).
Beneath the screens are the record's schema and the engine behind it: the block DSL, the parse gate
and the merge by ownership, the record's own writes, and the rendered `timeline.json`,
`reference.json` and `plan.json` ([`docs/engine.md`](docs/engine.md)); and the sync that keeps the
store environment's tree in step with the record: the `/api/sync` routes and `pilot-sync`, the Go
sidecar, in each stage's store environment, with the hooks that hold a project's write lock around
each of the brain's edits, so that each save is its session's, and tell it what the record made of
them ([`docs/sync.md`](docs/sync.md)); and the server's jobs on the KubeCoder controller: the
environments of its own Pilot creates from a work item's repository, resets before each fresh start,
stops and deletes, and the sessions it runs there through the gate every start passes, recorded and
streamed live ([`docs/sessions.md`](docs/sessions.md)); and Pilot's MCP server, handed to every
session it creates ([`docs/mcp.md`](docs/mcp.md)), through which a work item's session registers the
documents it wrote and attaches what backs them: each read onto the timeline once the run ends,
written back to its file once answered, and the conversation continued as a new work item once none
is open, or resumed first by a clarification run that puts the pre-ruling pass's questions to the
writer ([`docs/round-trip.md`](docs/round-trip.md)); and the project's chat, in the side panel's
Chat tab, which every member watches live, Discuss quoting into it anything the project shows: a
person's message starts the brain's session in the store, sandboxed and briefed, which takes the
messages after it until it closes, after 55 quiet minutes or at Create project, Finish, Reopen and
Archive, and acts on the record through its own tools, each call's effect shown where it ran, an
answer given there reached from its block by *In the chat*, its chats projected for it as `chat.md`
([`docs/chats.md`](docs/chats.md)); and the phone's notifications through the estate's bridge, under
the token each person pastes on their profile: one standing notification per member and project,
which reads its state and rises when something comes to wait on them, and an alarm per condition
that holds all work, beside the profile's switch that turns the alarms off
([`docs/notifications.md`](docs/notifications.md)). The brain's own repository holds its map, its
rules, its four skills, and `pilot.py`, the script it edits a project's folder with, on the block
DSL's own package ([`docs/block-dsl.md`](docs/block-dsl.md)); its four skills' bodies are written:
the chat's, the create skill's, the pre-ruling pass and the plan skill's modes. Each stage follows
its own KubeCoder's fleet stream, and the dev stage's testing routes make projects there too. It is
built on the ModernAppTemplate stack (Flask on PostgreSQL, React + Vite, Playwright), which CI
builds and Argo CD deploys: every green build to the dev stage at `https://pilot-dev.home`, and
production at `https://pilot.ginbov.nl` when the operator promotes it
([`docs/deployment.md`](docs/deployment.md)).
