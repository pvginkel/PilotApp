# Pilot

Pilot is the project manager: it owns multi-step work front to end across the KubeCoder fleet, and
the operator decides and does only what their hands must. This repository is the app. Its specs
and slices are in `pvginkel/PilotAppSpecs`, its deploy chart in `pvginkel/PilotDeploy`, and the
store environment's repository in `pvginkel/PilotProjects`.

**Status**: version 1 is being built. Its first screens are in, in the mockup's look, with a PWA's
manifest and service worker ([`docs/ui.md`](docs/ui.md)): the handle a person chooses at their first
sign-in ([`docs/sign-in.md`](docs/sign-in.md)), the project list, and a project's head with its
plan, its members, the auto pilot switch, and Finish, Reopen, Archive and Bring back
([`docs/projects.md`](docs/projects.md)); under the head, its timeline, where every item that asks
one thing is answered in place and a document inline or from its card, its answers sent at once,
with Undo, urgent banners, a badge per tab and a URL per item, and which every open browser follows
live ([`docs/timeline.md`](docs/timeline.md)); its work items, each a session Pilot runs, live on
the timeline with its one current line, Stop and Resume, and its session log
([`docs/work.md`](docs/work.md)); each project's status as one icon on its tab, which pauses it, and
the gold bar over the list while the controller does not answer; and the overlay that opens a
document, an attachment or the handbook, beside the side panel with the project's documents
([`docs/documents.md`](docs/documents.md)). Nothing in the app creates a project or places a first
work item yet, so production's list is empty. Beneath the screens are the record's schema and the engine
behind it: the block DSL, the parse gate and the merge by ownership, the record's own writes,
and the rendered `timeline.json`, `reference.json` and `plan.json`
([`docs/engine.md`](docs/engine.md)); and the sync that keeps the store environment's tree in step
with the record: the `/api/sync` routes and `pilot-sync`, the Go sidecar, in each stage's store
environment, with the hook that tells the brain what the record made of each edit
([`docs/sync.md`](docs/sync.md)); and the server's jobs on the KubeCoder controller: the
environments of its own Pilot creates from a work item's repository, resets before each fresh
start, stops and deletes, and the sessions it runs there through the gate every start passes,
recorded and streamed live ([`docs/sessions.md`](docs/sessions.md)); and Pilot's MCP server,
handed to every session it creates ([`docs/mcp.md`](docs/mcp.md)), through which a work item's
session registers the documents it wrote and attaches what backs them: each read onto the timeline
once the run ends, written back to its file once answered, and the conversation continued as a new
work item once none is open ([`docs/round-trip.md`](docs/round-trip.md)). Each stage follows its
own KubeCoder's fleet stream; only the dev stage starts anything, through its testing routes. It
is built on the ModernAppTemplate stack (Flask on PostgreSQL, React + Vite, Playwright), which CI
builds and Argo CD deploys: every green build to the dev stage at
`https://pilot-dev.home`, and production at `https://pilot.ginbov.nl` when the operator promotes it
([`docs/deployment.md`](docs/deployment.md)).
