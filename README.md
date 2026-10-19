# Pilot

Pilot is the project manager: it owns multi-step work front to end across the KubeCoder fleet, and
the operator decides and does only what their hands must. This repository is the app. Its specs
and slices are in `pvginkel/PilotAppSpecs`, its deploy chart in `pvginkel/PilotDeploy`, and the
store environment's repository in `pvginkel/PilotProjects`.

**Status**: version 1 is being built. Its first screens are in, in the mockup's look, with a
PWA's manifest and service worker ([`docs/ui.md`](docs/ui.md)): the handle a person chooses at
their first sign-in ([`docs/sign-in.md`](docs/sign-in.md)), the project list, and a project's head
with its plan, its members, the auto pilot switch, and Finish, Reopen, Archive and Bring back
([`docs/projects.md`](docs/projects.md)). Nothing creates a project yet, so production's list is
empty. Beneath the screens are the record's schema and the engine behind it: the block DSL, the
parse gate and the merge by ownership, the record's own writes, and the rendered `timeline.json`,
`reference.json` and `plan.json` ([`docs/engine.md`](docs/engine.md)); and the sync that keeps the
store environment's tree in step with the record: the `/api/sync` routes and `pilot-sync`, the Go
sidecar ([`docs/sync.md`](docs/sync.md)), which production does not switch on yet; and the
server's jobs on the KubeCoder controller: the environments Pilot starts and stops, and the sessions
it runs there, recorded and streamed live ([`docs/sessions.md`](docs/sessions.md)). Production
follows the fleet's stream and starts nothing yet. It is built on the ModernAppTemplate stack
(Flask on PostgreSQL, React + Vite, Playwright), which CI builds and Argo CD deploys to production
at `https://pilot.ginbov.nl` ([`docs/deployment.md`](docs/deployment.md)).
